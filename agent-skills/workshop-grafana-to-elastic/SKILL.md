---
name: workshop-grafana-to-elastic
description: >
  Workshop skill for Grafana-customer migrations to Elastic Observability Serverless: bulk-convert Grafana dashboard JSON
  (Prometheus/PromQL) into dashboard drafts via CLI; pair with Elastic Agent Skills and Cursor for PromQL→ES|QL planning
  and Kibana Dashboards API publishing.
metadata:
  author: workshop
  version: 0.3.0
---

# Grafana → Elastic (workshop)

## When to use

**Grafana → Elastic Serverless** migration practice: **Grafana** exports in `assets/grafana/` (**20** sample dashboards)
→ **[mig-to-kbn](https://github.com/elastic/mig-to-kbn)** **`grafana-migrate`** → **`build/mig-grafana/`** + upload to **Kibana** on **Observability Serverless** (**`--native-promql`** for Serverless). **Telemetry:** **OpenTelemetry SDK** → **Grafana Alloy** → Elastic **mOTLP**. Restart: **`./scripts/start_workshop_otel.sh`**. Optional legacy **`tools/grafana_to_elastic.py`** + **`publish_grafana_drafts_kibana.py`** still exist for comparison.

## Prerequisites

- **`mig-to-kbn/`** + **`uv`** + Python **≥ 3.11** (Instruqt: **`/opt/mig-to-kbn-venv`** from **`install_workshop_mig_to_kbn.sh`**)
- Workshop checkout (`/root/workshop` in Instruqt)

## Path A — Instruqt Terminal (Kibana API)

```bash
cd /root/workshop && source ~/.bashrc
./scripts/migrate_grafana_dashboards_to_serverless.sh
```

Waits for OTLP (or starts **`start_workshop_otel.sh`**), then runs **`grafana-migrate`** with **`--validate --upload --ensure-data-views`** (see Lab 1 **`assignment.md`**). Output: **`build/mig-grafana/yaml/`**, **`migration_report.json`**.

## Path B — Laptop + Cursor (same flow as Lab 1 assignment)

Use **Instruqt Terminal** (secrets in `~/.bashrc`) and **laptop** (clone + Cursor). Order matters.

1. **Laptop:** clone the workshop repo **including** **`mig-to-kbn/`** (private **`elastic/mig-to-kbn`**). Run **`./scripts/install_workshop_mig_to_kbn.sh`**. Grafana inputs: **`assets/grafana/*.json`** (top-level only; **`fixtures/`** excluded by Grafana file glob).
2. **Instruqt Terminal:** **`cd /root/workshop && source ~/.bashrc`**, then:

   ```bash
   # Exports: KIBANA_URL, ES_URL, ES_USERNAME, ES_PASSWORD, ES_API_KEY (when bootstrap succeeded), ES_DEPLOYMENT_ID,
   # WORKSHOP_ROOT, WORKSHOP_OTLP_ENDPOINT (unique per Instruqt play — from ~/.bashrc / project_results or derived by
   # ./scripts/start_workshop_otel.sh from ES_URL; never paste another lab’s ingest URL).
   grep -E '^export (KIBANA_URL|ES_URL|ES_USERNAME|ES_PASSWORD|ES_API_KEY|ES_DEPLOYMENT_ID|WORKSHOP_ROOT|WORKSHOP_OTLP_ENDPOINT|WORKSHOP_OTLP_AUTH_HEADER)=' ~/.bashrc
   ```

3. **Laptop — Cursor integrated terminal:** paste the printed **`export`** lines, Enter (do not paste into chat).
4. **Cursor:** install [Elastic Agent Skills](https://github.com/elastic/agent-skills) **`kibana-dashboards`**, attach it, open this repo folder.
5. **Laptop terminal:** mirror Lab 1 Path B — run **`grafana-migrate`** with **`--input-dir assets/grafana`** (see **`01-lab-01-grafana-to-elastic/assignment.md`**).

6. **Optional — legacy drafts:** **`python3 tools/grafana_to_elastic.py …`** + **`publish_grafana_drafts_kibana.py`** for `*-elastic-draft.json` flows.

7. **Optional:** use **`kibana-dashboards`** to refine uploaded dashboards or map **PromQL** → **ES|QL** / Lens in Kibana.

## Safety

- Never commit API keys.
- Validate panels against **real** metric names and labels in your Serverless project.
