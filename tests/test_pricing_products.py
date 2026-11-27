"""Isolated tests for raw pricing product retrieval."""

import json
import unittest

from dataclasses import FrozenInstanceError
from datetime import timezone
from decimal import Decimal
from unittest.mock import Mock

from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
)

from finops.pricing.client import UnsafeEndpointError

from finops.pricing.products import (
    ProductFilter,
    PricingProductError,
    PricingProducts,
    RawPricingProduct,
)


def make_product(
    sku="TEST-T3-MICRO",
    service="AmazonEC2",
    instance_type="t3.micro",
    region="us-east-1",
    price="0.0104000000",
):
    """Synthetic product fixture, not a retrieved AWS offer."""

    return json.dumps({
        "serviceCode": service,
        "version": "TEST-VERSION",
        "publicationDate": "2026-01-01T00:00:00Z",
        "product": {
            "sku": sku,
            "productFamily": "Compute Instance",
            "attributes": {
                "servicecode": service,
                "instanceType": instance_type,
                "regionCode": region,
                "operatingSystem": "Linux",
                "tenancy": "Shared",
            },
        },
        "terms": {
            "OnDemand": {
                "TEST-OFFER": {
                    "sku": sku,
                    "offerTermCode": "TEST-TERM",
                    "effectiveDate": "2026-01-01T00:00:00Z",
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
                    "termAttributes": {},
                },
            },
        },
    })


def page(products, token=None):

    result = {
        "FormatVersion": "aws_v1",
        "PriceList": products,
        "ResponseMetadata": {
            "HTTPStatusCode": 200,
        },
    }

    if token is not None:
        result["NextToken"] = token

    return result


class ProductRetrievalTests(unittest.TestCase):

    def setUp(self):

        self.client = Mock()

        self.products = PricingProducts(
            self.client,
            page_size=2,
            max_pages=5,
        )

    def assert_error(self, code, operation):

        with self.assertRaises(PricingProductError) as context:
            operation()

        self.assertEqual(
            context.exception.code,
            code,
        )

        return context.exception

    def test_unfiltered_product_retrieval(self):

        self.client.get_products.return_value = page([
            make_product(),
        ])

        result = self.products.get_products("AmazonEC2")

        self.assertEqual(result.product_count, 1)
        self.assertEqual(result.page_count, 1)
        self.assertEqual(result.received_count, 1)
        self.assertEqual(result.duplicate_count, 0)
        self.assertFalse(result.is_empty)

        self.client.get_products.assert_called_once_with(
            ServiceCode="AmazonEC2",
            FormatVersion="aws_v1",
            MaxResults=2,
        )

    def test_exact_filters_are_forwarded(self):

        self.client.get_products.return_value = page([
            make_product(),
        ])

        filters = (
            ProductFilter("regionCode", "us-east-1"),
            ProductFilter("instanceType", "t3.micro"),
        )

        result = self.products.get_products(
            "AmazonEC2",
            filters,
        )

        self.assertEqual(result.product_count, 1)

        self.assertEqual(
            self.client.get_products.call_args.kwargs["Filters"],
            [
                {
                    "Type": "TERM_MATCH",
                    "Field": "instanceType",
                    "Value": "t3.micro",
                },
                {
                    "Type": "TERM_MATCH",
                    "Field": "regionCode",
                    "Value": "us-east-1",
                },
            ],
        )

    def test_product_family_filter(self):

        self.client.get_products.return_value = page([
            make_product(),
        ])

        result = self.products.get_products(
            "AmazonEC2",
            (
                ProductFilter(
                    "productFamily",
                    "Compute Instance",
                ),
            ),
        )

        self.assertEqual(result.product_count, 1)

    def test_multiple_pages_are_collected(self):

        self.client.get_products.side_effect = [
            page(
                [make_product(sku="SKU-B")],
                "next",
            ),
            page(
                [make_product(sku="SKU-A")],
            ),
        ]

        filters = (
            ProductFilter("regionCode", "us-east-1"),
        )

        result = self.products.get_products(
            "AmazonEC2",
            filters,
        )

        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.product_count, 2)

        self.assertEqual(
            tuple(item.sku for item in result.products),
            ("SKU-A", "SKU-B"),
        )

        first, second = self.client.get_products.call_args_list

        self.assertNotIn("NextToken", first.kwargs)

        self.assertEqual(
            second.kwargs["NextToken"],
            "next",
        )

        self.assertEqual(
            first.kwargs["Filters"],
            second.kwargs["Filters"],
        )

    def test_empty_intermediate_page_is_followed(self):

        self.client.get_products.side_effect = [
            page([], "next"),
            page([make_product()]),
        ]

        result = self.products.get_products("AmazonEC2")

        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.product_count, 1)

    def test_identical_duplicates_are_removed(self):

        product = make_product()

        reordered = json.dumps(
            json.loads(product),
            sort_keys=True,
        )

        self.client.get_products.side_effect = [
            page([product], "next"),
            page([reordered]),
        ]

        result = self.products.get_products("AmazonEC2")

        self.assertEqual(result.received_count, 2)
        self.assertEqual(result.duplicate_count, 1)
        self.assertEqual(result.product_count, 1)

    def test_conflicting_products_are_rejected(self):

        self.client.get_products.side_effect = [
            page(
                [make_product(price="0.01")],
                "next",
            ),
            page(
                [make_product(price="0.02")],
            ),
        ]

        self.assert_error(
            "CONFLICTING_PRODUCT",
            lambda: self.products.get_products("AmazonEC2"),
        )

    def test_successful_empty_result(self):

        self.client.get_products.return_value = page([])

        result = self.products.get_products(
            "AmazonEC2"
        )

        self.assertTrue(result.is_empty)
        self.assertEqual(result.products, ())
        self.assertEqual(result.page_count, 1)
        self.assertEqual(result.received_count, 0)

    def test_missing_or_invalid_price_list_is_rejected(self):

        invalid_responses = (
            None,
            {},
            {
                "ResponseMetadata": {
                    "HTTPStatusCode": 200,
                },
            },
            {
                "PriceList": "invalid",
                "ResponseMetadata": {
                    "HTTPStatusCode": 200,
                },
            },
        )

        for response in invalid_responses:

            with self.subTest(response=response):

                self.client.get_products.return_value = response

                self.assert_error(
                    "INVALID_RESPONSE",
                    lambda: self.products.get_products("AmazonEC2"),
                )

    def test_invalid_json_documents_are_rejected(self):

        invalid_documents = (
            "{}",
            "[1, 2]",
            "null",
            "{invalid",
            None,
            123,
            '{"product": {}, "product": {}}',
            '{"product": NaN}',
        )

        for document in invalid_documents:

            with self.subTest(document=document):

                self.client.get_products.return_value = page([
                    document,
                ])

                self.assert_error(
                    "INVALID_PRODUCT_DOCUMENT",
                    lambda: self.products.get_products("AmazonEC2"),
                )

    def test_invalid_product_structure_is_rejected(self):

        for field in ("sku", "productFamily", "attributes"):

            with self.subTest(field=field):

                document = json.loads(make_product())

                del document["product"][field]

                self.client.get_products.return_value = page([
                    json.dumps(document),
                ])

                self.assert_error(
                    "INVALID_PRODUCT_DOCUMENT",
                    lambda: self.products.get_products("AmazonEC2"),
                )

        document = json.loads(make_product())

        del document["terms"]

        self.client.get_products.return_value = page([
            json.dumps(document),
        ])

        self.assert_error(
            "INVALID_PRODUCT_DOCUMENT",
            lambda: self.products.get_products("AmazonEC2"),
        )

    def test_conflicting_service_identity_is_rejected(self):

        document = json.loads(make_product())

        document["product"]["attributes"]["servicecode"] = (
            "AmazonS3"
        )

        self.client.get_products.return_value = page([
            json.dumps(document),
        ])

        self.assert_error(
            "INVALID_PRODUCT_DOCUMENT",
            lambda: self.products.get_products("AmazonEC2"),
        )

    def test_service_mismatch_is_rejected(self):

        self.client.get_products.return_value = page([
            make_product(service="AmazonS3"),
        ])

        self.assert_error(
            "SERVICE_MISMATCH",
            lambda: self.products.get_products("AmazonEC2"),
        )

    def test_filter_mismatch_is_rejected(self):

        self.client.get_products.return_value = page([
            make_product(instance_type="m5.large"),
        ])

        self.assert_error(
            "FILTER_MISMATCH",
            lambda: self.products.get_products(
                "AmazonEC2",
                (
                    ProductFilter(
                        "instanceType",
                        "t3.micro",
                    ),
                ),
            ),
        )

    def test_missing_filter_attribute_is_rejected(self):

        self.client.get_products.return_value = page([
            make_product(),
        ])

        self.assert_error(
            "FILTER_MISMATCH",
            lambda: self.products.get_products(
                "AmazonEC2",
                (
                    ProductFilter(
                        "unknownAttribute",
                        "example",
                    ),
                ),
            ),
        )

    def test_repeated_pagination_token_is_rejected(self):

        self.client.get_products.side_effect = [
            page([], "same"),
            page([], "same"),
        ]

        self.assert_error(
            "REPEATED_PAGINATION_TOKEN",
            lambda: self.products.get_products("AmazonEC2"),
        )

        self.assertEqual(
            self.client.get_products.call_count,
            2,
        )

    def test_invalid_pagination_tokens_are_rejected(self):

        for token in (123, [], "   "):

            with self.subTest(token=token):

                self.client.get_products.return_value = page(
                    [],
                    token,
                )

                self.assert_error(
                    "INVALID_PAGINATION_TOKEN",
                    lambda: self.products.get_products("AmazonEC2"),
                )

    def test_page_limit_is_enforced(self):

        service = PricingProducts(
            self.client,
            max_pages=1,
        )

        self.client.get_products.return_value = page(
            [],
            "next",
        )

        self.assert_error(
            "PAGE_LIMIT_EXCEEDED",
            lambda: service.get_products("AmazonEC2"),
        )

    def test_api_error_details_are_preserved(self):

        self.client.get_products.side_effect = ClientError(
            {
                "Error": {
                    "Code": "InvalidParameterException",
                    "Message": "Invalid ServiceCode",
                },
                "ResponseMetadata": {
                    "HTTPStatusCode": 400,
                },
            },
            "GetProducts",
        )

        error = self.assert_error(
            "InvalidParameterException",
            lambda: self.products.get_products("AmazonRDS"),
        )

        self.assertEqual(error.operation, "GetProducts")
        self.assertEqual(error.http_status, 400)
        self.assertEqual(error.api_message, "Invalid ServiceCode")

    def test_connection_failure_is_not_empty_retrieval(self):

        self.client.get_products.side_effect = (
            EndpointConnectionError(
                endpoint_url="http://127.0.0.1:4566"
            )
        )

        self.assert_error(
            "EndpointConnectionError",
            lambda: self.products.get_products("AmazonEC2"),
        )

    def test_unsafe_endpoint_failure_is_preserved(self):

        self.client.get_products.side_effect = (
            UnsafeEndpointError("Blocked request")
        )

        self.assert_error(
            "UNSAFE_ENDPOINT",
            lambda: self.products.get_products("AmazonEC2"),
        )

    def test_later_page_failure_rejects_partial_retrieval(self):

        self.client.get_products.side_effect = [
            page([make_product()], "next"),
            EndpointConnectionError(
                endpoint_url="http://127.0.0.1:4566"
            ),
        ]

        self.assert_error(
            "EndpointConnectionError",
            lambda: self.products.get_products("AmazonEC2"),
        )

    def test_unexpected_http_status_is_rejected(self):

        self.client.get_products.return_value = {
            "PriceList": [],
            "ResponseMetadata": {
                "HTTPStatusCode": 503,
            },
        }

        error = self.assert_error(
            "UNEXPECTED_HTTP_STATUS",
            lambda: self.products.get_products("AmazonEC2"),
        )

        self.assertEqual(error.http_status, 503)

    def test_unknown_format_is_rejected(self):

        response = page([])

        response["FormatVersion"] = "unknown"

        self.client.get_products.return_value = response

        self.assert_error(
            "UNSUPPORTED_FORMAT",
            lambda: self.products.get_products("AmazonEC2"),
        )

    def test_original_price_precision_is_preserved(self):

        raw = make_product(
            price="0.0000002000"
        )

        self.client.get_products.return_value = page([
            raw,
        ])

        result = self.products.get_products("AmazonEC2")

        product = result.products[0]

        self.assertEqual(product.raw_json, raw)

        document = product.to_document()

        rate = (
            document["terms"]["OnDemand"]
            ["TEST-OFFER"]["priceDimensions"]
            ["TEST-RATE"]["pricePerUnit"]["USD"]
        )

        self.assertEqual(
            rate,
            "0.0000002000",
        )

        self.assertEqual(
            Decimal(rate).as_tuple(),
            Decimal("0.0000002000").as_tuple(),
        )

    def test_json_numbers_are_decoded_without_binary_float(self):

        raw = make_product()

        raw = raw[:-1] + ', "exampleNumber": 0.123456789123456789}'

        product = RawPricingProduct.from_json(raw)

        value = product.to_document()["exampleNumber"]

        self.assertIsInstance(value, Decimal)

        self.assertEqual(
            value,
            Decimal("0.123456789123456789"),
        )

    def test_raw_product_is_immutable(self):

        product = RawPricingProduct.from_json(
            make_product()
        )

        with self.assertRaises(FrozenInstanceError):
            product.sku = "UNEXPECTED"

        first = product.to_document()

        first["product"]["sku"] = "CHANGED"

        second = product.to_document()

        self.assertEqual(
            second["product"]["sku"],
            product.sku,
        )

    def test_retrieval_timestamp_is_utc(self):

        self.client.get_products.return_value = page([])

        result = self.products.get_products("AmazonEC2")

        self.assertIs(
            result.retrieved_at.tzinfo,
            timezone.utc,
        )

    def test_identical_filters_are_deduplicated(self):

        self.client.get_products.return_value = page([])

        item = ProductFilter(
            "instanceType",
            "t3.micro",
        )

        result = self.products.get_products(
            "AmazonEC2",
            (item, item),
        )

        self.assertEqual(result.filters, (item,))

    def test_conflicting_filters_are_rejected_before_request(self):

        with self.assertRaises(ValueError):

            self.products.get_products(
                "AmazonEC2",
                (
                    ProductFilter("instanceType", "t3.micro"),
                    ProductFilter("instanceType", "m5.large"),
                ),
            )

        self.client.get_products.assert_not_called()

    def test_conflicting_service_filter_is_rejected(self):

        with self.assertRaises(ValueError):

            self.products.get_products(
                "AmazonEC2",
                (
                    ProductFilter("ServiceCode", "AmazonS3"),
                ),
            )

        self.client.get_products.assert_not_called()

    def test_invalid_query_inputs_are_rejected(self):

        with self.assertRaises(ValueError):
            self.products.get_products("")

        with self.assertRaises(ValueError):
            self.products.get_products(
                "AmazonEC2",
                ("invalid",),
            )

        with self.assertRaises(ValueError):
            ProductFilter("", "value")

        with self.assertRaises(ValueError):
            ProductFilter("instanceType", "")

        self.client.get_products.assert_not_called()

    def test_filter_limit_is_enforced(self):

        filters = tuple(
            ProductFilter(f"field{i}", "value")
            for i in range(51)
        )

        with self.assertRaises(ValueError):

            self.products.get_products(
                "AmazonEC2",
                filters,
            )

        self.client.get_products.assert_not_called()

    def test_invalid_pagination_settings_are_rejected(self):

        for value in (0, -1, True, 101, "10"):

            with self.subTest(page_size=value):

                with self.assertRaises(ValueError):

                    PricingProducts(
                        self.client,
                        page_size=value,
                    )

        for value in (0, -1, True, 1.5):

            with self.subTest(max_pages=value):

                with self.assertRaises(ValueError):

                    PricingProducts(
                        self.client,
                        max_pages=value,
                    )


if __name__ == "__main__":
    unittest.main()
