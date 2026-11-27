"""Streamlit application tests with isolated pricing storage."""

import json
import tempfile
import unittest

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from botocore.exceptions import EndpointConnectionError

from streamlit.testing.v1 import AppTest

from finops.config import RuntimeSettings
from finops.pricing.cache import PricingCatalogueCache

from finops.pricing.products import (
    ProductRetrievalResult,
    RawPricingProduct,
)


PAGE = (
    Path(__file__).resolve().parents[1]
    / "pages"
    / "01_Pricing_Explorer.py"
)

LOCATION = "US East (N. Virginia)"


def api_response(key, values):

    return {
        key: values,
        "ResponseMetadata": {
            "HTTPStatusCode": 200,
        },
    }


def product_document():

    return {
        "serviceCode": "AmazonEC2",
        "version": "TEST-VERSION",
        "product": {
            "sku": "TEST-SKU",
            "productFamily": "Compute Instance",
            "attributes": {
                "servicecode": "AmazonEC2",
                "regionCode": "us-east-1",
                "location": LOCATION,
                "instanceType": "t3.micro",
                "operatingSystem": "Linux",
            },
        },
        "terms": {
            "OnDemand": {
                "TEST-OFFER": {
                    "sku": "TEST-SKU",
                    "offerTermCode": "TEST-TERM",
                    "priceDimensions": {
                        "TEST-RATE": {
                            "rateCode": "TEST-RATE",
                            "unit": "Hrs",
                            "beginRange": "0",
                            "endRange": "Inf",
                            "pricePerUnit": {
                                "USD": "0.0104000000",
                            },
                        },
                    },
                },
            },
        },
    }


class PricingExplorerTests(unittest.TestCase):

    def setUp(self):

        directory = tempfile.TemporaryDirectory()

        self.addCleanup(directory.cleanup)

        self.cache = PricingCatalogueCache(
            RuntimeSettings(
                runtime_root=Path(directory.name)
            )
        )

        self.client = Mock()

        self.client.describe_services.return_value = (
            api_response(
                "Services",
                [
                    {
                        "ServiceCode": "AmazonEC2",
                        "AttributeNames": [
                            "location",
                            "instanceType",
                            "operatingSystem",
                        ],
                    },
                    {
                        "ServiceCode": "AmazonS3",
                        "AttributeNames": [
                            "location",
                        ],
                    },
                ],
            )
        )

        def attributes(**request):

            values = {
                "location": [
                    LOCATION,
                    "US West (Oregon)",
                ],
                "instanceType": [
                    "t3.micro",
                    "t3.small",
                ],
                "operatingSystem": [
                    "Linux",
                    "Windows",
                ],
            }

            return api_response(
                "AttributeValues",
                [
                    {"Value": value}
                    for value in values.get(
                        request["AttributeName"], []
                    )
                ],
            )

        self.client.get_attribute_values.side_effect = (
            attributes
        )

        def products(**request):

            document = product_document()

            matches = (
                request["ServiceCode"] == "AmazonEC2"
                and all(
                    document["product"]["attributes"].get(
                        item["Field"]
                    ) == item["Value"]
                    for item in request.get("Filters", [])
                )
            )

            return api_response(
                "PriceList",
                [json.dumps(document)] if matches else [],
            )

        self.client.get_products.side_effect = products

        patches = (
            patch(
                "finops.pricing.client.create_pricing_client",
                return_value=self.client,
            ),
            patch(
                "finops.pricing.cache.create_pricing_client",
                return_value=self.client,
            ),
            patch(
                "finops.pricing.cache.PricingCatalogueCache",
                return_value=self.cache,
            ),
        )

        for item in patches:

            item.start()
            self.addCleanup(item.stop)

    def open_page(self):

        app = AppTest.from_file(
            str(PAGE),
            default_timeout=30,
        ).run()

        self.assertFalse(app.exception)

        return app

    def retrieve(self, app):

        app.button(
            key="m1.retrieve"
        ).click().run()

        self.assertFalse(app.exception)

    def test_initial_page_and_dynamic_service_selection(self):

        app = self.open_page()

        self.assertEqual(
            app.title[0].value,
            "Cloud Service Pricing Explorer",
        )

        selector = app.selectbox(
            key="m1.service"
        )

        self.assertEqual(
            selector.value,
            "AmazonEC2",
        )

        self.assertIn(
            "Amazon S3",
            selector.options,
        )

        self.client.get_products.assert_not_called()

    def test_retrieve_displays_and_persists_price(self):

        app = self.open_page()

        self.retrieve(app)

        self.assertTrue(app.success)
        self.assertEqual(len(app.dataframe), 1)

        table = app.dataframe[0].value

        self.assertEqual(
            table["Unit price"].tolist(),
            ["0.0104000000"],
        )

        self.assertTrue(self.cache.path.exists())

        self.assertEqual(
            self.cache.load("AmazonEC2")
            .catalogue.record_count,
            1,
        )

    def test_region_selection_is_forwarded(self):

        app = self.open_page()

        app.selectbox(
            key="m1.region.AmazonEC2"
        ).select(LOCATION).run()

        self.retrieve(app)

        request = (
            self.client.get_products.call_args.kwargs
        )

        self.assertIn(
            {
                "Type": "TERM_MATCH",
                "Field": "location",
                "Value": LOCATION,
            },
            request["Filters"],
        )

        self.assertEqual(len(app.dataframe), 1)

    def test_advertised_unpriced_configuration(self):

        app = self.open_page()

        app.selectbox(
            key="m1.filter.AmazonEC2.instanceType"
        ).select("t3.small").run()

        self.retrieve(app)

        self.assertEqual(len(app.dataframe), 0)

        self.assertTrue(
            any(
                "No pricing records" in warning.value
                for warning in app.warning
            )
        )

    def test_changing_service_does_not_display_previous_results(self):

        app = self.open_page()

        self.retrieve(app)

        app.selectbox(
            key="m1.service"
        ).select("AmazonS3").run()

        self.assertFalse(app.exception)

        self.assertEqual(len(app.dataframe), 0)

        self.assertTrue(
            any(
                "No pricing has been saved" in item.value
                for item in app.info
            )
        )

    def test_reopened_page_uses_fresh_saved_catalogue(self):

        first = self.open_page()

        self.retrieve(first)

        calls = self.client.get_products.call_count

        second = self.open_page()

        self.assertEqual(len(second.dataframe), 1)

        self.assertEqual(
            self.client.get_products.call_count,
            calls,
        )

    def test_stale_data_requires_explicit_selection(self):

        raw = RawPricingProduct.from_json(
            json.dumps(product_document())
        )

        old = ProductRetrievalResult(
            service_code="AmazonEC2",
            filters=(),
            products=(raw,),
            retrieved_at=(
                datetime.now(timezone.utc)
                - timedelta(hours=1)
            ),
            page_count=1,
            received_count=1,
            duplicate_count=0,
        )

        self.cache.store(old)

        app = self.open_page()

        self.assertEqual(len(app.dataframe), 0)

        self.assertTrue(
            any(
                "stale" in item.value.lower()
                for item in app.warning
            )
        )

        app.checkbox(
            key="m1.show_historical"
        ).check().run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 1)

        self.client.get_products.assert_not_called()

    def test_failed_refresh_does_not_substitute_cache(self):

        app = self.open_page()

        self.retrieve(app)

        before = self.cache.path.read_bytes()

        self.client.get_products.side_effect = (
            EndpointConnectionError(
                endpoint_url="http://127.0.0.1:4566"
            )
        )

        self.retrieve(app)

        self.assertEqual(len(app.dataframe), 0)

        self.assertTrue(
            any(
                "Live pricing retrieval failed" in item.value
                for item in app.error
            )
        )

        self.assertEqual(
            self.cache.path.read_bytes(),
            before,
        )

    def test_discovery_failure_is_explicit(self):

        self.client.describe_services.side_effect = (
            EndpointConnectionError(
                endpoint_url="http://127.0.0.1:4566"
            )
        )

        app = self.open_page()

        self.assertTrue(
            any(
                "Unable to discover pricing services" in item.value
                for item in app.error
            )
        )

        self.assertEqual(len(app.dataframe), 0)


if __name__ == "__main__":
    unittest.main()
