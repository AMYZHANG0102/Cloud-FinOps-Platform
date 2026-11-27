"""Interactive historical cloud pricing comparisons."""

import csv
import io

from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from finops.comparison.compute import (
    ComputeComparisonResult,
    ReservedAssumptions,
    SavingsPlanAssumptions,
    build_compute_workload,
)

from finops.comparison.engine import PricingComparisonEngine

from finops.comparison.models import (
    format_percentage,
    format_signed_usd,
)

from finops.comparison.storage import (
    STORAGE_CLASSES,
    STORAGE_CLASS_NOTES,
    StorageComparisonResult,
    StorageRateAssumptions,
    build_storage_workload,
)

from finops.estimation.financial import EstimateStatus

from finops.infrastructure.models import ResourceType


ZERO = Decimal("0")

RESULT_KEY = "m5.result"

STORAGE_DEFAULTS = {
    "Standard - Infrequent Access": "0.0125",
    "One Zone - Infrequent Access": "0.010",
    "Glacier Flexible Retrieval": "0.004",
    "Glacier Deep Archive": "0.001",
}


def _decimal(text, label, *, optional=False):

    value = text.strip()

    if not value and optional:
        return None

    try:

        amount = Decimal(value)

    except InvalidOperation as exc:

        raise ValueError(
            f"{label} must be a valid decimal number."
        ) from exc

    if not amount.is_finite() or amount < ZERO:

        raise ValueError(
            f"{label} must be finite and nonnegative."
        )

    return amount


def _money(value):

    return format_signed_usd(value)


def _exact(value):

    return "" if value is None else format(value, "f")


def _sources(option):

    return (
        ", ".join(
            source.value
            for source in option.sources
        )
        or "No priced source"
    )


def _annual(option):

    periods = option.complete_period_costs

    return None if periods is None else periods.annual


def _safe_text(value):

    text = str(value)

    if (
        text.startswith(("\t", "\r", "\n"))
        or text.lstrip().startswith(("=", "+", "-", "@"))
    ):

        return "'" + text

    return text


def _estimate_label(estimate):

    return (
        f"{estimate.scenario.name} | "
        f"Revision {estimate.scenario_revision} | "
        f"{estimate.summary.status.value} | "
        f"{estimate.estimate_id}"
    )


def _resource_label(resource):

    return (
        f"{resource.name} | "
        f"{resource.region} | "
        f"{resource.resource_id}"
    )


def _comparison_rows(report):

    baseline = report.baseline

    rows = [
        {
            "Option": baseline.name,
            "Status": baseline.status.value,
            "Pricing sources": _sources(baseline),
            "Known monthly subtotal": _money(
                baseline.known_monthly_cost
            ),
            "Monthly cost": _money(
                baseline.complete_monthly_cost
            ),
            "Annual cost": _money(
                _annual(baseline)
            ),
            "Monthly savings": "Baseline",
            "Annual savings": "Baseline",
            "Savings percentage": "Baseline",
            "Infrastructure monthly cost": _money(
                report.infrastructure_baseline_monthly_cost
            ),
            "Infrastructure annual cost": _money(
                report.infrastructure_baseline_annual_cost
            ),
        }
    ]

    for entry in report.entries:

        comparison = entry.comparison
        option = comparison.alternative

        rows.append(
            {
                "Option": option.name,
                "Status": option.status.value,
                "Pricing sources": _sources(option),
                "Known monthly subtotal": _money(
                    option.known_monthly_cost
                ),
                "Monthly cost": _money(
                    option.complete_monthly_cost
                ),
                "Annual cost": _money(
                    _annual(option)
                ),
                "Monthly savings": _money(
                    comparison.monthly_savings
                ),
                "Annual savings": _money(
                    comparison.annual_savings
                ),
                "Savings percentage": format_percentage(
                    comparison.savings_percentage
                ),
                "Infrastructure monthly cost": _money(
                    entry.infrastructure_monthly_cost
                ),
                "Infrastructure annual cost": _money(
                    entry.infrastructure_annual_cost
                ),
            }
        )

    return rows


def _comparison_csv(estimate, resource, report):

    """Export exact financial values rather than rounded display values."""

    output = io.StringIO(newline="")

    fields = (
        "baseline_estimate_id",
        "scenario_id",
        "scenario_name",
        "scenario_revision",
        "resource_id",
        "resource_name",
        "region",
        "billing_components",
        "option",
        "pricing_model",
        "status",
        "pricing_sources",
        "known_monthly_subtotal_usd",
        "complete_monthly_cost_usd",
        "complete_annual_cost_usd",
        "monthly_savings_usd",
        "annual_savings_usd",
        "savings_percentage",
        "infrastructure_monthly_cost_usd",
        "infrastructure_annual_cost_usd",
        "pricing_detail",
        "assumptions",
        "exclusions",
        "projection_assumptions",
    )

    writer = csv.DictWriter(
        output,
        fieldnames=fields,
    )

    writer.writeheader()

    def write_option(
        option,
        *,
        comparison=None,
        infrastructure_monthly=None,
        infrastructure_annual=None,
    ):

        writer.writerow(
            {
                "baseline_estimate_id": str(
                    estimate.estimate_id
                ),
                "scenario_id": str(
                    estimate.scenario_id
                ),
                "scenario_name": _safe_text(
                    estimate.scenario.name
                ),
                "scenario_revision": estimate.scenario_revision,
                "resource_id": str(
                    resource.resource_id
                ),
                "resource_name": _safe_text(
                    resource.name
                ),
                "region": _safe_text(
                    resource.region
                ),
                "billing_components": "; ".join(
                    option.scope.components
                ),
                "option": _safe_text(
                    option.name
                ),
                "pricing_model": option.pricing_model.value,
                "status": option.status.value,
                "pricing_sources": _sources(option),
                "known_monthly_subtotal_usd": _exact(
                    option.known_monthly_cost
                ),
                "complete_monthly_cost_usd": _exact(
                    option.complete_monthly_cost
                ),
                "complete_annual_cost_usd": _exact(
                    _annual(option)
                ),
                "monthly_savings_usd": (
                    _exact(comparison.monthly_savings)
                    if comparison is not None
                    else ""
                ),
                "annual_savings_usd": (
                    _exact(comparison.annual_savings)
                    if comparison is not None
                    else ""
                ),
                "savings_percentage": (
                    _exact(comparison.savings_percentage)
                    if comparison is not None
                    else ""
                ),
                "infrastructure_monthly_cost_usd": _exact(
                    infrastructure_monthly
                ),
                "infrastructure_annual_cost_usd": _exact(
                    infrastructure_annual
                ),
                "pricing_detail": _safe_text(
                    option.detail
                ),
                "assumptions": _safe_text(
                    " | ".join(option.assumptions)
                ),
                "exclusions": _safe_text(
                    " | ".join(option.exclusions)
                ),
                "projection_assumptions": _safe_text(
                    " | ".join(report.projection_assumptions)
                ),
            }
        )

    write_option(
        report.baseline,
        infrastructure_monthly=(
            report.infrastructure_baseline_monthly_cost
        ),
        infrastructure_annual=(
            report.infrastructure_baseline_annual_cost
        ),
    )

    for entry in report.entries:

        write_option(
            entry.comparison.alternative,
            comparison=entry.comparison,
            infrastructure_monthly=(
                entry.infrastructure_monthly_cost
            ),
            infrastructure_annual=(
                entry.infrastructure_annual_cost
            ),
        )

    return output.getvalue().encode("utf-8-sig")


def _render_evidence(option):

    st.caption(
        f"Pricing sources: {_sources(option)}"
    )

    if option.detail:
        st.write(option.detail)

    if option.assumptions:

        st.markdown("**Assumptions**")

        for item in option.assumptions:
            st.write(f"- {item}")

    if option.exclusions:

        st.markdown("**Exclusions**")

        for item in option.exclusions:
            st.write(f"- {item}")


def _render_compute_breakdown(result):

    st.markdown("**Compute cost breakdown**")

    rows = (
        (
            "Covered instance-hours",
            str(result.covered_instance_hours),
        ),
        (
            "Uncovered On-Demand hours",
            str(result.uncovered_on_demand_hours),
        ),
        (
            "Monthly upfront amortization",
            _money(result.monthly_upfront_amortization),
        ),
        (
            "Monthly commitment charge",
            _money(result.monthly_commitment_charge),
        ),
        (
            "Monthly uncovered On-Demand charge",
            _money(result.monthly_on_demand_charge),
        ),
        (
            "Monthly Spot charge",
            _money(result.monthly_spot_charge),
        ),
    )

    breakdown = list(rows)

    if result.unused_reserved_hours is not None:

        breakdown.append(
            (
                "Unused reserved instance-hours",
                str(result.unused_reserved_hours),
            )
        )

    if result.unused_savings_plan_commitment is not None:

        breakdown.append(
            (
                "Unused monthly spending commitment",
                _money(
                    result.unused_savings_plan_commitment
                ),
            )
        )

    if result.term_months is not None:

        breakdown.extend(
            (
                (
                    "Commitment term (months)",
                    str(result.term_months),
                ),
                (
                    "Modeled resource cost over commitment term",
                    _money(result.modeled_term_cost),
                ),
            )
        )

    st.dataframe(
        pd.DataFrame(
            breakdown,
            columns=("Component", "Value"),
        ),
        hide_index=True,
        use_container_width=True,
    )


def _render_storage_breakdown(result):

    st.markdown("**Storage cost breakdown**")

    rows = []

    for charge in result.charges:

        rows.append(
            {
                "Component": charge.component,
                "Usage": str(charge.usage),
                "Unit": charge.unit,
                "USD rate": (
                    str(charge.rate)
                    if charge.rate is not None
                    else "Unavailable"
                ),
                "Rate basis": str(charge.rate_basis),
                "Status": charge.status.value,
                "Monthly cost": _money(
                    charge.monthly_cost
                ),
            }
        )

    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
    )

    if result.unresolved_components:

        st.warning(
            "Unresolved billing components: "
            + ", ".join(
                result.unresolved_components
            )
        )


def _render_report(estimate, resource, report):

    st.divider()

    st.subheader("Pricing comparison results")

    st.caption(
        f"Historical estimate: {estimate.estimate_id} | "
        f"Resource: {resource.name}"
    )

    first, second, third = st.columns(3)

    first.metric(
        "Resource baseline monthly cost",
        _money(
            report.baseline.complete_monthly_cost
        ),
    )

    second.metric(
        "Infrastructure baseline monthly cost",
        _money(
            report.infrastructure_baseline_monthly_cost
        ),
    )

    third.metric(
        "Complete alternatives",
        f"{len(report.comparable_entries)} / {len(report.entries)}",
    )

    if report.infrastructure_baseline_monthly_cost is None:

        st.warning(
            "The historical infrastructure baseline is incomplete. "
            "Resource-level comparisons remain available, but complete "
            "infrastructure projections are unavailable."
        )

    if report.incomplete_entries:

        st.warning(
            "Some alternatives have incomplete pricing. Known subtotals "
            "are not complete costs. Definitive savings are unavailable "
            "for those alternatives."
        )

    st.info(
        "Alternatives are independent. Each infrastructure projection "
        "replaces only the selected resource's billing scope. "
        "Do not add savings or projections together."
    )

    st.dataframe(
        pd.DataFrame(
            _comparison_rows(report)
        ),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Monthly resource cost comparison")

    chart_rows = [
        {
            "Option": report.baseline.name,
            "Monthly cost (USD)": float(
                report.baseline.complete_monthly_cost
            ),
        }
    ]

    for entry in report.comparable_entries:

        option = entry.comparison.alternative

        chart_rows.append(
            {
                "Option": option.name,
                "Monthly cost (USD)": float(
                    option.complete_monthly_cost
                ),
            }
        )

    st.bar_chart(
        pd.DataFrame(chart_rows),
        x="Option",
        y="Monthly cost (USD)",
    )

    st.caption(
        "Only complete modeled resource costs are shown in the chart."
    )

    if report.infrastructure_baseline_monthly_cost is not None:

        st.subheader(
            "Projected monthly infrastructure cost"
        )

        projection_rows = [
            {
                "Option": "Original infrastructure",
                "Monthly cost (USD)": float(
                    report.infrastructure_baseline_monthly_cost
                ),
            }
        ]

        for entry in report.entries:

            if entry.infrastructure_monthly_cost is None:
                continue

            projection_rows.append(
                {
                    "Option": (
                        entry.comparison.alternative.name
                    ),
                    "Monthly cost (USD)": float(
                        entry.infrastructure_monthly_cost
                    ),
                }
            )

        st.bar_chart(
            pd.DataFrame(projection_rows),
            x="Option",
            y="Monthly cost (USD)",
        )

    st.subheader("Cost breakdowns and pricing evidence")

    with st.expander(
        f"{report.baseline.name} - baseline evidence"
    ):

        _render_evidence(report.baseline)

    for entry in report.entries:

        option = entry.comparison.alternative

        with st.expander(
            f"{option.name} - cost breakdown and evidence"
        ):

            st.write(
                f"Modeled cost status: {option.status.value}"
            )

            if isinstance(
                entry.breakdown,
                ComputeComparisonResult,
            ):

                _render_compute_breakdown(
                    entry.breakdown
                )

            elif isinstance(
                entry.breakdown,
                StorageComparisonResult,
            ):

                _render_storage_breakdown(
                    entry.breakdown
                )

            _render_evidence(option)

    with st.expander(
        "Infrastructure projection assumptions"
    ):

        for item in report.projection_assumptions:
            st.write(f"- {item}")

    st.download_button(
        "Download comparison CSV",
        data=_comparison_csv(
            estimate,
            resource,
            report,
        ),
        file_name=(
            f"pricing-comparison-"
            f"{estimate.estimate_id}-"
            f"{resource.resource_id}.csv"
        ),
        mime="text/csv",
        key="m5.download",
    )

    st.caption(
        "The CSV includes the baseline, every generated alternative, "
        "exact financial values, pricing sources and assumptions."
    )


def _compute_inputs(workload, prefix):

    st.subheader("EC2 purchasing model comparison")

    first, second, third, fourth = st.columns(4)

    first.metric(
        "Instance type",
        workload.instance_type,
    )

    second.metric(
        "Instance quantity",
        workload.quantity,
    )

    third.metric(
        "Monthly instance-hours",
        str(workload.total_instance_hours),
    )

    fourth.metric(
        "Historical On-Demand rate",
        f"${_exact(workload.on_demand_rate)}/h",
    )

    st.caption(
        "Compute charges only. EBS storage, networking and other "
        "infrastructure charges remain outside this resource comparison."
    )

    st.warning(
        "Reserved Instance and Savings Plans rates are illustrative "
        "assumptions, not retrieved commercial AWS quotations."
    )

    is_demo = (
        workload.instance_type == "t3.micro"
        and workload.on_demand_rate == Decimal("0.0104")
    )

    default_reserved_rate = (
        "0.005"
        if is_demo
        else _exact(
            workload.on_demand_rate * Decimal("0.5")
        )
    )

    default_discounted_rate = (
        "0.006"
        if is_demo
        else _exact(
            workload.on_demand_rate * Decimal("0.6")
        )
    )

    # Keep the default discounted rate positive even for a
    # hypothetical zero-rate historical offer.

    if Decimal(default_discounted_rate) == ZERO:
        default_discounted_rate = "0.001"

    default_count = min(
        2,
        workload.quantity,
    )

    include_reserved = st.checkbox(
        "Include Reserved Instances",
        value=True,
        key=f"{prefix}.reserved.enabled",
    )

    reserved = None

    if include_reserved:

        with st.expander(
            "Reserved Instance assumptions",
            expanded=True,
        ):

            left, right = st.columns(2)

            quantity = left.number_input(
                "Reserved instance quantity",
                min_value=0,
                value=default_count,
                step=1,
                key=f"{prefix}.reserved.quantity",
            )

            recurring = right.text_input(
                "Reserved recurring rate (USD/hour)",
                value=default_reserved_rate,
                key=f"{prefix}.reserved.rate",
            )

            upfront = left.text_input(
                "Upfront payment per instance (USD)",
                value="12" if is_demo else "0",
                key=f"{prefix}.reserved.upfront",
            )

            term = right.selectbox(
                "Reserved commitment term (months)",
                options=(12, 36),
                key=f"{prefix}.reserved.term",
            )

            reserved = (
                int(quantity),
                recurring,
                upfront,
                term,
            )

            st.caption(
                "Reserved commitments incur recurring charges even "
                "during unused instance-hours."
            )

    include_savings = st.checkbox(
        "Include Savings Plan",
        value=True,
        key=f"{prefix}.savings.enabled",
    )

    savings = None

    if include_savings:

        with st.expander(
            "Savings Plan assumptions",
            expanded=True,
        ):

            left, right = st.columns(2)

            commitment = left.text_input(
                "Hourly spending commitment (USD)",
                value=_exact(
                    Decimal(default_count)
                    * Decimal(default_discounted_rate)
                ),
                key=f"{prefix}.savings.commitment",
            )

            discounted = right.text_input(
                "Discounted instance rate (USD/hour)",
                value=default_discounted_rate,
                key=f"{prefix}.savings.rate",
            )

            term = st.selectbox(
                "Savings Plan commitment term (months)",
                options=(12, 36),
                key=f"{prefix}.savings.term",
            )

            savings = (
                commitment,
                discounted,
                term,
            )

            st.caption(
                "No-upfront commitment model. Unused hourly "
                "commitments do not roll forward."
            )

    include_spot = st.checkbox(
        "Include Floci Spot pricing",
        value=True,
        key=f"{prefix}.spot.enabled",
    )

    zone = ""

    if include_spot:

        zone = st.text_input(
            "Spot availability zone (optional)",
            value="",
            placeholder="All available zones, or e.g. us-east-1a",
            key=f"{prefix}.spot.zone",
        )

        st.caption(
            "Spot prices are retrieved from Floci when you generate "
            "the comparison. Observation and retrieval timestamps are "
            "shown in the pricing evidence. Price stability and capacity "
            "availability are not guaranteed."
        )

    return (
        reserved,
        savings,
        include_spot,
        zone,
    )


def _generate_compute(
    engine,
    estimate,
    resource,
    inputs,
):

    reserved_values, savings_values, include_spot, zone = inputs

    reserved = None
    savings = None

    if reserved_values is not None:

        quantity, recurring, upfront, term = reserved_values

        reserved = ReservedAssumptions(
            reserved_quantity=quantity,
            hourly_recurring_rate=_decimal(
                recurring,
                "Reserved recurring rate",
            ),
            upfront_per_instance=_decimal(
                upfront,
                "Reserved upfront payment",
            ),
            term_months=term,
        )

    if savings_values is not None:

        commitment, discounted, term = savings_values

        savings = SavingsPlanAssumptions(
            hourly_commitment=_decimal(
                commitment,
                "Hourly spending commitment",
            ),
            discounted_hourly_rate=_decimal(
                discounted,
                "Discounted instance rate",
            ),
            term_months=term,
        )

    return engine.compare_compute(
        estimate,
        resource.resource_id,
        reserved=reserved,
        savings_plan=savings,
        include_spot=include_spot,
        availability_zone=(
            zone.strip() or None
        ) if include_spot else None,
    )


def _storage_inputs(workload, prefix):

    st.subheader("S3 storage-class comparison")

    first, second, third = st.columns(3)

    first.metric(
        "Stored data (GB)",
        str(workload.storage_gb),
    )

    second.metric(
        "PUT requests",
        str(workload.put_requests),
    )

    third.metric(
        "GET requests",
        str(workload.get_requests),
    )

    st.write(
        f"Monthly outbound transfer: "
        f"{workload.transfer_out_gb} GB"
    )

    st.warning(
        "Alternative storage rates are illustrative assumptions. "
        "Minimum retention, transition charges, object-size overhead "
        "and archival restoration costs are not fully modeled."
    )

    if workload.get_requests > ZERO:

        retrieval = st.text_input(
            "Monthly retrieval volume (GB)",
            value="0",
            key=f"{prefix}.storage.retrieval",
        )

        retrieval_required = True

    else:

        retrieval = "0"
        retrieval_required = False

        st.caption(
            "The historical workload has zero GET requests, "
            "so modeled retrieval volume is fixed at zero."
        )

    classes = st.multiselect(
        "Alternative storage classes",
        options=STORAGE_CLASSES,
        default=list(STORAGE_CLASSES),
        key=f"{prefix}.storage.classes",
    )

    values = []

    for storage_class in classes:

        class_prefix = (
            f"{prefix}.storage."
            f"{STORAGE_CLASSES.index(storage_class)}"
        )

        with st.expander(
            f"{storage_class} pricing assumptions",
            expanded=True,
        ):

            st.caption(
                STORAGE_CLASS_NOTES[storage_class]
            )

            storage_rate = st.text_input(
                "Storage rate (USD/GB-month)",
                value=STORAGE_DEFAULTS[storage_class],
                key=f"{class_prefix}.capacity",
            )

            put_rate = ""

            if workload.put_requests > ZERO:

                put_rate = st.text_input(
                    "PUT rate (USD/1,000 requests)",
                    value="",
                    key=f"{class_prefix}.put",
                )

            get_rate = ""

            if workload.get_requests > ZERO:

                get_rate = st.text_input(
                    "GET rate (USD/1,000 requests)",
                    value="",
                    key=f"{class_prefix}.get",
                )

            retrieval_rate = ""

            if retrieval_required:

                retrieval_rate = st.text_input(
                    "Retrieval rate (USD/GB)",
                    value="",
                    key=f"{class_prefix}.retrieval",
                )

            transfer_rate = ""

            if workload.transfer_out_gb > ZERO:

                transfer_rate = st.text_input(
                    "Outbound transfer rate (USD/GB)",
                    value="",
                    key=f"{class_prefix}.transfer",
                )

            st.caption(
                "Blank rate means unavailable. Enter 0 only when "
                "explicitly assuming a zero rate. Zero-usage components "
                "do not require a rate."
            )

            values.append(
                (
                    storage_class,
                    storage_rate,
                    put_rate,
                    get_rate,
                    retrieval_rate,
                    transfer_rate,
                )
            )

    return (
        retrieval,
        tuple(values),
    )


def _generate_storage(
    engine,
    estimate,
    resource,
    inputs,
):

    retrieval, values = inputs

    alternatives = []

    for item in values:

        (
            storage_class,
            storage_rate,
            put_rate,
            get_rate,
            retrieval_rate,
            transfer_rate,
        ) = item

        alternatives.append(
            StorageRateAssumptions(
                storage_class=storage_class,
                storage_per_gb_month=_decimal(
                    storage_rate,
                    "Storage rate",
                    optional=True,
                ),
                put_per_thousand=_decimal(
                    put_rate,
                    "PUT rate",
                    optional=True,
                ),
                get_per_thousand=_decimal(
                    get_rate,
                    "GET rate",
                    optional=True,
                ),
                retrieval_per_gb=_decimal(
                    retrieval_rate,
                    "Retrieval rate",
                    optional=True,
                ),
                transfer_per_gb=_decimal(
                    transfer_rate,
                    "Outbound transfer rate",
                    optional=True,
                ),
            )
        )

    return engine.compare_storage(
        estimate,
        resource.resource_id,
        retrieval_gb=_decimal(
            retrieval,
            "Monthly retrieval volume",
        ),
        alternatives=tuple(alternatives),
    )


def main():

    st.set_page_config(
        page_title="Cloud Pricing Model Comparison",
        layout="wide",
    )

    st.title(
        "Cloud Pricing Model Comparison"
    )

    st.write(
        "Compare equivalent resource workloads across purchasing "
        "models and storage classes using saved infrastructure "
        "estimates and traceable pricing information."
    )

    engine = PricingComparisonEngine()

    try:

        history = engine.list_estimates()

    except Exception as exc:

        st.error(
            "Unable to load saved infrastructure estimates: "
            f"{type(exc).__name__}."
        )

        return

    if not history:

        st.info(
            "No saved infrastructure estimates are available. "
            "Generate and save an estimate in the Cost Estimator first."
        )

        return

    st.subheader(
        "Historical infrastructure baseline"
    )

    estimates = {
        _estimate_label(item): item
        for item in history
    }

    selected = st.selectbox(
        "Saved infrastructure estimate",
        options=list(estimates),
        key="m5.estimate",
    )

    estimate = estimates[selected]

    st.caption(
        f"Scenario revision {estimate.scenario_revision} | "
        f"Pricing policy: "
        f"{'Floci + supplementary reference pricing' if estimate.allow_reference else 'Floci only'}"
    )

    first, second, third = st.columns(3)

    first.metric(
        "Historical estimate status",
        estimate.summary.status.value,
    )

    second.metric(
        "Known monthly subtotal",
        _money(
            estimate.summary.known_monthly_cost
        ),
    )

    third.metric(
        "Complete infrastructure monthly cost",
        _money(
            estimate.summary.complete_monthly_cost
        ),
    )

    if estimate.summary.status != EstimateStatus.COMPLETE:

        st.warning(
            "This historical infrastructure estimate is incomplete. "
            "Fully priced individual resources can still be compared."
        )

    try:

        eligibility = engine.eligible_resources(
            estimate
        )

    except Exception as exc:

        st.error(
            "Unable to inspect historical resource eligibility: "
            f"{type(exc).__name__}."
        )

        return

    with st.expander(
        "Resource comparison eligibility"
    ):

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Resource": item.name,
                        "Type": item.resource_type.value,
                        "Region": item.region,
                        "Eligibility": (
                            "Eligible"
                            if item.eligible
                            else "Unsupported"
                        ),
                        "Reason": item.reason,
                    }
                    for item in eligibility
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    resources = {
        _resource_label(item): item
        for item in eligibility
        if item.eligible
    }

    if not resources:

        st.info(
            "No eligible resources are available in this estimate."
        )

        return

    resource_label = st.selectbox(
        "Resource to compare",
        options=list(resources),
        key=f"m5.resource.{estimate.estimate_id}",
    )

    resource = resources[resource_label]

    prefix = (
        f"m5.{estimate.estimate_id}."
        f"{resource.resource_id}"
    )

    try:

        if resource.resource_type == ResourceType.EC2_INSTANCE:

            workload = build_compute_workload(
                estimate,
                resource.resource_id,
            )

            inputs = _compute_inputs(
                workload,
                prefix,
            )

            can_generate = any(
                (
                    inputs[0] is not None,
                    inputs[1] is not None,
                    inputs[2],
                )
            )

            generate = _generate_compute

        elif resource.resource_type == ResourceType.S3_BUCKET:

            workload = build_storage_workload(
                estimate,
                resource.resource_id,
                retrieval_gb=ZERO,
            )

            inputs = _storage_inputs(
                workload,
                prefix,
            )

            can_generate = bool(inputs[1])

            generate = _generate_storage

        else:

            st.error(
                "Unsupported resource type."
            )

            return

    except ValueError as exc:

        st.error(str(exc))
        return

    signature = (
        estimate.estimate_id,
        resource.resource_id,
        inputs,
    )

    if not can_generate:

        st.info(
            "Select at least one alternative pricing model."
        )

    if st.button(
        "Generate comparison",
        type="primary",
        disabled=not can_generate,
        key="m5.generate",
    ):

        # Never leave an earlier result visible after a failed
        # generation attempt.

        st.session_state.pop(
            RESULT_KEY,
            None,
        )

        try:

            with st.spinner(
                "Calculating pricing alternatives..."
            ):

                report = generate(
                    engine,
                    estimate,
                    resource,
                    inputs,
                )

            st.session_state[RESULT_KEY] = (
                signature,
                report,
            )

        except ValueError as exc:

            st.error(str(exc))

        except Exception as exc:

            st.error(
                "Unable to generate the pricing comparison: "
                f"{type(exc).__name__}."
            )

    saved = st.session_state.get(
        RESULT_KEY
    )

    if saved is None:
        return

    saved_signature, report = saved

    if saved_signature != signature:

        st.info(
            "Comparison inputs have changed. Generate a new comparison "
            "to view results for the current selection."
        )

        return

    _render_report(
        estimate,
        resource,
        report,
    )


if __name__ == "__main__":
    main()
