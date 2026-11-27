"""Immutable pricing contracts shared by the FinOps modules.

The contracts preserve pricing precision, configuration identity,
source provenance, usage boundaries and resolution outcomes.

AWS response normalization and service-specific matching belong
to subsequent pricing components.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType


class PricingSource(StrEnum):
    """Origin of an applicable pricing record."""

    FLOCI_PRICING_API = "FLOCI_PRICING_API"
    FLOCI_EC2_API = "FLOCI_EC2_API"
    REFERENCE_DATA = "REFERENCE_DATA"
    ESTIMATION_ASSUMPTION = "ESTIMATION_ASSUMPTION"


class PricingModel(StrEnum):
    """Supported pricing model identifiers."""

    ON_DEMAND = "ON_DEMAND"
    RESERVED = "RESERVED"
    SAVINGS_PLAN = "SAVINGS_PLAN"
    SPOT = "SPOT"


class ResolutionStatus(StrEnum):
    """Outcome of a pricing resolution operation."""

    RESOLVED = "RESOLVED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"
    API_ERROR = "API_ERROR"


def _require_text(value: object, name: str) -> None:
    """Require a nonempty text value."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text.")


def _require_currency(value: object) -> None:
    """Validate a three-letter uppercase currency identifier."""

    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or not value.isupper()
    ):
        raise ValueError(
            "Currency must be a three-letter uppercase identifier."
        )


def _require_nonnegative_decimal(
    value: object,
    name: str,
) -> None:
    """Require a finite, nonnegative Decimal."""

    if not isinstance(value, Decimal):
        raise ValueError(
            f"{name} must be a Decimal."
        )

    if not value.is_finite() or value < 0:
        raise ValueError(
            f"{name} must be finite and nonnegative."
        )


def _freeze_mapping(
    value: Mapping[str, str],
    name: str,
    *,
    allow_empty_values: bool = True,
) -> Mapping[str, str]:
    """Create an independent, read-only attribute mapping."""

    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping.")

    copied = {}

    for key, item in value.items():
        _require_text(key, f"{name} key")

        if not isinstance(item, str):
            raise ValueError(
                f"{name} values must be strings."
            )

        if not allow_empty_values and not item.strip():
            raise ValueError(
                f"{name} values must be nonempty."
            )

        copied[key] = item

    return MappingProxyType(copied)


def _freeze_items(
    value: object,
    item_type: type,
    name: str,
) -> tuple:
    """Validate and copy a sequence into an immutable tuple."""

    if not isinstance(value, (tuple, list)):
        raise ValueError(
            f"{name} must be a tuple or list."
        )

    result = tuple(value)

    if any(not isinstance(item, item_type) for item in result):
        raise ValueError(
            f"{name} contains an invalid item."
        )

    return result


def _freeze_text_items(
    value: object,
    name: str,
) -> tuple[str, ...]:
    result = _freeze_items(value, str, name)

    for item in result:
        _require_text(item, name)

    return result


def _normalize_timestamp(
    value: datetime | None,
    name: str,
    *,
    required: bool = False,
) -> datetime | None:
    """Normalize an explicitly timezone-aware timestamp to UTC."""

    if value is None:
        if required:
            raise ValueError(f"{name} is required.")

        return None

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{name} must be a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class PriceDimension:
    """One billable pricing rate and its applicable usage range."""

    rate_code: str
    unit: str
    currency: str
    unit_price: Decimal
    begin_range: Decimal
    end_range: Decimal | None

    description: str = ""
    applies_to: tuple[str, ...] = ()
    cost_component: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.rate_code, "rate_code")
        _require_text(self.unit, "unit")
        _require_currency(self.currency)

        _require_nonnegative_decimal(
            self.unit_price,
            "unit_price",
        )

        _require_nonnegative_decimal(
            self.begin_range,
            "begin_range",
        )

        if self.end_range is not None:
            _require_nonnegative_decimal(
                self.end_range,
                "end_range",
            )

            if self.end_range <= self.begin_range:
                raise ValueError(
                    "end_range must exceed begin_range."
                )

        if not isinstance(self.description, str):
            raise ValueError(
                "description must be text."
            )

        if self.cost_component is not None:
            _require_text(
                self.cost_component,
                "cost_component",
            )

        object.__setattr__(
            self,
            "applies_to",
            _freeze_text_items(
                self.applies_to,
                "applies_to",
            ),
        )

    @property
    def is_unbounded(self) -> bool:
        """Whether the source dimension has no upper boundary."""

        return self.end_range is None


@dataclass(frozen=True, slots=True)
class PricingRecord:
    """Normalized product, pricing offer and source provenance."""

    service_code: str
    sku: str
    product_family: str
    region: str

    attributes: Mapping[str, str]
    pricing_model: PricingModel
    offer_term_code: str
    dimensions: tuple[PriceDimension, ...]

    source: PricingSource
    source_reference: str

    term_attributes: Mapping[str, str] = field(
        default_factory=dict
    )

    effective_date: datetime | None = None
    publication_date: datetime | None = None
    catalogue_version: str | None = None
    retrieved_at: datetime | None = None
    verified_at: datetime | None = None

    assumptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "service_code",
            "sku",
            "product_family",
            "region",
            "offer_term_code",
            "source_reference",
        ):
            _require_text(getattr(self, name), name)

        if not isinstance(self.pricing_model, PricingModel):
            raise ValueError("Invalid pricing model.")

        if not isinstance(self.source, PricingSource):
            raise ValueError("Invalid pricing source.")

        object.__setattr__(
            self,
            "attributes",
            _freeze_mapping(
                self.attributes,
                "attributes",
            ),
        )

        object.__setattr__(
            self,
            "term_attributes",
            _freeze_mapping(
                self.term_attributes,
                "term_attributes",
            ),
        )

        dimensions = _freeze_items(
            self.dimensions,
            PriceDimension,
            "dimensions",
        )

        if not dimensions:
            raise ValueError(
                "A pricing record requires at least one dimension."
            )

        identities = [
            (dimension.rate_code, dimension.currency)
            for dimension in dimensions
        ]

        if len(identities) != len(set(identities)):
            raise ValueError(
                "Duplicate pricing dimension identity."
            )

        object.__setattr__(
            self,
            "dimensions",
            dimensions,
        )

        for name in (
            "effective_date",
            "publication_date",
            "retrieved_at",
            "verified_at",
        ):
            object.__setattr__(
                self,
                name,
                _normalize_timestamp(
                    getattr(self, name),
                    name,
                ),
            )

        if self.catalogue_version is not None:
            _require_text(
                self.catalogue_version,
                "catalogue_version",
            )

        object.__setattr__(
            self,
            "assumptions",
            _freeze_text_items(
                self.assumptions,
                "assumptions",
            ),
        )

        if self.source in (
            PricingSource.FLOCI_PRICING_API,
            PricingSource.FLOCI_EC2_API,
        ) and self.retrieved_at is None:
            raise ValueError(
                "Floci pricing requires a retrieval timestamp."
            )

        if (
            self.source == PricingSource.REFERENCE_DATA
            and self.verified_at is None
        ):
            raise ValueError(
                "Reference pricing requires a verification timestamp."
            )

        if (
            self.source == PricingSource.ESTIMATION_ASSUMPTION
            and not self.assumptions
        ):
            raise ValueError(
                "Assumed pricing requires explicit assumptions."
            )


@dataclass(frozen=True, slots=True)
class PricingQuery:
    """Requested pricing configuration and billing component."""

    service_code: str
    resource_type: str
    region: str
    pricing_model: PricingModel
    cost_component: str

    attributes: Mapping[str, str] = field(
        default_factory=dict
    )

    currency: str = "USD"

    def __post_init__(self) -> None:
        for name in (
            "service_code",
            "resource_type",
            "region",
            "cost_component",
        ):
            _require_text(getattr(self, name), name)

        if not isinstance(self.pricing_model, PricingModel):
            raise ValueError("Invalid pricing model.")

        _require_currency(self.currency)

        object.__setattr__(
            self,
            "attributes",
            _freeze_mapping(
                self.attributes,
                "attributes",
                allow_empty_values=False,
            ),
        )


@dataclass(frozen=True, slots=True)
class PricingResolution:
    """Structured outcome of a pricing request."""

    query: PricingQuery
    status: ResolutionStatus

    records: tuple[PricingRecord, ...] = ()
    missing_components: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.query, PricingQuery):
            raise ValueError(
                "query must be a PricingQuery."
            )

        if not isinstance(self.status, ResolutionStatus):
            raise ValueError(
                "Invalid resolution status."
            )

        records = _freeze_items(
            self.records,
            PricingRecord,
            "records",
        )

        object.__setattr__(
            self,
            "records",
            records,
        )

        for name in (
            "missing_components",
            "diagnostics",
            "warnings",
        ):
            object.__setattr__(
                self,
                name,
                _freeze_text_items(
                    getattr(self, name),
                    name,
                ),
            )

        if self.status == ResolutionStatus.RESOLVED:
            if not records:
                raise ValueError(
                    "Resolved pricing requires applicable records."
                )

            if self.missing_components:
                raise ValueError(
                    "Resolved pricing cannot contain missing components."
                )

        elif self.status == ResolutionStatus.PARTIAL:
            if not records or not self.missing_components:
                raise ValueError(
                    "Partial pricing requires known records "
                    "and missing components."
                )

        elif records:
            raise ValueError(
                "Unsuccessful resolution must not expose "
                "records as selected usable pricing."
            )

        for record in records:
            if record.service_code != self.query.service_code:
                raise ValueError(
                    "Selected pricing service does not match the query."
                )

            if record.region != self.query.region:
                raise ValueError(
                    "Selected pricing region does not match the query."
                )

            if record.pricing_model != self.query.pricing_model:
                raise ValueError(
                    "Selected pricing model does not match the query."
                )

            if not any(
                dimension.currency == self.query.currency
                for dimension in record.dimensions
            ):
                raise ValueError(
                    "Selected pricing record has no matching currency."
                )

    @property
    def has_usable_prices(self) -> bool:
        return bool(self.records)

    @property
    def is_complete(self) -> bool:
        return self.status == ResolutionStatus.RESOLVED


@dataclass(frozen=True, slots=True)
class SpotPriceObservation:
    """A timestamped EC2 Spot pricing observation."""

    instance_type: str
    region: str
    availability_zone: str
    product_description: str

    unit_price: Decimal
    observed_at: datetime
    retrieved_at: datetime

    currency: str = "USD"
    unit: str = "Hrs"

    availability_zone_id: str | None = None

    source: PricingSource = PricingSource.FLOCI_EC2_API

    def __post_init__(self) -> None:
        for name in (
            "instance_type",
            "region",
            "availability_zone",
            "product_description",
            "unit",
        ):
            _require_text(getattr(self, name), name)

        _require_currency(self.currency)

        _require_nonnegative_decimal(
            self.unit_price,
            "unit_price",
        )

        if self.availability_zone_id is not None:
            _require_text(
                self.availability_zone_id,
                "availability_zone_id",
            )

        if self.source != PricingSource.FLOCI_EC2_API:
            raise ValueError(
                "Spot observations must originate from the EC2 API."
            )

        for name in (
            "observed_at",
            "retrieved_at",
        ):
            object.__setattr__(
                self,
                name,
                _normalize_timestamp(
                    getattr(self, name),
                    name,
                    required=True,
                ),
            )
