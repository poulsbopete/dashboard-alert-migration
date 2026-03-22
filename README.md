# elastic-serverless-migration-lab (Instruqt track)

**Instruqt** track (**two labs**) for a **high-volume migration spike**: **20** **Grafana** dashboards and **10**
**Datadog-style** dashboards (plus **4** monitor JSON files) → Elastic drafts on **Observability Serverless**, using
**CLI batch converters**, **[Elastic Agent Skills](https://github.com/elastic/agent-skills)**, and **Cursor** / AI for
query rewrite and Kibana API workflows.

The sandbox is **elastic/es3-api-v2**: **es3-api** provisions an **Observability Serverless** project per play, proxies
**Kibana** on **:8080**, and carries the workshop tree (Python venv + **assets/**).

## Spike goals

- **Grafana → Elastic**: **PromQL** continuity where Elastic exposes Prometheus-compatible workflows; refine in Kibana.
- **Datadog → Elastic**: pragmatic **alert-rule** mapping (threshold / query / ML paths).
- **Agent Skills**: use upstream skills locally (for example `kibana-dashboards`, `kibana-alerting-rules`) plus workshop
  wrappers under `agent-skills/`.

## Layout

| Path | Purpose |
| --- | --- |
| `track.yml` / `config.yml` | Instruqt metadata + VM **`elastic/es3-api-v2`** (`es3-api` host) |
| `track_scripts/` | `setup-es3-api`: create Serverless project, nginx → Kibana :8080, workshop venv + `pip` |
| `01-lab-01-grafana-to-elastic/` | Lab 1: **20** Grafana → `build/elastic-dashboards/*-elastic-draft.json` |
| `02-lab-02-datadog-dashboards-alerts-to-elastic/` | Lab 2: **10** DD dashboards + **4** monitors → `build/elastic-datadog-dashboards/`, `build/elastic-alerts/` |
| `assets/grafana/` | **20** generated Grafana JSON exports (`scripts/generate_grafana_dashboards.py`) |
| `assets/datadog/dashboards/` | **10** Datadog-style dashboard JSON (`scripts/generate_datadog_dashboards.py`) |
| `assets/datadog/monitor-*.json` | **4** monitor samples |
| `tools/` | `grafana_to_elastic.py`, `publish_grafana_drafts_kibana.py`, `datadog_dashboard_to_elastic.py`, `datadog_to_elastic_alert.py` |
| `scripts/migrate_grafana_dashboards_to_serverless.sh` | **Path A:** convert 20 Grafana exports + **Kibana Saved Objects API** publish |
| `agent-skills/` | Workshop skills + [elastic/agent-skills](https://github.com/elastic/agent-skills) |
| `k8s/`, `apps/sample-api/` | Legacy / optional material (not used by the container track bootstrap) |

Loading / wait slides are defined in each **`assignment.md`** frontmatter (`notes:`), per Instruqt [loading experience](https://docs.instruqt.com/tracks/manage/loading-experience).

## Facilitator prerequisites

- Learners need access to an **Observability Serverless** project (Elastic Cloud).
- Outbound **HTTPS** from the sandbox (for `git clone` fallback of the workshop repo if the bundle is not on disk).

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
