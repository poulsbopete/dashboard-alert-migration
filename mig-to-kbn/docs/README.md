# Documentation Guide

Use this index when you want the shortest path to the right document.

## Start Here

| Path | Use when |
|---|---|
| `../README.md` | You want the runnable entry points, capability matrix, and common commands |
| `command-contract.md` | You want the canonical command inventory and safe invocation examples |
| `architecture.md` | You want the repo-level architecture, boundaries, and package map |
| `pipeline-trace.md` | You want the shared pipeline overview and cross-source audit summary |
| `../REMAINING-ROADMAP.md` | You want the current roadmap and highest-priority gaps |

## Source Docs

| Path | Use when |
|---|---|
| `sources/grafana.md` | You want Grafana adapter capabilities, flags, and workflow boundaries |
| `sources/grafana-trace.md` | You want auto-generated Grafana per-dashboard traces |
| `sources/datadog.md` | You want Datadog adapter capabilities, flags, and workflow boundaries |
| `sources/datadog-trace.md` | You want auto-generated Datadog per-dashboard traces |

## Target And Schema Docs

| Path | Use when |
|---|---|
| `targets/kibana.md` | You want the shared Kibana emit / compile / upload runtime |
| `targets/kibana-esql-capabilities.md` | You want the current ES|QL capability survey |
| `targets/kibana-esql-upgrade-matrix.md` | You want the concrete ES|QL follow-up matrix for this repo |
| `dashboards/README.md` | You want the dashboard YAML schema, lint, and layout validation tooling |

## Contributing Docs

| Path | Use when |
|---|---|
| `contributing/import-paths.md` | You need the canonical Python import paths |
| `contributing/add-source.md` | You are adding a new source adapter |
| `contributing/add-asset-type.md` | You are adding a new shared asset type |
| `architecture/asset-model.md` | You need the canonical IR and result contracts |
| `architecture/tooling-matrix.md` | You want guidance on YAML, Pydantic, CUE, Hypothesis, and parser tooling |

## Generated Docs

These files are regenerated from templates and runtime data:

- `pipeline-trace.md`
- `sources/grafana-trace.md`
- `sources/datadog-trace.md`

Regenerate them with:

```bash
python scripts/audit_pipeline.py --update-docs
```

Their editable templates live next to them as `*.tpl.md`.

## Ops Docs

| Path | Use when |
|---|---|
| `local-otlp-validation.md` | You want the local validation lab and OTLP data flow |
