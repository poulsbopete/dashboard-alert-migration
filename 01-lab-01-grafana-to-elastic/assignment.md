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

    **20** Grafana JSON → **[mig-to-kbn](https://github.com/elastic/mig-to-kbn)** **`grafana-migrate`** → Kibana. Pick **Path A** (VM migrate script) or **Path B** (**Cursor**: repo includes **`mig-to-kbn/`**, Python **3.11+**, **`uv`**, paste **`export`** from VM **`~/.bashrc`**,     run the same CLI — OTLP already running from bootstrap).

    ***

    **While you wait:** [Vampire Clone](https://poulsbopete.github.io/Vampire-Clone/) (keyboard: arrows + space).

    <iframe src="https://poulsbopete.github.io/Vampire-Clone/" title="Vampire Clone" width="100%" height="440" style="border:0;border-radius:8px;max-width:100%;background:#0d0d0d;" allow="fullscreen" loading="lazy"></iframe>
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

Migration uses **[elastic/mig-to-kbn](https://github.com/elastic/mig-to-kbn)** (see [Grafana source](https://github.com/elastic/mig-to-kbn/blob/main/docs/sources/grafana.md) and [architecture](https://github.com/elastic/mig-to-kbn/blob/main/docs/architecture.md)): **`grafana-migrate`** with **`--native-promql`** for Observability Serverless.

Pick **Path A** or **Path B** (or both).

## Path A — dashboard migration (Instruqt)

```bash
cd /root/workshop
source ~/.bashrc
./scripts/migrate_grafana_dashboards_to_serverless.sh
```

Open **Elastic Serverless → Dashboards** — titles match your **Grafana** exports (uploaded by **`grafana-migrate`**, not the legacy “`(Grafana import draft)`” publisher).

*Charts empty?* **`./scripts/check_workshop_otel_pipeline.sh`**, **`./scripts/start_workshop_otel.sh`**, wait ~1 min. *Force OTLP restart:* **`WORKSHOP_FORCE_OTEL_RESTART=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh`**. *Old scripts?* **`./scripts/sync_workshop_from_git.sh`**.

## Path B — Cursor on your laptop

1. **Clone** this workshop repo **with** **`mig-to-kbn/`** (private: `gh repo clone elastic/mig-to-kbn` → `mig-to-kbn` in repo root). Install **[uv](https://docs.astral.sh/uv/)**, Python **≥ 3.11**, then: **`./scripts/install_workshop_mig_to_kbn.sh`** (or `uv venv` + `uv pip install -e ./mig-to-kbn[all]`).
2. On the **VM**, copy env: `cd /root/workshop && source ~/.bashrc` then
   `grep -E '^export (KIBANA_URL|ES_URL|ES_API_KEY|ES_USERNAME|ES_PASSWORD)=' ~/.bashrc`
3. In Cursor’s **integrated terminal**, paste those **`export`** lines, then run the same pipeline as Path A (from repo root), for example:

```bash
export MIG_TO_KBN_VENV="${MIG_TO_KBN_VENV:-.venv-mig}"
# after install_workshop_mig_to_kbn.sh or local venv:
"$MIG_TO_KBN_VENV/bin/grafana-migrate" \
  --source files --input-dir assets/grafana --output-dir build/mig-grafana \
  --native-promql --data-view 'metrics-*' --logs-index 'logs-*' \
  --es-url "$ES_URL" --es-api-key "$ES_API_KEY" --validate --upload \
  --kibana-url "$KIBANA_URL" --kibana-api-key "${KIBANA_API_KEY:-$ES_API_KEY}" --ensure-data-views
```

The sandbox **already runs Alloy + OTLP**. If charts look empty, on the VM run **`./scripts/check_workshop_otel_pipeline.sh`** or **`./scripts/start_workshop_otel.sh`**.

Optional: **[Elastic Agent Skills](https://github.com/elastic/agent-skills)** **`kibana-dashboards`**, **`agent-skills/workshop-grafana-to-elastic/SKILL.md`**. Do not paste API keys into the AI chat.

## Done

**Check** when **`build/mig-grafana/yaml/`** has **20** `*.yaml` files and **`build/mig-grafana/migration_report.json`** exists (Path A: **`/root/workshop/build/`**; Path B: your clone).
