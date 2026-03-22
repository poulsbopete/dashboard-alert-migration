# Lab 1 — Environment setup

Steps mirror `assignment.md` (Instruqt assignment tab is authoritative).

## Goal

Run **OpenTelemetry Collector** + **Grafana Alloy** + **`sample-api`**, then export to **Elastic Observability Serverless**
over **OTLP**.

## Commands (summary)

```bash
export ELASTIC_OTLP_ENDPOINT="https://<your-endpoint>.otlp.observability.elastic.cloud:443"
export ELASTIC_OTLP_AUTH="ApiKey <base64-api-key>"

cd /root/workshop
chmod +x scripts/apply_elastic_otlp.sh
./scripts/apply_elastic_otlp.sh

chmod +x scripts/generate_traffic.sh
./scripts/generate_traffic.sh 200
```

Validate in Kibana: APM service **`sample-api`**, traces for **`POST /v1/invoke`**.
