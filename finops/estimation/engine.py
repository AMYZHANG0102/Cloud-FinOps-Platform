"""Estimate hypothetical infrastructure expenditure.

The engine combines infrastructure billing quantities with the
existing pricing resolver and graduated financial calculations.

Compatible billing quantities are pooled before tier calculation.
Known subtotals remain distinct from complete modeled costs.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from finops.estimation.components import (
    BillingComponent,
    build_scenario_components,
)

from finops.estimation.financial import (
    ComponentEstimate,
    CostStatus,
    calculate_tier_charge,
    summarize_components,
)

from finops.infrastructure.models import InfrastructureScenario

from finops.pricing.models import (
    PricingResolution,
    PricingSource,
    ResolutionStatus,
)

from finops.pricing.resolver import PricingResolver


ZERO = Decimal("0")

ESTIMATION_MODEL_VERSION = "1.0"

ASSUMPTIONS = (
    "All modeled resources belong to one hypothetical billing account.",
    "The average billing month contains 730 hours.",
    "Annual projections assume unchanged monthly consumption and rates.",
    "Resource quantity is applied once during billing component mapping.",
    "Compatible pricing offers are pooled within their regional billing scope.",
    "Pooled charges and priced usage are allocated proportionally.",
    "Unknown consumption is excluded from the quantified pool and remains unresolved.",
    "All monetary amounts are expressed in USD.",
)

EXCLUSIONS = (
    "Taxes, promotional credits and free-tier allowances.",
    "Reserved Instance and Savings Plans commitments.",
    "Support plans, discounts and negotiated private pricing.",
    "Charges outside the current infrastructure component specification.",
    "Additional storage lifecycle and minimum-duration adjustments.",
)


@dataclass(frozen=True, slots=True)
class EstimatedComponent:
    """Billing input, financial outcome and pricing provenance."""

    billing: BillingComponent
    estimate: ComponentEstimate
    resolution: PricingResolution | None = None

    pool_id: str | None = None
    pool_usage: Decimal | None = None
    pool_priced_usage: Decimal | None = None
    pool_known_cost: Decimal | None = None


@dataclass(frozen=True, slots=True)
class InfrastructureEstimate:
    """Immutable estimation result associated with a scenario revision."""

    scenario: InfrastructureScenario

    components: tuple[EstimatedComponent, ...]

    allow_reference: bool

    estimate_id: UUID = field(default_factory=uuid4)

    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    model_version: str = ESTIMATION_MODEL_VERSION

    assumptions: tuple[str, ...] = ASSUMPTIONS
    exclusions: tuple[str, ...] = EXCLUSIONS

    @property
    def scenario_id(self):
        return self.scenario.scenario_id

    @property
    def scenario_revision(self):
        return self.scenario.revision

    @property
    def summary(self):

        return summarize_components(
            item.estimate
            for item in self.components
        )

    def resource_summary(self, resource_id):

        if not any(
            resource.resource_id == resource_id
            for resource in self.scenario.resources
        ):
            raise ValueError("Unknown scenario resource.")

        return summarize_components(
            item.estimate
            for item in self.components
            if item.billing.resource_id == resource_id
        )

    def service_summary(self, service_code):

        if service_code not in self.scenario.service_codes:
            raise ValueError("Unknown scenario service.")

        return summarize_components(
            item.estimate
            for item in self.components
            if item.billing.service_code == service_code
        )


def _query_key(query, unit):

    return (
        query.service_code,
        query.resource_type,
        query.region,
        query.pricing_model.value,
        query.cost_component,
        query.currency,
        unit,
        tuple(sorted(query.attributes.items())),
    )


def _offer_key(billing, record, dimensions):
    """Identify compatible resolved offers without using timestamps
    that merely describe when a catalogue was retrieved.
    """

    return (
        billing.service_code,
        billing.query.resource_type,
        billing.query.region,
        billing.query.pricing_model.value,
        billing.component,
        billing.unit,
        billing.query.currency,
        record.source.value,
        record.source_reference,
        record.sku,
        record.offer_term_code,
        record.effective_date,
        record.catalogue_version,
        tuple(sorted(record.attributes.items())),
        tuple(sorted(record.term_attributes.items())),
        tuple(
            (
                item.rate_code,
                item.unit,
                item.currency,
                item.unit_price,
                item.begin_range,
                item.end_range,
                item.cost_component,
                item.applies_to,
            )
            for item in dimensions
        ),
    )


def _component_result(
    billing,
    status,
    *,
    priced_usage=ZERO,
    known_cost=ZERO,
    resolution=None,
    detail="",
    pool_id=None,
    pool_usage=None,
    pool_priced_usage=None,
    pool_known_cost=None,
):

    explanation = " ".join(
        value
        for value in (billing.detail, detail)
        if value
    )

    return EstimatedComponent(
        billing=billing,
        estimate=ComponentEstimate(
            resource_id=billing.resource_id,
            component=billing.component,
            unit=billing.unit,
            status=status,
            usage=billing.usage,
            priced_usage=priced_usage,
            known_monthly_cost=known_cost,
            detail=explanation,
        ),
        resolution=resolution,
        pool_id=pool_id,
        pool_usage=pool_usage,
        pool_priced_usage=pool_priced_usage,
        pool_known_cost=pool_known_cost,
    )


def _unresolved(billing, detail, resolution=None):

    return _component_result(
        billing,
        CostStatus.UNRESOLVED,
        detail=detail,
        resolution=resolution,
    )


class InfrastructureCostEstimator:
    """Resolve pricing and calculate modeled infrastructure expenditure."""

    def __init__(self, resolver=None):

        self.resolver = (
            PricingResolver()
            if resolver is None
            else resolver
        )

    def estimate(
        self,
        scenario,
        *,
        allow_reference=False,
        force_refresh=False,
    ):

        if not isinstance(scenario, InfrastructureScenario):
            raise TypeError("InfrastructureScenario required.")

        if type(allow_reference) is not bool:
            raise ValueError("allow_reference must be boolean.")

        if type(force_refresh) is not bool:
            raise ValueError("force_refresh must be boolean.")

        billings = build_scenario_components(scenario)

        results = {}

        query_groups = defaultdict(list)
        offer_groups = defaultdict(list)

        # Resolve exclusions, unknown usage and zero usage first.

        for index, billing in enumerate(billings):

            if billing.excluded:

                results[index] = _component_result(
                    billing,
                    CostStatus.EXCLUDED,
                )

            elif billing.usage is None:

                results[index] = _unresolved(
                    billing,
                    "Expected billing usage is unknown.",
                )

            elif billing.usage == ZERO:

                results[index] = _component_result(
                    billing,
                    CostStatus.ZERO_USAGE,
                    detail=(
                        "Calculated billable usage is zero. "
                        "No rate lookup is required."
                    ),
                )

            elif billing.query is None:

                results[index] = _unresolved(
                    billing,
                    "Positive usage has no supported pricing query.",
                )

            else:

                key = _query_key(
                    billing.query,
                    billing.unit,
                )

                query_groups[key].append(index)

        # Resolve identical queries using their combined usage.

        for indices in query_groups.values():

            first = billings[indices[0]]

            combined_usage = sum(
                (billings[index].usage for index in indices),
                ZERO,
            )

            resolution = self.resolver.resolve(
                first.query,
                usage=combined_usage,
                allow_reference=allow_reference,
                force_refresh=force_refresh,
            )

            if not isinstance(resolution, PricingResolution):
                raise TypeError("Invalid pricing resolver response.")

            if resolution.query != first.query:
                raise ValueError("Pricing response query mismatch.")

            if resolution.status not in (
                ResolutionStatus.RESOLVED,
                ResolutionStatus.PARTIAL,
            ):

                for index in indices:

                    results[index] = _unresolved(
                        billings[index],
                        f"Pricing resolution: {resolution.status.value}.",
                        resolution,
                    )

                continue

            # Do not combine competing pricing offers.

            if len(resolution.records) != 1:

                for index in indices:

                    results[index] = _unresolved(
                        billings[index],
                        "A unique compatible pricing offer is required.",
                        resolution,
                    )

                continue

            record = resolution.records[0]

            allowed_sources = {
                PricingSource.FLOCI_PRICING_API,
            }

            if allow_reference:
                allowed_sources.add(
                    PricingSource.REFERENCE_DATA
                )

            if record.source not in allowed_sources:

                for index in indices:

                    results[index] = _unresolved(
                        billings[index],
                        "Pricing source is outside the selected policy.",
                        resolution,
                    )

                continue

            dimensions = tuple(sorted(
                (
                    dimension
                    for dimension in record.dimensions
                    if (
                        dimension.cost_component
                        == first.component
                        and dimension.unit == first.unit
                        and dimension.currency == "USD"
                    )
                ),
                key=lambda item: (
                    item.begin_range,
                    item.rate_code,
                ),
            ))

            try:

                if not dimensions:
                    raise ValueError(
                        "No matching billing dimensions."
                    )

                preliminary = calculate_tier_charge(
                    combined_usage,
                    dimensions,
                )

                if (
                    resolution.status == ResolutionStatus.PARTIAL
                    and preliminary.status == CostStatus.PRICED
                ):

                    raise ValueError(
                        "Partial resolution cannot establish full coverage."
                    )

            except ValueError as error:

                for index in indices:

                    results[index] = _unresolved(
                        billings[index],
                        f"Invalid pricing coverage: {error}",
                        resolution,
                    )

                continue

            key = _offer_key(
                first,
                record,
                dimensions,
            )

            for index in indices:

                offer_groups[key].append(
                    (index, resolution, dimensions)
                )

        # Pool compatible resolved offers and price the pooled usage.

        for pool_number, members in enumerate(
            offer_groups.values(),
            start=1,
        ):

            pool_id = f"pool-{pool_number}"

            pool_usage = sum(
                (
                    billings[index].usage
                    for index, _, _ in members
                ),
                ZERO,
            )

            dimensions = members[0][2]

            charge = calculate_tier_charge(
                pool_usage,
                dimensions,
            )

            remaining_usage = pool_usage
            remaining_priced = charge.priced_usage
            remaining_cost = charge.known_cost

            # Allocate pooled charges proportionally while preserving
            # the exact aggregate and assigning rounding residue
            # to the final member of the pool.

            for position, (
                index,
                resolution,
                _,
            ) in enumerate(members):

                billing = billings[index]

                usage = billing.usage

                final_member = (
                    position == len(members) - 1
                )

                if final_member:

                    priced_usage = remaining_priced
                    known_cost = remaining_cost

                else:

                    usage_after = remaining_usage - usage

                    if charge.priced_usage == pool_usage:

                        priced_usage = usage

                    else:

                        proportional_usage = (
                            remaining_priced
                            * usage
                            / remaining_usage
                        )

                        lower = max(
                            ZERO,
                            remaining_priced - usage_after,
                        )

                        upper = min(
                            usage,
                            remaining_priced,
                        )

                        priced_usage = min(
                            upper,
                            max(lower, proportional_usage),
                        )

                    if remaining_priced == ZERO:

                        known_cost = ZERO

                    elif priced_usage == remaining_priced:

                        known_cost = remaining_cost

                    else:

                        known_cost = min(
                            remaining_cost,
                            remaining_cost
                            * priced_usage
                            / remaining_priced,
                        )

                if priced_usage == ZERO:

                    status = CostStatus.UNRESOLVED

                elif priced_usage == usage:

                    status = CostStatus.PRICED

                else:

                    status = CostStatus.PARTIAL

                results[index] = _component_result(
                    billing,
                    status,
                    priced_usage=priced_usage,
                    known_cost=known_cost,
                    resolution=resolution,
                    detail=(
                        f"Pricing pool {pool_id}: "
                        f"{len(members)} resource component(s), "
                        f"pooled usage {pool_usage}, "
                        f"priced usage {charge.priced_usage}."
                    ),
                    pool_id=pool_id,
                    pool_usage=pool_usage,
                    pool_priced_usage=charge.priced_usage,
                    pool_known_cost=charge.known_cost,
                )

                remaining_usage -= usage
                remaining_priced -= priced_usage
                remaining_cost -= known_cost

            if any(
                value != ZERO
                for value in (
                    remaining_usage,
                    remaining_priced,
                    remaining_cost,
                )
            ):

                raise ArithmeticError(
                    "Pricing pool allocation did not reconcile."
                )

        if len(results) != len(billings):
            raise RuntimeError(
                "Some billing components were not evaluated."
            )

        return InfrastructureEstimate(
            scenario=scenario,
            components=tuple(
                results[index]
                for index in range(len(billings))
            ),
            allow_reference=allow_reference,
        )
