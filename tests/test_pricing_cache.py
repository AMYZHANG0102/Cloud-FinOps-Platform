"""Isolated verification of persistent pricing catalogue storage."""

import json
import tempfile
import unittest

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from finops.config import RuntimeSettings

from finops.pricing.cache import (
    PricingCacheError,
    PricingCatalogueCache,
)

from finops.pricing.client import (
    FlociClientSettings,
)

from finops.pricing.products import (
    PricingProductError,
    ProductFilter,
    ProductRetrievalResult,
    RawPricingProduct,
)


UTC_TIME = datetime(
    2026, 11, 27, 19, 44,
    tzinfo=timezone.utc,
)


def make_product(
    sku="TEST-SKU",
    instance_type="t3.micro",
    region="us-east-1",
    price="0.0104000000",
):
    """Synthetic fixture, not an independently retrieved AWS rate."""

    return RawPricingProduct.from_json(
        json.dumps({
            "serviceCode": "AmazonEC2",
            "version": "TEST-VERSION",
            "product": {
                "sku": sku,
                "productFamily": "Compute Instance",
                "attributes": {
                    "regionCode": region,
                    "instanceType": instance_type,
                    "servicecode": "AmazonEC2",
                },
            },
            "terms": {
                "OnDemand": {
                    "TEST-OFFER": {
                        "sku": sku,
                        "offerTermCode": "TEST-TERM",
                        "priceDimensions": {
                            "TEST-RATE": {
                                "rateCode": "TEST-RATE",
                                "unit": "Hrs",
                                "beginRange": "0",
                                "endRange": "Inf",
                                "pricePerUnit": {
                                    "USD": price,
                                },
                            },
                        },
                    },
                },
            },
        })
    )


def retrieval(
    *products,
    service="AmazonEC2",
    filters=(),
    retrieved_at=UTC_TIME,
):
    return ProductRetrievalResult(
        service_code=service,
        filters=filters,
        products=tuple(products),
        retrieved_at=retrieved_at,
        page_count=1,
        received_count=len(products),
        duplicate_count=0,
    )


class PricingCacheTests(unittest.TestCase):

    def setUp(self):

        self.temporary = tempfile.TemporaryDirectory()

        self.addCleanup(
            self.temporary.cleanup
        )

        self.settings = RuntimeSettings(
            runtime_root=Path(
                self.temporary.name
            ) / "runtime"
        )

        self.cache = PricingCatalogueCache(
            self.settings
        )

        self.product = make_product()

    def test_missing_cache_returns_none_without_creating_files(self):

        self.assertIsNone(
            self.cache.load("AmazonEC2")
        )

        self.assertFalse(
            self.settings.runtime_root.exists()
        )

    def test_store_and_load_preserves_price_and_source(self):

        original = retrieval(self.product)

        stored = self.cache.store(original)

        loaded = self.cache.load(
            "AmazonEC2",
            now=UTC_TIME,
        )

        self.assertEqual(
            loaded.catalogue,
            stored,
        )

        self.assertEqual(
            loaded.catalogue.records[0].dimensions[0]
            .unit_price.as_tuple(),
            Decimal("0.0104000000").as_tuple(),
        )

        self.assertEqual(
            loaded.catalogue.retrieved_at,
            UTC_TIME,
        )

        self.assertEqual(
            loaded.catalogue.retrieval.products[0].raw_json,
            self.product.raw_json,
        )

    def test_new_repository_instance_can_reload_saved_data(self):

        self.cache.store(
            retrieval(self.product)
        )

        reopened = PricingCatalogueCache(
            self.settings
        )

        result = reopened.load(
            "AmazonEC2",
            now=UTC_TIME,
        )

        self.assertEqual(
            result.catalogue.record_count,
            1,
        )

    def test_unrelated_services_remain_separate(self):

        self.cache.store(
            retrieval(self.product)
        )

        self.cache.store(
            retrieval(service="AmazonS3")
        )

        self.assertEqual(
            self.cache.load("AmazonEC2")
            .catalogue.record_count,
            1,
        )

        self.assertTrue(
            self.cache.load("AmazonS3")
            .catalogue.is_empty
        )

    def test_filters_and_regions_have_separate_entries(self):

        first_filters = (
            ProductFilter(
                "regionCode",
                "us-east-1",
            ),
        )

        second_filters = (
            ProductFilter(
                "regionCode",
                "us-west-2",
            ),
        )

        self.cache.store(
            retrieval(
                self.product,
                filters=first_filters,
            )
        )

        self.cache.store(
            retrieval(
                filters=second_filters,
            )
        )

        self.assertEqual(
            self.cache.load(
                "AmazonEC2",
                first_filters,
            ).catalogue.record_count,
            1,
        )

        self.assertTrue(
            self.cache.load(
                "AmazonEC2",
                second_filters,
            ).catalogue.is_empty
        )

        self.assertIsNone(
            self.cache.load("AmazonEC2")
        )

    def test_equivalent_filter_order_uses_same_entry(self):

        first = ProductFilter(
            "regionCode",
            "us-east-1",
        )

        second = ProductFilter(
            "instanceType",
            "t3.micro",
        )

        self.cache.store(
            retrieval(
                self.product,
                filters=(first, second),
            )
        )

        result = self.cache.load(
            "AmazonEC2",
            (second, first),
        )

        self.assertEqual(
            result.catalogue.record_count,
            1,
        )

    def test_endpoint_identity_is_part_of_cache_key(self):

        self.cache.store(
            retrieval(self.product)
        )

        different_endpoint = PricingCatalogueCache(
            self.settings,
            FlociClientSettings(
                endpoint_url="http://127.0.0.1:55466"
            ),
        )

        self.assertIsNone(
            different_endpoint.load("AmazonEC2")
        )

    def test_cache_is_fresh_before_expiration(self):

        self.cache.store(
            retrieval(self.product)
        )

        result = self.cache.load(
            "AmazonEC2",
            now=UTC_TIME + timedelta(seconds=899),
        )

        self.assertTrue(result.is_fresh)
        self.assertFalse(result.is_stale)

    def test_cache_is_stale_at_expiration(self):

        self.cache.store(
            retrieval(self.product)
        )

        result = self.cache.load(
            "AmazonEC2",
            now=UTC_TIME + timedelta(seconds=900),
        )

        self.assertFalse(result.is_fresh)
        self.assertTrue(result.is_stale)

        self.assertEqual(
            result.catalogue.retrieved_at,
            UTC_TIME,
        )

    def test_future_timestamp_is_not_considered_fresh(self):

        self.cache.store(
            retrieval(self.product)
        )

        result = self.cache.load(
            "AmazonEC2",
            now=UTC_TIME - timedelta(seconds=1),
        )

        self.assertTrue(result.is_stale)

    def test_custom_freshness_interval(self):

        cache = PricingCatalogueCache(
            RuntimeSettings(
                runtime_root=self.settings.runtime_root,
                catalogue_ttl_seconds=60,
            )
        )

        cache.store(
            retrieval(self.product)
        )

        result = cache.load(
            "AmazonEC2",
            now=UTC_TIME + timedelta(seconds=60),
        )

        self.assertTrue(result.is_stale)

    def test_successful_refresh_replaces_previous_entry(self):

        self.cache.store(
            retrieval(self.product)
        )

        updated = make_product(price="0.0200")

        self.cache.store(
            retrieval(
                updated,
                retrieved_at=(
                    UTC_TIME + timedelta(minutes=1)
                ),
            )
        )

        result = self.cache.load("AmazonEC2")

        self.assertEqual(
            result.catalogue.records[0].dimensions[0]
            .unit_price,
            Decimal("0.0200"),
        )

    def test_successful_empty_result_can_replace_previous_entry(self):

        self.cache.store(
            retrieval(self.product)
        )

        self.cache.store(
            retrieval(
                retrieved_at=(
                    UTC_TIME + timedelta(minutes=1)
                ),
            )
        )

        result = self.cache.load("AmazonEC2")

        self.assertIsNotNone(result)
        self.assertTrue(result.catalogue.is_empty)

    def test_older_retrieval_cannot_replace_newer_entry(self):

        self.cache.store(
            retrieval(self.product)
        )

        original = self.cache.path.read_bytes()

        with self.assertRaises(PricingCacheError):

            self.cache.store(
                retrieval(
                    retrieved_at=(
                        UTC_TIME - timedelta(minutes=1)
                    )
                )
            )

        self.assertEqual(
            self.cache.path.read_bytes(),
            original,
        )

    def test_corrupt_json_is_not_silently_replaced(self):

        self.cache.path.parent.mkdir(
            parents=True
        )

        self.cache.path.write_text(
            "{invalid",
            encoding="utf-8",
        )

        before = self.cache.path.read_bytes()

        with self.assertRaises(PricingCacheError):
            self.cache.load("AmazonEC2")

        with self.assertRaises(PricingCacheError):

            self.cache.store(
                retrieval(self.product)
            )

        self.assertEqual(
            self.cache.path.read_bytes(),
            before,
        )

    def test_unsupported_schema_version_is_rejected(self):

        self.cache.store(
            retrieval(self.product)
        )

        document = json.loads(
            self.cache.path.read_text(
                encoding="utf-8"
            )
        )

        document["schema_version"] = 999

        self.cache.path.write_text(
            json.dumps(document),
            encoding="utf-8",
        )

        with self.assertRaises(PricingCacheError):
            self.cache.load("AmazonEC2")

    def test_persisted_query_mismatch_is_rejected(self):

        self.cache.store(
            retrieval(self.product)
        )

        document = json.loads(
            self.cache.path.read_text(
                encoding="utf-8"
            )
        )

        entry = next(
            iter(document["entries"].values())
        )

        entry["query"]["service_code"] = "AmazonS3"

        self.cache.path.write_text(
            json.dumps(document),
            encoding="utf-8",
        )

        with self.assertRaises(PricingCacheError):
            self.cache.load("AmazonEC2")

    def test_invalid_product_does_not_replace_valid_cache(self):

        self.cache.store(
            retrieval(self.product)
        )

        before = self.cache.path.read_bytes()

        invalid = make_product(
            price="invalid"
        )

        with self.assertRaises(PricingCacheError):

            self.cache.store(
                retrieval(
                    invalid,
                    retrieved_at=(
                        UTC_TIME + timedelta(minutes=1)
                    ),
                )
            )

        self.assertEqual(
            self.cache.path.read_bytes(),
            before,
        )

    def test_filter_mismatch_is_rejected(self):

        with self.assertRaises(PricingCacheError):

            self.cache.store(
                retrieval(
                    self.product,
                    filters=(
                        ProductFilter(
                            "regionCode",
                            "us-west-2",
                        ),
                    ),
                )
            )

        self.assertFalse(
            self.cache.path.exists()
        )

    @patch("finops.pricing.cache.os.replace")
    def test_failed_file_replacement_preserves_previous_cache(
        self,
        replace,
    ):

        # Temporarily restore actual replacement for initial save.

        replace.stop = None

        from os import replace as patched_replace

        # The initial file is established separately below.

        document = {
            "schema_version": 1,
            "normalization_version": 1,
            "entries": {},
        }

        self.cache.path.parent.mkdir(
            parents=True
        )

        self.cache.path.write_text(
            json.dumps(document),
            encoding="utf-8",
        )

        before = self.cache.path.read_bytes()

        replace.side_effect = OSError(
            "Synthetic replacement failure"
        )

        with self.assertRaises(PricingCacheError):

            self.cache.store(
                retrieval(self.product)
            )

        self.assertEqual(
            self.cache.path.read_bytes(),
            before,
        )

        self.assertEqual(
            list(
                self.cache.path.parent.glob(
                    ".catalogue-*.tmp"
                )
            ),
            [],
        )

    @patch("finops.pricing.cache.create_pricing_client")
    def test_failed_live_refresh_preserves_valid_cache(
        self,
        factory,
    ):

        self.cache.store(
            retrieval(self.product)
        )

        before = self.cache.path.read_bytes()

        client = factory.return_value

        client.get_products.side_effect = (
            PricingProductError(
                "TEST_FAILURE",
                "Synthetic retrieval failure",
            )
        )

        with self.assertRaises(PricingProductError):
            self.cache.refresh("AmazonEC2")

        client.close.assert_called_once()

        self.assertEqual(
            self.cache.path.read_bytes(),
            before,
        )

    @patch("finops.pricing.cache.create_pricing_client")
    def test_live_refresh_persists_successful_result(
        self,
        factory,
    ):

        client = factory.return_value

        client.get_products.return_value = {
            "PriceList": [
                self.product.raw_json,
            ],
            "FormatVersion": "aws_v1",
            "ResponseMetadata": {
                "HTTPStatusCode": 200,
            },
        }

        catalogue = self.cache.refresh(
            "AmazonEC2"
        )

        client.close.assert_called_once()

        self.assertEqual(
            catalogue.record_count,
            1,
        )

        self.assertEqual(
            self.cache.load("AmazonEC2").catalogue,
            catalogue,
        )


if __name__ == "__main__":
    unittest.main()
