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

Example env files are available at the repo root: `serverless_creds.env.example`, `datadog_creds.env.example`, and `grafana_creds.env.example`.

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

## Before Elastic / Kibana

You can use the migration tooling productively before configuring a target cluster.

- Translate exported dashboards into YAML.
- Pull live dashboards from Grafana or Datadog APIs.
- Pull Grafana alert artifacts or Datadog monitor artifacts.
- Review `migration_report.json`, `migration_manifest.json`, `verification_packets.json`, and `rollout_plan.json`.
- Compile generated YAML to NDJSON locally.

Add `--es-url` when you want live target field discovery or emitted-query validation. Add `--kibana-url` when you want upload, target dashboard listing/deletion, smoke validation, or alert-rule payload checks against a real Kibana target.

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

Unified `obs-migrate migrate` exposes Datadog’s `--env-file`, but not `--dashboard-ids`. Datadog API mode still requires the optional `datadog-api-client` dependency (`.venv/bin/pip install -e ".[datadog]"`). With no ID list, the Datadog extractor uses the dashboard list returned by the Datadog API.

```bash
.venv/bin/obs-migrate migrate \
  --source datadog \
  --input-mode api \
  --env-file datadog_creds.env \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --data-view "metrics-*" \
  --es-url "$ELASTICSEARCH_ENDPOINT"
```

**Source-only / offline evaluation**

These runs intentionally omit target-aware flags such as `--es-url`, `--validate`, `--upload`, and `--smoke`. If your shell already exports Elastic/Kibana variables from another workflow, unset them first for a pure source-only run.

```bash
# Grafana files: translate, lint, compile, and report without Elastic
.venv/bin/obs-migrate migrate \
  --source grafana \
  --input-mode files \
  --input-dir infra/grafana/dashboards \
  --output-dir migration_output \
  --native-promql \
  --data-view "metrics-*" \
  --esql-index "metrics-*"

# Datadog files: translate and report without Elastic
.venv/bin/obs-migrate migrate \
  --source datadog \
  --input-mode files \
  --input-dir infra/datadog/dashboards \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --data-view "metrics-*"

# Grafana live API plus alert artifacts, source-only
KIBANA_URL= GRAFANA_URL=http://localhost:23000 GRAFANA_USER=admin GRAFANA_PASS=admin \
.venv/bin/obs-migrate migrate \
  --source grafana \
  --input-mode api \
  --output-dir migration_output \
  --native-promql \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --fetch-alerts

# Datadog live API plus scoped monitor artifacts, source-only
.venv/bin/obs-migrate migrate \
  --source datadog \
  --input-mode api \
  --env-file datadog_creds.env \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --data-view "metrics-*" \
  --fetch-alerts \
  --monitor-ids 12345678
```

Grafana source-only runs still lint and compile generated YAML, and `--fetch-alerts` writes artifacts such as `alert_migration_results.json` and `alert_comparison_results.json`. Datadog source-only runs stay in offline field-capabilities mode and still write YAML plus the standard report artifacts; unified `--fetch-alerts` forwards to monitor extraction and writes `monitor_migration_results.json`, `monitor_comparison_results.json`, and `monitor_verification_results.json`. Unified Datadog API mode does not expose `--dashboard-ids`, so dashboard pulling still uses the dashboard list returned by the Datadog API; `--monitor-ids` and `--monitor-query` only scope monitor extraction.

#### Supported live source scope

- **Grafana (`input-mode api`)** — Pulls dashboard documents from the Grafana API. Links, annotations, transforms, and legacy alert tasks are derived from that dashboard JSON during migration; they are not fetched as separate first-class API assets.
- **Datadog (`input-mode api`)** — Pulls dashboard objects from the Datadog API, and either CLI can also pull monitors when the dedicated `--fetch-monitors` or unified `--fetch-alerts` path is used. The current migration commands emit and validate rule payloads for a narrow source-faithful subset; they do not auto-create Kibana rules on the main path.

### Compile / Upload

```bash
.venv/bin/obs-migrate compile \
  --yaml-dir migration_output/yaml \
  --output-dir migration_output/compiled

.venv/bin/obs-migrate upload \
  --compiled-dir migration_output/compiled \
  --kibana-url "$KIBANA_URL" \
  --kibana-api-key "$KEY"
```

`obs-migrate compile` is a local step and does not require Elasticsearch or Kibana. It can still exit nonzero after writing NDJSON if the YAML lint or compiled-layout checks return nonzero, so inspect both the exit status and the generated output directory.

### Cluster

```bash
.venv/bin/obs-migrate cluster list-dashboards --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY"
.venv/bin/obs-migrate cluster ensure-data-views --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY" --data-view-patterns "metrics-*,logs-*"
.venv/bin/obs-migrate cluster delete-dashboards --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY" --dashboard-ids "id1,id2"
.venv/bin/obs-migrate cluster detect-serverless --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY"
```

On Serverless, `delete-dashboards` clears saved objects into `[DELETED]` placeholders because direct saved-object DELETE is unavailable.

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

# Live Grafana API plus alert artifacts, still source-only
KIBANA_URL= GRAFANA_URL=http://localhost:23000 GRAFANA_USER=admin GRAFANA_PASS=admin \
.venv/bin/grafana-migrate \
  --source api \
  --output-dir migration_output \
  --native-promql \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --fetch-alerts

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

Without `--es-url`, Grafana skips schema discovery and emitted-query validation but still writes YAML, compiled NDJSON, and the normal report artifacts. For pure source-side alert extraction, set `KIBANA_URL=` in the shell to suppress the default local Kibana alerting preflight.

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

# Live Datadog API plus monitor artifacts, still source-only
.venv/bin/datadog-migrate \
  --source api \
  --env-file datadog_creds.env \
  --dashboard-ids abc-def-123 \
  --output-dir datadog_migration_output \
  --field-profile otel \
  --data-view "metrics-*" \
  --fetch-monitors \
  --monitor-ids 12345678
```

Same scope as [Supported live source scope](#supported-live-source-scope) under unified migrate: Grafana dashboards via API (related artifacts from dashboard JSON only); Datadog dashboards via API, with monitor extraction available through the dedicated Datadog CLI or unified `--fetch-alerts`, and rule payload emission/validation limited to validated monitor shapes.

Without `--es-url`, Datadog stays in offline field-capabilities mode and still writes YAML plus the standard run reports. Use the dedicated Datadog CLI when you need explicit dashboard scoping via `--dashboard-ids` before any Elastic target exists.

## Validation / Verification CLIs

```bash
.venv/bin/grafana-validate-uploaded \
  --kibana-url "$KIBANA_URL" \
  --es-url "$ES_URL" \
  --output upload_smoke_report.json

.venv/bin/grafana-generate-corpus --help
```

## Tested Alert Upload Flow

This sequence was re-run against the Serverless target using the curated example corpus.

```bash
.venv/bin/python scripts/generate_alert_support_report.py

set -a && source serverless_creds.env && set +a
.venv/bin/obs-migrate upload \
  --compiled-dir examples/alerting/generated/grafana/compiled \
  --kibana-url "$KIBANA_ENDPOINT" \
  --kibana-api-key "$KEY"

set -a && source serverless_creds.env && set +a
.venv/bin/python scripts/verify_alert_rule_uploads.py \
  --kibana-url "$KIBANA_ENDPOINT" \
  --api-key "$KEY" \
  --keep-rules

set -a && source serverless_creds.env && set +a
.venv/bin/python scripts/audit_migrated_rules.py
```

This flow regenerates the curated Grafana and Datadog alert comparison artifacts, uploads the generated `Legacy Alert Examples` dashboard, creates the emitted Kibana rules disabled by default, and then audits the migrated rules present in Kibana. `scripts/verify_alert_rule_uploads.py` deletes its verification rules unless `--keep-rules` is passed.

## Script Commands

### Local Lab Lifecycle

```bash
bash scripts/start_local_lab.sh
bash scripts/start_local_lab.sh --with-alloy --recreate
bash scripts/stop_local_lab.sh
bash scripts/stop_local_lab.sh --volumes
```

These commands assume the selected local lab project owns the configured local ports. If another repo-owned lab is already using them, set `LOCAL_LAB_PROJECT`, `LOCAL_GRAFANA_PORT`, `LOCAL_ES_PORT`, `LOCAL_KIBANA_PORT`, and any colliding OTLP / Alloy ports before starting a second stack.

### Local Validation Flows

```bash
bash scripts/full_local_demo.sh --sample-set bundled
bash scripts/full_local_demo.sh --sample-set bundled --recreate-lab
bash scripts/full_local_demo.sh
```

These wrappers write reports even when smoke validation or query validation finds issues, so inspect `migration_report.json` and `upload_smoke_report.json` instead of treating exit `0` as “all panels are perfect.”

### Datadog Demo Flows

Default mode uses the curated four-dashboard smoke subset. Browser extras are opt-in.

```bash
bash scripts/run_datadog_demo.sh
bash scripts/run_datadog_demo.sh --browser-audit --capture-screenshots
bash scripts/run_datadog_demo.sh --target serverless
```

For local-target Datadog demos, keep a single local lab stack active on the selected ports. If you just recreated the lab, wait for the chosen Elasticsearch container to report Docker health `healthy` before rerunning the wrapper.

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
DATA_HOURS=6 INTERVAL_SEC=30 BULK_WORKERS=4 BATCH_DOC_LIMIT=8000 \
  .venv/bin/python scripts/setup_serverless_data.py

set -a && source serverless_creds.env && set +a
RECREATE_DATA_STREAMS=1 DASHBOARD_YAML_DIR=datadog_migration_output/yaml \
  .venv/bin/python scripts/setup_datadog_serverless_data.py
```

Use `RECREATE_DATA_STREAMS=1` for the Datadog seed path when targeting a reused cluster so stale metric/log mappings do not cause bulk-ingest errors.

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
