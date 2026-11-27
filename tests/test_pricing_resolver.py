"""Verify pricing precedence, exact matching and usage coverage."""

import unittest

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from finops.pricing.models import (
    PriceDimension,
    PricingModel,
    PricingQuery,
    PricingRecord,
    PricingSource,
    ResolutionStatus,
)

from finops.pricing.products import PricingProductError
from finops.pricing.reference import load_reference_rates
from finops.pricing.resolver import PricingResolver


def ec2_query(**changes):

    original = PricingQuery(
        service_code="AmazonEC2",
        resource_type="ec2_instance",
        region="us-east-1",
        pricing_model=PricingModel.ON_DEMAND,
        cost_component="compute",
        attributes={
            "instanceType": "t3.micro",
            "operatingSystem": "Linux",
            "tenancy": "Shared",
        },
    )

    return replace(original, **changes)


def ebs_query(**changes):

    original = PricingQuery(
        service_code="AmazonEC2",
        resource_type="ebs_volume",
        region="us-east-1",
        pricing_model=PricingModel.ON_DEMAND,
        cost_component="storage",
        attributes={"volumeType": "gp3"},
    )

    return replace(original, **changes)


def ec2_record():

    return PricingRecord(
        service_code="AmazonEC2",
        sku="TEST-EC2",
        product_family="Compute Instance",
        region="us-east-1",
        attributes=ec2_query().attributes,
        pricing_model=PricingModel.ON_DEMAND,
        offer_term_code="TEST-TERM",
        dimensions=(
            PriceDimension(
                rate_code="TEST-RATE",
                unit="Hrs",
                currency="USD",
                unit_price=Decimal("0.0104"),
                begin_range=Decimal("0"),
                end_range=None,
                cost_component="compute",
            ),
        ),
        source=PricingSource.FLOCI_PRICING_API,
        source_reference="Synthetic test record",
        retrieved_at=datetime.now(timezone.utc),
    )


class PricingResolverTests(unittest.TestCase):

    def setUp(self):

        self.cache = Mock()

        self.cache.load.return_value = None

        self.cache.refresh.return_value = (
            SimpleNamespace(records=())
        )

        self.resolver = PricingResolver(
            cache=self.cache,
            reference_rates=load_reference_rates(),
        )

    def set_records(self, *records):

        self.cache.refresh.return_value = (
            SimpleNamespace(records=records)
        )

    def test_exact_floci_price_is_selected(self):

        self.set_records(ec2_record())

        result = self.resolver.resolve(
            ec2_query(),
            usage=Decimal("730"),
            allow_reference=True,
        )

        self.assertEqual(
            result.status, ResolutionStatus.RESOLVED
        )

        self.assertEqual(
            result.records[0].source,
            PricingSource.FLOCI_PRICING_API,
        )

    def test_reference_pricing_requires_permission(self):

        strict = self.resolver.resolve(
            ebs_query()
        )

        allowed = self.resolver.resolve(
            ebs_query(),
            allow_reference=True,
        )

        self.assertEqual(
            strict.status, ResolutionStatus.UNAVAILABLE
        )

        self.assertEqual(
            allowed.status, ResolutionStatus.RESOLVED
        )

        self.assertEqual(
            allowed.records[0].source,
            PricingSource.REFERENCE_DATA,
        )

        self.assertEqual(
            allowed.records[0].dimensions[0].unit_price,
            Decimal("0.08"),
        )

    def test_primary_rate_has_precedence_over_reference(self):

        reference = next(
            item.record
            for item in load_reference_rates()
            if item.reference_id
            == "REF-EBS-GP3-STORAGE-USE1"
        )

        primary = replace(
            reference,
            source=PricingSource.FLOCI_PRICING_API,
            retrieved_at=datetime.now(timezone.utc),
        )

        self.set_records(primary)

        result = self.resolver.resolve(
            ebs_query(), allow_reference=True
        )

        self.assertEqual(
            result.records[0].source,
            PricingSource.FLOCI_PRICING_API,
        )

    def test_unexpected_failure_never_uses_reference(self):

        for code in (
            "EndpointConnectionError",
            "InvalidParameterException",
            "PAGE_LIMIT_EXCEEDED",
        ):
            with self.subTest(code=code):

                self.cache.refresh.side_effect = (
                    PricingProductError(
                        code,
                        "Synthetic failure",
                    )
                )

                result = self.resolver.resolve(
                    ebs_query(),
                    allow_reference=True,
                )

                self.assertEqual(
                    result.status,
                    ResolutionStatus.API_ERROR,
                )

                self.assertFalse(result.records)

    def test_confirmed_unsupported_service_allows_reference(self):

        self.cache.refresh.side_effect = (
            PricingProductError(
                "InvalidParameterException",
                "Service rejected",
                http_status=400,
                api_message="Invalid ServiceCode: AmazonDynamoDB",
            )
        )

        self.resolver._advertised_services = Mock(
            return_value={
                "AmazonEC2",
                "AmazonS3",
                "AWSLambda",
            }
        )

        query = PricingQuery(
            service_code="AmazonDynamoDB",
            resource_type="table",
            region="us-east-1",
            pricing_model=PricingModel.ON_DEMAND,
            cost_component="write_requests",
            attributes={
                "tableClass": "Standard",
                "capacityMode": "on_demand",
            },
        )

        strict = self.resolver.resolve(query)

        allowed = self.resolver.resolve(
            query, allow_reference=True
        )

        self.assertEqual(
            strict.status, ResolutionStatus.UNSUPPORTED
        )

        self.assertEqual(
            allowed.status, ResolutionStatus.RESOLVED
        )

        self.assertEqual(
            allowed.records[0].source,
            PricingSource.REFERENCE_DATA,
        )

        # A rejected but advertised service is an API failure.

        self.resolver._advertised_services.return_value.add(
            "AmazonDynamoDB"
        )

        rejected = self.resolver.resolve(
            query, allow_reference=True
        )

        self.assertEqual(
            rejected.status, ResolutionStatus.API_ERROR
        )

    def test_service_rejection_message_must_match_requested_service(self):

        query = PricingQuery(
            service_code="AmazonDynamoDB",
            resource_type="table",
            region="us-east-1",
            pricing_model=PricingModel.ON_DEMAND,
            cost_component="write_requests",
            attributes={
                "tableClass": "Standard",
                "capacityMode": "on_demand",
            },
        )

        self.resolver._advertised_services = Mock(
            return_value={"AmazonEC2", "AmazonS3", "AWSLambda"}
        )

        cases = (
            ("Invalid ServiceCode", ResolutionStatus.RESOLVED),
            (
                "Invalid ServiceCode: AmazonDynamoDB",
                ResolutionStatus.RESOLVED,
            ),
            (
                "Invalid ServiceCode: AmazonRDS",
                ResolutionStatus.API_ERROR,
            ),
            (
                "Invalid ServiceCode: AmazonDynamoDB unexpected",
                ResolutionStatus.API_ERROR,
            ),
            (
                "Invalid filter configuration",
                ResolutionStatus.API_ERROR,
            ),
        )

        for message, expected in cases:

            with self.subTest(message=message):

                self.cache.refresh.side_effect = PricingProductError(
                    "InvalidParameterException",
                    "Synthetic rejection",
                    http_status=400,
                    api_message=message,
                )

                result = self.resolver.resolve(
                    query,
                    allow_reference=True,
                )

                self.assertEqual(result.status, expected)

                if expected == ResolutionStatus.API_ERROR:
                    self.assertFalse(result.records)

    def test_configuration_and_region_are_not_substituted(self):

        self.set_records(ec2_record())

        for query in (
            ec2_query(region="us-west-2"),
            ec2_query(
                attributes={
                    "instanceType": "t3.small",
                    "operatingSystem": "Linux",
                    "tenancy": "Shared",
                }
            ),
        ):
            with self.subTest(query=query):

                result = self.resolver.resolve(
                    query,
                    allow_reference=True,
                )

                self.assertEqual(
                    result.status,
                    ResolutionStatus.UNAVAILABLE,
                )

                self.assertFalse(result.records)

    def test_invalid_query_is_rejected_before_retrieval(self):

        result = self.resolver.resolve(
            ec2_query(
                attributes={"instanceType": "t3.micro"}
            )
        )

        self.assertEqual(
            result.status, ResolutionStatus.INVALID
        )

        self.cache.refresh.assert_not_called()

    def test_ambiguous_offers_are_not_selected(self):

        first = ec2_record()

        second = replace(
            first,
            sku="OTHER-EC2",
            source_reference="Other synthetic offer",
        )

        self.set_records(first, second)

        result = self.resolver.resolve(
            ec2_query(),
            allow_reference=True,
        )

        self.assertEqual(
            result.status, ResolutionStatus.AMBIGUOUS
        )

        self.assertFalse(result.records)

    def test_wrong_billing_unit_is_rejected(self):

        record = ec2_record()

        invalid = replace(
            record,
            dimensions=(
                replace(
                    record.dimensions[0],
                    unit="GB-Mo",
                ),
            ),
        )

        self.set_records(invalid)

        result = self.resolver.resolve(
            ec2_query(),
            allow_reference=True,
        )

        self.assertEqual(
            result.status, ResolutionStatus.INVALID
        )

    def test_finite_tier_returns_partial_for_excess_usage(self):

        record = replace(
            ec2_record(),
            dimensions=(
                replace(
                    ec2_record().dimensions[0],
                    end_range=Decimal("100"),
                ),
            ),
        )

        self.set_records(record)

        exact = self.resolver.resolve(
            ec2_query(),
            usage=Decimal("100"),
        )

        partial = self.resolver.resolve(
            ec2_query(),
            usage=Decimal("101"),
        )

        self.assertEqual(
            exact.status, ResolutionStatus.RESOLVED
        )

        self.assertEqual(
            partial.status, ResolutionStatus.PARTIAL
        )

        self.assertTrue(partial.records)
        self.assertTrue(partial.missing_components)

    def test_overlapping_or_gapped_tiers_are_rejected(self):

        record = ec2_record()

        first = replace(
            record.dimensions[0],
            end_range=Decimal("100"),
        )

        for start in ("90", "110"):

            with self.subTest(start=start):

                second = replace(
                    record.dimensions[0],
                    rate_code="SECOND-RATE",
                    begin_range=Decimal(start),
                )

                self.set_records(
                    replace(
                        record,
                        dimensions=(first, second),
                    )
                )

                result = self.resolver.resolve(
                    ec2_query(),
                    usage=Decimal("200"),
                )

                self.assertEqual(
                    result.status,
                    ResolutionStatus.INVALID,
                )

    def test_fresh_cache_and_explicit_refresh(self):

        self.cache.load.return_value = (
            SimpleNamespace(
                is_fresh=True,
                catalogue=SimpleNamespace(
                    records=(ec2_record(),)
                ),
            )
        )

        cached = self.resolver.resolve(ec2_query())

        self.assertEqual(
            cached.status, ResolutionStatus.RESOLVED
        )

        self.cache.refresh.assert_not_called()

        self.set_records(ec2_record())

        refreshed = self.resolver.resolve(
            ec2_query(),
            force_refresh=True,
        )

        self.assertEqual(
            refreshed.status, ResolutionStatus.RESOLVED
        )

        self.cache.refresh.assert_called_once_with(
            "AmazonEC2"
        )

    def test_stale_cache_is_not_automatically_substituted(self):

        self.cache.load.return_value = (
            SimpleNamespace(
                is_fresh=False,
                catalogue=SimpleNamespace(
                    records=(ec2_record(),)
                ),
            )
        )

        self.cache.refresh.side_effect = (
            PricingProductError(
                "EndpointConnectionError",
                "Synthetic failure",
            )
        )

        result = self.resolver.resolve(
            ec2_query(),
            allow_reference=True,
        )

        self.assertEqual(
            result.status, ResolutionStatus.API_ERROR
        )

        self.assertFalse(result.records)

    def test_unsupported_pricing_model_is_explicit(self):

        result = self.resolver.resolve(
            ec2_query(
                pricing_model=PricingModel.SPOT
            )
        )

        self.assertEqual(
            result.status, ResolutionStatus.UNSUPPORTED
        )

        self.cache.refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
