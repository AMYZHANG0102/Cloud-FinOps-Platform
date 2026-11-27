"""Isolated verification of Pricing API discovery behaviour."""

import unittest

from dataclasses import FrozenInstanceError
from unittest.mock import Mock

from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
)

from finops.pricing.client import UnsafeEndpointError

from finops.pricing.discovery import (
    PricingDiscovery,
    PricingDiscoveryError,
    ServiceDescription,
)


def page(result_key, items, token=None):
    response = {
        result_key: items,
        "ResponseMetadata": {
            "HTTPStatusCode": 200,
        },
    }

    if token is not None:
        response["NextToken"] = token

    return response


def service(code="AmazonEC2", attributes=None):
    if attributes is None:
        attributes = [
            "instanceType",
            "location",
            "operatingSystem",
        ]

    return {
        "ServiceCode": code,
        "AttributeNames": attributes,
    }


class PricingDiscoveryTests(unittest.TestCase):

    def setUp(self):
        self.client = Mock()

        self.discovery = PricingDiscovery(
            self.client,
            page_size=2,
            max_pages=5,
        )

    def test_service_discovery(self):
        self.client.describe_services.return_value = page(
            "Services",
            [
                service("AmazonS3"),
                service("AmazonEC2"),
            ],
        )

        result = self.discovery.list_services()

        self.assertEqual(
            tuple(item.service_code for item in result),
            ("AmazonEC2", "AmazonS3"),
        )

        self.client.describe_services.assert_called_once_with(
            MaxResults=2
        )

    def test_filtered_service_discovery(self):
        self.client.describe_services.return_value = page(
            "Services",
            [service()],
        )

        result = self.discovery.list_services("AmazonEC2")

        self.assertEqual(len(result), 1)

        self.client.describe_services.assert_called_once_with(
            ServiceCode="AmazonEC2",
            MaxResults=2,
        )

    def test_service_metadata_is_immutable(self):
        names = ["location", "instanceType"]

        description = ServiceDescription(
            "AmazonEC2",
            names,
        )

        names.clear()

        self.assertEqual(
            description.attribute_names,
            ("instanceType", "location"),
        )

        with self.assertRaises(FrozenInstanceError):
            description.service_code = "AmazonS3"

    def test_attribute_name_discovery(self):
        self.client.describe_services.return_value = page(
            "Services",
            [
                service(
                    attributes=[
                        "location",
                        "instanceType",
                        "location",
                    ]
                )
            ],
        )

        result = self.discovery.list_attributes(
            "AmazonEC2"
        )

        self.assertEqual(
            result,
            ("instanceType", "location"),
        )

    def test_attribute_value_discovery(self):
        self.client.get_attribute_values.return_value = page(
            "AttributeValues",
            [
                {"Value": "t3.micro"},
                {"Value": "m5.large"},
            ],
        )

        result = self.discovery.list_attribute_values(
            "AmazonEC2",
            "instanceType",
        )

        self.assertEqual(
            result,
            ("m5.large", "t3.micro"),
        )

        self.client.get_attribute_values.assert_called_once_with(
            ServiceCode="AmazonEC2",
            AttributeName="instanceType",
            MaxResults=2,
        )

    def test_service_pagination(self):
        self.client.describe_services.side_effect = [
            page(
                "Services",
                [service("AmazonEC2")],
                "page-2",
            ),
            page(
                "Services",
                [service("AmazonS3")],
            ),
        ]

        result = self.discovery.list_services()

        self.assertEqual(len(result), 2)

        self.assertEqual(
            self.client.describe_services.call_count,
            2,
        )

        self.assertEqual(
            self.client.describe_services.call_args.kwargs,
            {
                "MaxResults": 2,
                "NextToken": "page-2",
            },
        )

    def test_attribute_value_pagination(self):
        self.client.get_attribute_values.side_effect = [
            page(
                "AttributeValues",
                [{"Value": "t3.micro"}],
                "next",
            ),
            page(
                "AttributeValues",
                [{"Value": "m5.large"}],
            ),
        ]

        result = self.discovery.list_attribute_values(
            "AmazonEC2",
            "instanceType",
        )

        self.assertEqual(
            result,
            ("m5.large", "t3.micro"),
        )

        self.assertEqual(
            self.client.get_attribute_values.call_args.kwargs,
            {
                "ServiceCode": "AmazonEC2",
                "AttributeName": "instanceType",
                "MaxResults": 2,
                "NextToken": "next",
            },
        )

    def test_identical_service_duplicates_are_removed(self):
        self.client.describe_services.return_value = page(
            "Services",
            [
                service(),
                service(),
            ],
        )

        self.assertEqual(
            len(self.discovery.list_services()),
            1,
        )

    def test_conflicting_service_metadata_is_rejected(self):
        self.client.describe_services.return_value = page(
            "Services",
            [
                service(attributes=["location"]),
                service(attributes=["instanceType"]),
            ],
        )

        with self.assertRaises(PricingDiscoveryError) as context:
            self.discovery.list_services()

        self.assertEqual(
            context.exception.code,
            "CONFLICTING_SERVICE_METADATA",
        )

    def test_duplicate_attribute_values_are_removed(self):
        self.client.get_attribute_values.side_effect = [
            page(
                "AttributeValues",
                [{"Value": "Linux"}],
                "next",
            ),
            page(
                "AttributeValues",
                [
                    {"Value": "Linux"},
                    {"Value": "Windows"},
                ],
            ),
        ]

        result = self.discovery.list_attribute_values(
            "AmazonEC2",
            "operatingSystem",
        )

        self.assertEqual(
            result,
            ("Linux", "Windows"),
        )

    def test_repeated_pagination_token_is_rejected(self):
        self.client.describe_services.side_effect = [
            page("Services", [], "same"),
            page("Services", [], "same"),
        ]

        with self.assertRaises(PricingDiscoveryError) as context:
            self.discovery.list_services()

        self.assertEqual(
            context.exception.code,
            "REPEATED_PAGINATION_TOKEN",
        )

        self.assertEqual(
            self.client.describe_services.call_count,
            2,
        )

    def test_invalid_pagination_token_is_rejected(self):
        for token in (123, [], "   "):

            with self.subTest(token=token):
                self.client.describe_services.return_value = page(
                    "Services",
                    [],
                    token,
                )

                with self.assertRaises(PricingDiscoveryError) as context:
                    self.discovery.list_services()

                self.assertEqual(
                    context.exception.code,
                    "INVALID_PAGINATION_TOKEN",
                )

    def test_page_limit_is_enforced(self):
        discovery = PricingDiscovery(
            self.client,
            max_pages=1,
        )

        self.client.describe_services.return_value = page(
            "Services",
            [service()],
            "next",
        )

        with self.assertRaises(PricingDiscoveryError) as context:
            discovery.list_services()

        self.assertEqual(
            context.exception.code,
            "PAGE_LIMIT_EXCEEDED",
        )

        self.assertEqual(
            self.client.describe_services.call_count,
            1,
        )

    def test_empty_attribute_response_is_valid(self):
        self.client.get_attribute_values.return_value = page(
            "AttributeValues",
            [],
        )

        result = self.discovery.list_attribute_values(
            "AmazonEC2",
            "regionCode",
        )

        self.assertEqual(result, ())

    def test_empty_service_response_is_valid(self):
        self.client.describe_services.return_value = page(
            "Services",
            [],
        )

        self.assertEqual(
            self.discovery.list_services(),
            (),
        )

    def test_missing_service_has_explicit_outcome(self):
        self.client.describe_services.return_value = page(
            "Services",
            [],
        )

        with self.assertRaises(PricingDiscoveryError) as context:
            self.discovery.list_attributes(
                "AmazonEC2"
            )

        self.assertEqual(
            context.exception.code,
            "SERVICE_NOT_FOUND",
        )

    def test_filtered_service_mismatch_is_rejected(self):
        self.client.describe_services.return_value = page(
            "Services",
            [service("AmazonS3")],
        )

        with self.assertRaises(PricingDiscoveryError) as context:
            self.discovery.list_services(
                "AmazonEC2"
            )

        self.assertEqual(
            context.exception.code,
            "SERVICE_MISMATCH",
        )

    def test_missing_result_collection_is_rejected(self):
        self.client.describe_services.return_value = {
            "ResponseMetadata": {
                "HTTPStatusCode": 200,
            }
        }

        with self.assertRaises(PricingDiscoveryError) as context:
            self.discovery.list_services()

        self.assertEqual(
            context.exception.code,
            "INVALID_RESPONSE",
        )

    def test_invalid_service_descriptions_are_rejected(self):
        invalid_items = (
            None,
            {},
            {"ServiceCode": "AmazonEC2"},
            {
                "ServiceCode": "",
                "AttributeNames": [],
            },
            {
                "ServiceCode": "AmazonEC2",
                "AttributeNames": "location",
            },
            {
                "ServiceCode": "AmazonEC2",
                "AttributeNames": [None],
            },
        )

        for item in invalid_items:
            with self.subTest(item=item):

                self.client.describe_services.return_value = page(
                    "Services",
                    [item],
                )

                with self.assertRaises(PricingDiscoveryError) as context:
                    self.discovery.list_services()

                self.assertEqual(
                    context.exception.code,
                    "INVALID_RESPONSE",
                )

    def test_invalid_attribute_values_are_rejected(self):
        for item in (
            None,
            {},
            {"Value": ""},
            {"Value": 123},
        ):
            with self.subTest(item=item):

                self.client.get_attribute_values.return_value = page(
                    "AttributeValues",
                    [item],
                )

                with self.assertRaises(PricingDiscoveryError) as context:
                    self.discovery.list_attribute_values(
                        "AmazonEC2",
                        "instanceType",
                    )

                self.assertEqual(
                    context.exception.code,
                    "INVALID_RESPONSE",
                )

    def test_unexpected_http_status_is_rejected(self):
        self.client.describe_services.return_value = {
            "Services": [],
            "ResponseMetadata": {
                "HTTPStatusCode": 503,
            },
        }

        with self.assertRaises(PricingDiscoveryError) as context:
            self.discovery.list_services()

        self.assertEqual(
            context.exception.code,
            "UNEXPECTED_HTTP_STATUS",
        )

        self.assertEqual(
            context.exception.http_status,
            503,
        )

    def test_api_error_code_is_preserved(self):
        self.client.describe_services.side_effect = ClientError(
            {
                "Error": {
                    "Code": "InvalidParameterException",
                    "Message": "Invalid ServiceCode",
                },
                "ResponseMetadata": {
                    "HTTPStatusCode": 400,
                },
            },
            "DescribeServices",
        )

        with self.assertRaises(PricingDiscoveryError) as context:
            self.discovery.list_services(
                "AmazonRDS"
            )

        self.assertEqual(
            context.exception.code,
            "InvalidParameterException",
        )

        self.assertEqual(
            context.exception.operation,
            "DescribeServices",
        )

        self.assertEqual(
            context.exception.http_status,
            400,
        )

    def test_connection_failure_is_not_empty_discovery(self):
        self.client.describe_services.side_effect = (
            EndpointConnectionError(
                endpoint_url="http://127.0.0.1:4566"
            )
        )

        with self.assertRaises(PricingDiscoveryError) as context:
            self.discovery.list_services()

        self.assertEqual(
            context.exception.code,
            "EndpointConnectionError",
        )

    def test_unsafe_endpoint_failure_is_preserved(self):
        self.client.describe_services.side_effect = (
            UnsafeEndpointError("Blocked endpoint")
        )

        with self.assertRaises(PricingDiscoveryError) as context:
            self.discovery.list_services()

        self.assertEqual(
            context.exception.code,
            "UNSAFE_ENDPOINT",
        )

    def test_later_page_failure_does_not_return_partial_results(self):
        self.client.describe_services.side_effect = [
            page(
                "Services",
                [service()],
                "next",
            ),
            EndpointConnectionError(
                endpoint_url="http://127.0.0.1:4566"
            ),
        ]

        with self.assertRaises(PricingDiscoveryError):
            self.discovery.list_services()

    def test_invalid_inputs_are_rejected_before_api_calls(self):
        with self.assertRaises(ValueError):
            self.discovery.list_services("")

        with self.assertRaises(ValueError):
            self.discovery.list_attributes(None)

        with self.assertRaises(ValueError):
            self.discovery.list_attribute_values(
                "AmazonEC2",
                "",
            )

        self.client.describe_services.assert_not_called()
        self.client.get_attribute_values.assert_not_called()

    def test_invalid_pagination_settings_are_rejected(self):
        for value in (0, -1, True, 101, "10"):

            with self.subTest(page_size=value):
                with self.assertRaises(ValueError):
                    PricingDiscovery(
                        self.client,
                        page_size=value,
                    )

        for value in (0, -1, True, 1.5):

            with self.subTest(max_pages=value):
                with self.assertRaises(ValueError):
                    PricingDiscovery(
                        self.client,
                        max_pages=value,
                    )


if __name__ == "__main__":
    unittest.main()
