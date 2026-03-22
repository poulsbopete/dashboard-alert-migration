---
name: workshop-grafana-to-elastic
description: >
  Workshop skill: bulk-migrate Grafana dashboard JSON (Prometheus/PromQL) into Elastic Observability Serverless
  dashboard drafts using the bundled CLI; combine with Elastic Agent Skills and Cursor AI for PromQL→ES|QL planning and
  Kibana Saved Object / API publishing.
metadata:
  author: workshop
  version: 0.2.0
---

# Grafana → Elastic (workshop)

## When to use

Bulk migration of **Grafana** exports in `assets/grafana/` (**20** sample dashboards in this track) into **Elastic**
drafts under `build/elastic-dashboards/`, then refinement in **Kibana** on the **Observability Serverless** project
provisioned by **es3-api**.

## Prerequisites

- Python 3.10+
- Workshop checkout (`/root/workshop` in Instruqt)

## Path A — Instruqt Terminal (Kibana API)

```bash
cd /root/workshop && source ~/.bashrc
./scripts/migrate_grafana_dashboards_to_serverless.sh
```

Converts **20** Grafana exports and publishes dashboard shells via **`tools/publish_grafana_drafts_kibana.py`**
(**`POST /api/saved_objects/_import`** with NDJSON; Serverless does not enable saved-object create/bulk-create APIs).

## Path B — Drafts only (then Cursor / skills)

```bash
mkdir -p build/elastic-dashboards
python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
```

Expect **20** files `*-elastic-draft.json`. Publish with **`kibana-dashboards`** (or extend panels beyond empty shells).

## Elastic Agent Skills + Cursor

1. Install [Elastic Agent Skills](https://github.com/elastic/agent-skills) — at minimum patterns from **`kibana-dashboards`**
   for Saved Objects / HTTP API workflows on Serverless.
2. Open this repo in **Cursor**. Attach the **`kibana-dashboards`** skill (or equivalent) so the model follows current Kibana APIs.
3. For each draft (or in batches), prompt the model to:
   - Map **PromQL** panels to **PromQL-native** metric views where available, or propose **ES|QL** / **TS** alternatives.
   - Produce a short **per-dashboard** note file under `build/migration-notes/` (create the directory) if you want an audit
     trail — optional but matches real migrations.
4. Use **`source ~/.bashrc`** in the workshop Terminal to load `ES_URL` / `ES_PASSWORD` / `ES_API_KEY` when calling Kibana APIs
   per the upstream skill.

## Safety

- Never commit API keys.
- Validate panels against **real** metric names and labels in your Serverless project.
