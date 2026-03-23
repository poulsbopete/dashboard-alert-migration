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

    ```mermaid
    flowchart TB
      subgraph vm["Workshop VM"]
        PY["Python OTLP SDK\nfleet + Datadog-style emitters"]
        AL["Grafana Alloy\nOTLP :4317 / :4318"]
        PR["Prometheus scrape\nAlloy self-metrics :12345"]
        PY --> AL
        PR --> AL
      end
      AL -->|"OTLP/HTTP + API key\nWORKSHOP_OTLP_*"| M["Elastic managed OTLP\nmOTLP"]
      M --> P["Observability\nServerless"]
      P --> D["Data: logs-* · metrics-* · traces-*"]
      D --> K["Kibana\nbrowser tab :8080"]
    ```

    **If the diagram does not render**, use this view:

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

    Track **bootstrap** creates the project, wires **nginx → Kibana**, installs **Alloy + emitters** when **mOTLP** URL and **API key** are available.
- type: text
  contents: |
    ## Track goal

    **Migrate Grafana (and in Lab 2, Datadog) workloads toward Elastic Observability Serverless**—this lab is the Grafana
    side: lots of real dashboard JSON, then Kibana publishing and optional AI-assisted refinement.

    ## Two labs

    **Lab 1 — Grafana (20 dashboards)** — Pick **Path A** (script + Kibana API in Terminal) or **Path B** (API key + Cursor + Elastic Agent Skills on your laptop).

    **Lab 2 — Datadog** — Ten dashboard JSON + four monitor JSON → Elastic drafts.
- type: text
  contents: |
    ## Path A

    In Terminal: **`cd /root/workshop`**, **`source ~/.bashrc`**, then **`./scripts/migrate_grafana_dashboards_to_serverless.sh`**. Converts drafts, ensures OTLP (or leaves bootstrap pipeline running), publishes to Kibana. **`git pull`**: run **`./scripts/sync_workshop_from_git.sh`** on the VM if scripts look old.

    ## Path B

    Clone **[github.com/poulsbopete/dashboard-alert-migration](https://github.com/poulsbopete/dashboard-alert-migration)** on your laptop, copy the **`export`** lines from Instruqt (**`grep`** in the challenge), paste into **Cursor’s terminal**, run **`grafana_to_elastic.py`**, then publish with **`kibana-dashboards`** or **`publish_grafana_drafts_kibana.py`**.
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

Use **Terminal** and **Elastic Serverless**. Pick **Path A** or **Path B** (or both).

---

## Path A — dashboard migration (Instruqt)

```bash
cd /root/workshop
source ~/.bashrc
./scripts/migrate_grafana_dashboards_to_serverless.sh
```

Open **Elastic Serverless → Dashboards** and look for titles ending in **`(Grafana import draft)`**.

**Path A vs Path B:** Track bootstrap usually starts **Alloy + OTLP emitters** before you open the lab. The migrate script now **skips restarting** that pipeline when it is already healthy (same steady data Path B publishes against). If you need a clean restart: **`WORKSHOP_FORCE_OTEL_RESTART=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh`**. Converter + publisher use **`/opt/workshop-venv/bin/python3`** when present so **`python3`** PATH issues do not break Path A.

*If charts look empty:* **`./scripts/check_workshop_otel_pipeline.sh`**, then **`./scripts/start_workshop_otel.sh`**, wait ~1 minute, refresh. **`otel_workshop_fleet.py`** emits **`entity_id`** (e.g. `shoplist-checkout`) and an **`operation_errors_total`** counter with **`reason`** so **entity / error** Grafana panels map to real OTLP metrics; other PromQL may still be a **Lens proxy**—see draft **Markdown**.

*Scripts out of date on the VM:* **`./scripts/sync_workshop_from_git.sh`** (needs **`git`** checkout under **`/root/workshop`**).

---

## Path B — Cursor on your laptop

Repo: **[https://github.com/poulsbopete/dashboard-alert-migration](https://github.com/poulsbopete/dashboard-alert-migration)**

1. **Clone** on your laptop:

```bash
git clone https://github.com/poulsbopete/dashboard-alert-migration.git
cd dashboard-alert-migration
```

2. **Instruqt Terminal** — print connection env to copy:

```bash
cd /root/workshop && source ~/.bashrc
grep -E '^export (KIBANA_URL|ES_URL|ES_USERNAME|ES_PASSWORD|ES_API_KEY|ES_DEPLOYMENT_ID|WORKSHOP_ROOT|WORKSHOP_OTLP_ENDPOINT|WORKSHOP_OTLP_AUTH_HEADER)=' ~/.bashrc
```

3. **Cursor** — open the **`dashboard-alert-migration`** folder, paste those **`export`** lines into the integrated terminal (not the chat).
4. In that repo, run the converter, then publish (skill or script):

```bash
mkdir -p build/elastic-dashboards
python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
```

Install **[Elastic Agent Skills](https://github.com/elastic/agent-skills)** **`kibana-dashboards`** if you want the skill to drive Kibana instead of the publish script. Optional: **`agent-skills/workshop-grafana-to-elastic/SKILL.md`**, **[dashboards API notes](../../docs/dashboards-api-getting-started.md)**.

*Before publishing from the laptop,* run **`./scripts/start_workshop_otel.sh`** once on the **Instruqt** VM so Lens has data (same as Path A troubleshooting).

**Optional — extra Grafana JSON:** download from **[grafana.com/grafana/dashboards](https://grafana.com/grafana/dashboards/)** (or export from Grafana), save under e.g. **`build/grafana-imports/`**, run **`grafana_to_elastic.py`** on those files into **`build/elastic-dashboards/`**, then publish. Respect licenses.

**Security:** do not paste API keys into the AI chat.

---

## Done

**Check** when **`build/elastic-dashboards/`** has **20** **`*-elastic-draft.json`** files from the bundled **`assets/grafana/`** samples.

- **Path A:** created under **`/root/workshop/build/…`**
- **Path B:** created under your clone after the **`grafana_to_elastic.py`** step
