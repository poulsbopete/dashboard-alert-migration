# Lab 2 — Datadog dashboards & monitors (facilitator)

**Audience:** teams **migrating Datadog customers to Elastic Observability Serverless** (pairs with Lab 1 for Grafana).

Ten dashboards under `assets/datadog/dashboards/` → `datadog_dashboard_to_elastic.py` → `build/elastic-datadog-dashboards/`.

**Kibana:** **`bash /root/workshop/scripts/migrate_datadog_dashboards_to_serverless.sh`** converts dashboards + monitors, runs OTLP, publishes **Dashboards** and **Rules** (see **`tools/publish_datadog_alert_drafts_kibana.py`**).

Four `monitor-*.json` → `datadog_to_elastic_alert.py` → `build/elastic-alerts/`. OTLP: **`send_datadog_otel.sh`** or Alloy on the VM → Elastic **managed OTLP**.
