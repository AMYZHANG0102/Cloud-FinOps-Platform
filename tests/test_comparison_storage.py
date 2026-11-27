"""Verify equivalent-workload storage pricing comparisons."""

import unittest

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

from finops.comparison.models import (
    ComparisonScope,
    PricingOption,
)

from finops.comparison.storage import (
    STORAGE_ASSUMPTIONS,
    STORAGE_CLASSES,
    STORAGE_COMPONENTS,
    STORAGE_EXCLUSIONS,
    StorageRateAssumptions,
    StorageWorkload,
    evaluate_storage,
)

from finops.estimation.financial import (
    CostStatus,
    EstimateStatus,
)

from finops.pricing.models import (
    PricingModel,
    PricingSource,
)


D = Decimal


class StorageComparisonTests(unittest.TestCase):

    def workload(self):

        return StorageWorkload(
            baseline=PricingOption(
                scope=ComparisonScope(
                    baseline_estimate_id=uuid4(),
                    resource_id=uuid4(),
                    components=STORAGE_COMPONENTS,
                ),
                name="S3 Standard",
                pricing_model=PricingModel.ON_DEMAND,
                status=EstimateStatus.COMPLETE,
                known_monthly_cost=D("11.50"),
                sources=(
                    PricingSource.FLOCI_PRICING_API,
                ),
                assumptions=STORAGE_ASSUMPTIONS,
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

    def active_workload(self):

        workload = self.workload()

        return replace(
            workload,
            baseline=replace(
                workload.baseline,
                known_monthly_cost=D("13.314"),
            ),
            put_requests=D("2000"),
            get_requests=D("10000"),
            transfer_out_gb=D("20"),
            retrieval_gb=D("100"),
        )

    def rates(self):

        return StorageRateAssumptions(
            storage_class="Standard - Infrequent Access",
            storage_per_gb_month=D("0.0125"),
            put_per_thousand=D("0.01"),
            get_per_thousand=D("0.001"),
            transfer_per_gb=D("0.09"),
            retrieval_per_gb=D("0.01"),
        )

    def test_storage_only_comparison(self):

        result = evaluate_storage(
            self.workload(),
            StorageRateAssumptions(
                storage_class="Standard - Infrequent Access",
                storage_per_gb_month=D("0.0125"),
            ),
        )

        self.assertEqual(
            result.complete_monthly_cost,
            D("6.25"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("5.25"),
        )

        self.assertEqual(
            result.comparison.annual_savings,
            D("63"),
        )

        self.assertEqual(
            result.unresolved_components,
            (),
        )

    def test_requests_retrieval_and_transfer_are_included(self):

        result = evaluate_storage(
            self.active_workload(),
            self.rates(),
        )

        charges = {
            item.component: item.monthly_cost
            for item in result.charges
        }

        self.assertEqual(
            charges["storage"],
            D("6.25"),
        )

        self.assertEqual(
            charges["put_requests"],
            D("0.02"),
        )

        self.assertEqual(
            charges["get_requests"],
            D("0.01"),
        )

        self.assertEqual(
            charges["retrieval"],
            D("1"),
        )

        self.assertEqual(
            charges["transfer_out"],
            D("1.80"),
        )

        self.assertEqual(
            result.complete_monthly_cost,
            D("9.08"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("4.234"),
        )

    def test_heavy_retrieval_can_eliminate_savings(self):

        workload = replace(
            self.active_workload(),
            retrieval_gb=D("600"),
        )

        result = evaluate_storage(
            workload,
            self.rates(),
        )

        self.assertEqual(
            result.complete_monthly_cost,
            D("14.08"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("-0.766"),
        )

        self.assertFalse(
            result.comparison.is_cheaper
        )

    def test_missing_retrieval_rate_blocks_complete_savings(self):

        result = evaluate_storage(
            self.active_workload(),
            replace(
                self.rates(),
                retrieval_per_gb=None,
            ),
        )

        self.assertEqual(
            result.comparison.alternative.status,
            EstimateStatus.PARTIAL,
        )

        self.assertEqual(
            result.known_monthly_cost,
            D("8.08"),
        )

        self.assertIsNone(
            result.complete_monthly_cost
        )

        self.assertIsNone(
            result.comparison.monthly_savings
        )

        self.assertEqual(
            result.unresolved_components,
            ("retrieval",),
        )

    def test_zero_usage_does_not_require_pricing(self):

        workload = self.workload()

        workload = replace(
            workload,
            baseline=replace(
                workload.baseline,
                known_monthly_cost=D("0"),
                sources=(),
            ),
            storage_gb=D("0"),
        )

        result = evaluate_storage(
            workload,
            StorageRateAssumptions(
                storage_class="Glacier Deep Archive",
            ),
        )

        self.assertEqual(
            result.complete_monthly_cost,
            D("0"),
        )

        self.assertIsNone(
            result.comparison.savings_percentage
        )

        self.assertTrue(
            all(
                item.status == CostStatus.ZERO_USAGE
                for item in result.charges
            )
        )

    def test_all_positive_usage_without_rates_is_unavailable(self):

        result = evaluate_storage(
            self.active_workload(),
            StorageRateAssumptions(
                storage_class="Standard - Infrequent Access",
            ),
        )

        self.assertEqual(
            result.comparison.alternative.status,
            EstimateStatus.UNAVAILABLE,
        )

        self.assertEqual(
            result.known_monthly_cost,
            D("0"),
        )

        self.assertEqual(
            len(result.unresolved_components),
            5,
        )

        self.assertIsNone(
            result.complete_monthly_cost
        )

    def test_explicit_zero_rate_is_not_missing_pricing(self):

        result = evaluate_storage(
            self.active_workload(),
            replace(
                self.rates(),
                retrieval_per_gb=D("0"),
            ),
        )

        retrieval = next(
            item
            for item in result.charges
            if item.component == "retrieval"
        )

        self.assertEqual(
            retrieval.status,
            CostStatus.PRICED,
        )

        self.assertEqual(
            retrieval.monthly_cost,
            D("0"),
        )

        self.assertEqual(
            result.complete_monthly_cost,
            D("8.08"),
        )

    def test_invalid_storage_rates_are_rejected(self):

        for amount in (
            D("-1"),
            D("NaN"),
            D("Infinity"),
            0.01,
        ):

            with self.subTest(amount=amount):

                with self.assertRaises(ValueError):

                    replace(
                        self.rates(),
                        storage_per_gb_month=amount,
                    )

        with self.assertRaises(ValueError):

            replace(
                self.rates(),
                storage_class="Unsupported class",
            )

    def test_invalid_storage_workload_is_rejected(self):

        workload = self.workload()

        for values in (
            {"storage_gb": D("-1")},
            {"get_requests": D("0.5")},
            {"put_requests": D("NaN")},
            {"quantity": 0},
            {"retrieval_gb": D("100")},
        ):

            with self.subTest(values=values):

                with self.assertRaises(ValueError):

                    replace(
                        workload,
                        **values,
                    )

    def test_incomplete_or_mismatched_baseline_is_rejected(self):

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
                baseline=replace(
                    workload.baseline,
                    scope=replace(
                        workload.baseline.scope,
                        components=("storage",),
                    ),
                ),
            )

    def test_storage_classes_preserve_scope_and_provenance(self):

        workload = self.workload()

        for storage_class in STORAGE_CLASSES:

            with self.subTest(storage_class=storage_class):

                result = evaluate_storage(
                    workload,
                    replace(
                        self.rates(),
                        storage_class=storage_class,
                    ),
                )

                alternative = (
                    result.comparison.alternative
                )

                self.assertEqual(
                    alternative.scope,
                    workload.baseline.scope,
                )

                self.assertEqual(
                    alternative.exclusions,
                    workload.baseline.exclusions,
                )

                self.assertEqual(
                    alternative.sources,
                    (
                        PricingSource.ESTIMATION_ASSUMPTION,
                    ),
                )

                self.assertTrue(
                    result.comparison.uses_assumptions
                )

                self.assertTrue(
                    alternative.detail
                )

    def test_request_rates_preserve_fractional_charge_precision(self):

        workload = replace(
            self.workload(),
            put_requests=D("1"),
            get_requests=D("3"),
        )

        result = evaluate_storage(
            workload,
            self.rates(),
        )

        self.assertEqual(
            result.complete_monthly_cost,
            D("6.250013"),
        )

        self.assertEqual(
            result.comparison.monthly_savings,
            D("5.249987"),
        )


if __name__ == "__main__":
    unittest.main()
