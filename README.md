# elastic-serverless-migration-lab (Instruqt track)

**Source repo:** [github.com/poulsbopete/dashboard-alert-migration](https://github.com/poulsbopete/dashboard-alert-migration)

**Goal:** Train for **customer migrations from Grafana and Datadog to Elastic Observability Serverless**—dashboards, monitors
→ Kibana rules, **PromQL / metric-query** handoffs, and **OTLP** telemetry landing in Elastic’s **managed OTLP** so migrated
views are validated on **live** Serverless data.

**Instruqt** track (**two labs**) for a **high-volume migration spike**: **20** **Grafana** dashboards and **10**
**Datadog-style** dashboards (plus **4** monitor JSON files) → Elastic drafts on **Observability Serverless**, using
**CLI batch converters**, **[Elastic Agent Skills](https://github.com/elastic/agent-skills)**, and **Cursor** / AI for
query rewrite and Kibana API workflows.

## Quick start on the workshop VM (`es3-api`)

```bash
cd /root/workshop
source ~/.bashrc
```

| Lab | One-liner (Terminal) |
| --- | --- |
| **Lab 1 — Grafana** | `./scripts/migrate_grafana_dashboards_to_serverless.sh` → opens **Elastic Serverless** → Dashboards (titles end in `(Grafana import draft)`). |
| **Lab 2 — Datadog dashboards** | `./scripts/migrate_datadog_dashboards_to_serverless.sh` → same tab → `(Datadog dashboard import draft)`. |

**Path B (laptop + Cursor):** clone the repo above, copy `export` lines from `~/.bashrc` on the VM (`grep` patterns are in Lab 1 `assignment.md`), then run the same `tools/*.py` steps locally. **Dashboards** only appear in Kibana after **`publish_grafana_drafts_kibana.py`** (included in the migrate scripts).

**Refresh the repo on an existing sandbox** (same VM, no new play):

```bash
cd /root/workshop && source ~/.bashrc && ./scripts/sync_workshop_from_git.sh
```

Uses **`git fetch`** + **`reset --hard origin/main`** (or **`WORKSHOP_GIT_REF`**) so shallow clones stay aligned with GitHub.

The sandbox is **elastic/es3-api-v2**: **es3-api** provisions an **Observability Serverless** project per play, proxies
**Kibana** on **:8080**, and carries the workshop tree (Python venv + **assets/**). Telemetry follows the same idea as
**[elastic-autonomous-observability](https://play.instruqt.com/manage/elastic/tracks/elastic-autonomous-observability/sandbox)**:
**[Grafana Alloy](https://grafana.com/docs/alloy/latest/)** receives OTLP from the workshop **OpenTelemetry Python SDK** emitters and forwards to Elastic **[managed OTLP](https://www.elastic.co/docs/reference/opentelemetry/motlp)**. Workshop telemetry is **real OTLP ingest**, not bulk-indexed JSON (legacy bulk seed exists only if **`WORKSHOP_ALLOW_BULK_SEED=1`** on bootstrap).

## Spike goals (migration outcomes)

- **Grafana customers → Serverless**: bulk **Grafana JSON** → Elastic dashboard drafts + **Dashboards API** publish; **PromQL**
  documented and refined toward **ES|QL** / native metrics where Elastic differs.
- **Datadog customers → Serverless**: **dashboard** and **monitor** JSON → Kibana drafts; **OTLP** with **Datadog-style**
  tags exercises the same ingest path those customers use when dual-shipping or cutting over.
- **Agent Skills**: upstream skills (`kibana-dashboards`, `kibana-alerting-rules`) plus workshop wrappers under
  `agent-skills/` so migrations are repeatable and automatable.

## Dashboards API (reference)

**`tools/publish_grafana_drafts_kibana.py`** publishes **both** Grafana- and Datadog-derived **`*-elastic-draft.json`** files via **`POST /api/dashboards?apiVersion=1`**, with a **saved-objects import** fallback. It reads **`migration.promql`** (Grafana) or **`migration.datadog_query`** (Datadog). Point **`--drafts-dir`** at **`build/elastic-dashboards`** or **`build/elastic-datadog-dashboards`**.

Lab 1 **Path A** and **`migrate_datadog_dashboards_to_serverless.sh`** call this publisher after OTLP is up. For deeper Lens work, use the **`kibana-dashboards`** skill. A concise guide lives in **[`docs/dashboards-api-getting-started.md`](docs/dashboards-api-getting-started.md)** (CRUD, headers, spaces, supported panels, links to Elastic docs).

## Layout

| Path | Purpose |
| --- | --- |
| `track.yml` / `config.yml` | Instruqt metadata + VM **`elastic/es3-api-v2`** (`es3-api` host) |
| `track_scripts/` | `setup-es3-api`: create Serverless project, nginx → Kibana :8080, venv + **Grafana Alloy** + OTLP SDK emitters → mOTLP (optional legacy bulk seed if **`WORKSHOP_ALLOW_BULK_SEED=1`**) |
| `01-lab-01-grafana-to-elastic/` | Lab 1: **20** Grafana → `build/elastic-dashboards/*-elastic-draft.json` |
| `02-lab-02-datadog-dashboards-alerts-to-elastic/` | Lab 2: **10** DD dashboards + **4** monitors → `build/elastic-datadog-dashboards/`, `build/elastic-alerts/` |
| `assets/grafana/` | **20** generated Grafana JSON exports (`scripts/generate_grafana_dashboards.py`) |
| `assets/datadog/dashboards/` | **10** Datadog-style dashboard JSON (`scripts/generate_datadog_dashboards.py`) |
| `assets/datadog/monitor-*.json` | **4** monitor samples |
| `tools/` | `grafana_to_elastic.py`, `publish_grafana_drafts_kibana.py`, `datadog_dashboard_to_elastic.py`, `datadog_to_elastic_alert.py` |
| `scripts/migrate_grafana_dashboards_to_serverless.sh` | **Lab 1 Path A:** Grafana → drafts + OTLP + **`publish_grafana_drafts_kibana.py`** |
| `scripts/migrate_datadog_dashboards_to_serverless.sh` | **Lab 2:** Datadog dashboards → drafts + OTLP + publish **`build/elastic-datadog-dashboards`** to Kibana |
| `assets/alloy/workshop.alloy` | Alloy: OTLP ingest + Prometheus self-scrape → **mOTLP** export ([Alloy OTLP→HTTP](https://grafana.com/docs/alloy/latest/reference/components/otelcol.exporter.otlphttp/)) |
| `tools/otel_workshop_fleet.py` | **Six** OTLP worker subprocesses (distinct **service.name** + **host.name**) + **`system.*`**-style utilization metrics → Alloy; plus **`datadog_otel_to_elastic.py`** (**shopist-checkout** on **`workshop-node-07`**) for **Applications / Infrastructure / Hosts** variety |
| `tools/otel_workshop_emitter.py` | Legacy single-service OTLP emitter (not started by default; use fleet) |
| `tools/datadog_otel_to_elastic.py` / `scripts/send_datadog_otel.sh` | **Datadog-style** OTLP traces + metrics + **logs** → Alloy → Elastic **mOTLP** |
| `scripts/start_workshop_otel.sh` | Restart Alloy + emitter; **`WORKSHOP_OTLP_ENDPOINT`** from `~/.bashrc` or **derived** from **`ES_URL`** (`.es.`→`.ingest.`) / **`KIBANA_URL`** (`.kb.`→`.ingest.`) on Serverless |
| `scripts/check_workshop_otel_pipeline.sh` | Verify Alloy (**`:12345/metrics`**), ports **4317/4318**, emitters, log tails |
| `scripts/sync_workshop_from_git.sh` | **`git fetch` + `reset --hard origin/main`** so new scripts exist on old sandboxes |
| `tools/seed_workshop_telemetry.py` / `scripts/seed_workshop_telemetry.sh` | **Legacy / opt-in:** direct-to-ES bulk docs (`*-workshop-default`) — only when **`WORKSHOP_ALLOW_BULK_SEED=1`** on bootstrap; not the default workshop path |
| `agent-skills/` | Workshop skills + [elastic/agent-skills](https://github.com/elastic/agent-skills) |
| `docs/dashboards-api-getting-started.md` | **Dashboards API** (`/api/dashboards?apiVersion=1`): CRUD, spaces, panel support — matches Lab 1 Path A primary publish path |

Loading / wait slides are defined in each **`assignment.md`** frontmatter (`notes:`), per Instruqt [loading experience](https://docs.instruqt.com/tracks/manage/loading-experience).

## Discover vs Observability UIs (OTLP default)

- **Default path:** **OpenTelemetry** (Python SDK → Alloy → **mOTLP**) populates **logs-***, **metrics-***, **traces-*** data the same way customer OTLP would. **`publish_grafana_drafts_kibana.py`** probes **`logs-*`** / **`metrics-*`** first so Lens works against OTLP-backed streams.
- **Traces in Discover:** create a data view if needed: **Stack Management → Data views → Create** → **`traces-*`** → **`@timestamp`**.
- **Applications**, **Infrastructure**, and **Hosts** align with **OTLP** / APM ingest — run **`./scripts/start_workshop_otel.sh`** if Alloy is not up.
- **Legacy bulk seed** (`seed_workshop_telemetry.py`) bypasses OTLP; enable only via **`WORKSHOP_ALLOW_BULK_SEED=1`** on host bootstrap for special facilitator cases.

## Facilitator prerequisites

- Learners need access to an **Observability Serverless** project (Elastic Cloud).
- Outbound **HTTPS** from the sandbox (for `git clone` fallback of the workshop repo if the bundle is not on disk).
- **Grafana Alloy → mOTLP:** **`elastic/es3-api-v2`** (or **`bin/es3-api.py`**) may put a managed OTLP base URL in **`/tmp/project_results.json`**. **Each play’s host differs.** Setup also **derives** mOTLP from **`ES_URL`** (`.es.`→`.ingest.`) or **`KIBANA_URL`** (`.kb.`→`.ingest.`). Learners run **`./scripts/start_workshop_otel.sh`** if Alloy did not start. Legacy bulk seed requires **`WORKSHOP_ALLOW_BULK_SEED=1`**.

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

After **git commit**, push **both** GitHub and Instruqt (maintainers):

```bash
./scripts/push_git_and_instruqt.sh
```

Or manually:

```bash
git push origin HEAD
instruqt track validate
instruqt track push
```
