"""Explicit local Floci client configuration.

Only Pricing and EC2 clients are constructed by this module.
Clients use dummy credentials and validated IPv4 loopback
endpoints rather than production AWS endpoints.

Individual pricing operations belong to subsequent services.
"""

import re

from dataclasses import dataclass
from urllib.parse import urlsplit

import boto3

from botocore.client import BaseClient
from botocore.config import Config


DEFAULT_FLOCI_ENDPOINT = "http://127.0.0.1:4566"

DEFAULT_REGION = "us-east-1"

PRICING_API_REGION = "us-east-1"

LOCAL_ACCESS_KEY = "test"

LOCAL_SECRET_KEY = "test"

SUPPORTED_CLIENTS = frozenset({"pricing", "ec2"})


class UnsafeEndpointError(ValueError):
    """An endpoint violates the local emulator policy."""


def normalize_local_endpoint(endpoint: str) -> str:
    """Validate and canonicalize a local HTTP emulator endpoint."""

    if not isinstance(endpoint, str):
        raise UnsafeEndpointError(
            "The Floci endpoint must be text."
        )

    match = re.fullmatch(
        r"http://(?:localhost|127\.0\.0\.1):([0-9]{1,5})/?",
        endpoint,
        flags=re.ASCII,
    )

    if match is None:
        raise UnsafeEndpointError(
            "Only explicit local HTTP loopback endpoints "
            "are supported."
        )

    port = int(match.group(1))

    if not 1 <= port <= 65535:
        raise UnsafeEndpointError(
            "The endpoint port must be between 1 and 65535."
        )

    return f"http://127.0.0.1:{port}"


def validate_region(region: str) -> str:
    """Validate the syntax of an AWS-style region identifier."""

    if (
        not isinstance(region, str)
        or re.fullmatch(
            r"[a-z]{2}(?:-[a-z0-9]+)+-[0-9]+",
            region,
            flags=re.ASCII,
        ) is None
    ):
        raise ValueError(
            "Invalid AWS region identifier."
        )

    return region


@dataclass(frozen=True, slots=True)
class FlociClientSettings:
    """Immutable settings for local emulator clients."""

    endpoint_url: str = DEFAULT_FLOCI_ENDPOINT

    region: str = DEFAULT_REGION

    connect_timeout: int = 3

    read_timeout: int = 10

    total_max_attempts: int = 3

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "endpoint_url",
            normalize_local_endpoint(self.endpoint_url),
        )

        validate_region(self.region)

        for name in (
            "connect_timeout",
            "read_timeout",
            "total_max_attempts",
        ):
            value = getattr(self, name)

            if type(value) is not int or value <= 0:
                raise ValueError(
                    f"{name} must be a positive integer."
                )

        if self.total_max_attempts > 5:
            raise ValueError(
                "total_max_attempts must not exceed 5."
            )


def build_client_config(
    settings: FlociClientSettings,
) -> Config:
    """Build explicit Botocore transport configuration."""

    if not isinstance(settings, FlociClientSettings):
        raise TypeError(
            "settings must be FlociClientSettings."
        )

    return Config(
        signature_version="v4",
        connect_timeout=settings.connect_timeout,
        read_timeout=settings.read_timeout,
        retries={
            "mode": "standard",
            "total_max_attempts": settings.total_max_attempts,
        },
        proxies={},
        ignore_configured_endpoint_urls=True,
        use_fips_endpoint=False,
        use_dualstack_endpoint=False,
    )


def ensure_local_request(
    request_url: str,
    endpoint_url: str,
) -> None:
    """Reject outgoing requests targeting an unexpected origin."""

    expected = urlsplit(
        normalize_local_endpoint(endpoint_url)
    )

    if (
        not isinstance(request_url, str)
        or any(ord(character) <= 32 for character in request_url)
        or "\x7f" in request_url
    ):
        raise UnsafeEndpointError(
            "Invalid outgoing request URL."
        )

    try:
        actual = urlsplit(request_url)
    except ValueError as error:
        raise UnsafeEndpointError(
            "Invalid outgoing request URL."
        ) from error

    if (
        actual.scheme != expected.scheme
        or actual.netloc != expected.netloc
        or actual.fragment
    ):
        raise UnsafeEndpointError(
            "Outgoing request blocked: unexpected endpoint."
        )


def create_floci_client(
    service_name: str,
    settings: FlociClientSettings | None = None,
) -> BaseClient:
    """Create an explicitly configured local Pricing or EC2 client."""

    if (
        not isinstance(service_name, str)
        or service_name not in SUPPORTED_CLIENTS
    ):
        raise ValueError(
            "Only pricing and ec2 clients are supported."
        )

    if settings is None:
        settings = FlociClientSettings()

    if not isinstance(settings, FlociClientSettings):
        raise TypeError(
            "settings must be FlociClientSettings."
        )

    region = (
        PRICING_API_REGION
        if service_name == "pricing"
        else settings.region
    )

    # Use a dedicated session, not a global default session.
    # Explicit dummy credentials avoid credential-chain lookup.
    session = boto3.session.Session(
        aws_access_key_id=LOCAL_ACCESS_KEY,
        aws_secret_access_key=LOCAL_SECRET_KEY,
        region_name=region,
    )

    client = session.client(
        service_name,
        region_name=region,
        endpoint_url=settings.endpoint_url,
        config=build_client_config(settings),
    )

    try:
        # Validate the endpoint returned by client construction.
        ensure_local_request(
            client.meta.endpoint_url,
            settings.endpoint_url,
        )

        # Validate the final destination before each SDK send.
        def guard_request(request, **kwargs):
            ensure_local_request(
                request.url,
                settings.endpoint_url,
            )

        client.meta.events.register(
            "before-send",
            guard_request,
        )

    except Exception:
        client.close()
        raise

    return client


def create_pricing_client(
    settings: FlociClientSettings | None = None,
) -> BaseClient:
    """Create a local AWS Pricing API client."""

    return create_floci_client(
        "pricing",
        settings,
    )


def create_ec2_client(
    settings: FlociClientSettings | None = None,
) -> BaseClient:
    """Create a local EC2 API client."""

    return create_floci_client(
        "ec2",
        settings,
    )
