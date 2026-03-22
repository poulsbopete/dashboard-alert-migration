---
slug: lab-05-high-cardinality
id: acx7y6xc0ssy
type: challenge
title: Lab 5 — High cardinality optimization
teaser: Turn on a cardinality stressor, observe label explosion, then apply collector-side
  protections.
difficulty: ""
enhanced_loading: null
---

# Lab 5 — High cardinality optimization

## Story beat

`merchant_id` is a realistic **high-cardinality** dimension for a marketplace. Prometheus metrics that include raw merchant IDs as labels can explode series counts, increasing cost and slowing queries.

## Step 1 — Scale the stressor

```bash
export KUBECONFIG=/root/.kube/config
kubectl scale deployment/cardinality-stress -n merchant-o11y --replicas=1
kubectl rollout status deployment/cardinality-stress -n merchant-o11y --timeout=180s
```

This deployment sets `HIGH_CARD_MERCHANTS` to **50,000** synthetic merchants.

## Step 2 — Point Alloy at the stressor

Replace the Alloy configuration with the lab overlay that scrapes **both** services:

```bash
cd /root/workshop
kubectl create configmap alloy-config -n merchant-o11y \
  --from-file=config.river=k8s/lab05/alloy-with-cardinality.river \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/alloy -n merchant-o11y
kubectl rollout status deployment/alloy -n merchant-o11y --timeout=180s
```

## Step 3 — Mitigate in the collector

Your Elastic OTLP template (`k8s/templates/otel-elastic-config.yaml`) already includes an `attributes` processor that **drops `merchant_id`** for metrics. Re-apply OTLP config after edits:

```bash
cd /root/workshop
./scripts/apply_elastic_otlp.sh
```

Discuss as a group:

- **Downsampling** (rollups) for analytics
- **Aggregations** at the edge (reduce labels before export)
- **Serverless** storage characteristics vs self-managed hot/warm tiers

## Validation

Click **Check** after:

- `cardinality-stress` replicas == 1
- Alloy ConfigMap contains `cardinality-stress`
