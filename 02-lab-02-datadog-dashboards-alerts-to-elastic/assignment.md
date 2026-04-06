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

    **10** Datadog dashboards (**`datadog-migrate`**) + **4** monitors (workshop rule publisher) → Kibana. Pick **Path A** or **Path B** (same **`mig-to-kbn`** + env pattern as Lab 1).

    **Live OTLP:** **`./scripts/send_datadog_otel.sh`** (or **`tools/datadog_otel_to_elastic.py`**) — same pipeline as Lab 1.

    **Next slide:** mini-game while Lab 2 environments load.
- type: text
  contents: |
    ## While you wait — **O11Y Survivors**

    [Open full screen](https://poulsbopete.github.io/Vampire-Clone/) if the embed is cramped. **Controls:** arrows or WASD, space, click to start.

    <div style="width:100%;max-width:100%;height:min(82vh,920px);min-height:520px;margin:0 auto;">
    <iframe src="https://poulsbopete.github.io/Vampire-Clone/" title="O11Y Survivors (Vampire Clone)" width="100%" height="100%" style="border:0;border-radius:10px;background:#0a0a0a;display:block;" allow="fullscreen" loading="lazy"></iframe>
    </div>
tabs:
- id: fsizfoyfjtag
  title: Terminal
  type: terminal
  hostname: es3-api
  workdir: /root
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

**10** dashboards via **[mig-to-kbn](https://github.com/elastic/mig-to-kbn)** **`datadog-migrate`** ([Datadog source](https://github.com/elastic/mig-to-kbn/blob/main/docs/sources/datadog.md), [architecture](https://github.com/elastic/mig-to-kbn/blob/main/docs/architecture.md)) with **`--field-profile otel`**; **4** monitors still use workshop **`datadog_to_elastic_alert.py`** → **`publish_datadog_alert_drafts_kibana.py`** (rules imported **disabled**, no connectors until you edit).

Pick **Path A** or **Path B** (or both).

## Path A — one script (same idea as Lab 1)

```bash
cd /root/workshop
source ~/.bashrc
./scripts/migrate_datadog_dashboards_to_serverless.sh
# Optional strict validation: WORKSHOP_MIG_ES_VALIDATE=1 ./scripts/migrate_datadog_dashboards_to_serverless.sh
```

Then **Dashboards** (migrated titles) and **Observability → Rules** in the Elastic Serverless tab.

**Kibana-only upload (default):** same as Lab 1 — **`datadog-migrate`** with **`--upload`** + **Kibana URL / API key** only. The migrate script passes **`--es-url ""`** and **`--es-api-key ""`** so **`ES_URL`** / **`ES_API_KEY`** from **`~/.bashrc`** do **not** turn on live ES|QL validation (the CLI otherwise reads those env vars by default). **`WORKSHOP_MIG_ES_VALIDATE=1`** restores **`--es-url`**, **`--es-api-key`**, and **`--validate`**. Workshop also passes **`--logs-index`**, **`--ensure-data-views`**, **`--fetch-monitors`**.

**Monitors under `monitors/`:** exports need **`id`** + **`type`** (API shape), or **`type`** + **`query`** (workshop samples); **`--fetch-monitors`** ingests them into **`monitor_migration_results.json`**.

**If `latency_p95` fails at compile:** **`kb-dashboard-cli`** may reject some Lens XY shapes (formula vs aggregation). Other dashboards still upload; track **mig-to-kbn** / **kb-dashboard-cli** updates or re-run after **`./scripts/sync_workshop_from_git.sh`**.

*Charts empty?* **`./scripts/check_workshop_otel_pipeline.sh`** then **`./scripts/start_workshop_otel.sh`**. *Old scripts?* **`./scripts/sync_workshop_from_git.sh`**.

**Optional — synthetic metrics from migrated Datadog YAML:** **`mig-to-kbn/scripts/setup_datadog_serverless_data.py`** discovers metrics from compiled dashboard YAML. Set **`DASHBOARD_YAML_DIR`** to **`/root/workshop/build/mig-datadog/yaml`** (Path B: **`$PWD/build/mig-datadog/yaml`**), plus **`ELASTICSEARCH_ENDPOINT`**, **`KEY`**, and optional **`DATA_HOURS`**, **`INTERVAL_SEC`**. See the script header and **`mig-to-kbn/docs/command-contract.md`**.

## Path B — Cursor on your laptop

1. Same **Lab 1 Path B** setup: workshop repo with **`mig-to-kbn/`**, **`uv`**, Python **≥ 3.11**, **`install_workshop_mig_to_kbn.sh`** (or equivalent venv).
2. On the **Instruqt** VM, copy credentials:

```bash
cd /root/workshop && source ~/.bashrc
grep -E '^export (KIBANA_URL|ES_URL|ES_API_KEY|ES_USERNAME|ES_PASSWORD)=' ~/.bashrc
```

3. In **Cursor**, **paste** those **`export`** lines, then mirror the migrate script: stage dashboards under **`build/mig-datadog-stage/`** (JSON in root, **`monitors/`** for monitor files), run **`datadog-migrate`**, then alerts:

```bash
rm -rf build/mig-datadog-stage && mkdir -p build/mig-datadog-stage/monitors
cp assets/datadog/dashboards/*.json build/mig-datadog-stage/
cp assets/datadog/monitor-*.json build/mig-datadog-stage/monitors/
mkdir -p build/elastic-alerts
export MIG_TO_KBN_VENV="${MIG_TO_KBN_VENV:-.venv-mig}"
"$MIG_TO_KBN_VENV/bin/datadog-migrate" \
  --source files --input-dir build/mig-datadog-stage --output-dir build/mig-datadog \
  --field-profile otel --data-view 'metrics-*' --logs-index 'logs-*' \
  --upload \
  --kibana-url "$KIBANA_URL" --kibana-api-key "${KIBANA_API_KEY:-$ES_API_KEY}" \
  --ensure-data-views --fetch-monitors
# Optional strict validation: add --es-url "$ES_URL" --es-api-key "$ES_API_KEY" before --upload (same as WORKSHOP_MIG_ES_VALIDATE=1).
for f in assets/datadog/monitor-*.json; do
  base="$(basename "$f" .json)"
  python3 tools/datadog_to_elastic_alert.py "$f" -o "build/elastic-alerts/${base}-elastic.json"
done
python3 tools/publish_datadog_alert_drafts_kibana.py --alerts-dir build/elastic-alerts
```

The sandbox **already runs Alloy + OTLP**. If Lens panels look empty, on the VM run **`./scripts/check_workshop_otel_pipeline.sh`** or **`./scripts/start_workshop_otel.sh`**.

Optional skills: **`workshop-datadog-dashboards-to-elastic`**, **`workshop-datadog-to-elastic-alerts`**, **`kibana-dashboards`**, **`kibana-alerting-rules`**. Do not paste API keys into the AI chat.

## Done

**Check** when **`build/mig-datadog/yaml/`** has **10** `*.yaml` files, **`build/mig-datadog/migration_report.json`** exists, and **`build/elastic-alerts/`** has **4** `monitor-*-elastic.json` (Path A: **`/root/workshop/build/`**; Path B: your clone).
