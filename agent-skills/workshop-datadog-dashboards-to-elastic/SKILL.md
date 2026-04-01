---
name: workshop-datadog-dashboards-to-elastic
description: >
  Workshop skill for Datadog-customer migrations to Elastic Observability Serverless: bulk-convert Datadog-style dashboard
  JSON into Kibana dashboard drafts via CLI; pair with kibana-dashboards Agent Skill and Cursor for query rewriting.
metadata:
  author: workshop
  version: 0.2.0
---

# Datadog dashboards → Elastic (workshop)

## When to use

Migrating **Datadog dashboard** exports via **[mig-to-kbn](https://github.com/elastic/mig-to-kbn)** **`datadog-migrate`**
(**`--field-profile otel`**) into **Kibana** on **Observability Serverless**, optionally with **Cursor** + [Elastic Agent Skills](https://github.com/elastic/agent-skills).
Legacy **`datadog_dashboard_to_elastic.py`** + **`publish_grafana_drafts_kibana.py`** remain for comparison.

## Prerequisites

- **`mig-to-kbn/`** + **`uv`** + Python **≥ 3.11** (VM: **`/opt/mig-to-kbn-venv`**)
- This repository (workshop VM: `/root/workshop`)

## Live telemetry (OTLP → Elastic mOTLP)

With Alloy running (**`./scripts/start_workshop_otel.sh`** after `source ~/.bashrc`), run **`./scripts/send_datadog_otel.sh`** to push **Datadog-style** OpenTelemetry **traces, metrics, and logs** to **`127.0.0.1:4318`** → Alloy → Elastic **managed OTLP** (see **`tools/datadog_otel_to_elastic.py`**).

## Batch CLI (legacy draft JSON)

```bash
mkdir -p build/elastic-datadog-dashboards
python3 tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/*.json --out-dir build/elastic-datadog-dashboards
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-datadog-dashboards
```

## Path A — mig-to-kbn (default on VM)

```bash
cd /root/workshop && source ~/.bashrc
./scripts/migrate_datadog_dashboards_to_serverless.sh
```

Uses **`datadog-migrate`** (Kibana-only **`--upload`** by default; **`WORKSHOP_MIG_ES_VALIDATE=1`** adds **`--es-url`** + live validation), stage dir with **`monitors/`** for monitor JSON, and **`publish_datadog_alert_drafts_kibana.py`** for the four workshop rules. Artifacts: **`build/mig-datadog/`**, **`build/elastic-alerts/`**.

**Publish rules only** (after you have **`monitor-*-elastic.json`**):

```bash
python3 tools/publish_datadog_alert_drafts_kibana.py --alerts-dir build/elastic-alerts
```

## Cursor + AI workflow

1. Open the repo in **Cursor** (or your agentic IDE).
2. Install upstream skills (for example `npx skills add elastic/agent-skills --skill kibana-dashboards`).
3. Paste one Datadog dashboard JSON and one generated **`build/mig-datadog/yaml/*.yaml`** snippet (or legacy `*-elastic-draft.json`); ask the model to propose **ES|QL** or metric-query equivalents and **Lens** shapes for **Serverless**.
4. In Cursor, use env from `source ~/.bashrc` (`ES_URL`, `ES_PASSWORD`, `ES_API_KEY`) when following the **kibana-dashboards** skill for API calls.

## Safety

- Do not paste long-lived API keys into shared chats.
- Treat drafts as **starting points**; validate every query against real indices and cardinality.
