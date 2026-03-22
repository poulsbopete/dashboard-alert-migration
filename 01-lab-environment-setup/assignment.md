---
slug: lab-01-environment-setup
type: challenge
title: "Lab 1 — Environment setup"
teaser: "Stand up Kubernetes telemetry plumbing and connect Elastic Observability Serverless over OTLP."
---

# Lab 1 — Environment setup (PayPal-inspired merchant platform)

You are operating a fictional **global merchant payments mesh**: services emit **Prometheus-style metrics**, **OpenTelemetry traces**, and **structured logs**. Today the organization is fragmented across Grafana + Datadog-style monitors; this workshop migrates the signal path into **Elastic Observability Serverless** using **OpenTelemetry Collector** and **Grafana Alloy**.

## What is already running

The track bootstrap installed **k3s**, built the `payment-simulator` image, and applied manifests under `k8s/`:

- `payment-simulator` (HTTP + `/metrics`)
- `otel-collector` (OTLP ingest + Prometheus remote write receiver; starts in **debug** mode until you apply Elastic export)
- `alloy` (scrapes the payment service and remote-writes into the collector)

Your workshop root is symlinked at `/root/workshop`.

## Step 1 — Create (or select) an Observability Serverless project

In Elastic Cloud, create an **Observability** Serverless project (or reuse an existing non-production project).

Copy the **OTLP endpoint** and an **API key** authorized to ingest APM/Observability data. Format the auth header exactly like:

```bash
export ELASTIC_OTLP_ENDPOINT="https://<your-endpoint>.otlp.observability.elastic.cloud:443"
export ELASTIC_OTLP_AUTH="ApiKey <base64-api-key>"
```

> Tip: If you are running this track on Instruqt with organization secrets, your instructor may inject these as environment variables instead.

## Step 2 — Apply the Elastic OTLP pipeline

```bash
cd /root/workshop
chmod +x scripts/apply_elastic_otlp.sh
./scripts/apply_elastic_otlp.sh
```

This renders `k8s/templates/otel-elastic-config.yaml` into a live `ConfigMap` and restarts the collector. The template includes a **label-dropping** processor for `merchant_id` to keep the default path safe for Prometheus metrics; Lab 5 explores what happens when that protection is removed under stress.

## Step 3 — Generate traffic

```bash
chmod +x scripts/generate_traffic.sh
./scripts/generate_traffic.sh 200
```

## Step 4 — Verify in Elastic

Open Kibana for your Serverless project and confirm:

- **APM / Services** shows `payment-simulator`
- **Metrics** explorer can see Prometheus-backed series (depending on feature flags/edition)
- You can locate spans for `POST /v1/payments`

## Validation (this lab)

Click **Check** after the cluster exporter is healthy and Elastic shows fresh telemetry.
