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
    ## This lab

    **10** Datadog dashboards + **4** monitors → Kibana. Pick **Path A** (Terminal migrate script) or **Path B** (laptop: converters + publish, same idea as Lab 1).

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

Pick **Path A** or **Path B** (or both).

## Path A — one script (same idea as Lab 1)

```bash
cd /root/workshop
source ~/.bashrc
./scripts/migrate_datadog_dashboards_to_serverless.sh
```

Then **Dashboards** and **Observability → Rules** in the Elastic Serverless tab.

*Charts empty?* **`./scripts/check_workshop_otel_pipeline.sh`** then **`./scripts/start_workshop_otel.sh`**. *Old scripts?* **`./scripts/sync_workshop_from_git.sh`**.

## Path B — Cursor on your laptop

Clone **[github.com/poulsbopete/dashboard-alert-migration](https://github.com/poulsbopete/dashboard-alert-migration)**. On the **Instruqt** VM, print env to copy:

```bash
cd /root/workshop && source ~/.bashrc
grep -E '^export (KIBANA_URL|ES_URL|ES_API_KEY|ES_USERNAME|ES_PASSWORD)=' ~/.bashrc
```

Paste those **`export`** lines into your laptop terminal (not the AI chat). Run **`./scripts/start_workshop_otel.sh`** on the **VM** once so Lens has data, then from the **clone**:

```bash
mkdir -p build/elastic-datadog-dashboards build/elastic-alerts
python3 tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/*.json --out-dir build/elastic-datadog-dashboards
for f in assets/datadog/monitor-*.json; do
  base="$(basename "$f" .json)"
  python3 tools/datadog_to_elastic_alert.py "$f" -o "build/elastic-alerts/${base}-elastic.json"
done
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-datadog-dashboards
python3 tools/publish_datadog_alert_drafts_kibana.py --alerts-dir build/elastic-alerts
```

Optional skills: **`workshop-datadog-dashboards-to-elastic`**, **`workshop-datadog-to-elastic-alerts`**, **`kibana-dashboards`**, **`kibana-alerting-rules`**.

## Done

**Check** when **`build/elastic-datadog-dashboards/`** has **10** `*-elastic-draft.json` and **`build/elastic-alerts/`** has **4** `monitor-*-elastic.json` (Path A: **`/root/workshop/build/`**; Path B: your clone).
