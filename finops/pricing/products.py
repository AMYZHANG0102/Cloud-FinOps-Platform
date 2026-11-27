"""Retrieve and validate raw Pricing API product documents.

Financial normalization is intentionally separate.

Original JSON documents are preserved so that price precision,
offer metadata and source attributes remain available.
"""

import json

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from botocore.exceptions import BotoCoreError, ClientError

from finops.pricing.client import UnsafeEndpointError


FORMAT_VERSION = "aws_v1"

DEFAULT_PAGE_SIZE = 100

DEFAULT_MAX_PAGES = 1000

MAX_FILTERS = 50


class PricingProductError(RuntimeError):
    """Structured failure during GetProducts retrieval."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        api_message: str | None = None,
    ) -> None:

        self.operation = "GetProducts"
        self.code = code
        self.http_status = http_status
        self.api_message = api_message

        super().__init__(
            f"{self.operation} [{code}]: {message}"
        )


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{name} must be nonempty text."
        )

    return value


def _reject_duplicate_keys(pairs):
    """Prevent ambiguous JSON caused by duplicate object keys."""

    result = {}

    for key, value in pairs:

        if key in result:
            raise ValueError(
                f"Duplicate JSON object key: {key}"
            )

        result[key] = value

    return result


def _reject_nonfinite_constant(value):
    raise ValueError(
        f"Invalid JSON numeric constant: {value}"
    )


def _decode_json(raw_json: str) -> dict:
    """Decode JSON without introducing binary float conversion."""

    if not isinstance(raw_json, str):
        raise ValueError(
            "A PriceList entry must be a JSON string."
        )

    document = json.loads(
        raw_json,
        parse_float=Decimal,
        parse_constant=_reject_nonfinite_constant,
        object_pairs_hook=_reject_duplicate_keys,
    )

    if not isinstance(document, dict):
        raise ValueError(
            "A product document must be a JSON object."
        )

    return document


def _validate_document(document: dict) -> tuple[str, str]:
    """Validate product identity and the basic document envelope."""

    product = document.get("product")

    if not isinstance(product, dict):
        raise ValueError(
            "Missing or invalid product object."
        )

    sku = _require_text(
        product.get("sku"),
        "product.sku",
    )

    _require_text(
        product.get("productFamily"),
        "product.productFamily",
    )

    attributes = product.get("attributes")

    if not isinstance(attributes, dict):
        raise ValueError(
            "Missing or invalid product attributes."
        )

    for key, value in attributes.items():

        _require_text(key, "attribute name")

        if not isinstance(value, str):
            raise ValueError(
                "Product attribute values must be strings."
            )

    service_identifiers = []

    if "serviceCode" in document:
        service_identifiers.append(
            _require_text(
                document["serviceCode"],
                "serviceCode",
            )
        )

    for key in ("servicecode", "serviceCode"):

        if key in attributes:
            service_identifiers.append(
                _require_text(
                    attributes[key],
                    f"attributes.{key}",
                )
            )

    if not service_identifiers:
        raise ValueError(
            "Product service identity is missing."
        )

    if len(set(service_identifiers)) != 1:
        raise ValueError(
            "Conflicting product service identifiers."
        )

    terms = document.get("terms")

    if not isinstance(terms, dict):
        raise ValueError(
            "Missing or invalid pricing terms."
        )

    return sku, service_identifiers[0]


@dataclass(frozen=True, slots=True)
class ProductFilter:
    """One exact source-attribute filter."""

    field: str
    value: str

    def __post_init__(self):
        _require_text(self.field, "filter field")
        _require_text(self.value, "filter value")

    def to_api_filter(self) -> dict[str, str]:

        return {
            "Type": "TERM_MATCH",
            "Field": self.field,
            "Value": self.value,
        }


@dataclass(frozen=True, slots=True)
class RawPricingProduct:
    """Immutable original product document and validated identity."""

    service_code: str
    sku: str
    raw_json: str

    def __post_init__(self):

        document = _decode_json(self.raw_json)

        sku, service_code = _validate_document(document)

        if sku != self.sku:
            raise ValueError(
                "Product SKU does not match its document."
            )

        if service_code != self.service_code:
            raise ValueError(
                "Product service does not match its document."
            )

    @classmethod
    def from_json(cls, raw_json: str):

        document = _decode_json(raw_json)

        sku, service_code = _validate_document(document)

        return cls(
            service_code=service_code,
            sku=sku,
            raw_json=raw_json,
        )

    def to_document(self) -> dict:
        """Return an independent decoded document."""

        return _decode_json(self.raw_json)


@dataclass(frozen=True, slots=True)
class ProductRetrievalResult:
    """Complete successful product retrieval."""

    service_code: str

    filters: tuple[ProductFilter, ...]

    products: tuple[RawPricingProduct, ...]

    retrieved_at: datetime

    page_count: int

    received_count: int

    duplicate_count: int

    @property
    def product_count(self) -> int:
        return len(self.products)

    @property
    def is_empty(self) -> bool:
        return not self.products


def _prepare_filters(filters) -> tuple[ProductFilter, ...]:

    if not isinstance(filters, (tuple, list)):
        raise ValueError(
            "filters must be a tuple or list."
        )

    if len(filters) > MAX_FILTERS:
        raise ValueError(
            f"No more than {MAX_FILTERS} filters are supported."
        )

    by_field = {}

    for item in filters:

        if not isinstance(item, ProductFilter):
            raise ValueError(
                "Every filter must be a ProductFilter."
            )

        previous = by_field.get(item.field)

        if previous is not None and previous != item:
            raise ValueError(
                f"Conflicting exact filters: {item.field}"
            )

        by_field[item.field] = item

    return tuple(
        by_field[field]
        for field in sorted(by_field)
    )


def _matches_filter(
    product: RawPricingProduct,
    document: dict,
    filter_item: ProductFilter,
) -> bool:
    """Check returned product metadata against the requested filter."""

    metadata = document["product"]
    attributes = metadata["attributes"]

    field = filter_item.field

    if field in ("ServiceCode", "serviceCode", "servicecode"):
        actual = product.service_code

    elif field == "productFamily":
        actual = metadata["productFamily"]

    elif field == "sku":
        actual = product.sku

    else:
        actual = attributes.get(field)

    return actual == filter_item.value


class PricingProducts:
    """Retrieve complete raw product collections from a supplied client."""

    def __init__(
        self,
        client,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ):

        if (
            type(page_size) is not int
            or not 1 <= page_size <= 100
        ):
            raise ValueError(
                "page_size must be between 1 and 100."
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

    def _request_page(self, parameters: dict) -> Mapping:

        try:
            response = self._client.get_products(
                **parameters
            )

        except ClientError as error:

            details = error.response.get("Error", {})

            metadata = error.response.get(
                "ResponseMetadata",
                {},
            )

            raise PricingProductError(
                str(details.get("Code", "UNKNOWN_API_ERROR")),
                "The Pricing API rejected the product request.",
                http_status=metadata.get("HTTPStatusCode"),
                api_message=details.get("Message"),
            ) from error

        except UnsafeEndpointError as error:

            raise PricingProductError(
                "UNSAFE_ENDPOINT",
                "The local endpoint policy blocked the request.",
            ) from error

        except BotoCoreError as error:

            raise PricingProductError(
                type(error).__name__,
                "The SDK could not complete the product request.",
            ) from error

        if not isinstance(response, Mapping):
            raise PricingProductError(
                "INVALID_RESPONSE",
                "The API response is not a mapping.",
            )

        metadata = response.get("ResponseMetadata")

        if not isinstance(metadata, Mapping):
            raise PricingProductError(
                "INVALID_RESPONSE",
                "Response metadata is missing or invalid.",
            )

        status = metadata.get("HTTPStatusCode")

        if type(status) is not int or status != 200:
            raise PricingProductError(
                "UNEXPECTED_HTTP_STATUS",
                "A successful HTTP response was not received.",
                http_status=(
                    status if type(status) is int else None
                ),
            )

        if (
            "FormatVersion" in response
            and response["FormatVersion"] != FORMAT_VERSION
        ):
            raise PricingProductError(
                "UNSUPPORTED_FORMAT",
                "Unexpected product response format.",
            )

        if not isinstance(response.get("PriceList"), list):
            raise PricingProductError(
                "INVALID_RESPONSE",
                "Missing or invalid PriceList collection.",
            )

        return response

    def get_products(
        self,
        service_code: str,
        filters: tuple[ProductFilter, ...] = (),
    ) -> ProductRetrievalResult:
        """Retrieve every page or raise without returning partial data."""

        _require_text(service_code, "service_code")

        filters = _prepare_filters(filters)

        for item in filters:

            if (
                item.field in (
                    "ServiceCode",
                    "serviceCode",
                    "servicecode",
                )
                and item.value != service_code
            ):
                raise ValueError(
                    "Service filter conflicts with requested service."
                )

        base_parameters = {
            "ServiceCode": service_code,
            "FormatVersion": FORMAT_VERSION,
            "MaxResults": self._page_size,
        }

        if filters:

            base_parameters["Filters"] = [
                item.to_api_filter()
                for item in filters
            ]

        products = {}
        decoded_products = {}

        seen_tokens = set()

        next_token = None

        received_count = 0
        duplicate_count = 0

        for page_number in range(
            1,
            self._max_pages + 1,
        ):

            parameters = dict(base_parameters)

            if next_token is not None:
                parameters["NextToken"] = next_token

            response = self._request_page(parameters)

            for raw_json in response["PriceList"]:

                received_count += 1

                try:
                    product = RawPricingProduct.from_json(
                        raw_json
                    )

                    document = product.to_document()

                except (ValueError, TypeError) as error:

                    raise PricingProductError(
                        "INVALID_PRODUCT_DOCUMENT",
                        "A returned product document is invalid.",
                    ) from error

                if product.service_code != service_code:

                    raise PricingProductError(
                        "SERVICE_MISMATCH",
                        "A returned product belongs to another service.",
                    )

                for item in filters:

                    if not _matches_filter(
                        product,
                        document,
                        item,
                    ):
                        raise PricingProductError(
                            "FILTER_MISMATCH",
                            "A returned product does not match "
                            "the requested exact filters.",
                        )

                sku = product.sku

                if sku in products:

                    if decoded_products[sku] != document:

                        raise PricingProductError(
                            "CONFLICTING_PRODUCT",
                            f"Conflicting product documents: {sku}",
                        )

                    duplicate_count += 1
                    continue

                products[sku] = product

                decoded_products[sku] = document

            token = response.get("NextToken")

            if token is None or token == "":

                return ProductRetrievalResult(
                    service_code=service_code,
                    filters=filters,
                    products=tuple(
                        products[sku]
                        for sku in sorted(products)
                    ),
                    retrieved_at=datetime.now(timezone.utc),
                    page_count=page_number,
                    received_count=received_count,
                    duplicate_count=duplicate_count,
                )

            if not isinstance(token, str) or not token.strip():

                raise PricingProductError(
                    "INVALID_PAGINATION_TOKEN",
                    "The API returned an invalid pagination token.",
                )

            if token in seen_tokens:

                raise PricingProductError(
                    "REPEATED_PAGINATION_TOKEN",
                    "The API repeated a pagination token.",
                )

            seen_tokens.add(token)
            next_token = token

        raise PricingProductError(
            "PAGE_LIMIT_EXCEEDED",
            "Product retrieval exceeded the configured page limit.",
        )
