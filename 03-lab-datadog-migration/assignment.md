---
slug: lab-03-datadog-migration
type: challenge
title: "Lab 3 — Datadog-style monitors → Elastic alerting"
teaser: "Export JSON monitors, translate mentally to Elastic rules, and emit Kibana alerting JSON drafts."
---

# Lab 3 — Datadog-style monitors → Elastic alerting

## Context

Many enterprises accumulate **alert fatigue** from loosely tuned Datadog monitors (this workshop ships **JSON shaped like** common exports—Datadog’s exact export format can vary by API version).

Elastic equivalents typically combine:

- **Threshold / query rules** for logs + metrics
- **ML anomaly detection** where enabled (mapped from Datadog anomaly monitors)

## Step 1 — Review the monitors

```bash
cd /root/workshop
ls -1 assets/datadog
jq . assets/datadog/monitor-high-5xx-rate.json
```

## Step 2 — Generate Elastic alert drafts

```bash
mkdir -p build/elastic-alerts
for f in assets/datadog/*.json; do
  base="$(basename "$f" .json)"
  python3 tools/datadog_to_elastic_alert.py "$f" -o "build/elastic-alerts/${base}-elastic.json"
done
```

## Step 3 — (Optional) Create a rule via Kibana API

If you have Kibana URL + API key available in your environment, create **one** rule using the draft JSON as a starting point. This step is optional in sandboxes without outbound access.

## Validation

Click **Check** after `build/elastic-alerts` contains **4** `*-elastic.json` files.
