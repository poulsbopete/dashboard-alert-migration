---
slug: lab-05-high-cardinality
id: acx7y6xc0ssy
type: challenge
title: Lab 5 — High cardinality optimization
teaser: Stress-test label cardinality, then apply collector-side protections and discuss rollups.
difficulty: ""
enhanced_loading: null
---

# Lab 5 — High cardinality optimization

## Story beat

`entity_id` models a **high-cardinality** label (tenants, shards, accounts, etc.). Prometheus metrics that attach raw
high-cardinality values as labels can explode **time series** count, increasing **cost** and slowing **queries**.

## Step 1 — Scale the stressor

```bash
export KUBECONFIG=/root/.kube/config
kubectl scale deployment/cardinality-stress -n workshop-o11y --replicas=1
kubectl rollout status deployment/cardinality-stress -n workshop-o11y --timeout=180s
```

This deployment sets `HIGH_CARD_ENTITIES` to **50,000** synthetic values.

## Step 2 — Point Alloy at the stressor

Replace the Alloy configuration with the lab overlay that scrapes **both** targets:

```bash
cd /root/workshop
kubectl create configmap alloy-config -n workshop-o11y \
  --from-file=config.river=k8s/lab05/alloy-with-cardinality.river \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/alloy -n workshop-o11y
kubectl rollout status deployment/alloy -n workshop-o11y --timeout=180s
```

## Step 3 — Mitigate in the collector

Your Elastic OTLP template (`k8s/templates/otel-elastic-config.yaml`) includes an `attributes` processor that **drops
`entity_id`** for metrics. Re-apply after edits:

```bash
cd /root/workshop
./scripts/apply_elastic_otlp.sh
```

Discuss as a group:

- **Downsampling** / rollups for analytics
- **Aggregations** at the edge (drop or hash labels before export)
- **Serverless** retention and indexing trade-offs versus self-managed tiers

## Validation

Click **Check** after:

- `cardinality-stress` replicas == 1
- Alloy ConfigMap contains `cardinality-stress`
