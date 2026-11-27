"""Verify monthly billing quantities and pricing query mappings."""

import unittest

from dataclasses import replace
from decimal import Decimal

from finops.estimation.components import (
    build_resource_components,
    build_scenario_components,
    multiply_usage,
)

from finops.infrastructure.models import (
    InfrastructureScenario,
    ResourceConfiguration,
    ResourceType,
)

from finops.pricing.resolver import RULES


D = Decimal


def resource(resource_type, configuration, usage, quantity=1):

    return ResourceConfiguration(
        name="Example resource",
        resource_type=resource_type,
        region="us-east-1",
        quantity=quantity,
        configuration=configuration,
        usage={
            key: None if value is None else D(value)
            for key, value in usage.items()
        },
    )


def components_for(instance):

    return {
        component.component: component
        for component in build_resource_components(instance)
    }


def ec2(hours="730", quantity=3):

    return resource(
        ResourceType.EC2_INSTANCE,
        {
            "instanceType": "t3.micro",
            "operatingSystem": "Linux",
            "tenancy": "Shared",
        },
        {"monthly_hours": hours},
        quantity,
    )


class BillingComponentTests(unittest.TestCase):

    def test_ec2_quantity_and_query_identity(self):

        result = components_for(ec2())["compute"]

        self.assertEqual(result.usage, D("2190"))
        self.assertEqual(result.unit, "Hrs")

        self.assertEqual(
            result.query.service_code,
            "AmazonEC2",
        )

        self.assertEqual(
            result.query.resource_type,
            "ec2_instance",
        )

        self.assertEqual(
            result.query.attributes["instanceType"],
            "t3.micro",
        )

        self.assertEqual(result.query.region, "us-east-1")

    def test_ebs_gp3_included_performance_and_proration(self):

        instance = resource(
            ResourceType.EBS_VOLUME,
            {"volumeType": "gp3"},
            {
                "capacity_gib": "100",
                "provisioned_hours": "365",
                "provisioned_iops": "5000",
                "provisioned_throughput_mibps": "225",
            },
            quantity=3,
        )

        results = components_for(instance)

        self.assertEqual(
            results["storage"].usage,
            D("150"),
        )

        self.assertEqual(
            results["additional_iops"].usage,
            D("3000"),
        )

        self.assertEqual(
            results["additional_throughput"].usage,
            D("150"),
        )

        included = replace(
            instance,
            usage={
                **instance.usage,
                "provisioned_iops": D("3000"),
                "provisioned_throughput_mibps": D("125"),
            },
        )

        results = components_for(included)

        self.assertEqual(
            results["additional_iops"].usage,
            D("0"),
        )

        self.assertEqual(
            results["additional_throughput"].usage,
            D("0"),
        )

    def test_ebs_io2_preserves_unsupported_iops(self):

        instance = resource(
            ResourceType.EBS_VOLUME,
            {"volumeType": "io2"},
            {
                "capacity_gib": "100",
                "provisioned_hours": "730",
                "provisioned_iops": "2000",
            },
        )

        results = components_for(instance)

        self.assertEqual(
            results["provisioned_iops"].usage,
            D("2000"),
        )

        self.assertIsNone(
            results["provisioned_iops"].query
        )

        self.assertNotIn(
            "additional_throughput",
            results,
        )

    def test_s3_usage_and_missing_pricing(self):

        instance = resource(
            ResourceType.S3_BUCKET,
            {"volumeType": "Standard"},
            {
                "average_storage_gb": "500",
                "monthly_put_requests": "1000",
                "monthly_get_requests": "0",
                "monthly_transfer_out_gb": None,
            },
            quantity=2,
        )

        results = components_for(instance)

        self.assertEqual(
            results["storage"].usage,
            D("1000"),
        )

        self.assertEqual(
            results["put_requests"].usage,
            D("2000"),
        )

        self.assertIsNone(
            results["put_requests"].query
        )

        self.assertEqual(
            results["get_requests"].usage,
            D("0"),
        )

        self.assertIsNone(
            results["transfer_out"].usage
        )

    def test_archive_retrieval_and_exclusions(self):

        instance = resource(
            ResourceType.S3_BUCKET,
            {"volumeType": "Glacier Deep Archive"},
            {
                "average_storage_gb": "500",
                "monthly_put_requests": "0",
                "monthly_get_requests": "0",
                "monthly_transfer_out_gb": "0",
                "monthly_retrieval_gb": "25",
            },
        )

        results = components_for(instance)

        self.assertEqual(
            results["retrieval"].usage,
            D("25"),
        )

        self.assertIsNone(
            results["retrieval"].query
        )

        self.assertTrue(
            results["minimum_storage_duration"].excluded
        )

    def test_lambda_duration_and_ephemeral_storage(self):

        instance = resource(
            ResourceType.LAMBDA_FUNCTION,
            {
                "architecture": "x86_64",
                "executionMode": "on_demand",
            },
            {
                "monthly_invocations": "2000000",
                "average_duration_ms": "100",
                "memory_mb": "512",
                "ephemeral_storage_mb": "1024",
            },
        )

        results = components_for(instance)

        self.assertEqual(
            results["requests"].usage,
            D("2000000"),
        )

        self.assertEqual(
            results["duration"].usage,
            D("100000"),
        )

        self.assertEqual(
            results["ephemeral_storage"].usage,
            D("100000"),
        )

        self.assertEqual(
            results["duration"].query.attributes[
                "architecture"
            ],
            "x86_64",
        )

        included = replace(
            instance,
            usage={
                **instance.usage,
                "ephemeral_storage_mb": D("512"),
            },
        )

        self.assertEqual(
            components_for(included)[
                "ephemeral_storage"
            ].usage,
            D("0"),
        )

    def test_dynamodb_on_demand_usage(self):

        instance = resource(
            ResourceType.DYNAMODB_TABLE,
            {
                "tableClass": "Standard",
                "capacityMode": "on_demand",
            },
            {
                "monthly_read_units": "1000000",
                "monthly_write_units": "250000",
                "average_storage_gb": "10",
            },
        )

        results = components_for(instance)

        self.assertEqual(
            results["read_requests"].usage,
            D("1000000"),
        )

        self.assertEqual(
            results["write_requests"].usage,
            D("250000"),
        )

        self.assertEqual(
            results["storage"].usage,
            D("10"),
        )

        self.assertEqual(
            results["read_requests"].unit,
            "RRU",
        )

        self.assertEqual(
            results["write_requests"].unit,
            "WRU",
        )

    def test_dynamodb_provisioned_capacity(self):

        instance = resource(
            ResourceType.DYNAMODB_TABLE,
            {
                "tableClass": "Standard",
                "capacityMode": "provisioned",
            },
            {
                "read_capacity_units": "5",
                "write_capacity_units": "10",
                "capacity_hours": "730",
                "average_storage_gb": "10",
            },
            quantity=2,
        )

        results = components_for(instance)

        self.assertEqual(
            results["read_capacity"].usage,
            D("7300"),
        )

        self.assertEqual(
            results["write_capacity"].usage,
            D("14600"),
        )

        self.assertIsNone(
            results["read_capacity"].query
        )

        self.assertNotIn(
            "read_requests",
            results,
        )

    def test_rds_preserves_unavailable_pricing(self):

        instance = resource(
            ResourceType.RDS_INSTANCE,
            {
                "instanceClass": "db.t3.medium",
                "engine": "mysql",
                "multiAZ": True,
                "volumeType": "gp3",
            },
            {
                "monthly_hours": "730",
                "capacity_gib": "100",
                "provisioned_hours": "730",
                "provisioned_iops": "3000",
                "provisioned_throughput_mibps": "125",
            },
        )

        results = components_for(instance)

        self.assertEqual(
            results["compute"].usage,
            D("730"),
        )

        self.assertEqual(
            results["storage"].usage,
            D("100"),
        )

        self.assertIsNone(results["compute"].query)

        self.assertIsNone(
            results["provisioned_iops"].usage
        )

        self.assertIsNone(
            results["provisioned_throughput"].usage
        )

        self.assertIn(
            "Multi-AZ",
            results["compute"].detail,
        )

    def test_unknown_and_zero_usage_propagation(self):

        unknown = components_for(ec2(None))["compute"]
        zero = components_for(ec2("0"))["compute"]

        self.assertIsNone(unknown.usage)
        self.assertEqual(zero.usage, D("0"))

        self.assertIsNone(
            multiply_usage(D("10"), None)
        )

        self.assertEqual(
            multiply_usage(D("0"), None),
            D("0"),
        )

        with self.assertRaises(ValueError):
            multiply_usage(D("0"), D("-1"))

    def test_invalid_configuration_is_rejected(self):

        with self.assertRaises(ValueError):
            build_resource_components(ec2("900"))

    def test_scenario_identity_and_pricing_rule_compatibility(self):

        first = ec2(quantity=2)
        second = ec2(quantity=3)

        scenario = InfrastructureScenario(
            name="Two resource groups",
            resources=(first, second),
        )

        components = build_scenario_components(scenario)

        self.assertEqual(len(components), 2)

        self.assertEqual(
            sum(item.usage for item in components),
            D("3650"),
        )

        self.assertEqual(
            {item.resource_id for item in components},
            {first.resource_id, second.resource_id},
        )

        for item in components:

            rule = RULES[
                (
                    item.query.resource_type,
                    item.query.cost_component,
                )
            ]

            self.assertEqual(item.unit, rule.unit)
            self.assertEqual(item.service_code, rule.service)

        self.assertEqual(
            build_scenario_components(
                InfrastructureScenario(name="Empty draft")
            ),
            (),
        )


if __name__ == "__main__":
    unittest.main()
