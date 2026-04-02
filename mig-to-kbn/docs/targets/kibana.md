# Kibana Target Runtime

## Overview

The shared Kibana target runtime starts once a source adapter has produced
dashboard YAML. It provides YAML emission helpers, compile/upload functions,
layout validation hooks, and supporting utilities that other pipelines reuse.

Today the shared target code lives in `observability_migration/targets/kibana/`.
It now includes the registered Kibana `TargetAdapter`, shared compile/upload
entry points, and the shared post-upload smoke runtime. Source-aware emitted
query validation still remains in source adapters because it needs
source-specific rewrite logic.

For a current survey of Kibana ES|QL commands, functions, editor behavior, and
translation-relevant opportunities, see `docs/targets/kibana-esql-capabilities.md`.
For the concrete implementation follow-up in this repo, see
`docs/targets/kibana-esql-upgrade-matrix.md`.

## Current Module Map

| Responsibility | Primary location | Notes |
|---|---|---|
| YAML emission | `observability_migration/targets/kibana/emit/` | Shared by all sources |
| Display enrichment | `observability_migration/targets/kibana/emit/display.py` | Common panel display helpers |
| ES\|QL shape helpers | `observability_migration/targets/kibana/emit/esql_utils.py` | Field extraction and query-shape helpers |
| Registered target adapter | `observability_migration/targets/kibana/adapter.py` | Shared `TargetAdapter` for compile/upload/smoke/cluster orchestration |
| Compile / upload / layout validation | `observability_migration/targets/kibana/compile.py` | Wraps `uvx kb-dashboard-cli` and validation scripts |
| Serverless API helpers | `observability_migration/targets/kibana/serverless.py` | Serverless-safe dashboard listing, data view CRUD, deletion workaround |
| Shared smoke validation | `observability_migration/targets/kibana/smoke.py` | Post-upload saved-object validation and browser audit |
| Unified compile / upload / cluster CLI | `observability_migration/app/cli.py` | `obs-migrate compile`, `obs-migrate upload`, `obs-migrate cluster` |
| Grafana query validation | `observability_migration/adapters/source/grafana/esql_validate.py` | Source-aware runtime validation against Elasticsearch |
| Grafana smoke wrapper | `observability_migration/adapters/source/grafana/validate_uploaded_dashboards.py` | Backward-compatible CLI surface for the shared smoke runtime |

## Shared Compile And Upload Flow

`observability_migration/targets/kibana/compile.py` exposes the shared runtime
functions:

- `compile_yaml()` and `compile_all()` compile dashboard YAML to NDJSON.
- `upload_yaml()` compiles and uploads a dashboard through `kb-dashboard-cli`.
- `lint_dashboard_yaml()` runs `scripts/validate_dashboard_yaml.sh`.
- `validate_compiled_layout()` runs `scripts/validate_dashboard_layout.py`.
- `sync_result_queries_to_yaml()` keeps emitted YAML aligned with post-validation query rewrites.

Compilation and upload are implemented via `uvx kb-dashboard-cli`:

```bash
uvx kb-dashboard-cli compile --input-file dashboard.yaml --output-dir compiled/
```

## Command Coverage

Compile/upload/cluster command examples are centralized in `docs/command-contract.md`.

Use that doc for:
- `obs-migrate compile`
- `obs-migrate upload`
- `obs-migrate cluster ...`
- source-specific smoke command examples

## Validation Boundaries

- **Pre-upload query validation** currently lives in source adapters because it needs source-aware query rewrite and manualization logic before compile/upload.
- **YAML lint and compiled-layout validation** are shared target checks and run through `targets/kibana/compile.py`.
- **Post-upload smoke validation** is now shared under `targets/kibana/smoke.py`, with a Grafana wrapper retained for backward-compatible CLI usage.

## Current Structural Gaps

- Source-aware emitted-query validation is still source-located because it depends on Grafana- and Datadog-specific query rewrite logic.
- Datadog now reuses the registered Kibana target adapter for compile/upload/smoke and emits first-class manifest/rollout artifacts. The remaining Datadog parity gap is broader source execution coverage beyond simple metric widgets.
- The shared target adapter does not yet own source-aware pre-upload fixup loops; those still sit at the source boundary.

## Notes By Source

- Grafana uses the full target path: emit, optional runtime validation, lint, compile, optional upload, verification artifacts, and optional smoke merge.
- Datadog reuses shared YAML emission, optional compile (`--compile`), first-class dedicated upload (`--upload`), shared smoke validation (`--smoke`), manifest/rollout artifacts, and verification packets. Preflight is first-class (`--preflight` with capability-aware field checks when `--es-url` is provided), while source-aware query validation remains Datadog-located because it can rewrite emitted queries safely before compile/upload.

## Elastic Serverless Compatibility

Elastic Serverless Kibana restricts saved-object management to two endpoints:

| Operation | API Endpoint | Available? |
|---|---|---|
| List / export dashboards | `POST /api/saved_objects/_export` | Yes |
| Import / upload dashboards | `POST /api/saved_objects/_import` | Yes (with `overwrite`) |
| Get individual saved object | `GET /api/saved_objects/{type}/{id}` | **No** (400) |
| Find saved objects | `GET /api/saved_objects/_find` | **No** (400) |
| Delete saved object | `DELETE /api/saved_objects/{type}/{id}` | **No** (400) |
| Bulk delete saved objects | `POST /api/saved_objects/_bulk_delete` | **No** (400) |

Data view management has full CRUD:

| Operation | API Endpoint | Available? |
|---|---|---|
| List data views | `GET /api/data_views` | Yes |
| Create data view | `POST /api/data_views/data_view` | Yes |
| Get data view | `GET /api/data_views/data_view/{id}` | Yes |
| Update data view | `POST /api/data_views/data_view/{id}` | Yes |
| Delete data view | `DELETE /api/data_views/data_view/{id}` | Yes |
| Runtime fields | Full CRUD | Yes |

### Workarounds

- **Dashboard listing**: Uses `_export` with `type: ["dashboard"]` (auto-fallback from `_find`).
- **Individual dashboard fetch**: Falls back to `_export` with `objects: [{type: "dashboard", id: "..."}]`.
- **Dashboard deletion**: Re-imports with empty content and `[DELETED]` title prefix. The object remains but is harmless. Full removal requires the Kibana UI.
- **Data views**: Use `--ensure-data-views` flag to auto-create required data views before upload.

### CLI Flags

All three CLIs (Grafana, Datadog, unified) support:

```
--list-dashboards          List dashboards in target Kibana and exit
--delete-dashboards IDS    Comma-separated dashboard IDs to clear
--ensure-data-views        Auto-create required data views before upload
```

The unified CLI also provides a dedicated `cluster` subcommand:

```bash
obs-migrate cluster list-dashboards    --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY"
obs-migrate cluster ensure-data-views  --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY" --data-view-patterns "metrics-*,logs-*"
obs-migrate cluster delete-dashboards  --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY" --dashboard-ids "id1,id2"
obs-migrate cluster detect-serverless  --kibana-url "$KIBANA_URL" --kibana-api-key "$KEY"
```

## Location

Shared target package: `observability_migration/targets/kibana/`
