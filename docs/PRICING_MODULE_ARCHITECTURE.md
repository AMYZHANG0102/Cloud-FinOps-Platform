# Pricing and Infrastructure Module Architecture

## 1. Document Status

| Property | Value |
|---|---|
| Project | Cloud FinOps Platform |
| Scope | M1, M3, M4 and M5 |
| Checkpoint | M0.6A.2 |
| Status | Proposed architecture |
| Baseline | c521cb9 |
| Date | 2026-11-27 |

This document establishes the proposed software architecture
for the pricing and infrastructure estimation modules.

It will be extended during the shared data contract,
financial design and implementation foundation checkpoints.

Shared integration conventions remain subject to team
coordination.

## 2. Architecture Objectives

The architecture should:

- Separate Streamlit presentation from application logic.
- Provide reusable pricing retrieval and resolution.
- Support validated hypothetical infrastructure scenarios.
- Perform consistent and testable financial calculations.
- Preserve pricing sources and estimation assumptions.
- Support integration with other project modules.
- Remain proportionate to the term project requirements.

The system will be implemented as a modular monolithic
Python application rather than as distributed microservices.

## 3. Technical Baseline

The verified environment consists of:

- Python 3.14.6.
- Streamlit 1.67.0.
- Boto3 1.44.12.
- Floci 2.5.0 Community Edition.
- Local Docker-based Floci environment.
- Local endpoint http://localhost:4566.

The detailed pricing investigation is documented in:

[FLOCI_PRICING_CAPABILITIES.md](FLOCI_PRICING_CAPABILITIES.md)

The investigation confirmed five On-Demand pricing
dimensions and six EC2 Spot price observations.

The observed catalogue limitations require documented
supplementary pricing and explicit missing-price handling.

## 4. Repository Organization

The following structure is proposed for the assigned
modules. Other team members may introduce additional
packages, pages, datasets and tests.

```text
Cloud-FinOps-Platform/
|-- app.py
|-- start_floci.py
|-- docker-compose.yml
|-- requirements.txt
|-- README.md
|-- .gitignore
|-- docs/
|   |-- FLOCI_PRICING_CAPABILITIES.md
|   `-- PRICING_MODULE_ARCHITECTURE.md
|-- pages/
|   |-- 01_Pricing_Explorer.py
|   |-- 03_Infrastructure_Builder.py
|   |-- 04_Cost_Estimator.py
|   `-- 05_Pricing_Comparison.py
|-- finops/
|   |-- __init__.py
|   |-- pricing/
|   |-- infrastructure/
|   |-- estimation/
|   `-- comparison/
|-- data/
|   `-- pricing/
`-- tests/
    |-- pricing/
    |-- infrastructure/
    |-- estimation/
    `-- comparison/
```

The proposed filenames use module identifiers for clarity.
Final Streamlit navigation ordering and naming conventions
will be coordinated with the team.

The listed application directories and packages are proposed.
They are not claimed to have been implemented.

## 5. Module Ownership Boundaries

| Module | Responsibility |
|---|---|
| M1 - Cloud Service Pricing Explorer | Assigned implementation |
| M3 - Infrastructure Configuration Builder | Assigned implementation |
| M4 - Infrastructure Cost Estimator | Assigned implementation |
| M5 - Cloud Pricing Model Comparison | Assigned implementation |
| M2 - Cost Explorer | External team module |
| M6 - Workload Simulator | External team module |
| M7 - Cost Optimization Engine | External team module |
| M8 - Cost Reporting | External team module |
| M9 - Budget Management | External team module |
| M10 - Resource Utilization | External team module |
| M11 - Cost Allocation | External team module |
| M12 - Scaling Analysis | External team module |
| M13 - Storage and Backup | External team module |

The application entry point, navigation, startup helper,
dependencies and deployment configuration are shared
project concerns.

External module integration does not transfer ownership
of those modules to the pricing and infrastructure scope.

## 6. Logical Architecture

### 6.1 Presentation Layer

The Streamlit presentation layer handles:

- User input.
- Forms and selectors.
- Resource configuration editing.
- Dashboard metrics.
- Tables and charts.
- Validation messages.
- Scenario selection.
- Display of pricing sources and estimation limitations.

Financial calculations and AWS API operations should be
delegated to reusable Python components.

### 6.2 Pricing Package

Proposed namespace: finops.pricing

Responsibilities:

- Local Floci client configuration.
- Pricing service discovery.
- Attribute and product retrieval.
- Pagination and response validation.
- Pricing record normalization.
- Spot price history retrieval.
- Supplementary pricing access.
- Exact configuration matching.
- Pricing source attribution.
- Missing-price and API-error handling.

### 6.3 Infrastructure Package

Proposed namespace: finops.infrastructure

Responsibilities:

- Resource configuration models.
- Service-specific configuration validation.
- Infrastructure scenario models.
- Scenario creation and editing.
- Scenario persistence and retrieval.
- Transfer of validated configurations to the estimator.

The builder defines hypothetical resources. It must not
provision actual AWS infrastructure.

### 6.4 Estimation Package

Proposed namespace: finops.estimation

Responsibilities:

- Resolve applicable pricing dimensions.
- Calculate resource-level expenditure.
- Calculate service-level expenditure.
- Calculate hourly costs where applicable.
- Calculate daily, monthly and annual estimates.
- Account for usage quantities and billing units.
- Preserve cost component provenance.
- Identify incomplete financial estimates.
- Produce reusable structured estimation results.

### 6.5 Comparison Package

Proposed namespace: finops.comparison

Responsibilities:

- Compare applicable pricing models.
- Evaluate On-Demand costs.
- Evaluate available Spot price observations.
- Evaluate documented Reserved Instance assumptions.
- Evaluate documented Savings Plans assumptions.
- Compare applicable storage pricing tiers.
- Calculate absolute and percentage savings.
- Explain model conditions and financial limitations.

## 7. Dependency Rules

Presentation components may depend on application
and financial components.

Financial components must not import Streamlit pages
or rely on Streamlit session state.

The infrastructure package owns infrastructure
configuration and scenario contracts.

The pricing package owns pricing retrieval and
normalized pricing contracts.

The estimation package may consume infrastructure
configurations and pricing results.

The comparison package may consume pricing and
estimation components where appropriate.

Pricing components must not depend on estimation
or comparison components.

Other team modules may consume the reusable pricing
and estimation interfaces.

Our modules must not depend on the implementation
of another team member's Streamlit page.

Circular package dependencies should be avoided.

## 8. Architectural Decisions

| ID | Decision | Rationale |
|---|---|---|
| AD-01 | Modular monolith | Avoid unnecessary distributed infrastructure |
| AD-02 | Presentation and logic separation | Improve testability and maintainability |
| AD-03 | Shared pricing foundation | Prevent inconsistent pricing definitions |
| AD-04 | Typed and validated contracts | Ensure reliable data exchange |
| AD-05 | Decimal financial arithmetic | Preserve monetary precision |
| AD-06 | Explicit pricing provenance | Distinguish retrieved and assumed prices |
| AD-07 | Lightweight local persistence | Avoid unnecessary database infrastructure |
| AD-08 | Automated regression testing | Verify functional and financial correctness |
| AD-09 | Preserve shared entry point | Avoid premature integration conflicts |
| AD-10 | Hypothetical infrastructure only | Avoid unnecessary resource provisioning |

These decisions define the proposed implementation direction.

Specific storage formats, public interfaces and calculation
rules remain subject to the subsequent design checkpoints.

## 9. Shared Integration Boundaries

Potential external consumers include:

| Module | Potential shared functionality |
|---|---|
| M6 - Workload Simulator | Estimate costs for changing usage levels |
| M7 - Cost Optimization | Compare original and optimized costs |
| M8 - Reporting | Consume structured cost breakdowns |
| M10 - Resource Utilization | Estimate rightsizing savings |
| M12 - Scaling Analysis | Estimate fixed and scaled resource costs |
| M13 - Storage and Backup | Resolve storage rates and compare costs |

These integrations are proposed rather than implemented.

The public interfaces should return structured Python data
rather than Streamlit presentation objects.

Other modules should be able to invoke the financial
components without launching our Streamlit pages.

## 10. Pricing Source Policy

The proposed pricing foundation distinguishes:

1. Floci-retrieved pricing.
2. Documented reference pricing.
3. Explicit estimation assumptions.
4. Unavailable pricing.

Every usable price must preserve its applicable configuration,
region, currency, unit and source information.

Missing prices must not silently become zero-cost resources.

API failures must remain distinguishable from successful
queries that return no matching products.

Supplementary rates must not be represented as prices
retrieved from Floci.

## 11. Persistence and Data Ownership

Reference pricing datasets are intended to be version-controlled
under the pricing-specific data directory.

User-generated scenarios and runtime pricing caches are
distinct from version-controlled reference datasets.

Runtime storage locations and ignore rules will be established
during the persistence design checkpoint.

The pricing catalogue cache must preserve source information
and retrieval timestamps.

Infrastructure scenario persistence should support multiple
named scenarios.

The exact persistence mechanism and schema remain pending.

## 12. Verification Strategy

The implementation should include:

- Unit tests for pricing record normalization.
- Unit tests for configuration validation.
- Unit tests for pricing resolution.
- Unit tests for financial calculations.
- Unit tests for pricing model comparisons.
- Tests for missing and invalid pricing information.
- Tests for scenario persistence.
- Integration tests against the local Floci environment.
- Streamlit workflow validation.

Unit tests should be executable independently of Docker
and Streamlit wherever practical.

Live Floci integration tests should be distinguishable
from isolated unit tests.

## 13. Shared Environment Considerations

The existing application entry point currently provides
a single-page Floci connectivity interface.

The startup helper considers HTTP responses below 500
successful. This may cause false-positive readiness
results for HTTP 404 responses.

The verified health endpoint is /_floci/health.

A readiness improvement should be coordinated separately
because the startup helper is shared by the project.

The existing Docker Compose configuration and project
dependencies remain unchanged at this checkpoint.

## 14. Pending Design Checkpoints

### M0.6B - Shared Data Contracts

Define and document:

- Normalized pricing records.
- Pricing lookup and resolution results.
- Resource configuration contracts.
- Infrastructure scenario contracts.
- Estimation result contracts.
- Pricing comparison result contracts.
- Validation and error semantics.

### M0.6C - Financial and Persistence Design

Define and document:

- Pricing resolution precedence.
- Billing-period assumptions.
- Unit normalization.
- Tiered pricing calculations.
- Commitment-based financial modelling.
- Spot price projection assumptions.
- Partial estimate handling.
- Scenario persistence and storage ownership.

### M0.6D - Architecture and Implementation Foundation

Finalize the architecture documentation and introduce
the approved package structure and implementation
foundation.

## 15. Checkpoint Outcome

M0.6A establishes the proposed repository organization,
module ownership boundaries and logical responsibilities.

Application source implementation remains pending.

The existing shared project files remain preserved.

The architecture must not be represented as implemented
until the corresponding development and verification
checkpoints have been completed.

---

## 16. Shared Data Contracts

### 16.1 Design Status

| Property | Value |
|---|---|
| Checkpoint | M0.6B.1 |
| Scope | M1, M3, M4 and M5 |
| Status | Proposed data contracts |
| Repository baseline | c521cb9 |

This section extends the proposed architecture established
during M0.6A.

It defines the information exchanged between the pricing,
infrastructure, estimation and comparison components.

The contracts are design specifications. They do not
represent implemented Python classes or completed tests.

### 16.2 General Contract Principles

- Use typed Python data structures.
- Prefer standard library dataclasses and enumerations.
- Use Decimal for monetary values and billable quantities.
- Preserve source precision until presentation.
- Serialize decimal values as strings in JSON.
- Use timezone-aware UTC timestamps.
- Use stable identifiers for resources and scenarios.
- Use explicit units and currency identifiers.
- Distinguish unknown values from genuine zero values.
- Avoid mutable shared state between calculations.
- Validate all externally supplied and persisted data.
- Keep domain contracts independent of Streamlit.
- Version persisted data schemas.

The initial financial currency is USD.

Currency conversion is outside the initial implementation
scope unless explicitly introduced through a documented
conversion mechanism.

Different currencies must not be aggregated directly.

## 17. Pricing Contracts

### 17.1 PriceDimension

Represents an individual billable pricing dimension.

| Field | Proposed type | Meaning |
|---|---|---|
| rate_code | str | Unique source rate identifier |
| unit | str | Original billing unit |
| currency | str | Currency identifier |
| unit_price | Decimal | Price per billable unit |
| begin_range | Decimal | Lower usage boundary |
| end_range | Decimal or None | Upper boundary; None means unbounded |
| description | str | Source description |
| applies_to | tuple[str] | Source applicability identifiers |

Validation requirements:

- Unit price must be finite and nonnegative.
- Currency and billing unit must be nonempty.
- Lower usage boundary must be finite and nonnegative.
- A finite upper boundary must exceed the lower boundary.
- Source infinity markers must be normalized explicitly.
- Unknown billing units must not be silently converted.
- Preserve original rate identifiers.

A dimension is not necessarily a complete product price.

Multiple dimensions may represent distinct cost components,
usage tiers or payment conditions.

### 17.2 PricingRecord

Represents a normalized product and pricing offer.

| Field | Proposed type | Meaning |
|---|---|---|
| service_code | str | AWS pricing service identifier |
| sku | str | Source product identifier |
| product_family | str | Product classification |
| region | str | Applicable AWS region |
| attributes | Mapping[str, str] | Configuration attributes |
| pricing_model | PricingModel | Pricing model |
| offer_term_code | str | Source offer identifier |
| term_attributes | Mapping[str, str] | Offer conditions |
| dimensions | tuple[PriceDimension] | Pricing dimensions |
| source | PricingSource | Pricing origin |
| effective_date | datetime or None | Source effective date |
| publication_date | datetime or None | Source publication date |
| catalogue_version | str or None | Source catalogue version |
| retrieved_at | datetime or None | Retrieval timestamp |
| source_reference | str | API operation or documented reference |
| assumptions | tuple[str] | Applicable assumptions |

Multiple offers for one product must remain distinguishable.

Product attributes and term attributes must not be merged
in a way that removes their original meaning.

Missing source dates must remain unknown rather than
being replaced with fabricated effective dates.

Supplementary pricing records require an identifiable
reference or documented estimation assumption.

### 17.3 PricingSource

Proposed enumeration:

- FLOCI_PRICING_API
- FLOCI_EC2_API
- REFERENCE_DATA
- ESTIMATION_ASSUMPTION

An unavailable price is a resolution outcome, not a
pricing source.

### 17.4 PricingModel

Proposed enumeration:

- ON_DEMAND
- RESERVED
- SAVINGS_PLAN
- SPOT

Storage classes are resource configurations rather than
additional compute commitment models.

Storage usage tiers are represented by pricing dimensions
and their applicable usage boundaries.

Source model identifiers must be retained where needed
for traceability.

### 17.5 PricingQuery

Describes a requested pricing configuration.

| Field | Proposed type |
|---|---|
| service_code | str |
| resource_type | str |
| region | str |
| pricing_model | PricingModel |
| attributes | Mapping[str, str] |
| cost_component | str |
| currency | str |

A query identifies a specific pricing component rather
than requesting an arbitrary rate for a cloud service.

For example, Lambda invocation pricing and Lambda
duration pricing require different component queries.

Resolution must validate all applicable attributes.

A price from another region, operating system or resource
configuration must not be silently substituted.

### 17.6 PricingResolution

Represents the result of a pricing request.

| Field | Proposed type |
|---|---|
| query | PricingQuery |
| status | ResolutionStatus |
| records | tuple[PricingRecord] |
| missing_components | tuple[str] |
| diagnostics | tuple[str] |
| warnings | tuple[str] |

Proposed resolution statuses:

- RESOLVED
- PARTIAL
- UNAVAILABLE
- UNSUPPORTED
- AMBIGUOUS
- INVALID
- API_ERROR

RESOLVED indicates that the requested component has
applicable pricing information.

A resolved component does not imply that every charge
associated with the complete resource is available.

PARTIAL indicates incomplete requested pricing coverage.

UNAVAILABLE indicates that no applicable price was
identified in the configured pricing sources.

UNSUPPORTED identifies an unsupported service or
operation in the relevant pricing source.

AMBIGUOUS identifies conflicting or insufficiently
specific matches.

INVALID identifies invalid query inputs or unusable
pricing records.

API_ERROR preserves unsuccessful retrieval information.

When a supplementary rate resolves an unsupported or
unavailable API result, the original source outcome must
remain available in the resolution diagnostics.

Multiple valid tiers or distinct billing dimensions are
not automatically ambiguous.

### 17.7 SpotPriceObservation

Represents a time-specific EC2 Spot price.

| Field | Proposed type |
|---|---|
| instance_type | str |
| region | str |
| availability_zone | str |
| availability_zone_id | str or None |
| product_description | str |
| unit_price | Decimal |
| currency | str |
| unit | str |
| observed_at | datetime |
| retrieved_at | datetime |
| source | PricingSource |

Spot observations originate from the EC2 API rather
than from the ordinary GetProducts catalogue.

The observation time and availability zone must remain
visible during price comparisons.

A historical observation must not be represented as
a guaranteed future price.

## 18. Infrastructure Contracts

### 18.1 ResourceConfiguration

Represents a hypothetical configured resource.

| Field | Proposed type |
|---|---|
| resource_id | str |
| service | str |
| resource_type | str |
| region | str |
| quantity | int |
| configuration | Service-specific configuration |
| usage | Service-specific usage |
| name | str or None |
| tags | Mapping[str, str] |

Each resource has an identifier that remains stable
when the resource is edited.

Configuration fields describe the resource itself.

Usage fields describe the expected billable activity.

The quantity field must be a positive integer.

Zero usage is valid where applicable.

Unknown usage must remain distinguishable from zero.

The initial builder supports hypothetical configurations.
It does not create cloud resources.

### 18.2 Service-Specific Configuration Requirements

EC2:

- Instance type.
- Operating system.
- Tenancy.
- Region.
- Instance quantity.
- Monthly runtime hours per instance.

EBS:

- Volume type.
- Capacity in GB per volume.
- Volume quantity.
- Region.
- Additional provisioned performance inputs when supported.

S3:

- Storage class.
- Region.
- Average monthly stored data in GB.
- Request usage by applicable request category.
- Data retrieval and transfer usage when applicable.

Lambda:

- Region.
- Memory allocation.
- Execution architecture.
- Monthly invocation count.
- Average billable execution duration.
- Additional ephemeral storage usage when applicable.

DynamoDB:

- Region.
- Capacity mode.
- Table class.
- Read and write billing quantities.
- Storage usage.
- Provisioned throughput inputs when applicable.

RDS:

- Region.
- Database instance class.
- Database engine.
- Deployment configuration.
- Runtime hours per instance.
- Storage type and capacity.
- Additional applicable billing components.

The final supported configuration variants will depend
on available pricing and documented assumptions.

Configuration validity and price availability are
separate concerns.

### 18.3 Usage Semantics

Every usage field must have a defined measurement unit
and aggregation scope.

Instance runtime expressed per instance is multiplied
by instance quantity exactly once.

Storage capacity expressed per volume is multiplied by
volume quantity exactly once.

Service-wide request totals must not be multiplied by
resource quantity again.

Service-specific contracts must distinguish per-resource
usage from already aggregated usage.

Optional usage values must distinguish omitted, unknown,
not applicable and explicitly zero usage.

An omitted required billing input must not be interpreted
as a free cost component.

### 18.4 InfrastructureScenario

Represents a named collection of configured resources.

| Field | Proposed type |
|---|---|
| schema_version | int |
| scenario_id | str |
| name | str |
| description | str |
| resources | tuple[ResourceConfiguration] |
| created_at | datetime |
| updated_at | datetime |

Scenario names must be nonempty.

Scenario identifiers must be stable and unique within
the scenario repository.

Resource identifiers must be unique within a scenario.

An empty draft scenario may be saved, but it must not
be represented as a completed infrastructure estimate.

Resource modifications must not accidentally mutate
another saved scenario.

The initial persistence schema version is proposed as 1.

The persistence implementation is defined during M0.6C.

## 19. Financial Estimation Contracts

### 19.1 BillingPeriod

Represents the financial projection assumptions.

| Field | Proposed type |
|---|---|
| hours_per_month | Decimal |
| days_per_month | Decimal |
| months_per_year | int |

The initial average-month convention is proposed as
730 hours and 730/24 average days, with 12 months
per year.

The billing period convention must be consistent across
a comparison or aggregate estimate.

Actual configured runtime is distinct from the maximum
hours in a billing period.

Daily expenditure derived from monthly expenditure
represents a daily average rather than an assertion
of actual daily billing.

The final period calculations and validation rules
will be established during M0.6C.

### 19.2 CostComponent

Represents an individual estimated charge.

| Field | Proposed type |
|---|---|
| component_id | str |
| resource_id | str |
| category | str |
| description | str |
| billing_unit | str |
| billable_quantity | Decimal or None |
| unit_price | Decimal or None |
| hourly_cost | Decimal or None |
| daily_cost | Decimal or None |
| monthly_cost | Decimal or None |
| annual_cost | Decimal or None |
| currency | str |
| pricing_source | PricingSource or None |
| source_reference | str or None |
| pricing_status | ResolutionStatus |
| assumptions | tuple[str] |
| warnings | tuple[str] |

Cost components must preserve applicable pricing
dimensions or rate identifiers.

Tiered pricing may generate multiple cost components.

Hourly cost is optional for charges that are not
meaningfully expressed as an hourly rate.

An unresolved charge uses an absent monetary value
rather than an invented zero cost.

Zero usage and zero prices are legitimate financial
values when applicable and validated.

### 19.3 ResourceEstimate

Represents the estimated costs of a configured resource.

| Field | Proposed type |
|---|---|
| resource_id | str |
| service | str |
| components | tuple[CostComponent] |
| known_monthly_subtotal | Decimal or None |
| known_annual_subtotal | Decimal or None |
| monthly_total | Decimal or None |
| annual_total | Decimal or None |
| currency | str |
| completeness | EstimateCompleteness |
| missing_components | tuple[str] |
| warnings | tuple[str] |

A complete total is permitted only when all applicable
cost components within the declared estimate scope
have been resolved.

An incomplete estimate may expose a known subtotal.

The subtotal must not be mislabeled as a complete
resource cost.

### 19.4 InfrastructureEstimate

Represents aggregated infrastructure expenditure.

| Field | Proposed type |
|---|---|
| scenario_id | str |
| estimated_at | datetime |
| billing_period | BillingPeriod |
| resource_estimates | tuple[ResourceEstimate] |
| service_breakdowns | Structured service totals |
| known_monthly_subtotal | Decimal or None |
| known_annual_subtotal | Decimal or None |
| monthly_total | Decimal or None |
| annual_total | Decimal or None |
| currency | str |
| completeness | EstimateCompleteness |
| assumptions | tuple[str] |
| missing_components | tuple[str] |
| warnings | tuple[str] |

Resource and service breakdowns must reconcile with
the underlying unrounded cost components.

Missing required costs must propagate to aggregate
completeness.

An unavailable resource cost must not silently become
zero when aggregating the infrastructure.

Monetary calculations use unrounded Decimal values.

Display rounding is performed at the presentation
boundary.

### 19.5 EstimateCompleteness

Proposed enumeration:

- COMPLETE
- PARTIAL
- UNAVAILABLE

COMPLETE applies when every required cost component
within the explicitly declared scope is resolved.

PARTIAL applies when known costs exist but other
required components cannot be resolved.

UNAVAILABLE applies when a meaningful cost estimate
cannot be calculated.

Estimate completeness is separate from pricing source.

A complete assumption-based estimate must still
disclose its assumptions and data provenance.

## 20. Pricing Comparison Contracts

### 20.1 Comparison Inputs

Pricing comparisons must use an equivalent workload
and clearly defined financial scope.

Proposed comparison inputs include:

- Resource configuration.
- Resource quantity.
- Region and operating system.
- Applicable availability zone for Spot.
- Workload usage.
- Billing period.
- Selected pricing models.
- Projection duration.
- Commitment duration where applicable.
- Upfront and recurring payment assumptions.
- Commitment coverage and utilization assumptions.
- Applicable storage access and retrieval assumptions.

The selected assumptions must remain visible and
reproducible.

### 20.2 ModelCostEstimate

Represents the expenditure under one pricing model
or storage configuration.

| Field | Proposed type |
|---|---|
| option_id | str |
| pricing_model | PricingModel |
| configuration | ResourceConfiguration |
| monthly_cost | Decimal or None |
| annual_cost | Decimal or None |
| upfront_cost | Decimal or None |
| commitment_total | Decimal or None |
| currency | str |
| completeness | EstimateCompleteness |
| sources | tuple[PricingSource] |
| assumptions | tuple[str] |
| limitations | tuple[str] |

Where relevant, actual commitment cash flows must
remain distinguishable from amortized monthly costs.

An assumed effective discount must not be described
as a retrieved commitment offer.

### 20.3 PricingComparisonResult

Represents the result of comparing pricing options.

| Field | Proposed type |
|---|---|
| comparison_id | str |
| baseline_option_id | str |
| options | tuple[ModelCostEstimate] |
| absolute_savings | Structured savings by option |
| percentage_savings | Structured savings by option |
| currency | str |
| comparable | bool |
| assumptions | tuple[str] |
| warnings | tuple[str] |

Savings are calculated against an explicit baseline.

Absolute savings may be negative when a selected
pricing model is more expensive.

Percentage savings are unavailable when the baseline
cost is zero or cannot be calculated.

Incomplete or financially incompatible estimates must
not produce misleading complete savings comparisons.

Storage class comparisons must identify excluded
request, retrieval, transition and retention charges.

Spot comparisons must disclose price variability
and interruption limitations.

## 21. Validation and Error Semantics

The implementation must distinguish:

- Invalid resource configuration.
- Invalid usage input.
- Unsupported pricing service or operation.
- Successful API response with no matching records.
- Incomplete pricing retrieval.
- Conflicting pricing records.
- Invalid financial data.
- API connectivity or response failure.
- Invalid persisted scenario data.

Expected pricing limitations should produce structured
results where practical.

Programmer errors and invalid persisted schemas should
be surfaced explicitly rather than silently ignored.

The presentation layer must convert diagnostics into
understandable user-facing messages.

No financial calculation may use NaN or unbounded
monetary values.

No error may silently become a zero-cost estimate.

## 22. Proposed Public Interfaces

The following signatures describe intended service
boundaries rather than implemented functions.

| Interface | Proposed responsibility |
|---|---|
| list_services() | Discover Pricing API services |
| list_attributes(service_code) | Discover pricing attributes |
| list_attribute_values(service_code, attribute) | Discover advertised values |
| get_products(query) | Retrieve and normalize pricing records |
| resolve_price(query) | Resolve applicable component pricing |
| get_spot_prices(query) | Retrieve matching Spot observations |
| validate_resource(resource) | Validate resource configuration and usage |
| save_scenario(scenario) | Persist a scenario |
| load_scenario(scenario_id) | Retrieve a saved scenario |
| list_scenarios() | Discover saved scenarios |
| estimate_resource(resource, billing_period) | Calculate a resource estimate |
| estimate_scenario(scenario, billing_period) | Calculate an infrastructure estimate |
| compare_pricing_models(request) | Evaluate applicable pricing alternatives |

The final signatures may receive explicit service
dependencies through constructors or function parameters.

The shared pricing and estimation interfaces must be
usable without importing Streamlit.

Other team modules may consume these interfaces
after team coordination.

## 23. Contract Verification Strategy

The future contract implementation must be verified
with automated tests covering:

- Valid normalized pricing records.
- Decimal precision preservation.
- Negative and nonfinite monetary values.
- Invalid pricing ranges.
- Exact configuration matching.
- Missing and ambiguous price resolution.
- Genuine zero prices.
- Invalid resource quantities.
- Missing and invalid usage values.
- Duplicate resource identifiers.
- Scenario serialization round trips.
- Per-resource versus aggregated usage.
- Incomplete cost component handling.
- Service-level cost reconciliation.
- Infrastructure completeness propagation.
- Comparable and incompatible pricing options.
- Zero-cost comparison baselines.
- Negative savings.
- Source attribution preservation.

Integration tests will separately verify the actual
responses from the local Floci environment.

## 24. M0.6B.1 Checkpoint Outcome

The proposed shared data contracts establish the
information required by M1, M3, M4 and M5.

They preserve configuration identity, usage semantics,
pricing provenance and financial completeness.

The original M0.6A architecture remains preserved.

Python implementation and executable validation
remain subsequent development work.

M0.6C will finalize financial formulas, pricing resolution
precedence and local persistence mechanisms.

The contracts remain proposed until the design is
consolidated and coordinated with the team.

---

## 25. Pricing Resolution Design

### 25.1 Design Status

| Property | Value |
|---|---|
| Checkpoint | M0.6C.1 |
| Scope | M1, M3, M4 and M5 |
| Status | Proposed implementation design |
| Repository baseline | c521cb9 |

This section extends the shared data contracts with
pricing resolution rules and supplementary pricing
requirements.

The design is based on observed behaviour of the installed
Floci 2.5.0 Community Edition environment.

The detailed investigation evidence remains documented in
FLOCI_PRICING_CAPABILITIES.md.

### 25.2 Resolution Responsibilities

The pricing resolution service is responsible for:

- Validating pricing queries.
- Selecting an applicable pricing source.
- Retrieving candidate pricing records.
- Validating returned records and source metadata.
- Matching financially relevant configuration attributes.
- Preserving valid billing dimensions and usage ranges.
- Applying permitted supplementary pricing policies.
- Reporting missing, unsupported or ambiguous prices.
- Returning structured results with source diagnostics.

The pricing resolver identifies applicable pricing
dimensions. The estimation engine applies resource usage
and calculates monetary expenditure.

Pricing resolution must not depend on Streamlit pages
or another team member's implementation.

### 25.3 Pricing Source Precedence

The proposed normal source precedence is:

1. Applicable Floci-retrieved pricing.
2. Applicable documented reference pricing.
3. Explicit estimation assumptions when enabled.
4. Pricing unavailable.

The source policy must be configurable through explicit
resolution inputs or service configuration.

A strict Floci-only policy must also be supported.

Reference pricing and assumptions must not replace a valid
Floci rate merely because they are financially preferable.

Alternative pricing models are resolved independently.
An assumed Reserved rate must not replace an On-Demand rate.

A successful price resolution must preserve the actual
source of every selected pricing record.

### 25.4 Module-Specific Source Policies

M1 - Pricing Explorer:

- Use Floci Pricing API as the primary data source.
- Display retrieved service and product information.
- Distinguish advertised attributes from actual products.
- Display missing pricing coverage explicitly.
- Keep supplementary reference rates distinguishable from
  retrieved Floci catalogue records.
- Never count supplementary records as Floci API results.

M3 - Infrastructure Builder:

- Permit valid hypothetical resource configurations even
  when pricing is unavailable.
- Display pricing availability where useful.
- Do not equate pricing availability with resource
  configuration validity.
- Do not provision actual cloud resources.

M4 - Cost Estimator:

- Resolve each applicable resource charge independently.
- Use Floci rates wherever valid matching rates exist.
- Permit documented supplementary reference rates.
- Permit explicit assumptions when enabled.
- Preserve incomplete estimates and missing cost components.

M5 - Pricing Comparison:

- Resolve each applicable pricing option independently.
- Use retrieved On-Demand and Spot prices where available.
- Permit documented commitment-based modelling assumptions.
- Distinguish actual offers from hypothetical model inputs.
- Compare options using equivalent workload and financial scope.

## 26. Exact Configuration Matching

### 26.1 Query Validation

A pricing query must identify:

- Service code.
- Resource type.
- Applicable region.
- Requested pricing model.
- Requested cost component.
- Required configuration attributes.
- Currency.

Required attributes are defined by the service and
requested cost component.

Empty required attributes and invalid configurations
must be rejected before pricing resolution.

An omitted financially significant attribute must not
cause an arbitrary product to be selected.

### 26.2 Component-Specific Attribute Rules

EC2 compute pricing may require:

- Instance type.
- Operating system.
- Tenancy.
- Region.
- Software or licensing attributes where applicable.

EBS pricing may require:

- Volume type.
- Region.
- Storage, IOPS or throughput charge category.

S3 pricing may require:

- Storage class.
- Region.
- Storage, request, retrieval or transfer category.
- Applicable usage dimension.

Lambda pricing may require:

- Region.
- Invocation, duration or storage charge category.
- Execution architecture where relevant.
- Other configuration attributes affecting the charge.

DynamoDB pricing may require:

- Region.
- Capacity mode.
- Table class.
- Read, write, throughput or storage charge category.

RDS pricing may require:

- Region.
- Database instance class.
- Database engine.
- Deployment configuration.
- Compute, storage or other charge category.

The implementation must distinguish required attributes
from irrelevant or optional attributes for each component.

The final supported configuration catalogue will be
established during module implementation.

### 26.3 Attribute Normalization

Internal resource identifiers may differ from AWS Pricing
API attribute names and values.

Explicit mapping rules must translate internal fields into
applicable source-specific query attributes.

Examples:

- instance_type maps to instanceType.
- operating_system maps to operatingSystem.
- region maps to regionCode or an explicitly mapped location.
- S3 storage class maps to its applicable source attributes.

Normalization must not introduce financially significant
configuration changes.

Unknown aliases must not be guessed.

The original source attributes must remain available for
traceability.

### 26.4 Candidate Validation

Returned pricing records must be validated even when
server-side TERM_MATCH filters were applied.

Validation must confirm:

- Applicable service and product family.
- Exact required configuration attributes.
- Correct region.
- Applicable pricing model.
- Appropriate cost component.
- Matching currency.
- Supported billing units.
- Valid finite nonnegative prices.
- Valid usage boundaries.

A candidate must not be accepted simply because it was
the first returned product.

A price from another region, instance type, operating
system or tenancy must not be silently substituted.

### 26.5 Multiple Candidates and Usage Tiers

Multiple pricing dimensions do not necessarily represent
conflicting prices.

They may represent:

- Graduated usage tiers.
- Distinct billing components.
- Upfront payment charges.
- Recurring payment charges.
- Different offer conditions.

Applicable dimensions must be grouped by their financial
meaning and pricing offer.

Duplicate identical source dimensions may be deduplicated
using stable source identifiers.

Conflicting values associated with the same source
identity must be reported.

Multiple incompatible offers must not be silently merged.

Tier coverage must be validated before calculating a
complete charge for a requested quantity.

The estimation engine must not apply a finite pricing tier
beyond its documented upper boundary.

Supplementary rates must not be stitched into a tier
schedule unless the combined schedule has explicitly
validated and documented financial semantics.

Detailed tier calculations are defined in M0.6C.2.

## 27. Supplementary Pricing Policy

### 27.1 Reference Pricing

Reference pricing represents supplementary pricing data
obtained from identifiable external documentation.

Reference data must not be described as retrieved
from the local Floci Pricing API.

Official AWS pricing references should be preferred
where applicable.

Reference values must be reviewed before inclusion.

The application must not silently contact production AWS
APIs using real credentials to resolve missing local prices.

The initial runtime will use a documented local reference
dataset rather than depend on external pricing downloads.

### 27.2 Proposed Reference Dataset

Proposed location:

data/pricing/reference_rates.json

The dataset should contain a schema version and a
reference catalogue version.

Each reference record should contain:

| Field | Purpose |
|---|---|
| reference_id | Stable reference identifier |
| service_code | Applicable service |
| resource_type | Applicable resource type |
| region | Applicable region |
| attributes | Applicable configuration |
| cost_component | Billable charge category |
| pricing_model | Applicable pricing model |
| currency | Currency identifier |
| unit | Billing measurement |
| unit_price | Decimal-formatted monetary value |
| begin_range | Lower usage boundary |
| end_range | Upper usage boundary or unbounded marker |
| source_reference | Identifiable source or URL |
| effective_date | Source effective date if known |
| verified_at | Reference review timestamp |
| limitations | Applicable conditions and exclusions |

Reference values must use decimal strings for
monetary precision.

Reference records must identify their applicable units,
configuration and financial limitations.

A reference verification timestamp does not imply that
the price remains current indefinitely.

Missing effective dates must remain unknown.

The dataset will be populated and validated during
pricing implementation.

No supplementary price is approved solely by this design.

### 27.3 Reference Coverage Priorities

Initial reference pricing should prioritize the missing
components required by our four modules:

- Additional EC2 configurations.
- EBS storage and applicable performance charges.
- Additional S3 storage classes and tiers.
- S3 request, retrieval and transfer charges where relevant.
- Lambda execution duration and additional storage.
- DynamoDB request and storage charges.
- RDS compute and storage charges.

Other service rates may be introduced through team
coordination and documented requirements.

Reference coverage must be evaluated against the selected
scenario rather than assumed to be complete.

### 27.4 Explicit Estimation Assumptions

Assumed pricing represents a hypothetical financial input.

Assumptions may include:

- Reserved Instance discount assumptions.
- Savings Plans discount or commitment assumptions.
- Documented hypothetical rates for missing components.
- Explicit storage or workload modelling assumptions.

An assumption must identify:

- Its applicable service and configuration.
- Its financial value and measurement unit.
- Its rationale.
- Its applicable pricing model.
- Its projection conditions.
- Its limitations.
- The baseline price where relevant.

Assumption-based resolution must be explicitly enabled.

Assumed prices must not be represented as retrieved
Floci prices or independently verified AWS offers.

An unavailable reference must not automatically trigger
an undocumented default discount.

## 28. Alternative Pricing Model Resolution

### 28.1 On-Demand

On-Demand pricing should primarily be retrieved through
the Floci Pricing API GetProducts operation.

Pricing dimensions must be selected using exact
configuration and charge-component matching.

### 28.2 Spot

Spot pricing should use the verified EC2
DescribeSpotPriceHistory operation.

Matching observations must preserve:

- Instance type.
- Region.
- Availability zone.
- Operating system or product description.
- Observed price.
- Observation timestamp.
- Retrieval timestamp.

The application should select the latest applicable
observation within the requested history window unless
the user explicitly selects a different observation.

Equal-time conflicting observations must not be selected
arbitrarily.

An unavailable availability zone or instance price must
not silently use another zone or instance type.

A selected Spot rate represents an observation rather
than a guaranteed future price.

Monthly and annual projections must disclose their
constant-rate assumption.

Spot capacity and uninterrupted execution are not guaranteed.

### 28.3 Reserved Instances

The tested DescribeReservedInstancesOfferings operation
returned UnsupportedOperation.

Reserved Instance comparisons may therefore use verified
reference information or explicit modelling assumptions.

The original unsupported-operation outcome must remain
visible in the resolution diagnostics.

Commitment duration and payment assumptions must be
preserved.

An assumed discount is not an actual purchasable offer.

### 28.4 Savings Plans

The tested Savings Plans offering and rate operations
returned UnknownOperationException.

The tested ComputeSavingsPlans bulk pricing query
returned InvalidParameterException.

Savings Plans modelling may use documented reference
information or explicit assumptions.

A Savings Plans comparison must not treat a commitment
as an unrestricted discount on every resource charge.

Commitment eligibility, coverage and utilization must
be considered or explicitly scoped out of the model.

Detailed commitment formulas are defined in M0.6C.2.

## 29. Resolution Outcomes, Provenance and Reproducibility

### 29.1 Resolution Outcome Policy

| Source outcome | Required handling |
|---|---|
| Valid exact match | Return applicable pricing dimensions |
| Successful empty response | Evaluate permitted supplementary sources |
| Explicitly unsupported operation | Evaluate permitted supplementary sources |
| Verified unsupported service code | Evaluate permitted supplementary sources |
| Invalid request configuration | Reject; do not silently fall back |
| Invalid pricing data | Report invalid data |
| Conflicting candidates | Report ambiguity |
| Incomplete pagination | Report incomplete retrieval |
| Connection failure | Report API error |
| Unexpected API failure | Report API error |
| No applicable permitted source | Return unavailable |

InvalidParameterException alone is not proof that a
service is unsupported.

Error classification must consider the operation,
request validity and observed source behaviour.

Unexpected API errors must not silently become successful
supplementary resolutions.

If an explicit offline reference-only mode is introduced,
the mode and inability to retrieve Floci data must remain
visible to the user.

### 29.2 Source Attempt Diagnostics

The resolution result should retain source attempts and
their outcomes.

For example:

- Floci Pricing API: no matching product.
- Reference catalogue: matching storage rate.
- Final resolution: RESOLVED.
- Selected source: REFERENCE_DATA.

A resolved supplementary rate must not remove evidence
that the primary source lacked matching pricing.

Diagnostics should contain meaningful operation names
and source outcomes without exposing credentials.

### 29.3 Partial Coverage

Pricing resolution occurs at the billable component level.

For example, a Lambda request rate may resolve
successfully while Lambda duration pricing remains
unavailable.

The request component remains usable.

The complete Lambda estimate remains incomplete when
required duration charges cannot be calculated.

Missing components must propagate to resource and
infrastructure completeness.

An excluded charge must be distinguished from a required
charge whose price is unavailable.

An estimate must identify its declared financial scope.

### 29.4 Pricing Snapshots

An estimate should retain the pricing information used
during its calculation.

This includes, where applicable:

- Selected pricing source.
- Source product or reference identifier.
- Rate identifiers.
- Applicable configuration.
- Original unit price and currency.
- Billing unit and usage range.
- Catalogue version.
- Source effective date.
- Retrieval timestamp.
- Spot observation timestamp.
- Reference verification timestamp.
- Explicit modelling assumptions.

Historical estimation results must not silently change
when a new catalogue is retrieved.

Recalculation must use an explicitly selected or refreshed
pricing context.

Runtime caching may improve performance but must not
misrepresent stale information as newly retrieved pricing.

Cache storage and lifecycle rules are defined in M0.6C.3.

### 29.5 Local Endpoint Safety

Floci clients must use the configured local emulator
endpoint and explicit test credentials.

The application must not silently fall back to production
AWS endpoints.

Bulk pricing references returned by Floci will not be
downloaded automatically.

Bulk catalogue file availability and contents were not
verified during the investigation.

Local endpoint failures must remain visible.

## 30. M0.6C.1 Checkpoint Outcome

The proposed pricing resolution design establishes:

- Explicit source selection policies.
- Floci-first pricing resolution.
- Component-specific configuration matching.
- Documented supplementary pricing requirements.
- Explicit financial assumption controls.
- Alternative pricing model resolution.
- Missing-price and API-error handling.
- Pricing provenance and snapshot requirements.

The architecture and shared data contracts remain
proposed until implementation and verification.

No reference pricing values, pricing engine source code
or automated implementation tests are introduced by
this documentation checkpoint.

M0.6C.2 will establish the detailed financial formulas
and billing semantics used by the estimation and
comparison engines.

---

## 31. Financial Calculation Design

### 31.1 Design Status

| Property | Value |
|---|---|
| Checkpoint | M0.6C.2 |
| Primary scope | M4 and M5 |
| Supporting scope | M1 and M3 |
| Status | Proposed implementation design |
| Repository baseline | c521cb9 |

This section establishes the financial calculation rules
for the infrastructure estimation and pricing comparison
engines.

The formulas define an educational FinOps estimation model.
They do not constitute a complete reproduction of the AWS
production billing system.

Prices must originate from the resolution policies defined
in M0.6C.1.

The calculation engine must remain independent of Streamlit
and must not directly provision cloud resources.

### 31.2 Financial Calculation Principles

The implementation must:

- Use Decimal arithmetic for monetary values.
- Preserve original source price precision.
- Reject NaN and nonfinite monetary inputs.
- Reject negative prices and invalid usage quantities.
- Distinguish unit prices from calculated expenditure.
- Apply resource quantities exactly once.
- Preserve pricing provenance for each calculated charge.
- Respect pricing applicability and usage boundaries.
- Distinguish missing costs from genuine zero costs.
- Avoid presenting partial subtotals as complete totals.
- Compare equivalent workloads and financial scopes.
- Round monetary values only at the presentation boundary.

The initial implementation uses USD.

Different currencies must not be added without an explicit
and documented currency conversion mechanism.

### 31.3 Rounding and Precision

Financial values are represented using Decimal.

Decimal values loaded from JSON must be constructed from
decimal strings rather than binary floating-point values.

Intermediate values must retain sufficient precision.

The proposed presentation convention rounds displayed
USD expenditure to two decimal places using ROUND_HALF_UP.

Unit prices must retain their relevant source precision.

For example, the Lambda request rate of 0.0000002000 USD
must not be rounded to 0.00 before calculation.

Aggregate totals must be calculated from unrounded
component values.

Rounded displayed components may differ from the displayed
aggregate by a small rounding amount.

This must not be corrected by altering the underlying
financial values.

## 32. Billing Periods and Usage Normalization

### 32.1 Standard Billing Period

The default representative month uses:

- 24 hours per day.
- 730 hours per month.
- 730 / 24 average days per month.
- 12 months per year.
- 8760 projected hours per year.

The average-month convention is an estimation assumption.

A configured billing period must be finite and positive.

Custom billing periods must maintain consistent hour
and day relationships.

The actual runtime of a resource is independent of the
maximum duration of the billing period.

Runtime per instance must not exceed the selected
billing-period duration.

A resource may have zero runtime.

### 32.2 Period Cost Calculations

Let:

- C_month be the unrounded monthly cost.
- D_month be the average number of days in the month.
- M_year be the number of representative months per year.

Then:

    C_daily_average = C_month / D_month

    C_annual = C_month * M_year

Annual projections assume that the representative monthly
usage and applicable prices remain constant.

Daily projections are averages rather than measurements
of actual expenditure on a particular calendar day.

Hourly compute expenditure while running must remain
distinguishable from average expenditure per calendar hour.

For hourly compute resources:

    Running_hourly_cost = Quantity * Hourly_rate

    Monthly_compute_cost =
        Quantity * Runtime_hours_per_instance * Hourly_rate

Average expenditure per calendar hour, if displayed:

    Average_hourly_cost = Monthly_cost / Hours_per_month

Non-hourly charges must not be mislabeled as native
hourly billing rates.

### 32.3 Quantity and Usage Scope

Each usage field must declare:

- Its measurement unit.
- Its billing period.
- Whether it is per resource or already aggregated.
- Whether the value is required or optional.

Per-resource quantities are multiplied by resource count
exactly once.

Already aggregated usage is not multiplied again.

For example:

    3 instances * 100 hours per instance = 300 instance-hours

A service-wide request total of one million requests
remains one million requests regardless of resource count.

### 32.4 Billing Unit Normalization

The observed Floci pricing units are:

| Source unit | Calculation meaning |
|---|---|
| Hrs | Price per billed hour |
| GB-Mo | Price per billable GB-month |
| Requests | Price per request |

Supplementary records may introduce additional units,
including:

- GB-seconds.
- Requests per thousand.
- Requests per million.
- Read and write request units.
- Provisioned capacity units.
- IOPS-months.
- Throughput-months.
- Data transfer GB.

Every supported unit must have an explicit normalization
rule.

For a price quoted per K units:

    Cost = Billable_usage / K * Quoted_price

The normalized rate may alternatively be represented as:

    Rate_per_unit = Quoted_price / K

    Cost = Billable_usage * Rate_per_unit

The implementation must not apply both normalization
methods to the same charge.

A description mentioning a million requests does not
automatically mean that the stored rate is per million.

For the observed Lambda Requests dimension:

    Rate = 0.0000002 USD per request

    1000000 requests * 0.0000002 = 0.20 USD

Unknown units or conversion conventions must produce
explicit diagnostics.

Storage units must follow the documented source convention.

## 33. Service-Level Calculation Rules

### 33.1 EC2 Compute

Inputs:

- Instance type.
- Operating system.
- Tenancy.
- Region.
- Instance quantity.
- Runtime hours per instance.
- Applicable hourly rate.

Formula:

    EC2_cost =
        Instance_quantity
        * Runtime_hours_per_instance
        * Hourly_rate

Example using verified Floci pricing:

    3 * 730 * 0.0104 = 22.776 USD/month

    22.776 * 12 = 273.312 USD/year

The formula represents compute charges only.

EBS, networking, additional software charges, public IP
charges and other applicable components must be handled
separately or identified as excluded.

### 33.2 EBS Storage

Inputs:

- Volume type.
- Region.
- Volume quantity.
- Provisioned capacity per volume.
- Billed month fraction.
- Applicable storage rate.

Formula:

    Billable_GB_months =
        Volume_quantity
        * Capacity_GB_per_volume
        * Billed_month_fraction

    EBS_storage_cost =
        Billable_GB_months * Storage_rate

The billed month fraction represents the assumed volume
provisioning duration.

Storage duration must not automatically be equated with
EC2 runtime.

An attached volume may remain provisioned while its
associated compute instance is stopped.

Additional billable IOPS, throughput, snapshots and other
applicable components require separate pricing rules.

Included performance allowances must be respected.

No additional performance charge may be assumed solely
from the total provisioned performance value.

### 33.3 S3 Storage and Usage

S3 storage pricing uses average billable GB-months
under the selected storage configuration.

For a single applicable untiered rate:

    Storage_cost = Billable_GB_months * Storage_rate

For tiered pricing, the rules in Section 34 apply.

Request charges are resolved by request category.

    Request_cost =
        Request_count / Pricing_unit_size * Request_rate

Data transfer and retrieval charges are separate components.

    Transfer_cost =
        Billable_transfer_GB * Transfer_rate

    Retrieval_cost =
        Billable_retrieval_GB * Retrieval_rate

The implementation must not assume that all request
categories or transfer destinations share the same rate.

Storage class comparisons must account for applicable
minimum storage duration, minimum billable object size,
retrieval, transition and request charges where modelled.

Otherwise, these limitations must be disclosed.

### 33.4 Lambda

Request component:

    Request_cost =
        Invocation_count * Normalized_request_rate

Execution component:

    Execution_GB_seconds =
        Invocation_count
        * Memory_GB
        * Average_billable_duration_seconds

    Execution_cost =
        Execution_GB_seconds * Duration_rate

The duration input represents an assumed average billed
duration, rather than an exact reconstruction of all
individual invocations.

Memory and duration conversions must be explicit.

Additional ephemeral storage charges must use applicable
billable storage above included allowances.

Provisioned concurrency and other optional features
require separate modelling if enabled.

The observed Floci catalogue provides request pricing
but does not provide execution-duration or additional
storage pricing.

A request-only estimate must not be represented as a
complete Lambda expenditure estimate.

### 33.5 DynamoDB

The initial design must distinguish on-demand request
pricing from provisioned capacity pricing.

For on-demand request pricing:

    Read_cost =
        Billable_read_units / Read_pricing_unit_size
        * Read_rate

    Write_cost =
        Billable_write_units / Write_pricing_unit_size
        * Write_rate

For provisioned capacity, where supported:

    Read_capacity_cost =
        Provisioned_read_units
        * Provisioned_hours
        * Read_capacity_hourly_rate

    Write_capacity_cost =
        Provisioned_write_units
        * Provisioned_hours
        * Write_capacity_hourly_rate

Storage is a separate billing component.

Read and write request counts are not necessarily equal
to billable read and write units.

The initial calculator may accept already normalized
billing units instead of attempting to reconstruct
item-size and consistency-dependent billing.

On-demand and provisioned charges must not be applied
simultaneously to the same usage.

Additional backups, replication and data transfer costs
must be handled separately or disclosed as excluded.

### 33.6 RDS

Inputs include:

- Database instance class.
- Engine.
- Deployment configuration.
- Region.
- Instance quantity.
- Runtime hours.
- Storage configuration and capacity.

Compute formula:

    RDS_compute_cost =
        Database_instance_quantity
        * Runtime_hours_per_instance
        * Applicable_hourly_rate

Storage formula:

    RDS_storage_cost =
        Billable_provisioned_GB_months
        * Applicable_storage_rate

Deployment configuration must match the selected rate.

If a retrieved rate already represents a Multi-AZ
deployment, an additional replica multiplier must not
be applied without documented justification.

Storage I/O, backup, licensing and transfer charges
require applicable separate components.

The final supported RDS variants depend on verified
reference pricing coverage.

### 33.7 Declared Estimate Scope

Each resource type must define its supported billing
components and applicability conditions.

An estimate must distinguish:

- Included and resolved charges.
- Included but unresolved charges.
- Explicitly excluded charges.
- Charges that are not applicable.
- Charges with validated zero usage.

Free-tier benefits, taxes, credits and account-specific
discounts are excluded from the initial model unless
explicitly implemented.

An excluded charge is not equivalent to a free charge.

## 34. Tiered Pricing and Incomplete Coverage

### 34.1 Graduated Pricing Tiers

Let:

- Q be total billable usage.
- B_i be the lower boundary of tier i.
- E_i be the upper boundary of tier i.
- P_i be the rate for tier i.

For a finite tier:

    Tier_usage_i = max(0, min(Q, E_i) - B_i)

    Tier_cost_i = Tier_usage_i * P_i

For an unbounded tier:

    Tier_usage_i = max(0, Q - B_i)

    Tier_cost_i = Tier_usage_i * P_i

Total graduated tier cost:

    Total_cost = sum(Tier_cost_i)

These formulas apply only to pricing schedules documented
as graduated usage tiers.

Other pricing structures require their own calculation
rules.

### 34.2 Tier Validation

Applicable tier schedules must be checked for:

- Valid nonnegative boundaries.
- Increasing upper boundaries.
- Consistent billing units.
- Consistent currency.
- Compatible product and offer identity.
- Duplicate or conflicting tier definitions.
- Overlaps and gaps.
- Complete coverage of the requested usage.

An unbounded upper boundary must be represented explicitly.

Overlapping or conflicting tiers must not be silently
combined.

Missing tier coverage must produce a partial or
unavailable estimate.

### 34.3 Observed S3 Tier Example

The verified Floci S3 Standard dimension has:

    Begin range = 0

    End range = 51200 GB-months

    Rate = 0.023 USD/GB-month

For 500 GB-months:

    500 * 0.023 = 11.50 USD

For 60000 GB-months:

    Priced usage = 51200

    Unpriced usage = 8800

    Known subtotal = 51200 * 0.023

    Known subtotal = 1177.60 USD

    Complete storage total = unavailable

The available tier must not be extrapolated to the
unpriced usage.

Supplementary tier schedules may be used only where
their financial compatibility has been documented.

### 34.4 Aggregation Scope

Some pricing tiers apply to aggregated service usage
rather than independent resource-level usage.

The initial model should treat one infrastructure
scenario as one hypothetical billing scope.

Compatible usage must be grouped by the relevant
service, region, configuration and billing category
before applying aggregate tiers.

A tier must not be restarted separately for every
resource when the applicable pricing schedule requires
aggregate usage.

When resource-level breakdowns are necessary, a
documented proportional allocation may be applied to
known aggregate charges.

Allocated resource costs must reconcile with the
aggregate cost.

Incomplete usage or tier coverage must remain visible
in the resulting allocations.

The initial model does not simulate organization-wide
consolidated billing or cross-account discount allocation.

## 35. Pricing Model Comparison Calculations

### 35.1 Comparison Requirements

A valid comparison must preserve:

- Equivalent workload requirements.
- Applicable resource configuration.
- Region and operating system.
- Comparable cost components.
- Billing period.
- Currency.
- Pricing source.
- Financial projection assumptions.

Differences affecting service availability, performance
or workload suitability must be disclosed.

### 35.2 On-Demand

For a homogeneous compute workload:

    OnDemand_monthly =
        Instance_quantity
        * Runtime_hours_per_instance
        * OnDemand_hourly_rate

    OnDemand_annual = OnDemand_monthly * 12

The On-Demand model provides the default comparison
baseline where applicable.

### 35.3 Spot

For a selected applicable Spot observation:

    Spot_monthly =
        Instance_quantity
        * Runtime_hours_per_instance
        * Observed_Spot_hourly_rate

    Spot_annual = Spot_monthly * 12

The calculation assumes the selected observation remains
constant over the projection period.

The estimate must retain the selected availability zone
and observation timestamp.

The initial calculation does not predict future Spot
prices, interruptions or replacement-capacity costs.

Spot suitability must be explained independently from
its calculated cost.

### 35.4 Reserved Instance Modelling

The initial Reserved Instance model represents a
hypothetical commitment for a homogeneous eligible
compute configuration.

Inputs:

- Commitment duration in months.
- Committed equivalent instance quantity.
- Total upfront commitment payment.
- Recurring commitment rate per committed instance-hour.
- Committed hours per month.
- Eligible workload usage.
- Applicable On-Demand rate.

Formulas:

    Committed_instance_hours =
        Committed_quantity * Hours_per_month

    Covered_instance_hours =
        min(Eligible_instance_hours,
            Committed_instance_hours)

    Uncovered_instance_hours =
        Eligible_instance_hours - Covered_instance_hours

    Monthly_upfront_amortization =
        Upfront_payment / Commitment_months

    Monthly_recurring_commitment =
        Committed_instance_hours * Recurring_hourly_rate

    Uncovered_OnDemand_cost =
        Uncovered_instance_hours * OnDemand_hourly_rate

    Reserved_monthly_amortized_cost =
        Monthly_upfront_amortization
        + Monthly_recurring_commitment
        + Uncovered_OnDemand_cost

    Full_term_commitment_cost =
        Upfront_payment
        + Monthly_recurring_commitment * Commitment_months

The commitment remains payable even when covered usage
is lower than committed capacity.

For the initial homogeneous model, usage is assumed to
be distributed consistently within the modelled period.
Monthly coverage arithmetic is an approximation and
must not be interpreted as exact hourly benefit matching.

The full-term commitment cost excludes variable
uncovered usage unless explicitly added.

Amortized monthly cost must remain distinguishable
from actual upfront and recurring cash payments.

If a simplified assumed effective hourly rate is
provided, it must be identified as amortized or
recurring to avoid counting upfront charges twice.

The initial design may support 12-month and 36-month
commitments as explicit modelling options.

No actual Reserved Instance offering was retrieved
from the tested Floci environment.

### 35.5 Savings Plans Modelling

The initial Savings Plans calculator represents a
simplified uniform hourly eligible compute workload.

It does not attempt to reproduce AWS benefit allocation
across mixed services, accounts or changing workloads.

Inputs:

- Equivalent eligible instance-hours consumed per hour.
- On-Demand hourly rate.
- Assumed discounted hourly rate.
- Effective hourly financial commitment.
- Commitment duration.
- Billing-period hours.

For one modelled hour:

    Covered_usage =
        min(Eligible_usage,
            Hourly_commitment / Discounted_hourly_rate)

    Uncovered_usage =
        Eligible_usage - Covered_usage

    Used_commitment =
        Covered_usage * Discounted_hourly_rate

    Unused_commitment =
        Hourly_commitment - Used_commitment

    Hourly_total =
        Hourly_commitment
        + Uncovered_usage * OnDemand_hourly_rate

For uniform usage across the representative month:

    SavingsPlan_monthly = Hourly_total * Hours_per_month

    Monthly_unused_commitment =
        Unused_commitment * Hours_per_month

    Full_term_commitment =
        Hourly_commitment
        * Hours_per_month
        * Commitment_months

Commitment utilization:

    Utilization =
        Used_commitment / Hourly_commitment * 100

Utilization is undefined when the commitment is zero.

The discounted hourly rate must be finite and positive
for the coverage formula.

The effective hourly commitment represents the assumed
amortized commitment cost.

Upfront payments must not be added again if they are
already included in the effective commitment.

Unused commitment remains part of the cost.

Unused commitment must not be carried into another hour.

For changing workloads, hourly or explicitly weighted
workload intervals must be modelled separately before
costs are aggregated.

A monthly average must not be presented as exact
hour-by-hour commitment utilization.

No actual Savings Plans offers or rates were retrieved
during the Floci investigation.

All assumed commitments and discounted rates must be
visibly identified as estimation assumptions.

### 35.6 Storage Class Comparison

Storage class comparisons must use equivalent stored
data, retention period and access requirements.

For each storage option:

    Storage_option_cost =
        Storage_charge
        + Request_charge
        + Retrieval_charge
        + Transfer_charge
        + Transition_charge
        + Other_applicable_charges

Only applicable components within the declared scope
are included.

Where charges cannot be resolved, the result must
remain partial or unavailable.

A lower storage-only price does not establish that
a storage class produces lower total expenditure.

### 35.7 Financial Savings

Let:

- C_base be the complete comparable baseline cost.
- C_option be the complete comparable alternative cost.

Absolute savings:

    Savings = C_base - C_option

Percentage savings:

    Savings_percent =
        (C_base - C_option) / C_base * 100

Percentage savings are undefined when the baseline
cost is zero.

Negative savings indicate increased expenditure.

A partial estimate must not be compared against a
complete estimate as though the financial scopes
were equivalent.

A separately labeled component-only comparison may
be provided when both options have the same explicit
component scope and complete pricing within that scope.

## 36. Cost Aggregation and Estimate Completeness

### 36.1 Aggregation Hierarchy

Costs are aggregated from:

1. Individual billing components.
2. Resource-level estimates.
3. Service-level breakdowns.
4. Infrastructure-level estimates.

Every included charge must be counted exactly once.

Service breakdowns and resource breakdowns are different
views of the same underlying charges.

They must not be added together to calculate the
infrastructure total.

### 36.2 Known Subtotals and Complete Totals

Known subtotal:

    Known_subtotal = sum(Known_component_costs)

A known subtotal is absent when no meaningful component
cost can be calculated.

A valid known subtotal may equal zero.

A complete total is available only when all required
components within the declared estimate scope are resolved.

For partial results:

    Known_subtotal = sum(Known_component_costs)

    Complete_total = None

Required unresolved components must remain listed.

### 36.3 Completeness Propagation

| Component coverage | Estimate completeness |
|---|---|
| All required charges resolved | COMPLETE |
| Some known charges and unresolved required charges | PARTIAL |
| No meaningful calculated costs | UNAVAILABLE |

A missing required resource charge must propagate to
the infrastructure completeness status.

A valid zero-usage component may have a zero variable
cost when no fixed charge or minimum commitment applies.

Unknown usage must not be interpreted as zero.

Invalid configurations must be reported separately from
financial limitations.

Empty draft scenarios must not be represented as complete
infrastructure estimates.

### 36.4 Provenance and Reproducibility

Every calculated component must retain:

- The requested configuration.
- The billable quantity and unit.
- The selected rate and rate identifier.
- The pricing source.
- The applicable pricing snapshot.
- The calculation assumptions.
- The financial period.
- Any exclusions or unresolved charges.

Recalculating with refreshed pricing may produce a
different estimate.

The application must distinguish historical results
from newly calculated results.

### 36.5 Contract Refinements

The data contracts defined in M0.6B must support:

- Explicit estimate scope and excluded components.
- Billable usage aggregation scope.
- Per-component pricing snapshot identifiers.
- Daily average expenditure.
- Running hourly versus average hourly expenditure.
- Unpriced tier usage.
- Per-option comparison validity.
- Commitment utilization and unused commitment costs.
- Amortized cost versus actual payment timing.

These refinements must be reflected in the executable
contracts during implementation.

## 37. Financial Verification Design

The following examples establish expected calculation
results for future automated tests.

### 37.1 Retrieved Pricing Examples

| Test | Inputs | Expected unrounded result |
|---|---|---:|
| EC2 monthly | 3 * 730 * 0.0104 | 22.776 |
| EC2 annual | 22.776 * 12 | 273.312 |
| S3 Standard | 500 * 0.023 | 11.50 |
| Lambda requests | 2000000 * 0.0000002 | 0.40 |
| Combined known monthly | 22.776 + 11.50 + 0.40 | 34.676 |
| Combined known annual | 34.676 * 12 | 416.112 |
| S3 known tier subtotal | 51200 * 0.023 | 1177.60 |

The combined example is partial because required
additional charges are not included.

### 37.2 Spot Comparison Example

Five m5.large instances running 730 hours per month.

Retrieved On-Demand rate:

    0.096 USD/hour

Retrieved Spot observation for us-east-1a:

    0.0128 USD/hour

Expected results:

    OnDemand_monthly = 5 * 730 * 0.096 = 350.40

    Spot_monthly = 5 * 730 * 0.0128 = 46.72

    Potential_monthly_savings = 303.68

    Potential_annual_savings = 3644.16

The expected savings percentage is approximately 86.67%.

This example assumes a constant observed Spot rate
and represents compute-only expenditure.

### 37.3 Reserved Commitment Example

Hypothetical inputs:

- One committed instance.
- 12-month commitment.
- 120 USD upfront.
- 0.03 USD recurring committed instance-hour.
- 730 committed hours per month.
- No uncovered usage.

Expected:

    Monthly_upfront_amortization = 120 / 12 = 10

    Monthly_recurring = 730 * 0.03 = 21.90

    Monthly_amortized_cost = 31.90

    Full_term_commitment_cost = 382.80

These inputs are hypothetical test values and must not
be described as actual AWS Reserved Instance rates.

### 37.4 Savings Plans Example

Hypothetical inputs:

- Two eligible instance-hours consumed per hour.
- 0.096 USD On-Demand rate per instance-hour.
- 0.06 USD assumed discounted rate.
- 0.06 USD hourly financial commitment.
- Uniform usage for 730 hours.

Expected:

    Covered_usage_per_hour = 1

    Uncovered_usage_per_hour = 1

    Unused_commitment_per_hour = 0

    Hourly_total = 0.06 + 0.096 = 0.156

    Monthly_total = 0.156 * 730 = 113.88

    OnDemand_monthly = 2 * 730 * 0.096 = 140.16

    Monthly_savings = 26.28

These values are modelling examples rather than retrieved
Savings Plans offers.

### 37.5 Boundary and Regression Requirements

Automated tests must cover:

- Zero usage.
- Genuine zero prices.
- Negative and nonfinite inputs.
- Invalid quantities.
- Runtime exceeding the billing period.
- Decimal precision preservation.
- Per-resource versus aggregate usage.
- Single-tier and graduated-tier calculations.
- Exact tier boundaries.
- Missing tier coverage.
- Conflicting or overlapping tiers.
- Aggregate-tier allocation reconciliation.
- Missing required billing components.
- Explicitly excluded charges.
- Partial and unavailable estimates.
- Mixed-currency rejection.
- Empty scenario handling.
- Annual calculation before presentation rounding.
- Reserved commitment underutilization.
- Reserved uncovered usage.
- Savings Plans unused commitment.
- Savings Plans uncovered usage.
- Zero commitment utilization handling.
- Invalid discounted rates.
- Zero-cost comparison baselines.
- Negative savings.
- Incompatible financial scopes.

These examples and requirements define future executable
tests.

They are not evidence that the estimation engine has
already been implemented or tested.

## 38. M0.6C.2 Checkpoint Outcome

The financial calculation design establishes:

- Consistent billing period assumptions.
- Decimal-based monetary calculation rules.
- Explicit billing unit normalization.
- Service-specific financial formulas.
- Graduated pricing tier handling.
- On-Demand and Spot comparison rules.
- Simplified commitment-based financial models.
- Absolute and percentage savings calculations.
- Estimate completeness propagation.
- Financial verification requirements.

The design remains proportionate to the educational
FinOps platform scope.

Application implementation, supplementary rate research
and executable financial tests remain pending.

M0.6C.3 will establish scenario persistence, runtime
pricing cache management and local data ownership.

---

## 39. Persistence and Runtime Data Design

### 39.1 Design Status

| Property | Value |
|---|---|
| Checkpoint | M0.6C.3 |
| Scope | M1, M3, M4 and M5 |
| Status | Proposed implementation design |
| Repository baseline | c521cb9 |

This section establishes the local persistence architecture
for infrastructure scenarios, retrieved pricing information
and reproducible financial estimates.

The design extends the shared data contracts, pricing
resolution rules and financial calculation specifications
established in the preceding checkpoints.

The initial implementation targets a local educational
FinOps application rather than a production multi-tenant
financial management platform.

### 39.2 Persistence Objectives

The persistence layer should:

- Support multiple named infrastructure scenarios.
- Preserve scenarios across application restarts.
- Keep persisted data independent of Streamlit session state.
- Support retrieval of saved configurations by M4.
- Store retrieved pricing information for further analysis.
- Avoid unnecessary repeated pricing API requests.
- Preserve pricing provenance and financial assumptions.
- Support reproducible saved estimates.
- Validate externally supplied and persisted data.
- Avoid committing user-generated runtime information to Git.
- Prevent accidental replacement of unrelated data.

### 39.3 Selected Persistence Mechanism

The proposed initial persistence mechanism is versioned
local JSON storage using the Python standard library.

Reasons include:

- Suitable complexity for the educational project.
- Human-readable scenario and pricing data.
- Straightforward serialization and validation.
- No additional database server.
- No additional deployment container.
- Independent testing using temporary directories.
- Portability between supported development environments.

Persistence operations should be encapsulated behind
repository interfaces.

Streamlit pages must not directly implement file access,
schema validation or financial snapshot serialization.

A database-backed repository may be introduced later
if the application develops multi-user or transactional
requirements beyond the supported local scope.

JSON persistence is not intended to provide production
database transaction guarantees.

## 40. Data Ownership and Storage Organization

### 40.1 Version-Controlled Data

The following locations are proposed for maintained
reference and demonstration datasets:

    data/pricing/reference_rates.json

    data/examples/

    tests/fixtures/

Reference pricing records must preserve their source,
verification date, configuration and financial limitations.

Example scenarios must be distinguishable from
user-generated configurations.

Test fixtures must not depend on mutable runtime data.

Version-controlled reference files must not contain
credentials, secrets or personal information.

The reference pricing dataset must not be overwritten
during ordinary pricing retrieval.

### 40.2 Runtime Data

The proposed local runtime root is:

    .finops-runtime/

Its initial organization is:

    .finops-runtime/
        pricing/
            catalogue_cache.json
            spot_cache.json
        scenarios/
            <scenario-id>.json
        snapshots/
            <snapshot-id>.json
        estimates/
            <estimate-id>.json

Runtime directories will be created on demand.

The root should be configurable to support isolated tests
and alternative local storage locations.

The default root must be resolved from the application
or repository location rather than depend on an arbitrary
current working directory.

The runtime root must be excluded from Git.

The corresponding ignore rule will be introduced during
the implementation foundation checkpoint.

Runtime files must not be confused with maintained
reference datasets.

### 40.3 Data Ownership Boundaries

The pricing package owns:

- Retrieved catalogue storage.
- Pricing cache access.
- Spot observation storage.
- Supplementary reference data access.

The infrastructure package owns:

- Infrastructure scenario serialization.
- Scenario repository operations.
- Resource and scenario validation.

The estimation package owns:

- Financial estimate serialization.
- Pricing snapshot references.
- Saved infrastructure estimation results.

The comparison package owns:

- Pricing comparison contracts.
- Financial comparison result generation.

Comparison results may initially be retained in session
state or explicitly exported.

Persistent comparison storage may be introduced when
required by the implementation.

Other team modules may consume repository interfaces
but must not modify private storage files directly.

The runtime namespace must not interfere with Floci's
Docker volume or another team member's runtime files.

## 41. Infrastructure Scenario Persistence

### 41.1 Scenario Document Structure

Each saved scenario should be represented by one
versioned JSON document.

Required top-level fields include:

| Field | Meaning |
|---|---|
| schema_version | Persistence schema version |
| scenario_id | Stable unique scenario identifier |
| name | Human-readable scenario name |
| description | Optional scenario description |
| revision | Persisted scenario revision |
| created_at | Creation timestamp in UTC |
| updated_at | Last successful update timestamp in UTC |
| resources | Collection of resource configurations |

The initial persistence schema version is 1.

Scenario identifiers should use UUIDs generated by
the application.

Resource identifiers must be unique within the scenario.

Scenario names are display values rather than file paths.

The repository must derive file names from validated
identifiers rather than directly from user-supplied names.

Decimal values must be serialized as decimal strings.

Timestamps must preserve their timezone information.

### 41.2 Scenario Repository Operations

The proposed repository interfaces include:

| Operation | Responsibility |
|---|---|
| create | Save a new scenario with a unique identifier |
| get | Retrieve and validate an existing scenario |
| list | Return saved scenario summaries |
| update | Persist a validated scenario revision |
| duplicate | Create an independent copy with new identifiers |
| delete | Remove an explicitly selected saved scenario |

Creation must not overwrite an existing scenario.

Updating a scenario must preserve its identifier and
creation timestamp.

A successful update must increment its revision and
record the new update timestamp.

Duplicating a scenario must produce independent resource
configurations and a new scenario identifier.

Deleting a scenario must require an explicit user action.

Deletion must not automatically remove unrelated pricing
data, historical snapshots or saved financial results.

### 41.3 Scenario Validation

Before saving a scenario, validate:

- Supported schema version.
- Valid scenario identifier.
- Nonempty scenario name.
- Resource identifier uniqueness.
- Valid resource quantities.
- Required service-specific configuration fields.
- Finite and nonnegative usage values.
- Applicable billing-period constraints.
- Supported serialized value types.

The repository must validate documents again when loading
them from disk.

Externally modified JSON must not bypass validation.

A saved draft may contain no resources.

An empty scenario must not be treated as a completed
infrastructure estimate.

An invalid scenario must not silently become a new
empty configuration.

### 41.4 Scenario Revision and Editing

The proposed update interface should accept the
expected persisted revision.

When a caller attempts to update an older revision,
the repository should report a stale-revision conflict.

Within the supported single-process application,
revision checks and writes must be protected by an
appropriate shared synchronization mechanism.

This prevents ordinary overlapping Streamlit sessions
from silently overwriting a newer revision.

The initial implementation does not guarantee safe
concurrent writes from independent application processes.

Multi-process synchronization and distributed
transaction management are outside the initial scope.

The presentation layer should preserve an unsaved
draft if an update fails.

### 41.5 Example Scenario Documents

Demonstration scenarios should be maintained separately
from user-generated scenarios.

Loading an example should create an independent draft.

Editing or saving that draft must not modify the
original version-controlled example file.

Example scenarios should exercise the supported pricing
and estimation workflows without requiring the creation
of real AWS resources.

## 42. Pricing Catalogue and Cache Management

### 42.1 Catalogue Persistence

M1 must store retrieved pricing information in a
structured form suitable for further analysis.

The retrieved catalogue should preserve:

- Schema version.
- Pricing source.
- Local endpoint identity.
- Floci version when available.
- Retrieval timestamp.
- Service and region selection.
- Applicable query parameters.
- Normalized pricing records.
- Catalogue versions and effective dates.
- Retrieval completeness.
- Source diagnostics.

Only validated records should be available for financial
calculations.

The cache must not represent incomplete retrieval as
a complete service catalogue.

### 42.2 Cache Identity

Cache entries must be associated with their applicable
query context.

Relevant identity information includes:

- Source endpoint.
- Service code.
- Region.
- Requested pricing model.
- Configuration filters.
- Cost component where applicable.
- Currency.
- Schema or normalization version.

Equivalent query filters may be canonicalized to
produce a stable cache identity.

Different regions, pricing models and resource
configurations must not share an incompatible cache entry.

### 42.3 Cache Freshness

The proposed initial catalogue cache freshness interval
is 15 minutes.

This is an application performance policy rather than
an AWS pricing validity guarantee.

The interval should be configurable.

Every displayed cached result must retain its original
retrieval timestamp.

Users must be able to request a pricing refresh.

A successful refresh replaces the relevant cache entry
only after the new retrieval has been validated.

A failed refresh must not overwrite a previously valid
cache entry with an empty or invalid result.

### 42.4 Stale Data and Retrieval Errors

Freshness must be distinguished from financial
applicability.

Expired cache entries must not be represented as newly
retrieved prices.

If a new retrieval fails:

- Preserve the original API failure diagnostics.
- Retain previously valid cached data where appropriate.
- Identify the cached data as stale.
- Do not silently substitute stale data for a live result.
- Require an explicit policy or user action to use stale
  pricing for a financial calculation.

A strict live retrieval operation must report the
retrieval failure rather than automatically use stale data.

An intentionally selected offline reference-only mode
must remain distinguishable from Floci-retrieved pricing.

### 42.5 Spot Observation Storage

Spot observations require separate cache identity.

Relevant fields include:

- Instance type.
- Operating system or product description.
- Region.
- Availability zone.
- Requested history window.
- Observation timestamp.
- Retrieval timestamp.

A proposed initial Spot cache freshness interval is
five minutes.

Cache freshness does not establish that the underlying
Spot observation is recent.

The observation timestamp must be evaluated separately.

A historical Spot observation must not be represented
as a guaranteed current or future price.

## 43. Financial Snapshots and Saved Estimates

### 43.1 Pricing Snapshot Purpose

A pricing snapshot preserves the exact financial inputs
selected during an estimation or comparison operation.

Snapshots are distinct from replaceable pricing caches.

A snapshot must remain immutable after creation.

Refreshing pricing information must not modify existing
saved snapshots.

### 43.2 Snapshot Contents

A snapshot should preserve:

| Field | Meaning |
|---|---|
| schema_version | Snapshot schema version |
| snapshot_id | Stable unique identifier |
| created_at | Snapshot creation timestamp |
| scenario_id | Associated scenario identifier if applicable |
| scenario_revision | Configuration revision used |
| pricing_records | Exact selected pricing records |
| spot_observations | Selected Spot rates where applicable |
| billing_period | Financial projection assumptions |
| assumptions | Explicit financial modelling assumptions |
| exclusions | Charges outside the declared scope |
| diagnostics | Missing or unsupported pricing information |

Snapshots must preserve original rate precision,
source references and billing dimensions.

A snapshot must not invent pricing for unresolved
cost components.

### 43.3 Saved Infrastructure Estimates

A saved estimate should retain:

- Its own unique estimate identifier.
- Schema and calculation model versions.
- Estimation timestamp.
- Exact scenario configuration used.
- Associated scenario identifier and revision.
- Pricing snapshot identifier.
- Resource-level cost components.
- Service-level breakdowns.
- Monthly and annual financial results.
- Completeness status.
- Unresolved components and exclusions.
- Calculation assumptions.

The configuration used must be preserved independently
of later edits to the active infrastructure scenario.

A saved estimate must remain understandable even if its
original scenario is subsequently deleted.

### 43.4 Recalculation

Loading a historical estimate must not automatically
perform new pricing retrieval.

Historical results represent the original calculation.

A user may explicitly recalculate using:

- The preserved configuration and pricing snapshot.
- The preserved configuration and refreshed pricing.
- A newer scenario revision and newly resolved pricing.

Recalculation should create a new financial result
rather than silently replace the historical result.

The calculation model version must be recorded.

Exact historical recomputation is only guaranteed when
the applicable calculation behaviour remains available.

### 43.5 Persistence Ordering

When explicitly saving a financial estimate:

1. Validate the result and its required metadata.
2. Persist the associated immutable pricing snapshot.
3. Persist the estimate referencing that snapshot.
4. Report success only after the required files exist.

If the estimate write fails after snapshot creation,
the application must report the incomplete save.

An unreferenced snapshot may remain after such a failure.

Automatic destructive cleanup is not required for
the initial implementation.

Multiple JSON file writes must not be represented as
one atomic database transaction.

## 44. Storage Integrity and Verification

### 44.1 Serialization Rules

Persisted data should use:

- UTF-8 encoding.
- Valid JSON.
- Explicit schema versions.
- Decimal strings for monetary and precise usage values.
- ISO 8601 timestamps with timezone information.
- Stable resource and document identifiers.
- Explicit null values for unknown information.

Serialization must reject nonfinite financial values.

Unsupported schema versions must produce a clear error.

The application must not silently reinterpret an
unknown schema version as the current version.

### 44.2 Safe File Writing

Individual document updates should use atomic file
replacement where supported by the local filesystem.

The intended sequence is:

1. Validate the document before writing.
2. Serialize the complete document.
3. Write to a temporary file in the destination directory.
4. Flush the temporary file.
5. Replace the intended destination atomically.
6. Report the operation result.
7. Clean up temporary files created by a failed operation
   where safe.

Creation must distinguish new documents from updates.

An existing document must not be overwritten by a
create operation.

The original destination should remain unchanged if
validation fails before replacement.

Atomic replacement reduces the risk of partial JSON
writes but does not guarantee recovery from every
filesystem or hardware failure.

### 44.3 Path Safety

Repository file access must be restricted to the
configured storage root.

User-entered names must not be interpreted as paths.

Persisted document identifiers must be validated before
constructing file paths.

Path traversal, unexpected absolute paths and invalid
identifiers must be rejected.

Secrets and credentials must never be included in
scenario documents, pricing caches or financial snapshots.

### 44.4 Error Handling

The persistence layer must distinguish:

- Document not found.
- Duplicate document identifier.
- Invalid JSON.
- Invalid persisted schema.
- Unsupported schema version.
- Invalid resource configuration.
- Stale scenario revision.
- File permission failure.
- File write failure.
- Invalid storage path.
- Missing snapshot referenced by a saved estimate.

A corrupted file must not be silently replaced with
an empty document.

Invalid documents must remain available for inspection
or explicit recovery.

The presentation layer must communicate storage errors
without misleading the user about save success.

### 44.5 Streamlit Session State

Streamlit session state should hold temporary UI data,
including:

- The currently selected scenario identifier.
- Unsaved resource configuration drafts.
- Current page filters and form values.
- Temporary calculation results.
- Unsaved-change indicators.

Session state must not be the sole persistent source
of saved infrastructure configurations.

Streamlit reruns must not create duplicate scenarios
or repeat unintended persistence operations.

Saving, duplicating and deleting a scenario must be
triggered by explicit user actions.

Switching scenarios with unsaved edits should preserve
the draft or request an explicit discard decision.

Shared session-state keys should be namespaced to
avoid conflicts between team modules.

### 44.6 Verification Requirements

Future automated persistence tests must include:

- Runtime directory creation.
- Configurable storage roots.
- Independent temporary test directories.
- Scenario creation and loading.
- Multiple saved scenarios.
- Scenario update and revision increments.
- Duplicate scenario creation.
- Independent duplicated configurations.
- Explicit scenario deletion.
- Duplicate identifier rejection.
- Missing document handling.
- Invalid JSON handling.
- Unsupported schema version rejection.
- Decimal serialization round trips.
- Timestamp serialization round trips.
- Unknown versus zero usage preservation.
- Path traversal rejection.
- Stale revision rejection.
- Failed write preservation.
- Cache identity separation.
- Cache expiration and refresh behaviour.
- Failed refresh preservation.
- Stale pricing diagnostics.
- Snapshot immutability.
- Historical estimate preservation after scenario edits.
- Historical estimate preservation after pricing refresh.
- Missing snapshot detection.
- Runtime data exclusion from Git.
- Scenario retrieval after application restart.

The live application verification should demonstrate
creating, saving, reopening and estimating multiple
infrastructure scenarios.

These requirements describe future executable tests.

They do not represent tests that have already passed.

## 45. M0.6C.3 Checkpoint Outcome

The proposed persistence architecture establishes:

- Versioned local JSON storage.
- Separation of reference and runtime data.
- Scenario repository responsibilities.
- Scenario lifecycle and revision handling.
- Pricing catalogue persistence and cache freshness.
- Explicit stale-pricing behaviour.
- Immutable financial snapshots.
- Historical estimate preservation.
- Safe serialization and file access.
- Streamlit session-state boundaries.
- Persistence verification requirements.

M0.6C completes the financial and persistence design
for the four assigned functional modules.

M0.6D will consolidate the architecture and introduce
the initial Python package structure, runtime ignore
rules and executable implementation foundation.

Application services, persistence implementations,
reference pricing datasets and automated behavioural
tests remain subsequent development work.

Shared integration conventions remain subject to
team coordination.

---

## 46. Consolidated Implementation Decisions

### 46.1 Status and Scope

Checkpoint: M0.6D.1

The preceding architecture sections establish the proposed
design for M1, M3, M4 and M5.

This section consolidates refinements introduced throughout
the design checkpoints.

Where an earlier proposal differs from a later refinement,
the consolidated implementation decisions below take
precedence.

Shared team integration conventions remain subject to
coordination.

### 46.2 Contract Refinements

The executable infrastructure scenario contract must include
a persisted revision in addition to the fields defined in
Section 18.4.

Scenario identity and revision must remain distinguishable
from persistence schema version.

The pricing source and pricing resolution status are
independent concepts.

A supplementary resolution must retain diagnostics from
the unsuccessful primary source attempt.

Pricing queries must identify the relevant billing component.

Resolution of one component does not imply that a complete
resource has been priced.

Cost components must retain applicable rate identifiers,
pricing snapshot references, financial scope and usage
aggregation semantics.

Infrastructure estimates must distinguish known subtotals
from complete totals and preserve excluded, missing and
not-applicable charge categories.

Comparison results must preserve comparability at the
individual option level.

### 46.3 Financial Consistency

The default representative billing period is 730 hours
per month and 12 months per year.

Average days per month are derived from hours per month
divided by 24.

The implementation must not permit inconsistent independently
configured hour and day values.

Financial arithmetic uses Decimal.

Presentation rounding uses ROUND_HALF_UP.

Annual totals are calculated from unrounded monthly values.

Graduated pricing tiers must respect their documented
aggregation scope and applicable usage boundaries.

Missing tier coverage must remain visible.

Reserved Instance and Savings Plans calculations are
simplified educational models with explicit assumptions.

Monthly Reserved Instance coverage is an approximation
for the supported homogeneous workload model.

Savings Plans coverage is evaluated for uniform hourly
usage or explicitly defined workload intervals.

### 46.4 Cache Consistency

A successful validated empty response is a valid source
outcome and must not be confused with a failed retrieval.

A successful complete refresh may replace an earlier
matching cache entry with an empty result.

A failed or incomplete refresh must not overwrite a
previously valid complete cache entry.

Stale pricing use requires an explicit policy or action.

Cache freshness does not establish the effective validity
of the original price.

Spot observation time and retrieval time are distinct.

### 46.5 Persistence Consistency

The default runtime directory is:

    .finops-runtime/

Runtime paths must not depend on the process working
directory.

Runtime storage roots must be configurable.

Reference data remains separate from user-generated data.

Scenario updates require revision validation.

Revision checks and writes must be synchronized within
the supported single-process application.

JSON file replacement does not provide a multi-document
database transaction.

Historical estimates retain their original configuration,
pricing context and calculation version.

Historical financial snapshots must not be overwritten
during pricing refreshes.

### 46.6 Implementation Boundaries

The initial Python packages are:

- finops.pricing
- finops.infrastructure
- finops.estimation
- finops.comparison

The shared runtime configuration belongs to finops.config.

The package foundation must not import Streamlit or
communicate with AWS during ordinary imports.

The existing app.py, start_floci.py, Docker Compose
configuration and dependency requirements remain preserved.

The initial testing foundation uses the Python standard
library unittest framework.

Additional dependencies require a documented justification.

### 46.7 Implementation Sequence

Development proceeds in dependency order:

1. M1 - Pricing Explorer and reusable pricing foundation.
2. M3 - Infrastructure Builder and scenario persistence.
3. M4 - Infrastructure Cost Estimator.
4. M5 - Pricing Model Comparison.
5. Cross-module integration and regression testing.
6. Documentation and demonstration preparation.
7. Pull request and team integration.

External team modules are integration consumers and are
not additional assigned implementation responsibilities.

## 47. Initial Implementation Foundation

M0.6D.1 introduces the package namespace, runtime
configuration, runtime ignore policy and executable
foundation tests.

The package structure does not represent completed
pricing, infrastructure, estimation or comparison services.

Functional implementation and its associated behavioural
tests remain part of the individual module milestones.

No actual cloud resources are provisioned by this checkpoint.
