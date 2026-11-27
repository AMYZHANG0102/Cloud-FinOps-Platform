"""Verify compute purchasing models and commitment expenditure."""

import unittest

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from finops.comparison.compute import (
    COMPUTE_ASSUMPTIONS,
    COMPUTE_EXCLUSIONS,
    ComputeWorkload,
    ReservedAssumptions,
    SavingsPlanAssumptions,
    evaluate_reserved,
    evaluate_savings_plan,
    evaluate_spot,
)

from finops.comparison.models import (
    ComparisonScope,
    PricingOption,
)

from finops.estimation.financial import EstimateStatus

from finops.pricing.models import (
    PricingModel,
    PricingSource,
    SpotPriceObservation,
)


D = Decimal


class ComputeComparisonTests(unittest.TestCase):

    def workload(
        self,
        quantity=2,
        hours="730",
        rate="0.096",
    ):

        hours = D(hours)
        rate = D(rate)

        scope = ComparisonScope(
            baseline_estimate_id=uuid4(),
            resource_id=uuid4(),
            components=("compute",),
        )

        baseline = PricingOption(
            scope=scope,
            name="On-Demand",
            pricing_model=PricingModel.ON_DEMAND,
            status=EstimateStatus.COMPLETE,
            known_monthly_cost=(
                D(quantity) * hours * rate
            ),
            sources=(PricingSource.FLOCI_PRICING_API,),
            assumptions=COMPUTE_ASSUMPTIONS,
            exclusions=COMPUTE_EXCLUSIONS,
        )

        return ComputeWorkload(
            baseline=baseline,
            instance_type="m5.large",
            region="us-east-1",
            quantity=quantity,
            monthly_hours=hours,
            on_demand_rate=rate,
        )

    def observation(self):

        return SpotPriceObservation(
            instance_type="m5.large",
            region="us-east-1",
            availability_zone="us-east-1a",
            product_description="Linux/UNIX",
            unit_price=D("0.0128"),
            observed_at=datetime(
                2026, 11, 27,
                tzinfo=timezone.utc,
            ),
            retrieved_at=datetime(
                2026, 11, 27,
                1,
                tzinfo=timezone.utc,
            ),
        )

    def test_on_demand_baseline_reconciliation(self):

        workload = self.workload()

        self.assertEqual(
            workload.total_instance_hours,
            D("1460"),
        )

        self.assertEqual(
            workload.baseline.complete_monthly_cost,
            D("140.16"),
        )

        with self.assertRaises(ValueError):

            replace(
                workload,
                on_demand_rate=D("0.10"),
            )

    def test_reserved_full_coverage_and_upfront_amortization(self):

        result = evaluate_reserved(
            self.workload(quantity=1),
            ReservedAssumptions(
                reserved_quantity=1,
                hourly_recurring_rate=D("0.03"),
                upfront_per_instance=D("120"),
                term_months=12,
            ),
        )

        self.assertEqual(
            result.covered_instance_hours,
            D("730"),
        )

        self.assertEqual(
            result.monthly_upfront_amortization,
            D("10"),
        )

        self.assertEqual(
            result.monthly_commitment_charge,
            D("21.90"),
        )

        self.assertEqual(
            result.monthly_total,
            D("31.90"),
        )

        self.assertEqual(
            result.modeled_term_cost,
            D("382.80"),
        )

        self.assertEqual(
            result.unused_reserved_hours,
            D("0"),
        )

    def test_reserved_partial_coverage(self):

        result = evaluate_reserved(
            self.workload(),
            ReservedAssumptions(
                reserved_quantity=1,
                hourly_recurring_rate=D("0.03"),
                upfront_per_instance=D("120"),
            ),
        )

        self.assertEqual(
            result.covered_instance_hours,
            D("730"),
        )

        self.assertEqual(
            result.uncovered_on_demand_hours,
            D("730"),
        )

        self.assertEqual(
            result.monthly_on_demand_charge,
            D("70.08"),
        )

        self.assertEqual(
            result.monthly_total,
            D("101.98"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("38.18"),
        )

        self.assertIn(
            PricingSource.FLOCI_PRICING_API,
            result.comparison.alternative.sources,
        )

    def test_reserved_underutilization(self):

        result = evaluate_reserved(
            self.workload(quantity=1, hours="100"),
            ReservedAssumptions(
                reserved_quantity=1,
                hourly_recurring_rate=D("0.03"),
                upfront_per_instance=D("120"),
            ),
        )

        self.assertEqual(
            result.unused_reserved_hours,
            D("630"),
        )

        self.assertEqual(
            result.monthly_total,
            D("31.90"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("-22.30"),
        )

    def test_reserved_overcommitment(self):

        result = evaluate_reserved(
            self.workload(quantity=1),
            ReservedAssumptions(
                reserved_quantity=2,
                hourly_recurring_rate=D("0.03"),
            ),
        )

        self.assertEqual(
            result.unused_reserved_hours,
            D("730"),
        )

        self.assertEqual(
            result.monthly_total,
            D("43.80"),
        )

    def test_reserved_zero_usage_still_incurs_commitment(self):

        result = evaluate_reserved(
            self.workload(quantity=1, hours="0"),
            ReservedAssumptions(
                reserved_quantity=1,
                hourly_recurring_rate=D("0.03"),
                upfront_per_instance=D("120"),
            ),
        )

        self.assertEqual(
            result.monthly_total,
            D("31.90"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("-31.90"),
        )

        self.assertIsNone(
            result.comparison.savings_percentage
        )

    def test_savings_plan_partial_coverage(self):

        result = evaluate_savings_plan(
            self.workload(),
            SavingsPlanAssumptions(
                hourly_commitment=D("0.06"),
                discounted_hourly_rate=D("0.06"),
            ),
        )

        self.assertEqual(
            result.covered_instance_hours,
            D("730"),
        )

        self.assertEqual(
            result.uncovered_on_demand_hours,
            D("730"),
        )

        self.assertEqual(
            result.monthly_commitment_charge,
            D("43.80"),
        )

        self.assertEqual(
            result.monthly_on_demand_charge,
            D("70.08"),
        )

        self.assertEqual(
            result.monthly_total,
            D("113.88"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("26.28"),
        )

        self.assertEqual(
            result.unused_savings_plan_commitment,
            D("0"),
        )

    def test_savings_plan_full_coverage(self):

        result = evaluate_savings_plan(
            self.workload(),
            SavingsPlanAssumptions(
                hourly_commitment=D("0.12"),
                discounted_hourly_rate=D("0.06"),
            ),
        )

        self.assertEqual(
            result.covered_instance_hours,
            D("1460"),
        )

        self.assertEqual(
            result.uncovered_on_demand_hours,
            D("0"),
        )

        self.assertEqual(
            result.monthly_total,
            D("87.60"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("52.56"),
        )

    def test_savings_plan_idle_hours_do_not_roll_forward(self):

        result = evaluate_savings_plan(
            self.workload(hours="100"),
            SavingsPlanAssumptions(
                hourly_commitment=D("0.06"),
                discounted_hourly_rate=D("0.06"),
            ),
        )

        self.assertEqual(
            result.covered_instance_hours,
            D("100"),
        )

        self.assertEqual(
            result.uncovered_on_demand_hours,
            D("100"),
        )

        self.assertEqual(
            result.unused_savings_plan_commitment,
            D("37.80"),
        )

        self.assertEqual(
            result.monthly_total,
            D("53.40"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("-34.20"),
        )

    def test_savings_plan_excess_commitment(self):

        result = evaluate_savings_plan(
            self.workload(),
            SavingsPlanAssumptions(
                hourly_commitment=D("0.15"),
                discounted_hourly_rate=D("0.06"),
            ),
        )

        self.assertEqual(
            result.monthly_total,
            D("109.50"),
        )

        self.assertEqual(
            result.unused_savings_plan_commitment,
            D("21.90"),
        )

    def test_savings_plan_fractional_coverage(self):

        result = evaluate_savings_plan(
            self.workload(),
            SavingsPlanAssumptions(
                hourly_commitment=D("0.09"),
                discounted_hourly_rate=D("0.06"),
            ),
        )

        self.assertEqual(
            result.covered_instance_hours,
            D("1095"),
        )

        self.assertEqual(
            result.uncovered_on_demand_hours,
            D("365"),
        )

        self.assertEqual(
            result.monthly_total,
            D("100.74"),
        )

    def test_spot_observation_and_financial_comparison(self):

        workload = self.workload(quantity=5)

        result = evaluate_spot(
            workload,
            self.observation(),
        )

        self.assertEqual(
            workload.baseline.complete_monthly_cost,
            D("350.40"),
        )

        self.assertEqual(
            result.monthly_total,
            D("46.72"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("303.68"),
        )

        self.assertEqual(
            result.comparison.alternative.sources,
            (PricingSource.FLOCI_EC2_API,),
        )

        self.assertFalse(
            result.comparison.uses_assumptions
        )

        self.assertIn(
            "us-east-1a",
            result.comparison.alternative.detail,
        )

    def test_mismatched_spot_observation_is_rejected(self):

        observation = self.observation()

        for candidate in (
            replace(
                observation,
                instance_type="t3.micro",
            ),
            replace(
                observation,
                region="us-west-2",
                availability_zone="us-west-2a",
            ),
            replace(
                observation,
                product_description="Windows",
            ),
        ):

            with self.subTest(observation=candidate):

                with self.assertRaises(ValueError):

                    evaluate_spot(
                        self.workload(),
                        candidate,
                    )

    def test_invalid_commitment_inputs(self):

        for quantity in (-1, True, 1.5):

            with self.subTest(quantity=quantity):

                with self.assertRaises(ValueError):

                    ReservedAssumptions(
                        reserved_quantity=quantity,
                        hourly_recurring_rate=D("0.03"),
                    )

        with self.assertRaises(ValueError):

            ReservedAssumptions(
                reserved_quantity=1,
                hourly_recurring_rate=D("-0.03"),
            )

        with self.assertRaises(ValueError):

            ReservedAssumptions(
                reserved_quantity=1,
                hourly_recurring_rate=D("0.03"),
                term_months=6,
            )

        with self.assertRaises(ValueError):

            SavingsPlanAssumptions(
                hourly_commitment=D("0.06"),
                discounted_hourly_rate=D("0"),
            )

        with self.assertRaises(ValueError):

            SavingsPlanAssumptions(
                hourly_commitment=D("NaN"),
                discounted_hourly_rate=D("0.06"),
            )

    def test_incomplete_baseline_and_invalid_runtime(self):

        workload = self.workload()

        with self.assertRaises(ValueError):

            replace(
                workload,
                baseline=replace(
                    workload.baseline,
                    status=EstimateStatus.PARTIAL,
                ),
            )

        with self.assertRaises(ValueError):

            replace(
                workload,
                monthly_hours=D("731"),
            )

    def test_zero_commitment_preserves_on_demand_cost(self):

        workload = self.workload()

        reserved = evaluate_reserved(
            workload,
            ReservedAssumptions(
                reserved_quantity=0,
                hourly_recurring_rate=D("0.03"),
            ),
        )

        savings_plan = evaluate_savings_plan(
            workload,
            SavingsPlanAssumptions(
                hourly_commitment=D("0"),
                discounted_hourly_rate=D("0.06"),
            ),
        )

        for result in (reserved, savings_plan):

            self.assertEqual(
                result.monthly_total,
                workload.baseline.complete_monthly_cost,
            )

            self.assertEqual(
                result.comparison.monthly_savings,
                D("0"),
            )


if __name__ == "__main__":
    unittest.main()
