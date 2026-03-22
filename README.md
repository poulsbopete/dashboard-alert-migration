# elastic-serverless-migration-lab (Instruqt track)

Self-contained **Instruqt** workshop for a **dashboard and alert migration spike**: from **Grafana (Prometheus via
Grafana Alloy)** and **Datadog-style** monitor exports toward **Elastic Observability Serverless**, using
**OpenTelemetry**, **CLI utilities**, and optional **Elastic Agent Skills** / AI agents.

The scenario is intentionally **vendor- and domain-neutral**: a tiny `sample-api` workload exists only to produce
realistic **metrics, traces, and logs** so you can practice extraction, translation, and governance patterns (including
**high-cardinality** label handling).

## What this aligns with (spike goals)

- **Grafana → Elastic**: leverage **PromQL** continuity where Elastic exposes Prometheus-compatible querying—often
  simpler than a full rewrite to another DSL.
- **Datadog → Elastic**: expect **more tailoring for alerting** (threshold rules, query rules, ML)—plan for a **short-term
  compromise** while standards mature.
- **Tooling**: **CLI-first** migration helpers under `tools/` for speed; **Agent Skills** for repeatable, automatable steps.
- **AI**: optional agent-driven flows on top of the same artifacts.

## Layout

| Path | Purpose |
| --- | --- |
| `track.yml` / `config.yml` | Instruqt metadata + `instruqt/k3s-v1-34-5` sandbox host |
| `track_scripts/` | Bootstrap: build `sample-api` image, `kubectl apply`, Python venv |
| `01-lab-01-environment-setup/` … `06-lab-06-unified-observability/` | Labs: `assignment.md` (**tabs**: Terminal, Workshop, Elastic Cloud) + `notes.md` (shown on **loading / wait** screens per [loading experience](https://docs.instruqt.com/tracks/manage/loading-experience)) |
| `k8s/` | Namespaced manifests (`workshop-o11y`): OTEL Collector, Alloy, workloads |
| `apps/sample-api/` | Minimal HTTP API + Prometheus metrics + OTEL traces |
| `assets/grafana/` | 12 sample Grafana JSON exports |
| `assets/datadog/` | Sample monitor JSON |
| `tools/` | `grafana_to_elastic.py`, `datadog_to_elastic_alert.py` |
| `agent-skills/` | Thin workshop skills pointing at the CLIs + [elastic/agent-skills](https://github.com/elastic/agent-skills) |

## Facilitator prerequisites

- Elastic **Observability** Serverless project: OTLP endpoint + API key for learners (or Instruqt secrets)
- Outbound access from the sandbox to Elastic Cloud

### Instruqt secrets (retained on `track push`)

`config.yml` declares **`LLM_PROXY_PROD`** and **`ESS_CLOUD_API_KEY`** under `secrets:`. That keeps them bound to this
track when you push from Git—sandbox-only edits in the UI can be overwritten if they are not also in `config.yml`.

- Store **values** under **Team settings → Secrets** in Instruqt (never commit secrets to this repo).
- During **lifecycle scripts** (`track_scripts/*`, challenge `setup-host01`, etc.), each name is available as an
  **environment variable** with the same name (for example `$ESS_CLOUD_API_KEY`).

## Local smoke test (optional)

```bash
docker build -t sample-api:workshop apps/sample-api
python3 scripts/generate_grafana_dashboards.py
python3 tools/grafana_to_elastic.py assets/grafana/01-overview.json | head
```

## Publishing to Instruqt

1. Install the [Instruqt CLI](https://docs.instruqt.com/reference/cli/commands) and authenticate.
2. Keep `track.yml` in sync with your remote track (`instruqt track pull` / `push`).
3. Run `instruqt track validate`, then `instruqt track push`.

## Agent Skills

- Upstream: [github.com/elastic/agent-skills](https://github.com/elastic/agent-skills)
- Workshop wrappers: `agent-skills/workshop-grafana-to-elastic/`, `agent-skills/workshop-datadog-to-elastic-alerts/`
