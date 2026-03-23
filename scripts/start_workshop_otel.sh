#!/usr/bin/env bash
# Start Grafana Alloy + Python OTLP emitter (same pipeline as track bootstrap when mOTLP URL is known).
# Prerequisites: source ~/.bashrc — ES_API_KEY (or ES_PASSWORD for seed only; OTLP needs API key).
# WORKSHOP_OTLP_ENDPOINT: if unset, derived from ES_URL (.es.→.ingest.) or KIBANA_URL (.kb.→.ingest.) on Serverless.
# Disable auto-derive: WORKSHOP_DERIVE_OTLP_FROM_ES=0
set -euo pipefail
cd /root/workshop
# shellcheck disable=SC1090
source ~/.bashrc

# Prefer track venv — system python3 often lacks opentelemetry-* (silent failures if PATH is wrong).
if [ -x /opt/workshop-venv/bin/python3 ]; then
  PYTHON="${WORKSHOP_PYTHON:-/opt/workshop-venv/bin/python3}"
else
  PYTHON="${WORKSHOP_PYTHON:-python3}"
fi

if [ -z "${WORKSHOP_OTLP_ENDPOINT:-}" ] && [ "${WORKSHOP_DERIVE_OTLP_FROM_ES:-1}" != "0" ]; then
  _mot=""
  if [ -n "${ES_URL:-}" ] && [[ "$ES_URL" == *".es."* ]]; then
    _mot="${ES_URL%/}"
    _mot="${_mot//.es./.ingest.}"
  elif [ -n "${KIBANA_URL:-}" ] && [[ "$KIBANA_URL" == *".kb."* ]]; then
    _mot="${KIBANA_URL%/}"
    _mot="${_mot//.kb./.ingest.}"
  fi
  if [ -n "$_mot" ]; then
    export WORKSHOP_OTLP_ENDPOINT="$_mot"
    echo "INFO: WORKSHOP_OTLP_ENDPOINT was unset — derived Serverless managed OTLP host:" >&2
    echo "      $WORKSHOP_OTLP_ENDPOINT" >&2
    echo "      (Copy from Kibana → Add data → OpenTelemetry to override, or set WORKSHOP_DERIVE_OTLP_FROM_ES=0 to force manual.)" >&2
  fi
fi

if [ -z "${WORKSHOP_OTLP_ENDPOINT:-}" ]; then
  echo "ERROR: WORKSHOP_OTLP_ENDPOINT is not set and could not be derived from ES_URL / KIBANA_URL." >&2
  echo "Copy the managed OTLP (mOTLP) base URL from Kibana → Add data → OpenTelemetry (HTTPS host, no /v1/traces)." >&2
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

_ensure_alloy_binary() {
  if [ -x "$ALLOY_BIN" ]; then
    return 0
  fi
  echo "Alloy missing at $ALLOY_BIN — installing Grafana Alloy (one-time)..." >&2
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq 2>/dev/null || true
  apt-get install -y --no-install-recommends curl ca-certificates unzip >/dev/null 2>&1 || true
  ALLOY_VER="${ALLOY_VERSION:-v1.8.3}"
  Z="/tmp/alloy-workshop-install-$$.zip"
  D="/tmp/alloy-workshop-unpack-$$"
  rm -rf "$D"
  mkdir -p "$D" "$(dirname "$ALLOY_BIN")"
  if ! curl -fsSL "https://github.com/grafana/alloy/releases/download/${ALLOY_VER}/alloy-linux-amd64.zip" -o "$Z"; then
    echo "ERROR: could not download Alloy ${ALLOY_VER} (need curl + github.com)." >&2
    return 1
  fi
  if ! unzip -o -j "$Z" -d "$D" >/dev/null; then
    echo "ERROR: unzip failed for Alloy archive (apt install unzip?)." >&2
    rm -f "$Z"
    return 1
  fi
  rm -f "$Z"
  for cand in "$D/alloy" "$D/alloy-linux-amd64" "$D/alloy-linux-amd64.exe"; do
    if [ -f "$cand" ]; then
      install -m 0755 "$cand" "$ALLOY_BIN"
      rm -rf "$D"
      echo "Installed Alloy → $ALLOY_BIN" >&2
      return 0
    fi
  done
  echo "ERROR: no alloy binary found after unzip. Contents:" >&2
  ls -la "$D" >&2 || true
  rm -rf "$D"
  return 1
}

if ! _ensure_alloy_binary; then
  exit 1
fi

mkdir -p /tmp/alloy-storage
pkill -f "alloy run.*workshop.alloy" 2>/dev/null || true
pkill -f "otel_workshop_fleet.py" 2>/dev/null || true
pkill -f "otel_workshop_emitter.py" 2>/dev/null || true
pkill -f "datadog_otel_to_elastic.py" 2>/dev/null || true
sleep 1
nohup "$ALLOY_BIN" run --storage.path=/tmp/alloy-storage "$ALLOY_CFG" >>/tmp/workshop-alloy.log 2>&1 &
echo $! >/tmp/workshop-alloy.pid
sleep 3
nohup "$PYTHON" /root/workshop/tools/otel_workshop_fleet.py >>/tmp/workshop-fleet-supervisor.log 2>&1 &
echo $! >/tmp/workshop-fleet.pid
nohup "$PYTHON" /root/workshop/tools/datadog_otel_to_elastic.py >>/tmp/workshop-datadog-otel.log 2>&1 &
echo $! >/tmp/workshop-datadog-otel.pid
echo "Alloy PID $(cat /tmp/workshop-alloy.pid), OTLP fleet supervisor $(cat /tmp/workshop-fleet.pid), Datadog-style OTLP $(cat /tmp/workshop-datadog-otel.pid)"
echo "Logs: /tmp/workshop-alloy.log /tmp/workshop-fleet.log /tmp/workshop-fleet-supervisor.log /tmp/workshop-datadog-otel.log"
