#!/usr/bin/env bash
# Quick checks: is Grafana Alloy up, are OTLP emitters running, do local ports answer?
# Run on the workshop VM:  cd /root/workshop && source ~/.bashrc && ./scripts/check_workshop_otel_pipeline.sh
set -u

echo "=== Workshop OTLP / Alloy diagnostics ==="
echo

if [ -f /root/.bashrc ]; then
  # shellcheck disable=SC1090
  source /root/.bashrc 2>/dev/null || true
fi

if [ -n "${WORKSHOP_OTLP_ENDPOINT:-}" ]; then
  echo "WORKSHOP_OTLP_ENDPOINT: set (Alloy can export to Elastic mOTLP)"
else
  echo "WORKSHOP_OTLP_ENDPOINT: NOT SET — track setup may have skipped Alloy; copy URL from Kibana → Add data → OpenTelemetry"
fi
if [ -n "${WORKSHOP_OTLP_AUTH_HEADER:-}" ] || [ -n "${ES_API_KEY:-}" ]; then
  echo "API key for OTLP: present (ES_API_KEY or WORKSHOP_OTLP_AUTH_HEADER)"
else
  echo "API key for OTLP: missing — export ES_API_KEY after source ~/.bashrc"
fi
echo

echo "--- Processes (alloy + Python emitters) ---"
pgrep -af '[a]lloy run' || echo "  (no alloy run … process)"
pgrep -af '[o]tel_workshop_emitter' || echo "  (no otel_workshop_emitter.py)"
pgrep -af '[d]atadog_otel_to_elastic' || echo "  (no datadog_otel_to_elastic.py)"
echo

echo "--- Listening ports (OTLP gRPC 4317, OTLP HTTP 4318, Alloy self-metrics 12345) ---"
if command -v ss >/dev/null 2>&1; then
  ss -tlnp 2>/dev/null | grep -E ':(4317|4318|12345)\b' || echo "  (none of 4317/4318/12345 listening — Alloy probably not running)"
elif command -v netstat >/dev/null 2>&1; then
  netstat -tln 2>/dev/null | grep -E '4317|4318|12345' || echo "  (none listening)"
else
  echo "  (install ss or netstat to list ports)"
fi
echo

echo "--- Alloy self-metrics (Prometheus scrape target) ---"
if curl -sf --max-time 3 "http://127.0.0.1:12345/metrics" | head -n 5; then
  echo "  … http://127.0.0.1:12345/metrics responds (Alloy internal telemetry is live)"
else
  echo "  FAIL: no response from http://127.0.0.1:12345/metrics"
fi
echo

echo "--- Recent log lines ---"
for f in /tmp/workshop-alloy.log /tmp/workshop-emitter.log /tmp/workshop-datadog-otel.log; do
  echo ">>> $f"
  tail -n 12 "$f" 2>/dev/null || echo "  (file missing)"
  echo
done

echo "=== If Alloy is down ==="
echo "  cd /root/workshop && source ~/.bashrc && ./scripts/start_workshop_otel.sh"
echo "=== If Alloy is up but Elastic has no data ==="
echo "  tail -50 /tmp/workshop-alloy.log   # look for export errors to mOTLP"
echo "  echo \"\\\$WORKSHOP_OTLP_ENDPOINT\" should be the HTTPS base URL from Kibana (no /v1/traces path)."
