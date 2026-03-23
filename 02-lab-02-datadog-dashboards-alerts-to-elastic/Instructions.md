# Lab 2 — Datadog dashboards & monitors (facilitator)

**Audience:** teams **migrating Datadog customers to Elastic Observability Serverless** (pairs with Lab 1 for Grafana).

Ten dashboards under `assets/datadog/dashboards/` → `datadog_dashboard_to_elastic.py` → `build/elastic-datadog-dashboards/`.

**Kibana:** drafts are only files until **`publish_grafana_drafts_kibana.py --drafts-dir build/elastic-datadog-dashboards`** runs (or **`./scripts/migrate_datadog_dashboards_to_serverless.sh`** for convert + OTLP + publish).

Four `monitor-*.json` → `datadog_to_elastic_alert.py` → `build/elastic-alerts/`. Optional: **`send_datadog_otel.sh`** for OTLP
into Elastic **managed OTLP** (Alloy on the VM).
