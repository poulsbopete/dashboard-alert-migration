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

    Next: run both CLIs, then refine in the **Elastic Serverless** tab. (Terminal + Elastic Serverless only.)
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

## Outcome

1. Convert **10** Datadog-style **dashboard** JSON files (`assets/datadog/dashboards/*.json`) into Elastic dashboard drafts in `build/elastic-datadog-dashboards/`.
2. Convert **4** Datadog-style **monitor** JSON files (`assets/datadog/monitor-*.json`) into Kibana alerting drafts in `build/elastic-alerts/`.
3. Use **Cursor** + **[Elastic Agent Skills](https://github.com/elastic/agent-skills)** (**`kibana-dashboards`**, **`kibana-alerting-rules`**) to push from drafts into **Kibana** / **Rules** on your **Observability Serverless** project.

## 1) Inspect inputs

```bash
cd /root/workshop
ls -1 assets/datadog/dashboards/*.json | wc -l   # 10
ls -1 assets/datadog/monitor-*.json
```

## 2) Dashboard batch CLI

```bash
source ~/.bashrc
mkdir -p build/elastic-datadog-dashboards
python3 tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/*.json --out-dir build/elastic-datadog-dashboards
ls -1 build/elastic-datadog-dashboards/*-elastic-draft.json | wc -l   # expect 10
```

## 3) Monitor → alert drafts

```bash
mkdir -p build/elastic-alerts
for f in assets/datadog/monitor-*.json; do
  base="$(basename "$f" .json)"
  python3 tools/datadog_to_elastic_alert.py "$f" -o "build/elastic-alerts/${base}-elastic.json"
done
ls -1 build/elastic-alerts/*-elastic.json | wc -l   # expect 4
```

## 4) Cursor + Agent Skills (recommended)

- Read **`agent-skills/workshop-datadog-dashboards-to-elastic/SKILL.md`** and **`agent-skills/workshop-datadog-to-elastic-alerts/SKILL.md`**.
- In **Cursor**, batch through dashboards: for each pair (Datadog JSON → `*-elastic-draft.json`), ask the model for metric / log query mapping into **ES|QL** or **PromQL-native** views.
- For alerts, use **`kibana-alerting-rules`** patterns to shape threshold vs query rules and connectors.

## 5) Refine in Kibana

Use the **Elastic Serverless** tab: **Dashboards** / **Lens** for visualizations, **Rules** for alerting. Replace placeholders with queries that run on **your** data.

## Done

Click **Check** when:

- `build/elastic-datadog-dashboards/` has **10** files matching `*-elastic-draft.json`, and
- `build/elastic-alerts/` has **4** files matching `*-elastic.json`.
