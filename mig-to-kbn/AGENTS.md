# AGENTS.md — Observability Migration Platform

## Project Overview

This repo is a **source-agnostic observability migration platform** that migrates
dashboards from **Grafana** and **Datadog** into **Kibana Lens YAML/NDJSON**. The
primary target is **Elastic Serverless**. The platform uses a shared adapter
architecture: source adapters handle extraction and query translation, shared
core owns canonical IRs and reporting, and the Kibana target adapter handles
emission, compilation, validation, and upload.

## Directory Layout

```
observability_migration/             Single Python package — all production code
  adapters/source/grafana/           Grafana source adapter (panels, promql, rules, etc.)
  adapters/source/datadog/           Datadog source adapter (models, translate, etc.)
  core/assets/                       Canonical IRs (QueryIR, VisualIR, OperationalIR, …)
  core/interfaces/                   Source/target adapter ABCs and registries
  core/reporting/                    MigrationResult, PanelResult, runtime summaries
  core/verification/                 Comparators, semantic gates
  targets/kibana/                    Compile, upload, display enrichment, ES|QL utils
  app/                               Unified CLI (obs-migrate)
tests/                               Test suites (unittest/pytest)
scripts/                             Lab lifecycle, dashboard analysis, data gen, validation
docs/                                Architecture, sources, targets, contributing guides
infra/                               docker-compose + configs for local Prometheus/Loki/Grafana/OTel
examples/                            Example rule pack, corpus profile, plugin stub
```

## Key Commands

```bash
# Install
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .

# Run Grafana migration (Elastic Serverless — always use --native-promql)
.venv/bin/python -m observability_migration.adapters.source.grafana.cli \
  --source files \
  --input-dir infra/grafana/dashboards \
  --output-dir migration_output \
  --native-promql \
  --data-view "metrics-*" \
  --esql-index "metrics-*"

# Run Datadog migration
.venv/bin/python -m observability_migration.adapters.source.datadog.cli \
  --source files \
  --input-dir infra/datadog/dashboards \
  --output-dir datadog_migration_output \
  --data-view "metrics-*"

# Run unified CLI
.venv/bin/obs-migrate migrate --source grafana --input-mode files --input-dir infra/grafana/dashboards --output-dir migration_output --native-promql --data-view "metrics-*" --esql-index "metrics-*"

# Run tests
.venv/bin/python -m pytest tests/ -x -q

# Send synthetic data to serverless cluster
set -a && source serverless_creds.env && set +a
DATA_HOURS=6 INTERVAL_SEC=30 BULK_WORKERS=4 BATCH_DOC_LIMIT=8000 \
  .venv/bin/python scripts/setup_serverless_data.py

# Pull live Grafana dashboards plus alert artifacts (no MCP, source-only)
KIBANA_URL= GRAFANA_URL=http://localhost:23000 GRAFANA_USER=admin GRAFANA_PASS=admin \
  .venv/bin/obs-migrate migrate --source grafana --input-mode api --output-dir migration_output \
  --native-promql --data-view "metrics-*" --esql-index "metrics-*" --fetch-alerts

# Pull live Datadog dashboards plus monitor artifacts (no MCP; monitor flags scope only monitor extraction)
.venv/bin/obs-migrate migrate --source datadog --input-mode api --env-file datadog_creds.env \
  --output-dir datadog_migration_output --field-profile otel --data-view "metrics-*" \
  --fetch-alerts --monitor-query "tag:team:platform"

# Compile generated YAML locally before any target exists
.venv/bin/obs-migrate compile --yaml-dir datadog_migration_output/yaml \
  --output-dir datadog_migration_output/compiled

# Upload compiled dashboards to Kibana
set -a && source serverless_creds.env && set +a
.venv/bin/obs-migrate upload --compiled-dir migration_output/compiled \
  --kibana-url "$KIBANA_ENDPOINT" --kibana-api-key "$KEY"

# Generate curated alert artifacts, then verify emitted alert rule payloads against Kibana
./.venv/bin/python scripts/generate_alert_support_report.py
set -a && source serverless_creds.env && set +a
.venv/bin/python scripts/verify_alert_rule_uploads.py \
  --kibana-url "$KIBANA_ENDPOINT" --api-key "$KEY" --keep-rules

# Audit migrated rules / dashboards in the target cluster
set -a && source serverless_creds.env && set +a
.venv/bin/python scripts/audit_migrated_rules.py
.venv/bin/obs-migrate cluster list-dashboards --kibana-url "$KIBANA_ENDPOINT" --kibana-api-key "$KEY"
```

## Dependencies

- Python >= 3.11
- Runtime: `promql-parser>=0.7.0` (required — Rust-backed PromQL AST parser), `pyyaml`, `requests`, `grafana-client>=5.0.0`
- Optional: `datadog-api-client` (for Datadog API extraction)
- Live Grafana extraction currently uses `requests` with `GRAFANA_URL`, `GRAFANA_USER`, and `GRAFANA_PASS`; it does not go through `grafana-client`.
- External: `uvx kb-dashboard-cli` (compile/upload), `uvx kb-dashboard-lint` (YAML linting) — both invoked via subprocess
- Install: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .`

## Architecture — Translation Pipeline

### Grafana path

Four translation paths per panel, chosen automatically.
**Always use `--native-promql`** for Elastic Serverless targets.

1. **Native PROMQL** (`--native-promql`, **preferred**): Wraps the original PromQL in
   `PROMQL index=... value=(expr)` — highest fidelity for `rate()`, `increase()`, etc.
2. **Rule-engine ES|QL**: Parses PromQL AST via `promql-parser`, classifies, translates
   through priority-ordered rules, renders ES|QL.
3. **LLM fallback ES|QL** (`--local-ai-endpoint` + `--local-ai-model`): For `not_feasible`
   panels, asks an LLM to translate. Structurally validated.
4. **Native ES|QL**: Passes through pre-existing Elasticsearch queries unchanged.

### Datadog path

Widget-level translation: metric queries → ES|QL via field map profiles, log queries
→ ES|QL WHERE / KQL via AST parser, formulas → inline ES|QL expressions.

### Module Responsibilities (Datadog adapter)

| Module | Role |
|--------|------|
| `cli.py` | Main orchestration: extract → translate → validate → compile → upload → smoke → report |
| `models.py` | `NormalizedWidget`, `NormalizedDashboard`, `DashboardResult`, `TranslationResult` |
| `translate.py` | Metric/log/formula → ES|QL translation with field-map profiles |
| `generate.py` | `generate_dashboard_yaml()` — YAML emission for all widget types |
| `display.py` | Datadog visual props → kb-dashboard YAML (legend, axis, colors) |
| `extract.py` | Dashboard extraction from files or Datadog API; credential loading |
| `preflight.py` | Field capability checks, ES|QL limits, Kibana version gates |
| `report.py` | Console reporting and JSON-detailed report for Datadog runs |
| `planner.py` | Widget → `PanelPlan` mapping (Kibana chart type, data shape) |
| `execution.py` | Live Datadog metric query execution for source-side verification |
| `verification.py` | Verification packets, semantic gates, source-vs-target comparison |
| `manifest.py` | `migration_manifest.json` generation |
| `rollout.py` | `rollout_plan.json` generation, review queue |

### Module Responsibilities (Grafana adapter)

| Module | Role |
|--------|------|
| `cli.py` | Main orchestration: extract → translate → lint → compile → upload → report |
| `panels.py` | Panel/variable/dashboard translation; native PROMQL builder; panel type dispatch |
| `translate.py` | Rule-based PromQL → ES|QL pipeline via `TranslationContext` |
| `promql.py` | PromQL AST parsing via `promql-parser`, fragment model, ES|QL planning |
| `llm_translate.py` | LLM-based fallback translator for not_feasible expressions |
| `rules.py` | `RuleRegistry` with `@register(name, priority)` decorator; rule pack loading |
| `schema.py` | Elasticsearch field_caps schema discovery; counter/gauge detection |
| `esql_validate.py` | ES|QL validation against `_query` API, auto-fixes |
| `extract.py` | Grafana dashboard extraction and normalization |
| `manifest.py` | Manifest I/O, datasource normalization, runtime summary |
| `verification.py` | Verification packets, semantic gates |
| `alerts.py` | Legacy Grafana alerts → migration tasks |
| `annotations.py` | Grafana annotations → Kibana guidance |
| `links.py` | Dashboard/panel links → Kibana equivalents |
| `transforms.py` | Grafana transformations → structured redesign tasks |

### Shared core

| Module | Role |
|--------|------|
| `core/assets/*.py` | Canonical IRs: `QueryIR`, `VisualIR`, `OperationalIR`, `DashboardIR`, etc. |
| `core/interfaces/` | `SourceAdapter` / `TargetAdapter` ABCs, adapter registries |
| `core/reporting/report.py` | `MigrationResult`, `PanelResult`, runtime summaries |
| `core/verification/comparators.py` | Source/target comparison logic |

### Kibana target

| Module | Role |
|--------|------|
| `targets/kibana/compile.py` | YAML lint via `kb-dashboard-lint`, compile/upload via `kb-dashboard-cli` |
| `targets/kibana/serverless.py` | Serverless-safe dashboard listing, data view CRUD, deletion workaround, Serverless detection |
| `targets/kibana/emit/display.py` | Grafana units/legend/axis → kb-dashboard YAML format |
| `targets/kibana/emit/esql_utils.py` | ES|QL shape extraction utilities |

### Rule Registries

Rules are registered via decorator and run in priority order:

```python
@QUERY_TRANSLATORS.register("my_rule", priority=500)
def my_rule(context):
    ...
```

Global registries (in execution order):
`QUERY_PREPROCESSORS` → `QUERY_CLASSIFIERS` → `QUERY_TRANSLATORS` →
`QUERY_POSTPROCESSORS` → `QUERY_VALIDATORS` → `PANEL_TRANSLATORS` →
`VARIABLE_TRANSLATORS`

## Testing

- Framework: `unittest` (also runnable via `pytest`)
- Test files: `tests/test_migrate.py` (main Grafana), `tests/test_datadog_migrate.py` (Datadog),
  `tests/test_datadog_test_plan.py` (Datadog extended), `tests/test_grafana_extended.py` (Grafana extended)
- Pattern: Builds mock panels, runs `translate_panel()`, asserts on YAML/result
- Run: `.venv/bin/python -m pytest tests/ -x -q`
- Default dataset in tests is `"prometheus"` (matching the data stream convention)

## Code Conventions

- Linting: `ruff` configured in `pyproject.toml`
- Type checking: `mypy` configured in `pyproject.toml`
- Commit messages: imperative mood, sentence case, concise
- Never commit `.env` files or credentials
- Prefer editing existing files over creating new ones
- Panel translation follows "degrade gracefully": if translation fails, emit a
  `markdown` placeholder with the original query and mark as `not_feasible`

## Known Limitations & Gotchas

### Native PROMQL path
- `_timeseries` column: Available only when the PromQL result has ungrouped series
  labels. Metric/gauge panels must not reference it (scalar results lack this column).
- `$variable` substitution: Template variables in PromQL are replaced with wildcards
  (`=~".*"`) or literal `1` for arithmetic — semantics may drift.
- Multi-target XY panels: Fall through to the rule-engine ES|QL path.

### Rule-engine ES|QL path
- Multi-target fusion: Only merges targets with compatible structure.
- `or` / `join` expressions: Approximated using left side only.
- `topk`, `histogram_quantile`, `scalar`, subqueries: Not supported, marked `not_feasible`.

### Display enrichment
- `enrich_yaml_panel_display()` must run on ALL translation paths.
- `legend.visible` must be a `LegendVisibleEnum` string (`"show"` / `"hide"` / `"auto"`) for
  all ESQL chart types (XY, Pie, Treemap, etc.), per `kb-dashboard-core` schema.

### Compile / upload
- `kb-dashboard-cli` is invoked via `uvx` subprocess — must be on PATH.
- Serverless Kibana disables `saved_objects/_find` API; use `_export`/`_import`.
- `serverless_creds.env` provides `ELASTICSEARCH_ENDPOINT`, `KIBANA_ENDPOINT`, `KEY`.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `ELASTICSEARCH_ENDPOINT` | Target ES cluster URL |
| `KIBANA_ENDPOINT` | Target Kibana URL |
| `KEY` | API key for ES/Kibana auth |
| `GRAFANA_URL` | Grafana API URL for live dashboard / alert extraction |
| `GRAFANA_USER` | Grafana basic-auth username for live extraction |
| `GRAFANA_PASS` | Grafana basic-auth password for live extraction |
| `GRAFANA_TOKEN` | Optional Grafana bearer token for alerting API access |
| `DD_API_KEY` | Datadog API key for live dashboard / monitor extraction |
| `DD_APP_KEY` | Datadog application key for live dashboard / monitor extraction |
| `DD_SITE` | Datadog site, e.g. `datadoghq.com` |
| `DATA_HOURS` | Hours of synthetic data to generate (default: 48, recommend 6 for quick tests) |
| `INTERVAL_SEC` | Interval between data points in seconds (default: 30) |
| `BULK_WORKERS` | Concurrent bulk ingest workers (default: 4) |
| `BATCH_DOC_LIMIT` | NDJSON lines per bulk request (default: 8000) |
| `SKIP_PREFLIGHT` | Set to `1` to bypass missing-metric / type-conflict gate |
| `MAX_BROKEN_PCT` | Max allowed % of broken panels before validation fails (default: 10) |

Example env files live at the repo root: `serverless_creds.env.example`, `datadog_creds.env.example`, `grafana_creds.env.example`.

## Sample Dashboards

**Grafana** (in `infra/grafana/dashboards/`):
- `node-exporter-full.json` — 132 panels
- `prometheus-all.json` — 44 panels
- `kube-state-metrics-v2.json` — 51 panels
- `k8s-views-global.json` — 30 panels
- `otel-collector-dashboard.json` — 15 panels
- `diverse-panels-test.json` — 11 panels

**Datadog** (in `infra/datadog/dashboards/`):
- `integrations/` — 30+ integration dashboards (nginx, redis, kafka, kubernetes, etc.)
- `account/` — 4 account dashboards
- `sample_dashboard.json` — test fixture
