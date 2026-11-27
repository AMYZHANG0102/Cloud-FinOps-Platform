"""Unit tests for normalized pricing domain contracts."""

import unittest

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from finops.pricing.models import (
    PriceDimension,
    PricingModel,
    PricingQuery,
    PricingRecord,
    PricingResolution,
    PricingSource,
    ResolutionStatus,
    SpotPriceObservation,
)


UTC_TIME = datetime(
    2026, 11, 26, 18, 0,
    tzinfo=timezone.utc,
)


def make_dimension(**overrides):
    values = {
        "rate_code": "TEST-EC2-COMPUTE",
        "unit": "Hrs",
        "currency": "USD",
        "unit_price": Decimal("0.0104"),
        "begin_range": Decimal("0"),
        "end_range": None,
        "description": "EC2 compute charge",
        "cost_component": "compute",
    }

    values.update(overrides)

    return PriceDimension(**values)


def make_record(**overrides):
    values = {
        "service_code": "AmazonEC2",
        "sku": "FLOCI-EC2-T3MICRO-USE1",
        "product_family": "Compute Instance",
        "region": "us-east-1",
        "attributes": {
            "instanceType": "t3.micro",
            "operatingSystem": "Linux",
            "tenancy": "Shared",
        },
        "pricing_model": PricingModel.ON_DEMAND,
        "offer_term_code": "TEST-ON-DEMAND",
        "dimensions": (make_dimension(),),
        "source": PricingSource.FLOCI_PRICING_API,
        "source_reference": "pricing.GetProducts",
        "retrieved_at": UTC_TIME,
    }

    values.update(overrides)

    return PricingRecord(**values)


def make_query(**overrides):
    values = {
        "service_code": "AmazonEC2",
        "resource_type": "instance",
        "region": "us-east-1",
        "pricing_model": PricingModel.ON_DEMAND,
        "cost_component": "compute",
        "attributes": {
            "instanceType": "t3.micro",
            "operatingSystem": "Linux",
            "tenancy": "Shared",
        },
    }

    values.update(overrides)

    return PricingQuery(**values)


def make_spot(**overrides):
    values = {
        "instance_type": "t3.micro",
        "region": "us-east-1",
        "availability_zone": "us-east-1a",
        "product_description": "Linux/UNIX",
        "unit_price": Decimal("0.004400"),
        "observed_at": UTC_TIME,
        "retrieved_at": UTC_TIME,
    }

    values.update(overrides)

    return SpotPriceObservation(**values)


class PricingEnumerationTests(unittest.TestCase):

    def test_supported_pricing_models(self):
        self.assertEqual(
            {item.value for item in PricingModel},
            {
                "ON_DEMAND",
                "RESERVED",
                "SAVINGS_PLAN",
                "SPOT",
            },
        )

    def test_pricing_sources_and_statuses_are_separate(self):
        self.assertEqual(len(PricingSource), 4)
        self.assertEqual(len(ResolutionStatus), 7)

        self.assertNotIn(
            "UNAVAILABLE",
            {item.value for item in PricingSource},
        )


class PriceDimensionTests(unittest.TestCase):

    def test_decimal_precision_is_preserved(self):
        rate = Decimal("0.0000002000")

        dimension = make_dimension(
            unit_price=rate,
            unit="Requests",
        )

        self.assertEqual(dimension.unit_price, rate)

        self.assertEqual(
            dimension.unit_price.as_tuple(),
            rate.as_tuple(),
        )

        self.assertEqual(
            dimension.unit_price * Decimal("1000000"),
            Decimal("0.20"),
        )

    def test_genuine_zero_price_is_valid(self):
        dimension = make_dimension(
            unit_price=Decimal("0")
        )

        self.assertEqual(
            dimension.unit_price,
            Decimal("0"),
        )

    def test_invalid_prices_are_rejected(self):
        invalid_prices = (
            Decimal("-0.01"),
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
            0.01,
            "0.01",
            1,
            None,
        )

        for value in invalid_prices:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    make_dimension(unit_price=value)

    def test_unbounded_usage_range(self):
        dimension = make_dimension(end_range=None)

        self.assertTrue(dimension.is_unbounded)

    def test_finite_usage_range(self):
        dimension = make_dimension(
            unit="GB-Mo",
            unit_price=Decimal("0.023"),
            end_range=Decimal("51200"),
        )

        self.assertFalse(dimension.is_unbounded)

        self.assertEqual(
            dimension.end_range,
            Decimal("51200"),
        )

    def test_invalid_usage_ranges_are_rejected(self):
        invalid_ranges = (
            (Decimal("-1"), None),
            (Decimal("NaN"), None),
            (Decimal("0"), Decimal("0")),
            (Decimal("10"), Decimal("5")),
            (Decimal("0"), Decimal("Infinity")),
        )

        for begin, end in invalid_ranges:
            with self.subTest(begin=begin, end=end):
                with self.assertRaises(ValueError):
                    make_dimension(
                        begin_range=begin,
                        end_range=end,
                    )

    def test_invalid_currency_is_rejected(self):
        for currency in ("", "usd", "US", "US1", None):
            with self.subTest(currency=currency):
                with self.assertRaises(ValueError):
                    make_dimension(currency=currency)

    def test_empty_billing_unit_is_rejected(self):
        with self.assertRaises(ValueError):
            make_dimension(unit=" ")

    def test_price_dimensions_are_immutable(self):
        dimension = make_dimension()

        with self.assertRaises(FrozenInstanceError):
            dimension.unit_price = Decimal("0.50")

    def test_applicability_list_is_copied(self):
        applicable = ["example"]

        dimension = make_dimension(
            applies_to=applicable
        )

        applicable.append("unexpected")

        self.assertEqual(
            dimension.applies_to,
            ("example",),
        )


class PricingRecordTests(unittest.TestCase):

    def test_valid_pricing_record(self):
        record = make_record()

        self.assertEqual(record.service_code, "AmazonEC2")
        self.assertEqual(record.region, "us-east-1")

        self.assertEqual(
            record.dimensions[0].unit_price,
            Decimal("0.0104"),
        )

    def test_product_attributes_are_copied(self):
        attributes = {"instanceType": "t3.micro"}

        record = make_record(attributes=attributes)

        attributes["instanceType"] = "m5.large"

        self.assertEqual(
            record.attributes["instanceType"],
            "t3.micro",
        )

    def test_product_attributes_are_read_only(self):
        record = make_record()

        with self.assertRaises(TypeError):
            record.attributes["instanceType"] = "m5.large"

    def test_term_attributes_are_copied_and_read_only(self):
        attributes = {"LeaseContractLength": "1yr"}

        record = make_record(
            term_attributes=attributes
        )

        attributes["LeaseContractLength"] = "3yr"

        self.assertEqual(
            record.term_attributes["LeaseContractLength"],
            "1yr",
        )

        with self.assertRaises(TypeError):
            record.term_attributes["LeaseContractLength"] = "3yr"

    def test_dimension_collection_is_copied(self):
        dimensions = [make_dimension()]

        record = make_record(dimensions=dimensions)

        dimensions.clear()

        self.assertEqual(len(record.dimensions), 1)

    def test_empty_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            make_record(dimensions=())

    def test_duplicate_dimensions_are_rejected(self):
        dimension = make_dimension()

        with self.assertRaises(ValueError):
            make_record(
                dimensions=(dimension, dimension)
            )

    def test_distinct_tiers_are_preserved(self):
        first = make_dimension(
            rate_code="TIER-1",
            begin_range=Decimal("0"),
            end_range=Decimal("51200"),
        )

        second = make_dimension(
            rate_code="TIER-2",
            begin_range=Decimal("51200"),
            end_range=None,
        )

        record = make_record(
            dimensions=(first, second)
        )

        self.assertEqual(
            record.dimensions,
            (first, second),
        )

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            make_record(
                retrieved_at=datetime(2026, 11, 26)
            )

    def test_timestamp_is_normalized_to_utc(self):
        offset = timezone(timedelta(hours=-5))

        source_time = datetime(
            2026, 11, 26, 13, 0,
            tzinfo=offset,
        )

        record = make_record(
            retrieved_at=source_time
        )

        self.assertEqual(
            record.retrieved_at,
            UTC_TIME,
        )

        self.assertIs(
            record.retrieved_at.tzinfo,
            timezone.utc,
        )

    def test_unknown_effective_date_is_preserved(self):
        record = make_record(effective_date=None)

        self.assertIsNone(record.effective_date)

    def test_floci_retrieval_timestamp_is_required(self):
        with self.assertRaises(ValueError):
            make_record(retrieved_at=None)

    def test_reference_verification_timestamp_is_required(self):
        with self.assertRaises(ValueError):
            make_record(
                source=PricingSource.REFERENCE_DATA,
                verified_at=None,
            )

        record = make_record(
            source=PricingSource.REFERENCE_DATA,
            source_reference="TEST-REFERENCE",
            verified_at=UTC_TIME,
        )

        self.assertEqual(
            record.source,
            PricingSource.REFERENCE_DATA,
        )

    def test_assumed_price_requires_explicit_assumptions(self):
        with self.assertRaises(ValueError):
            make_record(
                source=PricingSource.ESTIMATION_ASSUMPTION,
                assumptions=(),
            )

        record = make_record(
            source=PricingSource.ESTIMATION_ASSUMPTION,
            source_reference="TEST-ASSUMPTION",
            assumptions=("Hypothetical test rate",),
        )

        self.assertEqual(
            record.assumptions,
            ("Hypothetical test rate",),
        )

    def test_record_is_immutable(self):
        record = make_record()

        with self.assertRaises(FrozenInstanceError):
            record.region = "us-west-2"


class PricingQueryTests(unittest.TestCase):

    def test_valid_query_uses_usd_by_default(self):
        query = make_query()

        self.assertEqual(query.currency, "USD")
        self.assertEqual(query.cost_component, "compute")

    def test_empty_required_query_fields_are_rejected(self):
        for name in (
            "service_code",
            "resource_type",
            "region",
            "cost_component",
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    make_query(**{name: ""})

    def test_empty_query_attribute_is_rejected(self):
        with self.assertRaises(ValueError):
            make_query(
                attributes={"instanceType": ""}
            )

    def test_query_attributes_are_independent(self):
        attributes = {"instanceType": "t3.micro"}

        query = make_query(attributes=attributes)

        attributes.clear()

        self.assertEqual(
            query.attributes["instanceType"],
            "t3.micro",
        )


class PricingResolutionTests(unittest.TestCase):

    def test_successful_resolution(self):
        result = PricingResolution(
            query=make_query(),
            status=ResolutionStatus.RESOLVED,
            records=(make_record(),),
        )

        self.assertTrue(result.has_usable_prices)
        self.assertTrue(result.is_complete)

    def test_resolved_status_requires_records(self):
        with self.assertRaises(ValueError):
            PricingResolution(
                query=make_query(),
                status=ResolutionStatus.RESOLVED,
            )

    def test_resolved_status_rejects_missing_components(self):
        with self.assertRaises(ValueError):
            PricingResolution(
                query=make_query(),
                status=ResolutionStatus.RESOLVED,
                records=(make_record(),),
                missing_components=("storage",),
            )

    def test_partial_resolution_preserves_known_records(self):
        result = PricingResolution(
            query=make_query(),
            status=ResolutionStatus.PARTIAL,
            records=(make_record(),),
            missing_components=("additional_tier",),
        )

        self.assertTrue(result.has_usable_prices)
        self.assertFalse(result.is_complete)

    def test_partial_resolution_requires_missing_components(self):
        with self.assertRaises(ValueError):
            PricingResolution(
                query=make_query(),
                status=ResolutionStatus.PARTIAL,
                records=(make_record(),),
            )

    def test_unavailable_price_is_not_zero(self):
        result = PricingResolution(
            query=make_query(),
            status=ResolutionStatus.UNAVAILABLE,
            diagnostics=("No matching pricing record",),
        )

        self.assertFalse(result.has_usable_prices)
        self.assertFalse(result.is_complete)
        self.assertEqual(result.records, ())

    def test_api_error_diagnostics_are_preserved(self):
        result = PricingResolution(
            query=make_query(),
            status=ResolutionStatus.API_ERROR,
            diagnostics=("Local endpoint unavailable",),
        )

        self.assertEqual(
            result.diagnostics,
            ("Local endpoint unavailable",),
        )

    def test_unsuccessful_resolution_rejects_selected_records(self):
        statuses = (
            ResolutionStatus.UNAVAILABLE,
            ResolutionStatus.UNSUPPORTED,
            ResolutionStatus.AMBIGUOUS,
            ResolutionStatus.INVALID,
            ResolutionStatus.API_ERROR,
        )

        for status in statuses:
            with self.subTest(status=status):
                with self.assertRaises(ValueError):
                    PricingResolution(
                        query=make_query(),
                        status=status,
                        records=(make_record(),),
                    )

    def test_mismatched_pricing_region_is_rejected(self):
        record = make_record(region="us-west-2")

        with self.assertRaises(ValueError):
            PricingResolution(
                query=make_query(),
                status=ResolutionStatus.RESOLVED,
                records=(record,),
            )

    def test_mismatched_pricing_service_is_rejected(self):
        record = make_record(
            service_code="AmazonS3"
        )

        with self.assertRaises(ValueError):
            PricingResolution(
                query=make_query(),
                status=ResolutionStatus.RESOLVED,
                records=(record,),
            )

    def test_mismatched_pricing_model_is_rejected(self):
        record = make_record(
            pricing_model=PricingModel.RESERVED
        )

        with self.assertRaises(ValueError):
            PricingResolution(
                query=make_query(),
                status=ResolutionStatus.RESOLVED,
                records=(record,),
            )

    def test_mismatched_currency_is_rejected(self):
        dimension = make_dimension(currency="EUR")

        record = make_record(
            dimensions=(dimension,)
        )

        with self.assertRaises(ValueError):
            PricingResolution(
                query=make_query(),
                status=ResolutionStatus.RESOLVED,
                records=(record,),
            )

    def test_reference_resolution_preserves_primary_diagnostics(self):
        reference = make_record(
            source=PricingSource.REFERENCE_DATA,
            verified_at=UTC_TIME,
            source_reference="TEST-REFERENCE",
        )

        result = PricingResolution(
            query=make_query(),
            status=ResolutionStatus.RESOLVED,
            records=(reference,),
            diagnostics=(
                "Floci: no matching products",
                "Reference: matching rate",
            ),
        )

        self.assertEqual(
            result.records[0].source,
            PricingSource.REFERENCE_DATA,
        )

        self.assertEqual(len(result.diagnostics), 2)


class SpotObservationTests(unittest.TestCase):

    def test_valid_spot_observation(self):
        observation = make_spot()

        self.assertEqual(
            observation.unit_price,
            Decimal("0.004400"),
        )

        self.assertEqual(
            observation.availability_zone,
            "us-east-1a",
        )

        self.assertEqual(
            observation.source,
            PricingSource.FLOCI_EC2_API,
        )

    def test_spot_price_precision_is_preserved(self):
        observation = make_spot()

        self.assertEqual(
            observation.unit_price.as_tuple(),
            Decimal("0.004400").as_tuple(),
        )

    def test_negative_spot_price_is_rejected(self):
        with self.assertRaises(ValueError):
            make_spot(
                unit_price=Decimal("-0.01")
            )

    def test_missing_spot_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            make_spot(observed_at=None)

    def test_naive_spot_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            make_spot(
                observed_at=datetime(2026, 11, 26)
            )

    def test_spot_source_must_be_ec2_api(self):
        with self.assertRaises(ValueError):
            make_spot(
                source=PricingSource.REFERENCE_DATA
            )

    def test_spot_observation_is_immutable(self):
        observation = make_spot()

        with self.assertRaises(FrozenInstanceError):
            observation.unit_price = Decimal("1")


if __name__ == "__main__":
    unittest.main()
