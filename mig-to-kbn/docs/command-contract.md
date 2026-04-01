# Command Contract

This is the canonical command inventory for the repo.

Use this file as the source of truth for:
- supported commands
- required environment variables
- safe example invocations

## Environment Baseline

| Variable | Required for | Notes |
|---|---|---|
| `ELASTICSEARCH_ENDPOINT` or `ES_URL` | live validate, upload smoke, data scripts | Elasticsearch URL |
| `KIBANA_ENDPOINT` or `KIBANA_URL` | upload, cluster commands, smoke | Kibana URL |
| `KEY` or `ES_API_KEY` | authenticated ES/Kibana operations | API key |
| `DD_API_KEY` / `DD_APP_KEY` | Datadog API extraction / verification | can also load via `--env-file` |

## Install And Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
```

Datadog live API extraction (`--source api` on the dedicated CLI or Datadog
`--input-mode api` through `obs-migrate migrate`) also requires the optional
Datadog client extra:

```bash
.venv/bin/pip install -e ".[datadog]"
```

## Unified CLI (`obs-migrate`)

### Migrate

**Key flags**

| Flag | Role |
|------|------|
| `--input-mode {files,api}` | `files` reads exports under `--input-dir`; `api` runs live dashboard extraction for Grafana and Datadog. |
| `--include` | Accepted by `obs-migrate migrate`, but **not** forwarded into the Grafana or Datadog migration pipelines today. It does **not** act as a source-asset selector for those sources in either `files` or `api` mode; use dedicated CLIs or source-specific options such as Datadog's dedicated `--dashboard-ids` when you need explicit source scoping. |
| `--smoke`, `--browser-audit`, `--capture-screenshots` | Post-upload validation options; forwarded to the Grafana and Datadog CLIs when any smoke-related path is used. |

```bash
# Grafana (files)
.venv/bin/obs-migrate migrate \
  --source grafana \
  --input-mode files \
  --input-dir infra/grafana/dashboards \
  --output-dir migration_output \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --native-promql

# Datadog (files)
.venv/bin/obs-migrate migrate \
  --source datadog \
  --input-mode files \
  --input-dir infra/datadog/dashboards \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --data-view "metrics-*" \
  --es-url "$ELASTICSEARCH_ENDPOINT"
```

**Live extraction (`--input-mode api`)**

Grafana API mode expects Grafana HTTP basic auth via environment variables: `GRAFANA_URL`, `GRAFANA_USER`, and `GRAFANA_PASS` (defaults exist for local labs). For the full environment-driven setup and entry points, see [Grafana source adapter](sources/grafana.md).

```bash
.venv/bin/obs-migrate migrate \
  --source grafana \
  --input-mode api \
  --output-dir migration_output \
  --native-promql \
  --data-view "metrics-*" \
  --esql-index "metrics-*"
```

Unified `obs-migrate migrate` does not expose Datadog’s `--env-file` or `--dashboard-ids`, but the delegated Datadog CLI still uses its default credential loading (`DD_API_KEY`, `DD_APP_KEY`, optional `DD_SITE`, or `datadog_creds.env` in the working directory). Datadog API mode also requires the optional `datadog-api-client` dependency (`.venv/bin/pip install -e ".[datadog]"`). With no ID list, the Datadog extractor uses the dashboard list returned by the Datadog API.

```bash
set -a && source datadog_creds.env && set +a
.venv/bin/obs-migrate migrate \
  --source datadog \
  --input-mode api \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --data-view "metrics-*" \
  --es-url "$ELASTICSEARCH_ENDPOINT"
```

#### Supported live source scope

- **Grafana (`input-mode api`)** — Pulls dashboard documents from the Grafana API. Links, annotations, transforms, and legacy alert tasks are derived from that dashboard JSON during migration; they are not fetched as separate first-class API assets.
- **Datadog (`input-mode api`)** — Pulls dashboard objects from the Datadog API, and the dedicated Datadog CLI can also pull monitors when `--fetch-monitors` is used. Monitor auto-creation remains limited to source-faithful shapes that pass field-profile and live `_field_caps` checks.

### Compile / Upload

```bash
.venv/bin/obs-migrate compile \
  --yaml-dir migration_output/yaml \
  --output-dir migration_output/compiled

.venv/bin/obs-migrate upload \
  --compiled-dir migration_output/compiled \
  --kibana-url "$KIBANA_URL"
```

### Cluster

```bash
.venv/bin/obs-migrate cluster list-dashboards --kibana-url "$KIBANA_URL"
.venv/bin/obs-migrate cluster ensure-data-views --kibana-url "$KIBANA_URL" --data-view-patterns "metrics-*,logs-*"
.venv/bin/obs-migrate cluster delete-dashboards --kibana-url "$KIBANA_URL" --dashboard-ids "id1,id2"
.venv/bin/obs-migrate cluster detect-serverless --kibana-url "$KIBANA_URL"
```

### Extensions

```bash
.venv/bin/obs-migrate extensions --source grafana --format yaml
.venv/bin/obs-migrate extensions --source datadog --format json
.venv/bin/obs-migrate extensions --source grafana --format yaml --template-out custom-rule-pack.yaml
.venv/bin/obs-migrate extensions --source datadog --format yaml --template-out custom-field-profile.yaml
```

## Dedicated Source CLIs

Dedicated entry points (`grafana-migrate`, `datadog-migrate`) are thin wrappers around `python -m observability_migration.adapters.source.grafana.cli` and `python -m observability_migration.adapters.source.datadog.cli`.

### Grafana

**Inventory (representative)** — `--source {api,files}`; when using `--upload` and integrated smoke: `--smoke`, `--browser-audit`, `--capture-screenshots`, `--smoke-output`, `--smoke-timeout`, `--time-from`, `--time-to`, `--chrome-binary`; `--smoke-report` for merging a pre-generated smoke report.

```bash
# Files
.venv/bin/grafana-migrate \
  --source files \
  --input-dir infra/grafana/dashboards \
  --output-dir migration_output \
  --native-promql \
  --data-view "metrics-*" \
  --esql-index "metrics-*"

# Live Grafana API (set GRAFANA_URL, GRAFANA_USER, GRAFANA_PASS; see [Grafana source adapter](sources/grafana.md))
.venv/bin/python -m observability_migration.adapters.source.grafana.cli \
  --source api \
  --output-dir migration_output \
  --native-promql \
  --data-view "metrics-*" \
  --esql-index "metrics-*"

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
```

### Datadog

**Inventory (representative)** — `--source {files,api}`; API mode: `--env-file`, `--dashboard-ids` (comma-separated); post-upload: `--smoke`, `--browser-audit`, `--capture-screenshots`, `--smoke-output`, `--smoke-timeout`.

```bash
# Files
.venv/bin/datadog-migrate \
  --source files \
  --input-dir infra/datadog/dashboards \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --data-view "metrics-*"

# Live Datadog API
.venv/bin/python -m observability_migration.adapters.source.datadog.cli \
  --source api \
  --env-file datadog_creds.env \
  --dashboard-ids abc-def-123 \
  --output-dir datadog_migration_output \
  --data-view "metrics-*"
```

Same scope as [Supported live source scope](#supported-live-source-scope) under unified migrate: Grafana dashboards via API (related artifacts from dashboard JSON only); Datadog dashboards via API, with monitor extraction available through the dedicated Datadog CLI and safe auto-create limited to validated monitor shapes.

## Validation / Verification CLIs

```bash
.venv/bin/grafana-validate-uploaded \
  --kibana-url "$KIBANA_URL" \
  --es-url "$ES_URL" \
  --output upload_smoke_report.json

.venv/bin/grafana-generate-corpus --help
```

## Script Commands

### Local Lab Lifecycle

```bash
bash scripts/start_local_lab.sh
bash scripts/start_local_lab.sh --with-alloy --recreate
bash scripts/stop_local_lab.sh
bash scripts/stop_local_lab.sh --volumes
```

### Local Validation Flows

```bash
bash scripts/full_local_demo.sh --sample-set bundled
bash scripts/full_local_demo.sh --sample-set bundled --recreate-lab
bash scripts/full_local_demo.sh
```

### Datadog Demo Flows

Default mode uses the curated four-dashboard smoke subset. Browser extras are opt-in.

```bash
bash scripts/run_datadog_demo.sh
bash scripts/run_datadog_demo.sh --browser-audit --capture-screenshots
bash scripts/run_datadog_demo.sh --target serverless
```

### Migration Helpers

```bash
bash scripts/run_migration.sh
bash scripts/run_migration.sh --skip-data
bash scripts/run_migration.sh --skip-upload
```

### Schema / Lint / Layout

```bash
bash scripts/generate_dashboard_schema.sh
bash scripts/validate_dashboard_yaml.sh migration_output/yaml
.venv/bin/python scripts/validate_dashboard_layout.py migration_output/compiled
```

### Data Setup

```bash
set -a && source serverless_creds.env && set +a
.venv/bin/python scripts/setup_serverless_data.py

set -a && source serverless_creds.env && set +a
.venv/bin/python scripts/setup_datadog_serverless_data.py
```

### Pipeline Trace Regeneration

```bash
.venv/bin/python scripts/audit_pipeline.py --update-docs
```

## Test Commands

```bash
.venv/bin/python -m pytest tests/ -x -q
.venv/bin/python -m pytest tests/core/ -x -q
.venv/bin/python -m pytest tests/test_migrate.py -x -q
.venv/bin/python -m pytest tests/test_datadog_migrate.py -x -q
.venv/bin/python -m pytest tests/e2e/ -x -q
```
