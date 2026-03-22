---
slug: lab-06-unified-observability
id: msxmmkc5azfz
type: challenge
title: Lab 6 — Unified observability + before/after
teaser: Tie metrics, logs, and traces into one narrative and compare “before vs after” operations.
difficulty: ""
enhanced_loading: null
---

# Lab 6 — Unified observability + before/after

## Goal

Build a **unified story** in Elastic Observability:

- **Metrics**: request rate, latency, error rate (Prometheus scrape → remote write → OTLP export)
- **Traces**: service maps and transactions (`sample-api`)
- **Logs**: stdout in this sandbox; in production you would wire log ingestion (Elastic Agent, hosted shipper, etc.).
  Emphasize **correlation** concepts and Kibana navigation.

## Step 1 — Create a unified dashboard draft

Write a small JSON document describing the panels you want in Kibana (lightweight on purpose—real publishing should use
the dashboards API or Agent Skills).

```bash
cd /root/workshop
cat > build/unified-overview.json <<'EOF'
{
  "title": "Unified observability overview",
  "description": "Single view for service health: rates, errors, traces, and entity drilldowns.",
  "sections": [
    {"name": "Traffic", "signals": ["metrics: http_requests_total"], "drilldown_dimension": "entity_id"},
    {"name": "Latency", "signals": ["metrics: http_request_duration_seconds histogram"]},
    {"name": "Reliability", "signals": ["metrics: operation_errors_total", "apm: sample-api transactions"]},
    {"name": "Investigation", "signals": ["apm: trace sample", "logs: request_completed JSON"]}
  ],
  "ai_insights": "Use Elastic AI Assistant / Observability insights where available to summarize anomalies across signals."
}
EOF
```

## Step 2 — Bonus comparison (facilitator-led)

### Before (Grafana + Datadog)

- **Dashboards**: PromQL and panel logic live in Grafana; KPIs may be duplicated elsewhere.
- **Alerts**: overlapping monitors, noisy pages, inconsistent thresholds.
- **Cardinality**: series sprawl without a single governance model.

### After (Elastic Serverless Observability)

- **One stack** for metrics/logs/traces with consistent RBAC and navigation.
- **Agent Skills**: encode migration + operations for repeatability.
- **Ops complexity**: fewer edge moving parts (Collector + Alloy), more policy in-platform (rollups, lifecycle, ML).

### Cost notes (qualitative)

- Serverless shifts spend toward **ingest + retention** with less cluster tuning.
- Cardinality discipline (label drops, aggregations) remains the biggest lever regardless of vendor.

## Validation

Click **Check** after `build/unified-overview.json` exists and contains `"Unified observability overview"`.
