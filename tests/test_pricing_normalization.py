"""Verification of source-to-domain pricing normalization."""

import copy
import json
import unittest

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal

from finops.pricing.models import (
    PricingModel,
    PricingSource,
)

from finops.pricing.products import (
    ProductRetrievalResult,
    RawPricingProduct,
)

from finops.pricing.normalization import (
    PricingNormalizationError,
    normalize_product,
    normalize_catalogue,
)


UTC_TIME = datetime(
    2026, 11, 27, 19, 41,
    tzinfo=timezone.utc,
)


def make_document(
    service="AmazonEC2",
    family="Compute Instance",
    unit="Hrs",
    price="0.0104000000",
    end_range="Inf",
    attributes=None,
):
    """Synthetic fixture using the observed source structure."""

    metadata = {
        "regionCode": "us-east-1",
        "servicecode": service,
    }

    if attributes is not None:
        metadata.update(attributes)

    return {
        "serviceCode": service,
        "version": "TEST-VERSION",
        "publicationDate": "2026-01-01T00:00:00Z",
        "product": {
            "sku": "TEST-SKU",
            "productFamily": family,
            "attributes": metadata,
        },
        "terms": {
            "OnDemand": {
                "TEST-OFFER": {
                    "sku": "TEST-SKU",
                    "offerTermCode": "TEST-TERM",
                    "effectiveDate": "2026-01-01T00:00:00Z",
                    "termAttributes": {},
                    "priceDimensions": {
                        "TEST-RATE": {
                            "rateCode": "TEST-RATE",
                            "unit": unit,
                            "beginRange": "0",
                            "endRange": end_range,
                            "description": "Synthetic test rate",
                            "appliesTo": [],
                            "pricePerUnit": {
                                "USD": price,
                            },
                        },
                    },
                },
            },
        },
    }


def offer(document):
    return document["terms"]["OnDemand"]["TEST-OFFER"]


def dimension(document):
    return offer(document)["priceDimensions"]["TEST-RATE"]


def raw(document):
    return RawPricingProduct.from_json(
        json.dumps(document)
    )


def normalize(document):
    return normalize_product(raw(document), UTC_TIME)


def retrieval(*products, service="AmazonEC2"):
    return ProductRetrievalResult(
        service_code=service,
        filters=(),
        products=tuple(products),
        retrieved_at=UTC_TIME,
        page_count=1,
        received_count=len(products),
        duplicate_count=0,
    )


class NormalizationTests(unittest.TestCase):

    def test_ec2_record_preserves_provenance(self):

        document = make_document(
            attributes={
                "instanceType": "t3.micro",
                "operatingSystem": "Linux",
                "tenancy": "Shared",
            },
        )

        record, = normalize(document)

        self.assertEqual(record.service_code, "AmazonEC2")
        self.assertEqual(record.region, "us-east-1")
        self.assertEqual(record.sku, "TEST-SKU")
        self.assertEqual(record.offer_term_code, "TEST-TERM")
        self.assertEqual(record.catalogue_version, "TEST-VERSION")

        self.assertEqual(
            record.attributes["instanceType"],
            "t3.micro",
        )

        self.assertEqual(
            record.pricing_model,
            PricingModel.ON_DEMAND,
        )

        self.assertEqual(
            record.source,
            PricingSource.FLOCI_PRICING_API,
        )

        self.assertIn(
            "TEST-OFFER",
            record.source_reference,
        )

        self.assertEqual(record.retrieved_at, UTC_TIME)

        self.assertEqual(
            record.dimensions[0].cost_component,
            "compute",
        )

    def test_decimal_precision_is_preserved(self):

        record, = normalize(make_document())

        price = record.dimensions[0].unit_price

        self.assertIsInstance(price, Decimal)

        self.assertEqual(
            price.as_tuple(),
            Decimal("0.0104000000").as_tuple(),
        )

    def test_unbounded_usage_range(self):

        record, = normalize(make_document())

        self.assertIsNone(
            record.dimensions[0].end_range
        )

        self.assertTrue(
            record.dimensions[0].is_unbounded
        )

    def test_s3_finite_storage_tier(self):

        document = make_document(
            service="AmazonS3",
            family="Storage",
            unit="GB-Mo",
            price="0.0230000000",
            end_range="51200",
            attributes={"volumeType": "Standard"},
        )

        record, = normalize(document)
        rate, = record.dimensions

        self.assertEqual(
            rate.unit_price,
            Decimal("0.023"),
        )

        self.assertEqual(
            rate.end_range,
            Decimal("51200"),
        )

        self.assertEqual(
            rate.cost_component,
            "storage",
        )

    def test_lambda_request_rate(self):

        document = make_document(
            service="AWSLambda",
            family="Serverless",
            unit="Requests",
            price="0.0000002000",
            attributes={
                "group": "AWS-Lambda-Requests",
            },
        )

        record, = normalize(document)
        rate, = record.dimensions

        self.assertEqual(
            rate.cost_component,
            "requests",
        )

        self.assertEqual(
            rate.unit_price * Decimal("1000000"),
            Decimal("0.20"),
        )

    def test_zero_price_is_valid(self):

        record, = normalize(
            make_document(price="0")
        )

        self.assertEqual(
            record.dimensions[0].unit_price,
            Decimal("0"),
        )

    def test_invalid_prices_are_rejected(self):

        for price in (
            "-1", "NaN", "Infinity",
            "1_000", "", None, 0.01,
        ):
            with self.subTest(price=price):

                with self.assertRaises(
                    PricingNormalizationError
                ):
                    normalize(
                        make_document(price=price)
                    )

    def test_invalid_usage_ranges_are_rejected(self):

        for end_range in ("0", "-1", "unknown", None):

            with self.subTest(end_range=end_range):

                with self.assertRaises(
                    PricingNormalizationError
                ):
                    normalize(
                        make_document(
                            end_range=end_range
                        )
                    )

    def test_invalid_lower_boundary_is_rejected(self):

        document = make_document()

        dimension(document)["beginRange"] = "Inf"

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize(document)

    def test_multiple_currencies_are_preserved(self):

        document = make_document()

        dimension(document)["pricePerUnit"]["EUR"] = "0.009"

        record, = normalize(document)

        self.assertEqual(
            {
                rate.currency: rate.unit_price
                for rate in record.dimensions
            },
            {
                "USD": Decimal("0.0104"),
                "EUR": Decimal("0.009"),
            },
        )

    def test_empty_currency_collection_is_rejected(self):

        document = make_document()

        dimension(document)["pricePerUnit"] = {}

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize(document)

    def test_invalid_currency_is_rejected(self):

        document = make_document()

        dimension(document)["pricePerUnit"] = {
            "usd": "0.01"
        }

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize(document)

    def test_multiple_pricing_tiers_are_preserved(self):

        document = make_document(
            service="AmazonS3",
            family="Storage",
            unit="GB-Mo",
            price="0.023",
            end_range="51200",
        )

        second = copy.deepcopy(
            dimension(document)
        )

        second.update({
            "rateCode": "TEST-RATE-2",
            "beginRange": "51200",
            "endRange": "Inf",
            "pricePerUnit": {"USD": "0.022"},
        })

        offer(document)["priceDimensions"][
            "TEST-RATE-2"
        ] = second

        record, = normalize(document)

        self.assertEqual(
            len(record.dimensions),
            2,
        )

        self.assertEqual(
            record.dimensions[1].begin_range,
            Decimal("51200"),
        )

    def test_multiple_pricing_models_are_preserved(self):

        document = make_document()

        reserved = copy.deepcopy(
            offer(document)
        )

        reserved["offerTermCode"] = "RESERVED-TERM"

        reserved["termAttributes"] = {
            "LeaseContractLength": "1yr",
            "PurchaseOption": "No Upfront",
        }

        document["terms"]["Reserved"] = {
            "RESERVED-OFFER": reserved
        }

        records = normalize(document)

        self.assertEqual(len(records), 2)

        self.assertEqual(
            {
                item.pricing_model
                for item in records
            },
            {
                PricingModel.ON_DEMAND,
                PricingModel.RESERVED,
            },
        )

        self.assertEqual(
            records[1].term_attributes[
                "LeaseContractLength"
            ],
            "1yr",
        )

    def test_unknown_pricing_model_is_rejected(self):

        document = make_document()

        document["terms"]["UnknownTerm"] = {}

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize(document)

    def test_mismatched_offer_sku_is_rejected(self):

        document = make_document()

        offer(document)["sku"] = "WRONG-SKU"

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize(document)

    def test_missing_price_dimensions_are_rejected(self):

        document = make_document()

        del offer(document)["priceDimensions"]

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize(document)

    def test_missing_region_is_rejected(self):

        document = make_document()

        del document["product"]["attributes"]["regionCode"]

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize(document)

    def test_missing_dates_remain_unknown(self):

        document = make_document()

        del document["publicationDate"]
        del offer(document)["effectiveDate"]

        record, = normalize(document)

        self.assertIsNone(record.publication_date)
        self.assertIsNone(record.effective_date)

    def test_naive_source_timestamp_is_rejected(self):

        document = make_document()

        offer(document)["effectiveDate"] = (
            "2026-01-01T00:00:00"
        )

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize(document)

    def test_source_timestamp_is_normalized_to_utc(self):

        document = make_document()

        offer(document)["effectiveDate"] = (
            "2026-01-01T05:00:00+05:00"
        )

        record, = normalize(document)

        self.assertEqual(
            record.effective_date,
            datetime(
                2026, 1, 1,
                tzinfo=timezone.utc,
            ),
        )

    def test_unclassified_dimension_remains_explicit(self):

        document = make_document(
            unit="UnknownUnit",
        )

        catalogue = normalize_catalogue(
            retrieval(raw(document))
        )

        self.assertEqual(catalogue.record_count, 1)

        self.assertIsNone(
            catalogue.records[0].dimensions[
                0
            ].cost_component
        )

        self.assertTrue(catalogue.warnings)

    def test_empty_catalogue_is_valid(self):

        catalogue = normalize_catalogue(
            retrieval()
        )

        self.assertTrue(catalogue.is_empty)
        self.assertEqual(catalogue.record_count, 0)
        self.assertEqual(catalogue.dimension_count, 0)

    def test_unpriced_product_remains_visible(self):

        document = make_document()

        document["terms"] = {}

        catalogue = normalize_catalogue(
            retrieval(raw(document))
        )

        self.assertTrue(catalogue.is_empty)

        self.assertEqual(
            catalogue.unpriced_skus,
            ("TEST-SKU",),
        )

        self.assertTrue(catalogue.warnings)

    def test_catalogue_preserves_raw_retrieval(self):

        original = retrieval(
            raw(make_document())
        )

        catalogue = normalize_catalogue(original)

        self.assertIs(catalogue.retrieval, original)
        self.assertEqual(catalogue.record_count, 1)
        self.assertEqual(catalogue.dimension_count, 1)
        self.assertEqual(catalogue.service_code, "AmazonEC2")
        self.assertEqual(catalogue.retrieved_at, UTC_TIME)

        with self.assertRaises(FrozenInstanceError):
            catalogue.records = ()

    def test_catalogue_rejects_mismatched_service(self):

        document = make_document(
            service="AmazonS3",
        )

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize_catalogue(
                retrieval(raw(document))
            )

    def test_catalogue_rejects_duplicate_sku(self):

        product = raw(make_document())

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize_catalogue(
                retrieval(product, product)
            )

    def test_invalid_product_does_not_return_partial_catalogue(self):

        first = raw(make_document())

        second_document = make_document(
            price="invalid",
        )

        second_document["product"]["sku"] = "SECOND-SKU"

        offer(second_document)["sku"] = "SECOND-SKU"

        second = raw(second_document)

        with self.assertRaises(
            PricingNormalizationError
        ):
            normalize_catalogue(
                retrieval(first, second)
            )


if __name__ == "__main__":
    unittest.main()
