---
slug: lab-01-grafana-to-elastic
id: 7xffw36spadb
type: challenge
title: Lab 1 — Grafana → Elastic (API path or Cursor path)
teaser: One-click Terminal migration via Kibana API, or Agent Skills + Cursor on your
  laptop—only Terminal and Elastic Serverless tabs.
notes:
- type: text
  contents: |
    ## Track goal

    **Migrate Grafana (and in Lab 2, Datadog) workloads toward Elastic Observability Serverless**—this lab is the Grafana
    side: lots of real dashboard JSON, then Kibana publishing and optional AI-assisted refinement.

    ## Two labs

    **Lab 1 — Grafana (20 dashboards)** — Pick **Path A** (script + Kibana API in Terminal) or **Path B** (API key + Cursor + Elastic Agent Skills on your laptop).

    **Lab 2 — Datadog** — Ten dashboard JSON + four monitor JSON → Elastic drafts.

    This challenge uses only **Terminal** and **Elastic Serverless** (no Workshop tab).

    **Telemetry:** primary path matches **[elastic-autonomous-observability](https://play.instruqt.com/manage/elastic/tracks/elastic-autonomous-observability/sandbox)** — **Grafana Alloy** on the VM forwards OTLP to Elastic **[managed OTLP](https://www.elastic.co/docs/reference/opentelemetry/motlp)**. If that URL is missing from `project_results`, setup falls back to **`./scripts/seed_workshop_telemetry.sh`**. Restart Alloy: **`./scripts/start_workshop_otel.sh`** (after `source ~/.bashrc`).
- type: text
  contents: |
    ## Path A (fast)

    Run **`scripts/migrate_grafana_dashboards_to_serverless.sh`** after `source ~/.bashrc`. It converts Grafana exports, runs **`seed_workshop_telemetry.py`** (so ES|QL has **`@timestamp`** data), then **POSTs** dashboards to Kibana.

    ## Path B (skills + AI)

    **Laptop:** clone **`git@github.com:poulsbopete/dashboard-alert-migration.git`** → Grafana JSON in **`assets/grafana/`**. **Instruqt:** `source ~/.bashrc` → **`grep`** (see challenge body) → paste **`export`** lines into **Cursor’s terminal** on the laptop. Then **`kibana-dashboards`** skill + local **`grafana_to_elastic.py`**.
tabs:
- id: lypopaehfkah
  title: Terminal
  type: terminal
  hostname: es3-api
  workdir: /root/workshop
- id: blxkp1sz0kzz
  title: Elastic Serverless
  type: service
  hostname: es3-api
  path: /app/dashboards#/list?_g=(filters:!(),refreshInterval:(pause:!f,value:30000),time:(from:now-30m,to:now))
  port: 8080
  custom_request_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self'' https://kibana.estccdn.com; worker-src blob: ''self'';
      style-src ''unsafe-inline'' ''self'' https://kibana.estccdn.com; style-src-elem
      ''unsafe-inline'' ''self'' https://kibana.estccdn.com'
  custom_response_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self'' https://kibana.estccdn.com; worker-src blob: ''self'';
      style-src ''unsafe-inline'' ''self'' https://kibana.estccdn.com; style-src-elem
      ''unsafe-inline'' ''self'' https://kibana.estccdn.com'
difficulty: ""
enhanced_loading: null
---

# Lab 1 — Grafana → Elastic Serverless (**20 dashboards**)

This lab supports **Grafana → Elastic Observability Serverless** migrations at **volume**: you batch-convert exports, publish
to Kibana, and (Path B) use **Cursor** + **Agent Skills** to close gaps PromQL cannot map one-to-one.

Use the **Terminal** and **Elastic Serverless** tabs. Choose **Path A** (everything in Instruqt) or **Path B** (clone repo on your **laptop** + **Cursor**, and copy connection settings from Instruqt). You may do both.

## Sample telemetry (Discover + dashboard charts)

This track is meant to mirror **[elastic-autonomous-observability](https://play.instruqt.com/manage/elastic/tracks/elastic-autonomous-observability/sandbox)**: **Grafana Alloy** on the **es3-api** host receives OTLP on **`127.0.0.1:4317/4318`**, scrapes Alloy’s own Prometheus metrics, and exports everything to Elastic **Observability Serverless** using the **[managed OTLP (mOTLP)](https://www.elastic.co/docs/reference/opentelemetry/motlp)** endpoint (plus **`Authorization: ApiKey …`**). **`tools/otel_workshop_emitter.py`** sends generic **traces** + **metrics**; **`tools/datadog_otel_to_elastic.py`** (Datadog→Elastic narrative) adds **OTLP logs** plus **`dd.*`-style** span attributes and metrics on the same path into the **managed OTLP** collector.

- **If `project_results.json` includes an OTLP URL** (`endpoints.motlp` / `otlp` / `otel`), bootstrap starts **Alloy + emitter** automatically.
- **Otherwise**, bootstrap runs **`tools/seed_workshop_telemetry.py`** (bulk **`logs-workshop-default`**, **`metrics-workshop-default`**, **`traces-workshop-default`**) so **Discover / ES|QL** have data. **Traces** do not always appear as a ready-made Data view — create one: **Stack Management → Data views → Create** → pattern **`traces-*`** → time field **`@timestamp`**. Curated **Applications**, **Infrastructure**, and **Hosts** experiences expect **OTLP** ( **`./scripts/start_workshop_otel.sh`** ) or **Elastic Agent** integrations, not bulk seed alone.
- You can still copy the mOTLP URL from **Kibana → Add data → OpenTelemetry**, `export WORKSHOP_OTLP_ENDPOINT=…`, then run **`./scripts/start_workshop_otel.sh`**.

Re-seed bulk docs (adds more; safe for demos):

```bash
cd /root/workshop && source ~/.bashrc
./scripts/seed_workshop_telemetry.sh
```

Restart **Alloy + emitter** (e.g. after setting **`WORKSHOP_OTLP_ENDPOINT`**):

```bash
cd /root/workshop && source ~/.bashrc
./scripts/start_workshop_otel.sh
```

**Check Alloy / OTLP locally** (processes, ports **4317/4318**, **`http://127.0.0.1:12345/metrics`**, log tails):

```bash
cd /root/workshop && source ~/.bashrc
./scripts/check_workshop_otel_pipeline.sh
```

**If `check_workshop_otel_pipeline.sh` is missing** (sandbox was created before that script landed), update the repo then re-run:

```bash
cd /root/workshop && git fetch origin && git reset --hard origin/main && chmod +x scripts/*.sh
# or: ./scripts/sync_workshop_from_git.sh   (after the pull above makes it exist)
```

**Paste-only diagnostics** (no script file needed):

```bash
source ~/.bashrc
echo "WORKSHOP_OTLP_ENDPOINT=${WORKSHOP_OTLP_ENDPOINT:+set}${WORKSHOP_OTLP_ENDPOINT:-unset}"
pgrep -af alloy || echo "no alloy"
pgrep -af otel_workshop_emitter || echo "no generic emitter"
ss -tlnp 2>/dev/null | grep -E '4317|4318|12345' || echo "ports not listening"
curl -sS --max-time 2 http://127.0.0.1:12345/metrics 2>&1 | head -3
ls -la /tmp/workshop-alloy.log /tmp/workshop-emitter.log 2>&1
```

**Nothing on 12345 / no log files** means Alloy never started—usually **`WORKSHOP_OTLP_ENDPOINT`** was not in **`project_results.json`** at bootstrap. Set it from **Kibana → Add data → OpenTelemetry**, `export WORKSHOP_OTLP_ENDPOINT='https://…'`, then **`./scripts/start_workshop_otel.sh`**. For **Discover / ES|QL** without OTLP, use **`./scripts/seed_workshop_telemetry.sh`**.

---

## Path A — Instruqt only (script publishes to Kibana)

**1. In the Instruqt Terminal tab**, load the workshop environment:

```bash
cd /root/workshop
source ~/.bashrc
```

**2. From `/root/workshop`**, run:

```bash
./scripts/migrate_grafana_dashboards_to_serverless.sh
```

This will:

1. Run **`tools/grafana_to_elastic.py`** on all **`assets/grafana/*.json`** → **`build/elastic-dashboards/*-elastic-draft.json`** (20 files).
2. Run **`tools/publish_grafana_drafts_kibana.py`** (the migrate script runs **`seed_workshop_telemetry.py`** first): **`POST /api/dashboards?apiVersion=1`** with **Markdown** plus **Lens** lines. ES|QL tries **`logs-workshop-default,metrics-workshop-default`**, then **`logs-*,metrics-*`**, then **`logs-*,metrics-*,traces-*`** so charts work even when **`traces-*`** breaks **`@timestamp`** in the union. **PromQL is not translated.** Optional **`WORKSHOP_ESQL_FROM`** (single **`FROM`**), **`WORKSHOP_ESQL_TIME_FIELD`**, **`WORKSHOP_MAX_LENS_PANELS`**, **`WORKSHOP_DISABLE_LENS=1`**. If the API rejects a payload, **import** + **PUT**, then note-only fallback.

Then open **Elastic Serverless → Dashboards** and confirm **~20** dashboards (titles end with **`(Grafana import draft)`**). Each dashboard should show **Markdown** plus **Lens** lines once **seed** (Path A) or OTLP/bulk ingest has created **`@timestamp`** fields. **Path B** from a laptop: run **`python3 tools/seed_workshop_telemetry.py`** against the same **`ES_URL`** *before* **`publish_grafana_drafts_kibana.py`**, or rely on OTLP + a compatible **`WORKSHOP_ESQL_FROM`**.

**If dashboards from an earlier run still look empty:** pull the latest workshop, then run **`./scripts/migrate_grafana_dashboards_to_serverless.sh`** again (`overwrite` replaces imports; new **`POST`** runs may add duplicate titles—delete old copies in the UI if needed).

**Same steps by hand** (optional):

```bash
cd /root/workshop && source ~/.bashrc
mkdir -p build/elastic-dashboards
python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
python3 tools/seed_workshop_telemetry.py
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
```

---

## Path B — Laptop + Cursor (Agent Skills)

Path B uses **two places**: the **Instruqt Terminal** (has the live Serverless URLs and keys in `~/.bashrc`) and **your laptop** (Cursor + a clone of this repo). Nothing in Path B requires you to hunt another section—all commands are below.

| Step | Where | What to do |
| --- | --- | --- |
| B1 | **Laptop** | Clone the repo; Grafana samples are **`assets/grafana/*.json`** (20 files). |
| B2 | **Instruqt Terminal** | `cd /root/workshop`, `source ~/.bashrc`, run the **`grep`** below; **select the printed lines**. |
| B3 | **Laptop — Cursor** | **Terminal → New Terminal**, **paste** those lines, **Enter** (sets **`KIBANA_URL`**, **`ES_API_KEY`**, etc. for that shell and for agent-run commands). |
| B4 | **Laptop — Cursor** | Install **[Elastic Agent Skills](https://github.com/elastic/agent-skills)** **`kibana-dashboards`**, attach it, open **`agent-skills/workshop-grafana-to-elastic/SKILL.md`**. |
| B5 | **Laptop — terminal** | Run **`grafana_to_elastic.py`** on the bundled **`assets/grafana/*.json`** (from the clone). |
| B5b | **Laptop — optional** | Download **any** dashboard JSON from the **[Grafana dashboard library](https://grafana.com/grafana/dashboards/)** (or export from your own Grafana **≥ 3.1**), convert, and publish — see **B5b** below. |
| B6 | **Optional** | Use the skill or chat to **`POST`/`PUT`** dashboards against Serverless, or run **`publish_grafana_drafts_kibana.py`**. API shapes: **[`docs/dashboards-api-getting-started.md`](../../docs/dashboards-api-getting-started.md)**. |

**B1 — clone (laptop):**

```bash
git clone git@github.com:poulsbopete/dashboard-alert-migration.git
cd dashboard-alert-migration
```

**B2 — print exports to copy (Instruqt Terminal tab):**

```bash
cd /root/workshop
source ~/.bashrc
# When bootstrap succeeded, ~/.bashrc exports: KIBANA_URL, ES_URL, ES_USERNAME, ES_PASSWORD, ES_API_KEY,
# ES_DEPLOYMENT_ID, WORKSHOP_ROOT. WORKSHOP_OTLP_ENDPOINT is often missing (Alloy not auto-started):
# copy the HTTPS ingest URL from Kibana → Add data → OpenTelemetry (host …ingest….elastic.cloud, not …es… or …kb…).
grep -E '^export (KIBANA_URL|ES_URL|ES_USERNAME|ES_PASSWORD|ES_API_KEY|ES_DEPLOYMENT_ID|WORKSHOP_ROOT|WORKSHOP_OTLP_ENDPOINT|WORKSHOP_OTLP_AUTH_HEADER)=' ~/.bashrc
```

**B3 — paste into Cursor (laptop):** Copy **only** what the terminal printed (lines starting with `export …`). Paste into Cursor’s integrated terminal and press **Enter**. Do **not** paste API keys or passwords into the AI chat.

**B4 — skills (laptop):** In Cursor, install **`kibana-dashboards`** from Elastic Agent Skills (`npx skills add elastic/agent-skills --skill kibana-dashboards` or your usual method), attach the skill, and open **`agent-skills/workshop-grafana-to-elastic/SKILL.md`** in this repo.

**B5 — build drafts (laptop, same repo as B1):**

```bash
cd dashboard-alert-migration   # your clone from B1
mkdir -p build/elastic-dashboards
python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
```

**B5b — optional: bring your own Grafana dashboard (community or internal)**

Customers often have favorites from the public gallery or a self-managed Grafana. You can **download the JSON** and run the **same** conversion pipeline as the bundled samples.

1. **Download:** In **[grafana.com/grafana/dashboards](https://grafana.com/grafana/dashboards/)**, open a dashboard → use the site’s **JSON download / export** (wording varies by page). Or in Grafana: **Share → Export → Save to file** (dashboard JSON).
2. **Save locally** in your clone, e.g. **`build/grafana-imports/`** or **`assets/grafana-imports/`**. Prefer a **gitignored** folder if the file is third-party — check the dashboard’s **license** before redistributing or committing it.
3. **Convert to Elastic drafts:**

   ```bash
   mkdir -p build/elastic-dashboards build/grafana-imports
   python3 tools/grafana_to_elastic.py build/grafana-imports/*.json --out-dir build/elastic-dashboards
   ```

   (Use a single filename instead of `*` if you only downloaded one dashboard.)

4. **Publish to Serverless** (with **`KIBANA_URL`** + **`ES_API_KEY`** from B3 pasted in the same shell):

   ```bash
   python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
   ```

   Ensure the project has **telemetry** (Instruqt seed / OTLP) so **ES|QL** panels validate; see the **Telemetry** section above.

**Reality check:** Gallery dashboards target **Prometheus, Loki, Tempo, Influx, CloudWatch**, etc. **`grafana_to_elastic.py`** pulls **PromQL** (and similar) into **migration notes** and builds **Kibana-ready drafts** with **Lens/ES|QL** placeholders — not a full automatic PromQL→ES|QL rewrite. Use **Edit** in Kibana and **`kibana-dashboards`** + Cursor to align queries with **your** `logs-*` / `metrics-*` / `traces-*` data.

**B6 — optional:** Use the agent + **`kibana-dashboards`** to **`POST`/`PUT`** dashboards on Serverless (**`KIBANA_URL`**), or rely on **`publish_grafana_drafts_kibana.py`** from **B5b**. Request/response patterns: **[`docs/dashboards-api-getting-started.md`](../../docs/dashboards-api-getting-started.md)**.

**Credentials note:** In Kibana (**Admin → API keys**), **`workshop-migration`** matches **`ES_API_KEY`** when bootstrap succeeded. If **`ES_API_KEY`** is empty in the grep output, create a key in the UI or rely on **`ES_USERNAME`** + **`ES_PASSWORD`**. For **Alloy / mOTLP** on the VM, add **`export WORKSHOP_OTLP_ENDPOINT='https://…ingest….elastic.cloud:443'`** to **`~/.bashrc`** (from **Add data → OpenTelemetry**), **`source ~/.bashrc`**, then **`./scripts/start_workshop_otel.sh`**; include that line in the grep output if you paste env into Cursor for laptop-side OTLP tooling.

**Security:** never commit API keys; keep secrets out of model prompts.

---

## Done

Click **Check** when **`build/elastic-dashboards/`** contains **20** files named **`*-elastic-draft.json`** from the **bundled** Grafana samples (**B5**).

- **Path A:** the script creates them under **`/root/workshop/build/...`** and publishes to Kibana for you.  
- **Path B:** the same folder appears under your **laptop clone** after **B5**; publishing to Kibana is optional (B6).  
- **B5b** (community downloads) is **additive** — extra **`*-elastic-draft.json`** files can coexist in **`build/elastic-dashboards/`**; the challenge still expects the **20** workshop drafts unless your facilitator changes the check.
