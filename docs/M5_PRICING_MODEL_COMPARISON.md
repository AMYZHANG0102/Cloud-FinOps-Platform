# M5 - Cloud Pricing Model Comparison

## 1. Purpose

Module 5 compares alternative cloud pricing arrangements using
equivalent resource workloads and historical infrastructure
estimates produced by Module 4.

The module demonstrates the financial trade-offs between
On-Demand pricing, Reserved Instances, Savings Plans,
Spot Instances and S3 storage classes.

It does not purchase commitments, provision resources,
perform storage migrations or modify existing infrastructure.

## 2. Implemented Capabilities

| Capability | Implementation |
|---|---|
| Historical financial baseline | Saved M4 infrastructure estimate |
| Resource selection | Eligible EC2 and S3 resource groups |
| On-Demand comparison | Historical EC2 compute charges |
| Reserved Instances | Upfront and recurring commitment assumptions |
| Savings Plans | Hourly spending commitment assumptions |
| Spot Instances | Matching Floci EC2 Spot price observations |
| Storage-class comparisons | Standard and four alternative S3 classes |
| Financial periods | Monthly and annual modeled expenditure |
| Savings analysis | Signed savings amounts and percentages |
| Commitment coverage | Covered and uncovered instance-hours |
| Infrastructure projections | Independent single-resource replacements |
| Visual analysis | Resource and infrastructure comparison charts |
| Pricing transparency | Sources, assumptions, evidence and exclusions |
| Data export | Exact financial comparison CSV |

## 3. Application Architecture

| File | Responsibility |
|---|---|
| finops/comparison/models.py | Comparison scope, pricing options and signed savings |
| finops/comparison/compute.py | EC2 purchasing model calculations |
| finops/comparison/storage.py | S3 storage-class calculations |
| finops/comparison/engine.py | Historical integration and comparison orchestration |
| pages/05_Pricing_Model_Comparison.py | Interactive Streamlit dashboard |

Processing sequence:

    M1 Pricing Explorer
        -> M3 Infrastructure Builder
        -> M4 Cost Estimator
        -> Saved historical infrastructure estimate
        -> M5 Pricing Comparison Engine
        -> Compute or storage comparison
        -> Financial report
        -> Streamlit visualization and CSV export

The comparison engine reuses existing pricing and estimation
contracts instead of reproducing their responsibilities.

Financial models remain independent of the Streamlit interface.

## 4. Comparison Scope

A comparison identifies:

- The original historical estimate.
- The selected infrastructure resource.
- The included billing components.
- The applicable baseline pricing model.
- Equivalent modeled financial exclusions.

The resource-specific calculators preserve equivalent workload
consumption across alternatives.

ComparisonScope normalizes billing-component ordering and rejects
duplicate component identities.

PricingComparison rejects mismatched billing scopes and exclusions.

A complete selected resource may be compared even when other
resources in the historical infrastructure remain unpriced.

## 5. Financial Conventions

All authoritative financial calculations use Decimal and USD.

Monthly savings:

    On-Demand monthly cost - alternative monthly cost

Annual savings:

    Monthly savings * 12

Savings percentage:

    Monthly savings / baseline monthly cost * 100

Negative savings indicate that an alternative costs more.

A zero baseline prevents meaningful percentage savings.

Incomplete baseline or alternative pricing prevents definitive
savings calculations.

An average month contains 730 hours. Annual projections assume
unchanged monthly workloads and pricing.

ROUND_HALF_UP is used for currency and percentage presentation.
Calculations are performed before display rounding.

## 6. Historical EC2 On-Demand Baseline

The compute comparison accepts a fully priced, positive-usage,
flat-rate historical EC2 compute component.

Supported configurations use Linux, shared tenancy and no
additional preinstalled licensed software.

The historical hourly rate and recorded compute consumption must
reconcile exactly with the stored monthly compute charge.

Only EC2 instance compute expenditure is compared.

EBS storage, networking and unrelated infrastructure charges
remain outside the selected compute billing scope.

## 7. Reserved Instance Model

The Reserved Instance comparison uses explicitly hypothetical
matching commitment assumptions.

Inputs:

- Reserved instance quantity.
- Recurring hourly rate.
- Upfront payment per reserved instance.
- Commitment term of 12 or 36 months.

Calculation:

    Committed hours =
        Reserved quantity * 730

    Covered hours =
        Minimum of fleet quantity and reserved quantity
        * monthly runtime per instance

    Uncovered hours =
        Total workload hours - covered hours

    Monthly upfront amortization =
        Reserved quantity * upfront payment / term months

    Monthly recurring commitment =
        Committed hours * recurring hourly rate

    Uncovered On-Demand expenditure =
        Uncovered hours * historical On-Demand hourly rate

    Alternative monthly expenditure =
        Upfront amortization
        + recurring commitment
        + uncovered On-Demand expenditure

Unused reserved hours are reported separately.

The model retains the financial consequences of underutilization
and overcommitment.

The comparison is an illustrative amortized financial model,
not a retrieved AWS Reserved Instance offering or cash-flow forecast.

## 8. Savings Plans Model

The Savings Plans comparison uses a simplified no-upfront
hourly spending commitment.

Inputs:

- Hourly spending commitment.
- Discounted hourly instance rate.
- Commitment term of 12 or 36 months.

Calculation:

    Active-hour discounted expenditure =
        Fleet quantity * discounted hourly rate

    Used commitment per active hour =
        Minimum of hourly commitment and
        active-hour discounted expenditure

    Covered equivalent instance-hours =
        Used commitment per active hour
        / discounted hourly rate
        * monthly runtime

    Monthly commitment expenditure =
        Hourly commitment * 730

    Uncovered expenditure =
        Uncovered instance-hours * On-Demand rate

    Alternative monthly expenditure =
        Monthly commitment expenditure
        + uncovered expenditure

Unused hourly commitment does not roll forward.

The model assumes concurrent fleet usage for its recorded
monthly runtime.

Fractional coverage represents equivalent financial allocation,
not fractional instance deployment.

Account-wide Savings Plans allocation and interactions with other
discount arrangements are outside the modeled scope.

## 9. Spot Instance Model

Spot pricing is retrieved using the existing Module 1
SpotPricingService.

Observations must match:

- Instance type.
- Region.
- Linux/UNIX product description.
- USD hourly rate.
- Floci EC2 API pricing provenance.

The most recent usable observation per matching Availability Zone
is selected.

The comparison retains both observation and retrieval timestamps.

Calculation:

    Spot monthly expenditure =
        Total workload instance-hours * observed Spot hourly rate

The observation is held constant for the modeled projection.

Floci observations are emulator data, not live AWS market quotations.

Spot availability, interruptions, replacement overhead and future
price changes are not comprehensively modeled.

Failed or empty Spot retrieval produces an unavailable alternative.
No invented replacement Spot price is introduced.

Other valid purchasing-model comparisons remain available.

## 10. S3 Storage-Class Comparisons

Supported historical baseline:

- S3 Standard.

Supported alternative classes:

- Standard - Infrequent Access.
- One Zone - Infrequent Access.
- Glacier Flexible Retrieval.
- Glacier Deep Archive.

The historical Standard baseline must have complete modeled costs.

The current implementation supports a single S3 resource group
per selected region to avoid account-level repricing ambiguity.

Alternative classes use explicitly hypothetical flat rates.

The model retains the same aggregate storage capacity,
PUT requests, GET requests and outbound transfer.

Retrieval volume is a separate explicit workload assumption.

| Billing component | Alternative calculation |
|---|---|
| Storage | GB-month * assumed storage rate |
| PUT requests | Requests / 1,000 * assumed PUT rate |
| GET requests | Requests / 1,000 * assumed GET rate |
| Retrieval | Retrieved GB * assumed retrieval rate |
| Outbound transfer | Transferred GB * assumed transfer rate |

A missing rate is not equivalent to zero.

Zero-usage components do not require pricing.

Positive usage with missing pricing prevents a complete alternative
cost and definitive savings.

Operational considerations are presented separately from
financial results.

Lower modeled storage expenditure does not establish equivalent
availability, resilience, retention requirements or access latency.

Storage lifecycle optimization remains within Module 13 scope.

## 11. Pricing Provenance

| Pricing source | Meaning |
|---|---|
| FLOCI_PRICING_API | Historical emulator catalogue rates |
| FLOCI_EC2_API | Retrieved emulator Spot observations |
| REFERENCE_DATA | Applicable supplementary historical reference rates |
| ESTIMATION_ASSUMPTION | Explicit hypothetical financial inputs |

Reserved Instance and Savings Plans alternatives may combine
hypothetical commitment assumptions with retrieved historical
On-Demand charges for uncovered usage.

Alternative S3 class prices are explicitly hypothetical.

Default values are editable demonstration assumptions and are
not represented as current commercial AWS prices.

## 12. Infrastructure Projections

Infrastructure projections replace only the selected resource
billing scope.

Calculation:

    Projected infrastructure monthly cost =
        Original complete infrastructure monthly cost
        - original selected resource monthly cost
        + alternative selected resource monthly cost

Unrelated historical charges remain unchanged.

A complete infrastructure baseline and complete comparable
alternative are both required.

Each projection is independent.

Multiple alternative projections must not be added together.

This feature is not an account-wide optimization engine and
does not apply purchasing changes to infrastructure scenarios.

## 13. User Interface

The Pricing Model Comparison dashboard provides:

- Historical estimate selection.
- Historical scenario revision and pricing policy display.
- Resource eligibility and unsupported-resource explanations.
- EC2 purchasing model selection.
- Editable Reserved Instance assumptions.
- Editable Savings Plans assumptions.
- Optional Floci Spot retrieval and Availability Zone selection.
- S3 storage-class selection and editable rates.
- Explicit comparison generation.
- Monthly and annual expenditure tables.
- Signed savings and savings percentages.
- Resource cost comparison charts.
- Infrastructure projection charts.
- Detailed commitment and storage billing breakdowns.
- Pricing sources, assumptions, evidence and exclusions.
- Complete comparison CSV export.

Generation occurs only after an explicit user action.

Ordinary reruns do not automatically retrieve additional Spot
prices.

Changed inputs hide outdated results until regeneration.

Invalid input does not leave an earlier result visible.

Incomplete pricing is not displayed as a complete zero-cost result.

Comparison results are session-based and exportable.

The module does not introduce a separate persistent comparison
repository.

## 14. CSV Export

The comparison CSV includes:

- Historical estimate and scenario identifiers.
- Historical scenario revision.
- Resource identity, name and region.
- Included billing components.
- Baseline and every generated alternative.
- Pricing models and sources.
- Financial coverage status.
- Known monthly subtotal.
- Complete monthly and annual costs.
- Monthly and annual savings.
- Savings percentage.
- Infrastructure projections.
- Pricing details.
- Assumptions and exclusions.

Financial fields preserve calculation precision.

Unavailable values remain empty rather than becoming zero.

Text fields include spreadsheet formula-injection protection.

The file uses UTF-8 with a byte-order mark for compatibility
with common spreadsheet applications.

## 15. Verified Demonstration Scenario

Historical scenario: E-commerce Production.

Scenario revision: 6.

Original modeled infrastructure monthly cost: USD 63.12392.

Original modeled infrastructure annual cost: USD 757.48704.

### EC2 configuration

| Configuration | Value |
|---|---|
| Resource | Web Servers |
| Instance type | t3.micro |
| Quantity | 3 |
| Region | us-east-1 |
| Monthly runtime per instance | 730 hours |
| Total compute usage | 2,190 instance-hours |
| Historical hourly rate | USD 0.0104 |
| Historical monthly compute charge | USD 22.776 |

Illustrative Reserved Instance assumptions:

- Reserved quantity: 2.
- Recurring hourly rate: USD 0.005.
- Upfront payment per instance: USD 12.
- Commitment term: 12 months.

Illustrative Savings Plans assumptions:

- Hourly spending commitment: USD 0.012.
- Discounted instance rate: USD 0.006.
- Commitment term: 12 months.

Verified M5.5 demonstration:

| Alternative | Monthly cost | Monthly savings | Savings percentage |
|---|---:|---:|---:|
| On-Demand | USD 22.78 | Baseline | Baseline |
| Reserved Instances | USD 16.89 | USD 5.88 | 25.83% |
| Savings Plan | USD 16.35 | USD 6.42 | 28.21% |
| Spot - us-east-1a | USD 9.64 | USD 13.14 | 57.69% |

The Spot demonstration used a Floci observation of USD 0.0044
per instance-hour.

Future retrievals may return different observations.

Exact modeled monthly alternative costs:

- Reserved Instances: USD 16.892.
- Savings Plan: USD 16.352.
- Demonstration Spot: USD 9.636.

### S3 configuration

| Configuration | Value |
|---|---|
| Resource | Application Object Storage |
| Region | us-east-1 |
| Quantity | 1 |
| Storage capacity | 500 GB |
| PUT requests | 0 |
| GET requests | 0 |
| Outbound transfer | 0 GB |
| Retrieval | 0 GB |
| Historical Standard monthly cost | USD 11.50 |

| Storage class | Assumed rate | Monthly cost | Savings percentage |
|---|---:|---:|---:|
| Standard | Historical USD 0.023 | USD 11.50 | Baseline |
| Standard-IA | USD 0.0125 | USD 6.25 | 45.65% |
| One Zone-IA | USD 0.010 | USD 5.00 | 56.52% |
| Glacier Flexible Retrieval | USD 0.004 | USD 2.00 | 82.61% |
| Glacier Deep Archive | USD 0.001 | USD 0.50 | 95.65% |

All alternative storage rates in this example are hypothetical.

Zero access and transfer quantities are explicit assumptions
of this demonstration workload.

### Infrastructure expenditure projections

| Independent alternative | Monthly | Annual |
|---|---:|---:|
| Original infrastructure | USD 63.12 | USD 757.49 |
| Reserved Instances | USD 57.24 | USD 686.88 |
| Savings Plan | USD 56.70 | USD 680.40 |
| Demonstration Spot | USD 49.98 | USD 599.81 |
| Standard-IA | USD 57.87 | USD 694.49 |
| One Zone-IA | USD 56.62 | USD 679.49 |
| Glacier Flexible Retrieval | USD 53.62 | USD 643.49 |
| Glacier Deep Archive | USD 52.12 | USD 625.49 |

All totals use exact arithmetic before presentation rounding.

## 16. Partial Baseline Behavior

The saved Floci-only infrastructure estimate has a known
monthly subtotal of USD 34.676.

Its complete infrastructure cost is unavailable.

Its EC2 compute component remains fully priced at USD 22.776.

Module 5 therefore permits valid resource-level comparisons
while suppressing complete infrastructure projections.

This distinction prevents an incomplete infrastructure
subtotal from being represented as a complete cost.

## 17. Running the Dashboard

From the repository root, start Floci:

    docker compose up -d

Launch Streamlit:

    & ".\.venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501

Open:

    http://127.0.0.1:8501

Using the existing modules:

1. Review supported prices in Pricing Explorer.
2. Create and save a scenario in Infrastructure Builder.
3. Generate an estimate in Cost Estimator.
4. Save the historical estimate.
5. Open Pricing Model Comparison.
6. Select the saved estimate and eligible resource.
7. Select alternatives and review pricing assumptions.
8. Generate the comparison.
9. Inspect costs, savings, charts and pricing evidence.
10. Download the comparison CSV.

Historical runtime documents are intentionally excluded from Git.

A new installation must create its own scenarios and estimates.

## 18. Automated Verification

| Checkpoint | New passing tests |
|---|---:|
| M5.1 - Comparison contracts | 12 |
| M5.2 - EC2 purchasing models | 16 |
| M5.3 - Storage pricing comparisons | 12 |
| M5.4 - Comparison integration engine | 12 |
| M5.5 - Streamlit dashboard | 11 |
| Total M5 tests | 63 |
| Previous foundation, M1, M3 and M4 tests | 341 |
| Complete regression suite | 404 |

Verification covered:

- Positive, negative and zero savings.
- Missing and incomplete financial baselines.
- Equivalent billing scope enforcement.
- Reserved Instance commitment costs.
- Savings Plans hourly commitment utilization.
- Underutilization and overcommitment.
- Matching Spot observations and retrieval failure isolation.
- Alternative storage charges and retrieval expenditure.
- Infrastructure projection accuracy.
- Historical estimate and snapshot integrity.
- Streamlit dashboard interactions.
- Changed-input and invalid-input handling.
- CSV financial precision and unavailable-value handling.
- Preservation of existing source and runtime data.

Run the complete suite:

    & ".\.venv\Scripts\python.exe" -B -m unittest discover -s tests -p "test_*.py" -q

## 19. Manual Browser Acceptance

The developer confirmed the following M5.6 checks during
the publication checkpoint:

- Application startup and navigation.
- EC2 comparisons, charts and financial breakdowns.
- Editable commitment assumptions.
- S3 storage-class comparisons.
- Missing pricing protection.
- Partial infrastructure baseline handling.
- EC2 and S3 CSV downloads.
- Cross-module navigation.

Automated Streamlit AppTest verification and manual browser
acceptance are distinct forms of evidence.

## 20. Limitations and Future Compatibility

- Current EC2 comparisons support matching Linux/shared
  configurations with complete positive-usage flat-rate baselines.
- Reserved Instance and Savings Plans rates are hypothetical.
- Savings Plans use a simplified no-upfront concurrent-fleet model.
- Account-wide commitment allocation is not modeled.
- Spot observations are not guarantees of capacity or future prices.
- Alternative S3 prices use hypothetical flat-rate assumptions.
- Minimum storage duration, early deletion, object-size overhead,
  transition charges and restoration overhead are excluded.
- Operational suitability is not established solely by cost.
- Taxes, credits, promotional allowances and private discounts
  are not comprehensively modeled.
- Infrastructure projections replace one selected resource only.
- Comparisons are not independently persisted.
- Current Streamlit versions may emit deprecation warnings for
  use_container_width. The parameter remains functional in the
  verified development environment. Future upgrades may require
  migration to the width parameter.

## 21. Assigned Module Completion

Member 2 implementation scope:

| Module | Implementation status |
|---|---|
| M1 - Cloud Service Pricing Explorer | Complete |
| M3 - Cloud Infrastructure Configuration Builder | Complete |
| M4 - Cloud Infrastructure Cost Estimator | Complete |
| M5 - Cloud Pricing Model Comparison | Complete |

The original team module allocation is unchanged.

This completion status refers to the assigned implementation
on the Member 2 feature branch.

Shared-branch integration, other team members' modules and
overall term project acceptance remain separate activities.
