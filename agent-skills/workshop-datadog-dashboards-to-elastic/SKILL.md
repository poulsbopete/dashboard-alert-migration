---
name: workshop-datadog-dashboards-to-elastic
description: >
  Workshop skill: bulk-migrate Datadog-style dashboard JSON (widgets with metric/logs queries) into Elastic
  Observability Serverless dashboard drafts using the bundled CLI; pair with upstream kibana-dashboards Agent Skill and
  Cursor for AI-assisted query rewriting.
metadata:
  author: workshop
  version: 0.1.0
---

# Datadog dashboards → Elastic (workshop)

## When to use

Migrating **Datadog dashboard** exports under `assets/datadog/dashboards/` into **Elastic** dashboard drafts for Kibana,
optionally driving **batch steps** from **Cursor** with [Elastic Agent Skills](https://github.com/elastic/agent-skills).

## Prerequisites

- Python 3.10+
- This repository (workshop VM: `/root/workshop`)

## Batch CLI

```bash
mkdir -p build/elastic-datadog-dashboards
python3 tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/*.json --out-dir build/elastic-datadog-dashboards
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
