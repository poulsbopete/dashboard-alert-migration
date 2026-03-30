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
| **Lab 2 — Datadog** | `./scripts/migrate_datadog_dashboards_to_serverless.sh` → Dashboards **`(Datadog dashboard import draft)`** + **Rules** (imports disabled until you edit). |

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

## Grafana and Datadog: how conversion to ES|QL works

Migrations here are **two stages**. Learners should understand both: **(1)** how source queries are **captured** in draft JSON, and **(2)** how the **publisher** turns each panel into **Lens** panels whose **executable** language is **ES|QL** against **`logs-*` / `metrics-*` / `traces-*`**. Original **PromQL** and **Datadog `q`** strings are **not** run inside Elasticsearch; they are preserved in panel **descriptions** and in **`migration.*`** for traceability and for you to refine in Kibana or Cursor.

### Stage 1 — Converters (source JSON → `*-elastic-draft.json`)

| Script | What it reads | What it writes per panel |
| --- | --- | --- |
| **`tools/grafana_to_elastic.py`** | Grafana dashboard JSON: walks **`panels`** (and nested layout) and collects **`targets[].expr`** (PromQL). | **`migration.promql`**, **`migration.legend`**, plus human **`description`** / **`note`** (lightweight PromQL→ES|QL *hints* in `promql_to_esql_note()` — not auto-generated queries). |
| **`tools/datadog_dashboard_to_elastic.py`** | Datadog export JSON: walks **`widgets[].definition`** for **`timeseries`**, **`query_value`**, and **`toplist`** widgets and collects each **`requests[].q`**. | **`migration.datadog_query`**, **`description`**, **`note`** from `query_to_note()` (logs vs trace vs metric narrative). |
| **`tools/datadog_to_elastic_alert.py`** | Monitor JSON | Rule drafts for **`publish_datadog_alert_drafts_kibana.py`** (separate from dashboard ES|QL). |

Draft files are **Kibana-oriented shapes**: **`title`**, **`tags`**, **`panels[]`** with **`type: lens`** placeholders; the **real** chart definition is applied in Stage 2.

### Stage 2 — Publisher (`tools/publish_grafana_drafts_kibana.py`)

Called with **`--drafts-dir`** pointing at **`build/elastic-dashboards`** or **`build/elastic-datadog-dashboards`**. It builds a **Dashboards API** payload: **Markdown** canvas (source queries as documentation) + **Lens** panels with **inline ES|QL**.

**1) Resolve index pattern (`FROM …`)**  
The publisher must pick a **`FROM`** clause that **verifies** on Serverless (unions of logs+metrics can fail ES|QL checks if columns differ). It tries, in order: optional **`WORKSHOP_ESQL_FROM`** override; then **`logs-*`**, **`metrics-*`**, workshop streams, unions, and finally **`traces-*`**. First probe that succeeds drives **`_from_capabilities()`** (which of logs / metrics / traces are in play).

**2) Classify each panel**  
For every panel, it builds a string from **`migration.promql`** *or* **`migration.datadog_query`** plus the **panel title**, then **`_classify_grafana_panel()`** assigns a **category** via regex (same function for both sources). Datadog-style prefixes are handled first, e.g. **`avg:system.cpu…`**, **`avg:system.mem…`**, **`kubernetes.`**, **`system.disk`**, **`system.io`**, **`trace.`**, **`logs(`**. Then PromQL-style patterns (**`http_requests_total`**, **`histogram_quantile`**, **`entity_id`**, **`process_cpu`**, etc.). Categories include **`cpu`**, **`memory`**, **`http`**, **`latency`**, **`errors`**, **`storage`**, **`k8s`**, **`network`**, **`db`**, **`scrape`**, **`go_runtime`**, **`operation_errors`**, **`by_entity`**, **`generic`**, and related variants.

**3) Map category → Lens ES|QL**  
**`_panel_esql_spec()`** returns a **viz** (line, area, bar, metric) and one **ES|QL** string per panel. Examples aligned with **workshop OTLP** ( **`otel_workshop_fleet.py`** ):

| Category | Typical workshop mapping (simplified) |
| --- | --- |
| **cpu** | **`AVG(\`system.cpu.utilization\`)`** by time bucket + **`service.name`**. |
| **memory** | **`AVG(\`system.memory.utilization\`)`** by bucket + service. |
| **http** | **`SUM(\`http.server.request.count\`)`** by **`service.name`** or optional HTTP status column (**`WORKSHOP_ESQL_HTTP_STATUS_COLUMN`**). |
| **latency** | **`AVG(\`http.server.request.duration\`)`** on **metrics-***, or **`AVG(transaction.duration.us)`** on **traces-*** when logs are not mixed in. |
| **operation_errors** | **`SUM(\`operation_errors_total\`)`** by **`attributes.reason`** / **`attributes.entity_id`**. |
| **storage** (disk-style DD/Grafana) | No real disk I/O in the fleet → **rotating proxies**: CPU, memory, or HTTP request activity by bucket + service. |
| **k8s** | **metrics-***: requests **`SUM(\`http.server.request.count\`)`** by **`host.name`**; else logs by host. |
| **generic** | Rotates **route bars**, **CPU lines**, **volume** line/area by **`panel_index`**. |

Time series use **`BUCKET(\`@timestamp\`, <duration>)`** where **`<duration>`** comes from **`WORKSHOP_ESQL_BUCKET_DURATION`** (default **`1 hour`**). Integer-only **`BUCKET(datetime, n)`** is avoided because current Serverless ES|QL expects **four** arguments for that form; the **duration** two-argument form matches the dashboard time picker.

**4) Padding and Datadog-specific behavior**  
**Grafana** drafts are often short; **`WORKSHOP_MIN_LENS_PANELS`** / **`WORKSHOP_MAX_LENS_PANELS`** pad or cap how many Lens slots are emitted. **Datadog** imports use tag **`datadog-dashboard-import`**: by default **`WORKSHOP_DD_PAD_LENS`** is **off**, so only **real** widgets become panels (no duplicate filler rows). Set **`WORKSHOP_DD_PAD_LENS=1`** to pad like Grafana.

**5) Fallbacks**  
**`WORKSHOP_SIMPLE_LENS=1`**, **`WORKSHOP_DISABLE_LENS=1`**, and saved-object import paths exist for debugging; see the script module docstring.

### Publisher environment variables (quick reference)

| Variable | Role |
| --- | --- |
| **`WORKSHOP_ESQL_FROM`** | Force **`FROM`** for probes and panels. |
| **`WORKSHOP_ESQL_TIME_FIELD`** | Time field for **`BUCKET()`** (default **`@timestamp`**). |
| **`WORKSHOP_ESQL_BUCKET_DURATION`** | e.g. **`1 hour`**, **`15 minutes`**. |
| **`WORKSHOP_ESQL_SERVICE_NAME_COLUMN`** / **`WORKSHOP_ESQL_HTTP_ROUTE_COLUMN`** / **`WORKSHOP_ESQL_HTTP_STATUS_COLUMN`** | Adjust field names if your mapping differs. |
| **`WORKSHOP_MIN_LENS_PANELS`** / **`WORKSHOP_MAX_LENS_PANELS`** | Panel count for Grafana-style padding / caps. |
| **`WORKSHOP_DD_PAD_LENS`** | **`1`** = pad Datadog dashboards like Grafana. |

Implementation details live in **`tools/publish_grafana_drafts_kibana.py`** (`_classify_grafana_panel`, `_panel_esql_spec`, `_expand_draft_panels_for_lens`).

### Grafana Cloud app dashboards (`dashboard.grafana.app/v2beta1`) with Elasticsearch datasource

Grafana **Kubernetes / Elasticsearch** exports (app platform JSON, **not** classic `panels[].targets[].expr` PromQL) are **not** handled by **`grafana_to_elastic.py`**. Use **`tools/publish_grafana_es_app_dashboard.py`** instead: it walks **`spec.layout`** → **`spec.elements`**, reads each panel’s **Elasticsearch** `DataQuery` (Lucene `query`, `bucketAggs`, `metrics`), and builds **Lens** panels with **ES|QL** for **`POST /api/dashboards?apiVersion=1`**.

1. Save the dashboard JSON to a file (e.g. **`prom-demo.app-v2.json`**).
2. Set **`KIBANA_URL`** and **`ES_API_KEY`** (same as the workshop / Serverless project).
3. Run from the **repo root**:

```bash
python3 tools/publish_grafana_es_app_dashboard.py --input ./prom-demo.app-v2.json
```

Optional: **`--title "…"`** to override the Kibana title; **`GRAFANA_IMPORT_FROM=metrics-*`** (default) or **`logs-*`** if panels are log-based. **`WORKSHOP_ESQL_BUCKET_DURATION`** is honored via the shared publisher helpers.

**Caveats:** translation is **best-effort** (simple `field:value AND …` Lucene, common aggregations). Field names must exist in your **`metrics-*` / `logs-*`** mapping. Panels with **multiple** Elasticsearch queries only use the **first** query. A tiny fixture for smoke tests lives at **`assets/grafana/fixtures/grafana-app-v2-elasticsearch-min.json`** (`--dry-run` prints panel count).

This script **cannot** run against your Serverless project from CI without your credentials; execute it **locally** or on a host where **`export`** lines from Kibana/ES are configured.

## Dashboards API (reference)

**`tools/publish_grafana_drafts_kibana.py`** publishes **both** Grafana- and Datadog-derived **`*-elastic-draft.json`** files via **`POST /api/dashboards?apiVersion=1`**, with a **saved-objects import** fallback. It reads **`migration.promql`** (Grafana) or **`migration.datadog_query`** (Datadog). Point **`--drafts-dir`** at **`build/elastic-dashboards`** or **`build/elastic-datadog-dashboards`**. **Datadog** imports default to **no** padded “Workshop insights” rows; set **`WORKSHOP_DD_PAD_LENS=1`** to match Grafana-style **`WORKSHOP_MIN_LENS_PANELS`**. Datadog disk-style queries map to **OTEL CPU / memory / HTTP** proxies (workshop fleet has no host disk I/O metrics). If Lens reports **Unknown column** on HTTP panels, set **`WORKSHOP_ESQL_HTTP_STATUS_COLUMN`** or rely on the default **request volume by `service.name`**. **Line charts** use **multi-series** by **`service.name`** and **`WORKSHOP_ESQL_BUCKET_DURATION`**. See **[Grafana and Datadog: how conversion to ES|QL works](#grafana-and-datadog-how-conversion-to-esql-works)** above for the full pipeline.

Lab 1 **Path A** and **`migrate_datadog_dashboards_to_serverless.sh`** call this publisher after OTLP is up. For deeper Lens work, use the **`kibana-dashboards`** skill. **[`docs/dashboards-api-getting-started.md`](docs/dashboards-api-getting-started.md)** covers CRUD, headers, spaces, and supported panels.

**Dynamic dashboard from live OTLP:** **`tools/generate_dynamic_o11y_dashboard.py`** (wrapper **`./scripts/generate_dynamic_o11y_dashboard.sh`**) runs **`POST /_query`** probes on **`logs-*` / `metrics-*`** (same family as **`publish_grafana_drafts_kibana.py`**), picks a working **`FROM`** clause, then **POST**s a single Kibana dashboard with **ES|QL Lens** panels (volume, CPU, HTTP, logs, traces when present). Requires **`ES_URL`** + **`KIBANA_URL`** and **`ES_API_KEY`**. An Elastic **MCP workflow** for discovery + summary lives at **`workflows/dynamic-observability-dashboard.yaml`** (**`discover_o11y_data`** → **`get_data_summary`** → optional **`esql_query`** smoke checks); run the Python tool on the lab VM (or laptop with exports) to materialize the dashboard.

## Layout

| Path | Purpose |
| --- | --- |
| `track.yml` / `config.yml` | Instruqt metadata + VM **`elastic/es3-api-v2`** (`es3-api` host) |
| `track_scripts/` | `setup-es3-api`: create Serverless project, nginx → Kibana :8080, venv + **Grafana Alloy** + OTLP SDK emitters → mOTLP (optional legacy bulk seed if **`WORKSHOP_ALLOW_BULK_SEED=1`**) |
| `01-lab-01-grafana-to-elastic/` | Lab 1: **20** Grafana → `build/elastic-dashboards/*-elastic-draft.json` |
| `02-lab-02-datadog-dashboards-alerts-to-elastic/` | Lab 2: **10** DD dashboards + **4** monitors → `build/elastic-datadog-dashboards/`, `build/elastic-alerts/` |
| `assets/grafana/` | **20** generated Grafana JSON exports (`scripts/generate_grafana_dashboards.py`) |
| `assets/datadog/dashboards/` | **10** Datadog-style dashboard JSON (**12** timeseries widgets each; regenerate with **`scripts/generate_datadog_dashboards.py`**) |
| `assets/datadog/monitor-*.json` | **4** monitor samples |
| `tools/` | `grafana_to_elastic.py`, `publish_grafana_drafts_kibana.py`, **`generate_dynamic_o11y_dashboard.py`** (probe OTLP streams → one Lens dashboard), **`publish_grafana_es_app_dashboard.py`** (Grafana app + Elasticsearch → ES|QL), `datadog_dashboard_to_elastic.py`, `datadog_to_elastic_alert.py` |
| `workflows/` | **`dynamic-observability-dashboard.yaml`** — MCP-oriented steps: discovery, **`get_data_summary`**, ES|QL smoke; pair with **`generate_dynamic_o11y_dashboard.py`** to create the dashboard |
| `scripts/migrate_grafana_dashboards_to_serverless.sh` | **Lab 1 Path A:** Grafana → drafts + OTLP + **`publish_grafana_drafts_kibana.py`** |
| `scripts/migrate_datadog_dashboards_to_serverless.sh` | **Lab 2:** dashboards + monitors → drafts + OTLP + publish Dashboards + **Rules** (`publish_datadog_alert_drafts_kibana.py`) |
| `tools/publish_datadog_alert_drafts_kibana.py` | POST/PUT **`monitor-*-elastic.json`** rule drafts to **`/api/alerting/rule/{id}`** |
| `assets/alloy/workshop.alloy` | Alloy: OTLP ingest + Prometheus self-scrape → **mOTLP** export ([Alloy OTLP→HTTP](https://grafana.com/docs/alloy/latest/reference/components/otelcol.exporter.otlphttp/)) |
| `tools/otel_workshop_fleet.py` | **Six** OTLP worker subprocesses (distinct **service.name** + **host.name**) + **`system.*`**-style utilization metrics → Alloy; plus **`datadog_otel_to_elastic.py`** (**shopist-checkout** on **`workshop-node-07`**) for **Applications / Infrastructure / Hosts** variety |
| `tools/otel_workshop_emitter.py` | Legacy single-service OTLP emitter (not started by default; use fleet) |
| `tools/datadog_otel_to_elastic.py` / `scripts/send_datadog_otel.sh` | **Datadog-style** OTLP traces + metrics + **logs** → Alloy → Elastic **mOTLP** |
| `scripts/start_workshop_otel.sh` | Restart Alloy + emitter; **`WORKSHOP_OTLP_ENDPOINT`** from `~/.bashrc` or **derived** from **`ES_URL`** (`.es.`→`.ingest.`) / **`KIBANA_URL`** (`.kb.`→`.ingest.`) on Serverless |
| `scripts/check_workshop_otel_pipeline.sh` | Verify Alloy (**`:12345/metrics`**), ports **4317/4318**, emitters, log tails |
| `scripts/sync_workshop_from_git.sh` | **`git fetch` + `reset --hard origin/main`** so new scripts exist on old sandboxes |
| `scripts/push_git_and_instruqt.sh` | Maintainer: **`git push`** + **`instruqt track validate/push`** after a commit |
| `tools/seed_workshop_telemetry.py` / `scripts/seed_workshop_telemetry.sh` | **Legacy / opt-in:** direct-to-ES bulk docs (`*-workshop-default`); **`--metrics-time-series`** backfills a regular metric grid for Discover TS; not the default OTLP path |
| `agent-skills/` | Workshop skills + [elastic/agent-skills](https://github.com/elastic/agent-skills) |
| `docs/dashboards-api-getting-started.md` | **Dashboards API** (`/api/dashboards?apiVersion=1`): CRUD, spaces, panel support — matches Lab 1 Path A primary publish path |

Loading / wait slides are defined in each **`assignment.md`** frontmatter (`notes:`), per Instruqt [loading experience](https://docs.instruqt.com/tracks/manage/loading-experience).

## Discover vs Observability UIs (OTLP default)

- **Default path:** **OpenTelemetry** (Python SDK → Alloy → **mOTLP**) populates **logs-***, **metrics-***, **traces-*** data the same way customer OTLP would. **`publish_grafana_drafts_kibana.py`** probes **`logs-*`** / **`metrics-*`** first so Lens works against OTLP-backed streams.
- **“Nothing in metrics-*” in Discover:** the **Observability → Discover** search bar often ships a **narrow** pattern (e.g. `metrics-*.otel-*`, `metrics-apm*`) and **does not include** the broad wildcard **`metrics-*`**. Edit the pattern and append **`,metrics-*`** (or switch to **Stack Management → Data views** and create **`metrics-*`** with **`@timestamp`**). In **ES|QL**, run **`FROM metrics-* | LIMIT 5`** to confirm documents exist regardless of that default.
- **Histogram looks empty but the table has rows:** set the time picker to **Last 15 minutes** / **Last 24 hours** and ensure the **end** time includes **now**; the chart buckets may stop earlier than your newest `@timestamp`, so the table shows hits while the graph looks blank.
- **Sparse multi-day metric charts (Alloy self-metrics + fresh OTLP):** the fleet only writes **from startup onward**; for a filled **Last 30 days** view in Discover, run **`python3 tools/seed_workshop_telemetry.py --metrics-time-series --days 30`** (bulk to **`metrics-workshop-default`**; same **`service.name`** values as **`otel_workshop_fleet.py`**). Tune **`--metric-time-step-minutes`** / **`--metric-series-cap`** if needed.
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
