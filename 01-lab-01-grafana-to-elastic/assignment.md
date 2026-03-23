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
    ## Telemetry workflow

    **Live workshop data** flows like this (same path customers use with OTLP → Elastic):

    ```
                      ┌──────────────────────────────┐
                      │  Python OTLP (fleet, DD OTLP) │
                      └──────────────┬───────────────┘
                                     │ OTLP
    Prometheus :12345 ──► Grafana Alloy (:4317 / :4318)
                                     │
                          OTLP/HTTP + Authorization
                                     ▼
                        Elastic managed OTLP (mOTLP)
                                     ▼
                        Observability Serverless project
                                     ▼
                    logs-*    metrics-*    traces-*
                                     ▼
                           Kibana (proxied :8080)
    ```

    Track **bootstrap** creates the project, wires **nginx → Kibana**, starts **Alloy + emitters** when **mOTLP** and **API key** are available.
- type: text
  contents: |
    ## This lab

    **20** Grafana JSON → Elastic drafts → Kibana. Pick **Path A** (VM migrate script) or **Path B** (**Cursor**: open clone, paste **`export`** from VM **`~/.bashrc`**, run converter + publish in integrated terminal — OTLP already running from bootstrap).
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

Pick **Path A** or **Path B** (or both).

## Path A — dashboard migration (Instruqt)

```bash
cd /root/workshop
source ~/.bashrc
./scripts/migrate_grafana_dashboards_to_serverless.sh
```

Open **Elastic Serverless → Dashboards** → titles **`(Grafana import draft)`**.

*Charts empty?* **`./scripts/check_workshop_otel_pipeline.sh`**, **`./scripts/start_workshop_otel.sh`**, wait ~1 min. *Force OTLP restart:* **`WORKSHOP_FORCE_OTEL_RESTART=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh`**. *Old scripts?* **`./scripts/sync_workshop_from_git.sh`**.

## Path B — Cursor on your laptop

1. **Clone** **[github.com/poulsbopete/dashboard-alert-migration](https://github.com/poulsbopete/dashboard-alert-migration)** and open the folder in **Cursor**.
2. On the **VM**, copy env: `cd /root/workshop && source ~/.bashrc` then  
   `grep -E '^export (KIBANA_URL|ES_URL|ES_API_KEY|ES_USERNAME|ES_PASSWORD)=' ~/.bashrc`
3. In Cursor’s **integrated terminal**, paste those **`export`** lines, then:

```bash
mkdir -p build/elastic-dashboards
python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
```

The sandbox **already runs Alloy + OTLP**; you do **not** need **`start_workshop_otel.sh`** on the VM before importing from Cursor. If charts look empty, troubleshoot on the VM with **`./scripts/check_workshop_otel_pipeline.sh`** or **`./scripts/start_workshop_otel.sh`**.

Optional: **[Elastic Agent Skills](https://github.com/elastic/agent-skills)** **`kibana-dashboards`**, **`agent-skills/workshop-grafana-to-elastic/SKILL.md`**. Do not paste API keys into the AI chat.

## Done

**Check** when **`build/elastic-dashboards/`** has **20** `*-elastic-draft.json` (Path A: under **`/root/workshop/build/`**; Path B: your clone).
