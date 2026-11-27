# M1 - Cloud Service Pricing Explorer

## 1. Purpose

Module 1 provides interactive exploration of cloud service
pricing using the local Floci environment.

It establishes reusable pricing functionality for:

- M3 - Cloud Infrastructure Configuration Builder.
- M4 - Cloud Infrastructure Cost Estimator.
- M5 - Cloud Pricing Model Comparison.

The Pricing Explorer does not provision resources or calculate
complete infrastructure expenditure.

## 2. Assignment Requirements

| Requirement | Implementation |
|---|---|
| Connect Python to Floci | Local Boto3 client factory |
| Configure the Pricing client | finops/pricing/client.py |
| Retrieve selected service prices | Discovery and product retrieval |
| Select services and regions | Streamlit selection controls |
| Display available pricing | Tables, filters and comparable charts |
| Store retrieved information | Persistent local pricing cache |

The implementation covers the six Module 1 tasks specified
in the Cloud Economics term project.

Suggested service coverage remains subject to the pricing
operations supported by the installed Floci version.

## 3. Running the Application

From the repository root, with Docker running:

    docker compose up -d

Create the Python environment if required:

    python -m venv .venv
    & ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

Launch the Streamlit dashboard:

    & ".\.venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501

Open http://127.0.0.1:8501 and select Pricing Explorer.

The implementation uses the local Floci endpoint at
http://127.0.0.1:4566 with emulator-only credentials.

Production AWS credentials are not required.

## 4. Dashboard Views

### Floci Pricing Catalogue

- Discover supported pricing services.
- Select a service, region and available configuration attributes.
- Retrieve and refresh applicable pricing information.
- Display exact decimal prices and billing units.
- Display SKUs, source metadata and comparable EC2 hourly rates.
- Inspect raw product information.
- Export retrieved catalogue data as CSV.
- Reload saved pricing.
- Explicitly inspect expired catalogue entries.

### Supplementary Reference Pricing

- Display the documented local AWS reference dataset.
- Filter reference pricing by service and region.
- Inspect source URLs and verification dates.
- Inspect coverage limitations and assumptions.
- Export selected reference pricing data as CSV.

Reference rates are not Floci API results or live AWS quotations.

### EC2 Spot Pricing

- Select instance type, region and product description.
- Optionally restrict retrieval to an Availability Zone.
- Retrieve observations through the Floci EC2 API.
- Display latest returned observations by Availability Zone.
- Inspect observation and retrieval timestamps independently.
- Save observations in a persistent local cache.
- Export Spot observations as CSV.

Spot observations are simulated historical records.
They do not guarantee future pricing.

## 5. Verified Floci Pricing Coverage

Validation environment: Floci 2.5.0 community edition.

The following On-Demand catalogue rates were verified during
development on November 27, 2026.

| Service | Configuration | USD rate | Billing unit |
|---|---|---:|---|
| EC2 | t3.micro, Linux, Shared | 0.0104 | Hrs |
| EC2 | m5.large, Linux, Shared | 0.096 | Hrs |
| EC2 | c5.large, Linux, Shared | 0.085 | Hrs |
| S3 | Standard, first storage tier | 0.023 | GB-Mo |
| Lambda | Requests | 0.0000002 | Requests |

The above catalogue records belong to us-east-1.

Advertised configurations do not necessarily have corresponding
pricing products. Missing pricing must not be treated as zero.

### Supplementary Coverage

Eight documented reference rates are stored in:

data/pricing/reference_rates.json

They cover selected EBS gp3 storage and performance charges,
Lambda duration and additional ephemeral storage, and DynamoDB
Standard on-demand requests and storage.

Each entry retains its source, verification date, billing unit,
configuration and limitations.

### Spot Coverage

Live verification retrieved t3.micro and m5.large Linux/UNIX
observations for the following Availability Zones:

- us-east-1a
- us-east-1b
- us-east-1c

The tested c5.large query returned no observations.

Spot rates are not guaranteed to remain unchanged.

## 6. Reusable Pricing Interfaces

| File | Responsibility |
|---|---|
| models.py | Immutable pricing contracts and resolution outcomes |
| client.py | Local Floci client configuration |
| discovery.py | Service and attribute discovery |
| products.py | Paginated exact product retrieval |
| normalization.py | Decimal rates and billing dimensions |
| cache.py | Persistent pricing catalogue |
| reference.py | Validated reference catalogue |
| resolver.py | Component-specific pricing resolution |
| spot.py | EC2 Spot observations and persistence |

The pricing domain packages do not depend on Streamlit.

M4 should use PricingQuery and PricingResolver.resolve()
for applicable On-Demand cost components.

The resolver prefers exact Floci pricing. Supplementary
reference pricing requires explicit permission.

Unexpected API failures, invalid records and ambiguity
are not silently substituted with reference pricing.

For expenditure calculations, requested usage should be
provided explicitly so bounded pricing coverage can be
assessed correctly.

M5 can use SpotPricingService and SpotQuery to obtain
zone-specific Spot observations.

Reserved Instance and Savings Plans financial models
remain future M5 implementation work.

## 7. Persistence

Runtime pricing files are excluded from Git:

- .finops-runtime/pricing/catalogue_cache.json
- .finops-runtime/pricing/spot_cache.json

Default catalogue cache lifetime: 900 seconds.

Default Spot cache lifetime: 300 seconds.

Cache entries retain query identity and retrieval timestamps.

Expired entries are distinguished from fresh entries.
Successful empty results do not represent zero-priced resources.

Atomic file replacement and process-local locking protect
local persistence.

Concurrent multi-process writes are not guaranteed.

## 8. Verification

The M1.10B checkpoint completed on November 27, 2026.

- Complete automated regression suite: 244 passing tests.
- Original Pricing Explorer tests: 9 passing tests.
- Extended dashboard tests: 6 passing tests.
- Live catalogue, reference and Spot views: PASS.
- Live Spot persistence: PASS.
- Availability Zone filtering: PASS.
- Original catalogue view restoration: PASS.
- Browser functionality accepted through manual confirmation.

Run the complete regression suite:

    & ".\.venv\Scripts\python.exe" -B -m unittest discover -s tests -p "test_*.py" -q

CSV export controls are implemented.

Automated dashboard testing does not independently establish
downloaded file contents or visual browser appearance.

## 9. Known Limitations

- Floci pricing support is limited to its available catalogue.
- Reference pricing does not establish comprehensive AWS pricing.
- Reference rates may change and require periodic verification.
- The available S3 storage tier ends at 51,200 GB-Mo.
- Lambda duration reference coverage is deliberately bounded.
- RDS and additional storage pricing remain future work.
- Reserved Instance and Savings Plans rates are not verified
  live catalogue offers in the tested Floci environment.
- The Spot request window is seven days, aligned to millisecond
  precision for compatibility with observed Floci behavior.
- Floci may generate timestamps from request parameters.
- Returned Spot observations do not establish real market trends.
- A fresh Spot cache does not imply a recent underlying observation.
- Live catalogue discovery is required in a new catalogue session.
- Final shared navigation and cross-module integration remain
  subject to team coordination.

No unavailable pricing component should be presented as
zero cost or silently included in a complete infrastructure total.

## 10. Next Development Stage

M3 will allow users to define and persist hypothetical cloud
infrastructure scenarios without provisioning actual resources.

M4 will consume those scenarios and resolve applicable pricing
components using the shared pricing foundation.

M5 will compare applicable pricing models using retrieved
prices and clearly documented assumptions.
