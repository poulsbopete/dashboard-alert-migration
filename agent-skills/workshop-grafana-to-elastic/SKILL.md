---
name: workshop-grafana-to-elastic
description: >
  Workshop skill for Grafana-customer migrations to Elastic Observability Serverless: bulk-convert Grafana dashboard JSON
  (Prometheus/PromQL) into dashboard drafts via CLI; pair with Elastic Agent Skills and Cursor for PromQL→ES|QL planning
  and Kibana Dashboards API publishing.
metadata:
  author: workshop
  version: 0.2.13
---

# Grafana → Elastic (workshop)

## When to use

**Grafana → Elastic Serverless** migration practice: **Grafana** exports in `assets/grafana/` (**20** sample dashboards)
→ **Elastic** drafts under `build/elastic-dashboards/`, then **Kibana** on the **Observability Serverless** project from
**es3-api**. **Telemetry:** **OpenTelemetry SDK** (Python emitters) → **Grafana Alloy** → Elastic **mOTLP** — same path as production OTLP. Restart: **`./scripts/start_workshop_otel.sh`**. Legacy bulk JSON (**`seed_workshop_telemetry.py`**) exists only if **`WORKSHOP_ALLOW_BULK_SEED=1`** on bootstrap (not default).

## Prerequisites

- Python 3.10+
- Workshop checkout (`/root/workshop` in Instruqt)

## Path A — Instruqt Terminal (Kibana API)

```bash
cd /root/workshop && source ~/.bashrc
./scripts/migrate_grafana_dashboards_to_serverless.sh
```

Converts **20** Grafana exports, runs **`./scripts/start_workshop_otel.sh`** (OTLP → mOTLP), brief wait, then publishes via **`tools/publish_grafana_drafts_kibana.py`**
(**`POST /api/dashboards?apiVersion=1`**: Markdown + **mixed Lens** — each panel’s chart/ES|QL follows **PromQL + panel title** (not identical widgets on every dashboard); pad with **`WORKSHOP_MIN_LENS_PANELS`** / **`WORKSHOP_MAX_LENS_PANELS`**; **`WORKSHOP_SIMPLE_LENS=1`** = uniform lines).

## Path B — Laptop + Cursor (same flow as Lab 1 assignment)

Use **Instruqt Terminal** (secrets in `~/.bashrc`) and **laptop** (clone + Cursor). Order matters.

1. **Laptop:** clone **`https://github.com/poulsbopete/dashboard-alert-migration.git`** (or **`git@github.com:poulsbopete/dashboard-alert-migration.git`**), **`cd dashboard-alert-migration`**. Repo: [github.com/poulsbopete/dashboard-alert-migration](https://github.com/poulsbopete/dashboard-alert-migration). Grafana inputs: **`assets/grafana/*.json`**.
2. **Instruqt Terminal:** **`cd /root/workshop && source ~/.bashrc`**, then:

   ```bash
   # Exports: KIBANA_URL, ES_URL, ES_USERNAME, ES_PASSWORD, ES_API_KEY (when bootstrap succeeded), ES_DEPLOYMENT_ID,
   # WORKSHOP_ROOT, WORKSHOP_OTLP_ENDPOINT (unique per Instruqt play — from ~/.bashrc / project_results or derived by
   # ./scripts/start_workshop_otel.sh from ES_URL; never paste another lab’s ingest URL).
   grep -E '^export (KIBANA_URL|ES_URL|ES_USERNAME|ES_PASSWORD|ES_API_KEY|ES_DEPLOYMENT_ID|WORKSHOP_ROOT|WORKSHOP_OTLP_ENDPOINT|WORKSHOP_OTLP_AUTH_HEADER)=' ~/.bashrc
   ```

3. **Laptop — Cursor integrated terminal:** paste the printed **`export`** lines, Enter (do not paste into chat).
4. **Cursor:** install [Elastic Agent Skills](https://github.com/elastic/agent-skills) **`kibana-dashboards`**, attach it, open this repo folder.
5. **Laptop terminal** (clone directory):

   ```bash
   mkdir -p build/elastic-dashboards
   python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
   ```

6. **Optional — any Grafana JSON (community gallery or export):** Download or export dashboard JSON (e.g. from **[grafana.com/grafana/dashboards](https://grafana.com/grafana/dashboards/)** or **Grafana → Share → Export**). Save under something like **`build/grafana-imports/`** (often **gitignored**; respect **licenses**). Then:

   ```bash
   python3 tools/grafana_to_elastic.py build/grafana-imports/*.json --out-dir build/elastic-dashboards
   python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
   ```

   Gallery dashboards assume **Prometheus/Loki/Tempo/etc.**; **`grafana_to_elastic.py`** captures **PromQL** into drafts — refine **ES|QL** and panels in Kibana or with **`kibana-dashboards`** + Cursor.

7. **Optional:** prompt the model (with **`kibana-dashboards`**) to **`POST`/`PUT`** dashboards to **`KIBANA_URL`**, or map **PromQL** → **ES|QL** / Lens. Step **6** already runs the publisher; use the skill for custom layouts. Optional audit trail: **`build/migration-notes/`**.

## Safety

- Never commit API keys.
- Validate panels against **real** metric names and labels in your Serverless project.
