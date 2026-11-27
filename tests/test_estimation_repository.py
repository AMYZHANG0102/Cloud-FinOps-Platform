"""Verify historical estimates and immutable pricing snapshots."""

import json
import os
import tempfile
import unittest

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from finops.config import RuntimeSettings

from finops.estimation.engine import InfrastructureCostEstimator

from finops.estimation.financial import (
    EstimateStatus,
)

from finops.estimation.repository import (
    EstimateConflictError,
    EstimateNotFoundError,
    EstimateRepository,
    EstimateRepositoryError,
)

from finops.pricing.models import PricingSource

from test_estimation_engine import (
    FixtureResolver,
    ec2,
    s3,
    scenario,
)


D = Decimal


class EstimateRepositoryTests(unittest.TestCase):

    def setUp(self):

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        self.settings = RuntimeSettings(
            runtime_root=Path(directory.name)
        )

        self.repository = EstimateRepository(
            self.settings
        )

        self.estimator = InfrastructureCostEstimator(
            FixtureResolver()
        )

    def complete_estimate(self):

        return self.estimator.estimate(
            scenario(ec2(), s3())
        )

    def test_complete_estimate_round_trip(self):

        estimate = self.complete_estimate()

        saved = self.repository.save(estimate)

        reopened = EstimateRepository(self.settings)

        loaded = reopened.load(saved.estimate_id)

        self.assertEqual(loaded, estimate)

        self.assertEqual(
            loaded.summary.complete_monthly_cost,
            D("34.276"),
        )

        self.assertEqual(
            loaded.summary.complete_period_costs.annual,
            D("411.312"),
        )

        self.assertTrue(
            reopened.snapshot_path(
                estimate.estimate_id
            ).is_file()
        )

    def test_partial_estimate_preserves_pooled_coverage(self):

        estimate = self.estimator.estimate(
            scenario(s3("30000"), s3("30000"))
        )

        self.repository.save(estimate)

        loaded = self.repository.load(
            estimate.estimate_id
        )

        self.assertEqual(loaded, estimate)

        self.assertEqual(
            loaded.summary.status,
            EstimateStatus.PARTIAL,
        )

        self.assertEqual(
            loaded.summary.known_monthly_cost,
            D("1177.60"),
        )

        self.assertIsNone(
            loaded.summary.complete_monthly_cost
        )

        self.assertIsNone(
            loaded.summary.complete_period_costs
        )

        storage = [
            item
            for item in loaded.components
            if item.billing.component == "storage"
        ]

        self.assertEqual(
            storage[0].pool_usage,
            D("60000"),
        )

        self.assertEqual(
            storage[0].pool_priced_usage,
            D("51200"),
        )

    def test_reference_pricing_evidence_is_preserved(self):

        estimator = InfrastructureCostEstimator(
            FixtureResolver(reference=True)
        )

        estimate = estimator.estimate(
            scenario(ec2()),
            allow_reference=True,
        )

        self.repository.save(estimate)

        loaded = self.repository.load(
            estimate.estimate_id
        )

        record = loaded.components[0].resolution.records[0]

        self.assertTrue(loaded.allow_reference)

        self.assertEqual(
            record.source,
            PricingSource.REFERENCE_DATA,
        )

        self.assertEqual(
            record,
            estimate.components[0].resolution.records[0],
        )

        self.assertIsNotNone(record.verified_at)

    def test_saved_estimates_cannot_be_overwritten(self):

        estimate = self.complete_estimate()

        self.repository.save(estimate)

        estimate_path = self.repository.estimate_path(
            estimate.estimate_id
        )

        snapshot_path = self.repository.snapshot_path(
            estimate.estimate_id
        )

        before_estimate = estimate_path.read_bytes()
        before_snapshot = snapshot_path.read_bytes()

        with self.assertRaises(EstimateConflictError):

            self.repository.save(estimate)

        self.assertEqual(
            estimate_path.read_bytes(),
            before_estimate,
        )

        self.assertEqual(
            snapshot_path.read_bytes(),
            before_snapshot,
        )

    def test_historical_scenario_revision_is_preserved(self):

        original = scenario(ec2())

        first = self.estimator.estimate(original)

        self.repository.save(first)

        modified = replace(
            original,
            revision=2,
            resources=(
                replace(
                    original.resources[0],
                    quantity=6,
                ),
            ),
        )

        second = self.estimator.estimate(modified)

        self.repository.save(second)

        historical = self.repository.load(
            first.estimate_id
        )

        current = self.repository.load(
            second.estimate_id
        )

        self.assertEqual(
            historical.scenario_revision,
            1,
        )

        self.assertEqual(
            current.scenario_revision,
            2,
        )

        self.assertEqual(
            historical.summary.complete_monthly_cost,
            D("22.776"),
        )

        self.assertEqual(
            current.summary.complete_monthly_cost,
            D("45.552"),
        )

        self.assertEqual(
            historical.scenario.resources[0].quantity,
            3,
        )

    def test_list_and_filter_saved_estimates(self):

        first = self.complete_estimate()

        second = self.estimator.estimate(
            scenario(ec2(quantity=1))
        )

        self.repository.save(first)
        self.repository.save(second)

        estimates = self.repository.list_estimates()

        self.assertEqual(len(estimates), 2)

        self.assertEqual(
            {item.estimate_id for item in estimates},
            {first.estimate_id, second.estimate_id},
        )

        self.assertEqual(
            self.repository.list_estimates(
                first.scenario_id
            ),
            (first,),
        )

        self.assertEqual(
            self.repository.list_estimates(uuid4()),
            (),
        )

    def test_missing_estimate_and_snapshot(self):

        with self.assertRaises(EstimateNotFoundError):

            self.repository.load(uuid4())

        estimate = self.complete_estimate()

        self.repository.save(estimate)

        self.repository.snapshot_path(
            estimate.estimate_id
        ).unlink()

        with self.assertRaises(EstimateRepositoryError):

            self.repository.load(estimate.estimate_id)

    def test_corrupted_pricing_snapshot_is_rejected(self):

        estimate = self.complete_estimate()

        self.repository.save(estimate)

        path = self.repository.snapshot_path(
            estimate.estimate_id
        )

        document = json.loads(
            path.read_text(encoding="utf-8")
        )

        document["scenario_revision"] = 999

        path.write_text(
            json.dumps(document),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            EstimateRepositoryError,
            "checksum mismatch",
        ):

            self.repository.load(estimate.estimate_id)

    def test_corrupted_financial_summary_is_rejected(self):

        estimate = self.complete_estimate()

        self.repository.save(estimate)

        path = self.repository.estimate_path(
            estimate.estimate_id
        )

        document = json.loads(
            path.read_text(encoding="utf-8")
        )

        document["summary"]["known_monthly_cost"] = "9999"

        path.write_text(
            json.dumps(document),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            EstimateRepositoryError,
            "summary mismatch",
        ):

            self.repository.load(estimate.estimate_id)

    def test_failed_estimate_write_is_not_published(self):

        estimate = self.complete_estimate()

        original_replace = os.replace

        def fail_final_write(source, destination):

            if (
                Path(destination).parent
                == self.repository.estimates_directory
            ):

                raise OSError(
                    "Simulated estimate publication failure."
                )

            return original_replace(
                source,
                destination,
            )

        with patch(
            "finops.estimation.repository.os.replace",
            side_effect=fail_final_write,
        ):

            with self.assertRaises(EstimateRepositoryError):

                self.repository.save(estimate)

        self.assertEqual(
            self.repository.list_estimates(),
            (),
        )

        self.assertFalse(
            self.repository.estimate_path(
                estimate.estimate_id
            ).exists()
        )

        self.assertTrue(
            self.repository.snapshot_path(
                estimate.estimate_id
            ).exists()
        )

        self.assertEqual(
            list(
                self.repository.estimates_directory.glob("*.tmp")
            ),
            [],
        )

        with self.assertRaises(EstimateConflictError):

            self.repository.save(estimate)


if __name__ == "__main__":
    unittest.main()
