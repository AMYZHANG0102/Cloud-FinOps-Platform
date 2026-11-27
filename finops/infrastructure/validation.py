"""Service-specific validation for hypothetical infrastructure.

Rules define the application's initial modelling scope, rather
than claiming to reproduce every AWS provisioning constraint.

Missing usage is distinct from invalid configuration and zero usage.
"""

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from finops.infrastructure.models import (
    InfrastructureScenario,
    ResourceConfiguration,
    ResourceType,
)

from finops.pricing.models import PricingModel


MONTHLY_HOURS = Decimal("730")
HOURS_PER_DAY = Decimal("24")
MONTHS_PER_YEAR = Decimal("12")


@dataclass(frozen=True, slots=True)
class ConfigurationField:
    key: str
    label: str
    choices: tuple[str, ...] = ()
    required: bool = True
    value_type: type = str
    default: str | bool | None = None


@dataclass(frozen=True, slots=True)
class UsageField:
    key: str
    label: str
    unit: str
    minimum: Decimal = Decimal("0")
    maximum: Decimal | None = None
    integral: bool = False
    default: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ResourceSpecification:
    label: str
    configuration_fields: tuple[ConfigurationField, ...]
    usage_fields: tuple[UsageField, ...]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class ResourceValidation:
    errors: tuple[ValidationIssue, ...] = ()
    missing_usage: tuple[ValidationIssue, ...] = ()

    @property
    def is_valid(self):
        return not self.errors

    @property
    def is_complete(self):
        return self.is_valid and not self.missing_usage


@dataclass(frozen=True, slots=True)
class ScenarioValidation:
    resource_results: tuple[
        tuple[str, ResourceValidation], ...
    ]

    @property
    def is_valid(self):
        return all(
            result.is_valid
            for _, result in self.resource_results
        )

    @property
    def is_complete(self):
        return bool(self.resource_results) and all(
            result.is_complete
            for _, result in self.resource_results
        )


def monthly_hours(key, label):
    return UsageField(
        key,
        label,
        "hours/month",
        maximum=MONTHLY_HOURS,
        default=MONTHLY_HOURS,
    )


SPECIFICATIONS = MappingProxyType({

    ResourceType.EC2_INSTANCE: ResourceSpecification(
        label="Amazon EC2",
        configuration_fields=(
            ConfigurationField(
                "instanceType",
                "Instance type",
                default="t3.micro",
            ),
            ConfigurationField(
                "operatingSystem",
                "Operating system",
                ("Linux", "Windows", "RHEL", "SUSE"),
                default="Linux",
            ),
            ConfigurationField(
                "tenancy",
                "Tenancy",
                ("Shared", "Dedicated", "Host"),
                default="Shared",
            ),
            ConfigurationField(
                "preInstalledSw",
                "Preinstalled software",
                required=False,
            ),
        ),
        usage_fields=(
            monthly_hours(
                "monthly_hours",
                "Monthly running hours",
            ),
        ),
    ),

    ResourceType.EBS_VOLUME: ResourceSpecification(
        label="Amazon EBS",
        configuration_fields=(
            ConfigurationField(
                "volumeType",
                "Volume type",
                ("gp3", "gp2", "io1", "io2", "st1", "sc1"),
                default="gp3",
            ),
        ),
        usage_fields=(
            UsageField(
                "capacity_gib",
                "Provisioned capacity",
                "GiB",
                minimum=Decimal("1"),
                default=Decimal("100"),
            ),
            monthly_hours(
                "provisioned_hours",
                "Monthly provisioned hours",
            ),
        ),
    ),

    ResourceType.S3_BUCKET: ResourceSpecification(
        label="Amazon S3",
        configuration_fields=(
            ConfigurationField(
                "volumeType",
                "Storage class",
                (
                    "Standard",
                    "Standard - Infrequent Access",
                    "One Zone - Infrequent Access",
                    "Glacier Flexible Retrieval",
                    "Glacier Deep Archive",
                ),
                default="Standard",
            ),
            ConfigurationField(
                "storageClass",
                "Additional catalogue classification",
                required=False,
            ),
        ),
        usage_fields=(
            UsageField(
                "average_storage_gb",
                "Average monthly storage",
                "GB",
                default=Decimal("500"),
            ),
            UsageField(
                "monthly_put_requests",
                "Monthly write requests",
                "requests/month",
                integral=True,
            ),
            UsageField(
                "monthly_get_requests",
                "Monthly read requests",
                "requests/month",
                integral=True,
            ),
            UsageField(
                "monthly_transfer_out_gb",
                "Monthly outbound transfer",
                "GB/month",
            ),
        ),
    ),

    ResourceType.LAMBDA_FUNCTION: ResourceSpecification(
        label="AWS Lambda",
        configuration_fields=(
            ConfigurationField(
                "architecture",
                "Architecture",
                ("x86_64", "arm64"),
                default="x86_64",
            ),
            ConfigurationField(
                "executionMode",
                "Execution mode",
                ("on_demand",),
                default="on_demand",
            ),
        ),
        usage_fields=(
            UsageField(
                "monthly_invocations",
                "Monthly invocations",
                "invocations/month",
                integral=True,
                default=Decimal("1000000"),
            ),
            UsageField(
                "average_duration_ms",
                "Average billable execution duration",
                "ms",
                minimum=Decimal("1"),
                default=Decimal("100"),
            ),
            UsageField(
                "memory_mb",
                "Configured memory",
                "MB",
                minimum=Decimal("128"),
                integral=True,
                default=Decimal("512"),
            ),
            UsageField(
                "ephemeral_storage_mb",
                "Configured ephemeral storage",
                "MB",
                minimum=Decimal("512"),
                integral=True,
                default=Decimal("512"),
            ),
        ),
    ),

    ResourceType.DYNAMODB_TABLE: ResourceSpecification(
        label="Amazon DynamoDB",
        configuration_fields=(
            ConfigurationField(
                "tableClass",
                "Table class",
                ("Standard", "Standard-IA"),
                default="Standard",
            ),
            ConfigurationField(
                "capacityMode",
                "Capacity mode",
                ("on_demand", "provisioned"),
                default="on_demand",
            ),
        ),
        usage_fields=(
            UsageField(
                "average_storage_gb",
                "Average monthly storage",
                "GB",
                default=Decimal("10"),
            ),
        ),
    ),

    ResourceType.RDS_INSTANCE: ResourceSpecification(
        label="Amazon RDS",
        configuration_fields=(
            ConfigurationField(
                "instanceClass",
                "Database instance class",
                default="db.t3.medium",
            ),
            ConfigurationField(
                "engine",
                "Database engine",
                ("mysql", "postgres", "mariadb", "oracle-ee", "sqlserver-se"),
                default="mysql",
            ),
            ConfigurationField(
                "multiAZ",
                "Multi-AZ deployment",
                value_type=bool,
                default=False,
            ),
            ConfigurationField(
                "volumeType",
                "Storage type",
                ("gp3", "gp2", "io1", "io2"),
                default="gp3",
            ),
        ),
        usage_fields=(
            monthly_hours(
                "monthly_hours",
                "Monthly running hours",
            ),
            UsageField(
                "capacity_gib",
                "Provisioned database storage",
                "GiB",
                minimum=Decimal("1"),
                default=Decimal("100"),
            ),
            monthly_hours(
                "provisioned_hours",
                "Monthly storage provisioned hours",
            ),
        ),
    ),
})


def get_resource_specification(resource_type):
    """Return the shared configuration-field definitions."""

    if not isinstance(resource_type, ResourceType):
        raise ValueError("ResourceType required.")

    return SPECIFICATIONS[resource_type]


def get_usage_fields(resource_type, configuration):
    """Return base fields and applicable conditional usage fields."""

    specification = get_resource_specification(resource_type)

    fields = list(specification.usage_fields)

    if resource_type == ResourceType.EBS_VOLUME:

        volume = configuration.get("volumeType")

        if volume in ("gp3", "io1", "io2"):

            fields.append(
                UsageField(
                    "provisioned_iops",
                    "Total provisioned IOPS",
                    "IOPS",
                    minimum=(
                        Decimal("3000")
                        if volume == "gp3"
                        else Decimal("1")
                    ),
                    integral=True,
                    default=(
                        Decimal("3000")
                        if volume == "gp3"
                        else None
                    ),
                )
            )

        if volume == "gp3":

            fields.append(
                UsageField(
                    "provisioned_throughput_mibps",
                    "Total provisioned throughput",
                    "MiB/s",
                    minimum=Decimal("125"),
                    default=Decimal("125"),
                )
            )

    elif resource_type == ResourceType.S3_BUCKET:

        volume = configuration.get("volumeType")

        if volume and volume != "Standard":

            fields.append(
                UsageField(
                    "monthly_retrieval_gb",
                    "Monthly retrieved data",
                    "GB/month",
                )
            )

    elif resource_type == ResourceType.DYNAMODB_TABLE:

        mode = configuration.get("capacityMode")

        if mode == "on_demand":

            fields.extend((
                UsageField(
                    "monthly_read_units",
                    "Monthly billable read request units",
                    "RRU/month",
                    integral=True,
                    default=Decimal("1000000"),
                ),
                UsageField(
                    "monthly_write_units",
                    "Monthly billable write request units",
                    "WRU/month",
                    integral=True,
                    default=Decimal("250000"),
                ),
            ))

        elif mode == "provisioned":

            fields.extend((
                UsageField(
                    "read_capacity_units",
                    "Provisioned read capacity",
                    "RCU",
                    minimum=Decimal("1"),
                    integral=True,
                ),
                UsageField(
                    "write_capacity_units",
                    "Provisioned write capacity",
                    "WCU",
                    minimum=Decimal("1"),
                    integral=True,
                ),
                monthly_hours(
                    "capacity_hours",
                    "Monthly provisioned capacity hours",
                ),
            ))

    elif resource_type == ResourceType.RDS_INSTANCE:

        if configuration.get("volumeType") in (
            "gp3", "io1", "io2"
        ):

            fields.append(
                UsageField(
                    "provisioned_iops",
                    "Total provisioned IOPS",
                    "IOPS",
                    integral=True,
                )
            )

        if configuration.get("volumeType") == "gp3":

            fields.append(
                UsageField(
                    "provisioned_throughput_mibps",
                    "Total provisioned throughput",
                    "MiB/s",
                )
            )

    return tuple(fields)


def validate_resource(resource):
    """Assess configuration and expected usage independently."""

    if not isinstance(resource, ResourceConfiguration):
        raise TypeError("ResourceConfiguration required.")

    specification = get_resource_specification(
        resource.resource_type
    )

    errors = []
    missing = []

    if resource.pricing_model != PricingModel.ON_DEMAND:

        errors.append(
            ValidationIssue(
                "pricing_model",
                "The initial Infrastructure Builder uses "
                "On-Demand scenarios. Alternative models "
                "are evaluated in Module 5.",
            )
        )

    config_fields = {
        field.key: field
        for field in specification.configuration_fields
    }

    for key in resource.configuration:

        if key not in config_fields:

            errors.append(
                ValidationIssue(
                    key,
                    "Unexpected configuration field.",
                )
            )

    for field in specification.configuration_fields:

        value = resource.configuration.get(field.key)

        if value is None:

            if field.required:

                errors.append(
                    ValidationIssue(
                        field.key,
                        f"{field.label} is required.",
                    )
                )

            continue

        if type(value) is not field.value_type:

            errors.append(
                ValidationIssue(
                    field.key,
                    f"{field.label} has an invalid value type.",
                )
            )

            continue

        if field.choices and value not in field.choices:

            errors.append(
                ValidationIssue(
                    field.key,
                    f"{field.label} is outside the supported "
                    "configuration choices.",
                )
            )

    usage_fields = get_usage_fields(
        resource.resource_type,
        resource.configuration,
    )

    allowed_usage = {
        field.key
        for field in usage_fields
    }

    for key in resource.usage:

        if key not in allowed_usage:

            errors.append(
                ValidationIssue(
                    key,
                    "Unexpected or inapplicable usage field.",
                )
            )

    for field in usage_fields:

        value = resource.usage.get(field.key)

        if value is None:

            missing.append(
                ValidationIssue(
                    field.key,
                    f"{field.label} is unknown.",
                )
            )

            continue

        if value < field.minimum:

            errors.append(
                ValidationIssue(
                    field.key,
                    f"{field.label} must be at least "
                    f"{field.minimum} {field.unit}.",
                )
            )

        if (
            field.maximum is not None
            and value > field.maximum
        ):

            errors.append(
                ValidationIssue(
                    field.key,
                    f"{field.label} must not exceed "
                    f"{field.maximum} {field.unit}.",
                )
            )

        if (
            field.integral
            and value != value.to_integral_value()
        ):

            errors.append(
                ValidationIssue(
                    field.key,
                    f"{field.label} must be a whole number.",
                )
            )

    return ResourceValidation(
        errors=tuple(errors),
        missing_usage=tuple(missing),
    )


def validate_scenario(scenario):
    """Validate all resource groups in a scenario."""

    if not isinstance(scenario, InfrastructureScenario):
        raise TypeError("InfrastructureScenario required.")

    return ScenarioValidation(
        resource_results=tuple(
            (
                str(resource.resource_id),
                validate_resource(resource),
            )
            for resource in scenario.resources
        )
    )
