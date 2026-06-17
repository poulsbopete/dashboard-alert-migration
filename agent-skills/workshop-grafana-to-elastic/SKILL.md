---
name: workshop-grafana-to-elastic
description: >
  Workshop skill for Grafana-customer migrations to Elastic Observability Serverless: bulk-convert Grafana dashboard JSON
  (Prometheus/PromQL) into Kibana dashboards and rules via grafana-migrate; pair with Elastic Agent Skills for refinement.
metadata:
  author: workshop
  version: 0.4.0
---

# Grafana → Elastic (workshop)

## When to use

**Grafana → Elastic Serverless** migration practice: **Grafana** exports in `assets/grafana/` (**20** dashboards)
and **`assets/grafana/alerts/`** (unified alert rules for **`--fetch-alerts`**)
→ **[observability-migration-platform](https://github.com/elastic/observability-migration-platform)** **`grafana-migrate`**
→ **`build/mig-grafana/`** + Kibana upload (**`--native-promql`**), then **`tools/publish_grafana_alert_drafts_kibana.py`** for **Rules**.

**Telemetry:** OpenTelemetry SDK → Grafana Alloy → Elastic **mOTLP**. Restart: **`./scripts/start_workshop_otel.sh`**.

## Run migration (Instruqt)

```bash
bash /root/workshop/scripts/migrate_grafana_dashboards_to_serverless.sh
```

Waits for OTLP (or starts **`start_workshop_otel.sh`**), runs **`grafana-migrate`** with **`--upload --ensure-data-views --fetch-alerts`**, then publishes rules. Output: **`build/mig-grafana/yaml/`**, **`migration_report.json`**, **`alert_comparison_results.json`**.

Set **`WORKSHOP_MIG_ES_VALIDATE=1`** to add live ES\|QL validation before upload.

## Optional — laptop + Cursor

1. Clone workshop repo; **`./scripts/install_workshop_mig_to_kbn.sh`**
2. On VM: `grep -E '^export (KIBANA_URL|ES_URL|ES_API_KEY)=' ~/.bashrc` — paste into laptop terminal
3. Run the same migrate script from repo root, or invoke **`grafana-migrate`** directly (see **`scripts/migrate_grafana_dashboards_to_serverless.sh`**)

## Safety

- Never commit API keys.
- Validate panels against **real** metric names and labels in your Serverless project.
