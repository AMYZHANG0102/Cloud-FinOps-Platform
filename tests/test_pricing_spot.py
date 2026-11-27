"""Verify Spot observation integrity and local persistence."""

import tempfile
import unittest

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from botocore.exceptions import EndpointConnectionError

from finops.config import RuntimeSettings

from finops.pricing.spot import (
    SpotPricingError,
    SpotPricingService,
    SpotQuery,
    retrieve_spot_history,
)


def observation(
    zone="us-east-1a",
    price="0.004400",
    timestamp=None,
    instance="t3.micro",
):

    return {
        "InstanceType": instance,
        "ProductDescription": "Linux/UNIX",
        "AvailabilityZone": zone,
        "Timestamp": (
            datetime.now(timezone.utc)
            - timedelta(minutes=5)
            if timestamp is None
            else timestamp
        ),
        "SpotPrice": price,
    }


def response(rows, token=None):

    result = {
        "SpotPriceHistory": rows,
        "ResponseMetadata": {"HTTPStatusCode": 200},
    }

    if token is not None:
        result["NextToken"] = token

    return result


class SpotPricingTests(unittest.TestCase):

    def setUp(self):

        self.client = Mock()
        self.query = SpotQuery("t3.micro")

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        self.service = SpotPricingService(
            RuntimeSettings(
                runtime_root=Path(directory.name)
            )
        )

    def test_pagination_and_latest_observation_per_zone(self):

        old = observation()

        latest = observation(
            price="0.004532",
            timestamp=(
                old["Timestamp"] + timedelta(minutes=1)
            ),
        )

        second_zone = observation(
            zone="us-east-1b",
            price="0.005",
        )

        self.client.describe_spot_price_history.side_effect = [
            response([old], "NEXT"),
            response([old, latest, second_zone]),
        ]

        result = retrieve_spot_history(
            self.client, self.query
        )

        self.assertEqual(result.page_count, 2)
        self.assertEqual(len(result.observations), 3)
        self.assertEqual(len(result.latest_by_zone), 2)

        self.assertEqual(
            result.latest_for_zone("us-east-1a").unit_price,
            Decimal("0.004532"),
        )

        self.assertIsNone(
            result.latest_for_zone("us-east-1c")
        )

        request = (
            self.client.describe_spot_price_history
            .call_args.kwargs
        )

        self.assertEqual(request["NextToken"], "NEXT")

    def test_millisecond_boundary_precision(self):

        requested_end = (
            datetime.now(timezone.utc)
            - timedelta(seconds=10)
        ).replace(microsecond=392778)

        expected_end = requested_end.replace(
            microsecond=392000
        )

        expected_start = (
            expected_end - timedelta(days=7)
        )

        boundary_observation = observation(
            timestamp=expected_start
        )

        earlier_observation = observation(
            timestamp=(
                expected_start
                - timedelta(milliseconds=1)
            ),
        )

        self.client.describe_spot_price_history.return_value = (
            response([
                earlier_observation,
                boundary_observation,
            ])
        )

        history = retrieve_spot_history(
            self.client,
            self.query,
            end_time=requested_end,
        )

        self.assertEqual(
            history.start_time, expected_start
        )

        self.assertEqual(
            history.end_time, expected_end
        )

        self.assertEqual(
            history.end_time - history.start_time,
            timedelta(days=7),
        )

        self.assertEqual(
            len(history.observations), 1
        )

        self.assertEqual(
            history.observations[0].observed_at,
            expected_start,
        )

        request = (
            self.client.describe_spot_price_history
            .call_args.kwargs
        )

        self.assertEqual(
            request["StartTime"], expected_start
        )

        self.assertEqual(
            request["EndTime"], expected_end
        )

    def test_conflicting_observations_are_rejected(self):

        first = observation()
        second = {**first, "SpotPrice": "0.009"}

        self.client.describe_spot_price_history.return_value = (
            response([first, second])
        )

        with self.assertRaises(SpotPricingError):
            retrieve_spot_history(self.client, self.query)

    def test_wrong_instance_or_zone_is_rejected(self):

        cases = (
            (
                self.query,
                observation(instance="m5.large"),
            ),
            (
                SpotQuery(
                    "t3.micro",
                    availability_zone="us-east-1b",
                ),
                observation(),
            ),
        )

        for query, row in cases:

            with self.subTest(query=query):

                self.client.describe_spot_price_history.return_value = (
                    response([row])
                )

                with self.assertRaises(SpotPricingError):
                    retrieve_spot_history(self.client, query)

    def test_invalid_prices_are_rejected(self):

        for price in ("NaN", "-1", "Infinity", "invalid"):

            with self.subTest(price=price):

                self.client.describe_spot_price_history.return_value = (
                    response([observation(price=price)])
                )

                with self.assertRaises(SpotPricingError):
                    retrieve_spot_history(self.client, self.query)

    def test_repeated_pagination_token_is_rejected(self):

        self.client.describe_spot_price_history.return_value = (
            response([], "REPEAT")
        )

        with self.assertRaises(SpotPricingError) as error:
            retrieve_spot_history(self.client, self.query)

        self.assertEqual(
            error.exception.code,
            "INVALID_PAGINATION",
        )

    def test_observations_before_window_are_excluded(self):

        old = observation(
            timestamp=(
                datetime.now(timezone.utc)
                - timedelta(days=8)
            )
        )

        self.client.describe_spot_price_history.return_value = (
            response([old])
        )

        result = retrieve_spot_history(
            self.client, self.query
        )

        self.assertEqual(result.observations, ())

    def test_successful_empty_history_is_not_zero_price(self):

        self.client.describe_spot_price_history.return_value = (
            response([])
        )

        result = retrieve_spot_history(
            self.client, self.query
        )

        self.assertEqual(result.observations, ())
        self.assertIsNone(
            result.latest_for_zone("us-east-1a")
        )

    @patch("finops.pricing.spot.create_ec2_client")
    def test_cache_round_trip_freshness_and_query_separation(
        self, factory,
    ):

        factory.return_value = self.client

        self.client.describe_spot_price_history.return_value = (
            response([observation()])
        )

        original = self.service.refresh(self.query)

        fresh = self.service.load(
            self.query,
            now=(
                original.retrieved_at
                + timedelta(seconds=299)
            ),
        )

        stale = self.service.load(
            self.query,
            now=(
                original.retrieved_at
                + timedelta(seconds=300)
            ),
        )

        self.assertEqual(fresh.history, original)
        self.assertTrue(fresh.is_fresh)
        self.assertTrue(stale.is_stale)

        self.assertIsNone(
            self.service.load(SpotQuery("m5.large"))
        )

        self.assertIsNone(
            self.service.load(
                SpotQuery("t3.micro", region="us-west-2")
            )
        )

        self.client.close.assert_called_once()

    @patch("finops.pricing.spot.create_ec2_client")
    def test_failed_refresh_preserves_previous_history(
        self, factory,
    ):

        factory.return_value = self.client

        self.client.describe_spot_price_history.return_value = (
            response([observation()])
        )

        self.service.refresh(self.query)

        before = self.service.path.read_bytes()

        self.client.describe_spot_price_history.side_effect = (
            EndpointConnectionError(
                endpoint_url="http://127.0.0.1:4566"
            )
        )

        with self.assertRaises(SpotPricingError):
            self.service.refresh(self.query)

        self.assertEqual(
            self.service.path.read_bytes(),
            before,
        )

    def test_corrupt_cache_is_rejected(self):

        self.service.path.parent.mkdir(
            parents=True, exist_ok=True
        )

        self.service.path.write_text(
            "{invalid",
            encoding="utf-8",
        )

        with self.assertRaises(SpotPricingError):
            self.service.load(self.query)


if __name__ == "__main__":
    unittest.main()
