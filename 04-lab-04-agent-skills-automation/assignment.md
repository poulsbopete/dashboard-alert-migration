---
slug: lab-04-agent-skills-automation
id: nbcewe3y3az0
type: challenge
title: Lab 4 — Agent Skills automation
teaser: Wire Elastic Agent Skills to CLI migration utilities and (optionally) drive
  them from an AI agent.
difficulty: ""
enhanced_loading: null
---

# Lab 4 — Agent Skills automation

## Why this matters

[Elastic Agent Skills](https://github.com/elastic/agent-skills) package operational know-how so agents (and humans) can execute **repeatable** Elastic workflows: dashboards, alerting, cloud projects, ES|QL, and more.

This workshop ships **two focused CLIs** under `tools/`:

- `grafana_to_elastic.py`
- `datadog_to_elastic_alert.py`

## Step 1 — Run a batch conversion report

```bash
cd /root/workshop
mkdir -p build
python3 tools/grafana_to_elastic.py assets/grafana/01-overview.json > build/sample-grafana-elastic.json
python3 tools/datadog_to_elastic_alert.py assets/datadog/monitor-high-5xx-rate.json > build/sample-datadog-elastic.json

cat > build/agent-skills-batch-report.txt <<'EOF'
Batch migration report
- Grafana: extracted PromQL targets from exported JSON and emitted Elastic dashboard drafts.
- Datadog: mapped threshold + anomaly monitors to Elastic rule JSON skeletons.
Next: refine in Kibana UI or automate with Agent Skills + Kibana APIs.
EOF
```

## Step 2 — (Optional) Install upstream Agent Skills

On your workstation (outside this sandbox), clone `https://github.com/elastic/agent-skills` and follow its README to install skills into your agent runtime (for example, Cursor). Then prompt:

> Using the kibana-dashboards and kibana-alerting-rules skills, take `build/elastic-dashboards/01-overview-elastic-draft.json` and describe the API calls you would use to publish panels safely.

## Validation

Click **Check** after `build/agent-skills-batch-report.txt` exists and is non-empty.
