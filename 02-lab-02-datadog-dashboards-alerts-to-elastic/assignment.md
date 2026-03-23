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

    **Migrate Datadog (with Grafana in Lab 1) customers to Elastic Observability Serverless**—dashboards and monitors become
    Kibana drafts, then rules and Lens panels on **live** OTLP-backed data where possible.

    ## This track (two labs)

    **Lab 1** — **20** Grafana dashboards → `build/elastic-dashboards/` (Cursor + **kibana-dashboards** skill).

    **Lab 2** — **10** Datadog **dashboard** JSON files → `build/elastic-datadog-dashboards/` plus **4** **monitor** JSON → `build/elastic-alerts/`.

    Together this is a **20 + 10 = 30** dashboard-class migration exercise, plus **alert** drafts—closer to a real **10–20+**
    dashboard program when you count only the subset you choose to perfect in Kibana.
- type: text
  contents: |
    ## This lab

    - Dashboards: `tools/datadog_dashboard_to_elastic.py` + `agent-skills/workshop-datadog-dashboards-to-elastic/SKILL.md`.
    - Monitors: `tools/datadog_to_elastic_alert.py` + `agent-skills/workshop-datadog-to-elastic-alerts/SKILL.md`.
    - Upstream: [elastic/agent-skills](https://github.com/elastic/agent-skills) — **`kibana-dashboards`**, **`kibana-alerting-rules`**.
- type: text
  contents: |
    ## Cursor + AI

    Use **Cursor** to compare Datadog `widgets[].definition.requests[].q` strings to generated drafts and to draft **ES|QL** /
    **KQL** for Kibana. Let **Agent Skills** own API details; use the model for translation and tedious JSON reshaping—always
    validate on **live** Serverless data.

    One Terminal script (**`migrate_datadog_dashboards_to_serverless.sh`**) converts dashboards + monitors, starts OTLP, **publishes Dashboards and Rules** to Kibana (like Lab 1 Grafana migrate). Optional: refine in Cursor with Agent Skills. (Terminal + Elastic Serverless only.)

    **Live OTLP:** with Alloy + mOTLP running, **`./scripts/send_datadog_otel.sh`** (or **`tools/datadog_otel_to_elastic.py`**) sends Datadog-style OpenTelemetry into the **Elastic managed OTLP** path (same as Lab 1 telemetry).
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

# Lab 2 — Datadog dashboards & monitors → Elastic

This lab is the **Datadog → Elastic Observability Serverless** half of the track: representative **dashboard** and **monitor**
exports become drafts you refine in Kibana—mirroring how you would onboard a Datadog estate without redoing every panel by hand.

## Outcome

1. **10** Datadog dashboards and **4** monitors become Kibana **Dashboards** (in the UI) and **Rules** (draft imports).
2. Optional: use **Cursor** + **`kibana-dashboards`** / **`kibana-alerting-rules`** to tighten **ES|QL** and connectors after the automated import.

---

## Path A — one script (same idea as Lab 1 Grafana)

```bash
cd /root/workshop
source ~/.bashrc
./scripts/migrate_datadog_dashboards_to_serverless.sh
```

This runs **five** steps: convert dashboards → convert monitors → **OTLP** (Alloy) + short wait → **publish dashboards** → **publish rules** (`tools/publish_datadog_alert_drafts_kibana.py`). Rules are created **disabled** with **no connectors** so nothing fires until you edit them.

Then open **Elastic Serverless** → **Dashboards** (titles contain **`(Datadog dashboard import draft)`**) and **Observability → Rules** (Datadog import drafts).

---

## Step by step (same result as Path A)

Use this when you want each stage explicit instead of **`migrate_datadog_dashboards_to_serverless.sh`**. From **`/root/workshop`**, run **`source ~/.bashrc`** once.

**1 — Check inputs** (10 dashboard JSON files, 4 monitors):

```bash
cd /root/workshop
ls -1 assets/datadog/dashboards/*.json | wc -l   # expect 10
ls -1 assets/datadog/monitor-*.json              # 4 files
```

**2 — Build dashboard and alert drafts:**

```bash
mkdir -p build/elastic-datadog-dashboards build/elastic-alerts
python3 tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/*.json --out-dir build/elastic-datadog-dashboards
for f in assets/datadog/monitor-*.json; do
  base="$(basename "$f" .json)"
  python3 tools/datadog_to_elastic_alert.py "$f" -o "build/elastic-alerts/${base}-elastic.json"
done
```

**3 — OTLP + publish to Kibana:**

```bash
./scripts/start_workshop_otel.sh && sleep 25
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-datadog-dashboards
python3 tools/publish_datadog_alert_drafts_kibana.py --alerts-dir build/elastic-alerts
```

---

## Path B — Cursor on your laptop

Clone **[github.com/poulsbopete/dashboard-alert-migration](https://github.com/poulsbopete/dashboard-alert-migration)** and paste **`export`** lines from the Instruqt Terminal (**`grep`** like Lab 1) into Cursor’s terminal.

- **Easiest:** run the full **`./scripts/migrate_datadog_dashboards_to_serverless.sh`** on the **Instruqt VM** (it uses OTLP on that host). On the laptop, only use Cursor + skills to **refine** dashboards/rules after they exist in Kibana.
- **From the laptop:** run the **converter** `*.py` steps + **`publish_grafana_drafts_kibana.py`** / **`publish_datadog_alert_drafts_kibana.py`** against **`KIBANA_URL`**. Ensure **`./scripts/start_workshop_otel.sh`** has run on the **VM** first so Lens has data.

**Optional refinement:** **`agent-skills/workshop-datadog-dashboards-to-elastic/SKILL.md`**, **`workshop-datadog-to-elastic-alerts/SKILL.md`**, **`kibana-dashboards`**, **`kibana-alerting-rules`**.

## Done

Click **Check** when:

- `build/elastic-datadog-dashboards/` has **10** files matching `*-elastic-draft.json`, and
- `build/elastic-alerts/` has **4** files matching `monitor-*-elastic.json`.
