---
name: workshop-datadog-dashboards-to-elastic
description: >
  Workshop skill for Datadog-customer migrations to Elastic Observability Serverless: bulk-convert Datadog-style dashboard
  JSON into Kibana dashboard drafts via CLI; pair with kibana-dashboards Agent Skill and Cursor for query rewriting.
metadata:
  author: workshop
  version: 0.1.3
---

# Datadog dashboards → Elastic (workshop)

## When to use

Migrating **Datadog dashboard** exports under `assets/datadog/dashboards/` into **Elastic** dashboard drafts for Kibana,
optionally driving **batch steps** from **Cursor** with [Elastic Agent Skills](https://github.com/elastic/agent-skills).

## Prerequisites

- Python 3.10+
- This repository (workshop VM: `/root/workshop`)

## Live telemetry (OTLP → Elastic mOTLP)

With Alloy running (**`./scripts/start_workshop_otel.sh`** after `source ~/.bashrc`), run **`./scripts/send_datadog_otel.sh`** to push **Datadog-style** OpenTelemetry **traces, metrics, and logs** to **`127.0.0.1:4318`** → Alloy → Elastic **managed OTLP** (see **`tools/datadog_otel_to_elastic.py`**).

## Batch CLI

```bash
mkdir -p build/elastic-datadog-dashboards
python3 tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/*.json --out-dir build/elastic-datadog-dashboards
```

## Publish to Kibana (drafts are not visible in the UI until you publish)

Lab 1 uses **`tools/publish_grafana_drafts_kibana.py`**; the same tool publishes Datadog-derived **`*-elastic-draft.json`** when you point **`--drafts-dir`** at **`build/elastic-datadog-dashboards`** (it reads **`migration.datadog_query`**).

**All-in-one on the workshop VM:**

```bash
cd /root/workshop && source ~/.bashrc
./scripts/migrate_datadog_dashboards_to_serverless.sh
```

**Publish only** (after CLI conversion):

```bash
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-datadog-dashboards
```

## Cursor + AI workflow

1. Open the repo in **Cursor** (or your agentic IDE).
2. Install upstream skills (for example `npx skills add elastic/agent-skills --skill kibana-dashboards`).
3. Paste one Datadog dashboard JSON and one generated `*-elastic-draft.json`; ask the model to propose **ES|QL** or **PromQL**
   equivalents and **Lens** panel shapes for your **Serverless** data model.
4. In Cursor, use env from `source ~/.bashrc` (`ES_URL`, `ES_PASSWORD`, `ES_API_KEY`) when following the **kibana-dashboards** skill for API calls.

## Safety

- Do not paste long-lived API keys into shared chats.
- Treat drafts as **starting points**; validate every query against real indices and cardinality.
