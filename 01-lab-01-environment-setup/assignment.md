---
slug: lab-01-environment-setup
id: 7xffw36spadb
type: challenge
title: Lab 1 — Environment setup
teaser: Stand up Kubernetes telemetry plumbing and connect Elastic Observability Serverless
  over OTLP.
tabs:
- id: lypopaehfkah
  title: Terminal
  type: terminal
  hostname: host01
  workdir: /root/workshop
- id: rdmuzri3smi7
  title: Workshop
  type: code
  hostname: host01
  path: /root/workshop
- id: blxkp1sz0kzz
  title: Elastic Cloud
  type: website
  url: https://cloud.elastic.co
  new_window: true
difficulty: ""
enhanced_loading: null
---

# Lab 1 — Environment setup

This spike assumes telemetry is fragmented today (for example **Grafana** for Prometheus-backed dashboards and another
tool for **alerts**). In this track you standardize **ingestion** into **Elastic Observability Serverless** using
**OpenTelemetry Collector** and **Grafana Alloy** scraping Prometheus-format metrics.

## What is already running

The track bootstrap installed **k3s**, built the `sample-api` image, and applied manifests under `k8s/`:

- `sample-api` (HTTP + `/metrics`, synthetic `POST /v1/invoke`)
- `otel-collector` (OTLP ingest + Prometheus remote write receiver; ships **debug** output until you apply Elastic export)
- `alloy` (scrapes `/metrics`, remote-writes into the collector)

Your workshop root is symlinked at `/root/workshop`. Kubernetes namespace: **`workshop-o11y`**.

## Step 1 — Create (or select) an Observability Serverless project

In Elastic Cloud, create an **Observability** Serverless project (or reuse an existing non-production project).

Copy the **OTLP endpoint** and an **API key** authorized to ingest APM/Observability data:

```bash
export ELASTIC_OTLP_ENDPOINT="https://<your-endpoint>.otlp.observability.elastic.cloud:443"
export ELASTIC_OTLP_AUTH="ApiKey <base64-api-key>"
```

> Tip: Instructors can inject these via Instruqt **secrets** instead of asking learners to paste keys.

## Step 2 — Apply the Elastic OTLP pipeline

```bash
cd /root/workshop
chmod +x scripts/apply_elastic_otlp.sh
./scripts/apply_elastic_otlp.sh
```

This renders `k8s/templates/otel-elastic-config.yaml` into a live `ConfigMap` and restarts the collector. The template
includes an `attributes` processor that **drops `entity_id`** on metrics by default (a stand-in for **high-cardinality**
dimensions). Lab 5 explores stress-testing that assumption.

## Step 3 — Generate traffic

```bash
chmod +x scripts/generate_traffic.sh
./scripts/generate_traffic.sh 200
```

## Step 4 — Verify in Elastic

Open Kibana for your Serverless project and confirm:

- **APM / Services** shows `sample-api`
- Metrics and traces reflect `POST /v1/invoke`

## Validation (this lab)

Click **Check** after the cluster exporter is healthy and Elastic shows fresh telemetry.
