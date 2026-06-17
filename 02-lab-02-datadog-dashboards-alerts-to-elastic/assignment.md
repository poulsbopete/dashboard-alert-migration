---
slug: lab-02-datadog-dashboards-alerts-to-elastic
id: berxl591tjk4
type: challenge
title: Lab 2 — Datadog dashboards & monitors → Elastic
teaser: One command migrates 10 Datadog-style dashboards and four monitors into Kibana.
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

    **10** Datadog dashboards (**`datadog-migrate`**) + **4** monitors (workshop rule publisher) → Kibana. Run **one command** in **Terminal** when the sandbox is ready.

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

When the sandbox is ready, open **Terminal** and run:

```bash
bash /root/workshop/scripts/migrate_datadog_dashboards_to_serverless.sh
```

That single script:

1. Starts (or reuses) the **OTLP** pipeline — Alloy → Elastic **mOTLP**
2. Runs **`datadog-migrate`** on **10** Datadog JSON files in **`assets/datadog/dashboards/`** (`--field-profile otel`, uploads to Kibana)
3. Converts **4** monitor JSON files under **`assets/datadog/`** and publishes **Rules** via **`publish_datadog_alert_drafts_kibana.py`** (imported **disabled**)

The script loads **`KIBANA_URL`** and **`ES_API_KEY`** from **`~/.bashrc`** — no **`cd`** or **`source`** needed first. Use the **absolute path** above so it works even if your shell left **`/root/workshop`**.

## Verify

Open the **Elastic Serverless** tab:

- **Dashboards** — migrated titles from the Datadog exports
- **Observability → Rules** — four workshop rules (imported **disabled**; enable in the UI to test)

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Empty charts | `bash /root/workshop/scripts/check_workshop_otel_pipeline.sh` then `bash /root/workshop/scripts/start_workshop_otel.sh` — wait ~1 min |
| Still empty after migrate | Re-run migrate after OTLP is healthy; `cd /root/workshop && ./scripts/sync_workshop_from_git.sh` if files are stale |
| Script not found | **Stop** → **Start** the track (wait for challenge to finish loading) |
| `latency_p95` compile warning | Other dashboards still upload; refresh workshop files and re-run migrate |

Optional pre-upload ES\|QL validation: `WORKSHOP_MIG_ES_VALIDATE=1 bash /root/workshop/scripts/migrate_datadog_dashboards_to_serverless.sh`

## Optional — integration dashboards

Migrate **eight** official Agent integration dashboards from [DataDog/integrations-core](https://github.com/DataDog/integrations-core) (see **`assets/datadog/integrations-core/ATTRIBUTION.md`**):

```bash
bash /root/workshop/scripts/migrate_datadog_integrations_to_serverless.sh
```

These use integration metric namespaces (`nginx.*`, `postgresql.*`, …), not the OTLP workshop fleet — expect many panels to need data mapping after migration.

## Done

**Check** passes when **`build/mig-datadog/yaml/`** has **10** `*.yaml` files, **`build/mig-datadog/migration_report.json`** exists, and **`build/elastic-alerts/`** has **4** `monitor-*-elastic.json` files.
