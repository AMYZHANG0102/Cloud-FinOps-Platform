"""Verify infrastructure estimates using deterministic pricing fixtures."""

import unittest

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from finops.estimation.engine import InfrastructureCostEstimator

from finops.estimation.financial import (
    CostStatus,
    EstimateStatus,
)

from finops.infrastructure.models import (
    InfrastructureScenario,
    ResourceConfiguration,
    ResourceType,
)

from finops.pricing.models import (
    PriceDimension,
    PricingRecord,
    PricingResolution,
    PricingSource,
    ResolutionStatus,
)


D = Decimal


def ec2(hours="730", quantity=3, region="us-east-1"):

    return ResourceConfiguration(
        name="Web servers",
        resource_type=ResourceType.EC2_INSTANCE,
        region=region,
        quantity=quantity,
        configuration={
            "instanceType": "t3.micro",
            "operatingSystem": "Linux",
            "tenancy": "Shared",
        },
        usage={
            "monthly_hours": (
                None if hours is None else D(hours)
            ),
        },
    )


def s3(
    storage="500",
    put="0",
    get="0",
    transfer="0",
    region="us-east-1",
    classification=None,
):

    configuration = {
        "volumeType": "Standard",
    }

    if classification is not None:
        configuration["storageClass"] = classification

    return ResourceConfiguration(
        name="Object storage",
        resource_type=ResourceType.S3_BUCKET,
        region=region,
        configuration=configuration,
        usage={
            "average_storage_gb": D(storage),
            "monthly_put_requests": (
                None if put is None else D(put)
            ),
            "monthly_get_requests": (
                None if get is None else D(get)
            ),
            "monthly_transfer_out_gb": (
                None if transfer is None else D(transfer)
            ),
        },
    )


def scenario(*resources):

    return InfrastructureScenario(
        name="Estimation test",
        resources=resources,
    )


class FixtureResolver:
    """Return known pricing while recording resolver calls."""

    def __init__(
        self,
        *,
        failure=None,
        reference=False,
        force_partial=False,
    ):

        self.calls = []
        self.failure = failure
        self.reference = reference
        self.force_partial = force_partial

    def resolve(
        self,
        query,
        *,
        usage=None,
        allow_reference=False,
        force_refresh=False,
    ):

        self.calls.append((
            query,
            usage,
            allow_reference,
            force_refresh,
        ))

        if self.failure is not None:

            return PricingResolution(
                query=query,
                status=self.failure,
                diagnostics=("Simulated pricing failure.",),
            )

        if query.service_code == "AmazonEC2":

            rate = D("0.0104")
            unit = "Hrs"
            end = None
            sku = "fixture-ec2"
            family = "Compute Instance"
            attributes = dict(query.attributes)

        elif (
            query.service_code == "AmazonS3"
            and query.attributes.get("volumeType") == "Standard"
        ):

            rate = D("0.023")
            unit = "GB-Mo"
            end = D("51200")
            sku = "fixture-s3"
            family = "Storage"

            attributes = {
                "volumeType": "Standard",
                "storageClass": "General Purpose",
            }

        else:

            return PricingResolution(
                query=query,
                status=ResolutionStatus.UNAVAILABLE,
                diagnostics=("No matching fixture rate.",),
            )

        timestamp = datetime.now(timezone.utc)

        source = (
            PricingSource.REFERENCE_DATA
            if self.reference
            else PricingSource.FLOCI_PRICING_API
        )

        record = PricingRecord(
            service_code=query.service_code,
            sku=sku,
            product_family=family,
            region=query.region,
            attributes=attributes,
            pricing_model=query.pricing_model,
            offer_term_code="fixture-on-demand",
            dimensions=(
                PriceDimension(
                    rate_code=f"{sku}-rate",
                    unit=unit,
                    currency="USD",
                    unit_price=rate,
                    begin_range=D("0"),
                    end_range=end,
                    cost_component=query.cost_component,
                ),
            ),
            source=source,
            source_reference=(
                "https://aws.amazon.com/ec2/pricing/"
                if self.reference
                else "test-pricing-fixture"
            ),
            retrieved_at=timestamp,
            verified_at=(
                timestamp if self.reference else None
            ),
        )

        partial = (
            self.force_partial
            or (end is not None and usage > end)
        )

        return PricingResolution(
            query=query,
            status=(
                ResolutionStatus.PARTIAL
                if partial
                else ResolutionStatus.RESOLVED
            ),
            records=(record,),
            missing_components=(
                (query.cost_component,)
                if partial
                else ()
            ),
        )


class EstimationEngineTests(unittest.TestCase):

    def test_complete_estimate_and_resource_service_totals(self):

        resolver = FixtureResolver()
        instance = ec2()
        bucket = s3()

        result = InfrastructureCostEstimator(
            resolver
        ).estimate(scenario(instance, bucket))

        self.assertEqual(
            result.summary.status,
            EstimateStatus.COMPLETE,
        )

        self.assertEqual(
            result.summary.complete_monthly_cost,
            D("34.276"),
        )

        self.assertEqual(
            result.resource_summary(
                instance.resource_id
            ).complete_monthly_cost,
            D("22.776"),
        )

        self.assertEqual(
            result.service_summary(
                "AmazonS3"
            ).complete_monthly_cost,
            D("11.50"),
        )

        self.assertEqual(len(resolver.calls), 2)

        self.assertEqual(
            result.components[0].resolution.records[0].source,
            PricingSource.FLOCI_PRICING_API,
        )

    def test_zero_and_unknown_usage_do_not_require_lookup(self):

        resolver = FixtureResolver()

        result = InfrastructureCostEstimator(
            resolver
        ).estimate(scenario(ec2("0"), ec2(None)))

        self.assertEqual(resolver.calls, [])

        self.assertEqual(
            result.components[0].estimate.status,
            CostStatus.ZERO_USAGE,
        )

        self.assertEqual(
            result.components[1].estimate.status,
            CostStatus.UNRESOLVED,
        )

        self.assertEqual(
            result.summary.status,
            EstimateStatus.PARTIAL,
        )

        self.assertIsNone(
            result.summary.complete_monthly_cost
        )

    def test_unsupported_positive_s3_usage_remains_unresolved(self):

        result = InfrastructureCostEstimator(
            FixtureResolver()
        ).estimate(
            scenario(s3(put="100", get=None))
        )

        components = {
            item.billing.component: item.estimate
            for item in result.components
        }

        self.assertEqual(
            components["storage"].known_monthly_cost,
            D("11.50"),
        )

        self.assertEqual(
            components["put_requests"].status,
            CostStatus.UNRESOLVED,
        )

        self.assertEqual(
            components["get_requests"].status,
            CostStatus.UNRESOLVED,
        )

        self.assertEqual(
            components["transfer_out"].status,
            CostStatus.ZERO_USAGE,
        )

        self.assertIsNone(
            result.summary.complete_monthly_cost
        )

    def test_identical_s3_queries_share_bounded_tier(self):

        resolver = FixtureResolver()

        result = InfrastructureCostEstimator(
            resolver
        ).estimate(
            scenario(s3("30000"), s3("30000"))
        )

        self.assertEqual(len(resolver.calls), 1)
        self.assertEqual(resolver.calls[0][1], D("60000"))

        storage = [
            item
            for item in result.components
            if item.billing.component == "storage"
        ]

        for item in storage:

            self.assertEqual(
                item.estimate.status,
                CostStatus.PARTIAL,
            )

            self.assertEqual(
                item.estimate.priced_usage,
                D("25600"),
            )

            self.assertEqual(
                item.estimate.known_monthly_cost,
                D("588.80"),
            )

        self.assertEqual(
            storage[0].pool_id,
            storage[1].pool_id,
        )

        self.assertEqual(
            result.summary.known_monthly_cost,
            D("1177.60"),
        )

        self.assertIsNone(
            result.summary.complete_monthly_cost
        )

    def test_different_queries_resolving_same_offer_are_pooled(self):

        resolver = FixtureResolver()

        result = InfrastructureCostEstimator(
            resolver
        ).estimate(
            scenario(
                s3("30000"),
                s3(
                    "30000",
                    classification="General Purpose",
                ),
            )
        )

        self.assertEqual(len(resolver.calls), 2)

        self.assertEqual(
            result.summary.known_monthly_cost,
            D("1177.60"),
        )

        self.assertEqual(
            result.summary.status,
            EstimateStatus.PARTIAL,
        )

    def test_different_regions_are_not_pooled(self):

        result = InfrastructureCostEstimator(
            FixtureResolver()
        ).estimate(
            scenario(
                s3("30000", region="us-east-1"),
                s3("30000", region="us-west-2"),
            )
        )

        self.assertEqual(
            result.summary.complete_monthly_cost,
            D("1380"),
        )

        storage = [
            item
            for item in result.components
            if item.billing.component == "storage"
        ]

        self.assertNotEqual(
            storage[0].pool_id,
            storage[1].pool_id,
        )

    def test_reference_policy_is_explicitly_enforced(self):

        resolver = FixtureResolver(reference=True)

        estimator = InfrastructureCostEstimator(
            resolver
        )

        infrastructure = scenario(ec2())

        strict = estimator.estimate(infrastructure)

        self.assertEqual(
            strict.summary.status,
            EstimateStatus.UNAVAILABLE,
        )

        allowed = estimator.estimate(
            infrastructure,
            allow_reference=True,
            force_refresh=True,
        )

        self.assertEqual(
            allowed.summary.complete_monthly_cost,
            D("22.776"),
        )

        self.assertTrue(resolver.calls[-1][2])
        self.assertTrue(resolver.calls[-1][3])

    def test_api_failure_cannot_become_zero_cost(self):

        result = InfrastructureCostEstimator(
            FixtureResolver(
                failure=ResolutionStatus.API_ERROR
            )
        ).estimate(
            scenario(ec2()),
            allow_reference=True,
        )

        self.assertEqual(
            result.summary.status,
            EstimateStatus.UNAVAILABLE,
        )

        self.assertIsNone(
            result.summary.complete_monthly_cost
        )

        self.assertEqual(
            result.components[0].resolution.status,
            ResolutionStatus.API_ERROR,
        )

    def test_empty_and_invalid_scenarios(self):

        estimator = InfrastructureCostEstimator(
            FixtureResolver()
        )

        empty = estimator.estimate(scenario())

        self.assertEqual(
            empty.summary.status,
            EstimateStatus.UNAVAILABLE,
        )

        self.assertEqual(empty.components, ())

        with self.assertRaises(ValueError):

            estimator.estimate(
                scenario(ec2("900"))
            )

    def test_archive_exclusions_are_retained(self):

        bucket = replace(
            s3(),
            configuration={
                "volumeType": "Glacier Deep Archive",
            },
            usage={
                **s3().usage,
                "monthly_retrieval_gb": D("25"),
            },
        )

        result = InfrastructureCostEstimator(
            FixtureResolver()
        ).estimate(scenario(bucket))

        self.assertEqual(
            result.summary.excluded_components,
            1,
        )

        self.assertEqual(
            result.summary.unresolved_components,
            2,
        )

        self.assertIsNone(
            result.summary.complete_monthly_cost
        )

    def test_partial_resolution_cannot_claim_full_coverage(self):

        result = InfrastructureCostEstimator(
            FixtureResolver(force_partial=True)
        ).estimate(scenario(ec2()))

        self.assertEqual(
            result.summary.status,
            EstimateStatus.UNAVAILABLE,
        )

        self.assertIsNone(
            result.summary.complete_monthly_cost
        )


if __name__ == "__main__":
    unittest.main()
