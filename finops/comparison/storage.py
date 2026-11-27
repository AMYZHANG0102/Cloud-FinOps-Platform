"""Equivalent-workload S3 storage-class pricing comparisons.

Historical S3 Standard charges establish the baseline.

Alternative rates are explicitly hypothetical flat pricing
assumptions, not retrieved AWS quotations.

The comparison preserves storage capacity, requests, retrieval
consumption and outbound transfer within a fixed resource scope.
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

from finops.pricing.models import (
    PricingModel,
    PricingSource,
)


ZERO = Decimal("0")
ONE = Decimal("1")
THOUSAND = Decimal("1000")


STORAGE_CLASSES = (
    "Standard - Infrequent Access",
    "One Zone - Infrequent Access",
    "Glacier Flexible Retrieval",
    "Glacier Deep Archive",
)


HISTORICAL_COMPONENTS = (
    "storage",
    "put_requests",
    "get_requests",
    "transfer_out",
)


STORAGE_COMPONENTS = tuple(
    sorted(
        HISTORICAL_COMPONENTS + ("retrieval",)
    )
)


STORAGE_ASSUMPTIONS = (
    "The selected resource group retains the same stored data.",
    "Monthly PUT and GET request counts remain unchanged.",
    "Monthly outbound transfer remains unchanged.",
    "Retrieval volume is an explicit aggregate workload assumption.",
    "S3 Standard has no separate modeled data retrieval charge.",
    "Alternative prices are modeled as flat USD unit rates.",
    "Annual projections assume unchanged monthly usage and rates.",
)


STORAGE_EXCLUSIONS = (
    "Taxes, credits, free-tier allowances and private discounts.",
    "Storage-class transition and migration charges.",
    "Minimum storage duration and early-deletion charges.",
    "Minimum billable object size and per-object metadata overhead.",
    "Temporary restored-copy storage charges.",
    "Archive restoration request and expedited retrieval premiums.",
    "Cross-region replication, additional monitoring and other optional charges.",
    "Account-wide pricing tier and allowance changes.",
    "Operational availability, resilience and retrieval latency differences.",
)


STORAGE_CLASS_NOTES = {
    "Standard - Infrequent Access": (
        "Intended for less frequently accessed data. "
        "Retrieval charges and minimum storage rules can affect savings."
    ),
    "One Zone - Infrequent Access": (
        "Stores data in a single Availability Zone. "
        "Lower modeled cost does not imply equivalent resilience."
    ),
    "Glacier Flexible Retrieval": (
        "Archive-oriented storage. "
        "Restoration delays and restoration charges are not fully modeled."
    ),
    "Glacier Deep Archive": (
        "Long-term archive storage. "
        "Retrieval delays and retention requirements must be considered."
    ),
}


def _amount(
    value,
    name,
    *,
    optional=False,
    integral=False,
):

    if value is None and optional:
        return None

    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < ZERO
    ):
        raise ValueError(
            f"{name} must be a finite nonnegative Decimal."
        )

    if integral and value != value.to_integral_value():
        raise ValueError(
            f"{name} must be a whole number."
        )

    return value


@dataclass(frozen=True, slots=True)
class StorageWorkload:
    """Fixed workload and historical Standard storage baseline.

    All quantities represent the complete selected resource group,
    rather than per-bucket quantities.
    """

    baseline: PricingOption

    region: str
    quantity: int

    storage_gb: Decimal
    put_requests: Decimal
    get_requests: Decimal
    transfer_out_gb: Decimal
    retrieval_gb: Decimal

    def __post_init__(self):

        if not isinstance(self.baseline, PricingOption):
            raise ValueError("Invalid storage baseline.")

        if (
            self.baseline.pricing_model
            != PricingModel.ON_DEMAND
        ):
            raise ValueError(
                "Storage baseline must use On-Demand pricing."
            )

        if self.baseline.status != EstimateStatus.COMPLETE:
            raise ValueError(
                "Storage comparison requires a complete historical baseline."
            )

        if (
            self.baseline.scope.components
            != STORAGE_COMPONENTS
        ):
            raise ValueError(
                "Storage baseline has an incompatible billing scope."
            )

        if (
            not isinstance(self.region, str)
            or not self.region.strip()
        ):
            raise ValueError("Storage region is required.")

        if type(self.quantity) is not int or self.quantity <= 0:
            raise ValueError("Invalid storage resource quantity.")

        _amount(
            self.storage_gb,
            "Storage capacity",
        )

        _amount(
            self.put_requests,
            "PUT requests",
            integral=True,
        )

        _amount(
            self.get_requests,
            "GET requests",
            integral=True,
        )

        _amount(
            self.transfer_out_gb,
            "Outbound transfer",
        )

        _amount(
            self.retrieval_gb,
            "Data retrieval",
        )

        # This simplified model associates retrieval with GET requests.

        if (
            self.retrieval_gb > ZERO
            and self.get_requests == ZERO
        ):
            raise ValueError(
                "Positive retrieval requires recorded GET requests."
            )


@dataclass(frozen=True, slots=True)
class StorageRateAssumptions:
    """Explicitly hypothetical alternative storage unit prices.

    A None rate means unavailable pricing.
    A Decimal zero means an explicitly assumed zero rate.
    """

    storage_class: str

    storage_per_gb_month: Decimal | None = None

    put_per_thousand: Decimal | None = None

    get_per_thousand: Decimal | None = None

    transfer_per_gb: Decimal | None = None

    retrieval_per_gb: Decimal | None = None

    def __post_init__(self):

        if self.storage_class not in STORAGE_CLASSES:
            raise ValueError(
                "Unsupported alternative storage class."
            )

        for name in (
            "storage_per_gb_month",
            "put_per_thousand",
            "get_per_thousand",
            "transfer_per_gb",
            "retrieval_per_gb",
        ):

            _amount(
                getattr(self, name),
                name,
                optional=True,
            )


@dataclass(frozen=True, slots=True)
class StorageCharge:
    """A modeled monthly storage billing component."""

    component: str
    usage: Decimal
    unit: str

    rate: Decimal | None
    rate_basis: Decimal

    def __post_init__(self):

        if self.component not in STORAGE_COMPONENTS:
            raise ValueError(
                "Unknown storage billing component."
            )

        _amount(self.usage, "Billing usage")

        _amount(
            self.rate,
            "Unit rate",
            optional=True,
        )

        _amount(
            self.rate_basis,
            "Rate basis",
        )

        if self.rate_basis == ZERO:
            raise ValueError(
                "Rate basis must be positive."
            )

        if (
            not isinstance(self.unit, str)
            or not self.unit.strip()
        ):
            raise ValueError(
                "Billing unit is required."
            )

    @property
    def status(self):

        if self.usage == ZERO:
            return CostStatus.ZERO_USAGE

        if self.rate is None:
            return CostStatus.UNRESOLVED

        return CostStatus.PRICED

    @property
    def monthly_cost(self):

        if self.usage == ZERO:
            return ZERO

        if self.rate is None:
            return None

        return (
            self.usage
            / self.rate_basis
            * self.rate
        )


def _summarize_charges(charges):

    resolved = [
        charge
        for charge in charges
        if charge.monthly_cost is not None
    ]

    known = sum(
        (
            charge.monthly_cost
            for charge in resolved
        ),
        ZERO,
    )

    if len(resolved) == len(charges):
        status = EstimateStatus.COMPLETE

    elif resolved:
        status = EstimateStatus.PARTIAL

    else:
        status = EstimateStatus.UNAVAILABLE

    return status, known


@dataclass(frozen=True, slots=True)
class StorageComparisonResult:
    """Alternative storage charges and financial comparison."""

    comparison: PricingComparison

    charges: tuple[StorageCharge, ...]

    def __post_init__(self):

        if not isinstance(
            self.comparison,
            PricingComparison,
        ):
            raise ValueError(
                "Invalid storage pricing comparison."
            )

        if not isinstance(self.charges, tuple):
            raise ValueError(
                "Storage charges must be a tuple."
            )

        if any(
            not isinstance(charge, StorageCharge)
            for charge in self.charges
        ):
            raise ValueError(
                "Invalid storage charge."
            )

        names = tuple(
            sorted(
                charge.component
                for charge in self.charges
            )
        )

        if names != STORAGE_COMPONENTS:
            raise ValueError(
                "Expected each storage billing component exactly once."
            )

        status, known = _summarize_charges(
            self.charges
        )

        alternative = self.comparison.alternative

        if (
            alternative.status != status
            or alternative.known_monthly_cost != known
        ):
            raise ValueError(
                "Alternative cost does not match storage charges."
            )

    @property
    def known_monthly_cost(self):

        return (
            self.comparison.alternative
            .known_monthly_cost
        )

    @property
    def complete_monthly_cost(self):

        return (
            self.comparison.alternative
            .complete_monthly_cost
        )

    @property
    def unresolved_components(self):

        return tuple(
            charge.component
            for charge in self.charges
            if charge.status == CostStatus.UNRESOLVED
        )


def build_storage_workload(
    estimate: InfrastructureEstimate,
    resource_id: UUID,
    *,
    retrieval_gb: Decimal,
) -> StorageWorkload:

    """Recover a complete historical S3 Standard billing baseline.

    A separate retrieval charge is not present in the Standard
    baseline. Retrieval volume is explicitly supplied for the
    alternative comparison.

    Only a single S3 resource group per selected region is
    supported, avoiding account-level repricing ambiguity.
    """

    if not isinstance(
        estimate,
        InfrastructureEstimate,
    ):
        raise ValueError(
            "Invalid infrastructure estimate."
        )

    if not isinstance(resource_id, UUID):
        raise ValueError(
            "Invalid resource identity."
        )

    _amount(
        retrieval_gb,
        "Retrieval volume",
    )

    resource = next(
        (
            item
            for item in estimate.scenario.resources
            if item.resource_id == resource_id
        ),
        None,
    )

    if resource is None:
        raise ValueError(
            "Resource not found in historical scenario."
        )

    if resource.resource_type != ResourceType.S3_BUCKET:
        raise ValueError(
            "Selected resource is not an S3 bucket."
        )

    if resource.pricing_model != PricingModel.ON_DEMAND:
        raise ValueError(
            "Expected an On-Demand storage configuration."
        )

    if resource.configuration.get("volumeType") != "Standard":
        raise ValueError(
            "Current storage comparison requires an S3 Standard baseline."
        )

    regional_groups = [
        item
        for item in estimate.scenario.resources
        if (
            item.resource_type == ResourceType.S3_BUCKET
            and item.region == resource.region
        )
    ]

    if len(regional_groups) != 1:
        raise ValueError(
            "Current comparison requires one S3 resource group "
            "in the selected region."
        )

    selected = [
        item
        for item in estimate.components
        if item.billing.resource_id == resource_id
    ]

    actual_components = tuple(
        sorted(
            item.billing.component
            for item in selected
        )
    )

    if actual_components != tuple(
        sorted(HISTORICAL_COMPONENTS)
    ):
        raise ValueError(
            "Historical S3 Standard billing scope is unsupported."
        )

    usage = {}
    sources = set()
    evidence = []
    known_monthly = ZERO

    for item in selected:

        component = item.estimate

        if component.status not in (
            CostStatus.PRICED,
            CostStatus.ZERO_USAGE,
        ):
            raise ValueError(
                f"Historical component is incomplete: "
                f"{component.component}"
            )

        amount = _amount(
            component.usage,
            component.component,
        )

        monthly_cost = component.complete_monthly_cost

        if monthly_cost is None:
            raise ValueError(
                "Historical component has no complete cost."
            )

        if component.status == CostStatus.ZERO_USAGE:

            if amount != ZERO or monthly_cost != ZERO:
                raise ValueError(
                    "Historical zero-usage component is inconsistent."
                )

        else:

            if component.priced_usage != amount:
                raise ValueError(
                    "Historical usage is not fully priced."
                )

            if (
                item.resolution is None
                or len(item.resolution.records) != 1
            ):
                raise ValueError(
                    "Historical pricing evidence is unavailable."
                )

            record = item.resolution.records[0]

            if (
                record.service_code != "AmazonS3"
                or record.region != resource.region
                or record.pricing_model != PricingModel.ON_DEMAND
            ):
                raise ValueError(
                    "Historical storage pricing does not match the resource."
                )

            if record.source not in (
                PricingSource.FLOCI_PRICING_API,
                PricingSource.REFERENCE_DATA,
            ):
                raise ValueError(
                    "Unsupported historical storage pricing source."
                )

            sources.add(record.source)

            evidence.append(
                f"{component.component}: "
                f"SKU {record.sku}; "
                f"source {record.source_reference}"
            )

        known_monthly += monthly_cost

        usage[component.component] = amount

    scope = ComparisonScope(
        baseline_estimate_id=estimate.estimate_id,
        resource_id=resource.resource_id,
        components=STORAGE_COMPONENTS,
    )

    baseline = PricingOption(
        scope=scope,
        name="S3 Standard",
        pricing_model=PricingModel.ON_DEMAND,
        status=EstimateStatus.COMPLETE,
        known_monthly_cost=known_monthly,
        sources=tuple(
            sorted(
                sources,
                key=lambda item: item.value,
            )
        ),
        assumptions=STORAGE_ASSUMPTIONS,
        exclusions=STORAGE_EXCLUSIONS,
        detail=(
            "; ".join(evidence)
            if evidence
            else "All historical modeled charges are zero."
        ),
    )

    return StorageWorkload(
        baseline=baseline,
        region=resource.region,
        quantity=resource.quantity,
        storage_gb=usage["storage"],
        put_requests=usage["put_requests"],
        get_requests=usage["get_requests"],
        transfer_out_gb=usage["transfer_out"],
        retrieval_gb=retrieval_gb,
    )


def evaluate_storage(
    workload: StorageWorkload,
    assumptions: StorageRateAssumptions,
) -> StorageComparisonResult:

    """Compare an explicitly hypothetical alternative storage class."""

    if not isinstance(workload, StorageWorkload):
        raise ValueError(
            "Invalid storage workload."
        )

    if not isinstance(
        assumptions,
        StorageRateAssumptions,
    ):
        raise ValueError(
            "Invalid alternative storage pricing."
        )

    charges = (
        StorageCharge(
            component="storage",
            usage=workload.storage_gb,
            unit="GB-Mo",
            rate=assumptions.storage_per_gb_month,
            rate_basis=ONE,
        ),
        StorageCharge(
            component="put_requests",
            usage=workload.put_requests,
            unit="Requests",
            rate=assumptions.put_per_thousand,
            rate_basis=THOUSAND,
        ),
        StorageCharge(
            component="get_requests",
            usage=workload.get_requests,
            unit="Requests",
            rate=assumptions.get_per_thousand,
            rate_basis=THOUSAND,
        ),
        StorageCharge(
            component="retrieval",
            usage=workload.retrieval_gb,
            unit="GB",
            rate=assumptions.retrieval_per_gb,
            rate_basis=ONE,
        ),
        StorageCharge(
            component="transfer_out",
            usage=workload.transfer_out_gb,
            unit="GB",
            rate=assumptions.transfer_per_gb,
            rate_basis=ONE,
        ),
    )

    status, known = _summarize_charges(
        charges
    )

    rate_evidence = tuple(
        (
            f"{charge.component}: "
            f"USD {charge.rate} per "
            f"{charge.rate_basis} {charge.unit}."
        )
        if charge.rate is not None
        else f"{charge.component}: rate unavailable."
        for charge in charges
    )

    alternative = PricingOption(
        scope=workload.baseline.scope,
        name=f"S3 {assumptions.storage_class}",
        pricing_model=PricingModel.ON_DEMAND,
        status=status,
        known_monthly_cost=known,
        sources=(
            PricingSource.ESTIMATION_ASSUMPTION,
        ),
        assumptions=workload.baseline.assumptions + (
            "Alternative storage rates are explicitly hypothetical.",
            "No current AWS quotation is represented.",
            f"Region: {workload.region}.",
            f"Aggregate retrieval: {workload.retrieval_gb} GB.",
        ) + rate_evidence,
        exclusions=workload.baseline.exclusions,
        detail=STORAGE_CLASS_NOTES[
            assumptions.storage_class
        ],
    )

    return StorageComparisonResult(
        comparison=PricingComparison(
            workload.baseline,
            alternative,
        ),
        charges=charges,
    )
