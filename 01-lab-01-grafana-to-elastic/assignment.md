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

**`/root/workshop` missing?** Wait until the challenge has **fully loaded** (setup can take a few minutes). The track script creates **`/root/workshop`** early, then provisions Serverless and appends **`export KIBANA_URL=…`** to **`~/.bashrc`**. If the path is still missing or **`source ~/.bashrc`** has no Elastic vars, **Stop** the track and **Start** again (setup failed mid-way—often apt lock or Cloud API). Hosts: confirm **`ESS_CLOUD_API_KEY`** / **`PME_CLOUD_INSTRUQT_API_KEY`** in team secrets.

```bash
cd /root/workshop
source ~/.bashrc
./scripts/migrate_grafana_dashboards_to_serverless.sh
# Pre-upload live ES|QL validation against ES (optional): WORKSHOP_MIG_ES_VALIDATE=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh
```

Open **Elastic Serverless → Dashboards** — titles match your **Grafana** exports (uploaded by **`grafana-migrate`**, not the legacy “`(Grafana import draft)`” publisher). **Observability → Rules** lists **two** workshop rules (from **`assets/grafana/alerts/`** via **`--fetch-alerts`** and **`tools/publish_grafana_alert_drafts_kibana.py`**); they are created **disabled** until you enable them in the UI.

**Kibana-only upload (default Path A):** **`migrate_grafana_dashboards_to_serverless.sh`** passes **`--es-url ""`** and **`--es-api-key ""`** so **`ES_URL`** from **`~/.bashrc`** does not enable live validation (the **grafana-migrate** CLI otherwise defaults **`--es-url`** from that env var). **`--upload`** uses **Kibana** credentials only unless **`WORKSHOP_MIG_ES_VALIDATE=1`**. **`--esql-index`** is **`metrics-*`** with **`--data-view`**. **`--fetch-alerts`** reads **`assets/grafana/alerts/`** (see upstream file-mode [alert inputs](https://github.com/elastic/mig-to-kbn/blob/main/observability_migration/adapters/source/grafana/extract.py)); artifacts include **`build/mig-grafana/alert_comparison_results.json`**.

*Charts empty after upload?* **`./scripts/check_workshop_otel_pipeline.sh`**, **`./scripts/start_workshop_otel.sh`**, wait ~1 min, or optional **`setup_serverless_data.py`** (below). *Force OTLP restart:* **`WORKSHOP_FORCE_OTEL_RESTART=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh`**. *Old scripts?* **`./scripts/sync_workshop_from_git.sh`**.

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
