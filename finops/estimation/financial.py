"""Reusable financial contracts for infrastructure cost estimation.

All monetary calculations use Decimal and USD.

Amounts represent the explicitly modelled billing scope.
Missing pricing must never be substituted with a complete zero cost.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from uuid import UUID

from finops.infrastructure.validation import (
    MONTHLY_HOURS,
    HOURS_PER_DAY,
    MONTHS_PER_YEAR,
)

from finops.pricing.models import PriceDimension


ZERO = Decimal("0")
USD_DISPLAY_PRECISION = Decimal("0.01")


class CostStatus(StrEnum):
    PRICED = "PRICED"
    ZERO_USAGE = "ZERO_USAGE"
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"
    EXCLUDED = "EXCLUDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EstimateStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


def _nonnegative_decimal(value, name):

    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < ZERO
    ):

        raise ValueError(
            f"{name} must be a finite nonnegative Decimal."
        )

    return value


@dataclass(frozen=True, slots=True)
class PeriodCosts:
    """Normalized costs for an average billing month."""

    average_hourly: Decimal
    daily: Decimal
    monthly: Decimal
    annual: Decimal


def calculate_period_costs(monthly_cost):
    """Convert monthly cost without rounding to cents."""

    monthly_cost = _nonnegative_decimal(
        monthly_cost,
        "Monthly cost",
    )

    return PeriodCosts(
        average_hourly=monthly_cost / MONTHLY_HOURS,
        daily=monthly_cost * HOURS_PER_DAY / MONTHLY_HOURS,
        monthly=monthly_cost,
        annual=monthly_cost * MONTHS_PER_YEAR,
    )


def format_usd(value):
    """Round to cents only for presentation."""

    value = _nonnegative_decimal(value, "USD amount")

    rounded = value.quantize(
        USD_DISPLAY_PRECISION,
        rounding=ROUND_HALF_UP,
    )

    return f"${rounded:,.2f}"


@dataclass(frozen=True, slots=True)
class TierCharge:
    """Known charges and coverage for one billing component."""

    usage: Decimal
    priced_usage: Decimal
    known_cost: Decimal

    @property
    def unpriced_usage(self):
        return self.usage - self.priced_usage

    @property
    def status(self):

        if self.usage == ZERO:
            return CostStatus.ZERO_USAGE

        if self.priced_usage == self.usage:
            return CostStatus.PRICED

        if self.priced_usage == ZERO:
            return CostStatus.UNRESOLVED

        return CostStatus.PARTIAL

    @property
    def total_cost(self):

        if self.status in (
            CostStatus.PRICED,
            CostStatus.ZERO_USAGE,
        ):
            return self.known_cost

        return None


def calculate_tier_charge(usage, dimensions):
    """Calculate graduated charges over matching price dimensions.

    Each tier covers [begin_range, end_range).
    An end_range of None represents an unbounded tier.

    The caller must supply dimensions belonging to one compatible
    billing component and one pricing offer.

    Uncovered quantities remain unpriced.
    Overlapping tiers are rejected.
    """

    usage = _nonnegative_decimal(usage, "Billing usage")
    dimensions = tuple(dimensions)

    for dimension in dimensions:

        if not isinstance(dimension, PriceDimension):
            raise TypeError("PriceDimension required.")

        if dimension.currency != "USD":
            raise ValueError("Only USD pricing is supported.")

    if len({item.unit for item in dimensions}) > 1:
        raise ValueError("Incompatible billing units.")

    if len({
        item.cost_component
        for item in dimensions
    }) > 1:

        raise ValueError("Incompatible cost components.")

    ordered = sorted(
        dimensions,
        key=lambda item: item.begin_range,
    )

    for previous, current in zip(ordered, ordered[1:]):

        if (
            previous.end_range is None
            or current.begin_range < previous.end_range
        ):

            raise ValueError("Overlapping pricing tiers.")

    known_cost = ZERO
    priced_usage = ZERO

    for dimension in ordered:

        upper = (
            usage
            if dimension.end_range is None
            else min(usage, dimension.end_range)
        )

        covered = max(
            ZERO,
            upper - dimension.begin_range,
        )

        priced_usage += covered

        known_cost += (
            covered * dimension.unit_price
        )

    return TierCharge(
        usage=usage,
        priced_usage=priced_usage,
        known_cost=known_cost,
    )


@dataclass(frozen=True, slots=True)
class ComponentEstimate:
    """Monthly charge outcome for a resource billing component.

    Usage is expressed in the component billing unit after
    applying the resource quantity where appropriate.

    known_monthly_cost is a known subtotal, not necessarily
    the complete monthly cost.
    """

    resource_id: UUID
    component: str
    unit: str
    status: CostStatus

    usage: Decimal | None
    priced_usage: Decimal

    known_monthly_cost: Decimal

    detail: str = ""

    def __post_init__(self):

        if (
            not isinstance(self.resource_id, UUID)
            or self.resource_id.int == 0
        ):

            raise ValueError("A nonzero resource UUID is required.")

        for name, value in (
            ("component", self.component),
            ("unit", self.unit),
        ):

            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty.")

        if not isinstance(self.detail, str):
            raise ValueError("Detail must be text.")

        if not isinstance(self.status, CostStatus):
            raise ValueError("Invalid component cost status.")

        if self.usage is not None:
            _nonnegative_decimal(self.usage, "Usage")

        _nonnegative_decimal(
            self.priced_usage,
            "Priced usage",
        )

        _nonnegative_decimal(
            self.known_monthly_cost,
            "Known monthly cost",
        )

        if (
            self.usage is not None
            and self.priced_usage > self.usage
        ):

            raise ValueError("Priced usage exceeds total usage.")

        if self.status == CostStatus.PRICED:

            if (
                self.usage is None
                or self.usage == ZERO
                or self.priced_usage != self.usage
            ):

                raise ValueError(
                    "Priced components require full positive usage coverage."
                )

        elif self.status == CostStatus.ZERO_USAGE:

            if (
                self.usage != ZERO
                or self.priced_usage != ZERO
                or self.known_monthly_cost != ZERO
            ):

                raise ValueError(
                    "Zero-usage components require explicit zero values."
                )

        elif self.status == CostStatus.PARTIAL:

            if (
                self.usage is None
                or not ZERO < self.priced_usage < self.usage
            ):

                raise ValueError(
                    "Partial components require incomplete positive coverage."
                )

        else:

            if (
                self.priced_usage != ZERO
                or self.known_monthly_cost != ZERO
            ):

                raise ValueError(
                    "Unresolved or excluded components cannot "
                    "claim priced usage or charges."
                )

    @property
    def complete_monthly_cost(self):

        if self.status in (
            CostStatus.PRICED,
            CostStatus.ZERO_USAGE,
        ):

            return self.known_monthly_cost

        return None


@dataclass(frozen=True, slots=True)
class CostSummary:
    """Aggregate cost coverage within a declared estimation scope."""

    status: EstimateStatus
    known_monthly_cost: Decimal
    resolved_components: int
    partial_components: int
    unresolved_components: int
    excluded_components: int
    not_applicable_components: int

    @property
    def complete_monthly_cost(self):

        if self.status == EstimateStatus.COMPLETE:
            return self.known_monthly_cost

        return None

    @property
    def known_period_costs(self):

        return calculate_period_costs(
            self.known_monthly_cost
        )

    @property
    def complete_period_costs(self):

        if self.status != EstimateStatus.COMPLETE:
            return None

        return self.known_period_costs


def summarize_components(components):
    """Aggregate known charges without hiding missing coverage."""

    components = tuple(components)

    identities = set()

    counts = {
        status: 0
        for status in CostStatus
    }

    known_monthly_cost = ZERO

    for component in components:

        if not isinstance(component, ComponentEstimate):
            raise TypeError("ComponentEstimate required.")

        identity = (
            component.resource_id,
            component.component,
        )

        if identity in identities:
            raise ValueError("Duplicate resource cost component.")

        identities.add(identity)

        counts[component.status] += 1
        known_monthly_cost += component.known_monthly_cost

    resolved = (
        counts[CostStatus.PRICED]
        + counts[CostStatus.ZERO_USAGE]
    )

    partial = counts[CostStatus.PARTIAL]
    unresolved = counts[CostStatus.UNRESOLVED]

    if resolved and not partial and not unresolved:

        status = EstimateStatus.COMPLETE

    elif resolved or partial:

        status = EstimateStatus.PARTIAL

    else:

        status = EstimateStatus.UNAVAILABLE

    return CostSummary(
        status=status,
        known_monthly_cost=known_monthly_cost,
        resolved_components=resolved,
        partial_components=partial,
        unresolved_components=unresolved,
        excluded_components=counts[CostStatus.EXCLUDED],
        not_applicable_components=counts[
            CostStatus.NOT_APPLICABLE
        ],
    )
