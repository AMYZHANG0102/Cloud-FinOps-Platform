"""Verify equivalent-scope pricing comparisons and savings arithmetic."""

import unittest

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

from finops.comparison.models import (
    ComparisonScope,
    PricingComparison,
    PricingOption,
    format_percentage,
    format_signed_usd,
)

from finops.estimation.financial import EstimateStatus

from finops.pricing.models import (
    PricingModel,
    PricingSource,
)


D = Decimal


class PricingComparisonTests(unittest.TestCase):

    def setUp(self):

        self.scope = ComparisonScope(
            baseline_estimate_id=uuid4(),
            resource_id=uuid4(),
            components=("compute",),
        )

        self.baseline = PricingOption(
            scope=self.scope,
            name="On-Demand",
            pricing_model=PricingModel.ON_DEMAND,
            status=EstimateStatus.COMPLETE,
            known_monthly_cost=D("22.776"),
            sources=(PricingSource.FLOCI_PRICING_API,),
            exclusions=("Taxes and credits",),
        )

        self.alternative = PricingOption(
            scope=self.scope,
            name="Illustrative Reserved Instance",
            pricing_model=PricingModel.RESERVED,
            status=EstimateStatus.COMPLETE,
            known_monthly_cost=D("15"),
            sources=(PricingSource.ESTIMATION_ASSUMPTION,),
            assumptions=(
                "Illustrative commitment pricing.",
            ),
            exclusions=("Taxes and credits",),
        )

    def test_positive_savings(self):

        result = PricingComparison(
            self.baseline,
            self.alternative,
        )

        self.assertTrue(result.is_comparable)
        self.assertTrue(result.is_cheaper)

        self.assertEqual(
            result.monthly_savings,
            D("7.776"),
        )

        self.assertEqual(
            result.annual_savings,
            D("93.312"),
        )

        self.assertEqual(
            format_percentage(
                result.savings_percentage
            ),
            "34.14%",
        )

    def test_negative_savings_are_preserved(self):

        alternative = replace(
            self.alternative,
            known_monthly_cost=D("30"),
        )

        result = PricingComparison(
            self.baseline,
            alternative,
        )

        self.assertEqual(
            result.monthly_savings,
            D("-7.224"),
        )

        self.assertEqual(
            result.annual_savings,
            D("-86.688"),
        )

        self.assertLess(
            result.savings_percentage,
            D("0"),
        )

        self.assertFalse(result.is_cheaper)

    def test_equal_costs(self):

        alternative = replace(
            self.alternative,
            known_monthly_cost=D("22.776"),
        )

        result = PricingComparison(
            self.baseline,
            alternative,
        )

        self.assertEqual(
            result.monthly_savings,
            D("0"),
        )

        self.assertEqual(
            result.savings_percentage,
            D("0"),
        )

        self.assertFalse(result.is_cheaper)

    def test_zero_baseline_has_no_percentage(self):

        baseline = replace(
            self.baseline,
            known_monthly_cost=D("0"),
            sources=(),
        )

        result = PricingComparison(
            baseline,
            self.alternative,
        )

        self.assertTrue(result.is_comparable)

        self.assertEqual(
            result.monthly_savings,
            D("-15"),
        )

        self.assertIsNone(
            result.savings_percentage
        )

    def test_incomplete_alternative_has_no_definitive_savings(self):

        for status in (
            EstimateStatus.PARTIAL,
            EstimateStatus.UNAVAILABLE,
        ):

            with self.subTest(status=status):

                alternative = replace(
                    self.alternative,
                    status=status,
                    known_monthly_cost=(
                        D("5")
                        if status == EstimateStatus.PARTIAL
                        else D("0")
                    ),
                )

                result = PricingComparison(
                    self.baseline,
                    alternative,
                )

                self.assertFalse(result.is_comparable)
                self.assertIsNone(result.monthly_savings)
                self.assertIsNone(result.annual_savings)
                self.assertIsNone(result.savings_percentage)
                self.assertIsNone(result.is_cheaper)

    def test_incomplete_baseline_has_no_definitive_savings(self):

        baseline = replace(
            self.baseline,
            status=EstimateStatus.PARTIAL,
        )

        result = PricingComparison(
            baseline,
            self.alternative,
        )

        self.assertFalse(result.is_comparable)
        self.assertIsNone(result.monthly_savings)

    def test_mismatched_comparison_scope_is_rejected(self):

        for scope in (
            replace(
                self.scope,
                baseline_estimate_id=uuid4(),
            ),
            replace(
                self.scope,
                resource_id=uuid4(),
            ),
            replace(
                self.scope,
                components=("storage",),
            ),
        ):

            with self.subTest(scope=scope):

                with self.assertRaises(ValueError):

                    PricingComparison(
                        self.baseline,
                        replace(
                            self.alternative,
                            scope=scope,
                        ),
                    )

    def test_component_scope_order_is_normalized(self):

        first = replace(
            self.scope,
            components=("storage", "compute"),
        )

        second = replace(
            self.scope,
            components=("compute", "storage"),
        )

        self.assertEqual(first, second)

        for components in (
            (),
            ("compute", "compute"),
        ):

            with self.assertRaises(ValueError):

                replace(
                    self.scope,
                    components=components,
                )

    def test_assumption_provenance_is_required(self):

        with self.assertRaises(ValueError):

            replace(
                self.alternative,
                assumptions=(),
            )

        with self.assertRaises(ValueError):

            replace(
                self.alternative,
                sources=(),
            )

        result = PricingComparison(
            self.baseline,
            self.alternative,
        )

        self.assertTrue(result.uses_assumptions)

    def test_invalid_financial_values_are_rejected(self):

        for amount in (
            D("-1"),
            D("NaN"),
            D("Infinity"),
            1.5,
        ):

            with self.subTest(amount=amount):

                with self.assertRaises(ValueError):

                    replace(
                        self.baseline,
                        known_monthly_cost=amount,
                    )

        with self.assertRaises(ValueError):

            replace(
                self.baseline,
                status=EstimateStatus.UNAVAILABLE,
            )

    def test_baseline_model_and_exclusions_are_enforced(self):

        with self.assertRaises(ValueError):

            PricingComparison(
                replace(
                    self.baseline,
                    pricing_model=PricingModel.SPOT,
                ),
                self.alternative,
            )

        with self.assertRaises(ValueError):

            PricingComparison(
                self.baseline,
                replace(
                    self.alternative,
                    exclusions=(),
                ),
            )

    def test_period_costs_and_signed_presentation(self):

        periods = self.baseline.complete_period_costs

        self.assertEqual(
            periods.annual,
            D("273.312"),
        )

        self.assertEqual(
            periods.average_hourly,
            D("0.0312"),
        )

        self.assertEqual(
            format_signed_usd(D("-7.224")),
            "-$7.22",
        )

        self.assertEqual(
            format_signed_usd(D("7.776")),
            "$7.78",
        )

        self.assertEqual(
            format_signed_usd(D("-0.001")),
            "$0.00",
        )

        self.assertEqual(
            format_signed_usd(None),
            "Unavailable",
        )

        self.assertEqual(
            format_percentage(None),
            "Unavailable",
        )

        self.assertEqual(
            format_percentage(D("-25.123")),
            "-25.12%",
        )


if __name__ == "__main__":
    unittest.main()
