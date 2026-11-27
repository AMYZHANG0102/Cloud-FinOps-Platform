"""Resolve applicable unit prices without estimating expenditure.

Floci is the primary source. Documented reference pricing is
optional and never substitutes for unexpected retrieval failures.
"""

from dataclasses import dataclass, replace
from decimal import Decimal

from botocore.exceptions import BotoCoreError, ClientError

from finops.pricing.cache import (
    PricingCacheError,
    PricingCatalogueCache,
)

from finops.pricing.client import (
    UnsafeEndpointError,
    create_pricing_client,
    validate_region,
)

from finops.pricing.discovery import (
    PricingDiscovery,
    PricingDiscoveryError,
)

from finops.pricing.models import (
    PricingModel,
    PricingQuery,
    PricingResolution,
    PricingSource,
    ResolutionStatus,
)

from finops.pricing.products import PricingProductError

from finops.pricing.reference import (
    ReferenceCatalogueError,
    load_reference_rates,
)


@dataclass(frozen=True, slots=True)
class ComponentRule:
    service: str
    product_family: str
    unit: str
    required_attributes: tuple[str, ...]
    optional_attributes: tuple[str, ...] = ()
    source_attributes: tuple[tuple[str, str], ...] = ()


# Application resource identifiers and component-specific matching.
# Each rule defines the expected billing unit explicitly.

RULES = {
    ("ec2_instance", "compute"): ComponentRule(
        "AmazonEC2", "Compute Instance", "Hrs",
        ("instanceType", "operatingSystem", "tenancy"),
        ("preInstalledSw",),
    ),
    ("ebs_volume", "storage"): ComponentRule(
        "AmazonEC2", "Storage", "GiB-Mo",
        ("volumeType",),
    ),
    ("ebs_volume", "additional_iops"): ComponentRule(
        "AmazonEC2", "Storage", "IOPS-Mo",
        ("volumeType",),
    ),
    ("ebs_volume", "additional_throughput"): ComponentRule(
        "AmazonEC2", "Storage", "MiBps-Mo",
        ("volumeType",),
    ),
    ("s3_bucket", "storage"): ComponentRule(
        "AmazonS3", "Storage", "GB-Mo",
        ("volumeType",),
        ("storageClass",),
    ),
    ("function", "requests"): ComponentRule(
        "AWSLambda", "Serverless", "Requests",
        (),
        (),
        (("group", "AWS-Lambda-Requests"),),
    ),
    ("function", "duration"): ComponentRule(
        "AWSLambda", "Serverless", "GB-Second",
        ("architecture", "executionMode"),
        (),
        (("group", "AWS-Lambda-Duration"),),
    ),
    ("function", "ephemeral_storage"): ComponentRule(
        "AWSLambda", "Serverless", "GB-Second",
        ("executionMode",),
        (),
        (("group", "AWS-Lambda-Storage"),),
    ),
    ("table", "write_requests"): ComponentRule(
        "AmazonDynamoDB", "Database", "WRU",
        ("tableClass", "capacityMode"),
    ),
    ("table", "read_requests"): ComponentRule(
        "AmazonDynamoDB", "Database", "RRU",
        ("tableClass", "capacityMode"),
    ),
    ("table", "storage"): ComponentRule(
        "AmazonDynamoDB", "Database", "GB-Mo",
        ("tableClass", "capacityMode"),
    ),
}


INVALID_PRODUCT_ERRORS = frozenset({
    "INVALID_RESPONSE",
    "UNEXPECTED_HTTP_STATUS",
    "INVALID_PRODUCT_DOCUMENT",
    "UNSUPPORTED_FORMAT",
    "SERVICE_MISMATCH",
    "FILTER_MISMATCH",
})


class PricingResolver:
    """Resolve one resource billing component at a time."""

    def __init__(self, cache=None, reference_rates=None):

        self.cache = (
            PricingCatalogueCache()
            if cache is None
            else cache
        )

        self.reference_rates = (
            None
            if reference_rates is None
            else tuple(reference_rates)
        )

    def _result(
        self, query, status, *,
        records=(), missing=(), diagnostics=(), warnings=(),
    ):
        return PricingResolution(
            query=query,
            status=status,
            records=tuple(records),
            missing_components=tuple(missing),
            diagnostics=tuple(diagnostics),
            warnings=tuple(warnings),
        )

    def _validate_query(self, query, usage):

        validate_region(query.region)

        if query.currency != "USD":
            raise ValueError("Only USD resolution is supported.")

        if usage is not None and (
            not isinstance(usage, Decimal)
            or not usage.is_finite()
            or usage < 0
        ):
            raise ValueError(
                "Usage must be a finite nonnegative Decimal."
            )

        rule = RULES.get(
            (query.resource_type, query.cost_component)
        )

        if rule is None:
            return None

        if query.service_code != rule.service:
            raise ValueError(
                "Resource type and service do not agree."
            )

        provided = set(query.attributes)

        required = set(rule.required_attributes)

        allowed = required | set(rule.optional_attributes)

        if not required.issubset(provided):
            raise ValueError(
                "Missing required pricing configuration attributes."
            )

        if not provided.issubset(allowed):
            raise ValueError(
                "Unexpected pricing configuration attributes."
            )

        return rule

    def _advertised_services(self):

        client = create_pricing_client(
            self.cache.client_settings
        )

        try:
            return {
                service.service_code
                for service in PricingDiscovery(
                    client
                ).list_services()
            }

        finally:
            client.close()

    def _load_primary(self, query, force_refresh):

        if not force_refresh:

            cached = self.cache.load(
                query.service_code
            )

            if cached is not None and cached.is_fresh:

                return (
                    cached.catalogue.records,
                    ("Fresh local Floci catalogue used.",),
                )

        catalogue = self.cache.refresh(
            query.service_code
        )

        return (
            catalogue.records,
            ("Live Floci catalogue retrieved.",),
        )

    def _select(
        self, records, query, rule, *, primary,
    ):
        """Return matching offers or reject unsafe ambiguity."""

        candidates = []

        for record in records:

            if (
                record.service_code != query.service_code
                or record.region != query.region
                or record.pricing_model != query.pricing_model
                or record.product_family != rule.product_family
            ):
                continue

            expected_source = (
                PricingSource.FLOCI_PRICING_API
                if primary
                else PricingSource.REFERENCE_DATA
            )

            if record.source != expected_source:
                raise ValueError("Unexpected pricing source.")

            attributes = dict(query.attributes)

            if primary:
                attributes.update(
                    dict(rule.source_attributes)
                )

            # A known conflicting attribute excludes the offer.
            # Missing identity attributes on an otherwise
            # plausible offer must not be guessed.

            if any(
                key in record.attributes
                and record.attributes[key] != value
                for key, value in attributes.items()
            ):
                continue

            relevant = tuple(
                dimension
                for dimension in record.dimensions
                if dimension.cost_component
                == query.cost_component
                and dimension.currency == query.currency
            )

            unknown = any(
                dimension.cost_component is None
                and dimension.currency == query.currency
                and dimension.unit == rule.unit
                for dimension in record.dimensions
            )

            if unknown:
                raise ValueError(
                    f"Unclassified matching billing dimension: "
                    f"{record.sku}"
                )

            if not relevant:
                continue

            if not all(
                record.attributes.get(key) == value
                for key, value in attributes.items()
            ):
                raise ValueError(
                    f"Missing configuration metadata: {record.sku}"
                )

            if any(
                dimension.unit != rule.unit
                or dimension.applies_to
                for dimension in relevant
            ):
                raise ValueError(
                    f"Unsupported billing unit or applicability: "
                    f"{record.sku}"
                )

            selected = replace(
                record,
                dimensions=tuple(
                    sorted(
                        relevant,
                        key=lambda item: item.begin_range,
                    )
                ),
            )

            if selected not in candidates:
                candidates.append(selected)

        return tuple(candidates)

    def _resolve_schedule(
        self, query, candidates, usage, diagnostics,
    ):

        if len(candidates) > 1:

            return self._result(
                query,
                ResolutionStatus.AMBIGUOUS,
                diagnostics=diagnostics + (
                    "Multiple distinct pricing offers match.",
                ),
            )

        record, = candidates

        boundary = Decimal("0")

        for dimension in record.dimensions:

            if (
                boundary is None
                or dimension.begin_range != boundary
            ):
                return self._result(
                    query,
                    ResolutionStatus.INVALID,
                    diagnostics=diagnostics + (
                        "Pricing ranges overlap or contain gaps.",
                    ),
                )

            boundary = dimension.end_range

        warnings = tuple(record.assumptions)

        if boundary is not None:

            warnings += (
                f"Available pricing coverage ends at "
                f"{format(boundary, 'f')} "
                f"{record.dimensions[0].unit}.",
            )

            if usage is not None and usage > boundary:

                return self._result(
                    query,
                    ResolutionStatus.PARTIAL,
                    records=(record,),
                    missing=(query.cost_component,),
                    diagnostics=diagnostics + (
                        f"Unpriced usage: "
                        f"{format(usage - boundary, 'f')}",
                    ),
                    warnings=warnings,
                )

            if usage is None:

                warnings += (
                    "Requested usage was not supplied; "
                    "complete usage coverage is not established.",
                )

        return self._result(
            query,
            ResolutionStatus.RESOLVED,
            records=(record,),
            diagnostics=diagnostics,
            warnings=warnings,
        )

    def resolve(
        self,
        query: PricingQuery,
        *,
        usage: Decimal | None = None,
        allow_reference: bool = False,
        force_refresh: bool = False,
    ) -> PricingResolution:

        if not isinstance(query, PricingQuery):
            raise TypeError("A PricingQuery is required.")

        if (
            type(allow_reference) is not bool
            or type(force_refresh) is not bool
        ):
            raise TypeError("Boolean resolution policies required.")

        try:
            rule = self._validate_query(
                query, usage
            )

        except ValueError as error:

            return self._result(
                query,
                ResolutionStatus.INVALID,
                diagnostics=(str(error),),
            )

        if (
            rule is None
            or query.pricing_model
            != PricingModel.ON_DEMAND
        ):
            return self._result(
                query,
                ResolutionStatus.UNSUPPORTED,
                diagnostics=(
                    "This resource component or pricing model "
                    "is not supported by the current resolver.",
                ),
            )

        primary_status = ResolutionStatus.UNAVAILABLE

        diagnostics = ()

        try:

            records, diagnostics = self._load_primary(
                query, force_refresh
            )

        except PricingProductError as error:

            # InvalidParameterException by itself is insufficient.
            # Require the specific observed service rejection
            # and independent successful discovery confirmation.

            if (
                error.code == "InvalidParameterException"
                and error.http_status == 400
                and error.api_message in (
                    "Invalid ServiceCode",
                    f"Invalid ServiceCode: {query.service_code}",
                )
            ):

                try:
                    advertised = self._advertised_services()

                except (
                    PricingDiscoveryError,
                    BotoCoreError,
                    ClientError,
                    UnsafeEndpointError,
                ) as discovery_error:

                    return self._result(
                        query,
                        ResolutionStatus.API_ERROR,
                        diagnostics=(
                            str(error),
                            str(discovery_error),
                        ),
                    )

                if query.service_code in advertised:

                    return self._result(
                        query,
                        ResolutionStatus.API_ERROR,
                        diagnostics=(
                            str(error),
                            "Rejected service is still advertised.",
                        ),
                    )

                primary_status = ResolutionStatus.UNSUPPORTED

                diagnostics = (
                    f"Floci rejected {query.service_code}.",
                    "Service absent from successful discovery.",
                )

                records = ()

            else:

                status = ResolutionStatus.API_ERROR

                if error.code in INVALID_PRODUCT_ERRORS:
                    status = ResolutionStatus.INVALID

                elif error.code == "CONFLICTING_PRODUCT":
                    status = ResolutionStatus.AMBIGUOUS

                return self._result(
                    query,
                    status,
                    diagnostics=(str(error),),
                )

        except PricingCacheError as error:

            return self._result(
                query,
                ResolutionStatus.INVALID,
                diagnostics=(str(error),),
            )

        except (
            BotoCoreError,
            ClientError,
            UnsafeEndpointError,
        ) as error:

            return self._result(
                query,
                ResolutionStatus.API_ERROR,
                diagnostics=(type(error).__name__,),
            )

        try:

            candidates = self._select(
                records, query, rule, primary=True
            )

            if candidates:

                return self._resolve_schedule(
                    query, candidates, usage, diagnostics
                )

            diagnostics += (
                "No exact applicable Floci rate found.",
            )

            if not allow_reference:

                return self._result(
                    query,
                    primary_status,
                    diagnostics=diagnostics + (
                        "Supplementary reference pricing is disabled.",
                    ),
                )

            references = (
                load_reference_rates()
                if self.reference_rates is None
                else self.reference_rates
            )

            reference_records = tuple(
                item.record
                for item in references
                if item.resource_type == query.resource_type
            )

            candidates = self._select(
                reference_records,
                query,
                rule,
                primary=False,
            )

            if candidates:

                return self._resolve_schedule(
                    query,
                    candidates,
                    usage,
                    diagnostics + (
                        "Documented AWS reference pricing selected.",
                    ),
                )

            return self._result(
                query,
                primary_status,
                diagnostics=diagnostics + (
                    "No exact applicable reference rate found.",
                ),
            )

        except (
            ValueError,
            ReferenceCatalogueError,
        ) as error:

            return self._result(
                query,
                ResolutionStatus.INVALID,
                diagnostics=diagnostics + (
                    str(error),
                ),
            )
