"""Verify scenario persistence and revision integrity."""

import json
import tempfile
import unittest

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from finops.config import RuntimeSettings

from finops.infrastructure.models import (
    InfrastructureScenario,
    ResourceConfiguration,
    ResourceType,
)

from finops.infrastructure.repository import (
    ScenarioConflictError,
    ScenarioNotFoundError,
    ScenarioRepository,
    ScenarioRepositoryError,
    ScenarioValidationError,
)


def example_scenario():

    return InfrastructureScenario(
        name="Production",
        resources=(
            ResourceConfiguration(
                name="Web servers",
                resource_type=ResourceType.EC2_INSTANCE,
                region="us-east-1",
                quantity=3,
                configuration={
                    "instanceType": "t3.micro",
                    "operatingSystem": "Linux",
                    "tenancy": "Shared",
                },
                usage={
                    "monthly_hours": Decimal("123.456789"),
                },
            ),
            ResourceConfiguration(
                name="Object storage",
                resource_type=ResourceType.S3_BUCKET,
                region="us-east-1",
                configuration={
                    "volumeType": "Standard",
                },
                usage={
                    "average_storage_gb": Decimal("500"),
                    "monthly_put_requests": None,
                    "monthly_get_requests": Decimal("0"),
                },
            ),
        ),
    )


class ScenarioRepositoryTests(unittest.TestCase):

    def setUp(self):

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        self.settings = RuntimeSettings(
            runtime_root=Path(directory.name)
        )

        self.repository = ScenarioRepository(self.settings)

    def test_round_trip_preserves_identity_and_usage(self):

        original = example_scenario()

        self.repository.create(original)

        reopened = ScenarioRepository(self.settings)
        saved = reopened.load(original.scenario_id)

        self.assertEqual(saved, original)

        self.assertEqual(
            saved.resources[0].usage["monthly_hours"],
            Decimal("123.456789"),
        )

        self.assertIsNone(
            saved.resources[1].usage["monthly_put_requests"]
        )

        self.assertEqual(
            saved.resources[1].usage["monthly_get_requests"],
            Decimal("0"),
        )

        self.assertNotIn(
            "monthly_transfer_out_gb",
            saved.resources[1].usage,
        )

        path = (
            self.repository.directory
            / f"{original.scenario_id}.json"
        )

        document = json.loads(
            path.read_text(encoding="utf-8")
        )

        self.assertEqual(
            document["resources"][0]["usage"]["monthly_hours"],
            "123.456789",
        )

    def test_create_does_not_overwrite_existing_scenario(self):

        original = self.repository.create(example_scenario())

        with self.assertRaises(ScenarioConflictError):

            self.repository.create(
                replace(original, name="Overwrite")
            )

        self.assertEqual(
            self.repository.load(original.scenario_id),
            original,
        )

    def test_list_multiple_scenarios_and_empty_drafts(self):

        self.assertEqual(
            self.repository.list_scenarios(),
            (),
        )

        first = self.repository.create(example_scenario())

        second = self.repository.create(
            InfrastructureScenario(name="Empty draft")
        )

        scenarios = self.repository.list_scenarios()

        self.assertEqual(len(scenarios), 2)

        self.assertEqual(
            {item.scenario_id for item in scenarios},
            {first.scenario_id, second.scenario_id},
        )

        self.assertEqual(
            self.repository.load(second.scenario_id).resources,
            (),
        )

    def test_update_increments_revision_and_preserves_identity(self):

        original = self.repository.create(example_scenario())

        updated = self.repository.update(
            replace(original, name="Updated production")
        )

        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.scenario_id, original.scenario_id)
        self.assertEqual(updated.created_at, original.created_at)
        self.assertEqual(updated.resources, original.resources)

        self.assertGreaterEqual(
            updated.updated_at,
            original.updated_at,
        )

        self.assertEqual(
            self.repository.load(original.scenario_id),
            updated,
        )

    def test_stale_update_is_rejected(self):

        original = self.repository.create(example_scenario())

        updated = self.repository.update(
            replace(original, name="Current revision")
        )

        with self.assertRaises(ScenarioConflictError):

            self.repository.update(
                replace(original, name="Stale edit")
            )

        self.assertEqual(
            self.repository.load(original.scenario_id),
            updated,
        )

    def test_duplicate_creates_independent_identities(self):

        original = self.repository.create(example_scenario())

        duplicate = self.repository.duplicate(
            original.scenario_id,
            "Development",
        )

        self.assertNotEqual(
            duplicate.scenario_id,
            original.scenario_id,
        )

        self.assertEqual(duplicate.revision, 1)

        self.assertEqual(
            duplicate.resource_group_count,
            original.resource_group_count,
        )

        for first, second in zip(
            original.resources,
            duplicate.resources,
        ):

            self.assertNotEqual(
                first.resource_id,
                second.resource_id,
            )

            self.assertEqual(
                first.configuration,
                second.configuration,
            )

            self.assertEqual(first.usage, second.usage)

        self.assertEqual(
            len(self.repository.list_scenarios()),
            2,
        )

    def test_delete_requires_current_revision(self):

        original = self.repository.create(example_scenario())

        updated = self.repository.update(original)

        with self.assertRaises(ScenarioConflictError):

            self.repository.delete(
                original.scenario_id,
                expected_revision=1,
            )

        self.repository.delete(
            updated.scenario_id,
            expected_revision=2,
        )

        with self.assertRaises(ScenarioNotFoundError):
            self.repository.load(updated.scenario_id)

        self.assertEqual(
            self.repository.list_scenarios(),
            (),
        )

    def test_missing_scenarios_and_invalid_identifiers(self):

        with self.assertRaises(ScenarioNotFoundError):
            self.repository.load(uuid4())

        with self.assertRaises(ValueError):
            self.repository.load("../outside")

    def test_invalid_configuration_cannot_be_saved(self):

        original = example_scenario()

        invalid = replace(
            original.resources[0],
            usage={"monthly_hours": Decimal("900")},
        )

        scenario = replace(
            original,
            resources=(invalid,),
        )

        with self.assertRaises(ScenarioValidationError):
            self.repository.create(scenario)

        self.assertEqual(
            self.repository.list_scenarios(),
            (),
        )

    def test_corrupt_documents_are_rejected(self):

        original = self.repository.create(example_scenario())

        path = (
            self.repository.directory
            / f"{original.scenario_id}.json"
        )

        path.write_text("{invalid", encoding="utf-8")

        with self.assertRaises(ScenarioRepositoryError):
            self.repository.load(original.scenario_id)

        with self.assertRaises(ScenarioRepositoryError):
            self.repository.list_scenarios()

    def test_schema_and_identity_mismatches_are_rejected(self):

        original = self.repository.create(example_scenario())

        path = (
            self.repository.directory
            / f"{original.scenario_id}.json"
        )

        document = json.loads(
            path.read_text(encoding="utf-8")
        )

        for changes in (
            {"schema_version": 2},
            {"scenario_id": str(uuid4())},
        ):

            with self.subTest(changes=changes):

                path.write_text(
                    json.dumps({**document, **changes}),
                    encoding="utf-8",
                )

                with self.assertRaises(ScenarioRepositoryError):
                    self.repository.load(original.scenario_id)

    def test_failed_write_preserves_existing_scenario(self):

        original = self.repository.create(example_scenario())

        path = (
            self.repository.directory
            / f"{original.scenario_id}.json"
        )

        before = path.read_bytes()

        with patch(
            "finops.infrastructure.repository.os.replace",
            side_effect=OSError("Simulated write failure"),
        ):

            with self.assertRaises(ScenarioRepositoryError):

                self.repository.update(
                    replace(original, name="Failed update")
                )

        self.assertEqual(path.read_bytes(), before)

        self.assertEqual(
            self.repository.load(original.scenario_id),
            original,
        )

        self.assertEqual(
            list(self.repository.directory.glob("*.tmp")),
            [],
        )


if __name__ == "__main__":
    unittest.main()
