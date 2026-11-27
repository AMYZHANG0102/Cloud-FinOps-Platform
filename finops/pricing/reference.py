"""Load documented supplementary pricing without external API calls."""

import json
import re

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from finops.config import PROJECT_ROOT
from finops.pricing.client import validate_region

from finops.pricing.models import (
    PriceDimension,
    PricingModel,
    PricingRecord,
    PricingSource,
)

from finops.pricing.products import (
    _reject_duplicate_keys,
    _reject_nonfinite_constant,
)


DEFAULT_REFERENCE_PATH = (
    PROJECT_ROOT
    / "data"
    / "pricing"
    / "reference_rates.json"
)


class ReferenceCatalogueError(ValueError):
    """Invalid or unavailable supplementary pricing catalogue."""


@dataclass(frozen=True, slots=True)
class ReferenceRate:
    """A documented reference record and its resource classification."""

    reference_id: str
    resource_type: str
    record: PricingRecord
    verified_on: date
    limitations: tuple[str, ...]


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text.")

    return value


def _decimal(value):
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"[0-9]+(?:\.[0-9]+)?",
            value,
            flags=re.ASCII,
        ) is None
    ):
        raise ValueError("Invalid reference decimal string.")

    return Decimal(value)


def _source_url(value):
    value = _text(value, "source_reference")
    parts = urlsplit(value)

    if (
        parts.scheme != "https"
        or parts.netloc not in (
            "aws.amazon.com",
            "docs.aws.amazon.com",
        )
        or not parts.path
    ):
        raise ValueError("Invalid official AWS source URL.")

    return value


def _parse_rate(item, version, verified_on):

    reference_id = _text(
        item["reference_id"],
        "reference_id",
    )

    resource_type = _text(
        item["resource_type"],
        "resource_type",
    )

    region = validate_region(item["region"])

    if item["currency"] != "USD":
        raise ValueError("Only USD reference rates are supported.")

    if item["pricing_model"] != "ON_DEMAND":
        raise ValueError("Unsupported reference pricing model.")

    raw_limitations = item["limitations"]

    if not isinstance(raw_limitations, list) or not raw_limitations:
        raise ValueError("Reference limitations must be documented.")

    limitations = tuple(
        _text(value, "limitation")
        for value in raw_limitations
    )

    attributes = item["attributes"]

    if not isinstance(attributes, dict) or not attributes:
        raise ValueError("Configuration attributes are required.")

    for key, value in attributes.items():
        _text(key, "attribute name")
        _text(value, "attribute value")

    raw_end = item["end_range"]

    dimension = PriceDimension(
        rate_code=reference_id,
        unit=item["unit"],
        currency=item["currency"],
        unit_price=_decimal(item["unit_price"]),
        begin_range=_decimal(item["begin_range"]),
        end_range=(
            None if raw_end is None else _decimal(raw_end)
        ),
        cost_component=item["cost_component"],
        description="Documented AWS reference rate",
    )

    effective_date = item["effective_date"]

    if effective_date is not None:
        effective_date = datetime.fromisoformat(effective_date)

    # Source verification is recorded with calendar-day precision.
    # Midnight UTC is its domain-model representation, not an
    # asserted exact time at which the source was checked.

    verification_date = datetime.combine(
        verified_on,
        time.min,
        tzinfo=timezone.utc,
    )

    record = PricingRecord(
        service_code=item["service_code"],
        sku=reference_id,
        product_family=item["product_family"],
        region=region,
        attributes=attributes,
        pricing_model=PricingModel.ON_DEMAND,
        offer_term_code="REFERENCE_ON_DEMAND",
        dimensions=(dimension,),
        source=PricingSource.REFERENCE_DATA,
        source_reference=_source_url(
            item["source_reference"]
        ),
        catalogue_version=version,
        effective_date=effective_date,
        verified_at=verification_date,
        assumptions=limitations + (
            "Source verification has calendar-day precision.",
            "Local reference identifier; not an AWS-issued SKU.",
        ),
    )

    return ReferenceRate(
        reference_id=reference_id,
        resource_type=resource_type,
        record=record,
        verified_on=verified_on,
        limitations=limitations,
    )


def load_reference_rates(
    path: Path | None = None,
) -> tuple[ReferenceRate, ...]:
    """Load and validate the entire local reference catalogue."""

    path = (
        DEFAULT_REFERENCE_PATH
        if path is None
        else Path(path)
    )

    try:
        with path.open("r", encoding="utf-8") as stream:
            document = json.load(
                stream,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite_constant,
            )

        if (
            not isinstance(document, dict)
            or type(document.get("schema_version")) is not int
            or document["schema_version"] != 1
        ):
            raise ValueError("Unsupported reference schema.")

        version = _text(
            document["catalogue_version"],
            "catalogue_version",
        )

        verified_on = date.fromisoformat(
            document["verified_on"]
        )

        items = document["rates"]

        if not isinstance(items, list) or not items:
            raise ValueError("Missing reference rates.")

        rates = []
        seen = set()

        for item in items:

            if not isinstance(item, dict):
                raise ValueError("Invalid reference entry.")

            rate = _parse_rate(
                item,
                version,
                verified_on,
            )

            if rate.reference_id in seen:
                raise ValueError("Duplicate reference identifier.")

            seen.add(rate.reference_id)
            rates.append(rate)

        return tuple(rates)

    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
    ) as error:
        raise ReferenceCatalogueError(
            f"Reference catalogue validation failed: {error}"
        ) from error
