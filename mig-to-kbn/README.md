# Observability Migration Platform

A source-agnostic platform that migrates observability dashboards from **Grafana** and **Datadog** into **Kibana Lens YAML/NDJSON** with production-oriented query translators.

Docs index: `docs/README.md`. Canonical command inventory: `docs/command-contract.md`. Full architecture: `docs/architecture.md`.

The installable distribution is `obs-migrate`, while the importable Python package is `observability_migration`. The main installed CLIs are `obs-migrate`, `grafana-migrate`, and `datadog-migrate`.

## Source Capability Matrix

| Capability | Grafana | Datadog |
|---|---|---|
| Dashboard extraction (files) | Mature | Mature |
| Dashboard extraction (API) | Mature (dashboard documents) | Supported (dashboard objects) |
| Panel / widget translation | Mature (40+ panel types) | Supported (15+ widget types) |
| Metric query translation | PromQL → native PROMQL or ES\|QL | DD metric query → ES\|QL |
| Log query translation | LogQL → ES\|QL | DD log search → ES\|QL / KQL |
| Variable / control migration | Mature | Supported (template variables -> Kibana controls) |
| Alert / monitor extraction | First-class extraction for legacy tasks + unified alerting; validated Kibana rule payloads for source-faithful rules | First-class monitor extraction; validated Kibana rule payloads for trusted monitor shapes |
| Annotation / event extraction | Candidate annotations (derived from dashboard JSON) | Preserved in normalization, not emitted |
| Link / drilldown translation | URL + dashboard drilldowns (derived from dashboard JSON) | Not yet first-class |
| Transformation redesign tasks | Full classification | Not modeled |
| Compile to NDJSON | Shared Kibana target | Shared Kibana target |
| Validation against ES | First-class source-aware validation | First-class emitted-query validation with `--validate --es-url` |
| Upload to Kibana | Supported | First-class `--upload` in Datadog migrate or via shared `obs-migrate upload` |
| Preflight | Mature | Supported (capability-aware with `--es-url`) |
| Smoke validation | Mature | First-class post-upload `--smoke` |
| Manifest / rollout plan | Mature | First-class run artifacts |
| Verification packets | Mature | First-class semantic gates with live Datadog metric source execution where configured |
| Unified `obs-migrate migrate` parity | High for the current forwarded Grafana migration surface (`--include` is not forwarded) | High for the current forwarded Datadog migration surface (`--include` is not forwarded) |

## Architecture

```
Source Adapters → Canonical Asset IR / Results → Verification → Kibana Emitter → Compile / Upload / Smoke
```

The platform follows a strict adapter boundary:
- **Source adapters** (`observability_migration/adapters/source/`) handle extraction, normalization, and query translation for each vendor.
- **Shared core** (`observability_migration/core/`) owns canonical asset contracts, interfaces, reporting, and verification helpers.
- **Kibana target runtime** (`observability_migration/targets/kibana/`) owns YAML emission plus the registered shared compile/upload/smoke target adapter. Emitted-query validation is still source-aware because it needs source-specific fixup and manualization logic.

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
```

Optional live-source extras:

```bash
# Required for Datadog live API extraction
.venv/bin/pip install -e ".[datadog]"
```

### CLI Entry Points

| Use case | Installed command | Module entry point |
|---|---|---|
| Unified CLI | `.venv/bin/obs-migrate` | `.venv/bin/python -m observability_migration` |
| Grafana migration | `.venv/bin/grafana-migrate` | `.venv/bin/python -m observability_migration.adapters.source.grafana.cli` |
| Datadog migration | `.venv/bin/datadog-migrate` | `.venv/bin/python -m observability_migration.adapters.source.datadog.cli` |
| Grafana smoke validation | `.venv/bin/grafana-validate-uploaded` | `.venv/bin/python -m observability_migration.adapters.source.grafana.validate_uploaded_dashboards` |
| Grafana corpus generation | `.venv/bin/grafana-generate-corpus` | `.venv/bin/python -m observability_migration.adapters.source.grafana.corpus` |

### Grafana → Kibana

```bash
# Basic translation
.venv/bin/grafana-migrate \
  --source files \
  --input-dir infra/grafana/dashboards \
  --output-dir migration_output

# Elastic Serverless with native PromQL
.venv/bin/grafana-migrate \
  --source files \
  --input-dir infra/grafana/dashboards \
  --output-dir migration_output \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --native-promql

# With validation against live Elasticsearch
.venv/bin/grafana-migrate \
  --source files \
  --input-dir infra/grafana/dashboards \
  --output-dir migration_output \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --native-promql \
  --es-url "$ES_URL" \
  --validate

# With upload, smoke validation, browser audit, and screenshots
.venv/bin/grafana-migrate \
  --source files \
  --input-dir infra/grafana/dashboards \
  --output-dir migration_output \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --es-url "$ES_URL" \
  --smoke \
  --browser-audit \
  --capture-screenshots \
  --kibana-url "$KIBANA_URL"

# Live extraction from Grafana API (set GRAFANA_URL, GRAFANA_USER, and GRAFANA_PASS first)
.venv/bin/grafana-migrate \
  --source api \
  --output-dir migration_output \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --native-promql
```

The dedicated Grafana CLI always lints and compiles generated YAML. Add `--upload` to send compiled dashboards to Kibana, or `--smoke` to auto-run upload plus post-upload validation against Kibana and Elasticsearch.
Grafana API mode pulls dashboard documents only. Links, annotations, transformations, and legacy alert tasks are derived from dashboard JSON during migration rather than fetched as separate first-class API assets. The current search request is capped at 500 dashboards.

### Datadog → Kibana

```bash
# With preflight and live query validation
.venv/bin/datadog-migrate \
  --source files \
  --input-dir infra/datadog/dashboards \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --data-view "metrics-*" \
  --es-url "$ELASTICSEARCH_ENDPOINT" \
  --preflight \
  --validate

# With NDJSON compilation
.venv/bin/datadog-migrate \
  --source files \
  --input-dir infra/datadog/dashboards \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --compile

# With upload, smoke validation, and browser audit
.venv/bin/datadog-migrate \
  --source files \
  --input-dir infra/datadog/dashboards \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --es-url "$ELASTICSEARCH_ENDPOINT" \
  --upload \
  --smoke \
  --browser-audit \
  --kibana-url "$KIBANA_URL"

# Live extraction from Datadog API
.venv/bin/datadog-migrate \
  --source api \
  --env-file datadog_creds.env \
  --dashboard-ids abc-def-123 \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --data-view "metrics-*"

# Small curated demo flows
bash scripts/run_datadog_demo.sh
bash scripts/run_datadog_demo.sh --target serverless
```

Datadog API mode can now extract both dashboard objects and monitors. Monitor extraction is first-class, and the current CLI emits/validates Kibana rule payloads for trusted, source-faithful monitor shapes instead of creating rules automatically.
Install the optional Datadog client extra before using API mode: `.venv/bin/pip install -e ".[datadog]"`.

`scripts/setup_datadog_serverless_data.py` is environment-driven. It defaults to `datadog_migration_output/integrations/yaml`, so set `DASHBOARD_YAML_DIR=/path/to/generated/yaml` first when your Datadog migration output lives somewhere else.

### Alert and Monitor Migration

Alert extraction is now first-class for both sources, but the current source CLIs stop at artifact generation plus Kibana payload validation:

- Grafana legacy alerts are extracted as migration tasks and reports. The current Grafana migration CLI does **not** auto-create Kibana rules.
- Grafana Unified Alerting rules can emit validated `.es-query` payloads only when the source query is preserved faithfully. Today that mainly means supported Prometheus rules through Kibana's native `PROMQL ...` path.
- Grafana Loki / LogQL alert rules are extracted and reported, but remain manual until a source-faithful alert translation path exists.
- Datadog monitors are extracted as first-class inputs. For simple metric/query alerts and simple count-based log alerts, the pipeline can emit Kibana rule payloads and verify that they upload disabled by default when the Datadog query parses cleanly and the configured field profile plus live target schema confirm every referenced field.

Examples:

- Supported emitted-payload example:
  Grafana Unified Prometheus rule
  `100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)`
  maps to a Kibana `.es-query` payload using a native `PROMQL ...` query plus the original threshold.
- Supported emitted-payload example:
  Datadog monitor
  `avg(last_5m):avg:system.cpu.user{env:production} by {host} > 90`
  can emit a Kibana `.es-query` payload when the selected field profile maps `system.cpu.user` and `host` to real target fields.
- Manual-only example:
  Datadog monitor
  `sum(last_15m):sum:pipelines.component_errors_total{...} by {component_type,...} > 0`
  is extracted and classified, but stays manual when the live target schema does not contain the translated metric and tag fields.
- Manual-only example:
  Grafana Unified Loki rule
  `count_over_time({job=~".+"} |= "error" [5m])`
  is extracted and classified, but is **not** auto-created today.

See `examples/alerting/README.md` for concrete sample source alerts and expected migration behavior.
For tested live pull commands and the alert upload / verification flow, see `docs/command-contract.md`.

### Unified CLI

The unified CLI dispatches to the appropriate source adapter:

```bash
# Grafana via unified CLI
.venv/bin/obs-migrate migrate \
  --source grafana \
  --input-mode files \
  --input-dir infra/grafana/dashboards \
  --output-dir migration_output \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --native-promql

# Grafana via unified CLI with integrated smoke/browser validation
.venv/bin/obs-migrate migrate \
  --source grafana \
  --input-mode files \
  --input-dir infra/grafana/dashboards \
  --output-dir migration_output \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --es-url "$ES_URL" \
  --smoke \
  --browser-audit \
  --capture-screenshots \
  --kibana-url "$KIBANA_URL"

# Datadog via unified CLI
.venv/bin/obs-migrate migrate \
  --source datadog \
  --input-mode files \
  --input-dir infra/datadog/dashboards \
  --output-dir datadog_migration_output \
  --data-view "metrics-*" \
  --field-profile otel \
  --es-url "$ELASTICSEARCH_ENDPOINT"

# Grafana live extraction via unified CLI
.venv/bin/obs-migrate migrate \
  --source grafana \
  --input-mode api \
  --output-dir migration_output \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --native-promql

# Datadog live extraction via unified CLI (set DD_API_KEY, DD_APP_KEY, and optional DD_SITE first, or keep them in datadog_creds.env; requires `.venv/bin/pip install -e ".[datadog]"`)
.venv/bin/obs-migrate migrate \
  --source datadog \
  --input-mode api \
  --env-file datadog_creds.env \
  --output-dir datadog_migration_output \
  --data-view "metrics-*" \
  --field-profile otel

# Inspect adapter extension points
.venv/bin/obs-migrate extensions --source grafana --format yaml
.venv/bin/obs-migrate extensions --source datadog --format json

# Write starter extension templates
.venv/bin/obs-migrate extensions --source grafana --format yaml --template-out custom-rule-pack.yaml
.venv/bin/obs-migrate extensions --source datadog --format yaml --template-out custom-field-profile.yaml
```

Unified `obs-migrate migrate` accepts `--include`, but Grafana and Datadog handlers do not currently use it as source-asset selection in either `files` or `api` mode. For Datadog API mode, unified does expose `--env-file`, but explicit dashboard scoping via `--dashboard-ids` remains a dedicated-CLI feature.

### Unified CLI Subcommands

```bash
# Compile generated YAML to NDJSON
.venv/bin/obs-migrate compile \
  --yaml-dir migration_output/yaml \
  --output-dir migration_output/compiled

# Upload compiled dashboards to Kibana
.venv/bin/obs-migrate upload \
  --compiled-dir migration_output/compiled \
  --kibana-url "$KIBANA_URL" \
  --kibana-api-key "$KEY"

# Cluster utilities (Kibana target)
.venv/bin/obs-migrate cluster list-dashboards --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY"
.venv/bin/obs-migrate cluster ensure-data-views --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY" --data-view-patterns "metrics-*,logs-*"
.venv/bin/obs-migrate cluster delete-dashboards --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY" --dashboard-ids "id1,id2"
.venv/bin/obs-migrate cluster detect-serverless --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY"
```

## Package Structure

```
observability_migration/     Unified platform package
  app/                       Unified CLI entry points
  adapters/source/
    grafana/                 Grafana extraction, translation, preflight, verification, smoke
    datadog/                 Datadog extraction, normalization, translation, field profiles
  core/
    assets/                  DashboardIR, PanelIR, QueryIR, VisualIR, OperationalIR, ...
    interfaces/              SourceAdapter / TargetAdapter ABCs, registries
    reporting/               Shared result dataclasses and run summaries
    verification/            Comparator helpers and verification contracts
  targets/kibana/            YAML emit helpers plus compile/upload runtime functions
scripts/                     Local demo, validation, and data-seeding helpers
tests/
  core/                      Shared contract and interface tests
  targets/kibana/            Shared target-runtime tests
  e2e/                       Cross-adapter parity coverage
  fixtures/                  Lightweight shared test fixtures
docs/                        Architecture, sources, targets, contributing
infra/                       Bundled dashboards and local lab assets
examples/                    Rule packs, Datadog field profile, corpus profile, plugin examples
```

## Testing

```bash
# Run all tests
.venv/bin/python -m pytest tests/ -x -q

# Run only shared core tests
.venv/bin/python -m pytest tests/core/ -x -q

# Run only Grafana adapter tests
.venv/bin/python -m pytest tests/test_migrate.py -x -q

# Run only Datadog adapter tests
.venv/bin/python -m pytest tests/test_datadog_migrate.py -x -q

# Run cross-source parity tests
.venv/bin/python -m pytest tests/e2e/ -x -q
```

## Documentation

| Document | Purpose |
|---|---|
| `docs/README.md` | Docs index and recommended reading paths |
| `docs/architecture.md` | Architecture overview, design principles, package layout, contributor reading order |
| `docs/architecture/asset-model.md` | Canonical asset contracts |
| `docs/architecture/tooling-matrix.md` | Where to use YAML, Pydantic, CUE, Hypothesis, and future parser tools |
| `docs/dashboards/README.md` | Dashboard schema, YAML lint, and layout-validation tooling |
| `docs/pipeline-trace.md` | Shared pipeline architecture overview + cross-source summary — regenerate with `python scripts/audit_pipeline.py --update-docs` |
| `docs/sources/grafana.md` | Grafana adapter capabilities and entry points |
| `docs/sources/grafana-trace.md` | Auto-generated Grafana per-dashboard translation traces |
| `docs/sources/datadog.md` | Datadog adapter capabilities and entry points |
| `docs/sources/datadog-trace.md` | Auto-generated Datadog per-dashboard translation traces |
| `docs/targets/kibana.md` | Shared Kibana target runtime |
| `docs/targets/kibana-esql-capabilities.md` | Kibana ES|QL capability snapshot and translation opportunities |
| `docs/targets/kibana-esql-upgrade-matrix.md` | Concrete ES|QL upgrade matrix for Grafana and Datadog translation work |
| `docs/local-otlp-validation.md` | Local OTLP validation lab setup |
| `docs/contributing/import-paths.md` | Canonical imports after package consolidation |
| `docs/contributing/add-source.md` | How to add a new source adapter |
| `docs/contributing/add-asset-type.md` | How to add a new asset type |
| `REMAINING-ROADMAP.md` | Current roadmap and highest-priority gaps |

## Contributing

### Adding a New Source

1. Create `observability_migration/adapters/source/<name>/adapter.py` implementing `SourceAdapter`.
2. Register it with `@source_registry.register`.
3. Import the adapter module in `observability_migration/app/cli.py` so `obs-migrate` discovers it.
4. Add extraction, normalization, and query translation modules under the adapter package.
5. Add focused fixtures under `tests/fixtures/` and reusable sample dashboards under `infra/<name>/dashboards/` when helpful.
6. Add tests under `tests/` and `tests/e2e/`.
7. Update docs at `docs/sources/<name>.md`.

### Adding a New Asset Type

1. Create a shared contract in `observability_migration/core/assets/<asset>.py`.
2. Add it to `core/assets/__init__.py`.
3. Update affected source adapters to extract and map the asset.
4. Update the target emitter if the asset produces output.
5. Add tests at each layer.

## Environment Variables

| Variable | Purpose |
|---|---|
| `GRAFANA_URL` | Grafana API URL (Grafana source, API mode) |
| `GRAFANA_USER` / `GRAFANA_PASS` | Grafana API credentials |
| `DD_API_KEY` / `DD_APP_KEY` | Datadog API credentials |
| `ELASTICSEARCH_ENDPOINT` or `ES_URL` | Elasticsearch cluster URL |
| `KIBANA_ENDPOINT` or `KIBANA_URL` | Kibana URL |
| `KEY` or `ES_API_KEY` | API key for ES/Kibana auth |

Example env files live at the repo root: `serverless_creds.env.example`, `datadog_creds.env.example`, and `grafana_creds.env.example`.

## Field Mapping

Both adapters must translate vendor-specific field names into the Elasticsearch
field names used by the target cluster. They use different mechanisms suited to
their source models, but the goal is the same: ensure emitted ES|QL queries
reference fields that actually exist in the target.

| Aspect | Grafana | Datadog |
|---|---|---|
| Mechanism | `SchemaResolver` + rule packs | `FieldMapProfile` (field profiles) |
| Metric names | Pass through (PromQL names or native PROMQL wrapping) | Explicit `metric_map` + dot-to-underscore + optional prefix/suffix |
| Tag / label names | Multi-level resolution: rule-pack overrides → live `_field_caps` → built-in Prometheus→OTel candidates → pass-through | `tag_map` dictionary with optional `tag_prefix` fallback |
| Built-in profiles | One default Prometheus→OTel candidate map | Four built-in profiles: `otel`, `prometheus`, `elastic_agent`, `passthrough` |
| Customization | `--rules-file` (declarative YAML rule pack) | `--field-profile path.yaml` (custom YAML profile) |
| Live field discovery | `--es-url` feeds `SchemaResolver._field_caps` | `--es-url` loads `_field_caps` into the profile |
| Starter templates | `obs-migrate extensions --source grafana --template-out ...` | `obs-migrate extensions --source datadog --template-out ...` |

See `docs/sources/grafana.md` → "Schema Resolution and Field Naming" and
`docs/sources/datadog.md` → "Field Profiles" for full details.

## Grafana-Specific Features

- **Native PromQL**: Use `--native-promql` to emit `PROMQL` source commands for compatible expressions.
- **Schema resolution**: `SchemaResolver` maps Prometheus labels to Elasticsearch fields using rule-pack overrides, live `_field_caps` discovery, and built-in Prometheus→OTel candidates.
- **Rule packs**: Declarative YAML for field rewrites, label candidates, panel overrides. Load with `--rules-file`.
- **Validated extension inputs**: Rule packs are schema-validated before load, and starter templates can be emitted with `obs-migrate extensions --source grafana --template-out ...`.
- **Plugins**: Python files with `register(api)`. Load with `--plugin`.
- **Preflight**: `--preflight` produces structured readiness reports with customer-facing action summaries.
- **Metadata polish**: `--polish-metadata` with optional `--local-ai-polish` for AI-assisted title/label improvement.
- **Review explanations**: `--review-explanations` with optional `--local-ai-explanations` for reviewer-facing summaries.

## Datadog-Specific Features

- **Field profiles**: Use `--field-profile otel|prometheus|elastic_agent|passthrough` for environment-specific field mapping, or start from `examples/datadog-field-profile.example.yaml`. See `docs/sources/datadog.md` for per-profile tag and metric mappings.
- **Validated field profiles**: Custom Datadog profiles are schema-validated before load, and `obs-migrate extensions --source datadog --template-out ...` can emit a starter file.
- **Dashboard controls**: Datadog `template_variables` now emit Kibana dashboard controls; query-level semantics still degrade honestly when there is no direct target equivalent.
- **Capability-aware preflight**: With `--es-url`, Datadog runs target `_field_caps` discovery and surfaces risky or blocked fields before translation/reporting.
- **Formula translation**: Datadog metric formulas translate to ES|QL arithmetic expressions.
- **Log search**: Datadog log search DSL translates to ES|QL WHERE clauses or KQL filters.

## Limits

- Missing source data in Elasticsearch will still cause validation failures regardless of translation quality.
- Grafana and Datadog now both provide first-class preflight/validate/upload/smoke flows, including optional browser audit and screenshot capture on the main migration paths. The main remaining Datadog gap is broader source execution coverage for logs and multi-query cases.
- Alert and monitor extraction is broader than dashboard extraction, but rule payload emission/validation is deliberately narrower: only source-faithful query paths are emitted on the main migration path.
- Semantic gaps between source query models and ES|QL/PROMQL require approximation or custom plugins. This project now prefers `manual_required` over emitting a misleading alert query.
- The platform makes these gaps explicit, traceable, and customizable instead of hiding them.
