"""Persistent management of hypothetical infrastructure scenarios.

Each scenario is stored as an individual versioned JSON document.
Writes are atomic and synchronized within the current process.
"""

import json
import os
import tempfile

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from finops.config import RuntimeSettings

from finops.infrastructure.models import (
    InfrastructureScenario,
    ResourceConfiguration,
    ResourceType,
)

from finops.infrastructure.validation import validate_scenario
from finops.pricing.models import PricingModel


_LOCK = RLock()


class ScenarioRepositoryError(RuntimeError):
    """Base scenario persistence error."""


class ScenarioNotFoundError(ScenarioRepositoryError):
    """The requested scenario does not exist."""


class ScenarioConflictError(ScenarioRepositoryError):
    """The requested operation conflicts with saved state."""


class ScenarioValidationError(ScenarioRepositoryError):
    """The scenario contains invalid configuration or usage."""


def _unique_object(pairs):

    result = {}

    for key, value in pairs:

        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")

        result[key] = value

    return result


def _reject_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def _require_fields(document, fields):

    if not isinstance(document, dict):
        raise ValueError("Expected a JSON object.")

    if set(document) != set(fields):
        raise ValueError("Unexpected or missing document fields.")


def _decimal_string(value):

    if not isinstance(value, str):
        raise ValueError("Decimal values must be stored as strings.")

    return Decimal(value)


def _encode_resource(resource):

    return {
        "resource_id": str(resource.resource_id),
        "name": resource.name,
        "resource_type": resource.resource_type.value,
        "region": resource.region,
        "quantity": resource.quantity,
        "pricing_model": resource.pricing_model.value,
        "configuration": {
            key: (
                {"decimal": str(value)}
                if isinstance(value, Decimal)
                else value
            )
            for key, value in resource.configuration.items()
        },
        "usage": {
            key: None if value is None else str(value)
            for key, value in resource.usage.items()
        },
    }


def _decode_resource(document):

    _require_fields(
        document,
        (
            "resource_id",
            "name",
            "resource_type",
            "region",
            "quantity",
            "pricing_model",
            "configuration",
            "usage",
        ),
    )

    configuration = document["configuration"]
    usage = document["usage"]

    if not isinstance(configuration, dict):
        raise ValueError("Invalid resource configuration.")

    if not isinstance(usage, dict):
        raise ValueError("Invalid resource usage.")

    decoded_configuration = {}

    for key, value in configuration.items():

        if isinstance(value, dict):

            _require_fields(value, ("decimal",))

            value = _decimal_string(value["decimal"])

        decoded_configuration[key] = value

    return ResourceConfiguration(
        resource_id=UUID(document["resource_id"]),
        name=document["name"],
        resource_type=ResourceType(document["resource_type"]),
        region=document["region"],
        quantity=document["quantity"],
        pricing_model=PricingModel(document["pricing_model"]),
        configuration=decoded_configuration,
        usage={
            key: None if value is None else _decimal_string(value)
            for key, value in usage.items()
        },
    )


def _encode_scenario(scenario):

    return {
        "schema_version": scenario.schema_version,
        "scenario_id": str(scenario.scenario_id),
        "name": scenario.name,
        "description": scenario.description,
        "revision": scenario.revision,
        "created_at": scenario.created_at.isoformat(),
        "updated_at": scenario.updated_at.isoformat(),
        "resources": [
            _encode_resource(resource)
            for resource in scenario.resources
        ],
    }


def _decode_scenario(document):

    _require_fields(
        document,
        (
            "schema_version",
            "scenario_id",
            "name",
            "description",
            "revision",
            "created_at",
            "updated_at",
            "resources",
        ),
    )

    if not isinstance(document["resources"], list):
        raise ValueError("Invalid scenario resource collection.")

    return InfrastructureScenario(
        schema_version=document["schema_version"],
        scenario_id=UUID(document["scenario_id"]),
        name=document["name"],
        description=document["description"],
        revision=document["revision"],
        created_at=datetime.fromisoformat(document["created_at"]),
        updated_at=datetime.fromisoformat(document["updated_at"]),
        resources=tuple(
            _decode_resource(resource)
            for resource in document["resources"]
        ),
    )


def _validate_for_storage(scenario):

    if not isinstance(scenario, InfrastructureScenario):
        raise TypeError("InfrastructureScenario required.")

    validation = validate_scenario(scenario)

    if not validation.is_valid:

        messages = [
            f"{resource_id}: {issue.message}"
            for resource_id, result in validation.resource_results
            for issue in result.errors
        ]

        raise ScenarioValidationError(" | ".join(messages))

    # Valid but incomplete configurations and empty drafts
    # may be saved without inventing missing usage values.


class ScenarioRepository:

    def __init__(self, runtime_settings=None):

        self.runtime = (
            RuntimeSettings()
            if runtime_settings is None
            else runtime_settings
        )

        self.directory = self.runtime.scenarios_directory

    def _path(self, scenario_id):

        if (
            not isinstance(scenario_id, UUID)
            or scenario_id.int == 0
        ):
            raise ValueError("A nonzero scenario UUID is required.")

        return self.directory / f"{scenario_id}.json"

    def _read(self, scenario_id):

        path = self._path(scenario_id)

        try:

            with path.open("r", encoding="utf-8") as stream:

                document = json.load(
                    stream,
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                )

            scenario = _decode_scenario(document)

            if scenario.scenario_id != scenario_id:
                raise ValueError("Scenario identity mismatch.")

            _validate_for_storage(scenario)

            return scenario

        except FileNotFoundError as error:

            raise ScenarioNotFoundError(
                f"Scenario not found: {scenario_id}"
            ) from error

        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            ArithmeticError,
            ScenarioValidationError,
        ) as error:

            raise ScenarioRepositoryError(
                f"Unable to read scenario {scenario_id}: {error}"
            ) from error

    def _write(self, scenario):

        path = self._path(scenario.scenario_id)
        temporary = None

        try:

            self.directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                prefix=".scenario-",
                suffix=".tmp",
                delete=False,
            ) as stream:

                temporary = Path(stream.name)

                json.dump(
                    _encode_scenario(scenario),
                    stream,
                    indent=2,
                    allow_nan=False,
                )

                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())

            os.replace(temporary, path)
            temporary = None

        except (OSError, ValueError, TypeError) as error:

            raise ScenarioRepositoryError(
                f"Unable to save scenario: {error}"
            ) from error

        finally:

            if temporary is not None:

                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def create(self, scenario):

        _validate_for_storage(scenario)

        if scenario.revision != 1:
            raise ScenarioConflictError(
                "A new scenario must start at revision 1."
            )

        with _LOCK:

            if self._path(scenario.scenario_id).exists():

                raise ScenarioConflictError(
                    "A scenario with this identity already exists."
                )

            self._write(scenario)

        return scenario

    def load(self, scenario_id):

        with _LOCK:
            return self._read(scenario_id)

    def list_scenarios(self):

        with _LOCK:

            scenarios = []

            try:

                for path in self.directory.glob("*.json"):

                    scenario_id = UUID(path.stem)

                    if path.name != f"{scenario_id}.json":
                        raise ValueError(
                            "Noncanonical scenario filename."
                        )

                    scenarios.append(
                        self._read(scenario_id)
                    )

            except (OSError, ValueError) as error:

                raise ScenarioRepositoryError(
                    f"Unable to list saved scenarios: {error}"
                ) from error

            return tuple(sorted(
                scenarios,
                key=lambda scenario: (
                    scenario.updated_at,
                    str(scenario.scenario_id),
                ),
                reverse=True,
            ))

    def update(self, scenario):

        _validate_for_storage(scenario)

        with _LOCK:

            current = self._read(scenario.scenario_id)

            if scenario.revision != current.revision:

                raise ScenarioConflictError(
                    "Scenario revision has changed. "
                    "Reload before saving."
                )

            if scenario.created_at != current.created_at:

                raise ScenarioConflictError(
                    "Scenario creation timestamp cannot change."
                )

            saved = replace(
                scenario,
                revision=current.revision + 1,
                updated_at=max(
                    datetime.now(timezone.utc),
                    current.updated_at,
                ),
            )

            self._write(saved)

            return saved

    def duplicate(self, scenario_id, name):

        with _LOCK:

            original = self._read(scenario_id)
            timestamp = datetime.now(timezone.utc)

            duplicate = InfrastructureScenario(
                scenario_id=uuid4(),
                name=name,
                description=original.description,
                revision=1,
                created_at=timestamp,
                updated_at=timestamp,
                resources=tuple(
                    replace(resource, resource_id=uuid4())
                    for resource in original.resources
                ),
            )

            return self.create(duplicate)

    def delete(self, scenario_id, *, expected_revision):

        if (
            type(expected_revision) is not int
            or expected_revision < 1
        ):
            raise ValueError("A positive revision is required.")

        with _LOCK:

            current = self._read(scenario_id)

            if current.revision != expected_revision:

                raise ScenarioConflictError(
                    "Scenario revision has changed. "
                    "Reload before deleting."
                )

            try:
                self._path(scenario_id).unlink()

            except OSError as error:

                raise ScenarioRepositoryError(
                    f"Unable to delete scenario: {error}"
                ) from error
