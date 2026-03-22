---
name: paypal-grafana-to-elastic
description: >
  Workshop skill: convert Grafana dashboard JSON (Prometheus/PromQL) into Elastic Observability dashboard drafts using
  the bundled CLI in this repository. Pair with upstream Elastic Agent Skills for Kibana dashboard APIs.
metadata:
  author: workshop
  version: 0.1.0
---

# PayPal-style Grafana → Elastic (workshop)

## When to use

Use this skill when migrating **Grafana** JSON exports from the `assets/grafana/` directory into **Elastic** dashboard
drafts suitable for Kibana refinement.

## Prerequisites

- Python 3.10+
- This repository checked out locally

## Workflow

1. Inspect Grafana JSON for `targets[].expr` PromQL.
2. Run:

```bash
python3 tools/grafana_to_elastic.py assets/grafana/<dashboard>.json --out-dir build/elastic-dashboards
```

3. Use upstream [Elastic Agent Skills](https://github.com/elastic/agent-skills) (for example, dashboard automation
   skills compatible with your Kibana version) to publish or refine the generated JSON.

## Safety

- Do not paste Cloud API keys into prompts.
- Treat drafts as **starting points**; validate panel queries against your metric schema in Serverless.
