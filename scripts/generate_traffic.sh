#!/bin/bash
set -euo pipefail
NS="${NS:-workshop-o11y}"
SVC="${SVC:-sample-api}"
PORT="${PORT:-8080}"
for _ in $(seq 1 "${1:-50}"); do
  kubectl run "curl-$RANDOM" --rm -i --restart=Never --image=curlimages/curl:8.5.0 -n "$NS" -- \
    curl -fsS -X POST "http://${SVC}.${NS}.svc.cluster.local:${PORT}/v1/invoke" >/dev/null || true
done
