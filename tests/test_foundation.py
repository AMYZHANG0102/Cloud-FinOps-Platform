"""Verification of the initial FinOps package foundation."""

import importlib
import tempfile
import unittest

from dataclasses import FrozenInstanceError
from pathlib import Path

from finops.config import (
    PROJECT_ROOT,
    DEFAULT_RUNTIME_ROOT,
    RuntimeSettings,
    get_runtime_settings,
)


class PackageFoundationTests(unittest.TestCase):

    def test_assigned_packages_are_importable(self):
        packages = (
            "finops.pricing",
            "finops.infrastructure",
            "finops.estimation",
            "finops.comparison",
        )

        for package in packages:
            with self.subTest(package=package):
                module = importlib.import_module(package)
                self.assertIsNotNone(module)

    def test_project_root_matches_source_location(self):
        expected = Path(__file__).resolve().parents[1]

        self.assertEqual(PROJECT_ROOT, expected)

    def test_default_runtime_root(self):
        settings = get_runtime_settings()

        self.assertEqual(
            settings.runtime_root,
            DEFAULT_RUNTIME_ROOT,
        )

        self.assertTrue(settings.runtime_root.is_absolute())

    def test_default_cache_intervals(self):
        settings = RuntimeSettings()

        self.assertEqual(settings.catalogue_ttl_seconds, 900)
        self.assertEqual(settings.spot_ttl_seconds, 300)

    def test_custom_runtime_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"

            settings = get_runtime_settings(root)

            self.assertEqual(
                settings.runtime_root,
                root.resolve(),
            )

    def test_relative_root_is_project_relative(self):
        settings = RuntimeSettings(
            runtime_root=Path("example-runtime")
        )

        self.assertEqual(
            settings.runtime_root,
            (PROJECT_ROOT / "example-runtime").resolve(),
        )

    def test_runtime_directory_paths(self):
        settings = RuntimeSettings()
        root = settings.runtime_root

        self.assertEqual(
            settings.pricing_directory,
            root / "pricing",
        )

        self.assertEqual(
            settings.scenarios_directory,
            root / "scenarios",
        )

        self.assertEqual(
            settings.snapshots_directory,
            root / "snapshots",
        )

        self.assertEqual(
            settings.estimates_directory,
            root / "estimates",
        )

    def test_cache_file_paths(self):
        settings = RuntimeSettings()

        self.assertEqual(
            settings.catalogue_cache_path,
            settings.pricing_directory / "catalogue_cache.json",
        )

        self.assertEqual(
            settings.spot_cache_path,
            settings.pricing_directory / "spot_cache.json",
        )

    def test_configuration_has_no_directory_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "not-created"

            settings = RuntimeSettings(runtime_root=root)

            self.assertFalse(settings.runtime_root.exists())

            _ = settings.scenarios_directory
            _ = settings.catalogue_cache_path

            self.assertFalse(settings.runtime_root.exists())

    def test_custom_cache_intervals(self):
        settings = RuntimeSettings(
            catalogue_ttl_seconds=120,
            spot_ttl_seconds=60,
        )

        self.assertEqual(settings.catalogue_ttl_seconds, 120)
        self.assertEqual(settings.spot_ttl_seconds, 60)

    def test_invalid_cache_intervals_are_rejected(self):
        for field_name in (
            "catalogue_ttl_seconds",
            "spot_ttl_seconds",
        ):
            for value in (0, -1, 1.5, True, "60", None):
                with self.subTest(
                    field=field_name,
                    value=value,
                ):
                    with self.assertRaises(ValueError):
                        RuntimeSettings(
                            **{field_name: value}
                        )

    def test_runtime_settings_are_immutable(self):
        settings = RuntimeSettings()

        with self.assertRaises(FrozenInstanceError):
            settings.spot_ttl_seconds = 60


if __name__ == "__main__":
    unittest.main()
