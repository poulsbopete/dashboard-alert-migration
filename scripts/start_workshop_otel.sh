#!/usr/bin/env bash
# Start Grafana Alloy + Python OTLP emitter (same pipeline as track bootstrap when mOTLP URL is known).
# Prerequisites: source ~/.bashrc — need ES_API_KEY (or ES_PASSWORD) and WORKSHOP_OTLP_ENDPOINT.
set -euo pipefail
cd /root/workshop
# shellcheck disable=SC1090
source ~/.bashrc

if [ -z "${WORKSHOP_OTLP_ENDPOINT:-}" ]; then
  echo "ERROR: WORKSHOP_OTLP_ENDPOINT is not set." >&2
  echo "Copy the managed OTLP (mOTLP) URL from Kibana → Add data → OpenTelemetry (see Elastic docs)." >&2
  echo "Same flow as track https://play.instruqt.com/manage/elastic/tracks/elastic-autonomous-observability/sandbox" >&2
  exit 1
fi

if [ -n "${ES_API_KEY:-}" ]; then
  export WORKSHOP_OTLP_AUTH_HEADER="ApiKey ${ES_API_KEY}"
elif [ -n "${ES_PASSWORD:-}" ]; then
  echo "ERROR: OTLP ingest expects an API key. Create one in Kibana (workshop-migration) and set ES_API_KEY." >&2
  exit 1
else
  echo "ERROR: Set ES_API_KEY (source ~/.bashrc on the workshop VM)." >&2
  exit 1
fi

ALLOY_BIN="${ALLOY_BIN:-/usr/local/bin/alloy}"
ALLOY_CFG="${ALLOY_CFG:-/root/workshop/assets/alloy/workshop.alloy}"
if [ ! -x "$ALLOY_BIN" ]; then
  echo "ERROR: Alloy not found at $ALLOY_BIN (track setup should install it)." >&2
  exit 1
fi

mkdir -p /tmp/alloy-storage
pkill -f "alloy run.*workshop.alloy" 2>/dev/null || true
pkill -f "otel_workshop_emitter.py" 2>/dev/null || true
pkill -f "datadog_otel_to_elastic.py" 2>/dev/null || true
sleep 1
nohup "$ALLOY_BIN" run --storage.path=/tmp/alloy-storage "$ALLOY_CFG" >>/tmp/workshop-alloy.log 2>&1 &
echo $! >/tmp/workshop-alloy.pid
sleep 3
nohup python3 /root/workshop/tools/otel_workshop_emitter.py >>/tmp/workshop-emitter.log 2>&1 &
echo $! >/tmp/workshop-emitter.pid
nohup python3 /root/workshop/tools/datadog_otel_to_elastic.py >>/tmp/workshop-datadog-otel.log 2>&1 &
echo $! >/tmp/workshop-datadog-otel.pid
echo "Alloy PID $(cat /tmp/workshop-alloy.pid), generic emitter $(cat /tmp/workshop-emitter.pid), Datadog-style OTLP $(cat /tmp/workshop-datadog-otel.pid)"
echo "Logs: /tmp/workshop-alloy.log /tmp/workshop-emitter.log /tmp/workshop-datadog-otel.log"
