"""Interactive configuration of hypothetical cloud infrastructure."""

from dataclasses import replace
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from finops.infrastructure.models import (
    InfrastructureScenario,
    ResourceConfiguration,
    ResourceType,
)

from finops.infrastructure.repository import (
    ScenarioConflictError,
    ScenarioRepository,
    ScenarioRepositoryError,
)

from finops.infrastructure.validation import (
    MONTHLY_HOURS,
    get_resource_specification,
    get_usage_fields,
    validate_resource,
    validate_scenario,
)


REGIONS = (
    "us-east-1",
    "us-east-2",
    "us-west-2",
    "ca-central-1",
    "eu-west-1",
    "eu-central-1",
    "ap-southeast-1",
)

OTHER_REGION = "Other region"
NEW_RESOURCE = "new"


def activate_scenario(scenario, message):

    st.session_state["m3.snapshot"] = scenario

    st.session_state["m3.pending"] = (
        str(scenario.scenario_id)
        if scenario is not None
        else None
    )

    st.session_state["m3.epoch"] += 1
    st.session_state["m3.message"] = message

    st.rerun()


def resource_label(resource):

    specification = get_resource_specification(
        resource.resource_type
    )

    return specification.label


def render_create_scenario(repository, expanded):

    with st.expander(
        "Create a new infrastructure scenario",
        expanded=expanded,
    ):

        name = st.text_input(
            "New scenario name",
            key="m3.create.name",
            placeholder="E-commerce Production",
        )

        description = st.text_area(
            "New scenario description",
            key="m3.create.description",
        )

        if st.button(
            "Create scenario",
            type="primary",
            key="m3.create",
        ):

            try:

                saved = repository.create(
                    InfrastructureScenario(
                        name=name.strip(),
                        description=description.strip(),
                    )
                )

            except (ScenarioRepositoryError, ValueError) as error:
                st.error(str(error))

            else:

                activate_scenario(
                    saved,
                    "Infrastructure scenario created.",
                )


def render_summary(scenario):

    validation = validate_scenario(scenario)

    st.subheader("Scenario overview")

    columns = st.columns(4)

    columns[0].metric(
        "Resource groups",
        scenario.resource_group_count,
    )

    columns[1].metric(
        "Total resources",
        scenario.total_resource_count,
    )

    columns[2].metric(
        "AWS services",
        len(scenario.service_codes),
    )

    columns[3].metric(
        "Saved revision",
        scenario.revision,
    )

    st.caption(
        f"Scenario ID: {scenario.scenario_id}"
    )

    st.caption(
        f"Last saved: {scenario.updated_at.isoformat()}"
    )

    if not scenario.resources:

        st.info(
            "This scenario is an empty draft. "
            "Add resources to build your infrastructure."
        )

        return

    if not validation.is_complete:

        missing = sum(
            len(result.missing_usage)
            for _, result in validation.resource_results
        )

        st.warning(
            f"This scenario contains {missing} unknown usage "
            "fields. Unknown usage is not treated as zero."
        )

    else:

        st.success(
            "All usage fields in the current configuration "
            "specification have been supplied."
        )

    st.caption(
        "Usage completeness does not guarantee pricing "
        "availability or complete AWS billing coverage."
    )

    rows = []

    for resource in scenario.resources:

        result = validate_resource(resource)

        rows.append({
            "Resource": resource.name,
            "Service": resource_label(resource),
            "Region": resource.region,
            "Quantity": resource.quantity,
            "Configuration": ", ".join(
                f"{key}={value}"
                for key, value
                in resource.configuration.items()
            ),
            "Pricing model": "On-Demand",
            "Usage status": (
                "Complete"
                if result.is_complete
                else "Incomplete"
            ),
        })

    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
    )

    with st.expander("Saved resource usage details"):

        for resource in scenario.resources:

            st.markdown(
                f"**{resource.name} - "
                f"{resource_label(resource)}**"
            )

            rows = []

            for field in get_usage_fields(
                resource.resource_type,
                resource.configuration,
            ):

                value = resource.usage.get(field.key)

                rows.append({
                    "Expected usage per resource": field.label,
                    "Value": (
                        "Unknown"
                        if value is None
                        else format(value, "f")
                    ),
                    "Unit": field.unit,
                })

            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
            )


def render_scenario_details(repository, scenario, prefix):

    with st.expander("Edit scenario details"):

        name = st.text_input(
            "Scenario name",
            value=scenario.name,
            key=f"{prefix}.name",
        )

        description = st.text_area(
            "Scenario description",
            value=scenario.description,
            key=f"{prefix}.description",
        )

        if st.button(
            "Save scenario details",
            key=f"{prefix}.save_details",
        ):

            try:

                saved = repository.update(
                    replace(
                        scenario,
                        name=name.strip(),
                        description=description.strip(),
                    )
                )

            except (ScenarioRepositoryError, ValueError) as error:
                st.error(str(error))

            else:

                activate_scenario(
                    saved,
                    "Scenario details saved.",
                )


def render_configuration_fields(
    resource_type,
    original,
    prefix,
):

    specification = get_resource_specification(resource_type)
    configuration = {}

    columns = st.columns(2)

    for index, field in enumerate(
        specification.configuration_fields
    ):

        column = columns[index % 2]

        value = (
            original.configuration.get(field.key)
            if original is not None
            else field.default
        )

        key = f"{prefix}.configuration.{field.key}"

        if field.value_type is bool:

            selected = column.checkbox(
                field.label,
                value=bool(value),
                key=key,
            )

        elif field.choices:

            default_index = (
                field.choices.index(value)
                if value in field.choices
                else 0
            )

            selected = column.selectbox(
                field.label,
                list(field.choices),
                index=default_index,
                key=key,
            )

        else:

            selected = column.text_input(
                field.label,
                value="" if value is None else str(value),
                key=key,
            ).strip()

            if not selected:
                continue

        configuration[field.key] = selected

    return configuration


def render_usage_fields(
    resource_type,
    configuration,
    original,
    prefix,
):

    st.markdown("**Expected usage per resource**")

    st.caption(
        "Leave an input blank if its usage is unknown. "
        "Enter 0 only when zero consumption is intended."
    )

    fields = get_usage_fields(
        resource_type,
        configuration,
    )

    raw_usage = {}
    columns = st.columns(2)

    for index, field in enumerate(fields):

        value = (
            original.usage.get(field.key)
            if original is not None
            else field.default
        )

        raw_usage[field.key] = columns[index % 2].text_input(
            f"{field.label} ({field.unit})",
            value="" if value is None else format(value, "f"),
            key=f"{prefix}.usage.{field.key}",
        ).strip()

    return raw_usage


def parse_usage(raw_usage):

    usage = {}

    for key, value in raw_usage.items():

        if not value:

            usage[key] = None
            continue

        try:

            usage[key] = Decimal(value)

        except InvalidOperation as error:

            raise ValueError(
                f"Enter a valid number for {key}."
            ) from error

    return usage


def render_resource_editor(repository, scenario, prefix):

    st.subheader("Configure infrastructure resources")

    existing = {
        str(resource.resource_id): resource
        for resource in scenario.resources
    }

    selection = st.selectbox(
        "Resource to configure",
        [NEW_RESOURCE, *existing],
        format_func=lambda value: (
            "Add a new resource"
            if value == NEW_RESOURCE
            else (
                f"{existing[value].name} - "
                f"{resource_label(existing[value])} "
                f"({value[:8]})"
            )
        ),
        key=f"{prefix}.resource_selection",
    )

    original = existing.get(selection)

    if original is None:

        selected_type = st.selectbox(
            "Cloud resource type",
            [item.value for item in ResourceType],
            format_func=lambda value: (
                get_resource_specification(
                    ResourceType(value)
                ).label
            ),
            key=f"{prefix}.resource_type",
        )

        resource_type = ResourceType(selected_type)

    else:

        resource_type = original.resource_type

        st.caption(
            f"Editing {resource_label(original)}. "
            "Resource identity will be preserved."
        )

    specification = get_resource_specification(
        resource_type
    )

    editor = (
        f"{prefix}.resource.{selection}."
        f"{resource_type.value}"
    )

    first, second, third = st.columns(3)

    name = first.text_input(
        "Resource name",
        value=(
            original.name
            if original is not None
            else specification.label
        ),
        key=f"{editor}.name",
    )

    quantity = second.text_input(
        "Resource quantity",
        value=(
            str(original.quantity)
            if original is not None
            else "1"
        ),
        key=f"{editor}.quantity",
        help="Number of identically configured resources.",
    )

    original_region = (
        original.region
        if original is not None
        else "us-east-1"
    )

    regions = list(dict.fromkeys([
        *REGIONS,
        original_region,
        OTHER_REGION,
    ]))

    selected_region = third.selectbox(
        "AWS region",
        regions,
        index=regions.index(original_region),
        key=f"{editor}.region",
    )

    region = (
        third.text_input(
            "Custom AWS region",
            key=f"{editor}.custom_region",
        ).strip()
        if selected_region == OTHER_REGION
        else selected_region
    )

    st.markdown("**Resource configuration**")

    configuration = render_configuration_fields(
        resource_type,
        original,
        editor,
    )

    raw_usage = render_usage_fields(
        resource_type,
        configuration,
        original,
        editor,
    )

    st.caption(
        "All quantities and usage estimates are hypothetical. "
        "No actual cloud resources will be provisioned."
    )

    if st.button(
        "Add resource" if original is None else "Save resource changes",
        type="primary",
        key=f"{editor}.save",
    ):

        try:

            values = {
                "name": name.strip(),
                "region": region,
                "quantity": int(quantity),
                "configuration": configuration,
                "usage": parse_usage(raw_usage),
            }

            if original is None:

                resource = ResourceConfiguration(
                    resource_type=resource_type,
                    **values,
                )

            else:

                resource = replace(original, **values)

            validation = validate_resource(resource)

            if not validation.is_valid:

                raise ValueError(
                    " | ".join(
                        issue.message
                        for issue in validation.errors
                    )
                )

            if original is None:

                resources = (
                    *scenario.resources,
                    resource,
                )

            else:

                resources = tuple(
                    resource
                    if item.resource_id == original.resource_id
                    else item
                    for item in scenario.resources
                )

            saved = repository.update(
                replace(
                    scenario,
                    resources=resources,
                )
            )

        except (
            ScenarioRepositoryError,
            ValueError,
            ArithmeticError,
        ) as error:

            st.error(str(error))

        else:

            activate_scenario(
                saved,
                "Resource configuration saved.",
            )

    if original is not None:

        confirmed = st.checkbox(
            "Confirm removal of this resource group",
            key=f"{editor}.remove_confirm",
        )

        if st.button(
            "Remove resource",
            disabled=not confirmed,
            key=f"{editor}.remove",
        ):

            try:

                saved = repository.update(
                    replace(
                        scenario,
                        resources=tuple(
                            item
                            for item in scenario.resources
                            if item.resource_id != original.resource_id
                        ),
                    )
                )

            except ScenarioRepositoryError as error:
                st.error(str(error))

            else:

                activate_scenario(
                    saved,
                    "Resource group removed.",
                )


def render_scenario_management(
    repository,
    scenario,
    prefix,
):

    with st.expander("Duplicate or delete scenario"):

        duplicate_name = st.text_input(
            "Duplicate scenario name",
            value=f"{scenario.name} (copy)",
            key=f"{prefix}.duplicate_name",
        )

        if st.button(
            "Duplicate scenario",
            key=f"{prefix}.duplicate",
        ):

            try:

                current = repository.load(
                    scenario.scenario_id
                )

                if current.revision != scenario.revision:

                    raise ScenarioConflictError(
                        "The saved scenario has changed. "
                        "Reload before duplicating."
                    )

                saved = repository.duplicate(
                    scenario.scenario_id,
                    duplicate_name.strip(),
                )

            except (ScenarioRepositoryError, ValueError) as error:
                st.error(str(error))

            else:

                activate_scenario(
                    saved,
                    "Independent scenario copy created.",
                )

        st.divider()

        st.warning(
            "Deleting a scenario removes its saved configuration. "
            "Pricing caches and other scenario files are preserved."
        )

        confirmed = st.checkbox(
            "Confirm deletion of the selected scenario",
            key=f"{prefix}.delete_confirm",
        )

        if st.button(
            "Delete scenario",
            disabled=not confirmed,
            key=f"{prefix}.delete",
        ):

            try:

                repository.delete(
                    scenario.scenario_id,
                    expected_revision=scenario.revision,
                )

            except ScenarioRepositoryError as error:
                st.error(str(error))

            else:

                activate_scenario(
                    None,
                    "Scenario deleted.",
                )


def run():

    st.set_page_config(
        page_title="Infrastructure Builder | Cloud FinOps",
        page_icon=":material/dns:",
        layout="wide",
    )

    st.title("Cloud Infrastructure Builder")

    st.markdown(
        "Design, save and manage hypothetical cloud infrastructure "
        "for subsequent cost estimation and pricing comparison."
    )

    st.caption(
        f"On-Demand baseline | "
        f"{MONTHLY_HOURS} hours per average month | "
        "Usage is specified per resource"
    )

    st.session_state.setdefault("m3.epoch", 0)

    message = st.session_state.pop("m3.message", None)

    if message:
        st.success(message)

    repository = ScenarioRepository()

    try:

        scenarios = repository.list_scenarios()

    except ScenarioRepositoryError as error:

        st.error(f"Unable to load saved scenarios: {error}")
        return

    render_create_scenario(
        repository,
        expanded=not scenarios,
    )

    if not scenarios:

        st.info("No infrastructure scenarios have been saved.")
        return

    saved = {
        str(scenario.scenario_id): scenario
        for scenario in scenarios
    }

    if "m3.pending" in st.session_state:

        pending = st.session_state.pop("m3.pending")

        st.session_state["m3.selected"] = (
            pending if pending in saved else None
        )

    if (
        "m3.selected" in st.session_state
        and st.session_state["m3.selected"] not in saved
    ):

        st.session_state["m3.selected"] = None

    selection = st.selectbox(
        "Saved infrastructure scenario",
        list(saved),
        index=0,
        format_func=lambda value: (
            f"{saved[value].name} ({value[:8]})"
        ),
        key="m3.selected",
        placeholder="Select a saved scenario",
    )

    if selection is None:

        st.info("Select a saved scenario to continue.")
        return

    snapshot = st.session_state.get("m3.snapshot")

    if (
        snapshot is None
        or str(snapshot.scenario_id) != selection
    ):

        snapshot = saved[selection]

        st.session_state["m3.snapshot"] = snapshot
        st.session_state["m3.epoch"] += 1

    current = saved[selection]

    if current.revision != snapshot.revision:

        st.warning(
            "A newer saved revision exists. "
            "Reload the scenario before saving further changes."
        )

    if st.button(
        "Reload saved scenario",
        key="m3.reload",
    ):

        activate_scenario(
            current,
            "Latest saved scenario loaded.",
        )

    prefix = f"m3.edit.{st.session_state['m3.epoch']}"

    st.caption(
        "Inputs are not saved automatically. Switching scenarios "
        "or reloading discards changes that have not been saved."
    )

    render_summary(snapshot)

    render_scenario_details(
        repository,
        snapshot,
        prefix,
    )

    st.divider()

    render_resource_editor(
        repository,
        snapshot,
        prefix,
    )

    st.divider()

    render_scenario_management(
        repository,
        snapshot,
        prefix,
    )

    st.info(
        "Saved scenarios will be available to the "
        "Cloud Infrastructure Cost Estimator in Module 4."
    )


run()
