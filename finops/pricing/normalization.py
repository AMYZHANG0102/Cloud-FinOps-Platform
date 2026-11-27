"""Convert raw Pricing API products into validated domain records.

Original retrieval results are retained for provenance.

Normalization does not resolve competing pricing offers,
calculate expenditure or invent unavailable prices.
"""

import re

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from finops.pricing.client import validate_region

from finops.pricing.models import (
    PriceDimension,
    PricingModel,
    PricingRecord,
    PricingSource,
)

from finops.pricing.products import (
    ProductRetrievalResult,
    RawPricingProduct,
)


SUPPORTED_TERMS = {
    "OnDemand": PricingModel.ON_DEMAND,
    "Reserved": PricingModel.RESERVED,
}


class PricingNormalizationError(ValueError):
    """A raw pricing document cannot be normalized safely."""

    def __init__(self, sku: str, message: str):
        self.sku = sku
        super().__init__(
            f"Pricing normalization [{sku}]: {message}"
        )


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text.")

    return value


def _mapping(value, name, *, nonempty=False):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object.")

    if nonempty and not value:
        raise ValueError(f"{name} must not be empty.")

    return value


def _decimal(value, name):
    """Parse source decimal strings without float conversion."""

    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"[0-9]+(?:\.[0-9]+)?",
            value,
            flags=re.ASCII,
        ) is None
    ):
        raise ValueError(
            f"{name} must be a nonnegative decimal string."
        )

    result = Decimal(value)

    if not result.is_finite() or result < 0:
        raise ValueError(
            f"{name} must be finite and nonnegative."
        )

    return result


def _aware_datetime(value, name):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{name} must be a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)


def _timestamp(value, name):
    """Parse an optional source timestamp without inventing dates."""

    if value is None:
        return None

    value = _text(value, name)

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"{name} is not a valid ISO timestamp."
        ) from error

    return _aware_datetime(parsed, name)


def _classify_component(
    service_code,
    product_family,
    attributes,
    unit,
):
    """Classify the billing components verified in the local catalogue.

    Unrecognized components remain unclassified rather than
    receiving a guessed financial meaning.
    """

    if (
        service_code == "AmazonEC2"
        and product_family == "Compute Instance"
        and unit == "Hrs"
    ):
        return "compute"

    if (
        service_code == "AmazonS3"
        and product_family == "Storage"
        and unit == "GB-Mo"
    ):
        return "storage"

    if (
        service_code == "AWSLambda"
        and attributes.get("group") == "AWS-Lambda-Requests"
        and unit == "Requests"
    ):
        return "requests"

    return None


def _normalize_dimension(
    service_code,
    product_family,
    attributes,
    raw_dimension,
):
    """Preserve every currency and usage boundary in a dimension."""

    raw_dimension = _mapping(
        raw_dimension,
        "price dimension",
    )

    rate_code = _text(
        raw_dimension.get("rateCode"),
        "rateCode",
    )

    unit = _text(
        raw_dimension.get("unit"),
        "unit",
    )

    begin_range = _decimal(
        raw_dimension.get("beginRange"),
        "beginRange",
    )

    raw_end = raw_dimension.get("endRange")

    end_range = (
        None
        if raw_end == "Inf"
        else _decimal(raw_end, "endRange")
    )

    prices = _mapping(
        raw_dimension.get("pricePerUnit"),
        "pricePerUnit",
        nonempty=True,
    )

    description = raw_dimension.get("description", "")

    applies_to = raw_dimension.get("appliesTo", [])

    component = _classify_component(
        service_code,
        product_family,
        attributes,
        unit,
    )

    dimensions = []

    for currency, raw_price in sorted(prices.items()):

        dimensions.append(
            PriceDimension(
                rate_code=rate_code,
                unit=unit,
                currency=currency,
                unit_price=_decimal(
                    raw_price,
                    f"pricePerUnit.{currency}",
                ),
                begin_range=begin_range,
                end_range=end_range,
                description=description,
                applies_to=applies_to,
                cost_component=component,
            )
        )

    return tuple(dimensions)


def normalize_product(
    product: RawPricingProduct,
    retrieved_at: datetime,
) -> tuple[PricingRecord, ...]:
    """Normalize every supported pricing offer in one product."""

    if not isinstance(product, RawPricingProduct):
        raise TypeError(
            "product must be a RawPricingProduct."
        )

    try:

        retrieved_at = _aware_datetime(
            retrieved_at,
            "retrieved_at",
        )

        document = product.to_document()
        metadata = document["product"]
        attributes = metadata["attributes"]

        service_code = product.service_code
        product_family = metadata["productFamily"]

        region = validate_region(
            _text(
                attributes.get("regionCode"),
                "regionCode",
            )
        )

        publication_date = _timestamp(
            document.get("publicationDate"),
            "publicationDate",
        )

        version = document.get("version")

        if version is not None:
            _text(version, "catalogue version")

        records = []

        for term_name, raw_offers in sorted(
            document["terms"].items()
        ):

            if term_name not in SUPPORTED_TERMS:
                raise ValueError(
                    f"Unsupported pricing term: {term_name}"
                )

            offers = _mapping(
                raw_offers,
                f"{term_name} offers",
            )

            for offer_key, raw_offer in sorted(offers.items()):

                _text(offer_key, "offer identifier")

                offer = _mapping(
                    raw_offer,
                    "pricing offer",
                )

                if (
                    "sku" in offer
                    and offer["sku"] != product.sku
                ):
                    raise ValueError(
                        "Offer SKU differs from product SKU."
                    )

                offer_term_code = _text(
                    offer.get("offerTermCode"),
                    "offerTermCode",
                )

                effective_date = _timestamp(
                    offer.get("effectiveDate"),
                    "effectiveDate",
                )

                term_attributes = _mapping(
                    offer.get("termAttributes", {}),
                    "termAttributes",
                )

                raw_dimensions = _mapping(
                    offer.get("priceDimensions"),
                    "priceDimensions",
                    nonempty=True,
                )

                dimensions = []

                for dimension_key, raw_dimension in sorted(
                    raw_dimensions.items()
                ):

                    _text(
                        dimension_key,
                        "dimension identifier",
                    )

                    dimensions.extend(
                        _normalize_dimension(
                            service_code,
                            product_family,
                            attributes,
                            raw_dimension,
                        )
                    )

                records.append(
                    PricingRecord(
                        service_code=service_code,
                        sku=product.sku,
                        product_family=product_family,
                        region=region,
                        attributes=attributes,
                        pricing_model=SUPPORTED_TERMS[term_name],
                        offer_term_code=offer_term_code,
                        term_attributes=term_attributes,
                        dimensions=tuple(dimensions),
                        source=PricingSource.FLOCI_PRICING_API,
                        source_reference=(
                            f"pricing.GetProducts:"
                            f"{product.sku}:"
                            f"{term_name}:"
                            f"{offer_key}"
                        ),
                        effective_date=effective_date,
                        publication_date=publication_date,
                        catalogue_version=version,
                        retrieved_at=retrieved_at,
                    )
                )

        return tuple(records)

    except (KeyError, TypeError, ValueError) as error:

        raise PricingNormalizationError(
            product.sku,
            str(error),
        ) from error


@dataclass(frozen=True, slots=True)
class NormalizedCatalogue:
    """Normalized records and the original retrieval context."""

    retrieval: ProductRetrievalResult

    records: tuple[PricingRecord, ...]

    unpriced_skus: tuple[str, ...] = ()

    warnings: tuple[str, ...] = ()

    @property
    def record_count(self):
        return len(self.records)

    @property
    def dimension_count(self):
        return sum(
            len(record.dimensions)
            for record in self.records
        )

    @property
    def service_code(self):
        return self.retrieval.service_code

    @property
    def retrieved_at(self):
        return self.retrieval.retrieved_at

    @property
    def is_empty(self):
        return not self.records


def normalize_catalogue(
    retrieval: ProductRetrievalResult,
) -> NormalizedCatalogue:
    """Normalize a complete retrieval or fail explicitly."""

    if not isinstance(retrieval, ProductRetrievalResult):
        raise TypeError(
            "retrieval must be a ProductRetrievalResult."
        )

    _aware_datetime(
        retrieval.retrieved_at,
        "retrieved_at",
    )

    records = []
    warnings = []
    unpriced_skus = []
    seen_skus = set()

    for product in retrieval.products:

        if not isinstance(product, RawPricingProduct):
            raise ValueError(
                "Invalid product in retrieval result."
            )

        if product.service_code != retrieval.service_code:
            raise PricingNormalizationError(
                product.sku,
                "Product service differs from retrieval service.",
            )

        if product.sku in seen_skus:
            raise PricingNormalizationError(
                product.sku,
                "Duplicate SKU in retrieval result.",
            )

        seen_skus.add(product.sku)

        normalized = normalize_product(
            product,
            retrieval.retrieved_at,
        )

        if not normalized:
            unpriced_skus.append(product.sku)

            warnings.append(
                f"{product.sku}: no pricing offers available."
            )

        for record in normalized:

            for dimension in record.dimensions:

                if dimension.cost_component is None:
                    warnings.append(
                        f"{record.sku}: unclassified billing "
                        f"dimension {dimension.rate_code} "
                        f"({dimension.unit})."
                    )

            records.append(record)

    return NormalizedCatalogue(
        retrieval=retrieval,
        records=tuple(records),
        unpriced_skus=tuple(unpriced_skus),
        warnings=tuple(dict.fromkeys(warnings)),
    )
