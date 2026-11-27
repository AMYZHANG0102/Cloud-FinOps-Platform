"""Verify shared resource configuration and usage rules."""

import unittest

from dataclasses import replace
from decimal import Decimal

from finops.infrastructure.models import (
    InfrastructureScenario,
    ResourceConfiguration,
    ResourceType,
)

from finops.infrastructure.validation import (
    SPECIFICATIONS,
    get_usage_fields,
    validate_resource,
    validate_scenario,
)

from finops.pricing.models import PricingModel


def resource(resource_type, configuration, usage, **kwargs):
    return ResourceConfiguration(
        name="Test resource",
        resource_type=resource_type,
        region="us-east-1",
        configuration=configuration,
        usage=usage,
        **kwargs,
    )


def ec2(hours=Decimal("730")):
    return resource(
        ResourceType.EC2_INSTANCE,
        {
            "instanceType": "t3.micro",
            "operatingSystem": "Linux",
            "tenancy": "Shared",
        },
        {"monthly_hours": hours},
    )


class InfrastructureValidationTests(unittest.TestCase):

    def test_all_resource_types_have_specifications(self):
        self.assertEqual(
            set(SPECIFICATIONS),
            set(ResourceType),
        )

    def test_ec2_valid_monthly_hours(self):
        for hours in ("0", "120.5", "730"):
            with self.subTest(hours=hours):
                result = validate_resource(
                    ec2(Decimal(hours))
                )

                self.assertTrue(result.is_complete)

    def test_ec2_excessive_monthly_hours(self):
        result = validate_resource(
            ec2(Decimal("731"))
        )

        self.assertFalse(result.is_valid)

        self.assertIn(
            "monthly_hours",
            {issue.field for issue in result.errors},
        )

    def test_unknown_usage_is_not_invalid_or_zero(self):
        missing = validate_resource(ec2(None))
        zero = validate_resource(ec2(Decimal("0")))

        self.assertTrue(missing.is_valid)
        self.assertFalse(missing.is_complete)

        self.assertEqual(
            missing.missing_usage[0].field,
            "monthly_hours",
        )

        self.assertTrue(zero.is_complete)

    def test_missing_required_configuration(self):
        instance = replace(
            ec2(),
            configuration={
                "instanceType": "t3.micro",
                "tenancy": "Shared",
            },
        )

        result = validate_resource(instance)

        self.assertFalse(result.is_valid)

        self.assertIn(
            "operatingSystem",
            {issue.field for issue in result.errors},
        )

    def test_unexpected_fields_are_rejected(self):
        instance = replace(
            ec2(),
            configuration={
                **ec2().configuration,
                "unknown_option": "test",
            },
            usage={
                "monthly_hours": Decimal("730"),
                "unknown_usage": Decimal("10"),
            },
        )

        result = validate_resource(instance)

        self.assertFalse(result.is_valid)

        self.assertEqual(
            {issue.field for issue in result.errors},
            {"unknown_option", "unknown_usage"},
        )

    def test_unpriced_ec2_configuration_can_be_valid(self):
        instance = replace(
            ec2(),
            configuration={
                **ec2().configuration,
                "instanceType": "t3.small",
            },
        )

        self.assertTrue(
            validate_resource(instance).is_complete
        )

    def test_gp3_performance_fields(self):
        volume = resource(
            ResourceType.EBS_VOLUME,
            {"volumeType": "gp3"},
            {
                "capacity_gib": Decimal("100"),
                "provisioned_hours": Decimal("730"),
                "provisioned_iops": Decimal("3000"),
                "provisioned_throughput_mibps": Decimal("125"),
            },
        )

        self.assertTrue(
            validate_resource(volume).is_complete
        )

        invalid = replace(
            volume,
            usage={
                **volume.usage,
                "provisioned_iops": Decimal("2999"),
            },
        )

        self.assertFalse(
            validate_resource(invalid).is_valid
        )

        gp2_fields = get_usage_fields(
            ResourceType.EBS_VOLUME,
            {"volumeType": "gp2"},
        )

        self.assertNotIn(
            "provisioned_throughput_mibps",
            {field.key for field in gp2_fields},
        )

    def test_s3_storage_and_request_usage(self):
        bucket = resource(
            ResourceType.S3_BUCKET,
            {"volumeType": "Standard"},
            {
                "average_storage_gb": Decimal("500"),
                "monthly_put_requests": Decimal("0"),
                "monthly_get_requests": Decimal("1000"),
                "monthly_transfer_out_gb": Decimal("0"),
            },
        )

        self.assertTrue(
            validate_resource(bucket).is_complete
        )

        invalid = replace(
            bucket,
            usage={
                **bucket.usage,
                "monthly_get_requests": Decimal("10.5"),
            },
        )

        self.assertFalse(
            validate_resource(invalid).is_valid
        )

        archive = replace(
            bucket,
            configuration={
                "volumeType": "Glacier Deep Archive"
            },
        )

        result = validate_resource(archive)

        self.assertTrue(result.is_valid)
        self.assertFalse(result.is_complete)

        self.assertIn(
            "monthly_retrieval_gb",
            {issue.field for issue in result.missing_usage},
        )

    def test_lambda_configuration(self):
        function = resource(
            ResourceType.LAMBDA_FUNCTION,
            {
                "architecture": "x86_64",
                "executionMode": "on_demand",
            },
            {
                "monthly_invocations": Decimal("2000000"),
                "average_duration_ms": Decimal("100"),
                "memory_mb": Decimal("512"),
                "ephemeral_storage_mb": Decimal("512"),
            },
        )

        self.assertTrue(
            validate_resource(function).is_complete
        )

        invalid = replace(
            function,
            usage={
                **function.usage,
                "memory_mb": Decimal("64"),
            },
        )

        self.assertFalse(
            validate_resource(invalid).is_valid
        )

    def test_dynamodb_capacity_modes(self):
        for mode, usage in (
            (
                "on_demand",
                {
                    "monthly_read_units": Decimal("1000000"),
                    "monthly_write_units": Decimal("250000"),
                },
            ),
            (
                "provisioned",
                {
                    "read_capacity_units": Decimal("5"),
                    "write_capacity_units": Decimal("5"),
                    "capacity_hours": Decimal("730"),
                },
            ),
        ):

            with self.subTest(mode=mode):

                table = resource(
                    ResourceType.DYNAMODB_TABLE,
                    {
                        "tableClass": "Standard",
                        "capacityMode": mode,
                    },
                    {
                        "average_storage_gb": Decimal("10"),
                        **usage,
                    },
                )

                self.assertTrue(
                    validate_resource(table).is_complete
                )

    def test_rds_configuration_and_boolean_deployment(self):
        database = resource(
            ResourceType.RDS_INSTANCE,
            {
                "instanceClass": "db.t3.medium",
                "engine": "mysql",
                "multiAZ": False,
                "volumeType": "gp2",
            },
            {
                "monthly_hours": Decimal("730"),
                "capacity_gib": Decimal("100"),
                "provisioned_hours": Decimal("730"),
            },
        )

        self.assertTrue(
            validate_resource(database).is_complete
        )

        invalid = replace(
            database,
            configuration={
                **database.configuration,
                "multiAZ": "False",
            },
        )

        self.assertFalse(
            validate_resource(invalid).is_valid
        )

    def test_alternative_pricing_models_are_outside_builder_scope(self):
        instance = replace(
            ec2(),
            pricing_model=PricingModel.SPOT,
        )

        self.assertFalse(
            validate_resource(instance).is_valid
        )

    def test_scenario_validation_and_empty_drafts(self):
        empty = InfrastructureScenario(name="Draft")

        self.assertTrue(
            validate_scenario(empty).is_valid
        )

        self.assertFalse(
            validate_scenario(empty).is_complete
        )

        complete = InfrastructureScenario(
            name="Complete",
            resources=(ec2(), ec2()),
        )

        self.assertTrue(
            validate_scenario(complete).is_complete
        )

        incomplete = InfrastructureScenario(
            name="Unknown usage",
            resources=(ec2(), ec2(None)),
        )

        result = validate_scenario(incomplete)

        self.assertTrue(result.is_valid)
        self.assertFalse(result.is_complete)

        invalid = InfrastructureScenario(
            name="Invalid usage",
            resources=(ec2(Decimal("900")),),
        )

        self.assertFalse(
            validate_scenario(invalid).is_valid
        )


if __name__ == "__main__":
    unittest.main()
