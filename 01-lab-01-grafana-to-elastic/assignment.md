---
slug: lab-01-grafana-to-elastic
id: 7xffw36spadb
type: challenge
title: Lab 1 — Grafana → Elastic (API path or Cursor path)
teaser: One-click Terminal migration via Kibana API, or Agent Skills + Cursor on your
  laptop—only Terminal and Elastic Serverless tabs.
notes:
- type: text
  contents: |
    ## Two labs

    **Lab 1 — Grafana (20 dashboards)** — Pick **Path A** (script + Kibana API in Terminal) or **Path B** (API key + Cursor + Elastic Agent Skills on your laptop).

    **Lab 2 — Datadog** — Ten dashboard JSON + four monitor JSON → Elastic drafts.

    This challenge uses only **Terminal** and **Elastic Serverless** (no Workshop tab).
- type: text
  contents: |
    ## Path A (fast)

    Run **`scripts/migrate_grafana_dashboards_to_serverless.sh`** after `source ~/.bashrc`. It converts Grafana exports and **POSTs** dashboard saved objects to your Serverless Kibana.

    ## Path B (skills + AI)

    Copy **`KIBANA_URL`**, **`ES_URL`**, **`ES_API_KEY`** (or **`ES_PASSWORD`**) from the sandbox Terminal into your laptop env; use [Elastic Agent Skills](https://github.com/elastic/agent-skills) (**`kibana-dashboards`**) in **Cursor** with the same repo / drafts.
tabs:
- id: lypopaehfkah
  title: Terminal
  type: terminal
  hostname: es3-api
  workdir: /root/workshop
- id: blxkp1sz0kzz
  title: Elastic Serverless
  type: service
  hostname: es3-api
  path: /app/dashboards#/list?_g=(filters:!(),refreshInterval:(pause:!f,value:30000),time:(from:now-30m,to:now))
  port: 8080
  custom_request_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self'' https://kibana.estccdn.com; worker-src blob: ''self'';
      style-src ''unsafe-inline'' ''self'' https://kibana.estccdn.com; style-src-elem
      ''unsafe-inline'' ''self'' https://kibana.estccdn.com'
  custom_response_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self'' https://kibana.estccdn.com; worker-src blob: ''self'';
      style-src ''unsafe-inline'' ''self'' https://kibana.estccdn.com; style-src-elem
      ''unsafe-inline'' ''self'' https://kibana.estccdn.com'
difficulty: ""
enhanced_loading: null
---

# Lab 1 — Grafana → Elastic Serverless (**20 dashboards**)

You only need the **Terminal** and **Elastic Serverless** tabs. Pick **one** path below (or do both).

## Prep — credentials

```bash
cd /root/workshop
source ~/.bashrc
# Exports: KIBANA_URL, ES_URL, ES_USERNAME, ES_PASSWORD, ES_API_KEY (when bootstrap succeeded)
```

The **`workshop-migration`** API key in Kibana (Admin → API keys) matches **`ES_API_KEY`** here when setup completed successfully. If `ES_API_KEY` is empty, create a key in the UI or use **`admin`** + **`ES_PASSWORD`** (basic auth).

---

## Path A — All-in-one script (Kibana Dashboard API)

From **`/root/workshop`**, run:

```bash
./scripts/migrate_grafana_dashboards_to_serverless.sh
```

This will:

1. Run **`tools/grafana_to_elastic.py`** on all **`assets/grafana/*.json`** → **`build/elastic-dashboards/*-elastic-draft.json`** (20 files).
2. Run **`tools/publish_grafana_drafts_kibana.py`**, which creates dashboards via **`POST /api/dashboards?apiVersion=1`** (Markdown panel for PromQL / migration notes when present). If that fails for an object, it falls back to a **minimal** **`POST /api/saved_objects/_import`** (single-object NDJSON). Serverless is unreliable for hand-built bulk saved-object imports, so the Dashboards API is the primary path.

Then open **Elastic Serverless → Dashboards** and confirm **~20** dashboards (titles end with **`(Grafana import draft)`**). Add **Lens** panels in the UI as needed.

**Manual steps (same as script internals):**

```bash
mkdir -p build/elastic-dashboards
python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
```

---

## Path B — Elastic Agent Skills + Cursor (your laptop)

Use this when you want the model and **[Elastic Agent Skills](https://github.com/elastic/agent-skills)** (**`kibana-dashboards`**) to drive **Saved Objects** / **dashboard** APIs with richer Lens definitions than the automated shell.

For **`GET` / `POST` / `PUT` / `DELETE /api/dashboards?apiVersion=1`** (headers, spaces, supported panels), see the repo guide **[`docs/dashboards-api-getting-started.md`](../../docs/dashboards-api-getting-started.md)**.

1. **Clone** this workshop repository on your laptop (same layout as `/root/workshop`).
2. In the **Instruqt Terminal**, run **`source ~/.bashrc`** and **copy** (do not paste into chat logs): **`KIBANA_URL`**, **`ES_URL`**, **`ES_API_KEY`** or **`ES_PASSWORD`**.
3. Export those variables in your laptop shell or `.env` for Cursor / skills.
4. In **Cursor**, install skills (`npx skills add elastic/agent-skills --skill kibana-dashboards` or equivalent), attach **`kibana-dashboards`**, and follow **`agent-skills/workshop-grafana-to-elastic/SKILL.md`**.
5. Generate drafts locally:
   `python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards`
   Then use the skill (or Cursor) to **create/update** dashboards against **`KIBANA_URL`**—optionally going beyond empty shells to real **Lens** / **ES|QL** panels.

**Security:** never commit API keys; avoid pasting secrets into model prompts.

---

## Done

Click **Check** when **`build/elastic-dashboards/`** contains **20** files named **`*-elastic-draft.json`** (Path A or B both produce these; Path A also publishes to Kibana automatically).
