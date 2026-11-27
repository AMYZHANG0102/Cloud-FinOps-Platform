"""Verify comparison orchestration and infrastructure projections."""

import unittest

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from finops.comparison.compute import (
    ComputeWorkload,
    ReservedAssumptions,
    SavingsPlanAssumptions,
)

from finops.comparison.engine import PricingComparisonEngine

from finops.comparison.models import (
    ComparisonScope,
    PricingOption,
)

from finops.comparison.storage import (
    STORAGE_COMPONENTS,
    STORAGE_EXCLUSIONS,
    StorageRateAssumptions,
    StorageWorkload,
)

from finops.estimation.financial import EstimateStatus

from finops.infrastructure.models import ResourceType

from finops.pricing.models import (
    PricingModel,
    PricingSource,
    SpotPriceObservation,
)


D = Decimal


class ComparisonEngineTests(unittest.TestCase):

    def setUp(self):

        self.estimate_id = uuid4()
        self.resource_id = uuid4()

        self.estimate = SimpleNamespace(
            summary=SimpleNamespace(
                complete_monthly_cost=D("200"),
            ),
        )

        self.repository = Mock()
        self.spot_service = Mock()

        self.engine = PricingComparisonEngine(
            repository=self.repository,
            spot_service=self.spot_service,
        )

        self.compute = ComputeWorkload(
            baseline=PricingOption(
                scope=ComparisonScope(
                    baseline_estimate_id=self.estimate_id,
                    resource_id=self.resource_id,
                    components=("compute",),
                ),
                name="On-Demand",
                pricing_model=PricingModel.ON_DEMAND,
                status=EstimateStatus.COMPLETE,
                known_monthly_cost=D("140.16"),
                sources=(
                    PricingSource.FLOCI_PRICING_API,
                ),
            ),
            instance_type="m5.large",
            region="us-east-1",
            quantity=2,
            monthly_hours=D("730"),
            on_demand_rate=D("0.096"),
        )

        self.reserved = ReservedAssumptions(
            reserved_quantity=1,
            hourly_recurring_rate=D("0.03"),
            upfront_per_instance=D("120"),
        )

        self.savings_plan = SavingsPlanAssumptions(
            hourly_commitment=D("0.06"),
            discounted_hourly_rate=D("0.06"),
        )

        self.storage = StorageWorkload(
            baseline=PricingOption(
                scope=ComparisonScope(
                    baseline_estimate_id=self.estimate_id,
                    resource_id=self.resource_id,
                    components=STORAGE_COMPONENTS,
                ),
                name="S3 Standard",
                pricing_model=PricingModel.ON_DEMAND,
                status=EstimateStatus.COMPLETE,
                known_monthly_cost=D("11.50"),
                sources=(
                    PricingSource.FLOCI_PRICING_API,
                ),
                exclusions=STORAGE_EXCLUSIONS,
            ),
            region="us-east-1",
            quantity=1,
            storage_gb=D("500"),
            put_requests=D("0"),
            get_requests=D("0"),
            transfer_out_gb=D("0"),
            retrieval_gb=D("0"),
        )

        self.storage_rates = StorageRateAssumptions(
            storage_class="Standard - Infrequent Access",
            storage_per_gb_month=D("0.0125"),
        )

    def observation(
        self,
        zone="us-east-1a",
        rate="0.0128",
        day=26,
    ):

        return SpotPriceObservation(
            instance_type="m5.large",
            region="us-east-1",
            availability_zone=zone,
            product_description="Linux/UNIX",
            unit_price=D(rate),
            observed_at=datetime(
                2026, 11, day,
                tzinfo=timezone.utc,
            ),
            retrieved_at=datetime(
                2026, 11, 27,
                tzinfo=timezone.utc,
            ),
        )

    def compare_compute(self, **kwargs):

        with patch(
            "finops.comparison.engine.build_compute_workload",
            return_value=self.compute,
        ):

            return self.engine.compare_compute(
                self.estimate,
                self.resource_id,
                **kwargs,
            )

    def compare_storage(self, alternatives):

        with patch(
            "finops.comparison.engine.build_storage_workload",
            return_value=self.storage,
        ):

            return self.engine.compare_storage(
                self.estimate,
                self.resource_id,
                retrieval_gb=D("0"),
                alternatives=alternatives,
            )

    def test_repository_delegation(self):

        self.repository.list_estimates.return_value = (
            self.estimate,
        )

        self.repository.load.return_value = self.estimate

        self.assertEqual(
            self.engine.list_estimates(),
            (self.estimate,),
        )

        self.assertIs(
            self.engine.load_estimate(self.estimate_id),
            self.estimate,
        )

        self.repository.list_estimates.assert_called_once_with(
            None
        )

        self.repository.load.assert_called_once_with(
            self.estimate_id
        )

        self.spot_service.refresh.assert_not_called()

    def test_baseline_only_comparison(self):

        report = self.compare_compute(
            include_spot=False,
        )

        self.assertEqual(
            report.baseline,
            self.compute.baseline,
        )

        self.assertEqual(
            report.entries,
            (),
        )

        self.assertEqual(
            report.infrastructure_baseline_monthly_cost,
            D("200"),
        )

        self.spot_service.refresh.assert_not_called()

    def test_commitment_comparisons_and_projections(self):

        report = self.compare_compute(
            reserved=self.reserved,
            savings_plan=self.savings_plan,
            include_spot=False,
        )

        reserved, savings_plan = report.entries

        self.assertEqual(
            reserved.comparison.alternative.complete_monthly_cost,
            D("101.98"),
        )

        self.assertEqual(
            reserved.infrastructure_monthly_cost,
            D("161.82"),
        )

        self.assertEqual(
            reserved.infrastructure_annual_cost,
            D("1941.84"),
        )

        self.assertEqual(
            savings_plan.infrastructure_monthly_cost,
            D("173.72"),
        )

        self.assertEqual(
            len(report.comparable_entries),
            2,
        )

        self.assertEqual(
            report.incomplete_entries,
            (),
        )

        self.spot_service.refresh.assert_not_called()

    def test_partial_infrastructure_blocks_full_projection(self):

        self.estimate.summary.complete_monthly_cost = None

        report = self.compare_compute(
            reserved=self.reserved,
            include_spot=False,
        )

        entry = report.entries[0]

        self.assertEqual(
            entry.comparison.monthly_savings,
            D("38.18"),
        )

        self.assertIsNone(
            entry.infrastructure_monthly_cost
        )

        self.assertIsNone(
            report.infrastructure_baseline_annual_cost
        )

    def test_spot_selects_latest_matching_observation_per_zone(self):

        self.spot_service.refresh.return_value = SimpleNamespace(
            observations=(
                self.observation(
                    rate="0.01",
                    day=25,
                ),
                self.observation(
                    rate="0.0128",
                    day=26,
                ),
                self.observation(
                    zone="us-east-1b",
                    rate="0.015",
                ),
                replace(
                    self.observation(),
                    instance_type="t3.micro",
                ),
            ),
        )

        report = self.compare_compute()

        self.assertEqual(
            len(report.entries),
            2,
        )

        first, second = report.entries

        self.assertEqual(
            first.comparison.alternative.name,
            "Spot - us-east-1a",
        )

        self.assertEqual(
            first.comparison.alternative.complete_monthly_cost,
            D("18.688"),
        )

        self.assertEqual(
            second.comparison.alternative.complete_monthly_cost,
            D("21.90"),
        )

        self.spot_service.refresh.assert_called_once()

    def test_spot_zone_selection(self):

        self.spot_service.refresh.return_value = SimpleNamespace(
            observations=(
                self.observation(),
                self.observation(
                    zone="us-east-1b",
                ),
            ),
        )

        report = self.compare_compute(
            availability_zone="us-east-1b",
        )

        self.assertEqual(
            len(report.entries),
            1,
        )

        self.assertEqual(
            report.entries[0].comparison.alternative.name,
            "Spot - us-east-1b",
        )

        query = (
            self.spot_service.refresh.call_args.args[0]
        )

        self.assertEqual(
            query.availability_zone,
            "us-east-1b",
        )

    def test_spot_failure_preserves_commitment_comparison(self):

        self.spot_service.refresh.side_effect = RuntimeError(
            "Simulated provider failure."
        )

        report = self.compare_compute(
            reserved=self.reserved,
        )

        self.assertEqual(
            len(report.comparable_entries),
            1,
        )

        self.assertEqual(
            len(report.incomplete_entries),
            1,
        )

        unavailable = report.incomplete_entries[0]

        self.assertEqual(
            unavailable.comparison.alternative.status,
            EstimateStatus.UNAVAILABLE,
        )

        self.assertIsNone(
            unavailable.comparison.monthly_savings
        )

        self.assertIsNone(
            unavailable.infrastructure_monthly_cost
        )

        self.assertIn(
            "retrieval failed",
            unavailable.comparison.alternative.detail,
        )

    def test_empty_spot_result_is_unavailable(self):

        self.spot_service.refresh.return_value = SimpleNamespace(
            observations=(),
        )

        report = self.compare_compute()

        self.assertEqual(
            len(report.entries),
            1,
        )

        self.assertEqual(
            report.entries[0].comparison.alternative.status,
            EstimateStatus.UNAVAILABLE,
        )

        self.assertIsNone(
            report.entries[0].comparison.savings_percentage
        )

    def test_storage_projection_and_missing_pricing(self):

        incomplete = StorageRateAssumptions(
            storage_class="Glacier Deep Archive",
        )

        report = self.compare_storage(
            (
                self.storage_rates,
                incomplete,
            )
        )

        complete_entry, incomplete_entry = report.entries

        self.assertEqual(
            complete_entry.comparison.monthly_savings,
            D("5.25"),
        )

        self.assertEqual(
            complete_entry.infrastructure_monthly_cost,
            D("194.75"),
        )

        self.assertIsNone(
            incomplete_entry.infrastructure_monthly_cost
        )

        self.assertIsNone(
            incomplete_entry.comparison.monthly_savings
        )

        self.spot_service.refresh.assert_not_called()

    def test_duplicate_storage_alternatives_are_rejected(self):

        with self.assertRaises(ValueError):

            self.compare_storage(
                (
                    self.storage_rates,
                    self.storage_rates,
                )
            )

    def test_resource_eligibility(self):

        resources = tuple(
            SimpleNamespace(
                resource_id=uuid4(),
                name=resource_type.value,
                resource_type=resource_type,
                region="us-east-1",
            )
            for resource_type in (
                ResourceType.EC2_INSTANCE,
                ResourceType.S3_BUCKET,
                ResourceType.EBS_VOLUME,
            )
        )

        self.estimate.scenario = SimpleNamespace(
            resources=resources,
        )

        with (
            patch(
                "finops.comparison.engine.build_compute_workload",
                return_value=self.compute,
            ),
            patch(
                "finops.comparison.engine.build_storage_workload",
                side_effect=ValueError(
                    "Incomplete historical storage baseline."
                ),
            ),
        ):

            results = self.engine.eligible_resources(
                self.estimate
            )

        self.assertTrue(results[0].eligible)
        self.assertFalse(results[1].eligible)
        self.assertFalse(results[2].eligible)

        self.assertIn(
            "Incomplete",
            results[1].reason,
        )

        self.spot_service.refresh.assert_not_called()

    def test_inconsistent_infrastructure_total_is_rejected(self):

        self.estimate.summary.complete_monthly_cost = D("100")

        with self.assertRaises(ValueError):

            self.compare_compute(
                reserved=self.reserved,
                include_spot=False,
            )


if __name__ == "__main__":
    unittest.main()
