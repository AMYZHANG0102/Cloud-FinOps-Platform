"""Verify the supplementary and Spot pricing dashboard views."""

import tempfile
import unittest

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from botocore.exceptions import EndpointConnectionError
from streamlit.testing.v1 import AppTest

from finops.config import RuntimeSettings

from finops.pricing.spot import (
    SpotPricingService,
    SpotQuery,
)


PAGE = (
    Path(__file__).resolve().parents[1]
    / "pages"
    / "01_Pricing_Explorer.py"
)


class ExtendedPricingExplorerTests(unittest.TestCase):

    def setUp(self):

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        self.service = SpotPricingService(
            RuntimeSettings(
                runtime_root=Path(directory.name)
            )
        )

        self.client = Mock()

        self.client.describe_services.return_value = {
            "Services": [],
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

        self.client.describe_spot_price_history.return_value = {
            "SpotPriceHistory": [
                {
                    "InstanceType": "t3.micro",
                    "ProductDescription": "Linux/UNIX",
                    "AvailabilityZone": "us-east-1a",
                    "SpotPrice": "0.004400",
                    "Timestamp": (
                        datetime.now(timezone.utc)
                        - timedelta(minutes=1)
                    ),
                }
            ],
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

        patches = (
            patch(
                "finops.pricing.client.create_pricing_client",
                return_value=self.client,
            ),
            patch(
                "finops.pricing.spot.create_ec2_client",
                return_value=self.client,
            ),
            patch(
                "finops.pricing.spot.SpotPricingService",
                return_value=self.service,
            ),
        )

        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def open_view(self, view):

        app = AppTest.from_file(
            str(PAGE),
            default_timeout=30,
        ).run()

        app.radio(
            key="m1.view"
        ).set_value(view).run()

        self.assertFalse(app.exception)

        return app

    def test_reference_catalogue_displays_all_eight_rates(self):

        app = self.open_view(
            "Supplementary Reference Pricing"
        )

        self.assertFalse(app.error)
        self.assertEqual(len(app.dataframe), 1)

        table = app.dataframe[0].value

        self.assertEqual(len(table), 8)

        self.assertEqual(
            set(table["Source"]),
            {"REFERENCE_DATA"},
        )

        self.client.get_products.assert_not_called()

    def test_reference_service_filter(self):

        app = self.open_view(
            "Supplementary Reference Pricing"
        )

        app.selectbox(
            key="m1.reference.service"
        ).select("AmazonDynamoDB").run()

        self.assertFalse(app.exception)

        table = app.dataframe[0].value

        self.assertEqual(len(table), 3)

        self.assertEqual(
            set(table["Service"]),
            {"Amazon DynamoDB"},
        )

    def test_spot_retrieval_and_persistence(self):

        app = self.open_view("EC2 Spot Pricing")

        app.button(
            key="m1.spot.retrieve"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertTrue(app.success)

        table = app.dataframe[0].value

        self.assertEqual(
            table["Unit price"].tolist(),
            ["0.004400"],
        )

        self.assertEqual(
            table["Source"].tolist(),
            ["FLOCI_EC2_API"],
        )

        self.assertIsNotNone(
            self.service.load(SpotQuery("t3.micro"))
        )

        calls = self.client.describe_spot_price_history.call_count

        app.run()

        self.assertFalse(app.exception)
        self.assertEqual(
            self.client.describe_spot_price_history.call_count,
            calls,
        )

        self.assertTrue(app.dataframe)

    def test_empty_spot_history_is_explicit(self):

        self.client.describe_spot_price_history.return_value = {
            "SpotPriceHistory": [],
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

        app = self.open_view("EC2 Spot Pricing")

        app.button(
            key="m1.spot.retrieve"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 0)

        self.assertTrue(any(
            "No Spot observations" in warning.value
            for warning in app.warning
        ))

    def test_failed_spot_refresh_does_not_substitute_cache(self):

        app = self.open_view("EC2 Spot Pricing")

        app.button(
            key="m1.spot.retrieve"
        ).click().run()

        before = self.service.path.read_bytes()

        self.client.describe_spot_price_history.side_effect = (
            EndpointConnectionError(
                endpoint_url="http://127.0.0.1:4566"
            )
        )

        app.button(
            key="m1.spot.retrieve"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertEqual(len(app.dataframe), 0)

        self.assertEqual(
            self.service.path.read_bytes(),
            before,
        )

    def test_expired_spot_cache_requires_permission(self):

        query = SpotQuery("t3.micro")

        history = self.service.refresh(query)

        expired = self.service.load(
            query,
            now=(
                history.retrieved_at
                + timedelta(seconds=300)
            ),
        )

        with patch.object(
            self.service,
            "load",
            return_value=expired,
        ):

            app = self.open_view("EC2 Spot Pricing")

            self.assertFalse(app.exception)
            self.assertEqual(len(app.dataframe), 0)

            app.checkbox(
                key="m1.spot.historical"
            ).check().run()

            self.assertFalse(app.exception)
            self.assertTrue(app.dataframe)


if __name__ == "__main__":
    unittest.main()
