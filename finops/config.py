"""Shared local runtime configuration for FinOps modules."""

from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_RUNTIME_ROOT = PROJECT_ROOT / ".finops-runtime"

DEFAULT_CATALOGUE_TTL_SECONDS = 15 * 60

DEFAULT_SPOT_TTL_SECONDS = 5 * 60


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Validated runtime settings without filesystem side effects."""

    runtime_root: Path = field(
        default_factory=lambda: DEFAULT_RUNTIME_ROOT
    )

    catalogue_ttl_seconds: int = DEFAULT_CATALOGUE_TTL_SECONDS

    spot_ttl_seconds: int = DEFAULT_SPOT_TTL_SECONDS

    def __post_init__(self) -> None:
        root = Path(self.runtime_root).expanduser()

        if not root.is_absolute():
            root = PROJECT_ROOT / root

        object.__setattr__(
            self,
            "runtime_root",
            root.resolve(),
        )

        for name in (
            "catalogue_ttl_seconds",
            "spot_ttl_seconds",
        ):
            value = getattr(self, name)

            if type(value) is not int or value <= 0:
                raise ValueError(
                    f"{name} must be a positive integer."
                )

    @property
    def pricing_directory(self) -> Path:
        return self.runtime_root / "pricing"

    @property
    def scenarios_directory(self) -> Path:
        return self.runtime_root / "scenarios"

    @property
    def snapshots_directory(self) -> Path:
        return self.runtime_root / "snapshots"

    @property
    def estimates_directory(self) -> Path:
        return self.runtime_root / "estimates"

    @property
    def catalogue_cache_path(self) -> Path:
        return self.pricing_directory / "catalogue_cache.json"

    @property
    def spot_cache_path(self) -> Path:
        return self.pricing_directory / "spot_cache.json"


def get_runtime_settings(
    runtime_root: Path | None = None,
) -> RuntimeSettings:
    """Construct default or explicitly configured runtime settings."""

    if runtime_root is None:
        return RuntimeSettings()

    return RuntimeSettings(runtime_root=runtime_root)
