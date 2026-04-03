# Lab 1 — Grafana bulk migration (facilitator)

**Audience:** teams **migrating Grafana customers to Elastic Observability Serverless**.

Twenty Grafana JSON files plus **`assets/grafana/alerts/`** → **`grafana-migrate`** (**`--fetch-alerts`**) → **`build/mig-grafana/`** + **`publish_grafana_alert_drafts_kibana.py`** → Kibana (Dashboards + Rules). Legacy Path B still uses **`build/elastic-dashboards/`** with **`publish_grafana_drafts_kibana.py`**. Learners use **Cursor** + **`kibana-dashboards`** patterns to refine on the **es3-api**–provisioned Serverless project.

**Path B extension:** Assignment **B5b** walks through downloading **any** dashboard JSON from **[grafana.com/grafana/dashboards](https://grafana.com/grafana/dashboards/)** (or exporting from Grafana), running **`grafana_to_elastic.py`**, then **`publish_grafana_drafts_kibana.py`** — same pipeline as bundled assets, with explicit expectations about data sources and licenses.
