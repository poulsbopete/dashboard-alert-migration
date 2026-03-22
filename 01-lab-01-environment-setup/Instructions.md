# Lab 1 — Environment setup

This file duplicates the learner-facing steps from `assignment.md` without Instruqt front matter.

## Goal

Deploy the **Kubernetes** telemetry path (OpenTelemetry Collector + Grafana Alloy + `payment-simulator`) and connect **Elastic Observability Serverless** using **OTLP**.

## Steps

1. Create or choose an Elastic **Observability** Serverless project and obtain OTLP endpoint + API key.

   ```bash
   export ELASTIC_OTLP_ENDPOINT="https://<your-endpoint>.otlp.observability.elastic.cloud:443"
   export ELASTIC_OTLP_AUTH="ApiKey <base64-api-key>"
   ```

2. Apply the Elastic OTLP pipeline:

   ```bash
   cd /root/workshop
   chmod +x scripts/apply_elastic_otlp.sh
   ./scripts/apply_elastic_otlp.sh
   ```

3. Generate traffic:

   ```bash
   chmod +x scripts/generate_traffic.sh
   ./scripts/generate_traffic.sh 200
   ```

4. Validate in Kibana: APM service `payment-simulator`, metrics, and traces for `POST /v1/payments`.

For automated checks, use the Instruqt **Check** button (see `check-host01`).
