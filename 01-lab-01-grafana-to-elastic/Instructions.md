# Lab 1 — Grafana bulk migration (facilitator)

**Audience:** teams **migrating Grafana customers to Elastic Observability Serverless**.

Twenty Grafana JSON files → `build/elastic-dashboards/` → Kibana (Dashboards API or skills). Learners use **Cursor** +
**`kibana-dashboards`** patterns to refine on the **es3-api**–provisioned Serverless project.

**Path B extension:** Assignment **B5b** walks through downloading **any** dashboard JSON from **[grafana.com/grafana/dashboards](https://grafana.com/grafana/dashboards/)** (or exporting from Grafana), running **`grafana_to_elastic.py`**, then **`publish_grafana_drafts_kibana.py`** — same pipeline as bundled assets, with explicit expectations about data sources and licenses.
