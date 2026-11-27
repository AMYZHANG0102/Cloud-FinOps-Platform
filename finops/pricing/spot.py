"""Retrieve and persist observed Floci EC2 Spot prices.

Spot observations are not guaranteed future prices.
They remain separate from On-Demand catalogue records.
"""

import json
import os
import tempfile

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock

from botocore.exceptions import BotoCoreError, ClientError

from finops.config import RuntimeSettings

from finops.pricing.client import (
    FlociClientSettings,
    UnsafeEndpointError,
    create_ec2_client,
    validate_region,
)

from finops.pricing.models import SpotPriceObservation

from finops.pricing.products import (
    _reject_duplicate_keys,
    _reject_nonfinite_constant,
)


LOOKBACK_DAYS = 7
MAX_PAGES = 1000
CACHE_SCHEMA_VERSION = 1

_LOCK = RLock()


class SpotPricingError(RuntimeError):

    def __init__(self, code, message):
        self.code = code
        super().__init__(f"Spot pricing [{code}]: {message}")


def _utc(value):

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware datetime required.")

    return value.astimezone(timezone.utc)


def _text(value):

    if not isinstance(value, str) or not value.strip():
        raise ValueError("Nonempty text required.")

    return value


@dataclass(frozen=True, slots=True)
class SpotQuery:

    instance_type: str
    region: str = "us-east-1"
    product_description: str = "Linux/UNIX"
    availability_zone: str | None = None

    def __post_init__(self):

        validate_region(self.region)

        _text(self.instance_type)
        _text(self.product_description)

        if self.availability_zone is not None:
            _text(self.availability_zone)


@dataclass(frozen=True, slots=True)
class SpotHistory:

    query: SpotQuery
    start_time: datetime
    end_time: datetime
    retrieved_at: datetime
    observations: tuple[SpotPriceObservation, ...]
    page_count: int

    def latest_for_zone(self, availability_zone):

        _text(availability_zone)

        matches = [
            item for item in self.observations
            if item.availability_zone == availability_zone
        ]

        return max(
            matches,
            key=lambda item: item.observed_at,
            default=None,
        )

    @property
    def latest_by_zone(self):

        zones = sorted({
            item.availability_zone
            for item in self.observations
        })

        return tuple(
            self.latest_for_zone(zone)
            for zone in zones
        )


@dataclass(frozen=True, slots=True)
class CachedSpotHistory:

    history: SpotHistory
    checked_at: datetime
    ttl_seconds: int

    @property
    def is_fresh(self):

        age = (
            self.checked_at - self.history.retrieved_at
        ).total_seconds()

        return 0 <= age < self.ttl_seconds

    @property
    def is_stale(self):
        return not self.is_fresh


def _build_history(
    query, start, end, retrieved, pages, rows,
    *, ignore_earlier=False,
):

    start, end, retrieved = map(
        _utc, (start, end, retrieved)
    )

    if (
        end - start != timedelta(days=LOOKBACK_DAYS)
        or retrieved < end
        or type(pages) is not int
        or not 1 <= pages <= MAX_PAGES
        or not isinstance(rows, list)
    ):
        raise ValueError("Invalid history metadata.")

    observations = {}

    for row in rows:

        if not isinstance(row, dict):
            raise ValueError("Invalid Spot observation.")

        if (
            row["InstanceType"] != query.instance_type
            or row["ProductDescription"]
            != query.product_description
        ):
            raise ValueError("Spot configuration mismatch.")

        zone = _text(row["AvailabilityZone"])

        if (
            query.availability_zone is not None
            and zone != query.availability_zone
        ):
            raise ValueError("Availability Zone mismatch.")

        timestamp = _utc(row["Timestamp"])

        if timestamp > end:
            raise ValueError("Observation is after the query window.")

        raw_price = _text(row["SpotPrice"])

        try:
            price = Decimal(raw_price)
        except InvalidOperation as error:
            raise ValueError("Invalid Spot price.") from error

        observation = SpotPriceObservation(
            instance_type=query.instance_type,
            region=query.region,
            availability_zone=zone,
            product_description=query.product_description,
            unit_price=price,
            observed_at=timestamp,
            retrieved_at=retrieved,
            availability_zone_id=row.get(
                "AvailabilityZoneId"
            ),
        )

        # A source may include a price from before StartTime.
        # Only observations inside our requested window are stored.

        if timestamp < start:

            if ignore_earlier:
                continue

            raise ValueError("Observation precedes the stored window.")

        identity = (zone, timestamp)

        if identity in observations:

            if observations[identity] != observation:
                raise ValueError("Conflicting Spot observations.")

        else:
            observations[identity] = observation

    return SpotHistory(
        query=query,
        start_time=start,
        end_time=end,
        retrieved_at=retrieved,
        observations=tuple(
            observations[key]
            for key in sorted(observations)
        ),
        page_count=pages,
    )


def retrieve_spot_history(client, query, *, end_time=None):
    """Collect the complete requested history or raise an error."""

    if not isinstance(query, SpotQuery):
        raise TypeError("SpotQuery required.")

    end = _utc(
        datetime.now(timezone.utc)
        if end_time is None
        else end_time
    )

    # Align the request window to Floci's observed millisecond
    # timestamp precision before calculating its boundaries.
    # Preserve returned timestamps without modification.
    end = end.replace(
        microsecond=(end.microsecond // 1000) * 1000
    )

    start = end - timedelta(days=LOOKBACK_DAYS)

    parameters = {
        "InstanceTypes": [query.instance_type],
        "ProductDescriptions": [query.product_description],
        "StartTime": start,
        "EndTime": end,
        "MaxResults": 100,
    }

    if query.availability_zone is not None:
        parameters["AvailabilityZone"] = (
            query.availability_zone
        )

    rows = []
    seen_tokens = set()

    for page_number in range(1, MAX_PAGES + 1):

        try:
            response = client.describe_spot_price_history(
                **parameters
            )

        except ClientError as error:

            code = error.response.get(
                "Error", {}
            ).get("Code", "CLIENT_ERROR")

            raise SpotPricingError(
                code, "EC2 rejected the Spot history request."
            ) from error

        except (BotoCoreError, UnsafeEndpointError) as error:

            raise SpotPricingError(
                type(error).__name__,
                "Spot history retrieval failed.",
            ) from error

        if not isinstance(response, dict):

            raise SpotPricingError(
                "INVALID_RESPONSE", "Expected response object."
            )

        metadata = response.get("ResponseMetadata")
        items = response.get("SpotPriceHistory")

        if (
            not isinstance(metadata, dict)
            or metadata.get("HTTPStatusCode") != 200
            or not isinstance(items, list)
        ):
            raise SpotPricingError(
                "INVALID_RESPONSE", "Incomplete EC2 response."
            )

        rows.extend(items)

        token = response.get("NextToken")

        if token is None or token == "":

            try:
                return _build_history(
                    query, start, end,
                    datetime.now(timezone.utc),
                    page_number, rows,
                    ignore_earlier=True,
                )

            except (KeyError, TypeError, ValueError) as error:

                raise SpotPricingError(
                    "INVALID_OBSERVATION", str(error)
                ) from error

        if (
            not isinstance(token, str)
            or not token.strip()
            or token in seen_tokens
        ):
            raise SpotPricingError(
                "INVALID_PAGINATION",
                "Invalid or repeated continuation token.",
            )

        seen_tokens.add(token)
        parameters["NextToken"] = token

    raise SpotPricingError(
        "PAGE_LIMIT_EXCEEDED",
        "Spot history retrieval was not completed.",
    )


def _encode_history(history):

    return {
        "start_time": history.start_time.isoformat(),
        "end_time": history.end_time.isoformat(),
        "retrieved_at": history.retrieved_at.isoformat(),
        "page_count": history.page_count,
        "observations": [
            {
                "InstanceType": item.instance_type,
                "ProductDescription": item.product_description,
                "AvailabilityZone": item.availability_zone,
                "AvailabilityZoneId": item.availability_zone_id,
                "Timestamp": item.observed_at.isoformat(),
                "SpotPrice": format(item.unit_price, "f"),
            }
            for item in history.observations
        ],
    }


def _decode_history(query, document):

    rows = [
        {
            **row,
            "Timestamp": datetime.fromisoformat(
                row["Timestamp"]
            ),
        }
        for row in document["observations"]
    ]

    return _build_history(
        query,
        datetime.fromisoformat(document["start_time"]),
        datetime.fromisoformat(document["end_time"]),
        datetime.fromisoformat(document["retrieved_at"]),
        document["page_count"],
        rows,
    )


class SpotPricingService:

    def __init__(
        self,
        runtime_settings=None,
        client_settings=None,
    ):

        self.runtime = (
            RuntimeSettings()
            if runtime_settings is None
            else runtime_settings
        )

        self.client_settings = (
            FlociClientSettings()
            if client_settings is None
            else client_settings
        )

        self.path = self.runtime.spot_cache_path

    def _key(self, query):

        if not isinstance(query, SpotQuery):
            raise TypeError("SpotQuery required.")

        return json.dumps(
            {
                "endpoint": self.client_settings.endpoint_url,
                "lookback_days": LOOKBACK_DAYS,
                **asdict(query),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def _read(self):

        try:
            with self.path.open("r", encoding="utf-8") as stream:

                document = json.load(
                    stream,
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_nonfinite_constant,
                )

        except FileNotFoundError:

            return {
                "schema_version": CACHE_SCHEMA_VERSION,
                "entries": {},
            }

        except (OSError, ValueError) as error:

            raise SpotPricingError(
                "CACHE_READ_FAILED", "Invalid Spot cache."
            ) from error

        if (
            not isinstance(document, dict)
            or type(document.get("schema_version")) is not int
            or document["schema_version"] != CACHE_SCHEMA_VERSION
            or not isinstance(document.get("entries"), dict)
        ):
            raise SpotPricingError(
                "INVALID_CACHE_SCHEMA",
                "Unsupported Spot cache structure.",
            )

        return document

    def _write(self, document):

        temporary = None

        try:

            self.path.parent.mkdir(
                parents=True, exist_ok=True
            )

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".spot-",
                suffix=".tmp",
                delete=False,
            ) as stream:

                temporary = Path(stream.name)

                json.dump(
                    document, stream,
                    indent=2, allow_nan=False,
                )

                stream.flush()
                os.fsync(stream.fileno())

            os.replace(temporary, self.path)
            temporary = None

        except (OSError, ValueError, TypeError) as error:

            raise SpotPricingError(
                "CACHE_WRITE_FAILED",
                "Unable to save Spot history.",
            ) from error

        finally:

            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _validated_entry(self, query, document):

        try:
            return _decode_history(query, document)

        except (
            KeyError, TypeError, ValueError, AttributeError,
        ) as error:

            raise SpotPricingError(
                "INVALID_CACHE_ENTRY",
                "Stored Spot observations failed validation.",
            ) from error

    def load(self, query, *, now=None):

        key = self._key(query)

        checked = _utc(
            datetime.now(timezone.utc)
            if now is None
            else now
        )

        with _LOCK:

            document = self._read()

            if key not in document["entries"]:
                return None

            history = self._validated_entry(
                query, document["entries"][key]
            )

        return CachedSpotHistory(
            history=history,
            checked_at=checked,
            ttl_seconds=self.runtime.spot_ttl_seconds,
        )

    def refresh(self, query):
        """Retrieve live history and save only a complete result."""

        key = self._key(query)

        settings = replace(
            self.client_settings,
            region=query.region,
        )

        client = create_ec2_client(settings)

        try:
            history = retrieve_spot_history(client, query)

        finally:
            client.close()

        with _LOCK:

            document = self._read()

            if key in document["entries"]:

                previous = self._validated_entry(
                    query, document["entries"][key]
                )

                if history.retrieved_at < previous.retrieved_at:
                    raise SpotPricingError(
                        "OLDER_RETRIEVAL",
                        "Cannot replace newer Spot history.",
                    )

            document["entries"][key] = (
                _encode_history(history)
            )

            self._write(document)

        return history
