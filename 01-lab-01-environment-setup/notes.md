# While this challenge loads: why Elastic Observability Serverless?

**This lab:** Wire **OpenTelemetry Collector**, **Grafana Alloy**, and your **Elastic Serverless** OTLP endpoint — the same edge pattern many teams use before they retire legacy scrapers and agents.

Use this time to skim how a **Grafana + Datadog-style** footprint maps onto **one** Elastic stack.

## Operational wins

- **One place for signals** — Metrics, logs, and traces in a single Observability workflow instead of hand-stitching Grafana, agents, and a separate APM or log tool.
- **Less control-plane toil** — Serverless projects avoid sizing and patching a self-managed Elasticsearch cluster; you focus on ingest, retention, and access policy.
- **PromQL continuity** — Grafana dashboards built on Prometheus can often move faster because Elastic supports **PromQL** against Prometheus-compatible metric workflows (fewer full rewrites than jumping to a brand-new query language everywhere).
- **Clearer ownership** — Unified RBAC, spaces, and Kibana navigation reduce “which UI is source of truth?” friction for SRE and app teams.

## Migration and automation

- **CLI-first, then productize** — Start with scripts and APIs for dashboard and alert translation; layer **Elastic Agent Skills** or other agents on top when you want repeatable, reviewable automation.
- **Alerting is still bespoke** — Expect to map Datadog monitors to the right Elastic rule types (threshold, query, ML). Plan for a **short-term compromise** while you standardize.

## Cost lens (high level)

- Spend tends to follow **ingest volume** and **retention**, not idle clusters.
- **Cardinality discipline** (labels, rollups, drops at the collector) stays the main cost lever—regardless of vendor.

When the environment is ready, continue in the **Assignment** tab and use the **Terminal** tab for commands.
