"""Application interface for historical cloud pricing comparisons.

The engine coordinates existing compute and storage calculators.
It does not duplicate their financial calculations.

Each infrastructure projection replaces one selected resource
billing scope while holding all other historical charges constant.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from finops.comparison.compute import (
    ComputeComparisonResult,
    ReservedAssumptions,
    SavingsPlanAssumptions,
    build_compute_workload,
    evaluate_reserved,
    evaluate_savings_plan,
    evaluate_spot,
)

from finops.comparison.models import (
    PricingComparison,
    PricingOption,
)

from finops.comparison.storage import (
    StorageComparisonResult,
    StorageRateAssumptions,
    build_storage_workload,
    evaluate_storage,
)

from finops.estimation.financial import EstimateStatus
from finops.estimation.repository import EstimateRepository

from finops.infrastructure.models import ResourceType
from finops.infrastructure.validation import MONTHS_PER_YEAR

from finops.pricing.models import (
    PricingModel,
    SpotPriceObservation,
)

from finops.pricing.spot import (
    SpotPricingService,
    SpotQuery,
)


ZERO = Decimal("0")


PROJECTION_ASSUMPTIONS = (
    "Each alternative replaces only the selected resource billing scope.",
    "All unrelated historical resource charges remain unchanged.",
    "Alternatives are independent and must not be added together.",
    "Account-wide repricing, discount interactions and migration are not modeled.",
    "Infrastructure projections require a complete historical infrastructure estimate.",
)


@dataclass(frozen=True, slots=True)
class ResourceEligibility:
    """Identify resources that support pricing comparison."""

    resource_id: UUID
    name: str
    resource_type: ResourceType
    region: str

    eligible: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ComparisonEntry:
    """One alternative and its optional infrastructure projection."""

    comparison: PricingComparison

    breakdown: (
        ComputeComparisonResult
        | StorageComparisonResult
        | None
    ) = None

    infrastructure_monthly_cost: Decimal | None = None

    @property
    def infrastructure_annual_cost(self):

        if self.infrastructure_monthly_cost is None:
            return None

        return (
            self.infrastructure_monthly_cost
            * MONTHS_PER_YEAR
        )


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    """Independent alternatives for one historical resource."""

    baseline: PricingOption

    entries: tuple[ComparisonEntry, ...]

    infrastructure_baseline_monthly_cost: Decimal | None

    projection_assumptions: tuple[str, ...] = PROJECTION_ASSUMPTIONS

    @property
    def comparable_entries(self):

        return tuple(
            entry
            for entry in self.entries
            if entry.comparison.is_comparable
        )

    @property
    def incomplete_entries(self):

        return tuple(
            entry
            for entry in self.entries
            if not entry.comparison.is_comparable
        )

    @property
    def infrastructure_baseline_annual_cost(self):

        if self.infrastructure_baseline_monthly_cost is None:
            return None

        return (
            self.infrastructure_baseline_monthly_cost
            * MONTHS_PER_YEAR
        )


class PricingComparisonEngine:

    def __init__(
        self,
        repository=None,
        spot_service=None,
    ):

        self.repository = (
            repository
            if repository is not None
            else EstimateRepository()
        )

        self._spot_service = spot_service

    def list_estimates(self, scenario_id=None):

        return self.repository.list_estimates(
            scenario_id
        )

    def load_estimate(self, estimate_id):

        return self.repository.load(
            estimate_id
        )

    def eligible_resources(self, estimate):

        """Inspect historical resources without retrieving new prices."""

        results = []

        for resource in estimate.scenario.resources:

            reason = ""

            try:

                if resource.resource_type == ResourceType.EC2_INSTANCE:

                    build_compute_workload(
                        estimate,
                        resource.resource_id,
                    )

                elif resource.resource_type == ResourceType.S3_BUCKET:

                    build_storage_workload(
                        estimate,
                        resource.resource_id,
                        retrieval_gb=ZERO,
                    )

                else:

                    reason = (
                        "Pricing comparison currently supports "
                        "eligible EC2 compute and S3 Standard resources."
                    )

            except ValueError as exc:

                reason = str(exc)

            results.append(
                ResourceEligibility(
                    resource_id=resource.resource_id,
                    name=resource.name,
                    resource_type=resource.resource_type,
                    region=resource.region,
                    eligible=not bool(reason),
                    reason=reason,
                )
            )

        return tuple(results)

    def _entry(
        self,
        estimate,
        comparison,
        breakdown=None,
    ):

        """Calculate a single-resource replacement projection."""

        projected = None

        total = estimate.summary.complete_monthly_cost

        if (
            total is not None
            and comparison.is_comparable
        ):

            original = (
                comparison.baseline.complete_monthly_cost
            )

            replacement = (
                comparison.alternative.complete_monthly_cost
            )

            if original > total:

                raise ValueError(
                    "Selected billing scope exceeds historical "
                    "infrastructure cost."
                )

            projected = (
                total
                - original
                + replacement
            )

        return ComparisonEntry(
            comparison=comparison,
            breakdown=breakdown,
            infrastructure_monthly_cost=projected,
        )

    def _report(
        self,
        estimate,
        baseline,
        entries,
    ):

        entries = tuple(entries)

        for entry in entries:

            if entry.comparison.baseline != baseline:

                raise ValueError(
                    "Report alternatives must share the same baseline."
                )

        return ComparisonReport(
            baseline=baseline,
            entries=entries,
            infrastructure_baseline_monthly_cost=(
                estimate.summary.complete_monthly_cost
            ),
        )

    def _unavailable_spot(
        self,
        estimate,
        workload,
        reason,
    ):

        alternative = PricingOption(
            scope=workload.baseline.scope,
            name="Spot - unavailable",
            pricing_model=PricingModel.SPOT,
            status=EstimateStatus.UNAVAILABLE,
            known_monthly_cost=ZERO,
            assumptions=workload.baseline.assumptions + (
                "No matching usable Spot price was obtained.",
            ),
            exclusions=workload.baseline.exclusions,
            detail=reason,
        )

        return self._entry(
            estimate,
            PricingComparison(
                workload.baseline,
                alternative,
            ),
        )

    def _spot_entries(
        self,
        estimate,
        workload,
        availability_zone,
    ):

        """Retrieve Floci Spot observations on explicit comparison.

        The most recent matching observation per availability zone
        is retained.

        A failed retrieval produces an unavailable Spot alternative.
        It does not invalidate otherwise usable commitment comparisons.
        """

        query = SpotQuery(
            instance_type=workload.instance_type,
            region=workload.region,
            product_description="Linux/UNIX",
            availability_zone=availability_zone,
        )

        try:

            if self._spot_service is None:

                self._spot_service = SpotPricingService()

            history = self._spot_service.refresh(
                query
            )

        except Exception as exc:

            return (
                self._unavailable_spot(
                    estimate,
                    workload,
                    (
                        "Spot pricing retrieval failed: "
                        f"{type(exc).__name__}. "
                        "No replacement rate was assumed."
                    ),
                ),
            )

        latest = {}

        for observation in history.observations:

            if not isinstance(
                observation,
                SpotPriceObservation,
            ):
                continue

            if (
                availability_zone is not None
                and observation.availability_zone != availability_zone
            ):
                continue

            if (
                observation.instance_type != workload.instance_type
                or observation.region != workload.region
                or observation.product_description != "Linux/UNIX"
            ):
                continue

            try:

                result = evaluate_spot(
                    workload,
                    observation,
                )

            except ValueError:

                continue

            zone = observation.availability_zone

            previous = latest.get(zone)

            timestamp = (
                observation.observed_at,
                observation.retrieved_at,
            )

            if previous is None or timestamp > previous[0]:

                latest[zone] = (
                    timestamp,
                    result,
                )

        if not latest:

            return (
                self._unavailable_spot(
                    estimate,
                    workload,
                    "No matching Spot observations were returned.",
                ),
            )

        return tuple(
            self._entry(
                estimate,
                latest[zone][1].comparison,
                latest[zone][1],
            )
            for zone in sorted(latest)
        )

    def compare_compute(
        self,
        estimate,
        resource_id,
        *,
        reserved: ReservedAssumptions | None = None,
        savings_plan: SavingsPlanAssumptions | None = None,
        include_spot: bool = True,
        availability_zone: str | None = None,
    ) -> ComparisonReport:

        """Compare selected EC2 purchasing alternatives."""

        if type(include_spot) is not bool:

            raise ValueError(
                "include_spot must be a Boolean."
            )

        if availability_zone is not None:

            if (
                not isinstance(availability_zone, str)
                or not availability_zone.strip()
            ):

                raise ValueError(
                    "Invalid availability zone."
                )

        workload = build_compute_workload(
            estimate,
            resource_id,
        )

        entries = []

        if reserved is not None:

            result = evaluate_reserved(
                workload,
                reserved,
            )

            entries.append(
                self._entry(
                    estimate,
                    result.comparison,
                    result,
                )
            )

        if savings_plan is not None:

            result = evaluate_savings_plan(
                workload,
                savings_plan,
            )

            entries.append(
                self._entry(
                    estimate,
                    result.comparison,
                    result,
                )
            )

        if include_spot:

            entries.extend(
                self._spot_entries(
                    estimate,
                    workload,
                    availability_zone,
                )
            )

        return self._report(
            estimate,
            workload.baseline,
            entries,
        )

    def compare_storage(
        self,
        estimate,
        resource_id,
        *,
        retrieval_gb: Decimal,
        alternatives: tuple[StorageRateAssumptions, ...],
    ) -> ComparisonReport:

        """Compare storage classes using one fixed workload."""

        if not isinstance(alternatives, tuple):

            raise ValueError(
                "Storage alternatives must be a tuple."
            )

        if any(
            not isinstance(item, StorageRateAssumptions)
            for item in alternatives
        ):

            raise ValueError(
                "Invalid storage pricing alternative."
            )

        classes = [
            item.storage_class
            for item in alternatives
        ]

        if len(classes) != len(set(classes)):

            raise ValueError(
                "Duplicate storage-class alternatives."
            )

        workload = build_storage_workload(
            estimate,
            resource_id,
            retrieval_gb=retrieval_gb,
        )

        entries = []

        for assumptions in alternatives:

            result = evaluate_storage(
                workload,
                assumptions,
            )

            entries.append(
                self._entry(
                    estimate,
                    result.comparison,
                    result,
                )
            )

        return self._report(
            estimate,
            workload.baseline,
            entries,
        )
