---
slug: lab-02-datadog-dashboards-alerts-to-elastic
id: berxl591tjk4
type: challenge
title: Lab 2 — Datadog dashboards & monitors → Elastic
teaser: Ten Datadog-style dashboards plus four monitors — CLI drafts, Cursor + Agent
  Skills for Kibana dashboards and alerting rules.
notes:
- type: text
  contents: |
    ## Telemetry workflow

    **Live workshop data** flows like this (same as Lab 1 — Alloy → Elastic **mOTLP**):

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
- type: text
  contents: |
    ## Track goal

    **Lab 2** — **10** Datadog dashboard JSON → `build/elastic-datadog-dashboards/`, **4** monitors → `build/elastic-alerts/`.
    Refine in Kibana or with **Cursor** + **`kibana-dashboards`** / **`kibana-alerting-rules`** skills.

    **Live OTLP:** **`./scripts/send_datadog_otel.sh`** (or **`tools/datadog_otel_to_elastic.py`**) — same pipeline as Lab 1.
tabs:
- id: fsizfoyfjtag
  title: Terminal
  type: terminal
  hostname: es3-api
  workdir: /root/workshop
- id: v9ea7agmywny
  title: Elastic Serverless
  type: service
  hostname: es3-api
  path: /
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

# Lab 2 — Datadog → Elastic Serverless

**10** dashboards and **4** monitors import as Kibana **Dashboards** (`(Datadog dashboard import draft)`) and **Rules** (imported **disabled**, no connectors until you edit).

## Terminal

```bash
cd /root/workshop
source ~/.bashrc
./scripts/migrate_datadog_dashboards_to_serverless.sh
```

Then **Dashboards** and **Observability → Rules** in the Elastic Serverless tab.

*Charts empty?* **`./scripts/check_workshop_otel_pipeline.sh`** then **`./scripts/start_workshop_otel.sh`**. *Old scripts?* **`./scripts/sync_workshop_from_git.sh`**.

## Cursor (optional)

Clone **[github.com/poulsbopete/dashboard-alert-migration](https://github.com/poulsbopete/dashboard-alert-migration)** — use **`export`** lines from **`~/.bashrc`** on the VM to publish from your laptop, or only **refine** dashboards/rules in Kibana after the migrate script ran on the VM. Skills: **`workshop-datadog-dashboards-to-elastic`**, **`workshop-datadog-to-elastic-alerts`**, **`kibana-dashboards`**, **`kibana-alerting-rules`**.

## Done

**Check** when **`build/elastic-datadog-dashboards/`** has **10** `*-elastic-draft.json` and **`build/elastic-alerts/`** has **4** `monitor-*-elastic.json`.
