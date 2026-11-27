"""Interactive infrastructure expenditure estimation and history."""

from decimal import Decimal

import pandas as pd
import streamlit as st

from finops.estimation.engine import InfrastructureCostEstimator

from finops.estimation.financial import (
    CostStatus,
    EstimateStatus,
    format_usd,
)

from finops.estimation.repository import (
    EstimateRepository,
    EstimateRepositoryError,
)

from finops.infrastructure.repository import (
    ScenarioRepository,
    ScenarioRepositoryError,
)


ZERO = Decimal("0")

STRICT_POLICY = "Floci only"
REFERENCE_POLICY = "Floci + supplementary reference pricing"

SERVICE_LABELS = {
    "AmazonEC2": "Amazon EC2 / EBS",
    "AmazonS3": "Amazon S3",
    "AWSLambda": "AWS Lambda",
    "AmazonDynamoDB": "Amazon DynamoDB",
    "AmazonRDS": "Amazon RDS",
}

SOURCE_LABELS = {
    "FLOCI_PRICING_API": "Floci Pricing API",
    "FLOCI_EC2_API": "Floci EC2 API",
    "REFERENCE_DATA": "Supplementary reference",
    "ESTIMATION_ASSUMPTION": "Estimation assumption",
}


def money(value):

    if value is None:
        return "Unavailable"

    return format_usd(value)


def exact(value):

    if value is None:
        return "Unknown"

    return format(value, "f")


def service_label(service_code):

    return SERVICE_LABELS.get(
        service_code,
        service_code,
    )


def policy_label(estimate):

    return (
        REFERENCE_POLICY
        if estimate.allow_reference
        else STRICT_POLICY
    )


def source_label(source):

    return SOURCE_LABELS.get(
        source.value,
        source.value,
    )


def component_source(item):

    status = item.estimate.status

    if status == CostStatus.ZERO_USAGE:
        return "Zero billable usage"

    if status == CostStatus.EXCLUDED:
        return "Excluded"

    if status == CostStatus.NOT_APPLICABLE:
        return "Not applicable"

    if (
        item.resolution is None
        or not item.resolution.records
    ):
        return "No resolved rate"

    sources = ", ".join(sorted({
        source_label(record.source)
        for record in item.resolution.records
    }))

    if status == CostStatus.UNRESOLVED:
        return f"Unused pricing evidence: {sources}"

    return sources


def render_estimate_overview(result):

    summary = result.summary

    st.subheader("Infrastructure cost overview")

    if summary.status == EstimateStatus.COMPLETE:

        st.success(
            "Complete estimate within the modeled billing scope."
        )

    elif summary.status == EstimateStatus.PARTIAL:

        st.warning(
            "Partial estimate: some usage or pricing remains "
            "unresolved. Known subtotals are not complete costs."
        )

    else:

        st.warning(
            "A usable infrastructure total could not be established."
        )

    st.caption(
        f"Scenario: {result.scenario.name} | "
        f"Revision: {result.scenario_revision} | "
        f"Pricing policy: {policy_label(result)}"
    )

    st.caption(
        f"Estimate ID: {result.estimate_id}"
    )

    st.caption(
        f"Evaluated: {result.evaluated_at.isoformat()} | "
        f"Calculation model: {result.model_version}"
    )

    periods = summary.complete_period_costs

    columns = st.columns(4)

    metrics = (
        (
            "Average hourly cost",
            None if periods is None else periods.average_hourly,
        ),
        (
            "Average daily cost",
            None if periods is None else periods.daily,
        ),
        (
            "Monthly cost",
            None if periods is None else periods.monthly,
        ),
        (
            "Annual cost",
            None if periods is None else periods.annual,
        ),
    )

    for column, (label, value) in zip(columns, metrics):

        column.metric(label, money(value))

    st.caption(
        "All amounts are USD. Average hourly cost distributes "
        "modeled monthly expenditure across 730 hours; it is "
        "not an EC2 instance running-hour rate."
    )

    if summary.status != EstimateStatus.COMPLETE:

        st.metric(
            "Known monthly subtotal",
            money(summary.known_monthly_cost),
        )

        if (
            summary.resolved_components
            or summary.partial_components
        ):

            known = summary.known_period_costs

            st.caption(
                "Known subtotal projections: "
                f"{money(known.daily)} per average day | "
                f"{money(known.annual)} per year."
            )

        else:

            st.caption(
                "A zero known subtotal does not establish "
                "that the infrastructure is free."
            )

    st.markdown("**Billing component coverage**")

    coverage = st.columns(5)

    counts = (
        ("Resolved", summary.resolved_components),
        ("Partial", summary.partial_components),
        ("Unresolved", summary.unresolved_components),
        ("Excluded", summary.excluded_components),
        ("Not applicable", summary.not_applicable_components),
    )

    for column, (label, count) in zip(coverage, counts):
        column.metric(label, count)


def summary_row(summary):

    periods = summary.complete_period_costs

    return {
        "Status": summary.status.value,
        "Known monthly subtotal": money(
            summary.known_monthly_cost
        ),
        "Average hourly": money(
            None if periods is None else periods.average_hourly
        ),
        "Daily": money(
            None if periods is None else periods.daily
        ),
        "Monthly": money(
            summary.complete_monthly_cost
        ),
        "Annual": money(
            None if periods is None else periods.annual
        ),
    }


def running_hour_rate(result, resource_id):

    for item in result.components:

        estimate = item.estimate

        if (
            item.billing.resource_id == resource_id
            and item.billing.component == "compute"
            and estimate.unit == "Hrs"
            and estimate.status == CostStatus.PRICED
            and estimate.usage is not None
            and estimate.usage > ZERO
        ):

            rate = (
                estimate.known_monthly_cost
                / estimate.usage
            )

            return f"${exact(rate)}/Hrs"

    return "N/A or unresolved"


def render_cost_breakdowns(result):

    st.subheader("Resource cost breakdown")

    resource_rows = []
    resource_chart = []

    for resource in result.scenario.resources:

        summary = result.resource_summary(
            resource.resource_id
        )

        resource_rows.append({
            "Resource": resource.name,
            "Service": service_label(resource.service_code),
            "Region": resource.region,
            "Quantity": resource.quantity,
            **summary_row(summary),
            "Effective running-hour rate": running_hour_rate(
                result,
                resource.resource_id,
            ),
        })

        resource_chart.append({
            "Resource": (
                f"{resource.name} "
                f"({str(resource.resource_id)[:8]})"
            ),
            "Known monthly cost (USD)": float(
                summary.known_monthly_cost
            ),
        })

    if resource_rows:

        st.dataframe(
            pd.DataFrame(resource_rows),
            hide_index=True,
        )

        st.caption(
            "Running-hour rates are effective rates per billed "
            "compute hour and are displayed where applicable."
        )

    else:

        st.info("This scenario contains no resource groups.")

    st.subheader("Service cost breakdown")

    service_rows = []
    service_chart = []

    for service_code in result.scenario.service_codes:

        summary = result.service_summary(service_code)

        service_rows.append({
            "Service": service_label(service_code),
            **summary_row(summary),
        })

        service_chart.append({
            "Service": service_label(service_code),
            "Known monthly cost (USD)": float(
                summary.known_monthly_cost
            ),
        })

    if service_rows:

        st.dataframe(
            pd.DataFrame(service_rows),
            hide_index=True,
        )

    st.subheader("Monthly cost distribution")

    st.caption(
        "Charts display known charges only. Unpriced consumption "
        "is not represented as an established zero cost."
    )

    if result.summary.known_monthly_cost > ZERO:

        left, right = st.columns(2)

        with left:

            st.markdown("**By resource**")

            st.bar_chart(
                pd.DataFrame(resource_chart),
                x="Resource",
                y="Known monthly cost (USD)",
                horizontal=True,
            )

        with right:

            st.markdown("**By AWS service**")

            st.bar_chart(
                pd.DataFrame(service_chart),
                x="Service",
                y="Known monthly cost (USD)",
                horizontal=True,
            )

    else:

        st.info(
            "No positive known charges are available to chart."
        )


def component_rows(result):

    resources = {
        resource.resource_id: resource
        for resource in result.scenario.resources
    }

    rows = []

    for item in result.components:

        resource = resources[item.billing.resource_id]
        estimate = item.estimate

        unpriced = (
            None
            if estimate.usage is None
            else estimate.usage - estimate.priced_usage
        )

        rows.append({
            "Resource": resource.name,
            "Resource ID": str(resource.resource_id),
            "Service": item.billing.service_code,
            "Region": resource.region,
            "Component": estimate.component,
            "Billing unit": estimate.unit,
            "Monthly usage": exact(estimate.usage),
            "Priced usage": exact(estimate.priced_usage),
            "Unpriced usage": exact(unpriced),
            "Status": estimate.status.value,
            "Known monthly subtotal (USD)": exact(
                estimate.known_monthly_cost
            ),
            "Complete monthly cost (USD)": (
                "Unavailable"
                if estimate.complete_monthly_cost is None
                else exact(estimate.complete_monthly_cost)
            ),
            "Pricing source": component_source(item),
            "Pricing pool": item.pool_id or "",
            "Explanation": estimate.detail,
        })

    return rows


def render_component_breakdown(result):

    st.subheader("Billing component details")

    rows = component_rows(result)

    if not rows:

        st.info("No billing components are available.")
        return

    table = pd.DataFrame(rows)

    status_filter = st.multiselect(
        "Filter component status",
        sorted(table["Status"].unique().tolist()),
        key=f"m4.filter.{result.estimate_id}",
    )

    displayed = (
        table[table["Status"].isin(status_filter)]
        if status_filter
        else table
    )

    st.dataframe(
        displayed,
        hide_index=True,
    )

    st.caption(
        "Component amounts are shown at calculation precision. "
        "Currency rounding is applied only to displayed totals."
    )

    # Export all components, not just the filtered table.

    export = table.copy()

    export.insert(
        0,
        "Estimate ID",
        str(result.estimate_id),
    )

    export.insert(
        1,
        "Scenario ID",
        str(result.scenario_id),
    )

    export.insert(
        2,
        "Scenario revision",
        result.scenario_revision,
    )

    export.insert(
        3,
        "Pricing policy",
        policy_label(result),
    )

    # Prevent user-controlled text from being interpreted as
    # spreadsheet formulas when opening the CSV.

    for column in export.columns:

        export[column] = export[column].map(
            lambda value: (
                "'" + value
                if isinstance(value, str)
                and value.lstrip().startswith(
                    ("=", "+", "-", "@")
                )
                else value
            )
        )

    st.download_button(
        "Download complete billing breakdown (CSV)",
        data=export.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"estimate-{result.estimate_id}.csv",
        mime="text/csv",
        key=f"m4.download.{result.estimate_id}",
    )


def render_pricing_evidence(result):

    st.subheader("Pricing evidence and diagnostics")

    resources = {
        resource.resource_id: resource
        for resource in result.scenario.resources
    }

    for item in result.components:

        resource = resources[item.billing.resource_id]

        title = (
            f"{resource.name} - "
            f"{item.billing.component} - "
            f"{item.estimate.status.value}"
        )

        with st.expander(title):

            st.write(item.estimate.detail)

            st.write(
                "Pricing source:",
                component_source(item),
            )

            if item.pool_id is not None:

                st.caption(
                    f"Pool: {item.pool_id} | "
                    f"Combined usage: {exact(item.pool_usage)} | "
                    f"Priced usage: {exact(item.pool_priced_usage)} | "
                    f"Known pooled cost: "
                    f"{money(item.pool_known_cost)}"
                )

            resolution = item.resolution

            if resolution is None:

                st.caption(
                    "No pricing resolution was required "
                    "or available for this component."
                )

                continue

            st.write(
                "Resolver status:",
                resolution.status.value,
            )

            if resolution.missing_components:

                st.warning(
                    "Missing pricing coverage: "
                    + ", ".join(resolution.missing_components)
                )

            for message in resolution.diagnostics:
                st.caption(message)

            for message in resolution.warnings:
                st.warning(message)

            for record in resolution.records:

                st.markdown("**Rate record**")

                st.write("Source:", source_label(record.source))
                st.write("SKU:", record.sku)
                st.write("Offer term:", record.offer_term_code)
                st.write("Source reference:", record.source_reference)

                if record.retrieved_at is not None:

                    st.caption(
                        f"Retrieved: {record.retrieved_at.isoformat()}"
                    )

                if record.verified_at is not None:

                    st.caption(
                        f"Verified: {record.verified_at.isoformat()}"
                    )

                if record.effective_date is not None:

                    st.caption(
                        f"Effective: {record.effective_date.isoformat()}"
                    )

                for assumption in record.assumptions:
                    st.caption(assumption)

                st.dataframe(
                    pd.DataFrame([
                        {
                            "Rate code": dimension.rate_code,
                            "Unit": dimension.unit,
                            "Currency": dimension.currency,
                            "Unit price": exact(
                                dimension.unit_price
                            ),
                            "Tier begins": exact(
                                dimension.begin_range
                            ),
                            "Tier ends": (
                                "Unbounded"
                                if dimension.end_range is None
                                else exact(dimension.end_range)
                            ),
                        }
                        for dimension in record.dimensions
                    ]),
                    hide_index=True,
                )


def render_assumptions(result):

    with st.expander("Financial assumptions and exclusions"):

        st.markdown("**Assumptions**")

        for assumption in result.assumptions:
            st.write(f"- {assumption}")

        st.markdown("**Excluded expenditure**")

        for exclusion in result.exclusions:
            st.write(f"- {exclusion}")

        st.caption(
            "Floci rates are emulator catalogue data. "
            "Supplementary reference rates are documented local "
            "pricing evidence, not a live AWS quotation."
        )


def render_result(result):

    render_estimate_overview(result)

    st.divider()

    render_cost_breakdowns(result)

    st.divider()

    render_component_breakdown(result)

    st.divider()

    render_pricing_evidence(result)

    render_assumptions(result)


def render_generate(scenario_repository, estimate_repository):

    st.subheader("Generate infrastructure estimate")

    try:

        scenarios = scenario_repository.list_scenarios()

    except ScenarioRepositoryError as error:

        st.error(str(error))
        return

    if not scenarios:

        st.info(
            "No saved infrastructure scenarios exist. "
            "Create one in the Infrastructure Builder first."
        )

        return

    available = {
        str(scenario.scenario_id): scenario
        for scenario in scenarios
    }

    selection = st.selectbox(
        "Infrastructure scenario",
        list(available),
        format_func=lambda value: (
            f"{available[value].name} | "
            f"revision {available[value].revision} | "
            f"{value[:8]}"
        ),
        key="m4.scenario",
    )

    scenario = available[selection]

    st.caption(
        f"{scenario.resource_group_count} resource groups | "
        f"{scenario.total_resource_count} total resources | "
        f"{len(scenario.service_codes)} AWS services"
    )

    policy = st.radio(
        "Pricing policy",
        [STRICT_POLICY, REFERENCE_POLICY],
        key="m4.policy",
    )

    allow_reference = policy == REFERENCE_POLICY

    st.caption(
        "Supplementary reference pricing is used only when "
        "enabled and permitted by the pricing resolver."
    )

    refresh = st.checkbox(
        "Refresh pricing catalogue when generating",
        value=False,
        key="m4.refresh",
    )

    if st.button(
        "Generate estimate",
        type="primary",
        disabled=not scenario.resources,
        key="m4.generate",
    ):

        # Do not display a previous result as a newly generated
        # estimate if the current generation attempt fails.

        st.session_state.pop("m4.result", None)

        try:

            with st.spinner("Resolving infrastructure pricing..."):

                result = InfrastructureCostEstimator().estimate(
                    scenario,
                    allow_reference=allow_reference,
                    force_refresh=refresh,
                )

        except (RuntimeError, ValueError, ArithmeticError) as error:

            st.error(f"Unable to generate estimate: {error}")

        else:

            st.session_state["m4.result"] = result

    result = st.session_state.get("m4.result")

    if result is None:
        return

    if result.scenario_id != scenario.scenario_id:

        st.info(
            "Generate an estimate for the selected scenario "
            "to view its expenditure."
        )

        return

    if result.scenario_revision != scenario.revision:

        st.warning(
            "The scenario has changed since this estimate was "
            "generated. The displayed result represents an "
            "older saved scenario revision."
        )

    if result.allow_reference != allow_reference:

        st.warning(
            "The selected pricing policy differs from the "
            "displayed estimate. Generate again to apply it."
        )

    already_saved = estimate_repository.estimate_path(
        result.estimate_id
    ).exists()

    if already_saved:

        st.success("This historical estimate has been saved.")

    if st.button(
        "Save historical estimate",
        disabled=already_saved,
        key="m4.save",
    ):

        try:

            estimate_repository.save(result)

        except (
            EstimateRepositoryError,
            ValueError,
            TypeError,
            ArithmeticError,
        ) as error:

            st.error(f"Unable to save estimate: {error}")

        else:

            st.success(
                "Historical estimate and pricing snapshot saved."
            )

    render_result(result)


def render_history(estimate_repository):

    st.subheader("Saved estimate history")

    try:

        estimates = estimate_repository.list_estimates()

    except EstimateRepositoryError as error:

        st.error(str(error))
        return

    if not estimates:

        st.info("No historical estimates have been saved.")
        return

    st.caption(
        "Historical estimates contain their original "
        "scenario revision and pricing snapshot. "
        "Reopening does not retrieve current pricing."
    )

    names = {
        str(estimate.scenario_id): estimate.scenario.name
        for estimate in estimates
    }

    scenario_filter = st.selectbox(
        "Filter saved estimates by scenario",
        ["all", *names],
        format_func=lambda value: (
            "All scenarios"
            if value == "all"
            else f"{names[value]} ({value[:8]})"
        ),
        key="m4.history.scenario",
    )

    filtered = tuple(
        estimate
        for estimate in estimates
        if (
            scenario_filter == "all"
            or str(estimate.scenario_id) == scenario_filter
        )
    )

    available = {
        str(estimate.estimate_id): estimate
        for estimate in filtered
    }

    st.dataframe(
        pd.DataFrame([
            {
                "Scenario": estimate.scenario.name,
                "Revision": estimate.scenario_revision,
                "Status": estimate.summary.status.value,
                "Pricing policy": policy_label(estimate),
                "Known monthly subtotal": money(
                    estimate.summary.known_monthly_cost
                ),
                "Complete monthly cost": money(
                    estimate.summary.complete_monthly_cost
                ),
                "Evaluated at": estimate.evaluated_at.isoformat(),
                "Estimate ID": str(estimate.estimate_id),
            }
            for estimate in filtered
        ]),
        hide_index=True,
    )

    selection = st.selectbox(
        "Historical estimate",
        list(available),
        format_func=lambda value: (
            f"{available[value].scenario.name} | "
            f"revision {available[value].scenario_revision} | "
            f"{available[value].summary.status.value} | "
            f"{value[:8]}"
        ),
        key=f"m4.history.estimate.{scenario_filter}",
    )

    result = available[selection]

    st.info("Viewing an immutable historical estimate.")

    render_result(result)


def run():

    st.set_page_config(
        page_title="Cost Estimator | Cloud FinOps",
        page_icon=":material/calculate:",
        layout="wide",
    )

    st.title("Cloud Infrastructure Cost Estimator")

    st.markdown(
        "Estimate hypothetical infrastructure expenditure "
        "using saved configurations and traceable pricing data."
    )

    mode = st.radio(
        "Estimator workspace",
        ["Generate estimate", "Saved estimates"],
        horizontal=True,
        key="m4.mode",
    )

    estimate_repository = EstimateRepository()

    if mode == "Generate estimate":

        render_generate(
            ScenarioRepository(),
            estimate_repository,
        )

    else:

        render_history(estimate_repository)


run()
