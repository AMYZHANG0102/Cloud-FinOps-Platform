"""Reusable discovery operations for the local Pricing API.

Discovered services and attributes describe advertised catalogue
capabilities. They do not establish actual product price availability.

All SDK operations use an explicitly supplied client. The caller
owns the client lifecycle.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError

from finops.pricing.client import UnsafeEndpointError


DEFAULT_PAGE_SIZE = 100

DEFAULT_MAX_PAGES = 1000


class PricingDiscoveryError(RuntimeError):
    """Structured failure during a pricing discovery operation."""

    def __init__(
        self,
        operation: str,
        code: str,
        message: str,
        http_status: int | None = None,
    ) -> None:
        self.operation = operation
        self.code = code
        self.http_status = http_status

        super().__init__(
            f"{operation} [{code}]: {message}"
        )


def _require_text(value: object, name: str) -> str:
    """Validate a required nonempty string."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{name} must be nonempty text."
        )

    return value


@dataclass(frozen=True, slots=True)
class ServiceDescription:
    """Advertised Pricing API service metadata."""

    service_code: str
    attribute_names: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(
            self.service_code,
            "service_code",
        )

        if not isinstance(
            self.attribute_names,
            (tuple, list),
        ):
            raise ValueError(
                "attribute_names must be a tuple or list."
            )

        names = tuple(
            sorted(
                {
                    _require_text(name, "attribute name")
                    for name in self.attribute_names
                }
            )
        )

        object.__setattr__(
            self,
            "attribute_names",
            names,
        )


class PricingDiscovery:
    """Discover pricing services and their advertised attributes."""

    def __init__(
        self,
        client,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:

        if (
            type(page_size) is not int
            or not 1 <= page_size <= 100
        ):
            raise ValueError(
                "page_size must be an integer between 1 and 100."
            )

        if (
            type(max_pages) is not int
            or max_pages <= 0
        ):
            raise ValueError(
                "max_pages must be a positive integer."
            )

        self._client = client
        self._page_size = page_size
        self._max_pages = max_pages

    def _collect_pages(
        self,
        operation: str,
        method: Callable,
        result_key: str,
        parameters: dict,
    ) -> tuple:
        """Retrieve all pages or fail without returning partial data."""

        collected = []
        seen_tokens = set()
        next_token = None

        for _ in range(self._max_pages):

            request = {
                **parameters,
                "MaxResults": self._page_size,
            }

            if next_token is not None:
                request["NextToken"] = next_token

            try:
                response = method(**request)

            except ClientError as error:
                details = error.response.get("Error", {})
                metadata = error.response.get(
                    "ResponseMetadata",
                    {},
                )

                code = details.get(
                    "Code",
                    "UNKNOWN_API_ERROR",
                )

                status = metadata.get("HTTPStatusCode")

                raise PricingDiscoveryError(
                    operation=operation,
                    code=str(code),
                    message="The Pricing API rejected the request.",
                    http_status=status,
                ) from error

            except UnsafeEndpointError as error:
                raise PricingDiscoveryError(
                    operation,
                    "UNSAFE_ENDPOINT",
                    "The local endpoint policy blocked the request.",
                ) from error

            except BotoCoreError as error:
                raise PricingDiscoveryError(
                    operation,
                    type(error).__name__,
                    "The SDK could not complete the request.",
                ) from error

            if not isinstance(response, Mapping):
                raise PricingDiscoveryError(
                    operation,
                    "INVALID_RESPONSE",
                    "The response is not a mapping.",
                )

            metadata = response.get("ResponseMetadata")

            if not isinstance(metadata, Mapping):
                raise PricingDiscoveryError(
                    operation,
                    "INVALID_RESPONSE",
                    "Response metadata is missing or invalid.",
                )

            status = metadata.get("HTTPStatusCode")

            if type(status) is not int or status != 200:
                raise PricingDiscoveryError(
                    operation,
                    "UNEXPECTED_HTTP_STATUS",
                    "A successful HTTP response was not received.",
                    http_status=(
                        status if type(status) is int else None
                    ),
                )

            items = response.get(result_key)

            if not isinstance(items, list):
                raise PricingDiscoveryError(
                    operation,
                    "INVALID_RESPONSE",
                    f"Missing or invalid {result_key} collection.",
                )

            collected.extend(items)

            token = response.get("NextToken")

            if token is None or token == "":
                return tuple(collected)

            if not isinstance(token, str) or not token.strip():
                raise PricingDiscoveryError(
                    operation,
                    "INVALID_PAGINATION_TOKEN",
                    "The API returned an invalid pagination token.",
                )

            if token in seen_tokens:
                raise PricingDiscoveryError(
                    operation,
                    "REPEATED_PAGINATION_TOKEN",
                    "The API repeated a pagination token.",
                )

            seen_tokens.add(token)
            next_token = token

        raise PricingDiscoveryError(
            operation,
            "PAGE_LIMIT_EXCEEDED",
            "Pagination exceeded the configured safety limit.",
        )

    def list_services(
        self,
        service_code: str | None = None,
    ) -> tuple[ServiceDescription, ...]:
        """Return validated service descriptions from every page."""

        parameters = {}

        if service_code is not None:
            parameters["ServiceCode"] = _require_text(
                service_code,
                "service_code",
            )

        items = self._collect_pages(
            operation="DescribeServices",
            method=self._client.describe_services,
            result_key="Services",
            parameters=parameters,
        )

        services = {}

        for item in items:

            if not isinstance(item, Mapping):
                raise PricingDiscoveryError(
                    "DescribeServices",
                    "INVALID_RESPONSE",
                    "A service description is not a mapping.",
                )

            try:
                names = item["AttributeNames"]

                if not isinstance(names, list):
                    raise ValueError(
                        "AttributeNames must be a list."
                    )

                description = ServiceDescription(
                    service_code=item["ServiceCode"],
                    attribute_names=tuple(names),
                )

            except (KeyError, ValueError) as error:
                raise PricingDiscoveryError(
                    "DescribeServices",
                    "INVALID_RESPONSE",
                    "A service description is missing valid fields.",
                ) from error

            if (
                service_code is not None
                and description.service_code != service_code
            ):
                raise PricingDiscoveryError(
                    "DescribeServices",
                    "SERVICE_MISMATCH",
                    "A returned service does not match the request.",
                )

            previous = services.get(
                description.service_code
            )

            if (
                previous is not None
                and previous != description
            ):
                raise PricingDiscoveryError(
                    "DescribeServices",
                    "CONFLICTING_SERVICE_METADATA",
                    "Conflicting descriptions share a service code.",
                )

            services[description.service_code] = description

        return tuple(
            services[code]
            for code in sorted(services)
        )

    def list_attributes(
        self,
        service_code: str,
    ) -> tuple[str, ...]:
        """Return the advertised attribute names for one service."""

        _require_text(service_code, "service_code")

        services = self.list_services(
            service_code=service_code
        )

        if not services:
            raise PricingDiscoveryError(
                "DescribeServices",
                "SERVICE_NOT_FOUND",
                "No matching service description was returned.",
            )

        return services[0].attribute_names

    def list_attribute_values(
        self,
        service_code: str,
        attribute_name: str,
    ) -> tuple[str, ...]:
        """Return the advertised values for one service attribute."""

        parameters = {
            "ServiceCode": _require_text(
                service_code,
                "service_code",
            ),
            "AttributeName": _require_text(
                attribute_name,
                "attribute_name",
            ),
        }

        items = self._collect_pages(
            operation="GetAttributeValues",
            method=self._client.get_attribute_values,
            result_key="AttributeValues",
            parameters=parameters,
        )

        values = set()

        for item in items:

            if not isinstance(item, Mapping):
                raise PricingDiscoveryError(
                    "GetAttributeValues",
                    "INVALID_RESPONSE",
                    "An attribute value is not a mapping.",
                )

            try:
                value = _require_text(
                    item["Value"],
                    "attribute value",
                )

            except (KeyError, ValueError) as error:
                raise PricingDiscoveryError(
                    "GetAttributeValues",
                    "INVALID_RESPONSE",
                    "An attribute value is missing or invalid.",
                ) from error

            values.add(value)

        return tuple(sorted(values))
