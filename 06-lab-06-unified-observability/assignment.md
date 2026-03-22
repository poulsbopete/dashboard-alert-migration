---
slug: lab-06-unified-observability
id: vhw2fgovvr8u
type: challenge
title: Lab 6 — Unified observability + before/after
teaser: Tie metrics, logs, and traces to a merchant drill-down narrative and compare
  operational models.
difficulty: ""
enhanced_loading: null
---

# Lab 6 — Unified observability + before/after

## Goal

Build a **unified story** in Elastic Observability:

- **Metrics**: request rate, latency, error rate (from Prometheus scrape → remote write → OTLP export)
- **Traces**: payment flows (`payment-simulator` spans)
- **Logs**: container logs (stdout) — in production you would wire log ingestion (Elastic Agent, ECK, or cloud shipper). In this sandbox, emphasize **trace/log correlation** concepts and Kibana navigation.

## Step 1 — Create a unified dashboard draft

Write a small JSON document describing the panels you want in Kibana (this is intentionally lightweight—real publishing should use the dashboards API or Agent Skills).

```bash
cd /root/workshop
cat > build/unified-overview.json <<'EOF'
{
  "title": "Merchant platform — unified overview",
  "description": "Single place for payment health: rates, errors, traces, and merchant drilldowns.",
  "sections": [
    {"name": "Traffic", "signals": ["metrics: http_requests_total"], "drilldown_dimension": "merchant_id"},
    {"name": "Latency", "signals": ["metrics: http_request_duration_seconds histogram"]},
    {"name": "Reliability", "signals": ["metrics: payment_errors_total", "apm: payment-simulator transactions"]},
    {"name": "Investigation", "signals": ["apm: trace sample", "logs: payment_captured JSON"]}
  ],
  "ai_insights": "Use Elastic AI Assistant / Observability insights where available to summarize anomalies across signals."
}
EOF
```

## Step 2 — Bonus comparison (facilitator-led)

### Before (Grafana + Datadog)

- **Dashboards**: PromQL expertise siloed in Grafana; business KPIs duplicated in Datadog.
- **Alerts**: overlapping monitors, noisy pages, inconsistent thresholds.
- **Cardinality**: expensive index + metric series sprawl without a unified governance model.

### After (Elastic Serverless Observability)

- **One stack** for metrics/logs/traces with consistent RBAC and unified navigation.
- **Agent Skills**: encode migration + operational tasks for repeatability.
- **Ops complexity**: fewer moving parts at the edge (Collector + Alloy), more policy in-platform (rollups, lifecycle, ML).

### Cost notes (qualitative)

- Serverless shifts spend toward **ingest + retention** with less cluster tuning.
- Cardinality discipline (label drops, aggregations) remains the biggest lever regardless of vendor.

## Validation

Click **Check** after `build/unified-overview.json` exists and contains `"Merchant platform"`.
