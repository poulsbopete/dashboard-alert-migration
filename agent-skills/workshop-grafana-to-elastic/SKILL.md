---
name: workshop-grafana-to-elastic
description: >
  Workshop skill for Grafana-customer migrations to Elastic Observability Serverless: bulk-convert Grafana dashboard JSON
  (Prometheus/PromQL) into dashboard drafts via CLI; pair with Elastic Agent Skills and Cursor for PromQL→ES|QL planning
  and Kibana Dashboards API publishing.
metadata:
  author: workshop
  version: 0.2.7
---

# Grafana → Elastic (workshop)

## When to use

**Grafana → Elastic Serverless** migration practice: **Grafana** exports in `assets/grafana/` (**20** sample dashboards)
→ **Elastic** drafts under `build/elastic-dashboards/`, then **Kibana** on the **Observability Serverless** project from
**es3-api**. **Telemetry:** **Grafana Alloy** → Elastic **mOTLP** (aligned with **elastic-autonomous-observability**); fallback bulk seed **`./scripts/seed_workshop_telemetry.sh`**. Restart OTLP pipeline: **`./scripts/start_workshop_otel.sh`**.

## Prerequisites

- Python 3.10+
- Workshop checkout (`/root/workshop` in Instruqt)

## Path A — Instruqt Terminal (Kibana API)

```bash
cd /root/workshop && source ~/.bashrc
./scripts/migrate_grafana_dashboards_to_serverless.sh
```

Converts **20** Grafana exports, runs **`tools/seed_workshop_telemetry.py`** ( **`@timestamp`** for ES|QL ), then publishes via **`tools/publish_grafana_drafts_kibana.py`**
(**`POST /api/dashboards?apiVersion=1`**: Markdown + **mixed Lens** — line, area, bar, metric, breakdown, optional **AVG(workshop.requests.rate)**; uniform lines as API fallback; **`WORKSHOP_SIMPLE_LENS=1`** to disable mixing).

## Path B — Laptop + Cursor (same flow as Lab 1 assignment)

Use **Instruqt Terminal** (secrets in `~/.bashrc`) and **laptop** (clone + Cursor). Order matters.

1. **Laptop:** clone **`git@github.com:poulsbopete/dashboard-alert-migration.git`**, **`cd dashboard-alert-migration`**. Grafana inputs: **`assets/grafana/*.json`**.
2. **Instruqt Terminal:** **`cd /root/workshop && source ~/.bashrc`**, then:

   ```bash
   # When bootstrap succeeded: KIBANA_URL, ES_URL, ES_USERNAME, ES_PASSWORD, ES_API_KEY, ES_DEPLOYMENT_ID, WORKSHOP_ROOT.
   # WORKSHOP_OTLP_ENDPOINT is often unset until you add it: Kibana → Add data → OpenTelemetry (…ingest….elastic.cloud).
   grep -E '^export (KIBANA_URL|ES_URL|ES_USERNAME|ES_PASSWORD|ES_API_KEY|ES_DEPLOYMENT_ID|WORKSHOP_ROOT|WORKSHOP_OTLP_ENDPOINT|WORKSHOP_OTLP_AUTH_HEADER)=' ~/.bashrc
   ```

3. **Laptop — Cursor integrated terminal:** paste the printed **`export`** lines, Enter (do not paste into chat).
4. **Cursor:** install [Elastic Agent Skills](https://github.com/elastic/agent-skills) **`kibana-dashboards`**, attach it, open this repo folder.
5. **Laptop terminal** (clone directory):

   ```bash
   mkdir -p build/elastic-dashboards
   python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
   ```

6. **Optional:** prompt the model (with **`kibana-dashboards`**) to **`POST`/`PUT`** dashboards to **`KIBANA_URL`**, or map **PromQL** → **ES|QL** / Lens. Running **`python3 tools/publish_grafana_drafts_kibana.py`** from the clone (with env from Instruqt pasted) applies the same **mixed Lens** layout as Path A. Optional audit trail: **`build/migration-notes/`**.

## Safety

- Never commit API keys.
- Validate panels against **real** metric names and labels in your Serverless project.
