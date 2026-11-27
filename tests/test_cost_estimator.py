"""Verify dashboard generation, coverage and historical estimates."""

import tempfile
import unittest

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from finops.config import RuntimeSettings
from finops.estimation.engine import InfrastructureCostEstimator

from finops.estimation.financial import EstimateStatus

from finops.estimation.repository import EstimateRepository
from finops.infrastructure.repository import ScenarioRepository
from finops.pricing.models import ResolutionStatus

from test_estimation_engine import (
    FixtureResolver,
    ec2,
    s3,
    scenario,
)


D = Decimal

PAGE = (
    Path(__file__).resolve().parents[1]
    / "pages"
    / "04_Cost_Estimator.py"
)


class CostEstimatorDashboardTests(unittest.TestCase):

    def setUp(self):

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        self.settings = RuntimeSettings(
            runtime_root=Path(directory.name)
        )

        self.scenarios = ScenarioRepository(self.settings)
        self.estimates = EstimateRepository(self.settings)

        self.resolver = FixtureResolver()

        self.estimator = InfrastructureCostEstimator(
            self.resolver
        )

        patches = (
            (
                "finops.infrastructure.repository.ScenarioRepository",
                self.scenarios,
            ),
            (
                "finops.estimation.repository.EstimateRepository",
                self.estimates,
            ),
            (
                "finops.estimation.engine.InfrastructureCostEstimator",
                self.estimator,
            ),
        )

        for target, value in patches:

            patcher = patch(
                target,
                return_value=value,
            )

            patcher.start()
            self.addCleanup(patcher.stop)

    def open_app(self):

        app = AppTest.from_file(
            str(PAGE),
            default_timeout=60,
        ).run()

        self.assertFalse(app.exception)

        return app

    def generate(self, app):

        app.button(
            key="m4.generate"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        return app.session_state["m4.result"]

    @staticmethod
    def metrics(app):

        return {
            item.label: item.value
            for item in app.metric
        }

    def test_empty_workspace(self):

        app = self.open_app()

        self.assertTrue(any(
            "No saved infrastructure scenarios" in item.value
            for item in app.info
        ))

        app.radio(
            key="m4.mode"
        ).set_value("Saved estimates").run()

        self.assertFalse(app.exception)

        self.assertTrue(any(
            "No historical estimates" in item.value
            for item in app.info
        ))

    def test_complete_estimate_metrics_and_breakdowns(self):

        saved = self.scenarios.create(
            scenario(ec2(), s3())
        )

        app = self.open_app()
        result = self.generate(app)

        self.assertEqual(
            result.scenario_id,
            saved.scenario_id,
        )

        self.assertEqual(
            result.summary.status,
            EstimateStatus.COMPLETE,
        )

        self.assertEqual(
            result.summary.complete_monthly_cost,
            D("34.276"),
        )

        metrics = self.metrics(app)

        self.assertEqual(metrics["Monthly cost"], "$34.28")
        self.assertEqual(metrics["Annual cost"], "$411.31")

        resource_table = app.dataframe[0].value
        service_table = app.dataframe[1].value

        self.assertEqual(len(resource_table), 2)
        self.assertEqual(len(service_table), 2)

        self.assertEqual(
            resource_table.iloc[0]["Effective running-hour rate"],
            "$0.0104/Hrs",
        )

        self.assertEqual(
            self.estimates.list_estimates(),
            (),
        )

    def test_partial_estimate_displays_known_subtotal(self):

        self.scenarios.create(
            scenario(ec2(), s3(put="100"))
        )

        app = self.open_app()
        result = self.generate(app)

        self.assertEqual(
            result.summary.status,
            EstimateStatus.PARTIAL,
        )

        metrics = self.metrics(app)

        self.assertEqual(
            metrics["Monthly cost"],
            "Unavailable",
        )

        self.assertEqual(
            metrics["Annual cost"],
            "Unavailable",
        )

        self.assertEqual(
            metrics["Known monthly subtotal"],
            "$34.28",
        )

        app.multiselect[0].set_value(
            ["UNRESOLVED"]
        ).run()

        self.assertFalse(app.exception)

        component_table = next(
            item.value
            for item in app.dataframe
            if "Component" in item.value.columns
        )

        self.assertEqual(
            component_table["Status"].tolist(),
            ["UNRESOLVED"],
        )

    def test_unavailable_pricing_is_not_presented_as_free(self):

        self.resolver.failure = ResolutionStatus.API_ERROR

        self.scenarios.create(
            scenario(ec2())
        )

        app = self.open_app()
        result = self.generate(app)

        self.assertEqual(
            result.summary.status,
            EstimateStatus.UNAVAILABLE,
        )

        metrics = self.metrics(app)

        self.assertEqual(
            metrics["Monthly cost"],
            "Unavailable",
        )

        self.assertEqual(
            metrics["Known monthly subtotal"],
            "$0.00",
        )

        self.assertTrue(any(
            "does not establish" in item.value
            for item in app.caption
        ))

    def test_pricing_policy_and_refresh_controls(self):

        self.scenarios.create(
            scenario(ec2())
        )

        self.resolver.reference = True

        app = self.open_app()

        strict = self.generate(app)

        self.assertEqual(
            strict.summary.status,
            EstimateStatus.UNAVAILABLE,
        )

        app.radio(
            key="m4.policy"
        ).set_value(
            "Floci + supplementary reference pricing"
        ).run()

        self.assertTrue(any(
            "selected pricing policy differs" in item.value
            for item in app.warning
        ))

        app.checkbox(
            key="m4.refresh"
        ).check().run()

        result = self.generate(app)

        self.assertTrue(result.allow_reference)

        self.assertEqual(
            result.summary.complete_monthly_cost,
            D("22.776"),
        )

        self.assertTrue(self.resolver.calls[-1][2])
        self.assertTrue(self.resolver.calls[-1][3])

    def test_save_and_reopen_history_without_pricing(self):

        self.scenarios.create(
            scenario(ec2(), s3())
        )

        app = self.open_app()
        result = self.generate(app)

        app.button(
            key="m4.save"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        self.assertEqual(
            self.estimates.load(result.estimate_id),
            result,
        )

        previous_calls = len(self.resolver.calls)

        reopened = self.open_app()

        reopened.radio(
            key="m4.mode"
        ).set_value("Saved estimates").run()

        self.assertFalse(reopened.exception)
        self.assertFalse(reopened.error)

        self.assertEqual(
            self.metrics(reopened)["Monthly cost"],
            "$34.28",
        )

        self.assertEqual(
            len(self.resolver.calls),
            previous_calls,
        )

    def test_historical_revision_survives_scenario_changes(self):

        original = self.scenarios.create(
            scenario(ec2())
        )

        app = self.open_app()
        result = self.generate(app)

        app.button(
            key="m4.save"
        ).click().run()

        updated = self.scenarios.update(
            replace(
                original,
                resources=(
                    replace(
                        original.resources[0],
                        quantity=6,
                    ),
                ),
            )
        )

        app.run()

        self.assertFalse(app.exception)

        self.assertTrue(any(
            "older saved scenario revision" in item.value
            for item in app.warning
        ))

        self.assertEqual(
            self.metrics(app)["Monthly cost"],
            "$22.78",
        )

        self.scenarios.delete(
            updated.scenario_id,
            expected_revision=updated.revision,
        )

        app.radio(
            key="m4.mode"
        ).set_value("Saved estimates").run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        historical = self.estimates.load(
            result.estimate_id
        )

        self.assertEqual(
            historical.scenario_revision,
            original.revision,
        )

        self.assertEqual(
            self.metrics(app)["Monthly cost"],
            "$22.78",
        )

    def test_empty_scenario_cannot_generate_estimate(self):

        self.scenarios.create(
            scenario()
        )

        app = self.open_app()

        self.assertTrue(
            app.button(key="m4.generate").disabled
        )

        self.assertEqual(self.resolver.calls, [])


if __name__ == "__main__":
    unittest.main()
