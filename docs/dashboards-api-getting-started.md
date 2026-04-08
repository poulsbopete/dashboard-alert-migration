# Dashboards API — getting started (workshop)

This note summarizes the **Kibana Dashboards HTTP API** for **Observability / Analytics Serverless** and self-managed Kibana. It is adapted from Elastic’s *Dashboards API — Getting started* guide for use in this repo: same endpoints and patterns, without embedded screenshots or organization-enablement steps.

**Official references**

- [Kibana Serverless API — Saved objects (export / import)](https://www.elastic.co/docs/api/doc/serverless/group/endpoint-saved-objects) — what **this track’s** `tools/publish_grafana_drafts_kibana.py` uses for bulk empty-dashboard shells (`POST /api/saved_objects/_import`).
- **Dashboards API** (declarative dashboards, Lens-oriented): `GET|POST|PUT|DELETE /api/dashboards?apiVersion=1` as below.
- Public roadmap / panel coverage: [elastic/kibana#240171](https://github.com/elastic/kibana/issues/240171).

## How this fits the migration workshop

| Goal | Mechanism |
| --- | --- |
| **20 dashboards** + migration notes (Lab 1 Path A) | **Dashboards API** — `tools/publish_grafana_drafts_kibana.py` uses **`POST /api/dashboards?apiVersion=1`** (Markdown panel for notes), with **saved-objects import** only as a per-object fallback. |
| **Rich dashboards** (Lens panels, grid, time range) | Same **Dashboards API** — `POST/PUT /api/dashboards?apiVersion=1` (curl, Dev Tools, Terraform, or **[`kibana-dashboards`](https://github.com/elastic/agent-skills)** Agent Skill). |

In the Instruqt sandbox, use `KIBANA_URL`, `ES_API_KEY` (or `ES_USERNAME` / `ES_PASSWORD`) from `source ~/.bashrc`. Through **es3-api**, Kibana is reached at the proxied URL (port **8080** in the **Elastic Serverless** tab).

## Environment variables (curl)

Use the **Kibana** base URL (not Elasticsearch).

```bash
export MY_SERVERLESS_KIBANA="https://<your-serverless-kibana-host>:443"
# Workshop / Instruqt: often same as KIBANA_URL after sourcing ~/.bashrc

export ELASTIC_API_KEY="<your-api-key>"
# Or use ES_API_KEY if you already exported it from the sandbox
```

## Headers

Typical **curl** headers for the Dashboards API:

- `Authorization: ApiKey <key>` (or Basic auth where allowed)
- `Content-Type: application/json`
- `Elastic-Api-Version: 1`
- `kbn-xsrf: true` (or `kbn-xsrf: "true"`)

Some environments (preview / internal testing) also require `X-Elastic-Internal-Origin`. Values vary by release; follow the guide shipped with your project or Dev Tools examples if requests return 400 until that header is set.

**Dev Tools** shorthand:

```text
GET kbn:/api/dashboards/{DASHBOARD_ID}?apiVersion=1
```

## CRUD overview

### Get a dashboard

```http
GET /api/dashboards/{DASHBOARD_ID}?apiVersion=1
```

```bash
curl -sS -X GET "$MY_SERVERLESS_KIBANA/api/dashboards/{DASHBOARD_ID}?apiVersion=1" \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Elastic-Api-Version: 1" \
  -H "kbn-xsrf: true"
```

The JSON response includes `id`, `data` (title, options, panels, query, …), `meta`, `spaces`, and optional **`warnings`** for fields the API does not map yet (for example dropped keys).

### Create a dashboard

```http
POST /api/dashboards?apiVersion=1
```

Body: at minimum **`title`**; **`panels`** is a list of panel objects with **`grid`** (`x`, `y`, `w`, `h`) and type-specific **`config`** / **`attributes`** (see Lens xy charts, Markdown, etc. in the full Elastic guide).

### Update a dashboard

```http
PUT /api/dashboards/{DASHBOARD_ID}?apiVersion=1
```

Put the **`id` only in the URL**, not in the body (including `id` in the body fails). Required body fields match what you would send for create for a full replacement payload.

### Delete a dashboard

```http
DELETE /api/dashboards/{DASHBOARD_ID}?apiVersion=1
```

## Spaces

You **cannot** “move” a dashboard with the same `id` to another space in one step; use **get → create in target space** (and delete in the source if needed).

Prefix the path with **`/s/{SPACE_ID}`**:

| Operation | Path pattern |
| --- | --- |
| Get | `GET /s/{SPACE_ID}/api/dashboards/{DASHBOARD_ID}?apiVersion=1` |
| Create | `POST /s/{SPACE_ID}/api/dashboards?apiVersion=1` |
| Update | `PUT /s/{SPACE_ID}/api/dashboards/{DASHBOARD_ID}?apiVersion=1` |
| Delete | `DELETE /s/{SPACE_ID}/api/dashboards/{DASHBOARD_ID}?apiVersion=1` |

`SPACE_ID` is visible in Kibana **Stack Management → Spaces**.

## Other clusters

Send requests to the **destination** Kibana base URL (for example `https://other-kibana:5601/api/dashboards?apiVersion=1`).

## Copying a dashboard between spaces (pattern)

1. **GET** the dashboard in the source space/context.
2. **POST** to the target space with the returned **`data`** (title, panels, time range, options, …), adjusting only what you need.
3. Optionally **DELETE** the source dashboard.

If the POST assigns a new id, update any hard-coded links accordingly.

## Dashboards API vs standalone Lens

For automation, use **only** the Dashboards API:

- **`POST` / `PUT /api/dashboards?apiVersion=1`** — create or replace a dashboard and its panels in one request.

Do **not** use the **standalone Lens** paths for publishing workshop dashboards:

- No **`POST /api/saved_objects/lens/...`** (often blocked on Serverless anyway).
- No **`POST /api/saved_objects/_import`** of standalone **`type: lens`** rows when you can express the viz inline on the dashboard instead.

**Important naming detail:** a Dashboards API payload may still contain panel objects with **`"type": "lens"`** and **`config.attributes`** (`metric`, `xy`, …). That is the **embeddable shape inside the dashboard document**, not a separate Lens API call. Kibana’s current publisher path for ES|QL charts uses this wrapper; a root-level **`"type": "metric"`** / **`"type": "xy"`** panel shape is a different schema tier and may not be accepted on all stacks—see `tools/publish_grafana_drafts_kibana.py` (`build_esql_xy_panels`).

## Supported panels (summary)

Not every dashboard panel type is API-complete yet. Unsupported panels may be **dropped on GET** and listed under **`warnings`**.

**Generally supported**

- Lens charts (including ES|QL-backed and non-ES|QL)
- Collapsible sections
- Markdown
- KQL queries
- Filter pills
- Controls (pinned and unpinned)
- Drilldowns

**Work in progress / later**

- Discover sessions (WIP toward tech preview)
- Links panel, ML panels, O11y panels (SLOs, etc.), Vega (planned / later milestones)

Track updates in [elastic/kibana#240171](https://github.com/elastic/kibana/issues/240171).

## Hosted deployments vs Serverless

For **Elastic Cloud hosted** (non-serverless) deployments, older previews sometimes required Kibana user settings / feature flags (for example Lens API format). **Serverless** is the recommended target for the latest Dashboards API behavior; this workshop’s Instruqt track uses **Observability Serverless** via **es3-api**.

## Terraform

The upstream *Getting started* guide includes Terraform examples for managing dashboards as code. See Elastic’s provider documentation and that guide’s “Testing the Terraform provider” section when you outgrow curl and want GitOps-style workflows.
