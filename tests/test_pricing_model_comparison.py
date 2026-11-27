"""Streamlit integration tests for the M5 comparison dashboard."""

import csv
import io
import runpy
import unittest

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from streamlit.testing.v1 import AppTest

from finops.comparison.compute import ComputeWorkload

from finops.comparison.engine import (
    PricingComparisonEngine,
    ResourceEligibility,
)

from finops.comparison.models import (
    ComparisonScope,
    PricingOption,
)

from finops.comparison.storage import (
    STORAGE_COMPONENTS,
    STORAGE_EXCLUSIONS,
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

PAGE = (
    Path(__file__).resolve().parents[1]
    / "pages"
    / "05_Pricing_Model_Comparison.py"
)


class PricingComparisonDashboardTests(unittest.TestCase):

    def setUp(self):

        self.estimate_id = uuid4()
        self.scenario_id = uuid4()

        self.compute_id = uuid4()
        self.storage_id = uuid4()

        self.estimate = SimpleNamespace(
            estimate_id=self.estimate_id,
            scenario_id=self.scenario_id,
            scenario_revision=6,
            scenario=SimpleNamespace(
                name="E-commerce Production",
            ),
            allow_reference=True,
            summary=SimpleNamespace(
                status=EstimateStatus.COMPLETE,
                known_monthly_cost=D("63.12392"),
                complete_monthly_cost=D("63.12392"),
            ),
        )

        self.compute_resource = ResourceEligibility(
            resource_id=self.compute_id,
            name="Web Servers",
            resource_type=ResourceType.EC2_INSTANCE,
            region="us-east-1",
            eligible=True,
        )

        self.storage_resource = ResourceEligibility(
            resource_id=self.storage_id,
            name="Application Object Storage",
            resource_type=ResourceType.S3_BUCKET,
            region="us-east-1",
            eligible=True,
        )

        self.compute = ComputeWorkload(
            baseline=PricingOption(
                scope=ComparisonScope(
                    baseline_estimate_id=self.estimate_id,
                    resource_id=self.compute_id,
                    components=("compute",),
                ),
                name="On-Demand",
                pricing_model=PricingModel.ON_DEMAND,
                status=EstimateStatus.COMPLETE,
                known_monthly_cost=D("22.776"),
                sources=(
                    PricingSource.FLOCI_PRICING_API,
                ),
            ),
            instance_type="t3.micro",
            region="us-east-1",
            quantity=3,
            monthly_hours=D("730"),
            on_demand_rate=D("0.0104"),
        )

        self.storage = StorageWorkload(
            baseline=PricingOption(
                scope=ComparisonScope(
                    baseline_estimate_id=self.estimate_id,
                    resource_id=self.storage_id,
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

        self.repository = Mock()

        self.repository.list_estimates.return_value = (
            self.estimate,
        )

        self.spot_service = Mock()

        self.spot_service.refresh.return_value = SimpleNamespace(
            observations=(
                SpotPriceObservation(
                    instance_type="t3.micro",
                    region="us-east-1",
                    availability_zone="us-east-1a",
                    product_description="Linux/UNIX",
                    unit_price=D("0.0044"),
                    observed_at=datetime(
                        2026, 11, 20,
                        tzinfo=timezone.utc,
                    ),
                    retrieved_at=datetime(
                        2026, 11, 27,
                        tzinfo=timezone.utc,
                    ),
                ),
            ),
        )

        self.engine = PricingComparisonEngine(
            repository=self.repository,
            spot_service=self.spot_service,
        )

        self.engine.eligible_resources = Mock(
            return_value=(
                self.compute_resource,
                self.storage_resource,
            )
        )

        self.engine.compare_compute = Mock(
            wraps=self.engine.compare_compute
        )

        self.engine.compare_storage = Mock(
            wraps=self.engine.compare_storage
        )

        self.at = AppTest.from_file(
            str(PAGE),
            default_timeout=30,
        )

        self.compute_prefix = (
            f"m5.{self.estimate_id}."
            f"{self.compute_id}"
        )

        self.storage_prefix = (
            f"m5.{self.estimate_id}."
            f"{self.storage_id}"
        )

    def storage_builder(
        self,
        estimate,
        resource_id,
        *,
        retrieval_gb,
    ):

        return replace(
            self.storage,
            retrieval_gb=retrieval_gb,
        )

    def run_page(self):

        with (
            patch(
                "finops.comparison.engine.PricingComparisonEngine",
                return_value=self.engine,
            ),
            patch(
                "finops.comparison.compute.build_compute_workload",
                return_value=self.compute,
            ),
            patch(
                "finops.comparison.engine.build_compute_workload",
                return_value=self.compute,
            ),
            patch(
                "finops.comparison.storage.build_storage_workload",
                side_effect=self.storage_builder,
            ),
            patch(
                "finops.comparison.engine.build_storage_workload",
                side_effect=self.storage_builder,
            ),
        ):

            self.at.run()

        self.assertEqual(
            len(self.at.exception),
            0,
            str(self.at.exception),
        )

        return self.at

    def generate(self):

        self.at.button(
            key="m5.generate"
        ).click()

        return self.run_page()

    def select_storage(self):

        selector = self.at.selectbox(
            key=f"m5.resource.{self.estimate_id}"
        )

        selector.select_index(1)

        return self.run_page()

    def comparison_table(self):

        for element in self.at.dataframe:

            frame = element.value

            if (
                "Option" in frame.columns
                and "Monthly savings" in frame.columns
            ):

                return frame

        return None

    def option_row(self, name):

        frame = self.comparison_table()

        self.assertIsNotNone(frame)

        rows = frame.loc[
            frame["Option"] == name
        ]

        self.assertEqual(
            len(rows),
            1,
        )

        return rows.iloc[0]

    def test_empty_history(self):

        self.repository.list_estimates.return_value = ()

        self.run_page()

        self.assertTrue(
            any(
                "No saved infrastructure estimates" in item.value
                for item in self.at.info
            )
        )

        self.spot_service.refresh.assert_not_called()

    def test_history_failure_is_reported(self):

        self.repository.list_estimates.side_effect = RuntimeError(
            "Simulated historical storage failure."
        )

        self.run_page()

        self.assertTrue(
            any(
                "Unable to load saved" in item.value
                for item in self.at.error
            )
        )

        self.spot_service.refresh.assert_not_called()

    def test_no_eligible_resources(self):

        self.engine.eligible_resources.return_value = (
            replace(
                self.compute_resource,
                eligible=False,
                reason="Incomplete historical compute pricing.",
            ),
        )

        self.run_page()

        self.assertTrue(
            any(
                "No eligible resources" in item.value
                for item in self.at.info
            )
        )

        self.assertIsNone(
            self.comparison_table()
        )

    def test_compute_comparison_and_explicit_generation(self):

        self.run_page()

        self.spot_service.refresh.assert_not_called()
        self.engine.compare_compute.assert_not_called()

        self.generate()

        self.assertEqual(
            len(self.comparison_table()),
            4,
        )

        self.assertEqual(
            self.option_row("On-Demand")["Monthly cost"],
            "$22.78",
        )

        self.assertEqual(
            self.option_row("Reserved Instances")["Monthly cost"],
            "$16.89",
        )

        self.assertEqual(
            self.option_row("Savings Plan")["Monthly cost"],
            "$16.35",
        )

        self.assertEqual(
            self.option_row("Spot - us-east-1a")["Monthly cost"],
            "$9.64",
        )

        self.assertEqual(
            self.option_row(
                "Reserved Instances"
            )["Infrastructure monthly cost"],
            "$57.24",
        )

        self.engine.compare_compute.assert_called_once()
        self.spot_service.refresh.assert_called_once()

        # Ordinary reruns must not retrieve prices again.

        self.run_page()

        self.assertIsNotNone(
            self.comparison_table()
        )

        self.spot_service.refresh.assert_called_once()

    def test_changed_inputs_hide_previous_results(self):

        self.run_page()
        self.generate()

        self.at.text_input(
            key=f"{self.compute_prefix}.reserved.rate"
        ).set_value("0.007")

        self.run_page()

        self.assertIsNone(
            self.comparison_table()
        )

        self.assertTrue(
            any(
                "Comparison inputs have changed" in item.value
                for item in self.at.info
            )
        )

        self.spot_service.refresh.assert_called_once()

        self.generate()

        self.assertEqual(
            self.option_row(
                "Reserved Instances"
            )["Monthly cost"],
            "$19.81",
        )

        self.assertEqual(
            self.spot_service.refresh.call_count,
            2,
        )

    def test_invalid_input_does_not_generate_comparison(self):

        self.run_page()

        self.at.text_input(
            key=f"{self.compute_prefix}.reserved.rate"
        ).set_value("not-a-rate")

        self.run_page()
        self.generate()

        self.assertTrue(
            any(
                "valid decimal number" in item.value
                for item in self.at.error
            )
        )

        self.engine.compare_compute.assert_not_called()
        self.spot_service.refresh.assert_not_called()

        self.assertIsNone(
            self.comparison_table()
        )

    def test_partial_baseline_preserves_resource_savings(self):

        self.estimate.summary.status = EstimateStatus.PARTIAL

        self.estimate.summary.known_monthly_cost = D(
            "34.676"
        )

        self.estimate.summary.complete_monthly_cost = None

        self.run_page()
        self.generate()

        row = self.option_row(
            "Reserved Instances"
        )

        self.assertEqual(
            row["Monthly savings"],
            "$5.88",
        )

        self.assertEqual(
            row["Infrastructure monthly cost"],
            "Unavailable",
        )

        self.assertTrue(
            any(
                "infrastructure projections are unavailable" in item.value
                for item in self.at.warning
            )
        )

    def test_storage_comparison(self):

        self.run_page()
        self.select_storage()
        self.generate()

        self.assertEqual(
            len(self.comparison_table()),
            5,
        )

        self.assertEqual(
            self.option_row(
                "S3 Standard"
            )["Monthly cost"],
            "$11.50",
        )

        self.assertEqual(
            self.option_row(
                "S3 Standard - Infrequent Access"
            )["Monthly cost"],
            "$6.25",
        )

        self.assertEqual(
            self.option_row(
                "S3 Glacier Deep Archive"
            )["Monthly savings"],
            "$11.00",
        )

        self.engine.compare_storage.assert_called_once()
        self.spot_service.refresh.assert_not_called()

    def test_missing_storage_rate_suppresses_savings(self):

        self.run_page()
        self.select_storage()

        self.at.text_input(
            key=f"{self.storage_prefix}.storage.0.capacity"
        ).set_value("")

        self.run_page()
        self.generate()

        row = self.option_row(
            "S3 Standard - Infrequent Access"
        )

        self.assertEqual(
            row["Status"],
            EstimateStatus.PARTIAL.value,
        )

        self.assertEqual(
            row["Monthly cost"],
            "Unavailable",
        )

        self.assertEqual(
            row["Monthly savings"],
            "Unavailable",
        )

        self.assertEqual(
            row["Infrastructure monthly cost"],
            "Unavailable",
        )

    def test_spot_failure_preserves_commitment_results(self):

        self.spot_service.refresh.side_effect = RuntimeError(
            "Simulated Floci API failure."
        )

        self.run_page()
        self.generate()

        self.assertEqual(
            self.option_row(
                "Reserved Instances"
            )["Monthly cost"],
            "$16.89",
        )

        self.assertEqual(
            self.option_row(
                "Spot - unavailable"
            )["Monthly cost"],
            "Unavailable",
        )

        self.assertEqual(
            self.option_row(
                "Spot - unavailable"
            )["Monthly savings"],
            "Unavailable",
        )

    def test_csv_preserves_exact_values_and_incomplete_rows(self):

        self.spot_service.refresh.side_effect = RuntimeError(
            "Simulated Floci API failure."
        )

        self.run_page()
        self.generate()

        _, report = self.at.session_state["m5.result"]

        # Load helpers without invoking the Streamlit page.

        helpers = runpy.run_path(
            str(PAGE),
            run_name="comparison_export_helpers",
        )

        content = helpers["_comparison_csv"](
            self.estimate,
            self.compute_resource,
            report,
        )

        rows = list(
            csv.DictReader(
                io.StringIO(
                    content.decode("utf-8-sig")
                )
            )
        )

        self.assertEqual(
            len(rows),
            4,
        )

        options = {
            row["option"]: row
            for row in rows
        }

        self.assertEqual(
            D(
                options["On-Demand"][
                    "complete_monthly_cost_usd"
                ]
            ),
            D("22.776"),
        )

        self.assertEqual(
            D(
                options["Reserved Instances"][
                    "monthly_savings_usd"
                ]
            ),
            D("5.884"),
        )

        self.assertEqual(
            options["Spot - unavailable"][
                "complete_monthly_cost_usd"
            ],
            "",
        )

        self.assertEqual(
            options["Spot - unavailable"][
                "monthly_savings_usd"
            ],
            "",
        )

        self.assertEqual(
            options["On-Demand"][
                "baseline_estimate_id"
            ],
            str(self.estimate_id),
        )

        self.assertEqual(
            options["On-Demand"][
                "scenario_revision"
            ],
            "6",
        )

        dangerous_resource = replace(
            self.compute_resource,
            name="=1+1",
        )

        protected_csv = helpers["_comparison_csv"](
            self.estimate,
            dangerous_resource,
            report,
        )

        protected_rows = list(
            csv.DictReader(
                io.StringIO(
                    protected_csv.decode("utf-8-sig")
                )
            )
        )

        self.assertEqual(
            protected_rows[0]["resource_name"],
            "'=1+1",
        )


if __name__ == "__main__":
    unittest.main()
