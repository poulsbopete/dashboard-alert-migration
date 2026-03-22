# paypal-elastic-serverless-migration (Instruqt track)

This repository is a **self-contained Instruqt workshop track** that demonstrates migrating **Grafana (Prometheus via
Grafana Alloy)** and **Datadog-style monitors** into **Elastic Observability Serverless**, using **OpenTelemetry** and
optional **Elastic Agent Skills** workflows.

> **Note:** The upstream Instruqt track [`elastic-autonomous-observability`](https://play.instruqt.com/manage/elastic/tracks/elastic-autonomous-observability)
> is not publicly cloneable. This track mirrors common Instruqt layout conventions (`track.yml`, `config.yml`,
> `track_scripts/`, `NN-lab-*/assignment.md`) while implementing the PayPal-inspired storyline requested for this
> workshop.

## Layout

| Path | Purpose |
| --- | --- |
| `track.yml` / `config.yml` | Instruqt metadata + `instruqt/k3s-v1-34-5` sandbox host |
| `track_scripts/` | Track bootstrap: build `payment-simulator`, `kubectl apply`, venv |
| `01-lab-environment-setup/` … `06-lab-unified-observability/` | Labs (`assignment.md`, `Instructions.md`, lifecycle scripts) |
| `k8s/` | Kubernetes manifests (OTEL Collector, Alloy, workloads) |
| `apps/payment-simulator/` | FastAPI service (metrics + traces) |
| `assets/grafana/` | 12 sample Grafana dashboards (generated + committed) |
| `assets/datadog/` | Sample monitor JSON |
| `tools/` | CLIs: Grafana → Elastic drafts, Datadog → Elastic alert drafts |
| `agent-skills/` | Workshop-local skills that wrap the CLIs and point to upstream Agent Skills |

## Facilitator prerequisites

- Elastic Cloud **Observability** Serverless project and OTLP endpoint + API key for learners (or Instruqt secrets)
- Outbound network from the sandbox to Elastic Cloud (typical Instruqt default)

## Local smoke test (optional)

```bash
docker build -t payment-sim:workshop apps/payment-simulator
python3 scripts/generate_grafana_dashboards.py
python3 tools/grafana_to_elastic.py assets/grafana/01-overview.json | head
```

## Publishing to Instruqt

1. Install the [Instruqt CLI](https://docs.instruqt.com/reference/cli/commands) and authenticate.
2. Create a new track (or pull an existing track ID) and replace `REPLACE_WITH_INSTRUQT_TRACK_ID` in `track.yml`.
3. Set `owner` / `developers` to match your organization.
4. Push the track directory with `instruqt track push` (see Instruqt docs for your workflow).

## Agent Skills

- Upstream catalog: [github.com/elastic/agent-skills](https://github.com/elastic/agent-skills)
- This repo adds thin **workshop skills** under `agent-skills/` that document how to run the migration CLIs.
