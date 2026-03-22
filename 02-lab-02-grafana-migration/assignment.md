---
slug: lab-02-grafana-migration
id: berxl591tjk4
type: challenge
title: Lab 2 — Grafana migration (Prometheus → Elastic)
teaser: Treat Grafana JSON as the source of truth for PromQL panels and produce Elastic
  dashboard drafts.
tabs:
- id: fsizfoyfjtag
  title: Terminal
  type: terminal
  hostname: host01
  workdir: /root/workshop
- id: kq3pgzwyvvfw
  title: Workshop
  type: code
  hostname: host01
  path: /root/workshop
- id: v9ea7agmywny
  title: Elastic Cloud
  type: website
  url: https://cloud.elastic.co
  new_window: true
difficulty: ""
enhanced_loading: null
---

# Lab 2 — Grafana migration (Prometheus → Elastic)

## Context

Your organization standardized dashboards in Grafana using Prometheus (scraped here by **Alloy**). Elastic Observability Serverless can ingest the same metric shapes via OTLP / Prometheus remote write, and—depending on your deployment—**PromQL can remain a first-class query language** for Prometheus-compatible metric stores.

This lab focuses on **repeatable translation** from Grafana exports to **Elastic-native dashboard drafts** suitable for refinement in Kibana or automation via the [Elastic Agent Skills](https://github.com/elastic/agent-skills) ecosystem (for example, patterns described in the `kibana-dashboards` skill).

## Step 1 — Inspect the exports

```bash
cd /root/workshop
ls -1 assets/grafana
```

Open any JSON file and identify:

- `title`
- `targets[].expr` (PromQL)

## Step 2 — Generate Elastic drafts (CLI)

Use the bundled converter:

```bash
mkdir -p build/elastic-dashboards
python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
```

Each output file includes:

- extracted PromQL
- migration notes mapping PromQL constructs to ES|QL / native aggregations (high level)

## Step 3 — PromQL in Elastic (discussion)

In Elastic Observability, PromQL support is surfaced for **Prometheus-compatible** metric workflows. When moving to TSDB-native views, you typically:

- map labels (for example `entity_id`) to dimensions
- replace `rate()` / `histogram_quantile()` with time-bucketed aggregations or PromQL-native paths where enabled

Capture one example query from your exports and write a one-paragraph plan in `build/promql-notes.md` (create this file).

## Validation

Click **Check** after `build/elastic-dashboards` contains **12** JSON files and `build/promql-notes.md` exists.
