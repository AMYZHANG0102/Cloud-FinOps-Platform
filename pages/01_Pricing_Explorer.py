"""M1 - Cloud Service Pricing Explorer.

Displays pricing retrieved from the local Floci emulator.
Financial calculations remain in the reusable FinOps packages.
"""

import csv
import io

import pandas as pd
import streamlit as st

from botocore.exceptions import BotoCoreError, ClientError

from finops.pricing.reference import (
    ReferenceCatalogueError,
    load_reference_rates,
)

from finops.pricing.spot import (
    SpotPricingError,
    SpotPricingService,
    SpotQuery,
)


from finops.pricing.cache import (
    PricingCacheError,
    PricingCatalogueCache,
)

from finops.pricing.client import (
    DEFAULT_FLOCI_ENDPOINT,
    UnsafeEndpointError,
    create_pricing_client,
)

from finops.pricing.discovery import (
    PricingDiscovery,
    PricingDiscoveryError,
)

from finops.pricing.products import (
    PricingProductError,
    ProductFilter,
)


# Display labels only. Prices and advertised values come from Floci.

SERVICE_LABELS = {
    "AmazonEC2": "Amazon EC2",
    "AmazonS3": "Amazon S3",
    "AWSLambda": "AWS Lambda",
    "AmazonDynamoDB": "Amazon DynamoDB",
}

ATTRIBUTE_LABELS = {
    "instanceType": "Instance type",
    "operatingSystem": "Operating system",
    "tenancy": "Tenancy",
    "productFamily": "Product family",
    "volumeType": "Storage volume type",
    "storageClass": "Storage class",
    "group": "Billing group",
}

PREFERRED_ATTRIBUTES = {
    "AmazonEC2": (
        "instanceType",
        "operatingSystem",
        "tenancy",
        "productFamily",
    ),
    "AmazonS3": (
        "volumeType",
        "storageClass",
        "productFamily",
    ),
    "AWSLambda": (
        "group",
        "productFamily",
    ),
}

EXPECTED_ERRORS = (
    PricingDiscoveryError,
    PricingProductError,
    PricingCacheError,
    UnsafeEndpointError,
    BotoCoreError,
    ValueError,
)


def service_label(code):
    return SERVICE_LABELS.get(code, code)


def resource_label(record):
    """Human-readable configuration description."""

    attributes = record.attributes

    if record.service_code == "AmazonEC2":
        return attributes.get(
            "instanceType",
            record.product_family,
        )

    if record.service_code == "AmazonS3":
        return attributes.get(
            "volumeType",
            attributes.get(
                "storageClass",
                record.product_family,
            ),
        )

    if record.service_code == "AWSLambda":
        return attributes.get(
            "group",
            record.product_family,
        )

    return record.product_family


def error_label(error):
    """Avoid exposing unnecessary SDK request details."""

    if isinstance(
        error,
        (PricingDiscoveryError, PricingProductError),
    ):

        message = f"{error.operation}: {error.code}"

        if error.http_status is not None:
            message += f" (HTTP {error.http_status})"

        return message

    if isinstance(error, PricingCacheError):
        return str(error)

    if isinstance(error, UnsafeEndpointError):
        return "The local endpoint safety policy blocked the request."

    return type(error).__name__


def discover_services():

    client = create_pricing_client()

    try:
        return PricingDiscovery(client).list_services()

    finally:
        client.close()


def discover_filter_options(service):

    attributes = service.attribute_names

    region_field = None

    if "regionCode" in attributes:
        region_field = "regionCode"

    elif "location" in attributes:
        region_field = "location"

    preferred = PREFERRED_ATTRIBUTES.get(
        service.service_code,
        tuple(
            item
            for item in attributes
            if item not in ("regionCode", "location")
        ),
    )

    selected_attributes = tuple(
        item
        for item in preferred
        if item in attributes
    )

    fields = (
        (region_field,)
        if region_field is not None
        else ()
    ) + selected_attributes

    client = create_pricing_client()

    try:

        discovery = PricingDiscovery(client)

        values = {
            field: discovery.list_attribute_values(
                service.service_code,
                field,
            )
            for field in fields
        }

        # Some Floci catalogues advertise regionCode but do not
        # return regionCode values. Use location where available.

        if (
            region_field == "regionCode"
            and not values["regionCode"]
            and "location" in attributes
        ):

            region_field = "location"

            values["location"] = (
                discovery.list_attribute_values(
                    service.service_code,
                    "location",
                )
            )

        return region_field, selected_attributes, values

    finally:
        client.close()


def catalogue_rows(catalogue):

    rows = []

    for record in catalogue.records:

        for dimension in record.dimensions:

            rows.append({
                "Service": service_label(record.service_code),
                "Resource": resource_label(record),
                "Region": record.region,
                "Operating system": record.attributes.get(
                    "operatingSystem", ""
                ),
                "Pricing model": record.pricing_model.value,
                "Cost component": (
                    dimension.cost_component
                    or "Unclassified"
                ),
                "Currency": dimension.currency,
                "Unit price": format(
                    dimension.unit_price, "f"
                ),
                "Billing unit": dimension.unit,
                "Tier start": format(
                    dimension.begin_range, "f"
                ),
                "Tier end (exclusive)": (
                    "Unbounded"
                    if dimension.end_range is None
                    else format(
                        dimension.end_range, "f"
                    )
                ),
                "SKU": record.sku,
                "Rate code": dimension.rate_code,
                "Offer term": record.offer_term_code,
                "Source": record.source.value,
                "Source reference": record.source_reference,
                "Catalogue version": (
                    record.catalogue_version or ""
                ),
                "Effective date": (
                    record.effective_date.isoformat()
                    if record.effective_date
                    else ""
                ),
                "Retrieved at (UTC)": (
                    record.retrieved_at.isoformat()
                    if record.retrieved_at
                    else ""
                ),
            })

    return rows


def csv_bytes(rows):

    output = io.StringIO()

    writer = csv.DictWriter(
        output,
        fieldnames=list(rows[0]),
    )

    writer.writeheader()
    writer.writerows(rows)

    return output.getvalue().encode("utf-8-sig")


def render_comparable_chart(catalogue):

    entries = []

    for record in catalogue.records:

        for dimension in record.dimensions:

            # Only comparable USD On-Demand compute rates.
            # Do not graph mixed currencies, units or usage tiers.

            if (
                record.service_code == "AmazonEC2"
                and record.pricing_model.value == "ON_DEMAND"
                and dimension.cost_component == "compute"
                and dimension.currency == "USD"
                and dimension.unit == "Hrs"
                and dimension.begin_range == 0
                and dimension.end_range is None
            ):

                entries.append({
                    "Resource": (
                        f"{resource_label(record)} | "
                        f"{record.region} | "
                        f"{record.attributes.get('operatingSystem', 'Unknown OS')} | "
                        f"{record.attributes.get('tenancy', 'Unknown tenancy')}"
                    ),
                    "USD per hour": float(
                        dimension.unit_price
                    ),
                })

    labels = [
        item["Resource"]
        for item in entries
    ]

    if len(entries) < 2:
        return

    if len(labels) != len(set(labels)):
        return

    st.subheader("Hourly compute rate comparison")

    st.bar_chart(
        pd.DataFrame(entries),
        x="Resource",
        y="USD per hour",
    )

    st.caption(
        "Chart compares retrieved compute unit rates only. "
        "It is not a total infrastructure cost estimate. "
        "Exact decimal rates are retained in the table and CSV."
    )


def render_catalogue(catalogue):

    st.divider()

    st.subheader("Pricing results")

    first, second, third = st.columns(3)

    first.metric(
        "Retrieved products",
        catalogue.retrieval.product_count,
    )

    second.metric(
        "Pricing offers",
        catalogue.record_count,
    )

    third.metric(
        "Billing dimensions",
        catalogue.dimension_count,
    )

    st.caption(
        "Retrieved at: "
        + catalogue.retrieved_at.strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    if catalogue.unpriced_skus:

        st.warning(
            "Some retrieved products contain no usable pricing offers: "
            + ", ".join(catalogue.unpriced_skus)
        )

    for warning in catalogue.warnings:
        st.warning(warning)

    rows = catalogue_rows(catalogue)

    if not rows:

        st.warning(
            "No pricing records are available for this selection. "
            "Unavailable pricing does not mean zero cost."
        )

    else:

        frame = pd.DataFrame(rows)

        st.dataframe(
            frame,
            hide_index=True,
            column_order=[
                "Resource",
                "Region",
                "Operating system",
                "Pricing model",
                "Cost component",
                "Unit price",
                "Currency",
                "Billing unit",
                "Tier start",
                "Tier end (exclusive)",
                "Source",
                "SKU",
                "Rate code",
                "Offer term",
                "Catalogue version",
                "Effective date",
                "Retrieved at (UTC)",
                "Source reference",
            ],
        )

        render_comparable_chart(catalogue)

        st.download_button(
            "Download pricing CSV",
            data=csv_bytes(rows),
            file_name=(
                f"floci-pricing-{catalogue.service_code}.csv"
            ),
            mime="text/csv",
            key="m1.download",
        )

    with st.expander("Catalogue details and original JSON"):

        st.write(
            "Source: Local Floci Pricing API"
        )

        st.write(
            "Retrieved pages:",
            catalogue.retrieval.page_count,
        )

        st.write(
            "Duplicate products removed:",
            catalogue.retrieval.duplicate_count,
        )

        st.write(
            "Requested filters:",
            {
                item.field: item.value
                for item in catalogue.retrieval.filters
            },
        )

        for product in catalogue.retrieval.products:

            st.markdown(
                f"**{product.sku}**"
            )

            st.code(
                product.raw_json,
                language="json",
            )


def render_reference_view():

    st.subheader("Supplementary Reference Pricing")

    st.info(
        "These are documented AWS reference rates, not prices "
        "retrieved from Floci. They supplement missing catalogue "
        "coverage and are not live production AWS quotations."
    )

    try:
        rates = load_reference_rates()

    except ReferenceCatalogueError as error:
        st.error(f"Unable to load reference pricing: {error}")
        return

    services = sorted({
        item.record.service_code
        for item in rates
    })

    regions = sorted({
        item.record.region
        for item in rates
    })

    left, right = st.columns(2)

    service = left.selectbox(
        "Reference service",
        ["All services", *services],
        format_func=service_label,
        key="m1.reference.service",
    )

    region = right.selectbox(
        "Reference region",
        ["All regions", *regions],
        key="m1.reference.region",
    )

    selected = [
        item for item in rates
        if (
            service == "All services"
            or item.record.service_code == service
        )
        and (
            region == "All regions"
            or item.record.region == region
        )
    ]

    rows = []

    for item in selected:

        record = item.record

        for dimension in record.dimensions:

            rows.append({
                "Service": service_label(record.service_code),
                "Resource type": item.resource_type,
                "Region": record.region,
                "Configuration": ", ".join(
                    f"{key}={value}"
                    for key, value in record.attributes.items()
                ),
                "Cost component": dimension.cost_component,
                "Pricing model": record.pricing_model.value,
                "Unit price": format(dimension.unit_price, "f"),
                "Currency": dimension.currency,
                "Billing unit": dimension.unit,
                "Coverage start": format(
                    dimension.begin_range, "f"
                ),
                "Coverage end": (
                    "Unbounded"
                    if dimension.end_range is None
                    else format(dimension.end_range, "f")
                ),
                "Source": record.source.value,
                "Verified on": item.verified_on.isoformat(),
                "Effective date": (
                    record.effective_date.isoformat()
                    if record.effective_date
                    else "Unknown"
                ),
                "Reference ID": item.reference_id,
                "Source URL": record.source_reference,
                "Limitations": " | ".join(item.limitations),
            })

    st.metric("Available reference rates", len(rows))

    if not rows:
        st.warning("No reference rates match this selection.")
        return

    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        column_config={
            "Source URL": st.column_config.LinkColumn(
                "Official AWS source"
            )
        },
    )

    st.download_button(
        "Download reference pricing CSV",
        data=csv_bytes(rows),
        file_name="aws-reference-pricing.csv",
        mime="text/csv",
        key="m1.reference.download",
    )

    st.subheader("Coverage and assumptions")

    for item in selected:

        dimension = item.record.dimensions[0]

        with st.expander(
            f"{item.reference_id} | "
            f"{format(dimension.unit_price, 'f')} "
            f"{dimension.currency}/{dimension.unit}"
        ):

            st.write("Source:", item.record.source.value)
            st.write("Verified on:", item.verified_on.isoformat())

            for limitation in item.limitations:
                st.markdown(f"- {limitation}")

            st.markdown(
                f"[Official AWS documentation]"
                f"({item.record.source_reference})"
            )

    st.caption(
        "Reference pricing is optional in cost estimation. "
        "The resolver prefers applicable Floci pricing."
    )


def render_spot_view():

    st.subheader("EC2 Spot Pricing")

    st.info(
        "Spot observations are retrieved from the Floci EC2 API. "
        "They represent simulated historical prices, not guaranteed "
        "future rates or production AWS market quotations."
    )

    left, right = st.columns(2)

    instance = left.text_input(
        "Instance type",
        value="t3.micro",
        key="m1.spot.instance",
        help="For example, t3.micro or m5.large.",
    ).strip()

    region = right.text_input(
        "AWS region",
        value="us-east-1",
        key="m1.spot.region",
    ).strip()

    description = left.selectbox(
        "Spot product description",
        [
            "Linux/UNIX",
            "Linux/UNIX (Amazon VPC)",
            "Windows",
            "Windows (Amazon VPC)",
            "Red Hat Enterprise Linux",
            "Red Hat Enterprise Linux (Amazon VPC)",
            "SUSE Linux",
            "SUSE Linux (Amazon VPC)",
        ],
        key="m1.spot.description",
    )

    zone = right.text_input(
        "Availability Zone (optional)",
        value="",
        key="m1.spot.zone",
        help="Leave blank to retrieve all available zones.",
    ).strip()

    try:

        query = SpotQuery(
            instance_type=instance,
            region=region,
            product_description=description,
            availability_zone=zone or None,
        )

    except ValueError as error:
        st.error(f"Invalid Spot query: {error}")
        return

    service = SpotPricingService()

    first, second = st.columns(2)

    refresh = first.button(
        "Retrieve / refresh Spot pricing",
        type="primary",
        key="m1.spot.retrieve",
    )

    show_expired = second.checkbox(
        "Show expired Spot observations",
        key="m1.spot.historical",
    )

    try:

        if refresh:

            with st.spinner("Retrieving Spot observations..."):
                service.refresh(query)

            st.success(
                "Spot retrieval completed and saved locally."
            )

        cached = service.load(query)

    except (
        SpotPricingError,
        UnsafeEndpointError,
        BotoCoreError,
        ClientError,
        ValueError,
    ) as error:

        st.error(f"Spot pricing retrieval or cache access failed: {error}")

        st.caption(
            "No previously saved observation has been "
            "substituted for the failed request."
        )

        return

    if cached is None:

        st.info(
            "No Spot pricing has been saved for this selection. "
            "Retrieve pricing to begin."
        )

        return

    if cached.is_stale:

        st.warning(
            "The saved Spot cache is expired or has an "
            "invalid future retrieval timestamp."
        )

        if not show_expired:
            return

        st.caption(
            "Expired observations are displayed at your explicit request."
        )

    else:

        st.caption(
            "Freshly retrieved and saved Spot catalogue."
            if refresh
            else "Fresh locally saved Spot catalogue."
        )

    history = cached.history

    first, second, third = st.columns(3)

    first.metric(
        "Spot observations",
        len(history.observations),
    )

    second.metric(
        "Availability Zones",
        len(history.latest_by_zone),
    )

    third.metric(
        "Retrieved pages",
        history.page_count,
    )

    st.caption(
        f"Observation window: {history.start_time.isoformat()} "
        f"to {history.end_time.isoformat()}"
    )

    st.caption(
        f"Retrieved at: {history.retrieved_at.isoformat()} | "
        f"Cache freshness interval: {cached.ttl_seconds} seconds"
    )

    st.caption(
        "Observation time is distinct from retrieval time. "
        "A fresh cache can contain older price observations."
    )

    if not history.observations:

        st.warning(
            "No Spot observations are available for this configuration. "
            "Unavailable pricing does not mean zero cost."
        )

        return

    rows = []

    for item in history.observations:

        rows.append({
            "Instance type": item.instance_type,
            "Region": item.region,
            "Availability Zone": item.availability_zone,
            "Product description": item.product_description,
            "Unit price": format(item.unit_price, "f"),
            "Currency": item.currency,
            "Billing unit": item.unit,
            "Observed at (UTC)": item.observed_at.isoformat(),
            "Retrieved at (UTC)": item.retrieved_at.isoformat(),
            "Source": item.source.value,
        })

    latest = {
        (item.availability_zone, item.observed_at.isoformat())
        for item in history.latest_by_zone
    }

    latest_rows = [
        row for row in rows
        if (
            row["Availability Zone"],
            row["Observed at (UTC)"],
        ) in latest
    ]

    st.subheader("Latest observations by Availability Zone")

    st.dataframe(
        pd.DataFrame(latest_rows),
        hide_index=True,
    )

    if len(latest_rows) > 1:

        chart = pd.DataFrame([
            {
                "Availability Zone": row["Availability Zone"],
                "USD per hour": float(row["Unit price"]),
            }
            for row in latest_rows
        ])

        st.bar_chart(
            chart,
            x="Availability Zone",
            y="USD per hour",
        )

    with st.expander("All returned observations"):

        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
        )

    st.download_button(
        "Download Spot pricing CSV",
        data=csv_bytes(rows),
        file_name="floci-spot-pricing.csv",
        mime="text/csv",
        key="m1.spot.download",
    )

    st.warning(
        "Floci may generate observation timestamps from request "
        "parameters. These records do not establish real market "
        "price trends. Future cost projections require an explicit "
        "constant-price assumption."
    )


def run():

    st.set_page_config(
        page_title="Pricing Explorer | Cloud FinOps",
        page_icon=":material/price_check:",
        layout="wide",
    )

    st.caption("CLOUD FINOPS PLATFORM / M1")

    st.title("Cloud Service Pricing Explorer")

    st.write(
        "Explore cloud service pricing, inspect billing dimensions "
        "and save retrieved rates for infrastructure cost analysis."
    )

    st.caption(
        f"Local pricing endpoint: {DEFAULT_FLOCI_ENDPOINT}"
    )

    st.info(
        "Prices are retrieved from the Floci emulator. "
        "Catalogue coverage is limited and does not represent "
        "the complete production AWS pricing catalogue."
    )

    view = st.radio(
        "Pricing view",
        [
            "Floci Pricing Catalogue",
            "Supplementary Reference Pricing",
            "EC2 Spot Pricing",
        ],
        horizontal=True,
        key="m1.view",
    )

    if view == "Supplementary Reference Pricing":
        render_reference_view()
        return

    if view == "EC2 Spot Pricing":
        render_spot_view()
        return

    if st.button(
        "Refresh service options",
        key="m1.refresh_metadata",
    ):

        st.session_state.pop(
            "m1.services", None
        )

        st.session_state.pop(
            "m1.filter_options", None
        )

    try:

        if "m1.services" not in st.session_state:

            with st.spinner("Discovering pricing services..."):

                st.session_state["m1.services"] = (
                    discover_services()
                )

        services = st.session_state["m1.services"]

    except EXPECTED_ERRORS as error:

        st.error(
            "Unable to discover pricing services. "
            + error_label(error)
        )

        st.caption(
            "Verify that Floci is running, then refresh service options."
        )

        return

    if not services:

        st.warning(
            "Floci did not advertise any pricing services."
        )

        return

    st.subheader("Configure pricing search")

    service_by_code = {
        item.service_code: item
        for item in services
    }

    service_code = st.selectbox(
        "Cloud service",
        options=list(service_by_code),
        format_func=service_label,
        key="m1.service",
    )

    service = service_by_code[service_code]

    if "m1.filter_options" not in st.session_state:
        st.session_state["m1.filter_options"] = {}

    options_cache = (
        st.session_state["m1.filter_options"]
    )

    try:

        if service_code not in options_cache:

            with st.spinner("Loading available filters..."):

                options_cache[service_code] = (
                    discover_filter_options(service)
                )

        region_field, attribute_fields, options = (
            options_cache[service_code]
        )

    except EXPECTED_ERRORS as error:

        st.error(
            "Unable to discover service attributes. "
            + error_label(error)
        )

        return

    filters = []

    if region_field and options.get(region_field):

        region = st.selectbox(
            "Region",
            options=[
                "All regions",
                *options[region_field],
            ],
            key=f"m1.region.{service_code}",
            help="Regions or locations advertised by Floci.",
        )

        if region != "All regions":

            filters.append(
                ProductFilter(
                    region_field,
                    region,
                )
            )

    else:

        st.caption(
            "No region selector values were advertised. "
            "The search will not apply a region filter."
        )

    with st.expander(
        "Resource configuration filters",
        expanded=True,
    ):

        for field in attribute_fields:

            values = options.get(field, ())

            if not values:
                continue

            selected = st.selectbox(
                ATTRIBUTE_LABELS.get(field, field),
                options=[
                    "All configurations",
                    *values,
                ],
                key=f"m1.filter.{service_code}.{field}",
            )

            if selected != "All configurations":

                filters.append(
                    ProductFilter(
                        field,
                        selected,
                    )
                )

    filters = tuple(filters)

    st.caption(
        "Advertised configurations are not guaranteed "
        "to have matching pricing records."
    )

    cache = PricingCatalogueCache()

    left, right = st.columns(2)

    refresh_requested = left.button(
        "Retrieve / refresh pricing",
        type="primary",
        key="m1.retrieve",
    )

    show_historical = right.checkbox(
        "Show saved historical pricing",
        key="m1.show_historical",
        help=(
            "Explicitly allow viewing expired cached data. "
            "Historical prices are not live quotes."
        ),
    )

    if refresh_requested:

        try:

            with st.spinner(
                "Retrieving and saving pricing from Floci..."
            ):

                cache.refresh(
                    service_code,
                    filters,
                )

            st.success(
                "Pricing retrieval completed and saved locally."
            )

        except EXPECTED_ERRORS as error:

            st.error(
                "Live pricing retrieval failed. "
                + error_label(error)
            )

            st.caption(
                "No cached price has been substituted "
                "for this failed request."
            )

            return

    try:

        cached = cache.load(
            service_code,
            filters,
        )

    except EXPECTED_ERRORS as error:

        st.error(
            "Unable to load saved pricing. "
            + error_label(error)
        )

        return

    if cached is None:

        st.info(
            "No pricing has been saved for this selection. "
            "Retrieve pricing to begin."
        )

        return

    if cached.is_stale:

        st.warning(
            "Saved pricing is stale or has an invalid future timestamp. "
            "Refresh pricing to obtain updated information."
        )

        if not show_historical:
            return

        st.caption(
            "Historical pricing is displayed at your explicit request."
        )

    elif refresh_requested:

        st.caption(
            "Source: Floci / newly retrieved and saved."
        )

    else:

        st.caption(
            "Source: Floci / fresh locally saved catalogue."
        )

    st.caption(
        f"Cache freshness interval: {cached.ttl_seconds} seconds."
    )

    render_catalogue(
        cached.catalogue
    )

    st.divider()

    st.caption(
        "M1 provides unit pricing information. "
        "Infrastructure configuration, total cost estimates "
        "and pricing model comparisons belong to M3, M4 and M5."
    )


if __name__ == "__main__":
    run()
