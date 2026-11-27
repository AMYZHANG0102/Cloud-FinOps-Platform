"""Verify Infrastructure Builder interactions and saved state."""

import tempfile
import unittest

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from finops.config import RuntimeSettings
from finops.infrastructure.repository import ScenarioRepository


PAGE = (
    Path(__file__).resolve().parents[1]
    / "pages"
    / "03_Infrastructure_Builder.py"
)


class InfrastructureBuilderTests(unittest.TestCase):

    def setUp(self):

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        self.settings = RuntimeSettings(
            runtime_root=Path(directory.name)
        )

        self.repository = ScenarioRepository(
            self.settings
        )

        patcher = patch(
            "finops.infrastructure.repository.ScenarioRepository",
            return_value=self.repository,
        )

        patcher.start()
        self.addCleanup(patcher.stop)

    def open_app(self):

        app = AppTest.from_file(
            str(PAGE),
            default_timeout=30,
        ).run()

        self.assertFalse(app.exception)

        return app

    def prefix(self, app):

        return (
            f"m3.edit.{app.session_state['m3.epoch']}"
        )

    def create_scenario(self, app, name="Production"):

        app.text_input(
            key="m3.create.name"
        ).set_value(name).run()

        app.button(
            key="m3.create"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        return self.repository.list_scenarios()[0]

    def add_ec2(self, app, quantity="3"):

        editor = (
            f"{self.prefix(app)}."
            "resource.new.ec2_instance"
        )

        app.text_input(
            key=f"{editor}.quantity"
        ).set_value(quantity).run()

        app.button(
            key=f"{editor}.save"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        return self.repository.list_scenarios()[0]

    def test_create_and_reopen_saved_scenario(self):

        app = self.open_app()

        scenario = self.create_scenario(app)

        self.assertEqual(scenario.name, "Production")
        self.assertEqual(scenario.revision, 1)
        self.assertEqual(scenario.resources, ())

        reopened = self.open_app()

        self.assertEqual(
            reopened.selectbox(
                key="m3.selected"
            ).value,
            str(scenario.scenario_id),
        )

    def test_add_ec2_resource_and_persist_usage(self):

        app = self.open_app()
        self.create_scenario(app)

        scenario = self.add_ec2(app)

        self.assertEqual(scenario.revision, 2)
        self.assertEqual(scenario.resource_group_count, 1)
        self.assertEqual(scenario.total_resource_count, 3)

        resource = scenario.resources[0]

        self.assertEqual(
            resource.configuration["instanceType"],
            "t3.micro",
        )

        self.assertEqual(
            resource.usage["monthly_hours"],
            Decimal("730"),
        )

        reopened = self.open_app()

        self.assertEqual(
            reopened.dataframe[0].value["Quantity"].tolist(),
            [3],
        )

    def test_edit_and_remove_existing_resource(self):

        app = self.open_app()
        self.create_scenario(app)

        original = self.add_ec2(app)

        resource_id = str(
            original.resources[0].resource_id
        )

        prefix = self.prefix(app)

        app.selectbox(
            key=f"{prefix}.resource_selection"
        ).select(resource_id).run()

        editor = (
            f"{prefix}.resource."
            f"{resource_id}.ec2_instance"
        )

        app.text_input(
            key=f"{editor}.quantity"
        ).set_value("5").run()

        app.button(
            key=f"{editor}.save"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        updated = self.repository.load(
            original.scenario_id
        )

        self.assertEqual(updated.revision, 3)
        self.assertEqual(updated.total_resource_count, 5)

        self.assertEqual(
            updated.resources[0].resource_id,
            original.resources[0].resource_id,
        )

        prefix = self.prefix(app)

        app.selectbox(
            key=f"{prefix}.resource_selection"
        ).select(resource_id).run()

        editor = (
            f"{prefix}.resource."
            f"{resource_id}.ec2_instance"
        )

        app.checkbox(
            key=f"{editor}.remove_confirm"
        ).check().run()

        app.button(
            key=f"{editor}.remove"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        remaining = self.repository.load(
            original.scenario_id
        )

        self.assertEqual(remaining.revision, 4)
        self.assertEqual(remaining.resources, ())

    def test_conditional_s3_fields_and_unknown_usage(self):

        app = self.open_app()
        self.create_scenario(app)

        prefix = self.prefix(app)

        app.selectbox(
            key=f"{prefix}.resource_type"
        ).select("s3_bucket").run()

        editor = f"{prefix}.resource.new.s3_bucket"

        app.selectbox(
            key=f"{editor}.configuration.volumeType"
        ).select("Glacier Deep Archive").run()

        self.assertEqual(
            app.text_input(
                key=f"{editor}.usage.monthly_retrieval_gb"
            ).value,
            "",
        )

        app.text_input(
            key=f"{editor}.usage.monthly_put_requests"
        ).set_value("0").run()

        app.button(
            key=f"{editor}.save"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        scenario = self.repository.list_scenarios()[0]
        resource = scenario.resources[0]

        self.assertEqual(
            resource.usage["monthly_put_requests"],
            Decimal("0"),
        )

        self.assertIsNone(
            resource.usage["monthly_get_requests"]
        )

        self.assertIsNone(
            resource.usage["monthly_retrieval_gb"]
        )

    def test_invalid_usage_does_not_modify_scenario(self):

        app = self.open_app()
        original = self.create_scenario(app)

        editor = (
            f"{self.prefix(app)}."
            "resource.new.ec2_instance"
        )

        app.text_input(
            key=f"{editor}.usage.monthly_hours"
        ).set_value("900").run()

        app.button(
            key=f"{editor}.save"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertTrue(app.error)

        self.assertEqual(
            self.repository.load(original.scenario_id),
            original,
        )

    def test_duplicate_and_delete_scenario(self):

        app = self.open_app()
        self.create_scenario(app)
        original = self.add_ec2(app)

        prefix = self.prefix(app)

        app.text_input(
            key=f"{prefix}.duplicate_name"
        ).set_value("Development").run()

        app.button(
            key=f"{prefix}.duplicate"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        scenarios = self.repository.list_scenarios()

        self.assertEqual(len(scenarios), 2)

        duplicate = next(
            item for item in scenarios
            if item.scenario_id != original.scenario_id
        )

        self.assertEqual(duplicate.name, "Development")
        self.assertEqual(duplicate.revision, 1)

        self.assertNotEqual(
            duplicate.resources[0].resource_id,
            original.resources[0].resource_id,
        )

        prefix = self.prefix(app)

        app.checkbox(
            key=f"{prefix}.delete_confirm"
        ).check().run()

        app.button(
            key=f"{prefix}.delete"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        self.assertEqual(
            self.repository.list_scenarios(),
            (original,),
        )

    def test_stale_edit_requires_reload(self):

        app = self.open_app()
        original = self.create_scenario(app)

        updated = self.repository.update(
            replace(
                original,
                description="Updated elsewhere",
            )
        )

        prefix = self.prefix(app)

        app.text_input(
            key=f"{prefix}.name"
        ).set_value("Outdated edit").run()

        app.button(
            key=f"{prefix}.save_details"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertTrue(app.error)

        self.assertEqual(
            self.repository.load(original.scenario_id),
            updated,
        )

        app.button(
            key="m3.reload"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)

        self.assertEqual(
            app.session_state["m3.snapshot"],
            updated,
        )


if __name__ == "__main__":
    unittest.main()
