"""Convert infrastructure configurations into monthly billing components.

This module calculates billing quantities and constructs pricing queries.
It does not retrieve prices or calculate monetary charges.

Usage values produced here include resource quantity exactly once.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from finops.infrastructure.models import (
    InfrastructureScenario,
    ResourceConfiguration,
    ResourceType,
)

from finops.infrastructure.validation import (
    MONTHLY_HOURS,
    validate_resource,
)

from finops.pricing.models import PricingQuery


ZERO = Decimal("0")
ONE = Decimal("1")

MILLISECONDS_PER_SECOND = Decimal("1000")
MB_PER_GB = Decimal("1024")

GP3_INCLUDED_IOPS = Decimal("3000")
GP3_INCLUDED_THROUGHPUT = Decimal("125")

LAMBDA_INCLUDED_EPHEMERAL_MB = Decimal("512")


@dataclass(frozen=True, slots=True)
class BillingComponent:
    """Monthly usage and its applicable pricing query.

    A missing query identifies a component outside the current
    pricing resolver's supported scope.

    A missing usage value identifies unknown billable consumption.
    Neither condition should automatically become zero cost.
    """

    resource_id: UUID
    service_code: str
    component: str
    unit: str

    usage: Decimal | None

    query: PricingQuery | None = None

    detail: str = ""
    excluded: bool = False

    def __post_init__(self):

        if (
            not isinstance(self.resource_id, UUID)
            or self.resource_id.int == 0
        ):

            raise ValueError("A nonzero resource UUID is required.")

        for name, value in (
            ("service_code", self.service_code),
            ("component", self.component),
            ("unit", self.unit),
        ):

            if not isinstance(value, str) or not value.strip():

                raise ValueError(
                    f"{name} must be nonempty text."
                )

        if self.usage is not None:

            if (
                not isinstance(self.usage, Decimal)
                or not self.usage.is_finite()
                or self.usage < ZERO
            ):

                raise ValueError(
                    "Billing usage must be a nonnegative Decimal."
                )

        if not isinstance(self.detail, str):
            raise ValueError("Detail must be text.")

        if type(self.excluded) is not bool:
            raise ValueError("Excluded must be boolean.")

        if self.excluded:

            if self.query is not None or self.usage is not None:

                raise ValueError(
                    "Excluded components cannot contain "
                    "billable usage or a pricing query."
                )

        if self.query is not None:

            if not isinstance(self.query, PricingQuery):
                raise ValueError("Invalid pricing query.")

            if self.query.service_code != self.service_code:
                raise ValueError("Pricing service mismatch.")

            if self.query.cost_component != self.component:
                raise ValueError("Pricing component mismatch.")

            if self.query.currency != "USD":
                raise ValueError("Only USD pricing is supported.")


def multiply_usage(*values):
    """Multiply usage factors without inventing missing quantities.

    A known zero factor establishes zero consumption even when
    another factor remains unknown.
    """

    for value in values:

        if value is None:
            continue

        if (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or value < ZERO
        ):

            raise ValueError(
                "Usage factors must be nonnegative Decimals."
            )

    if any(
        value is not None and value == ZERO
        for value in values
    ):

        return ZERO

    if any(value is None for value in values):
        return None

    result = ONE

    for value in values:
        result *= value

    return result


def above_included(value, included):

    if value is None:
        return None

    return max(ZERO, value - included)


def prorated_monthly_usage(amount, hours):
    """Convert provisioned quantities into average-month units."""

    result = multiply_usage(amount, hours)

    if result is None:
        return None

    return result / MONTHLY_HOURS


def build_resource_components(resource):
    """Map one resource group to its monthly billing components."""

    if not isinstance(resource, ResourceConfiguration):
        raise TypeError("ResourceConfiguration required.")

    validation = validate_resource(resource)

    if not validation.is_valid:

        raise ValueError(
            "Invalid resource configuration: "
            + " | ".join(
                issue.message
                for issue in validation.errors
            )
        )

    configuration = resource.configuration
    usage = resource.usage
    quantity = Decimal(resource.quantity)

    components = []

    def attributes(*keys):

        return {
            key: configuration[key]
            for key in keys
            if key in configuration
        }

    def add(
        component,
        unit,
        per_resource_usage,
        *,
        query_attributes=None,
        detail="",
        excluded=False,
    ):

        query = None

        if query_attributes is not None:

            query = PricingQuery(
                service_code=resource.service_code,
                resource_type=resource.resource_type.value,
                region=resource.region,
                pricing_model=resource.pricing_model,
                cost_component=component,
                attributes=query_attributes,
            )

        total_usage = multiply_usage(
            quantity,
            per_resource_usage,
        )

        components.append(
            BillingComponent(
                resource_id=resource.resource_id,
                service_code=resource.service_code,
                component=component,
                unit=unit,
                usage=total_usage,
                query=query,
                detail=detail,
                excluded=excluded,
            )
        )

    # Amazon EC2

    if resource.resource_type == ResourceType.EC2_INSTANCE:

        add(
            "compute",
            "Hrs",
            usage.get("monthly_hours"),
            query_attributes=attributes(
                "instanceType",
                "operatingSystem",
                "tenancy",
                "preInstalledSw",
            ),
            detail="Instance quantity multiplied by running hours.",
        )

    # Amazon EBS

    elif resource.resource_type == ResourceType.EBS_VOLUME:

        volume_type = configuration["volumeType"]
        hours = usage.get("provisioned_hours")

        add(
            "storage",
            "GiB-Mo",
            prorated_monthly_usage(
                usage.get("capacity_gib"),
                hours,
            ),
            query_attributes=attributes("volumeType"),
            detail="Provisioned capacity prorated over 730 hours.",
        )

        if volume_type == "gp3":

            add(
                "additional_iops",
                "IOPS-Mo",
                prorated_monthly_usage(
                    above_included(
                        usage.get("provisioned_iops"),
                        GP3_INCLUDED_IOPS,
                    ),
                    hours,
                ),
                query_attributes=attributes("volumeType"),
                detail=(
                    "Only IOPS above the modeled included "
                    "3000 IOPS per volume."
                ),
            )

            add(
                "additional_throughput",
                "MiBps-Mo",
                prorated_monthly_usage(
                    above_included(
                        usage.get(
                            "provisioned_throughput_mibps"
                        ),
                        GP3_INCLUDED_THROUGHPUT,
                    ),
                    hours,
                ),
                query_attributes=attributes("volumeType"),
                detail=(
                    "Only throughput above the modeled "
                    "included 125 MiB/s per volume."
                ),
            )

        elif volume_type in ("io1", "io2"):

            add(
                "provisioned_iops",
                "IOPS-Mo",
                prorated_monthly_usage(
                    usage.get("provisioned_iops"),
                    hours,
                ),
                detail=(
                    "Provisioned IOPS pricing is not supported "
                    "by the current pricing resolver."
                ),
            )

    # Amazon S3

    elif resource.resource_type == ResourceType.S3_BUCKET:

        add(
            "storage",
            "GB-Mo",
            usage.get("average_storage_gb"),
            query_attributes=attributes(
                "volumeType",
                "storageClass",
            ),
            detail="Average monthly storage per bucket.",
        )

        add(
            "put_requests",
            "Requests",
            usage.get("monthly_put_requests"),
            detail="S3 write-request rates are not currently supported.",
        )

        add(
            "get_requests",
            "Requests",
            usage.get("monthly_get_requests"),
            detail="S3 read-request rates are not currently supported.",
        )

        add(
            "transfer_out",
            "GB",
            usage.get("monthly_transfer_out_gb"),
            detail="S3 outbound-transfer rates are not currently supported.",
        )

        if configuration["volumeType"] != "Standard":

            add(
                "retrieval",
                "GB",
                usage.get("monthly_retrieval_gb"),
                detail="Storage retrieval rates are not currently supported.",
            )

            add(
                "minimum_storage_duration",
                "N/A",
                None,
                excluded=True,
                detail=(
                    "Minimum-duration, object-size and early-deletion "
                    "adjustments are outside the current usage model."
                ),
            )

    # AWS Lambda

    elif resource.resource_type == ResourceType.LAMBDA_FUNCTION:

        invocations = usage.get("monthly_invocations")
        duration_ms = usage.get("average_duration_ms")

        execution_ms = multiply_usage(
            invocations,
            duration_ms,
        )

        execution_seconds = (
            None
            if execution_ms is None
            else execution_ms / MILLISECONDS_PER_SECOND
        )

        memory_mb = usage.get("memory_mb")

        memory_gb = (
            None
            if memory_mb is None
            else memory_mb / MB_PER_GB
        )

        add(
            "requests",
            "Requests",
            invocations,
            query_attributes={},
            detail="Monthly function invocations.",
        )

        add(
            "duration",
            "GB-Second",
            multiply_usage(
                execution_seconds,
                memory_gb,
            ),
            query_attributes=attributes(
                "architecture",
                "executionMode",
            ),
            detail=(
                "Invocations multiplied by average billable "
                "duration in seconds and configured memory in GB."
            ),
        )

        additional_mb = above_included(
            usage.get("ephemeral_storage_mb"),
            LAMBDA_INCLUDED_EPHEMERAL_MB,
        )

        additional_gb = (
            None
            if additional_mb is None
            else additional_mb / MB_PER_GB
        )

        add(
            "ephemeral_storage",
            "GB-Second",
            multiply_usage(
                execution_seconds,
                additional_gb,
            ),
            query_attributes=attributes("executionMode"),
            detail=(
                "Execution seconds multiplied by ephemeral "
                "storage above the included 512 MB."
            ),
        )

    # Amazon DynamoDB

    elif resource.resource_type == ResourceType.DYNAMODB_TABLE:

        mode = configuration["capacityMode"]

        if mode == "on_demand":

            add(
                "read_requests",
                "RRU",
                usage.get("monthly_read_units"),
                query_attributes=attributes(
                    "tableClass",
                    "capacityMode",
                ),
                detail="User-specified billable read request units.",
            )

            add(
                "write_requests",
                "WRU",
                usage.get("monthly_write_units"),
                query_attributes=attributes(
                    "tableClass",
                    "capacityMode",
                ),
                detail="User-specified billable write request units.",
            )

        elif mode == "provisioned":

            hours = usage.get("capacity_hours")

            add(
                "read_capacity",
                "RCU-Hrs",
                multiply_usage(
                    usage.get("read_capacity_units"),
                    hours,
                ),
                detail=(
                    "Provisioned read capacity-hours. "
                    "Applicable rates are not currently supported."
                ),
            )

            add(
                "write_capacity",
                "WCU-Hrs",
                multiply_usage(
                    usage.get("write_capacity_units"),
                    hours,
                ),
                detail=(
                    "Provisioned write capacity-hours. "
                    "Applicable rates are not currently supported."
                ),
            )

        add(
            "storage",
            "GB-Mo",
            usage.get("average_storage_gb"),
            query_attributes=attributes(
                "tableClass",
                "capacityMode",
            ),
            detail="Average monthly table storage.",
        )

    # Amazon RDS

    elif resource.resource_type == ResourceType.RDS_INSTANCE:

        deployment = (
            "Multi-AZ"
            if configuration["multiAZ"]
            else "Single-AZ"
        )

        add(
            "compute",
            "Hrs",
            usage.get("monthly_hours"),
            detail=(
                f"{deployment} database instance-hours. "
                "Applicable deployment pricing is unavailable."
            ),
        )

        hours = usage.get("provisioned_hours")

        add(
            "storage",
            "GiB-Mo",
            prorated_monthly_usage(
                usage.get("capacity_gib"),
                hours,
            ),
            detail=(
                f"{deployment} provisioned storage. "
                "Applicable deployment pricing is unavailable."
            ),
        )

        volume_type = configuration["volumeType"]

        if volume_type in ("gp3", "io1", "io2"):

            add(
                "provisioned_iops",
                "IOPS-Mo",
                (
                    None
                    if volume_type == "gp3"
                    else prorated_monthly_usage(
                        usage.get("provisioned_iops"),
                        hours,
                    )
                ),
                detail=(
                    "RDS billable performance depends on storage "
                    "and deployment pricing. Included gp3 performance "
                    "has not been resolved."
                ),
            )

        if volume_type == "gp3":

            add(
                "provisioned_throughput",
                "MiBps-Mo",
                None,
                detail=(
                    "RDS gp3 billable throughput cannot be "
                    "determined from the current pricing rules."
                ),
            )

    else:

        raise ValueError(
            f"Unsupported resource type: {resource.resource_type}"
        )

    return tuple(components)


def build_scenario_components(scenario):
    """Produce the billing components for every resource group."""

    if not isinstance(scenario, InfrastructureScenario):
        raise TypeError("InfrastructureScenario required.")

    return tuple(
        component
        for resource in scenario.resources
        for component in build_resource_components(resource)
    )
