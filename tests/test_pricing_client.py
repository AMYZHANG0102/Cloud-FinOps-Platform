"""Isolated tests for local Floci client configuration."""

import os
import tempfile
import unittest

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from finops.pricing.client import (
    DEFAULT_FLOCI_ENDPOINT,
    FlociClientSettings,
    UnsafeEndpointError,
    build_client_config,
    create_ec2_client,
    create_floci_client,
    create_pricing_client,
    ensure_local_request,
    normalize_local_endpoint,
    validate_region,
)


class EndpointValidationTests(unittest.TestCase):

    def test_default_endpoint_is_loopback(self):
        self.assertEqual(
            FlociClientSettings().endpoint_url,
            DEFAULT_FLOCI_ENDPOINT,
        )

    def test_localhost_is_canonicalized(self):
        self.assertEqual(
            normalize_local_endpoint(
                "http://localhost:4566/"
            ),
            "http://127.0.0.1:4566",
        )

    def test_custom_local_port(self):
        self.assertEqual(
            normalize_local_endpoint(
                "http://127.0.0.1:55466"
            ),
            "http://127.0.0.1:55466",
        )

    def test_remote_endpoints_are_rejected(self):
        endpoints = (
            "https://api.pricing.us-east-1.amazonaws.com",
            "https://ec2.us-east-1.amazonaws.com",
            "http://example.com:4566",
            "http://192.168.1.10:4566",
            "http://0.0.0.0:4566",
            "http://localhost.example.com:4566",
        )

        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(UnsafeEndpointError):
                    FlociClientSettings(
                        endpoint_url=endpoint
                    )

    def test_malformed_endpoints_are_rejected(self):
        endpoints = (
            "",
            None,
            4566,
            "localhost:4566",
            "http://localhost",
            "http://localhost:0",
            "http://localhost:65536",
            "http://localhost:-1",
            "http://localhost:abc",
            "http://localhost:4566/path",
            "http://localhost:4566?query=1",
            "http://localhost:4566#fragment",
            "http://user@localhost:4566",
            "http://localhost:4566@remote.example",
            "http://localhost:4566\n",
            "https://localhost:4566",
        )

        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(UnsafeEndpointError):
                    normalize_local_endpoint(endpoint)

    def test_valid_regions(self):
        for region in (
            "us-east-1",
            "us-west-2",
            "eu-central-1",
            "ca-central-1",
            "us-gov-west-1",
        ):
            with self.subTest(region=region):
                self.assertEqual(
                    validate_region(region),
                    region,
                )

    def test_invalid_regions(self):
        for region in (
            "",
            None,
            "US-EAST-1",
            "us east 1",
            "localhost",
            "us-east",
            "us-east-1.example.com",
        ):
            with self.subTest(region=region):
                with self.assertRaises(ValueError):
                    validate_region(region)


class ClientSettingsTests(unittest.TestCase):

    def test_default_transport_settings(self):
        settings = FlociClientSettings()

        self.assertEqual(settings.region, "us-east-1")
        self.assertEqual(settings.connect_timeout, 3)
        self.assertEqual(settings.read_timeout, 10)
        self.assertEqual(settings.total_max_attempts, 3)

    def test_settings_are_immutable(self):
        settings = FlociClientSettings()

        with self.assertRaises(FrozenInstanceError):
            settings.endpoint_url = "http://example.com"

    def test_invalid_transport_values(self):
        for name in (
            "connect_timeout",
            "read_timeout",
            "total_max_attempts",
        ):
            for value in (
                0, -1, True, 1.5, "3", None
            ):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        FlociClientSettings(
                            **{name: value}
                        )

    def test_excessive_attempts_are_rejected(self):
        with self.assertRaises(ValueError):
            FlociClientSettings(total_max_attempts=6)

    def test_explicit_botocore_configuration(self):
        settings = FlociClientSettings(
            connect_timeout=2,
            read_timeout=5,
            total_max_attempts=2,
        )

        config = build_client_config(settings)

        self.assertEqual(config.signature_version, "v4")
        self.assertEqual(config.connect_timeout, 2)
        self.assertEqual(config.read_timeout, 5)
        self.assertEqual(config.retries["mode"], "standard")
        self.assertEqual(
            config.retries["total_max_attempts"],
            2,
        )
        self.assertEqual(config.proxies, {})
        self.assertTrue(
            config.ignore_configured_endpoint_urls
        )
        self.assertFalse(config.use_fips_endpoint)
        self.assertFalse(config.use_dualstack_endpoint)


class OutgoingRequestTests(unittest.TestCase):

    def test_matching_local_request_is_permitted(self):
        ensure_local_request(
            "http://127.0.0.1:4566/",
            DEFAULT_FLOCI_ENDPOINT,
        )

    def test_local_paths_and_queries_are_permitted(self):
        ensure_local_request(
            "http://127.0.0.1:4566/path?example=1",
            DEFAULT_FLOCI_ENDPOINT,
        )

    def test_different_origins_are_blocked(self):
        urls = (
            "https://ec2.amazonaws.com/",
            "http://example.com:4566/",
            "http://127.0.0.1:4567/",
            "https://127.0.0.1:4566/",
            "http://127.0.0.1:4566@example.com/",
            "http://127.0.0.1:4566.example.com/",
            "http://127.0.0.1:4566/#fragment",
            "\nhttp://127.0.0.1:4566/",
            None,
        )

        for url in urls:
            with self.subTest(url=url):
                with self.assertRaises(UnsafeEndpointError):
                    ensure_local_request(
                        url,
                        DEFAULT_FLOCI_ENDPOINT,
                    )


class ClientFactoryTests(unittest.TestCase):

    @patch("finops.pricing.client.boto3.session.Session")
    def test_unsupported_service_rejected_before_session(
        self,
        session_class,
    ):
        with self.assertRaises(ValueError):
            create_floci_client("s3")

        session_class.assert_not_called()

    @patch("finops.pricing.client.boto3.session.Session")
    def test_explicit_pricing_credentials_and_region(
        self,
        session_class,
    ):
        session = session_class.return_value
        client = session.client.return_value

        client.meta.endpoint_url = DEFAULT_FLOCI_ENDPOINT

        settings = FlociClientSettings(
            region="us-west-2"
        )

        result = create_pricing_client(settings)

        self.assertIs(result, client)

        session_class.assert_called_once_with(
            aws_access_key_id="test",
            aws_secret_access_key="test",
            region_name="us-east-1",
        )

        kwargs = session.client.call_args.kwargs

        self.assertEqual(
            session.client.call_args.args,
            ("pricing",),
        )

        self.assertEqual(
            kwargs["endpoint_url"],
            DEFAULT_FLOCI_ENDPOINT,
        )

        self.assertEqual(
            kwargs["region_name"],
            "us-east-1",
        )

    @patch("finops.pricing.client.boto3.session.Session")
    def test_ec2_uses_selected_region(
        self,
        session_class,
    ):
        session = session_class.return_value

        session.client.return_value.meta.endpoint_url = (
            DEFAULT_FLOCI_ENDPOINT
        )

        create_ec2_client(
            FlociClientSettings(region="ca-central-1")
        )

        self.assertEqual(
            session.client.call_args.args,
            ("ec2",),
        )

        self.assertEqual(
            session.client.call_args.kwargs["region_name"],
            "ca-central-1",
        )

    @patch("finops.pricing.client.boto3.session.Session")
    def test_unexpected_constructed_endpoint_is_rejected(
        self,
        session_class,
    ):
        client = (
            session_class.return_value.client.return_value
        )

        client.meta.endpoint_url = (
            "https://ec2.amazonaws.com"
        )

        with self.assertRaises(UnsafeEndpointError):
            create_ec2_client()

        client.close.assert_called_once()

        client.meta.events.register.assert_not_called()

    @patch("finops.pricing.client.boto3.session.Session")
    def test_outgoing_request_guard_is_registered(
        self,
        session_class,
    ):
        client = (
            session_class.return_value.client.return_value
        )

        client.meta.endpoint_url = DEFAULT_FLOCI_ENDPOINT

        create_pricing_client()

        args = client.meta.events.register.call_args.args

        self.assertEqual(args[0], "before-send")

        handler = args[1]

        handler(
            SimpleNamespace(
                url="http://127.0.0.1:4566/"
            )
        )

        with self.assertRaises(UnsafeEndpointError):
            handler(
                SimpleNamespace(
                    url="https://example.com/"
                )
            )


class RealSDKConstructionTests(unittest.TestCase):

    def test_real_clients_use_explicit_local_configuration(self):
        with tempfile.TemporaryDirectory() as directory:

            config_file = Path(directory) / "config"
            credentials_file = Path(directory) / "credentials"

            config_file.write_text(
                "[default]\n",
                encoding="utf-8",
            )

            credentials_file.write_text(
                "[default]\n",
                encoding="utf-8",
            )

            environment = {
                "AWS_CONFIG_FILE": str(config_file),
                "AWS_SHARED_CREDENTIALS_FILE": str(
                    credentials_file
                ),
                "AWS_PROFILE": "default",
                "AWS_DEFAULT_PROFILE": "default",
                "AWS_ACCESS_KEY_ID": "synthetic-environment-key",
                "AWS_SECRET_ACCESS_KEY": "synthetic-environment-secret",
                "AWS_SESSION_TOKEN": "synthetic-environment-token",
                "AWS_ENDPOINT_URL": "https://example.com",
                "AWS_ENDPOINT_URL_PRICING": "https://example.com",
                "AWS_ENDPOINT_URL_EC2": "https://example.com",
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_MAX_ATTEMPTS": "9",
                "HTTP_PROXY": "http://example.com:8888",
                "HTTPS_PROXY": "http://example.com:8888",
            }

            with patch.dict(os.environ, environment):

                for service in ("pricing", "ec2"):

                    with self.subTest(service=service):

                        client = create_floci_client(service)

                        try:
                            self.assertEqual(
                                client.meta.endpoint_url,
                                DEFAULT_FLOCI_ENDPOINT,
                            )

                            self.assertEqual(
                                client.meta.region_name,
                                "us-east-1",
                            )

                            self.assertEqual(
                                client.meta.config.proxies,
                                {},
                            )

                            self.assertEqual(
                                client.meta.config.retries[
                                    "total_max_attempts"
                                ],
                                3,
                            )

                            self.assertEqual(
                                client.meta.service_model.service_name,
                                service,
                            )

                        finally:
                            client.close()

    @patch("finops.pricing.client.boto3.session.Session")
    def test_request_guard_rejects_remote_destination(
        self,
        session_class,
    ):
        client = Mock()

        client.meta.endpoint_url = DEFAULT_FLOCI_ENDPOINT

        session_class.return_value.client.return_value = (
            client
        )

        create_ec2_client()

        handler = (
            client.meta.events.register.call_args.args[1]
        )

        with self.assertRaises(UnsafeEndpointError):
            handler(
                SimpleNamespace(
                    url="https://ec2.us-east-1.amazonaws.com/"
                )
            )


if __name__ == "__main__":
    unittest.main()
