"""Immutable persistence of infrastructure estimates and pricing evidence.

Each estimate has one associated pricing snapshot. Both documents
use the estimate UUID as their identifier in separate directories.

Historical estimates are restored from saved values rather than
recalculated against the current pricing catalogue.
"""

import hashlib
import json
import os
import tempfile

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from threading import RLock
from uuid import UUID

from finops.config import RuntimeSettings

from finops.estimation.components import BillingComponent

from finops.estimation.engine import (
    EstimatedComponent,
    InfrastructureEstimate,
)

from finops.estimation.financial import (
    ComponentEstimate,
    CostStatus,
)

from finops.infrastructure.repository import (
    _decode_scenario,
    _encode_scenario,
    _reject_constant,
    _unique_object,
)

from finops.pricing.models import (
    PriceDimension,
    PricingModel,
    PricingQuery,
    PricingRecord,
    PricingResolution,
    PricingSource,
    ResolutionStatus,
)


SCHEMA_VERSION = 1

_LOCK = RLock()


class EstimateRepositoryError(RuntimeError):
    """An estimation persistence operation failed."""


class EstimateNotFoundError(EstimateRepositoryError):
    """The requested saved estimate does not exist."""


class EstimateConflictError(EstimateRepositoryError):
    """An immutable estimate or snapshot already exists."""


def _encode(value):
    """Encode domain values without converting Decimal to float."""

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, Decimal):

        if not value.is_finite():
            raise ValueError("Nonfinite Decimal cannot be persisted.")

        return str(value)

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if is_dataclass(value):

        return {
            field.name: _encode(
                getattr(value, field.name)
            )
            for field in fields(value)
        }

    if isinstance(value, Mapping):

        return {
            key: _encode(item)
            for key, item in value.items()
        }

    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]

    if value is None or type(value) in (str, bool, int):
        return value

    raise TypeError(
        f"Unsupported persisted value: {type(value).__name__}"
    )


def _require_fields(document, expected):

    if not isinstance(document, dict):
        raise ValueError("Expected a JSON object.")

    if set(document) != set(expected):
        raise ValueError("Missing or unexpected persisted fields.")


def _contract_values(document, contract):

    _require_fields(
        document,
        (field.name for field in fields(contract)),
    )

    return dict(document)


def _decimal(value):

    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError("Persisted Decimal must be text.")

    result = Decimal(value)

    if not result.is_finite():
        raise ValueError("Nonfinite persisted Decimal.")

    return result


def _timestamp(value):

    if value is None:
        return None

    return datetime.fromisoformat(value)


def _text_tuple(value):

    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
    ):
        raise ValueError("Expected a collection of text values.")

    return tuple(value)


def _decode_query(document):

    if document is None:
        return None

    values = _contract_values(
        document,
        PricingQuery,
    )

    values["pricing_model"] = PricingModel(
        values["pricing_model"]
    )

    return PricingQuery(**values)


def _decode_dimension(document):

    values = _contract_values(
        document,
        PriceDimension,
    )

    for key in (
        "unit_price",
        "begin_range",
        "end_range",
    ):

        values[key] = _decimal(values[key])

    values["applies_to"] = _text_tuple(
        values["applies_to"]
    )

    return PriceDimension(**values)


def _decode_record(document):

    values = _contract_values(
        document,
        PricingRecord,
    )

    values["pricing_model"] = PricingModel(
        values["pricing_model"]
    )

    values["source"] = PricingSource(
        values["source"]
    )

    for key in (
        "effective_date",
        "publication_date",
        "retrieved_at",
        "verified_at",
    ):

        values[key] = _timestamp(values[key])

    values["dimensions"] = tuple(
        _decode_dimension(item)
        for item in values["dimensions"]
    )

    values["assumptions"] = _text_tuple(
        values["assumptions"]
    )

    return PricingRecord(**values)


def _decode_resolution(document):

    if document is None:
        return None

    values = _contract_values(
        document,
        PricingResolution,
    )

    values["query"] = _decode_query(
        values["query"]
    )

    values["status"] = ResolutionStatus(
        values["status"]
    )

    values["records"] = tuple(
        _decode_record(item)
        for item in values["records"]
    )

    for key in (
        "missing_components",
        "diagnostics",
        "warnings",
    ):

        values[key] = _text_tuple(
            values[key]
        )

    return PricingResolution(**values)


def _decode_billing(document):

    values = _contract_values(
        document,
        BillingComponent,
    )

    values["resource_id"] = UUID(
        values["resource_id"]
    )

    values["usage"] = _decimal(
        values["usage"]
    )

    values["query"] = _decode_query(
        values["query"]
    )

    return BillingComponent(**values)


def _decode_component_estimate(document):

    values = _contract_values(
        document,
        ComponentEstimate,
    )

    values["resource_id"] = UUID(
        values["resource_id"]
    )

    values["status"] = CostStatus(
        values["status"]
    )

    for key in (
        "usage",
        "priced_usage",
        "known_monthly_cost",
    ):

        values[key] = _decimal(values[key])

    return ComponentEstimate(**values)


def _decode_component(document, resolution):

    values = dict(document)
    values["resolution"] = resolution

    _require_fields(
        values,
        (
            field.name
            for field in fields(EstimatedComponent)
        ),
    )

    values["billing"] = _decode_billing(
        values["billing"]
    )

    values["estimate"] = _decode_component_estimate(
        values["estimate"]
    )

    for key in (
        "pool_usage",
        "pool_priced_usage",
        "pool_known_cost",
    ):

        values[key] = _decimal(values[key])

    return EstimatedComponent(**values)


def _validate_estimate(estimate):

    if not isinstance(estimate, InfrastructureEstimate):
        raise TypeError("InfrastructureEstimate required.")

    if (
        not isinstance(estimate.estimate_id, UUID)
        or estimate.estimate_id.int == 0
    ):
        raise ValueError("Invalid estimate identity.")

    if (
        not isinstance(estimate.evaluated_at, datetime)
        or estimate.evaluated_at.utcoffset() != timedelta(0)
    ):
        raise ValueError("Estimate evaluation time must be UTC.")

    if type(estimate.allow_reference) is not bool:
        raise ValueError("Invalid pricing policy.")

    if (
        not isinstance(estimate.model_version, str)
        or not estimate.model_version.strip()
    ):
        raise ValueError("Invalid estimation model version.")

    resources = {
        resource.resource_id: resource
        for resource in estimate.scenario.resources
    }

    pools = {}

    for item in estimate.components:

        billing = item.billing
        financial = item.estimate

        if billing.resource_id not in resources:
            raise ValueError("Unknown estimate resource identity.")

        resource = resources[billing.resource_id]

        if billing.service_code != resource.service_code:
            raise ValueError("Estimate service mismatch.")

        if (
            billing.resource_id != financial.resource_id
            or billing.component != financial.component
            or billing.unit != financial.unit
            or billing.usage != financial.usage
        ):
            raise ValueError("Billing and financial result mismatch.")

        if item.resolution is not None:

            if item.resolution.query != billing.query:
                raise ValueError("Pricing evidence query mismatch.")

        if financial.status in (
            CostStatus.PRICED,
            CostStatus.PARTIAL,
        ) and item.resolution is None:

            raise ValueError("Priced component lacks pricing evidence.")

        pool_values = (
            item.pool_usage,
            item.pool_priced_usage,
            item.pool_known_cost,
        )

        if item.pool_id is None:

            if any(value is not None for value in pool_values):
                raise ValueError("Pool identity missing.")

        else:

            if (
                not isinstance(item.pool_id, str)
                or not item.pool_id
                or any(
                    not isinstance(value, Decimal)
                    or not value.is_finite()
                    or value < 0
                    for value in pool_values
                )
            ):
                raise ValueError("Invalid pricing pool metadata.")

            pools.setdefault(
                item.pool_id,
                [],
            ).append(item)

    for members in pools.values():

        first = members[0]

        for item in members:

            if (
                item.pool_usage != first.pool_usage
                or item.pool_priced_usage != first.pool_priced_usage
                or item.pool_known_cost != first.pool_known_cost
            ):
                raise ValueError("Inconsistent pricing pool metadata.")

        if sum(
            (item.estimate.usage for item in members),
            Decimal("0"),
        ) != first.pool_usage:

            raise ValueError("Pricing pool usage mismatch.")

        if sum(
            (item.estimate.priced_usage for item in members),
            Decimal("0"),
        ) != first.pool_priced_usage:

            raise ValueError("Pricing pool coverage mismatch.")

        if sum(
            (item.estimate.known_monthly_cost for item in members),
            Decimal("0"),
        ) != first.pool_known_cost:

            raise ValueError("Pricing pool cost mismatch.")

    # Also verifies duplicate component identities.

    estimate.summary


def _json_bytes(document):

    return (
        json.dumps(
            document,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
    ).encode("utf-8")


def _parse_json(content):

    return json.loads(
        content.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )


def _digest(content):
    return hashlib.sha256(content).hexdigest()


def _documents(estimate):

    _validate_estimate(estimate)

    identifier = str(estimate.estimate_id)

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": identifier,
        "estimate_id": identifier,
        "scenario_id": str(estimate.scenario_id),
        "scenario_revision": estimate.scenario_revision,
        "evaluated_at": estimate.evaluated_at.isoformat(),
        "allow_reference": estimate.allow_reference,
        "resolutions": [
            {
                "resource_id": str(item.billing.resource_id),
                "component": item.billing.component,
                "resolution": _encode(item.resolution),
            }
            for item in estimate.components
        ],
    }

    snapshot_content = _json_bytes(snapshot)

    document = _encode(estimate)

    document["scenario"] = _encode_scenario(
        estimate.scenario
    )

    for item in document["components"]:
        item.pop("resolution")

    document.update({
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": identifier,
        "snapshot_sha256": _digest(snapshot_content),
        "summary": _encode(estimate.summary),
        "known_period_costs": _encode(
            estimate.summary.known_period_costs
        ),
        "complete_period_costs": _encode(
            estimate.summary.complete_period_costs
        ),
    })

    return _json_bytes(document), snapshot_content


def _restore(estimate_content, snapshot_content, identifier):

    document = _parse_json(estimate_content)
    snapshot = _parse_json(snapshot_content)

    _require_fields(
        document,
        (
            *(field.name for field in fields(InfrastructureEstimate)),
            "schema_version",
            "snapshot_id",
            "snapshot_sha256",
            "summary",
            "known_period_costs",
            "complete_period_costs",
        ),
    )

    _require_fields(
        snapshot,
        (
            "schema_version",
            "snapshot_id",
            "estimate_id",
            "scenario_id",
            "scenario_revision",
            "evaluated_at",
            "allow_reference",
            "resolutions",
        ),
    )

    for item in (document, snapshot):

        version = item["schema_version"]

        if type(version) is not int or version != SCHEMA_VERSION:
            raise ValueError("Unsupported estimation schema version.")

        if (
            item["estimate_id"] != str(identifier)
            or item["snapshot_id"] != str(identifier)
        ):
            raise ValueError("Estimate or snapshot identity mismatch.")

    if document["snapshot_sha256"] != _digest(snapshot_content):
        raise ValueError("Pricing snapshot checksum mismatch.")

    scenario = _decode_scenario(
        document["scenario"]
    )

    if (
        snapshot["scenario_id"] != str(scenario.scenario_id)
        or snapshot["scenario_revision"] != scenario.revision
        or snapshot["evaluated_at"] != document["evaluated_at"]
        or snapshot["allow_reference"] != document["allow_reference"]
    ):
        raise ValueError("Snapshot metadata mismatch.")

    components = document["components"]
    resolutions = snapshot["resolutions"]

    if (
        not isinstance(components, list)
        or not isinstance(resolutions, list)
        or len(components) != len(resolutions)
    ):
        raise ValueError("Snapshot component count mismatch.")

    restored = []

    for item, evidence in zip(components, resolutions):

        _require_fields(
            evidence,
            ("resource_id", "component", "resolution"),
        )

        if (
            evidence["resource_id"] != item["billing"]["resource_id"]
            or evidence["component"] != item["billing"]["component"]
        ):
            raise ValueError("Snapshot component identity mismatch.")

        restored.append(
            _decode_component(
                item,
                _decode_resolution(evidence["resolution"]),
            )
        )

    result = InfrastructureEstimate(
        scenario=scenario,
        components=tuple(restored),
        allow_reference=document["allow_reference"],
        estimate_id=identifier,
        evaluated_at=_timestamp(document["evaluated_at"]),
        model_version=document["model_version"],
        assumptions=_text_tuple(document["assumptions"]),
        exclusions=_text_tuple(document["exclusions"]),
    )

    _validate_estimate(result)

    for key, actual in (
        ("summary", result.summary),
        ("known_period_costs", result.summary.known_period_costs),
        ("complete_period_costs", result.summary.complete_period_costs),
    ):

        if document[key] != _encode(actual):
            raise ValueError(f"Persisted financial {key} mismatch.")

    return result


def _write_atomic(path, content):

    temporary = None

    try:

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=".estimate-",
            suffix=".tmp",
            delete=False,
        ) as stream:

            temporary = Path(stream.name)

            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, path)
        temporary = None

    finally:

        if temporary is not None:
            temporary.unlink(missing_ok=True)


class EstimateRepository:
    """Save and reopen immutable historical infrastructure estimates."""

    def __init__(self, runtime_settings=None):

        self.runtime = (
            RuntimeSettings()
            if runtime_settings is None
            else runtime_settings
        )

        self.estimates_directory = (
            self.runtime.estimates_directory
        )

        self.snapshots_directory = (
            self.runtime.snapshots_directory
        )

    @staticmethod
    def _identifier(identifier):

        if (
            not isinstance(identifier, UUID)
            or identifier.int == 0
        ):
            raise ValueError("A nonzero estimate UUID is required.")

        return identifier

    def estimate_path(self, estimate_id):

        identifier = self._identifier(estimate_id)

        return (
            self.estimates_directory
            / f"{identifier}.json"
        )

    def snapshot_path(self, estimate_id):

        identifier = self._identifier(estimate_id)

        return (
            self.snapshots_directory
            / f"{identifier}.json"
        )

    def save(self, estimate):

        with _LOCK:

            estimate_content, snapshot_content = _documents(
                estimate
            )

            identifier = estimate.estimate_id

            estimate_path = self.estimate_path(identifier)
            snapshot_path = self.snapshot_path(identifier)

            if estimate_path.exists() or snapshot_path.exists():

                raise EstimateConflictError(
                    "Estimate or pricing snapshot already exists."
                )

            # Verify serialization before writing either document.

            restored = _restore(
                estimate_content,
                snapshot_content,
                identifier,
            )

            if restored != estimate:
                raise EstimateRepositoryError(
                    "Estimate serialization round trip failed."
                )

            try:

                # Publish pricing evidence first.
                # The estimate document is the final commit marker.

                _write_atomic(
                    snapshot_path,
                    snapshot_content,
                )

                _write_atomic(
                    estimate_path,
                    estimate_content,
                )

            except OSError as error:

                # A successfully written snapshot may remain if the
                # second write fails. It is not a published estimate.

                raise EstimateRepositoryError(
                    f"Unable to persist estimate: {error}"
                ) from error

        return estimate

    def load(self, estimate_id):

        with _LOCK:

            estimate_path = self.estimate_path(
                estimate_id
            )

            snapshot_path = self.snapshot_path(
                estimate_id
            )

            try:

                estimate_content = estimate_path.read_bytes()

            except FileNotFoundError as error:

                raise EstimateNotFoundError(
                    f"Estimate not found: {estimate_id}"
                ) from error

            except OSError as error:

                raise EstimateRepositoryError(
                    f"Unable to read estimate: {error}"
                ) from error

            try:

                return _restore(
                    estimate_content,
                    snapshot_path.read_bytes(),
                    estimate_id,
                )

            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                ArithmeticError,
            ) as error:

                raise EstimateRepositoryError(
                    f"Invalid saved estimate {estimate_id}: {error}"
                ) from error

    def list_estimates(self, scenario_id=None):

        if scenario_id is not None:
            self._identifier(scenario_id)

        with _LOCK:

            estimates = []

            try:

                for path in self.estimates_directory.glob("*.json"):

                    identifier = UUID(path.stem)

                    if path.name != f"{identifier}.json":
                        raise ValueError(
                            "Noncanonical estimate filename."
                        )

                    estimate = self.load(identifier)

                    if (
                        scenario_id is None
                        or estimate.scenario_id == scenario_id
                    ):

                        estimates.append(estimate)

            except (OSError, ValueError) as error:

                raise EstimateRepositoryError(
                    f"Unable to list estimates: {error}"
                ) from error

            return tuple(sorted(
                estimates,
                key=lambda item: (
                    item.evaluated_at,
                    str(item.estimate_id),
                ),
                reverse=True,
            ))
