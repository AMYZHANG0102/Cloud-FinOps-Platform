"""Focused validation of the supplementary reference catalogue."""

import json
import tempfile
import unittest

from decimal import Decimal
from pathlib import Path

from finops.pricing.models import PricingSource

from finops.pricing.reference import (
    DEFAULT_REFERENCE_PATH,
    ReferenceCatalogueError,
    load_reference_rates,
)


class ReferencePricingTests(unittest.TestCase):

    def setUp(self):

        self.rates = load_reference_rates()

        self.by_id = {
            item.reference_id: item
            for item in self.rates
        }

    def test_catalogue_contains_expected_rates(self):

        self.assertEqual(len(self.rates), 8)

        self.assertEqual(
            len(self.by_id),
            len(self.rates),
        )

    def test_reference_provenance_and_unknown_effective_dates(self):

        for item in self.rates:

            self.assertEqual(
                item.record.source,
                PricingSource.REFERENCE_DATA,
            )

            self.assertEqual(
                item.record.region,
                "us-east-1",
            )

            self.assertIsNone(
                item.record.effective_date
            )

            self.assertIsNotNone(
                item.record.verified_at
            )

            self.assertTrue(item.limitations)

    def test_exact_decimal_rates(self):

        expected = {
            "REF-EBS-GP3-STORAGE-USE1": "0.08",
            "REF-EBS-GP3-IOPS-USE1": "0.005",
            "REF-EBS-GP3-THROUGHPUT-USE1": "0.04",
            "REF-LAMBDA-X86-DURATION-USE1": "0.0000166667",
            "REF-LAMBDA-EPHEMERAL-USE1": "0.0000000309",
            "REF-DDB-STANDARD-WRITES-USE1": "0.000000625",
            "REF-DDB-STANDARD-READS-USE1": "0.000000125",
            "REF-DDB-STANDARD-STORAGE-USE1": "0.25",
        }

        for reference_id, price in expected.items():

            actual = (
                self.by_id[reference_id]
                .record.dimensions[0].unit_price
            )

            self.assertEqual(actual, Decimal(price))

    def test_dynamodb_request_unit_conversion(self):

        writes = self.by_id[
            "REF-DDB-STANDARD-WRITES-USE1"
        ].record.dimensions[0]

        reads = self.by_id[
            "REF-DDB-STANDARD-READS-USE1"
        ].record.dimensions[0]

        self.assertEqual(
            writes.unit_price * Decimal("1000000"),
            Decimal("0.625"),
        )

        self.assertEqual(
            reads.unit_price * Decimal("1000000"),
            Decimal("0.125"),
        )

    def test_lambda_duration_has_finite_reference_coverage(self):

        rate = self.by_id[
            "REF-LAMBDA-X86-DURATION-USE1"
        ].record.dimensions[0]

        self.assertEqual(
            rate.end_range,
            Decimal("14880000"),
        )

        self.assertFalse(rate.is_unbounded)

    def test_invalid_reference_documents_are_rejected(self):

        for modification in (
            "duplicate",
            "negative_price",
            "invalid_currency",
            "invalid_source",
            "missing_limitations",
            "unsupported_schema",
        ):

            with self.subTest(modification=modification):

                document = json.loads(
                    DEFAULT_REFERENCE_PATH.read_text(
                        encoding="utf-8"
                    )
                )

                first = document["rates"][0]

                if modification == "duplicate":
                    document["rates"].append(first)

                elif modification == "negative_price":
                    first["unit_price"] = "-0.08"

                elif modification == "invalid_currency":
                    first["currency"] = "CAD"

                elif modification == "invalid_source":
                    first["source_reference"] = (
                        "https://example.com/pricing"
                    )

                elif modification == "missing_limitations":
                    first["limitations"] = []

                elif modification == "unsupported_schema":
                    document["schema_version"] = 999

                with tempfile.TemporaryDirectory() as directory:

                    path = Path(directory) / "reference.json"

                    path.write_text(
                        json.dumps(document),
                        encoding="utf-8",
                    )

                    with self.assertRaises(
                        ReferenceCatalogueError
                    ):
                        load_reference_rates(path)

    def test_missing_reference_file_is_explicit(self):

        with tempfile.TemporaryDirectory() as directory:

            path = Path(directory) / "missing.json"

            with self.assertRaises(
                ReferenceCatalogueError
            ):
                load_reference_rates(path)


if __name__ == "__main__":
    unittest.main()
