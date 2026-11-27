"""Financial contracts for equivalent-scope cloud pricing comparisons.

All costs use Decimal and USD. Comparisons preserve the identity
of their historical infrastructure baseline.

A partial estimate cannot establish definitive financial savings.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from finops.estimation.financial import (
    EstimateStatus,
    calculate_period_costs,
)

from finops.infrastructure.validation import MONTHS_PER_YEAR

from finops.pricing.models import (
    PricingModel,
    PricingSource,
)


ZERO = Decimal("0")
HUNDRED = Decimal("100")
DISPLAY_PRECISION = Decimal("0.01")


def _validate_decimal(value, name, *, signed=False):

    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
    ):
        raise ValueError(
            f"{name} must be a finite Decimal."
        )

    if not signed and value < ZERO:
        raise ValueError(
            f"{name} cannot be negative."
        )

    return value


def _validate_uuid(value, name):

    if (
        not isinstance(value, UUID)
        or value.int == 0
    ):
        raise ValueError(
            f"{name} must be a nonzero UUID."
        )


def _validate_text(value, name):

    if (
        not isinstance(value, str)
        or not value.strip()
    ):
        raise ValueError(
            f"{name} must be nonempty text."
        )


def _validate_text_tuple(values, name):

    if not isinstance(values, tuple):
        raise ValueError(
            f"{name} must be a tuple."
        )

    for value in values:
        _validate_text(value, name)


@dataclass(frozen=True, slots=True)
class ComparisonScope:
    """Identify the historical baseline and resource billing scope.

    The baseline estimate identifies a fixed infrastructure scenario,
    revision and historical pricing context.

    The selected component identities establish which costs are
    included in the comparison.

    Model-specific evaluators must additionally ensure that workload
    consumption remains equivalent across alternatives.
    """

    baseline_estimate_id: UUID
    resource_id: UUID
    components: tuple[str, ...]

    def __post_init__(self):

        _validate_uuid(
            self.baseline_estimate_id,
            "Baseline estimate identity",
        )

        _validate_uuid(
            self.resource_id,
            "Resource identity",
        )

        _validate_text_tuple(
            self.components,
            "Billing components",
        )

        if not self.components:
            raise ValueError(
                "At least one billing component is required."
            )

        if len(set(self.components)) != len(self.components):
            raise ValueError(
                "Duplicate billing components."
            )

        # Normalize ordering so equivalent component sets match.

        object.__setattr__(
            self,
            "components",
            tuple(sorted(self.components)),
        )


@dataclass(frozen=True, slots=True)
class PricingOption:
    """A modeled purchasing or storage-pricing alternative."""

    scope: ComparisonScope
    name: str
    pricing_model: PricingModel
    status: EstimateStatus

    known_monthly_cost: Decimal

    sources: tuple[PricingSource, ...] = ()
    assumptions: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()

    detail: str = ""

    def __post_init__(self):

        if not isinstance(self.scope, ComparisonScope):
            raise ValueError("Invalid comparison scope.")

        _validate_text(self.name, "Pricing option name")

        if not isinstance(self.pricing_model, PricingModel):
            raise ValueError("Invalid pricing model.")

        if not isinstance(self.status, EstimateStatus):
            raise ValueError("Invalid estimate status.")

        _validate_decimal(
            self.known_monthly_cost,
            "Known monthly cost",
        )

        if not isinstance(self.sources, tuple):
            raise ValueError("Pricing sources must be a tuple.")

        if any(
            not isinstance(source, PricingSource)
            for source in self.sources
        ):
            raise ValueError("Invalid pricing source.")

        if len(set(self.sources)) != len(self.sources):
            raise ValueError("Duplicate pricing sources.")

        _validate_text_tuple(
            self.assumptions,
            "Pricing assumptions",
        )

        _validate_text_tuple(
            self.exclusions,
            "Pricing exclusions",
        )

        if not isinstance(self.detail, str):
            raise ValueError("Pricing detail must be text.")

        if (
            PricingSource.ESTIMATION_ASSUMPTION in self.sources
            and not self.assumptions
        ):
            raise ValueError(
                "Hypothetical pricing requires documented assumptions."
            )

        if (
            self.known_monthly_cost > ZERO
            and not self.sources
        ):
            raise ValueError(
                "Positive known charges require pricing provenance."
            )

        if (
            self.status == EstimateStatus.UNAVAILABLE
            and self.known_monthly_cost != ZERO
        ):
            raise ValueError(
                "Unavailable options cannot claim known positive charges."
            )

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


@dataclass(frozen=True, slots=True)
class PricingComparison:
    """Compare complete modeled costs within equivalent scope."""

    baseline: PricingOption
    alternative: PricingOption

    def __post_init__(self):

        if not isinstance(self.baseline, PricingOption):
            raise TypeError("Invalid baseline pricing option.")

        if not isinstance(self.alternative, PricingOption):
            raise TypeError("Invalid alternative pricing option.")

        if self.baseline.scope != self.alternative.scope:
            raise ValueError(
                "Pricing comparisons require equivalent billing scope."
            )

        if self.baseline.pricing_model != PricingModel.ON_DEMAND:
            raise ValueError(
                "The comparison baseline must use On-Demand pricing."
            )

        if (
            set(self.baseline.exclusions)
            != set(self.alternative.exclusions)
        ):
            raise ValueError(
                "Pricing comparisons require equivalent exclusions."
            )

    @property
    def is_comparable(self):

        return (
            self.baseline.status == EstimateStatus.COMPLETE
            and self.alternative.status == EstimateStatus.COMPLETE
        )

    @property
    def monthly_savings(self):

        if not self.is_comparable:
            return None

        return (
            self.baseline.complete_monthly_cost
            - self.alternative.complete_monthly_cost
        )

    @property
    def annual_savings(self):

        if self.monthly_savings is None:
            return None

        return (
            self.monthly_savings
            * MONTHS_PER_YEAR
        )

    @property
    def savings_percentage(self):

        if not self.is_comparable:
            return None

        baseline_cost = self.baseline.complete_monthly_cost

        if baseline_cost == ZERO:
            return None

        return (
            self.monthly_savings
            / baseline_cost
            * HUNDRED
        )

    @property
    def is_cheaper(self):

        savings = self.monthly_savings

        if savings is None:
            return None

        return savings > ZERO

    @property
    def uses_assumptions(self):

        return any(
            PricingSource.ESTIMATION_ASSUMPTION in option.sources
            for option in (self.baseline, self.alternative)
        )


def format_signed_usd(value):

    if value is None:
        return "Unavailable"

    value = _validate_decimal(
        value,
        "Signed USD amount",
        signed=True,
    )

    rounded = value.quantize(
        DISPLAY_PRECISION,
        rounding=ROUND_HALF_UP,
    )

    if rounded == ZERO:
        rounded = ZERO

    if rounded < ZERO:
        return f"-${abs(rounded):,.2f}"

    return f"${rounded:,.2f}"


def format_percentage(value):

    if value is None:
        return "Unavailable"

    value = _validate_decimal(
        value,
        "Percentage",
        signed=True,
    )

    rounded = value.quantize(
        DISPLAY_PRECISION,
        rounding=ROUND_HALF_UP,
    )

    if rounded == ZERO:
        rounded = ZERO

    return f"{rounded:,.2f}%"
