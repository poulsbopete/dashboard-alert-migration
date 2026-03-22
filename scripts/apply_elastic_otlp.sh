#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENDPOINT="${ELASTIC_OTLP_ENDPOINT:?Set ELASTIC_OTLP_ENDPOINT (e.g. https://<id>.otlp.observability.elastic.cloud:443)}"
AUTH="${ELASTIC_OTLP_AUTH:?Set ELASTIC_OTLP_AUTH (e.g. ApiKey <key>)}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
sed \
  -e "s|ELASTIC_OTLP_ENDPOINT_PLACEHOLDER|${ENDPOINT}|g" \
  -e "s|ELASTIC_OTLP_AUTH_PLACEHOLDER|${AUTH}|g" \
  "$ROOT/k8s/templates/otel-elastic-config.yaml" >"$TMP"
kubectl create configmap otel-collector-config \
  --namespace workshop-o11y \
  --from-file=config.yaml="$TMP" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/otel-collector --namespace workshop-o11y
if [ "${WAIT_ROLLOUT:-1}" != "0" ]; then
  kubectl rollout status deployment/otel-collector --namespace workshop-o11y --timeout=180s
fi
