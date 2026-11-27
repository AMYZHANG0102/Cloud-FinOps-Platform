# M3 - Cloud Infrastructure Configuration Builder

## 1. Purpose

Module 3 enables users to create and manage hypothetical cloud
infrastructure configurations for subsequent financial analysis.

It provides the infrastructure input required by:

- M4 - Cloud Infrastructure Cost Estimator.
- M5 - Cloud Pricing Model Comparison.

It also establishes reusable scenario contracts that may support
other project modules following team integration.

Module 3 does not provision actual cloud resources.

## 2. Assignment Requirements

| Requirement | Implementation |
|---|---|
| Select cloud services | Six supported resource types |
| Choose resource configurations | Dynamic configuration fields |
| Specify resource quantities | Positive integer resource quantities |
| Enter expected usage | Service-specific Decimal usage fields |
| Select a region | Predefined and custom AWS regions |
| Save infrastructure configurations | Persistent JSON scenario repository |
| Create multiple scenarios | Creation, selection and duplication |

The implementation covers the seven user capabilities specified
for Module 3 in the Cloud Economics term project.

## 3. Supported Resources

| Resource | Configuration and usage |
|---|---|
| EC2 | Instance type, operating system, tenancy and monthly running hours |
| EBS | Volume type, capacity, provisioned hours, IOPS and throughput |
| S3 | Storage class, average storage, requests, transfer and retrieval |
| Lambda | Architecture, invocations, memory, duration and ephemeral storage |
| DynamoDB | Table class, capacity mode, requests, capacity units and storage |
| RDS | Instance class, engine, Multi-AZ, storage and running hours |

Configuration support does not imply that matching prices exist
in Floci or the supplementary reference catalogue.

The resource specifications define the initial application scope.
They do not reproduce every AWS provisioning constraint.

## 4. Application Architecture

| File | Responsibility |
|---|---|
| finops/infrastructure/models.py | Immutable resource and scenario contracts |
| finops/infrastructure/validation.py | Configuration and usage validation |
| finops/infrastructure/repository.py | Persistent scenario management |
| pages/03_Infrastructure_Builder.py | Interactive Streamlit interface |

The infrastructure domain and persistence components are
independent of Streamlit.

The dashboard uses shared resource specifications to generate
configuration forms dynamically.

No pricing retrieval or expenditure calculations are duplicated
inside the Infrastructure Builder.

## 5. Scenario Data Contract

Scenario schema version: 1.

Each infrastructure scenario contains:

- Scenario UUID.
- Name and description.
- Revision number.
- Creation and update timestamps.
- Collection of resource configurations.

Each resource configuration contains:

- Resource UUID.
- Resource name and type.
- AWS region.
- Resource quantity.
- Configuration attributes.
- Expected usage per resource.
- Baseline pricing model.

AWS service codes are derived from resource types.

Usage values are represented using Decimal arithmetic.

Unknown usage is represented by None. An explicitly supplied
zero is preserved as zero and is not equivalent to missing usage.

## 6. Scenario Validation

Resource configurations are validated against their applicable
service specifications.

Validation distinguishes:

- Invalid configuration or usage.
- Valid but incomplete usage.
- Valid configuration with all specified usage supplied.

Empty infrastructure scenarios may be saved as drafts.

A complete usage specification does not guarantee complete
pricing availability or complete AWS billing coverage.

The baseline Infrastructure Builder uses On-Demand pricing.
Alternative purchasing models are evaluated in Module 5.

DynamoDB provisioned capacity is supported as a resource
configuration independently of the purchasing model.

## 7. Persistence and Scenario Management

Saved configurations are stored under:

    .finops-runtime/scenarios/

Each scenario is stored as:

    <scenario-uuid>.json

ScenarioRepository provides:

- create(scenario)
- load(scenario_id)
- list_scenarios()
- update(scenario)
- duplicate(scenario_id, name)
- delete(scenario_id, expected_revision=revision)

Creating a scenario establishes revision 1.

Updating an existing scenario preserves its identity and
increments its revision.

Outdated updates and deletion requests are rejected.

Duplicating a scenario creates a new scenario UUID, new
resource UUIDs and an independent revision history.

Deletion removes only the selected scenario document.

Atomic file replacement protects existing saved data against
failed writes. Process-local locking serializes repository
operations within the current application process.

Concurrent writes from independent processes are outside
the supported persistence scope.

Runtime scenario documents are excluded from Git.

## 8. Running the Infrastructure Builder

From the repository root:

    docker compose up -d

Launch the Streamlit application:

    & ".\.venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501

Open http://127.0.0.1:8501.

Select Infrastructure Builder in the application navigation.

Create or select a saved scenario, then add cloud resources
using the service-specific configuration forms.

The Infrastructure Builder itself does not require live pricing
retrieval to save hypothetical configurations.

## 9. Demonstration Scenario

The following configuration provides a reproducible baseline
for subsequent cost estimation.

Scenario: E-commerce Production.

All resources use us-east-1.

| Resource | Quantity | Configuration and usage per resource |
|---|---:|---|
| EC2 | 3 | t3.micro, Linux, Shared, 730 running hours |
| EBS | 3 | gp3, 100 GiB, 730 hours, 3000 IOPS, 125 MiB/s |
| S3 | 1 | Standard, 500 GB, zero requests and outbound transfer |
| Lambda | 1 | x86_64, 2 million invocations, 100 ms, 512 MB memory, 512 MB ephemeral storage |
| DynamoDB | 1 | Standard, on-demand capacity, 10 GB storage, 1 million RRU, 250,000 WRU |

Expected scenario overview:

- Resource groups: 5.
- Total resources: 9.
- Distinct AWS service codes: 4.
- Revision after initial creation and five additions: 6.
- Usage completeness: complete.

The demonstration scenario uses explicit hypothetical usage
assumptions. Zero S3 requests and transfer are selected to
isolate storage expenditure for the initial estimation example.

Runtime scenario files are not distributed through Git.
The configuration above allows the example to be recreated.

## 10. Financial Modelling Conventions

- 730 hours per average month.
- 24 hours per day.
- 12 months per year.
- All usage is specified per resource.
- Resource quantities must be applied exactly once.
- Unknown consumption must not be converted into zero.
- Valid but unpriced resources must remain distinguishable
  from invalid resources and zero-cost components.

M4 is responsible for applying pricing units, tier coverage,
resource quantities and applicable financial assumptions.

## 11. Verification

M3.4-R1 completed on November 27, 2026.

| Test area | Passing tests |
|---|---:|
| Infrastructure models | 12 |
| Configuration validation | 14 |
| Scenario repository | 12 |
| Infrastructure Builder | 7 |
| Total M3 tests | 45 |
| Previous foundation and M1 tests | 244 |
| Complete regression suite | 289 |

Additional verification covered:

- All six resource configuration forms.
- Multiple saved scenarios.
- Persistent scenario reopening.
- Resource editing and removal.
- Scenario duplication and deletion.
- Revision conflict protection.
- Invalid usage rejection.
- Decimal persistence and unknown usage preservation.
- Failed-write protection.
- Runtime Git exclusion.

The developer manually created the five-resource-group
demonstration scenario in the browser.

The displayed scenario overview matched the expected counts,
revision and usage completeness.

The M3.6 checkpoint additionally verifies the demonstration
scenario directly through the persistent repository.

Run the complete regression suite:

    & ".\.venv\Scripts\python.exe" -B -m unittest discover -s tests -p "test_*.py" -q

## 12. Known Limitations

- Scenario persistence is intended for local, single-process use.
- Unsaved input changes are discarded when users reload or switch
  scenarios without saving.
- Resource validation is not a complete AWS deployment validator.
- Complete usage does not establish complete pricing coverage.
- RDS and some other resource configurations lack verified rates.
- No real AWS resources are provisioned.
- Cost calculation and price comparisons remain separate modules.
- Final shared navigation and cross-module integration remain
  subject to team coordination.

## 13. Next Development Stage

Module 4 will retrieve saved infrastructure scenarios and resolve
applicable pricing through the Module 1 pricing foundation.

It will calculate hourly costs where applicable, daily costs,
monthly costs, annual costs and cost breakdowns.

Missing or partially covered pricing components will be
reported explicitly rather than treated as free resources.

Module 5 will subsequently compare applicable pricing models
using retrieved rates and documented assumptions.
