# elastic-serverless-migration-lab (Instruqt track)

**Goal:** Train for **customer migrations from Grafana and Datadog to Elastic Observability Serverless**—dashboards, monitors
→ Kibana rules, **PromQL / metric-query** handoffs, and **OTLP** telemetry landing in Elastic’s **managed OTLP** so migrated
views are validated on **live** Serverless data.

**Instruqt** track (**two labs**) for a **high-volume migration spike**: **20** **Grafana** dashboards and **10**
**Datadog-style** dashboards (plus **4** monitor JSON files) → Elastic drafts on **Observability Serverless**, using
**CLI batch converters**, **[Elastic Agent Skills](https://github.com/elastic/agent-skills)**, and **Cursor** / AI for
query rewrite and Kibana API workflows.

The sandbox is **elastic/es3-api-v2**: **es3-api** provisions an **Observability Serverless** project per play, proxies
**Kibana** on **:8080**, and carries the workshop tree (Python venv + **assets/**). Telemetry follows the same idea as
**[elastic-autonomous-observability](https://play.instruqt.com/manage/elastic/tracks/elastic-autonomous-observability/sandbox)**:
**[Grafana Alloy](https://grafana.com/docs/alloy/latest/)** forwards OTLP to Elastic **[managed OTLP](https://www.elastic.co/docs/reference/opentelemetry/motlp)** when the project exposes an OTLP URL; otherwise the track **bulk-seeds** sample logs/metrics.

## Spike goals (migration outcomes)

- **Grafana customers → Serverless**: bulk **Grafana JSON** → Elastic dashboard drafts + **Dashboards API** publish; **PromQL**
  documented and refined toward **ES|QL** / native metrics where Elastic differs.
- **Datadog customers → Serverless**: **dashboard** and **monitor** JSON → Kibana drafts; **OTLP** with **Datadog-style**
  tags exercises the same ingest path those customers use when dual-shipping or cutting over.
- **Agent Skills**: upstream skills (`kibana-dashboards`, `kibana-alerting-rules`) plus workshop wrappers under
  `agent-skills/` so migrations are repeatable and automatable.

## Dashboards API (reference)

Lab 1 **Path A** publishes dashboards via the **Dashboards HTTP API** (`POST /api/dashboards?apiVersion=1`; see `tools/publish_grafana_drafts_kibana.py`), with a **saved-objects import** fallback per dashboard if needed. For deeper Lens work, use the **`kibana-dashboards`** skill. A concise guide lives in **[`docs/dashboards-api-getting-started.md`](docs/dashboards-api-getting-started.md)** (CRUD, headers, spaces, supported panels, links to Elastic docs).

## Layout

| Path | Purpose |
| --- | --- |
| `track.yml` / `config.yml` | Instruqt metadata + VM **`elastic/es3-api-v2`** (`es3-api` host) |
| `track_scripts/` | `setup-es3-api`: create Serverless project, nginx → Kibana :8080, venv + **Grafana Alloy** + OTLP emitter → mOTLP (or bulk seed fallback) |
| `01-lab-01-grafana-to-elastic/` | Lab 1: **20** Grafana → `build/elastic-dashboards/*-elastic-draft.json` |
| `02-lab-02-datadog-dashboards-alerts-to-elastic/` | Lab 2: **10** DD dashboards + **4** monitors → `build/elastic-datadog-dashboards/`, `build/elastic-alerts/` |
| `assets/grafana/` | **20** generated Grafana JSON exports (`scripts/generate_grafana_dashboards.py`) |
| `assets/datadog/dashboards/` | **10** Datadog-style dashboard JSON (`scripts/generate_datadog_dashboards.py`) |
| `assets/datadog/monitor-*.json` | **4** monitor samples |
| `tools/` | `grafana_to_elastic.py`, `publish_grafana_drafts_kibana.py`, `datadog_dashboard_to_elastic.py`, `datadog_to_elastic_alert.py` |
| `scripts/migrate_grafana_dashboards_to_serverless.sh` | **Path A:** convert 20 Grafana exports + **Dashboards API** publish (import fallback) |
| `assets/alloy/workshop.alloy` | Alloy: OTLP ingest + Prometheus self-scrape → **mOTLP** export ([Alloy OTLP→HTTP](https://grafana.com/docs/alloy/latest/reference/components/otelcol.exporter.otlphttp/)) |
| `tools/otel_workshop_emitter.py` | Sends OTLP **traces** + **metrics** to local Alloy (`127.0.0.1:4318`) |
| `tools/datadog_otel_to_elastic.py` / `scripts/send_datadog_otel.sh` | **Datadog-style** OTLP traces + metrics + **logs** → Alloy → Elastic **mOTLP** |
| `scripts/start_workshop_otel.sh` | Restart Alloy + emitter (**`WORKSHOP_OTLP_ENDPOINT`** + **`ES_API_KEY`** from `~/.bashrc`) |
| `scripts/check_workshop_otel_pipeline.sh` | Verify Alloy (**`:12345/metrics`**), ports **4317/4318**, emitters, log tails |
| `scripts/sync_workshop_from_git.sh` | **`git fetch` + `reset --hard origin/main`** so new scripts exist on old sandboxes |
| `tools/seed_workshop_telemetry.py` / `scripts/seed_workshop_telemetry.sh` | **Fallback:** bulk-index **logs**, **metrics**, **traces** (`*-workshop-default`) for Discover / ES|QL — see **Discover vs Observability UIs** below |
| `agent-skills/` | Workshop skills + [elastic/agent-skills](https://github.com/elastic/agent-skills) |
| `docs/dashboards-api-getting-started.md` | **Dashboards API** (`/api/dashboards?apiVersion=1`): CRUD, spaces, panel support — matches Lab 1 Path A primary publish path |

Loading / wait slides are defined in each **`assignment.md`** frontmatter (`notes:`), per Instruqt [loading experience](https://docs.instruqt.com/tracks/manage/loading-experience).

## Discover vs Observability UIs (bulk seed vs OTLP)

- **Bulk seed** (`seed_workshop_telemetry.py`) is for **Discover**, **Dashboards** (ES|QL/Lens), and teaching migrations. It writes **`logs-*`**, **`metrics-*`**, and **`traces-*`** data streams with ECS-like fields (`host.name`, `service.name`, span/transaction shapes).
- **Traces in Discover:** Serverless may only list **`logs-*`** and **`metrics-*`** by default. After seeding, **create a data view**: **Stack Management → Data views → Create** → index pattern **`traces-*`** (or **`traces-workshop-default`**) → **Time field** `@timestamp`.
- **Applications**, **Infrastructure**, and inventory-style **Hosts** views are built for **OpenTelemetry / APM** ingest (e.g. **`WORKSHOP_OTLP_ENDPOINT`** + **`./scripts/start_workshop_otel.sh`**) or **Elastic Agent** integrations. They are **not** fully populated by workshop bulk JSON alone — use OTLP for that parity.

## Facilitator prerequisites

- Learners need access to an **Observability Serverless** project (Elastic Cloud).
- Outbound **HTTPS** from the sandbox (for `git clone` fallback of the workshop repo if the bundle is not on disk).
- **Grafana Alloy → mOTLP:** for automatic OTLP export, **`elastic/es3-api-v2`** (or your `bin/es3-api.py` wrapper) should include a managed OTLP base URL in **`/tmp/project_results.json`** under **`endpoints.motlp`** (or **`otlp`** / **`otel`**) per region. If that field is absent, bootstrap uses **bulk seed** only until the learner sets **`WORKSHOP_OTLP_ENDPOINT`** from **Kibana → Add data → OpenTelemetry** and runs **`./scripts/start_workshop_otel.sh`**.

### Instruqt secrets

`config.yml` lists **`LLM_PROXY_PROD`** and **`ESS_CLOUD_API_KEY`**. **`ESS_CLOUD_API_KEY`** must be a valid **Elastic
Cloud API key** so `bin/es3-api.py` can create/delete the Serverless project. Values live in Instruqt **Team settings →
Secrets**.

## Local smoke test (optional)

```bash
python3 scripts/generate_grafana_dashboards.py
python3 scripts/generate_datadog_dashboards.py
python3 tools/grafana_to_elastic.py assets/grafana/01-overview.json --out-dir /tmp/g
python3 tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/01-service-overview.json --out-dir /tmp/d
python3 tools/datadog_to_elastic_alert.py assets/datadog/monitor-high-5xx-rate.json
```

## Publishing

```bash
instruqt track validate
instruqt track push
```
