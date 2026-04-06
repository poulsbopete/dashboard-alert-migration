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

    **20** Grafana JSON → **[mig-to-kbn](https://github.com/elastic/mig-to-kbn)** **`grafana-migrate`** → Kibana. Pick **Path A** (VM migrate script) or **Path B** (**Cursor**: repo includes **`mig-to-kbn/`**, Python **3.11+**, **`uv`**, paste **`export`** from VM **`~/.bashrc`**, run the same CLI — OTLP already running from bootstrap).

    **Next slide:** mini-game while the sandbox finishes provisioning.
- type: text
  contents: |
    ## While you wait — **O11Y Survivors**

    [Open full screen](https://poulsbopete.github.io/Vampire-Clone/) if the embed is cramped. **Controls:** arrows or WASD, space, click to start.

    <div style="width:100%;max-width:100%;height:min(82vh,920px);min-height:520px;margin:0 auto;">
    <iframe src="https://poulsbopete.github.io/Vampire-Clone/" title="O11Y Survivors (Vampire Clone)" width="100%" height="100%" style="border:0;border-radius:10px;background:#0a0a0a;display:block;" allow="fullscreen" loading="lazy"></iframe>
    </div>
tabs:
- id: lypopaehfkah
  title: Terminal
  type: terminal
  hostname: es3-api
  workdir: /root
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

Migration uses **[elastic/mig-to-kbn](https://github.com/elastic/mig-to-kbn)** (see [Grafana source](https://github.com/elastic/mig-to-kbn/blob/main/docs/sources/grafana.md) and [architecture](https://github.com/elastic/mig-to-kbn/blob/main/docs/architecture.md)): **`grafana-migrate`** with **`--native-promql`** for Observability Serverless.

Pick **Path A** or **Path B** (or both).

## Path A — dashboard migration (Instruqt)

When the sandbox is ready, run:

```bash
cd /root/workshop && source ~/.bashrc && ./scripts/migrate_grafana_dashboards_to_serverless.sh
```

That one script converts **20** Grafana JSON under **`assets/grafana/`**, uploads dashboards to Kibana, fetches workshop alerts, and runs the alert publisher. Optional: pre-upload ES|QL checks against Elasticsearch — `WORKSHOP_MIG_ES_VALIDATE=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh`.

**Check:** **Elastic Serverless** tab → **Dashboards** (titles should match the Grafana exports). **Observability → Rules** → two workshop rules (start **disabled**; enable in the UI if you want them live).

**If something looks wrong**

- **`cd /root/workshop` fails** — wait for the challenge to finish loading; if it persists, **Stop** → **Start** the track (hosts: **`ESS_CLOUD_API_KEY`** in Instruqt secrets).
- **Empty charts** — `./scripts/check_workshop_otel_pipeline.sh` then `./scripts/start_workshop_otel.sh` and wait ~1 min; or `WORKSHOP_FORCE_OTEL_RESTART=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh`.
- **Stale workshop files** — `./scripts/sync_workshop_from_git.sh`.

### Path A — script defaults (optional)

Upload is **Kibana-only** by default (no pre-upload ES validation): the wrapper clears **`--es-url`** / **`--es-api-key`** so **`ES_URL`** in **`~/.bashrc`** does not enable validation unless you set **`WORKSHOP_MIG_ES_VALIDATE=1`**. The pipeline uses **`--native-promql`**, **`metrics-*`**, **`--fetch-alerts`** on **`assets/grafana/alerts/`**, and writes **`build/mig-grafana/`** (e.g. **`alert_comparison_results.json`**). More context: [Grafana source](https://github.com/elastic/mig-to-kbn/blob/main/docs/sources/grafana.md), [alert inputs](https://github.com/elastic/mig-to-kbn/blob/main/observability_migration/adapters/source/grafana/extract.py). For optional synthetic metrics demos, see **`setup_serverless_data.py`** at the bottom of this lab.

## Path B — Cursor on your laptop

1. **Clone** this workshop repo (**`mig-to-kbn/`** is included in git). Install **[uv](https://docs.astral.sh/uv/)**, Python **≥ 3.11**, then: **`./scripts/install_workshop_mig_to_kbn.sh`** (or `uv venv` + `uv pip install -e ./mig-to-kbn[all]`).
2. On the **VM**, copy env: `cd /root/workshop && source ~/.bashrc` then
   `grep -E '^export (KIBANA_URL|ES_URL|ES_API_KEY|ES_USERNAME|ES_PASSWORD)=' ~/.bashrc`
3. In Cursor’s **integrated terminal**, paste those **`export`** lines, then run the same pipeline as Path A (from repo root), for example:

```bash
export MIG_TO_KBN_VENV="${MIG_TO_KBN_VENV:-.venv-mig}"
# after install_workshop_mig_to_kbn.sh or local venv:
"$MIG_TO_KBN_VENV/bin/grafana-migrate" \
  --source files --input-dir assets/grafana --output-dir build/mig-grafana \
  --native-promql --data-view 'metrics-*' --esql-index 'metrics-*' --logs-index 'logs-*' \
  --upload \
  --kibana-url "$KIBANA_URL" --kibana-api-key "${KIBANA_API_KEY:-$ES_API_KEY}" --ensure-data-views \
  --fetch-alerts

python3 tools/publish_grafana_alert_drafts_kibana.py --comparison build/mig-grafana/alert_comparison_results.json
```

Same as Path A default (no **`--es-url`** / **`--validate`**). To mirror **`WORKSHOP_MIG_ES_VALIDATE=1`**, add **`--es-url`** + **`--es-api-key`** before **`--upload`** (validation auto-enables with **`--upload`** + **`--es-url`**):

```bash
"$MIG_TO_KBN_VENV/bin/grafana-migrate" \
  --source files --input-dir assets/grafana --output-dir build/mig-grafana \
  --native-promql --data-view 'metrics-*' --esql-index 'metrics-*' --logs-index 'logs-*' \
  --es-url "$ES_URL" --es-api-key "$ES_API_KEY" \
  --upload \
  --kibana-url "$KIBANA_URL" --kibana-api-key "${KIBANA_API_KEY:-$ES_API_KEY}" --ensure-data-views \
  --fetch-alerts

python3 tools/publish_grafana_alert_drafts_kibana.py --comparison build/mig-grafana/alert_comparison_results.json
```

The sandbox **already runs Alloy + OTLP**. If charts look empty, on the VM run **`./scripts/check_workshop_otel_pipeline.sh`** or **`./scripts/start_workshop_otel.sh`**.

**Optional — synthetic metrics aligned to migrated YAML (feedback / demos):** upstream **mig-to-kbn** includes **`mig-to-kbn/scripts/setup_serverless_data.py`**. It can read **`DASHBOARD_YAML_DIR`** (your **`build/mig-grafana/yaml/`**), extract metric names from the generated YAML, and bulk-ingest **Prometheus-style** synthetic series into Elasticsearch so native **PromQL** panels have material to query. It expects **`ELASTICSEARCH_ENDPOINT`** and **`KEY`** (API key), not **`ES_URL`** / **`ES_API_KEY`**. Example on the VM after **`source ~/.bashrc`** and a successful migrate:

```bash
cd /root/workshop
export ELASTICSEARCH_ENDPOINT="${ES_URL%/}"
export KEY="${ES_API_KEY}"
export DASHBOARD_YAML_DIR="${PWD}/build/mig-grafana/yaml"
export DATA_HOURS=6   # shorter run; default upstream is longer
# If preflight lists metrics the generator does not yet emit: export SKIP_PREFLIGHT=1  # use sparingly
python3 mig-to-kbn/scripts/setup_serverless_data.py
```

Upstream defaults target **`metrics-prometheus-default`** (see script header). Your migrated dashboards may use **`metrics-*`** data views; adjust expectations or extend the script if index names diverge. See **`mig-to-kbn/docs/command-contract.md`** and **`mig-to-kbn/AGENTS.md`**.

Optional: **[Elastic Agent Skills](https://github.com/elastic/agent-skills)** **`kibana-dashboards`**, **`agent-skills/workshop-grafana-to-elastic/SKILL.md`**. Do not paste API keys into the AI chat.

## Done

**Check** when **`build/mig-grafana/yaml/`** has **20** `*.yaml` files, **`build/mig-grafana/migration_report.json`** exists, and **`build/mig-grafana/alert_comparison_results.json`** lists the workshop Grafana rules (Path A: **`/root/workshop/build/`**; Path B: your clone).
