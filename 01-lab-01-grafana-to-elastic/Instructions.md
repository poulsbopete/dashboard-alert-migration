# Lab 1 — Grafana bulk migration (facilitator)

**Audience:** teams **migrating Grafana customers to Elastic Observability Serverless**.

Learners run **one command**:

```bash
bash /root/workshop/scripts/migrate_grafana_dashboards_to_serverless.sh
```

That script: OTLP → **`grafana-migrate`** (20 dashboards + **`--fetch-alerts`**) → **`publish_grafana_alert_drafts_kibana.py`**.

**Optional extensions (not in assignment):**

- **Laptop + Cursor:** clone repo, paste VM **`export`** lines from **`grep … ~/.bashrc`**, run the same migrate script or raw **`grafana-migrate`** (see **`scripts/migrate_grafana_dashboards_to_serverless.sh`**).
- **Legacy Path B:** **`grafana_to_elastic.py`** + **`publish_grafana_drafts_kibana.py`** for `*-elastic-draft.json` flows.
- **Any grafana.com dashboard:** export JSON → **`grafana_to_elastic.py`** → **`publish_grafana_drafts_kibana.py`**.

**Agent Skills:** **`kibana-dashboards`**, **`agent-skills/workshop-grafana-to-elastic/SKILL.md`**.
