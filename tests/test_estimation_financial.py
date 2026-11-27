"""Verify financial arithmetic and incomplete pricing coverage."""

import unittest

from decimal import Decimal
from uuid import uuid4

from finops.estimation.financial import (
    ComponentEstimate,
    CostStatus,
    EstimateStatus,
    calculate_period_costs,
    calculate_tier_charge,
    format_usd,
    summarize_components,
)

from finops.pricing.models import PriceDimension


D = Decimal


def tier(rate, begin="0", end=None, code="tier-1", unit="Hrs"):

    return PriceDimension(
        rate_code=code,
        unit=unit,
        currency="USD",
        unit_price=D(rate),
        begin_range=D(begin),
        end_range=None if end is None else D(end),
        cost_component="compute",
    )


def component(
    status=CostStatus.PRICED,
    usage=D("730"),
    priced_usage=D("730"),
    cost=D("7.592"),
):

    return ComponentEstimate(
        resource_id=uuid4(),
        component="compute",
        unit="Hrs",
        status=status,
        usage=usage,
        priced_usage=priced_usage,
        known_monthly_cost=cost,
    )


class FinancialCalculationTests(unittest.TestCase):

    def test_single_rate_with_resource_quantity(self):

        usage = D("3") * D("730")

        result = calculate_tier_charge(
            usage,
            [tier("0.0104")],
        )

        self.assertEqual(result.known_cost, D("22.776"))
        self.assertEqual(result.total_cost, D("22.776"))
        self.assertEqual(result.unpriced_usage, D("0"))
        self.assertEqual(result.status, CostStatus.PRICED)

    def test_graduated_pricing_tiers(self):

        result = calculate_tier_charge(
            D("150"),
            [
                tier("0.10", "0", "100", "first"),
                tier("0.05", "100", None, "second"),
            ],
        )

        self.assertEqual(result.total_cost, D("12.50"))
        self.assertEqual(result.priced_usage, D("150"))

        boundary = calculate_tier_charge(
            D("100"),
            [
                tier("0.10", "0", "100", "first"),
                tier("0.05", "100", None, "second"),
            ],
        )

        self.assertEqual(boundary.total_cost, D("10"))

    def test_bounded_s3_coverage_is_partial(self):

        result = calculate_tier_charge(
            D("60000"),
            [
                tier(
                    "0.023",
                    "0",
                    "51200",
                    unit="GB-Mo",
                )
            ],
        )

        self.assertEqual(result.known_cost, D("1177.600"))
        self.assertEqual(result.priced_usage, D("51200"))
        self.assertEqual(result.unpriced_usage, D("8800"))
        self.assertEqual(result.status, CostStatus.PARTIAL)
        self.assertIsNone(result.total_cost)

    def test_gaps_are_not_silently_priced(self):

        result = calculate_tier_charge(
            D("250"),
            [
                tier("0.10", "0", "100", "first"),
                tier("0.05", "200", None, "second"),
            ],
        )

        self.assertEqual(result.priced_usage, D("150"))
        self.assertEqual(result.unpriced_usage, D("100"))
        self.assertEqual(result.known_cost, D("12.50"))
        self.assertIsNone(result.total_cost)

    def test_overlaps_and_incompatible_units_are_rejected(self):

        cases = (
            [
                tier("0.10", "0", "100", "first"),
                tier("0.05", "90", None, "second"),
            ],
            [
                tier("0.10", "0", "100", "first"),
                tier(
                    "0.05",
                    "100",
                    None,
                    "second",
                    unit="GB-Mo",
                ),
            ],
        )

        for dimensions in cases:

            with self.subTest(dimensions=dimensions):

                with self.assertRaises(ValueError):
                    calculate_tier_charge(
                        D("150"),
                        dimensions,
                    )

    def test_zero_usage_and_missing_rates_are_distinct(self):

        zero = calculate_tier_charge(D("0"), ())
        missing = calculate_tier_charge(D("10"), ())

        self.assertEqual(
            zero.status,
            CostStatus.ZERO_USAGE,
        )

        self.assertEqual(zero.total_cost, D("0"))

        self.assertEqual(
            missing.status,
            CostStatus.UNRESOLVED,
        )

        self.assertIsNone(missing.total_cost)
        self.assertEqual(missing.unpriced_usage, D("10"))

    def test_complete_summary_preserves_unrounded_values(self):

        first = component(cost=D("22.776"))
        second = component(cost=D("11.50"))

        zero = component(
            status=CostStatus.ZERO_USAGE,
            usage=D("0"),
            priced_usage=D("0"),
            cost=D("0"),
        )

        result = summarize_components(
            [first, second, zero]
        )

        self.assertEqual(
            result.status,
            EstimateStatus.COMPLETE,
        )

        self.assertEqual(
            result.complete_monthly_cost,
            D("34.276"),
        )

        self.assertEqual(
            result.complete_period_costs.annual,
            D("411.312"),
        )

    def test_partial_summary_never_claims_complete_total(self):

        priced = component(cost=D("22.776"))

        missing = component(
            status=CostStatus.UNRESOLVED,
            usage=None,
            priced_usage=D("0"),
            cost=D("0"),
        )

        partial = component(
            status=CostStatus.PARTIAL,
            usage=D("60000"),
            priced_usage=D("51200"),
            cost=D("1177.6"),
        )

        result = summarize_components(
            [priced, missing, partial]
        )

        self.assertEqual(
            result.status,
            EstimateStatus.PARTIAL,
        )

        self.assertEqual(
            result.known_monthly_cost,
            D("1200.376"),
        )

        self.assertIsNone(result.complete_monthly_cost)
        self.assertIsNone(result.complete_period_costs)
        self.assertEqual(result.unresolved_components, 1)
        self.assertEqual(result.partial_components, 1)

    def test_unavailable_and_excluded_components(self):

        missing = component(
            status=CostStatus.UNRESOLVED,
            usage=None,
            priced_usage=D("0"),
            cost=D("0"),
        )

        excluded = component(
            status=CostStatus.EXCLUDED,
            usage=None,
            priced_usage=D("0"),
            cost=D("0"),
        )

        for items in ((), (missing,), (excluded,), (missing, excluded)):

            with self.subTest(items=items):

                result = summarize_components(items)

                self.assertEqual(
                    result.status,
                    EstimateStatus.UNAVAILABLE,
                )

                self.assertIsNone(
                    result.complete_monthly_cost
                )

        result = summarize_components(
            [component(), excluded]
        )

        self.assertEqual(
            result.status,
            EstimateStatus.COMPLETE,
        )

        self.assertEqual(result.excluded_components, 1)

    def test_invalid_and_duplicate_components_are_rejected(self):

        with self.assertRaises(ValueError):

            component(
                status=CostStatus.UNRESOLVED,
                usage=None,
                priced_usage=D("0"),
                cost=D("1"),
            )

        with self.assertRaises(ValueError):

            component(
                usage=D("730"),
                priced_usage=D("731"),
            )

        original = component()

        with self.assertRaises(ValueError):
            summarize_components([original, original])

    def test_period_conversions_and_display_rounding(self):

        periods = calculate_period_costs(D("22.776"))

        self.assertEqual(
            periods.average_hourly,
            D("0.0312"),
        )

        self.assertEqual(periods.daily, D("0.7488"))
        self.assertEqual(periods.monthly, D("22.776"))
        self.assertEqual(periods.annual, D("273.312"))

        self.assertEqual(format_usd(D("22.776")), "$22.78")
        self.assertEqual(format_usd(D("0.005")), "$0.01")

        for invalid in (D("-1"), D("NaN"), D("Infinity"), 1.5):

            with self.subTest(invalid=invalid):

                with self.assertRaises(ValueError):
                    calculate_period_costs(invalid)


if __name__ == "__main__":
    unittest.main()
