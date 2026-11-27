"""Persistent local storage for retrieved Floci pricing catalogues.

Raw source documents are preserved in versioned JSON.
Validated pricing records are reconstructed on every load.

Expired entries remain identifiable as stale and are never
automatically substituted for a failed live retrieval.
"""

import hashlib
import json
import os
import tempfile

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from finops.config import RuntimeSettings

from finops.pricing.client import (
    FlociClientSettings,
    create_pricing_client,
)

from finops.pricing.normalization import (
    NormalizedCatalogue,
    normalize_catalogue,
)

from finops.pricing.products import (
    ProductFilter,
    ProductRetrievalResult,
    PricingProducts,
    RawPricingProduct,
    _prepare_filters,
    _matches_filter,
    _reject_duplicate_keys,
    _reject_nonfinite_constant,
)


CACHE_SCHEMA_VERSION = 1

NORMALIZATION_VERSION = 1

# Shared within one application process.
_CACHE_LOCK = RLock()


class PricingCacheError(RuntimeError):
    """A pricing cache cannot be safely read or written."""


def _utc(value):

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            "A timezone-aware datetime is required."
        )

    return value.astimezone(timezone.utc)


def _query_context(endpoint, service_code, filters):

    if (
        not isinstance(service_code, str)
        or not service_code.strip()
    ):
        raise ValueError(
            "service_code must be nonempty text."
        )

    filters = _prepare_filters(filters)

    for item in filters:

        if (
            item.field in (
                "ServiceCode",
                "serviceCode",
                "servicecode",
            )
            and item.value != service_code
        ):
            raise ValueError(
                "Service filter conflicts with the requested service."
            )

    return {
        "endpoint_url": endpoint,
        "operation": "GetProducts",
        "format_version": "aws_v1",
        "service_code": service_code,
        "filters": [
            {
                "field": item.field,
                "value": item.value,
            }
            for item in filters
        ],
    }


def _cache_key(context):

    canonical = json.dumps(
        context,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def _encode_retrieval(retrieval, context):

    if not isinstance(
        retrieval,
        ProductRetrievalResult,
    ):
        raise TypeError(
            "retrieval must be a ProductRetrievalResult."
        )

    return {
        "query": context,
        "complete": True,
        "retrieved_at": _utc(
            retrieval.retrieved_at
        ).isoformat(),
        "page_count": retrieval.page_count,
        "received_count": retrieval.received_count,
        "duplicate_count": retrieval.duplicate_count,
        "products": [
            product.raw_json
            for product in retrieval.products
        ],
    }


def _decode_entry(entry, context):
    """Validate persisted data before reconstructing pricing."""

    if not isinstance(entry, dict):
        raise ValueError(
            "Invalid cache entry."
        )

    if entry.get("query") != context:
        raise ValueError(
            "Stored query context does not match the request."
        )

    if entry.get("complete") is not True:
        raise ValueError(
            "Incomplete retrieval cannot be used as a catalogue."
        )

    filters = tuple(
        ProductFilter(
            field=item["field"],
            value=item["value"],
        )
        for item in context["filters"]
    )

    raw_products = entry.get("products")

    if not isinstance(raw_products, list):
        raise ValueError(
            "Invalid persisted product collection."
        )

    page_count = entry["page_count"]
    received_count = entry["received_count"]
    duplicate_count = entry["duplicate_count"]

    for name, value, minimum in (
        ("page_count", page_count, 1),
        ("received_count", received_count, 0),
        ("duplicate_count", duplicate_count, 0),
    ):
        if type(value) is not int or value < minimum:
            raise ValueError(
                f"Invalid persisted {name}."
            )

    if received_count != (
        len(raw_products) + duplicate_count
    ):
        raise ValueError(
            "Persisted product counts are inconsistent."
        )

    products = []

    for raw_json in raw_products:

        product = RawPricingProduct.from_json(
            raw_json
        )

        if product.service_code != context["service_code"]:
            raise ValueError(
                "Stored product service does not match the query."
            )

        document = product.to_document()

        for item in filters:

            if not _matches_filter(
                product,
                document,
                item,
            ):
                raise ValueError(
                    "Stored product does not match the query filters."
                )

        products.append(product)

    retrieved_at = _utc(
        datetime.fromisoformat(
            entry["retrieved_at"]
        )
    )

    retrieval = ProductRetrievalResult(
        service_code=context["service_code"],
        filters=filters,
        products=tuple(products),
        retrieved_at=retrieved_at,
        page_count=page_count,
        received_count=received_count,
        duplicate_count=duplicate_count,
    )

    return normalize_catalogue(retrieval)


@dataclass(frozen=True, slots=True)
class CachedCatalogue:
    """A persisted catalogue and its freshness assessment."""

    catalogue: NormalizedCatalogue

    checked_at: datetime

    ttl_seconds: int

    @property
    def age_seconds(self):

        return (
            self.checked_at
            - self.catalogue.retrieved_at
        ).total_seconds()

    @property
    def is_fresh(self):

        return (
            0 <= self.age_seconds < self.ttl_seconds
        )

    @property
    def is_stale(self):

        return not self.is_fresh


class PricingCatalogueCache:
    """Store and reload validated GetProducts retrieval results."""

    def __init__(
        self,
        runtime_settings=None,
        client_settings=None,
    ):

        self.runtime_settings = (
            RuntimeSettings()
            if runtime_settings is None
            else runtime_settings
        )

        self.client_settings = (
            FlociClientSettings()
            if client_settings is None
            else client_settings
        )

        if not isinstance(
            self.runtime_settings,
            RuntimeSettings,
        ):
            raise TypeError(
                "Invalid runtime settings."
            )

        if not isinstance(
            self.client_settings,
            FlociClientSettings,
        ):
            raise TypeError(
                "Invalid Floci client settings."
            )

        self.path = (
            self.runtime_settings.catalogue_cache_path
        )

    def _read_document(self):

        try:

            with self.path.open(
                "r",
                encoding="utf-8",
            ) as stream:

                document = json.load(
                    stream,
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_nonfinite_constant,
                )

        except FileNotFoundError:

            return {
                "schema_version": CACHE_SCHEMA_VERSION,
                "normalization_version": NORMALIZATION_VERSION,
                "entries": {},
            }

        except (OSError, ValueError) as error:

            raise PricingCacheError(
                "Unable to read the pricing cache."
            ) from error

        if not isinstance(document, dict):

            raise PricingCacheError(
                "Invalid pricing cache document."
            )

        if (
            type(document.get("schema_version")) is not int
            or document["schema_version"]
            != CACHE_SCHEMA_VERSION
        ):
            raise PricingCacheError(
                "Unsupported pricing cache schema version."
            )

        if (
            type(document.get("normalization_version")) is not int
            or document["normalization_version"]
            != NORMALIZATION_VERSION
        ):
            raise PricingCacheError(
                "Unsupported pricing normalization version."
            )

        if not isinstance(document.get("entries"), dict):

            raise PricingCacheError(
                "Invalid pricing cache entries."
            )

        return document

    def _write_document(self, document):
        """Replace the cache only after writing complete JSON."""

        temporary_path = None

        try:

            content = json.dumps(
                document,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            ) + "\n"

            self.path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=".catalogue-",
                suffix=".tmp",
                delete=False,
            ) as stream:

                temporary_path = Path(stream.name)

                stream.write(content)
                stream.flush()

                os.fsync(stream.fileno())

            os.replace(
                temporary_path,
                self.path,
            )

            temporary_path = None

        except (OSError, ValueError, TypeError) as error:

            raise PricingCacheError(
                "Unable to persist the pricing cache."
            ) from error

        finally:

            if temporary_path is not None:

                try:
                    temporary_path.unlink(
                        missing_ok=True
                    )
                except OSError:
                    pass

    def _context(
        self,
        service_code,
        filters,
    ):

        return _query_context(
            self.client_settings.endpoint_url,
            service_code,
            filters,
        )

    def load(
        self,
        service_code,
        filters=(),
        *,
        now=None,
    ):
        """Return cached data or None when the query has no entry."""

        context = self._context(
            service_code,
            filters,
        )

        key = _cache_key(context)

        checked_at = _utc(
            datetime.now(timezone.utc)
            if now is None
            else now
        )

        with _CACHE_LOCK:

            document = self._read_document()

            if key not in document["entries"]:
                return None

            try:

                catalogue = _decode_entry(
                    document["entries"][key],
                    context,
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ) as error:

                raise PricingCacheError(
                    "Persisted catalogue failed validation."
                ) from error

        return CachedCatalogue(
            catalogue=catalogue,
            checked_at=checked_at,
            ttl_seconds=(
                self.runtime_settings.catalogue_ttl_seconds
            ),
        )

    def store(self, retrieval):
        """Validate and persist a successful complete retrieval.

        The caller must supply a retrieval obtained from the
        configured Floci endpoint. Prefer refresh() for live use.
        """

        if not isinstance(
            retrieval,
            ProductRetrievalResult,
        ):
            raise TypeError(
                "Invalid product retrieval result."
            )

        context = self._context(
            retrieval.service_code,
            retrieval.filters,
        )

        key = _cache_key(context)

        # Validate and normalize before changing persisted files.

        try:

            entry = _encode_retrieval(
                retrieval,
                context,
            )

            catalogue = _decode_entry(
                entry,
                context,
            )

        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:

            raise PricingCacheError(
                "Retrieval failed cache validation."
            ) from error

        with _CACHE_LOCK:

            document = self._read_document()

            if key in document["entries"]:

                try:

                    previous = _decode_entry(
                        document["entries"][key],
                        context,
                    )

                except (
                    KeyError,
                    TypeError,
                    ValueError,
                ) as error:

                    raise PricingCacheError(
                        "Existing cache entry failed validation."
                    ) from error

                if (
                    catalogue.retrieved_at
                    < previous.retrieved_at
                ):
                    raise PricingCacheError(
                        "An older retrieval cannot replace a newer entry."
                    )

            document["entries"][key] = entry

            self._write_document(document)

        return catalogue

    def refresh(
        self,
        service_code,
        filters=(),
    ):
        """Perform a live retrieval and persist only valid results."""

        self._context(
            service_code,
            filters,
        )

        client = create_pricing_client(
            self.client_settings
        )

        try:

            retrieval = PricingProducts(
                client
            ).get_products(
                service_code,
                filters,
            )

        finally:

            client.close()

        return self.store(retrieval)
