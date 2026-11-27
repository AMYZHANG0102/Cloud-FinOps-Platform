"""Domain contracts for hypothetical infrastructure scenarios.

These models describe intended resources and expected usage.
They do not provision resources or calculate infrastructure costs.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from uuid import UUID, uuid4

from finops.pricing.client import validate_region
from finops.pricing.models import PricingModel


SCENARIO_SCHEMA_VERSION = 1


class ResourceType(StrEnum):
    """Resource identifiers shared with pricing and estimation."""

    EC2_INSTANCE = "ec2_instance"
    EBS_VOLUME = "ebs_volume"
    S3_BUCKET = "s3_bucket"
    LAMBDA_FUNCTION = "function"
    DYNAMODB_TABLE = "table"
    RDS_INSTANCE = "rds_instance"


SERVICE_CODES = MappingProxyType({
    ResourceType.EC2_INSTANCE: "AmazonEC2",
    ResourceType.EBS_VOLUME: "AmazonEC2",
    ResourceType.S3_BUCKET: "AmazonS3",
    ResourceType.LAMBDA_FUNCTION: "AWSLambda",
    ResourceType.DYNAMODB_TABLE: "AmazonDynamoDB",
    ResourceType.RDS_INSTANCE: "AmazonRDS",
})


ConfigurationValue = str | int | bool | Decimal
UsageValue = Decimal | None


def _require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text.")

    return value


def _require_uuid(value, name):
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{name} must be a nonzero UUID.")

    return value


def _positive_integer(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer.")

    return value


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_timestamp(value, name):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{name} must be a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)


def _freeze_configuration(values):
    if not isinstance(values, Mapping):
        raise ValueError("Configuration must be a mapping.")

    result = {}

    for key, value in values.items():
        _require_text(key, "Configuration key")

        if type(value) not in (str, int, bool, Decimal):
            raise ValueError(
                f"Unsupported configuration value: {key}"
            )

        if isinstance(value, str):
            _require_text(value, key)

        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError(
                f"Configuration value must be finite: {key}"
            )

        result[key] = value

    return MappingProxyType(result)


def _freeze_usage(values):
    if not isinstance(values, Mapping):
        raise ValueError("Usage must be a mapping.")

    result = {}

    for key, value in values.items():
        _require_text(key, "Usage key")

        if value is not None:
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value < 0
            ):
                raise ValueError(
                    f"Usage must be a nonnegative Decimal "
                    f"or None: {key}"
                )

        result[key] = value

    return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class ResourceConfiguration:
    """One group of identically configured hypothetical resources.

    Usage values represent consumption per resource unless
    a service-specific contract explicitly states otherwise.
    The estimator must apply quantity exactly once.
    """

    name: str
    resource_type: ResourceType
    region: str

    quantity: int = 1

    configuration: Mapping[str, ConfigurationValue] = field(
        default_factory=dict
    )

    usage: Mapping[str, UsageValue] = field(
        default_factory=dict
    )

    pricing_model: PricingModel = PricingModel.ON_DEMAND

    resource_id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        _require_uuid(self.resource_id, "Resource ID")
        _require_text(self.name, "Resource name")
        _positive_integer(self.quantity, "Resource quantity")

        if not isinstance(self.resource_type, ResourceType):
            raise ValueError("Invalid resource type.")

        if not isinstance(self.pricing_model, PricingModel):
            raise ValueError("Invalid pricing model.")

        validate_region(self.region)

        object.__setattr__(
            self,
            "configuration",
            _freeze_configuration(self.configuration),
        )

        object.__setattr__(
            self,
            "usage",
            _freeze_usage(self.usage),
        )

    @property
    def service_code(self):
        """Derive the AWS service from the resource type."""
        return SERVICE_CODES[self.resource_type]


@dataclass(frozen=True, slots=True)
class InfrastructureScenario:
    """A versioned collection of hypothetical cloud resources.

    Empty scenarios are valid drafts. Service-specific
    completeness is assessed before cost estimation.
    """

    name: str

    resources: tuple[ResourceConfiguration, ...] = ()

    description: str = ""

    scenario_id: UUID = field(default_factory=uuid4)

    revision: int = 1

    created_at: datetime = field(default_factory=_utc_now)

    updated_at: datetime = field(default_factory=_utc_now)

    schema_version: int = SCENARIO_SCHEMA_VERSION

    def __post_init__(self):
        _require_uuid(self.scenario_id, "Scenario ID")
        _require_text(self.name, "Scenario name")
        _positive_integer(self.revision, "Scenario revision")

        if not isinstance(self.description, str):
            raise ValueError("Scenario description must be text.")

        if (
            type(self.schema_version) is not int
            or self.schema_version != SCENARIO_SCHEMA_VERSION
        ):
            raise ValueError("Unsupported scenario schema version.")

        if not isinstance(self.resources, (list, tuple)):
            raise ValueError("Resources must be a list or tuple.")

        resources = tuple(self.resources)

        identities = set()

        for resource in resources:
            if not isinstance(resource, ResourceConfiguration):
                raise ValueError("Invalid scenario resource.")

            if resource.resource_id in identities:
                raise ValueError("Duplicate resource ID.")

            identities.add(resource.resource_id)

        created = _utc_timestamp(
            self.created_at, "Creation timestamp"
        )

        updated = _utc_timestamp(
            self.updated_at, "Update timestamp"
        )

        if updated < created:
            raise ValueError(
                "Update timestamp cannot precede creation."
            )

        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)

    @property
    def resource_group_count(self):
        return len(self.resources)

    @property
    def total_resource_count(self):
        return sum(
            resource.quantity
            for resource in self.resources
        )

    @property
    def service_codes(self):
        return tuple(sorted({
            resource.service_code
            for resource in self.resources
        }))
