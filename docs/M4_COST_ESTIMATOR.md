# M4 - Cloud Infrastructure Cost Estimator

## 1. Purpose

Module 4 estimates hypothetical cloud infrastructure expenditure
using persistent infrastructure configurations from Module 3 and
pricing information from Module 1.

The module provides reusable financial results for Module 5 and
potential subsequent team integration.

It does not provision infrastructure or generate actual AWS bills.

## 2. Implemented Capabilities

| Capability | Implementation |
|---|---|
| Infrastructure configuration input | Persistent M3 scenarios |
| Pricing retrieval | Existing M1 pricing resolver |
| Hourly expenditure | Average hourly and applicable compute-hour rates |
| Daily expenditure | Average daily projections |
| Monthly expenditure | Component-level billing calculations |
| Annual expenditure | Twelve-month projections |
| Resource expenditure | Resource-level aggregation |
| Service expenditure | AWS service-level aggregation |
| Infrastructure expenditure | Complete totals and known subtotals |
| Visualization | Resource and service distribution charts |
| Pricing transparency | Rates, sources, diagnostics and coverage |
| Historical results | Immutable estimates and pricing snapshots |
| Data export | Complete billing-component CSV |

## 3. Application Architecture

| File | Responsibility |
|---|---|
| finops/estimation/financial.py | Decimal arithmetic, tier calculations and cost summaries |
| finops/estimation/components.py | Infrastructure-to-billing-component mapping |
| finops/estimation/engine.py | Pricing resolution, tier pooling and estimation |
| finops/estimation/repository.py | Immutable historical persistence |
| pages/04_Cost_Estimator.py | Interactive Streamlit dashboard |

Processing sequence:

    Saved infrastructure scenario
        -> Monthly billing components
        -> Pricing resolution
        -> Compatible billing pools
        -> Financial calculation
        -> Resource and service aggregation
        -> Infrastructure estimate
        -> Optional historical persistence

The estimation engine consumes existing infrastructure and pricing
contracts without duplicating their responsibilities.

The financial and estimation components remain independent of the
Streamlit user interface.

## 4. Resource Billing Models

| Resource | Modeled billing components |
|---|---|
| EC2 | Instance running hours |
| EBS | Prorated storage and applicable performance charges |
| S3 | Storage, requests, transfer and applicable retrieval |
| Lambda | Requests, execution duration and additional ephemeral storage |
| DynamoDB | Request units or provisioned capacity-hours, and storage |
| RDS | Instance runtime, storage and applicable performance components |

Resource quantities are applied once during billing-component mapping.

Unsupported components remain visible rather than being silently
removed from the estimation.

Resource configuration support does not establish pricing coverage.

## 5. Financial Conventions

- All monetary values use Decimal arithmetic and USD.
- An average billing month contains 730 hours.
- An average day contains 24 hours.
- Annual expenditure equals modeled monthly expenditure times 12.
- Average hourly expenditure equals monthly expenditure divided by 730.
- Daily expenditure equals monthly expenditure times 24 divided by 730.
- Applicable compute-hour rates are distinguished from average
  infrastructure expenditure per hour.
- Currency rounding uses ROUND_HALF_UP for presentation.
- Chart values are converted to float for visualization only.
- CSV financial values retain calculation precision.

Annual projections assume unchanged rates and monthly consumption.

The module does not claim calendar-specific AWS invoice accuracy.

## 6. Graduated Pricing and Billing Pools

Pricing tiers use inclusive lower bounds and exclusive upper bounds.

Compatible resource groups resolving to the same pricing offer within
the modeled regional billing scope are pooled before calculation.

The model assumes one hypothetical billing account.

Known charges and priced usage are allocated proportionally across
pool members, preserving the aggregate.

Verified storage example:

| Storage coverage | Value |
|---|---:|
| Combined requested storage | 60,000 GB |
| Available priced storage | 51,200 GB |
| Unpriced storage | 8,800 GB |
| Known monthly subtotal | USD 1,177.60 |
| Complete monthly cost | Unavailable |

The model does not reproduce every AWS consolidated billing rule
or cross-region discount arrangement.

Unknown consumption remains unresolved and is excluded from
quantified billing pools.

Known subtotals are not guaranteed lower bounds under every
possible pricing arrangement.

## 7. Pricing Policies

### Floci only

Uses applicable rates supplied through the Floci Pricing API.

Missing, unsupported or ambiguous pricing remains unresolved.

### Floci plus supplementary reference pricing

Allows verified local reference rates when permitted by the
existing Module 1 pricing resolver.

This does not permit arbitrary fallback after an API failure
or ambiguous pricing response.

Pricing evidence retains source references, rate dimensions,
retrieval or verification timestamps and relevant diagnostics.

Floci catalogue prices are emulator data, not live AWS quotations.

## 8. Cost Coverage

| Component status | Meaning |
|---|---|
| PRICED | Positive usage fully covered |
| ZERO_USAGE | Calculated billable usage is explicitly zero |
| PARTIAL | Only part of usage is covered |
| UNRESOLVED | Usage or applicable pricing cannot be established |
| EXCLUDED | Component outside the modeled scope |
| NOT_APPLICABLE | Component does not apply |

Infrastructure, resource and service summaries distinguish COMPLETE,
PARTIAL and UNAVAILABLE results.

Complete modeled totals are not returned when required modeled
billing components remain unresolved or partially covered.

A complete modeled estimate does not establish complete AWS
billing coverage.

## 9. Historical Estimation Persistence

Each saved estimate preserves:

- Original infrastructure scenario and revision.
- Estimate UUID and UTC evaluation timestamp.
- Calculation model version.
- Selected pricing policy.
- Component billing quantities and financial results.
- Pricing pool allocations.
- Financial summaries.
- Assumptions and exclusions.
- Associated pricing snapshot and SHA256 checksum.

Runtime storage:

    .finops-runtime/estimates/<estimate-id>.json
    .finops-runtime/snapshots/<estimate-id>.json

EstimateRepository provides:

- save(estimate)
- load(estimate_id)
- list_estimates(scenario_id=None)

Historical estimates are reopened without retrieving current prices.

The original scenario is embedded in each estimate, allowing
historical analysis after the current scenario changes or is deleted.

Documents are immutable through the repository interface.

Each document uses atomic file replacement. The estimate document
is published after its associated pricing snapshot.

A failed second write may leave an orphaned snapshot, but it does
not publish an incomplete estimate.

The implementation is intended for local, single-process use.
The snapshot checksum detects changes but is not authentication.

The repository reuses the existing M3 scenario serialization
helpers and depends on that serialization contract.

Runtime data is excluded from Git.

## 10. User Interface

The Cost Estimator provides:

- Saved scenario selection.
- Explicit pricing policy selection.
- Optional pricing catalogue refresh.
- Estimate generation.
- Financial overview and billing coverage.
- Resource and service cost tables.
- Monthly known-charge distribution charts.
- Billing-component status filters.
- Pricing evidence and diagnostics.
- CSV export containing all billing components.
- Explicit historical estimate saving.
- Saved estimate browsing.

Generation and saving are separate actions.

A generated estimate remains associated with its original
scenario revision and pricing policy.

Changes to the current scenario or selected policy are identified
before the user generates another estimate.

## 11. Running the Cost Estimator

From the repository root, start Floci:

    docker compose up -d

Launch Streamlit:

    & ".\.venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501

Open http://127.0.0.1:8501.

Navigate to Infrastructure Builder and create a scenario using the
example documented in M3_INFRASTRUCTURE_BUILDER.md.

Navigate to Cost Estimator, select the scenario and pricing policy,
then generate an estimate.

Select Save historical estimate to preserve the result.

Use Saved estimates to reopen previous results.

The runtime estimate and snapshot directories are automatically
created when an estimate is successfully saved.

## 12. Verified Demonstration Scenario

Scenario: E-commerce Production.

Configuration details are documented in M3_INFRASTRUCTURE_BUILDER.md.

| Resource | Quantity | Reference-enabled monthly cost |
|---|---:|---:|
| EC2 t3.micro | 3 | USD 22.78 |
| EBS gp3 | 3 | USD 24.00 |
| S3 Standard | 1 | USD 11.50 |
| Lambda | 1 | USD 2.07 |
| DynamoDB | 1 | USD 2.78 |

Exact monthly total: USD 63.12392.

Exact annual total: USD 757.48704.

Totals are calculated before presentation rounding.

| Financial metric | Floci only | Floci plus references |
|---|---|---|
| Status | PARTIAL | COMPLETE |
| Known monthly subtotal | USD 34.68 | USD 63.12 |
| Complete monthly cost | Unavailable | USD 63.12 |
| Complete annual cost | Unavailable | USD 757.49 |
| Resolved components | 9 | 14 |
| Unresolved components | 5 | 0 |

Reference-enabled estimate:

- Average hourly expenditure: USD 0.09.
- Average daily expenditure: USD 2.08.
- Floci-priced positive-usage components: 3.
- Reference-priced positive-usage components: 5.
- Zero-usage components: 6.

These results depend on the verified catalogue and reference
rates used during development.

Zero S3 request and transfer usage is an explicit hypothetical
assumption of this demonstration.

## 13. Verification

| Test area | Passing tests |
|---|---:|
| Financial calculations | 11 |
| Billing component mapping | 12 |
| Estimation engine | 11 |
| Historical persistence | 10 |
| Cost Estimator dashboard | 8 |
| Total M4 tests | 52 |
| Previous foundation, M1 and M3 tests | 289 |
| Complete regression suite | 341 |

Additional verification covered:

- Live Floci pricing integration.
- Supplementary reference pricing.
- Exact demonstration financial results.
- Compatible pricing tier pooling.
- Partial pricing coverage.
- Resource and service aggregation.
- Complete pricing evidence preservation.
- Historical estimate reopening without pricing calls.
- Snapshot checksum verification.
- Failed-write protection.
- Preservation of historical scenario revisions.
- Runtime storage exclusion from Git.

Manual browser acceptance was reported successful by the developer.

The M4.7-R1 checkpoint independently verified the locally saved
demonstration estimates through the repository interface:

- Two Floci-only partial estimates.
- One reference-enabled complete estimate.
- Three associated pricing snapshots.
- Original scenario revision preserved.
- Exact financial results verified.
- Historical reopening without pricing calls.

The publication checkpoint verifies these same saved documents
before committing the implementation.

Run the complete regression suite:

    & ".\.venv\Scripts\python.exe" -B -m unittest discover -s tests -p "test_*.py" -q

## 14. Limitations and Exclusions

- Pricing availability depends on the existing M1 catalogue and
  supplementary reference coverage.
- Some S3 request, retrieval and data transfer charges remain
  unsupported.
- RDS pricing and some provisioned-capacity rates remain unavailable.
- Taxes, credits, free-tier allowances and private discounts
  are excluded.
- Storage minimum-duration and object-size adjustments are not
  comprehensively modeled.
- Historical persistence is local and single-process.
- Runtime estimates and snapshots are not committed to Git.
- Future contract changes may require schema migrations.
- Charts visualize known charges, not complete unpriced consumption.
- Reserved Instances, Savings Plans and Spot alternatives belong
  to Module 5.

## 15. Next Development Stage

Module 5 will compare applicable purchasing and storage pricing
models while preserving equivalent resource usage, financial
scope and pricing provenance.

The estimation contracts provide the On-Demand baseline for
alternative pricing comparisons.
