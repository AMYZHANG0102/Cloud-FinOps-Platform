# Floci Pricing API Capability Investigation

## 1. Purpose

This document records the capabilities and limitations observed
during the investigation of the installed Floci environment for
the Cloud FinOps Platform.

The investigation supports the implementation of:

- M1 - Cloud Service Pricing Explorer
- M3 - Cloud Infrastructure Configuration Builder
- M4 - Cloud Infrastructure Cost Estimator
- M5 - Cloud Pricing Model Comparison

The findings may also support other platform modules requiring
consistent pricing information.

The document records observed behaviour rather than claiming
complete compatibility with the production AWS APIs.

## 2. Verified Environment

| Component | Verified value |
|---|---|
| Investigation date | 2026-11-27 |
| Floci version | 2.5.0 |
| Floci edition | Community |
| Docker image | floci/floci:latest |
| Container | finops-floci |
| Endpoint | http://localhost:4566 |
| Health endpoint | /_floci/health |
| Persistent volume | finops-floci-data |
| Python | 3.14.6 |
| Boto3 | 1.44.12 |
| Botocore | 1.44.12 |
| Streamlit | 1.67.0 |
| Signing region | us-east-1 |
| Currency | USD |
| Repository baseline | 5cc6f3c |

Verified image digest:

```text
sha256:a0fbf944d7f338cc0856f1ef83831ea749ff2be71956eb7a7fce08fc21458e19
```

The emulator was accessed using explicit local test credentials
and a localhost endpoint.

The image tag is mutable. The recorded digest identifies the
image used during this investigation but does not yet pin the
Docker Compose configuration.

## 3. Investigation Checkpoints

| Checkpoint | Purpose | Result |
|---|---|---|
| M0.5A | Pricing API operations and service discovery | Complete |
| M0.5B | Regional pricing, filters and pagination | Complete |
| M0.5C | Pricing models and billing dimensions | Complete |

### 3.1 API Response Results

| Checkpoint | Successful responses | API errors | Total probes |
|---|---:|---:|---:|
| M0.5A | 11 | 0 | 11 |
| M0.5B | 44 | 14 | 58 |
| M0.5C | 20 | 4 | 24 |
| Total | 75 | 18 | 93 |

An HTTP success response does not necessarily imply that usable
pricing information was returned.

The API errors represent observed service-code and operation
limitations. They must not be interpreted as successful data
retrieval.

## 4. Pricing API Operation Compatibility

| Operation | Observed result |
|---|---|
| DescribeServices | Successful service discovery |
| GetAttributeValues | Successful attribute discovery |
| GetProducts | Successful product and price retrieval |
| ListPriceLists | Successful for EC2, S3 and Lambda |
| GetPriceListFileUrl | Successful URL generation |

All five operations were exercised successfully in at least
one tested case.

ListPriceLists rejected ComputeSavingsPlans with
InvalidParameterException.

GetPriceListFileUrl returned URLs using the
pricing-snapshot.floci.local hostname.

The URLs were not dereferenced or downloaded. Their file
availability and contents remain unverified.

The EC2 bulk reference identifies catalogue version
20260401000000, whereas the EC2 records retrieved through
GetProducts identify version 20260101000000.

GetProducts is the proposed primary retrieval operation.

## 5. Observed On-Demand Pricing Catalogue

The complete observed GetProducts catalogue for the three
advertised services contains five usable pricing dimensions.

| Service | Configuration | Region | USD rate | Unit | Usage range |
|---|---|---|---:|---|---|
| AmazonEC2 | t3.micro | us-east-1 | 0.0104 | Hrs | 0-Inf |
| AmazonEC2 | m5.large | us-east-1 | 0.096 | Hrs | 0-Inf |
| AmazonEC2 | c5.large | us-east-1 | 0.085 | Hrs | 0-Inf |
| AmazonS3 | Standard | us-east-1 | 0.023 | GB-Mo | 0-51200 |
| AWSLambda | Requests | us-east-1 | 0.0000002 | Requests | 0-Inf |

All observed EC2 configurations use Linux and shared tenancy.

The observed catalogue version is 20260101000000.

The publication and effective dates of the retrieved records
are 2026-01-01T00:00:00Z.

These prices originate from the local emulator and must not
be described as independently verified live AWS market rates.

### 5.1 Product Identifiers

| Configuration | SKU |
|---|---|
| EC2 t3.micro | FLOCI-EC2-T3MICRO-USE1 |
| EC2 m5.large | FLOCI-EC2-M5LARGE-USE1 |
| EC2 c5.large | FLOCI-EC2-C5LARGE-USE1 |
| S3 Standard | FLOCI-S3-STANDARD-USE1 |
| Lambda requests | FLOCI-LAMBDA-REQ-USE1 |

## 6. Advertised Attributes Versus Pricing Records

Floci advertises more configurations through
GetAttributeValues than it currently returns through
GetProducts.

### 6.1 EC2 Instance Types

| Instance type | Advertised | Pricing record retrieved |
|---|---|---|
| t3.nano | Yes | No |
| t3.micro | Yes | Yes |
| t3.small | Yes | No |
| t3.medium | Yes | No |
| m5.large | Yes | Yes |
| m5.xlarge | Yes | No |
| c5.large | Yes | Yes |
| r5.large | Yes | No |

### 6.2 Regions

| Region | EC2 advertised | EC2 product retrieved |
|---|---|---|
| us-east-1 | Yes | Yes |
| us-east-2 | Yes | No |
| us-west-2 | Yes | No |
| eu-west-1 | Yes | No |
| eu-central-1 | Yes | No |

The retrieved S3 and Lambda products were also limited
to us-east-1.

### 6.3 Operating Systems and Tenancy

Linux, Windows, RHEL and SUSE were advertised.

Only Linux pricing records were retrieved.

Shared, Dedicated and Host tenancy were advertised.

Only Shared tenancy pricing records were retrieved.

The regionCode attribute was present in product records
and usable in GetProducts filters despite not being
advertised by DescribeServices.

Attribute discovery must not be treated as proof of
price availability.

## 7. Filtering and Pagination

The following tested behaviours were verified:

- Known EC2 instance filters returned matching products.
- A nonexistent EC2 instance returned an empty result.
- Combined instance, location, operating system and
  tenancy filters returned the expected product.
- Tested unavailable regions and configurations returned
  empty results.
- EC2 regionCode filtering returned matching results.
- EC2 pagination with MaxResults=1 returned all three SKUs.
- No missing, unexpected or duplicate EC2 SKUs were observed.
- S3 Standard and Lambda request filters returned
  matching products.

S3 and Lambda multi-page pagination was not exercised
because each catalogue contained only one product.

These results do not establish the behaviour of every
possible filter type, attribute or service configuration.

## 8. Alternative Pricing Models

### 8.1 Spot Pricing

The EC2 DescribeSpotPriceHistory operation returned six
price observations for Linux/UNIX configurations.

| Instance | Availability zone | USD/hour |
|---|---|---:|
| t3.micro | us-east-1a | 0.004400 |
| t3.micro | us-east-1b | 0.004532 |
| t3.micro | us-east-1c | 0.004664 |
| m5.large | us-east-1a | 0.012800 |
| m5.large | us-east-1b | 0.013184 |
| m5.large | us-east-1c | 0.013568 |

Observation timestamp:

2026-11-26T17:55:27.731Z

The query covered the preceding 24 hours.

No c5.large observations were returned in that query.

Spot prices must retain the relevant instance type,
availability zone, operating system and observation time.

A projected monthly or annual Spot cost must clearly
state that it assumes a selected observed price remains
constant over the projection period.

Spot pricing does not guarantee capacity or uninterrupted
execution.

### 8.2 Reserved Instances

DescribeReservedInstancesOfferings returned:

- HTTP 400
- UnsupportedOperation

No Reserved Instance offerings were retrieved.

Reserved pricing comparisons require separately documented
reference data or estimation assumptions.

### 8.3 Savings Plans

DescribeSavingsPlansOfferings and
DescribeSavingsPlansOfferingRates returned:

- HTTP 404
- UnknownOperationException

ComputeSavingsPlans was also rejected by ListPriceLists.

No Savings Plans offerings or rates were retrieved.

Savings Plans comparisons require separately documented
reference data or estimation assumptions.

### 8.4 Commitment-Based Cost Modelling

Future commitment-based comparisons should distinguish:

- Commitment duration.
- Applicable resource usage.
- Upfront payments, where applicable.
- Recurring commitment charges.
- Effective hourly rates.
- Utilization of the commitment.
- Charges for uncovered usage.

An assumed discount must not be described as an actual
Reserved Instance or Savings Plans offer.

## 9. Storage and Serverless Pricing Limitations

### 9.1 S3

Only S3 Standard storage pricing was retrieved.

The available dimension covers 0-51200 GB-months.

No additional pricing tier was retrieved.

The available rate must not be extrapolated beyond
its observed usage range without a documented assumption.

The following tested storage classes returned no products:

- Standard - Infrequent Access.
- One Zone - Infrequent Access.
- Glacier Flexible Retrieval.
- Glacier Deep Archive.

The API Request and Data Transfer product families also
returned no products.

Future storage comparisons must account for applicable
request, retrieval, transition and minimum storage
duration costs, or explicitly disclose their exclusion.

### 9.2 Lambda

The retrieved Lambda rate covers invocation requests.

No corresponding pricing products were retrieved for:

- AWS-Lambda-Duration.
- AWS-Lambda-Storage.

A request-only estimate is not a complete Lambda cost
estimate when execution duration or other applicable
charges are excluded.

## 10. Additional Service Pricing Limitations

| Service | Observed Pricing API result |
|---|---|
| EBS | No Storage products under AmazonEC2 |
| AmazonRDS | InvalidParameterException |
| AmazonDynamoDB | InvalidParameterException |
| AWSELB | InvalidParameterException |
| AmazonEFS | InvalidParameterException |
| AmazonAthena | InvalidParameterException |
| AWSBackup | InvalidParameterException |
| AmazonCloudWatch | InvalidParameterException |

The seven rejected service codes were tested through
DescribeServices and GetProducts.

A service being listed by the Floci health endpoint
does not establish the availability of corresponding
Pricing API records.

These findings describe the tested installation and
operations. They are not a universal statement about
all Floci versions.

## 11. Proposed Pricing Resolution Strategy

### 11.1 Floci-Retrieved Pricing

Use exact matching emulator pricing records as the
primary source.

On-Demand rates originate from the Pricing API.

Spot observations originate from the EC2 API.

Preserve the source operation and applicable product
or observation identifiers.

### 11.2 Supplementary Pricing

Where the emulator cannot provide a required price,
use appropriately documented reference data or
explicit estimation assumptions.

Reference prices and assumptions must be distinguishable
from each other and from Floci-retrieved pricing.

Supplementary records should include their source,
applicable configuration, region, currency, unit,
date and limitations.

Do not silently replace an API connection failure
with supplementary data.

### 11.3 Unavailable Pricing

If no applicable retrieved or supplementary rate exists,
report pricing as unavailable.

Do not substitute zero for an unknown price.

Where an infrastructure estimate is incomplete, display
the known subtotal and identify all missing cost components.

## 12. Proposed Financial Calculation Rules

- Use Decimal arithmetic for monetary calculations.
- Preserve the original pricing precision.
- Round monetary totals at the presentation boundary.
- Validate quantities and usage as finite and nonnegative.
- Match prices to the requested resource configuration.
- Preserve billing units and currency.
- Respect pricing ranges and tier boundaries.
- Preserve source attribution and effective dates.
- Document billing-period assumptions.
- Distinguish genuine zero prices from missing prices.
- Disclose excluded charges and incomplete estimates.
- Compare pricing models using equivalent workload usage.
- Distinguish cost estimates from actual billing records.

A 730-hour average month may be offered as a configurable
estimation convention. Actual usage may differ.

## 13. Module Implementation Implications

### M1 - Cloud Service Pricing Explorer

- Retrieve pricing using the local Floci Pricing API.
- Discover services and their advertised attributes.
- Display actual retrieved pricing records.
- Support service and region selection.
- Handle empty, unavailable and failed API responses.
- Store retrieved information for further analysis.

### M3 - Cloud Infrastructure Configuration Builder

- Configure hypothetical infrastructure resources.
- Support service-specific configurations and usage inputs.
- Allow multiple saved infrastructure scenarios.
- Distinguish configurable resources from priced resources.
- Provide validated scenario data to M4.

### M4 - Cloud Infrastructure Cost Estimator

- Consume infrastructure configurations from M3.
- Resolve applicable prices using the shared pricing layer.
- Calculate hourly costs where applicable.
- Calculate daily, monthly and annual estimates.
- Present resource-level and service-level breakdowns.
- Identify supplementary and unavailable cost components.
- Avoid presenting incomplete subtotals as complete totals.

### M5 - Cloud Pricing Model Comparison

- Compare applicable pricing models.
- Retrieve On-Demand and available Spot prices.
- Support documented commitment-based assumptions.
- Evaluate applicable storage pricing tiers.
- Calculate potential costs and savings.
- Explain financial assumptions and workload limitations.

## 14. Shared Integration Considerations

A shared pricing component is proposed to avoid
inconsistent price definitions across modules.

Potential consumers include the workload simulator,
cost optimizer, resource utilization, scaling and
storage optimization modules.

The common contract should preserve price provenance,
billing units, configuration identity and availability
status.

The final interface and repository organization require
coordination during the architecture checkpoint.

## 15. Remaining Environment Considerations

- The Docker image uses a mutable latest tag.
- Port 4566 is published on all host interfaces.
- The Docker socket is not mounted.
- Docker-backed service operations may be limited.
- The existing startup helper accepts HTTP responses
  below 500 and may report incorrect readiness.
- Persistent storage configuration and mounting were
  verified, but restart durability was not tested.
- Bulk pricing file contents remain unverified.
- Other team modules require their own API investigations.

These considerations are recorded without modifying the
existing shared Docker Compose configuration.

## 16. Investigation Outcome

The installed Floci environment provides a usable
foundation for the Pricing Explorer, Infrastructure
Builder, Cost Estimator and Pricing Comparison modules.

The tested Pricing API operations and EC2 Spot price
history can provide directly retrieved pricing data.

The limited catalogue requires transparent supplementary
pricing and missing-price handling to support the broader
project scenarios.

The investigation is complete.

Application implementation, supplementary pricing
datasets, architecture contracts and automated regression
tests remain subsequent development work.
