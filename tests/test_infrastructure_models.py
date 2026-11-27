"""Verify infrastructure contracts and scenario integrity."""

import unittest

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from finops.infrastructure.models import (
    InfrastructureScenario,
    ResourceConfiguration,
    ResourceType,
)

from finops.pricing.models import PricingModel


def ec2_resource(**changes):
    original = ResourceConfiguration(
        name="Web servers",
        resource_type=ResourceType.EC2_INSTANCE,
        region="us-east-1",
        quantity=3,
        configuration={
            "instanceType": "t3.micro",
            "operatingSystem": "Linux",
            "tenancy": "Shared",
        },
        usage={
            "monthly_hours": Decimal("730"),
        },
    )

    return replace(original, **changes)


class InfrastructureModelTests(unittest.TestCase):

    def test_resource_contract_matches_pricing_identifiers(self):
        cases = {
            ResourceType.EC2_INSTANCE: "AmazonEC2",
            ResourceType.EBS_VOLUME: "AmazonEC2",
            ResourceType.S3_BUCKET: "AmazonS3",
            ResourceType.LAMBDA_FUNCTION: "AWSLambda",
            ResourceType.DYNAMODB_TABLE: "AmazonDynamoDB",
            ResourceType.RDS_INSTANCE: "AmazonRDS",
        }

        for resource_type, service in cases.items():
            with self.subTest(resource_type=resource_type):
                resource = ResourceConfiguration(
                    name="Example",
                    resource_type=resource_type,
                    region="us-east-1",
                )

                self.assertEqual(resource.service_code, service)
                self.assertEqual(resource.quantity, 1)
                self.assertEqual(
                    resource.pricing_model,
                    PricingModel.ON_DEMAND,
                )

    def test_resource_identity_is_unique(self):
        first = ec2_resource()
        second = ec2_resource()

        self.assertIsInstance(first.resource_id, UUID)
        self.assertNotEqual(
            first.resource_id,
            second.resource_id,
        )

    def test_invalid_resource_metadata_is_rejected(self):
        cases = (
            {"name": ""},
            {"quantity": 0},
            {"quantity": -1},
            {"quantity": True},
            {"quantity": 1.5},
            {"region": "invalid"},
            {"resource_type": "ec2_instance"},
            {"pricing_model": "ON_DEMAND"},
            {"resource_id": UUID(int=0)},
        )

        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    ec2_resource(**changes)

    def test_usage_preserves_decimal_precision_and_unknowns(self):
        resource = ec2_resource(
            usage={
                "monthly_hours": Decimal("123.456789"),
                "requests": Decimal("0"),
                "transfer": None,
            }
        )

        self.assertEqual(
            resource.usage["monthly_hours"],
            Decimal("123.456789"),
        )

        self.assertEqual(
            resource.usage["requests"],
            Decimal("0"),
        )

        self.assertIsNone(resource.usage["transfer"])
        self.assertNotIn("unspecified_component", resource.usage)

    def test_invalid_usage_values_are_rejected(self):
        invalid = (
            Decimal("-1"),
            Decimal("NaN"),
            Decimal("Infinity"),
            1,
            0.1,
            True,
            "730",
        )

        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ec2_resource(
                        usage={"monthly_hours": value}
                    )

    def test_invalid_configuration_values_are_rejected(self):
        invalid = (
            [],
            {},
            None,
            "",
            0.1,
            Decimal("NaN"),
        )

        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ec2_resource(
                        configuration={"example": value}
                    )

    def test_resource_mappings_are_independent_and_immutable(self):
        configuration = {"instanceType": "t3.micro"}
        usage = {"monthly_hours": Decimal("730")}

        resource = ec2_resource(
            configuration=configuration,
            usage=usage,
        )

        configuration["instanceType"] = "m5.large"
        usage["monthly_hours"] = Decimal("100")

        self.assertEqual(
            resource.configuration["instanceType"],
            "t3.micro",
        )

        self.assertEqual(
            resource.usage["monthly_hours"],
            Decimal("730"),
        )

        with self.assertRaises(TypeError):
            resource.configuration["instanceType"] = "m5.large"

        with self.assertRaises(FrozenInstanceError):
            resource.quantity = 99

    def test_multiple_resource_scenario(self):
        ec2 = ec2_resource()

        storage = ResourceConfiguration(
            name="Application storage",
            resource_type=ResourceType.S3_BUCKET,
            region="us-east-1",
            configuration={"volumeType": "Standard"},
            usage={
                "average_storage_gb": Decimal("500"),
            },
        )

        resources = [ec2, storage]

        scenario = InfrastructureScenario(
            name="Production",
            resources=resources,
        )

        resources.clear()

        self.assertEqual(scenario.resource_group_count, 2)
        self.assertEqual(scenario.total_resource_count, 4)

        self.assertEqual(
            scenario.service_codes,
            ("AmazonEC2", "AmazonS3"),
        )

        self.assertEqual(scenario.revision, 1)
        self.assertEqual(scenario.schema_version, 1)

    def test_multiple_scenarios_and_empty_drafts(self):
        first = InfrastructureScenario(name="Development")
        second = InfrastructureScenario(name="Production")

        self.assertNotEqual(
            first.scenario_id,
            second.scenario_id,
        )

        self.assertEqual(first.resources, ())
        self.assertEqual(first.total_resource_count, 0)

    def test_duplicate_resource_ids_are_rejected(self):
        resource = ec2_resource()

        with self.assertRaises(ValueError):
            InfrastructureScenario(
                name="Invalid duplicate",
                resources=(resource, resource),
            )

    def test_invalid_scenario_metadata_is_rejected(self):
        cases = (
            {"name": ""},
            {"revision": 0},
            {"revision": True},
            {"schema_version": 2},
            {"schema_version": True},
            {"description": None},
            {"resources": ("invalid",)},
            {"scenario_id": UUID(int=0)},
        )

        scenario = InfrastructureScenario(name="Baseline")

        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    replace(scenario, **changes)

    def test_timestamps_are_normalized_and_validated(self):
        offset = timezone(timedelta(hours=-5))

        created = datetime(
            2026, 11, 27, 10, 0,
            tzinfo=offset,
        )

        scenario = InfrastructureScenario(
            name="Timestamp control",
            created_at=created,
            updated_at=created + timedelta(minutes=1),
        )

        self.assertEqual(
            scenario.created_at,
            datetime(
                2026, 11, 27, 15, 0,
                tzinfo=timezone.utc,
            ),
        )

        with self.assertRaises(ValueError):
            replace(
                scenario,
                updated_at=created - timedelta(seconds=1),
            )

        with self.assertRaises(ValueError):
            replace(
                scenario,
                created_at=created.replace(tzinfo=None),
            )


if __name__ == "__main__":
    unittest.main()
