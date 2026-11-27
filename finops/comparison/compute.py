"""Equivalent-workload EC2 purchasing model calculations.

Reserved Instance and Savings Plans inputs are hypothetical
financial assumptions, not retrieved purchasing quotations.

Spot alternatives use an actual matching price observation.

The commitment model assumes a fixed fleet running concurrently
for its configured monthly runtime.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from finops.comparison.models import (
    ComparisonScope,
    PricingComparison,
    PricingOption,
)

from finops.estimation.engine import InfrastructureEstimate

from finops.estimation.financial import (
    CostStatus,
    EstimateStatus,
)

from finops.infrastructure.models import ResourceType

from finops.infrastructure.validation import MONTHLY_HOURS

from finops.pricing.models import (
    PricingModel,
    PricingSource,
    SpotPriceObservation,
)


ZERO = Decimal("0")


COMPUTE_ASSUMPTIONS = (
    "All instances in the selected resource group use equivalent configuration.",
    "The fleet runs concurrently for its configured monthly runtime.",
    "An average month contains 730 hours.",
    "Annual projections assume unchanged monthly workload and rates.",
    "The comparison includes EC2 instance compute charges only.",
)


COMPUTE_EXCLUSIONS = (
    "Taxes, credits and promotional allowances.",
    "EBS storage, networking and data transfer.",
    "Additional software licensing and CPU credit charges.",
    "Cross-resource commitment allocation and other account-wide discounts.",
    "Operational migration and interruption recovery costs.",
)


def _amount(value, name, *, positive=False):

    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < ZERO
    ):
        raise ValueError(
            f"{name} must be a finite nonnegative Decimal."
        )

    if positive and value == ZERO:
        raise ValueError(
            f"{name} must be positive."
        )

    return value


def _count(value, name, *, allow_zero=False):

    if (
        type(value) is not int
        or value < 0
        or (value == 0 and not allow_zero)
    ):
        raise ValueError(
            f"{name} must be a valid integer quantity."
        )

    return value


def _term(value):

    if type(value) is not int or value not in (12, 36):
        raise ValueError(
            "Commitment term must be 12 or 36 months."
        )

    return value


def _sources(*groups):

    return tuple(
        sorted(
            {
                source
                for group in groups
                for source in group
            },
            key=lambda item: item.value,
        )
    )


@dataclass(frozen=True, slots=True)
class ComputeWorkload:
    """A complete, comparable Linux/shared EC2 compute baseline."""

    baseline: PricingOption

    instance_type: str
    region: str

    quantity: int
    monthly_hours: Decimal
    on_demand_rate: Decimal

    def __post_init__(self):

        if not isinstance(self.baseline, PricingOption):
            raise ValueError("Invalid historical pricing baseline.")

        if (
            self.baseline.pricing_model
            != PricingModel.ON_DEMAND
        ):
            raise ValueError(
                "Compute baseline must use On-Demand pricing."
            )

        if self.baseline.status != EstimateStatus.COMPLETE:
            raise ValueError(
                "Compute comparison requires a complete baseline."
            )

        if self.baseline.scope.components != ("compute",):
            raise ValueError(
                "Compute comparison requires compute-only billing scope."
            )

        if not isinstance(self.instance_type, str) or not self.instance_type.strip():
            raise ValueError("Instance type is required.")

        if not isinstance(self.region, str) or not self.region.strip():
            raise ValueError("Region is required.")

        _count(self.quantity, "Instance quantity")

        _amount(
            self.monthly_hours,
            "Monthly runtime",
        )

        _amount(
            self.on_demand_rate,
            "On-Demand hourly rate",
        )

        if self.monthly_hours > MONTHLY_HOURS:
            raise ValueError(
                "Monthly runtime cannot exceed 730 hours."
            )

        if (
            self.baseline.complete_monthly_cost
            != self.total_instance_hours * self.on_demand_rate
        ):
            raise ValueError(
                "Historical baseline does not match workload and rate."
            )

    @property
    def total_instance_hours(self):

        return (
            Decimal(self.quantity)
            * self.monthly_hours
        )


@dataclass(frozen=True, slots=True)
class ReservedAssumptions:
    """Illustrative Reserved Instance purchasing assumptions."""

    reserved_quantity: int

    hourly_recurring_rate: Decimal

    upfront_per_instance: Decimal = ZERO

    term_months: int = 12

    def __post_init__(self):

        _count(
            self.reserved_quantity,
            "Reserved instance quantity",
            allow_zero=True,
        )

        _amount(
            self.hourly_recurring_rate,
            "Recurring hourly rate",
        )

        _amount(
            self.upfront_per_instance,
            "Upfront payment",
        )

        _term(self.term_months)


@dataclass(frozen=True, slots=True)
class SavingsPlanAssumptions:
    """Illustrative no-upfront hourly spending commitment."""

    hourly_commitment: Decimal

    discounted_hourly_rate: Decimal

    term_months: int = 12

    def __post_init__(self):

        _amount(
            self.hourly_commitment,
            "Hourly spending commitment",
        )

        _amount(
            self.discounted_hourly_rate,
            "Discounted hourly rate",
            positive=True,
        )

        _term(self.term_months)


@dataclass(frozen=True, slots=True)
class ComputeComparisonResult:
    """A comparison and its model-specific financial breakdown."""

    comparison: PricingComparison

    covered_instance_hours: Decimal

    uncovered_on_demand_hours: Decimal

    monthly_upfront_amortization: Decimal = ZERO

    monthly_commitment_charge: Decimal = ZERO

    monthly_on_demand_charge: Decimal = ZERO

    monthly_spot_charge: Decimal = ZERO

    unused_reserved_hours: Decimal | None = None

    unused_savings_plan_commitment: Decimal | None = None

    term_months: int | None = None

    def __post_init__(self):

        if not isinstance(self.comparison, PricingComparison):
            raise ValueError("Invalid pricing comparison.")

        for name in (
            "covered_instance_hours",
            "uncovered_on_demand_hours",
            "monthly_upfront_amortization",
            "monthly_commitment_charge",
            "monthly_on_demand_charge",
            "monthly_spot_charge",
        ):

            _amount(
                getattr(self, name),
                name,
            )

        if self.unused_reserved_hours is not None:

            _amount(
                self.unused_reserved_hours,
                "Unused reserved hours",
            )

        if self.unused_savings_plan_commitment is not None:

            _amount(
                self.unused_savings_plan_commitment,
                "Unused Savings Plan commitment",
            )

        if self.term_months is not None:
            _term(self.term_months)

        if (
            self.comparison.alternative.complete_monthly_cost
            != self.monthly_total
        ):
            raise ValueError(
                "Alternative cost does not match its breakdown."
            )

    @property
    def monthly_total(self):

        return (
            self.monthly_upfront_amortization
            + self.monthly_commitment_charge
            + self.monthly_on_demand_charge
            + self.monthly_spot_charge
        )

    @property
    def modeled_term_cost(self):

        if self.term_months is None:
            return None

        return (
            self.monthly_total
            * Decimal(self.term_months)
        )


def build_compute_workload(
    estimate: InfrastructureEstimate,
    resource_id: UUID,
) -> ComputeWorkload:

    """Recover a comparable EC2 baseline from historical pricing.

    Only complete, positive-usage, flat-rate compute components
    are accepted. Other infrastructure costs do not affect this
    resource-specific comparison.
    """

    if not isinstance(estimate, InfrastructureEstimate):
        raise ValueError("Invalid infrastructure estimate.")

    if not isinstance(resource_id, UUID):
        raise ValueError("Invalid resource identity.")

    resource = next(
        (
            item
            for item in estimate.scenario.resources
            if item.resource_id == resource_id
        ),
        None,
    )

    if resource is None:
        raise ValueError("Resource not found in historical scenario.")

    if resource.resource_type != ResourceType.EC2_INSTANCE:
        raise ValueError("The selected resource is not an EC2 instance.")

    if resource.pricing_model != PricingModel.ON_DEMAND:
        raise ValueError("Expected an On-Demand resource configuration.")

    config = resource.configuration

    if (
        config.get("operatingSystem") != "Linux"
        or config.get("tenancy") != "Shared"
        or config.get("preInstalledSw") not in (None, "", "NA")
    ):
        raise ValueError(
            "Current comparison supports Linux/shared instances "
            "without additional preinstalled software."
        )

    components = [
        item
        for item in estimate.components
        if (
            item.billing.resource_id == resource_id
            and item.billing.component == "compute"
        )
    ]

    if len(components) != 1:
        raise ValueError(
            "Expected exactly one historical compute component."
        )

    component = components[0]

    if component.estimate.status != CostStatus.PRICED:
        raise ValueError(
            "A fully priced positive-usage compute component is required."
        )

    resolution = component.resolution

    if resolution is None or len(resolution.records) != 1:
        raise ValueError(
            "A single historical pricing offer is required."
        )

    record = resolution.records[0]

    if record.pricing_model != PricingModel.ON_DEMAND:
        raise ValueError(
            "Historical compute pricing must be On-Demand."
        )

    if record.region != resource.region:
        raise ValueError(
            "Historical pricing region does not match the resource."
        )

    if record.source not in (
        PricingSource.FLOCI_PRICING_API,
        PricingSource.REFERENCE_DATA,
    ):
        raise ValueError(
            "Unsupported historical On-Demand pricing source."
        )

    if len(record.dimensions) != 1:
        raise ValueError(
            "A single flat hourly pricing dimension is required."
        )

    dimension = record.dimensions[0]

    if (
        dimension.unit != "Hrs"
        or dimension.currency != "USD"
        or dimension.begin_range != ZERO
        or dimension.end_range is not None
        or dimension.cost_component != "compute"
    ):
        raise ValueError(
            "Historical compute pricing is not a flat USD hourly rate."
        )

    monthly_hours = resource.usage.get("monthly_hours")

    _amount(
        monthly_hours,
        "Historical monthly runtime",
        positive=True,
    )

    expected_hours = (
        Decimal(resource.quantity)
        * monthly_hours
    )

    if component.estimate.usage != expected_hours:
        raise ValueError(
            "Historical compute consumption does not match configuration."
        )

    if component.estimate.priced_usage != expected_hours:
        raise ValueError(
            "Historical compute usage is not fully covered."
        )

    scope = ComparisonScope(
        baseline_estimate_id=estimate.estimate_id,
        resource_id=resource.resource_id,
        components=("compute",),
    )

    baseline = PricingOption(
        scope=scope,
        name="On-Demand",
        pricing_model=PricingModel.ON_DEMAND,
        status=EstimateStatus.COMPLETE,
        known_monthly_cost=(
            component.estimate.complete_monthly_cost
        ),
        sources=(record.source,),
        assumptions=COMPUTE_ASSUMPTIONS,
        exclusions=COMPUTE_EXCLUSIONS,
        detail=(
            f"Historical SKU: {record.sku}; "
            f"Rate code: {dimension.rate_code}; "
            f"Rate: USD {dimension.unit_price}/hour; "
            f"Source: {record.source_reference}"
        ),
    )

    return ComputeWorkload(
        baseline=baseline,
        instance_type=config["instanceType"],
        region=resource.region,
        quantity=resource.quantity,
        monthly_hours=monthly_hours,
        on_demand_rate=dimension.unit_price,
    )


def evaluate_reserved(
    workload: ComputeWorkload,
    assumptions: ReservedAssumptions,
) -> ComputeComparisonResult:

    """Evaluate an illustrative Reserved Instance commitment."""

    if not isinstance(workload, ComputeWorkload):
        raise ValueError("Invalid compute workload.")

    if not isinstance(assumptions, ReservedAssumptions):
        raise ValueError("Invalid Reserved Instance assumptions.")

    reserved_quantity = Decimal(
        assumptions.reserved_quantity
    )

    committed_hours = (
        reserved_quantity
        * MONTHLY_HOURS
    )

    covered_hours = (
        Decimal(
            min(
                workload.quantity,
                assumptions.reserved_quantity,
            )
        )
        * workload.monthly_hours
    )

    uncovered_hours = (
        workload.total_instance_hours
        - covered_hours
    )

    unused_hours = (
        committed_hours
        - covered_hours
    )

    upfront_amortization = (
        reserved_quantity
        * assumptions.upfront_per_instance
        / Decimal(assumptions.term_months)
    )

    recurring_charge = (
        committed_hours
        * assumptions.hourly_recurring_rate
    )

    uncovered_charge = (
        uncovered_hours
        * workload.on_demand_rate
    )

    total = (
        upfront_amortization
        + recurring_charge
        + uncovered_charge
    )

    sources = (
        PricingSource.ESTIMATION_ASSUMPTION,
    )

    if uncovered_hours > ZERO:

        sources = _sources(
            sources,
            workload.baseline.sources,
        )

    alternative = PricingOption(
        scope=workload.baseline.scope,
        name="Reserved Instances",
        pricing_model=PricingModel.RESERVED,
        status=EstimateStatus.COMPLETE,
        known_monthly_cost=total,
        sources=sources,
        assumptions=workload.baseline.assumptions + (
            "Hypothetical matching Reserved Instance commitment.",
            "Reserved capacity is charged for all monthly hours.",
            "Upfront payments are amortized across the selected term.",
            "Usage beyond reserved capacity is charged On-Demand.",
            f"Reserved instances: {assumptions.reserved_quantity}.",
            f"Recurring rate: USD {assumptions.hourly_recurring_rate}/hour.",
            f"Upfront payment per instance: USD {assumptions.upfront_per_instance}.",
            f"Commitment term: {assumptions.term_months} months.",
        ),
        exclusions=workload.baseline.exclusions,
        detail=(
            "Illustrative commitment calculation; "
            "not a retrieved AWS Reserved Instance quotation."
        ),
    )

    return ComputeComparisonResult(
        comparison=PricingComparison(
            workload.baseline,
            alternative,
        ),
        covered_instance_hours=covered_hours,
        uncovered_on_demand_hours=uncovered_hours,
        monthly_upfront_amortization=upfront_amortization,
        monthly_commitment_charge=recurring_charge,
        monthly_on_demand_charge=uncovered_charge,
        unused_reserved_hours=unused_hours,
        term_months=assumptions.term_months,
    )


def evaluate_savings_plan(
    workload: ComputeWorkload,
    assumptions: SavingsPlanAssumptions,
) -> ComputeComparisonResult:

    """Evaluate a simplified no-upfront hourly Savings Plan.

    The entire modeled fleet runs concurrently for its configured
    monthly hours.

    The spending commitment is charged every hour. Unused hourly
    commitment does not roll forward to later hours.

    Fractional covered instance-hours are an equivalent financial
    allocation, not a fractional infrastructure deployment.
    """

    if not isinstance(workload, ComputeWorkload):
        raise ValueError("Invalid compute workload.")

    if not isinstance(assumptions, SavingsPlanAssumptions):
        raise ValueError("Invalid Savings Plan assumptions.")

    active_hour_spend = (
        Decimal(workload.quantity)
        * assumptions.discounted_hourly_rate
    )

    used_commitment_per_active_hour = min(
        assumptions.hourly_commitment,
        active_hour_spend,
    )

    covered_hours = (
        used_commitment_per_active_hour
        / assumptions.discounted_hourly_rate
        * workload.monthly_hours
    )

    uncovered_hours = (
        workload.total_instance_hours
        - covered_hours
    )

    commitment_charge = (
        assumptions.hourly_commitment
        * MONTHLY_HOURS
    )

    consumed_commitment = (
        used_commitment_per_active_hour
        * workload.monthly_hours
    )

    unused_commitment = (
        commitment_charge
        - consumed_commitment
    )

    uncovered_charge = (
        uncovered_hours
        * workload.on_demand_rate
    )

    total = (
        commitment_charge
        + uncovered_charge
    )

    sources = (
        PricingSource.ESTIMATION_ASSUMPTION,
    )

    if uncovered_hours > ZERO:

        sources = _sources(
            sources,
            workload.baseline.sources,
        )

    alternative = PricingOption(
        scope=workload.baseline.scope,
        name="Savings Plan",
        pricing_model=PricingModel.SAVINGS_PLAN,
        status=EstimateStatus.COMPLETE,
        known_monthly_cost=total,
        sources=sources,
        assumptions=workload.baseline.assumptions + (
            "Hypothetical no-upfront Savings Plan commitment.",
            "Commitment is charged every hour of the modeled month.",
            "Unused hourly commitment does not roll forward.",
            "All selected instances run concurrently.",
            "Uncovered equivalent usage is charged On-Demand.",
            f"Hourly commitment: USD {assumptions.hourly_commitment}.",
            f"Discounted rate: USD {assumptions.discounted_hourly_rate}/hour.",
            f"Commitment term: {assumptions.term_months} months.",
        ),
        exclusions=workload.baseline.exclusions,
        detail=(
            "Illustrative single-resource commitment calculation; "
            "not a retrieved AWS Savings Plans quotation."
        ),
    )

    return ComputeComparisonResult(
        comparison=PricingComparison(
            workload.baseline,
            alternative,
        ),
        covered_instance_hours=covered_hours,
        uncovered_on_demand_hours=uncovered_hours,
        monthly_commitment_charge=commitment_charge,
        monthly_on_demand_charge=uncovered_charge,
        unused_savings_plan_commitment=unused_commitment,
        term_months=assumptions.term_months,
    )


def evaluate_spot(
    workload: ComputeWorkload,
    observation: SpotPriceObservation,
) -> ComputeComparisonResult:

    """Project cost using a matching Floci Spot price observation."""

    if not isinstance(workload, ComputeWorkload):
        raise ValueError("Invalid compute workload.")

    if not isinstance(observation, SpotPriceObservation):
        raise ValueError("Invalid Spot price observation.")

    if (
        observation.instance_type != workload.instance_type
        or observation.region != workload.region
        or observation.product_description != "Linux/UNIX"
        or observation.currency != "USD"
        or observation.unit != "Hrs"
        or observation.source != PricingSource.FLOCI_EC2_API
    ):
        raise ValueError(
            "Spot observation does not match the compute workload."
        )

    _amount(
        observation.unit_price,
        "Spot hourly rate",
    )

    total = (
        workload.total_instance_hours
        * observation.unit_price
    )

    alternative = PricingOption(
        scope=workload.baseline.scope,
        name=f"Spot - {observation.availability_zone}",
        pricing_model=PricingModel.SPOT,
        status=EstimateStatus.COMPLETE,
        known_monthly_cost=total,
        sources=(observation.source,),
        assumptions=workload.baseline.assumptions + (
            "The observed Spot rate is held constant for projection.",
            "The same instance quantity and runtime are assumed.",
            "Spot capacity availability is not guaranteed.",
            "Interruption and replacement overhead are not modeled.",
        ),
        exclusions=workload.baseline.exclusions,
        detail=(
            f"Availability zone: {observation.availability_zone}; "
            f"Observed rate: USD {observation.unit_price}/hour; "
            f"Observed at: {observation.observed_at.isoformat()}; "
            f"Retrieved at: {observation.retrieved_at.isoformat()}; "
            "Floci emulator observation, not a live AWS quotation."
        ),
    )

    return ComputeComparisonResult(
        comparison=PricingComparison(
            workload.baseline,
            alternative,
        ),
        covered_instance_hours=workload.total_instance_hours,
        uncovered_on_demand_hours=ZERO,
        monthly_spot_charge=total,
    )
