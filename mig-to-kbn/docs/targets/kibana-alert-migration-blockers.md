# Kibana Alert Migration Blockers

Snapshot date: `2026-04-01`

## Purpose

This document summarizes the alert and monitor families in our curated Grafana and
Datadog suites that we cannot currently migrate to Kibana with source-faithful
semantics.

It is intended as a submission-ready note for the Kibana / Elastic team.

Two scope notes matter:

- This is evidence-backed, not hypothetical. Every blocker below is represented by
  at least one concrete curated example and current generated artifact.
- This is not an exhaustive inventory of every possible source alert in Grafana or
  Datadog. It is the current blocker set proven by our curated suites and
  generation pipeline.

## Current Snapshot

All counts below come from the current generated standings in the local artifact
path `examples/alerting/generated/alert_support_standings.md`.

| Source | Total cases | Automated | Draft review | Manual required |
| --- | ---: | ---: | ---: | ---: |
| Grafana | 24 | 6 | 3 | 15 |
| Datadog | 35 | 10 | 4 | 21 |

Important Datadog nuance:

- The current raw Datadog results show `18` monitors where `.es-query` is the
  selected target rule type, but only `14` emitted `.es-query` payloads. The
  missing `4` are intentionally blocked because the translated query is still
  approximate and therefore not source-faithful. See the local artifact path
  `examples/alerting/generated/datadog/monitor_migration_results.json`.

Top blockers from the current generated artifacts:

| Source | Blocker | Cases |
| --- | --- | ---: |
| Grafana | No source-faithful target query could be produced | 15 |
| Grafana | no-data policy `NoData` may not have exact Kibana equivalent | 15 |
| Datadog | No source-faithful target query could be produced | 17 |
| Datadog | rollup interval is approximated in ES\|QL | 2 |
| Datadog | Datadog formula monitor requires manual review outside the current exact subset | 2 |
| Datadog | rate semantics approximated with delta over observed bucket span | 1 |
| Datadog | default_zero semantics are approximated in ES\|QL | 1 |
| Datadog | Datadog recovery/trigger threshold windows not directly portable | 1 |
| Datadog | Datadog require_full_window semantics differ from Kibana evaluation | 1 |

## Evidence Base

### Internal Repo Evidence

- Curated standings: `examples/alerting/generated/alert_support_standings.md`
- Structured standings JSON: `examples/alerting/generated/alert_support_standings.json`
- Grafana raw migration results: `examples/alerting/generated/grafana/alert_migration_results.json`
- Datadog raw migration results: `examples/alerting/generated/datadog/monitor_migration_results.json`
- Datadog per-monitor comparison details: `examples/alerting/generated/datadog/monitor_comparison_results.json`
- Roadmap note for current `calendar_shift()` boundaries:
  [`docs/roadmap/alert-migration-next-steps.md`](../roadmap/alert-migration-next-steps.md)
- Local Kibana ES|QL capability snapshot used by this repo:
  [`docs/targets/kibana-esql-capabilities.md`](./kibana-esql-capabilities.md)

### Public Vendor References

- Elastic:
  [Elasticsearch query rule](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-type-es-query),
  [Index threshold rule](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-type-index-threshold),
  [Custom threshold rule](https://www.elastic.co/docs/solutions/observability/incident-management/create-custom-threshold-rule),
  [Metric threshold rule](https://www.elastic.co/docs/solutions/observability/incident-management/create-metric-threshold-rule),
  [ES|QL date-time functions](https://www.elastic.co/docs/reference/query-languages/esql/functions-operators/date-time-functions)
- Grafana:
  [No Data and Error states](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rules/state-and-health/)
- Prometheus:
  [Querying basics](https://prometheus.io/docs/prometheus/latest/querying/basics/),
  [Operators](https://prometheus.io/docs/prometheus/latest/querying/operators/),
  [Functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)
- Datadog:
  [Monitor Types](https://docs.datadoghq.com/monitors/types/),
  [Composite Monitor](https://docs.datadoghq.com/monitors/types/composite/),
  [Metric Type Modifiers](https://docs.datadoghq.com/metrics/custom_metrics/type_modifiers/?tab=count),
  [Rollup](https://docs.datadoghq.com/dashboards/functions/rollup/),
  [Interpolation](https://docs.datadoghq.com/dashboards/functions/interpolation/),
  [Interpolation and the Fill Modifier](https://docs.datadoghq.com/metrics/guide/interpolation-the-fill-modifier-explained/),
  [Timeshift / calendar_shift](https://docs.datadoghq.com/dashboards/functions/timeshift/),
  [Monitor API Options](https://docs.datadoghq.com/monitors/guide/monitor_api_options/)

## Grafana: Cases We Cannot Currently Migrate Exactly

### Summary

Grafana currently has `15` `manual_required` cases out of `24`.

Those `15` blockers are dominated by two things:

- advanced PromQL semantics outside the current exact migration boundary
- non-PromQL datasource alert families

The recurring semantic loss on top of those query blockers is Grafana's
documented `No Data` behavior, which is not an exact match for the generic
Kibana rule path we emit today.

### Blocker Buckets

| Bucket | Cases | Example alerts | Why the current migration keeps them manual |
| --- | ---: | --- | --- |
| Advanced PromQL semantics outside the current exact boundary | 13 | `Pinned timestamp CPU`, `Subquery request rate`, `Label replace CPU`, `CPU unless network down` | These alerts rely on PromQL semantics that are documented by Prometheus but not yet preserved by our exact alert-emission path. In current artifacts, all of these remain blocked with `No source-faithful target query could be produced`. |
| Non-PromQL datasource alert families | 2 | `Error log spike`, `Graphite queue depth` | The current target path is built around Kibana query rules over Elasticsearch data. No source-faithful target query is produced for Loki / LogQL or Graphite alert expressions in the current implementation. |
| Grafana `NoData` / `Error` semantics mismatch | cross-cutting | affects all 15 manual Grafana cases, plus some emitted rules | Grafana-managed alert rules have documented `No Data` and `Error` states, including `DatasourceNoData` / `DatasourceError` behaviors and configurable transitions. Our current Kibana query-rule path does not provide a generic one-to-one equivalent for those semantics. |

### The Blocked PromQL Families In The Current Curated Suite

The current detailed Grafana blocker families are:

- `PromQL @ modifier` via `Pinned timestamp CPU`
- `PromQL subquery` via `Subquery request rate`
- `PromQL changes()` via `Boot time changed`
- `PromQL label_replace()` via `Label replace CPU`
- `PromQL label_join()` via `Label join CPU`
- `PromQL scalar()` via `Scalar node time`
- `PromQL metric-to-metric comparison` via `Vector comparison memory`
- `PromQL nested comparison` via `Nested comparison count`
- `PromQL or operator` via `CPU or vector fallback`
- `PromQL unless operator` via `CPU unless network down`
- broader `PromQL topk()` shapes via `Topk CPU usage`
- broader `PromQL bottomk()` shapes via `Bottom CPU usage`
- `PromQL known server bug pattern` via `Filesystem planner bug candidate`

Why these remain blocked:

- Prometheus documents direct selector-time modifiers such as `@` and `offset`,
  subqueries, vector matching, set operators (`or`, `unless`), and comparison
  behavior in [Querying basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)
  and [Operators](https://prometheus.io/docs/prometheus/latest/querying/operators/).
- Prometheus documents `changes()`, `label_replace()`, `label_join()`, and
  `scalar()` in [Functions](https://prometheus.io/docs/prometheus/latest/querying/functions/).
- For these families, the migration pipeline currently cannot guarantee a
  source-faithful emitted Kibana rule payload. We therefore keep them
  `manual_required` instead of emitting a query that may look plausible but drift
  semantically.

Important nuance:

- We already support a narrow exact `topk()` / `bottomk()` subset for instant-like
  ranking alerts. The blocked `topk()` / `bottomk()` cases are the broader shapes
  that still fall outside that safe subset.

### Non-PromQL Grafana Families

The current curated non-PromQL blocker families are:

- `Loki / LogQL` via `Error log spike`
- `Graphite datasource` via `Graphite queue depth`

These are not simple threshold-mapping gaps. They are source-language gaps. The
current migration pipeline emits Kibana query rules over Elasticsearch data, but
it does not yet provide a source-faithful alert-query translation path for Loki
or Graphite alert expressions.

### Important Grafana Gaps Even When A Rule Is Emitted

These are not always hard blockers, but they are still relevant for Kibana team
discussion because they represent parity gaps:

- Grafana documents `No Data` and `Error` as first-class alert states with
  configurable transitions and separate `DatasourceNoData` /
  `DatasourceError` alerts:
  [Grafana docs](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rules/state-and-health/).
- Elastic does document no-data handling for some Observability rule types such
  as [custom threshold](https://www.elastic.co/docs/solutions/observability/incident-management/create-custom-threshold-rule)
  and [metric threshold](https://www.elastic.co/docs/solutions/observability/incident-management/create-metric-threshold-rule),
  but our generic translated Grafana alert path currently emits
  [Elasticsearch query rules](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-type-es-query),
  which do not give us an exact Grafana-style `DatasourceNoData` /
  `DatasourceError` parity layer.
- Legacy dashboard alerts also require manual mapping from Grafana notification
  channel UIDs to Kibana connectors.
- Dashboard-linked Grafana annotations still require manual Kibana linkage in the
  current emitted rules.

## Datadog: Cases We Cannot Currently Migrate Exactly

### Summary

Datadog currently has `21` `manual_required` cases out of `35`.

Those `21` blockers fall into four main categories:

- translated candidate query exists, but we intentionally do not emit because it
  is approximate
- formula / time-shift boundaries where no source-faithful query is currently
  produced
- analytical monitor families with algorithmic semantics
- Datadog product-specific monitor families that do not map to generic Kibana
  query rules

### Blocker Buckets

| Bucket | Cases | Example monitors | Why the current migration keeps them manual |
| --- | ---: | --- | --- |
| Approximation-blocked metric/query alerts with selected `.es-query` candidate but no emitted payload | 4 | `Checkout request rate is high`, `CPU rollup is high`, `CrashloopBackOff`, `CPU exclude_null rollup wrapper` | The translator can produce an ES\|QL candidate, but current semantics are still approximate for `as_rate()`, `rollup()`, and `default_zero()`. We intentionally block payload emission rather than claiming exact support. |
| Formula / time-shift boundaries with no source-faithful query | 2 | `[Redis] High memory consumption`, `CPU calendar_shift timezone-sensitive` | Exact automation currently covers only a stricter Datadog formula subset. Broader arithmetic formulas and DST-sensitive `calendar_shift()` are still manual. |
| Analytical monitor families | 3 | anomaly, forecast, outlier examples | Datadog defines these as algorithmic monitor types with historical / predictive / peer-comparison semantics. The current Kibana rule types we target do not provide a source-faithful generic equivalent. |
| Product-specific / manual-only monitor families | 12 | composite, service check, event, APM, RUM, Synthetics, CI, SLO, audit, cost, network, watchdog | These rely on Datadog product surfaces, cross-monitor state, or status semantics that do not map cleanly to the generic Kibana query rules we emit today. |

### The Four Translated-But-Blocked Datadog Cases

These are especially important because they show where Kibana is close but still
not exact enough for automatic migration.

| Source feature | Example | Why we still do not emit the rule |
| --- | --- | --- |
| `as_rate()` | `Checkout request rate is high` | Datadog documents `as_rate()` as disabling interpolation, forcing `SUM`, and normalizing by the sampling interval. Our current ES\|QL rewrite computes a rate from observed delta over observed bucket span, which is close but not guaranteed identical. |
| `rollup()` | `CPU rollup is high` | Datadog documents rollup interval and rollup alignment as first-class semantics, and explicitly warns that rollups in monitors can misalign with evaluation windows. Our current ES\|QL rewrite does not preserve Datadog's exact rollup-boundary monitor behavior. |
| `default_zero()` | `[Kubernetes] Pod {{pod_name.name}} is CrashloopBackOff on namespace {{kube_namespace.name}}` | Datadog documents `default_zero()` as filling sparse intervals using `0` or interpolation and notes that it can resolve monitors before they enter no-data. A simple `COALESCE(..., 0)` rewrite is not a full monitor-semantic equivalent. |
| `exclude_null()` wrapped around `rollup()` | `CPU exclude_null rollup wrapper` | `exclude_null()` itself is supportable in a narrow exact subset, but the wrapped `rollup()` still makes the monitor approximate, so the full rule remains manual. |

Relevant Datadog references:

- `as_rate()` / `as_count()` semantics:
  [Metric Type Modifiers](https://docs.datadoghq.com/metrics/custom_metrics/type_modifiers/?tab=count)
- `rollup()` semantics and monitor-window warning:
  [Rollup](https://docs.datadoghq.com/dashboards/functions/rollup/)
- `default_zero()` and interpolation semantics:
  [Interpolation](https://docs.datadoghq.com/dashboards/functions/interpolation/),
  [Interpolation and the Fill Modifier](https://docs.datadoghq.com/metrics/guide/interpolation-the-fill-modifier-explained/)

### Formula And `calendar_shift()` Boundaries

The current curated manual Datadog formula / time-shift blockers are:

- broader arithmetic formula monitor:
  `[Redis] High memory consumption`
- DST-sensitive `calendar_shift()`:
  `CPU calendar_shift timezone-sensitive`

Current exact boundary:

- arithmetic formulas over the current exact `as_count()` subset
- single-query shifted formulas such as `week_before()`, `timeshift()`, and
  `calendar_shift()` in `UTC` or stable-offset IANA time zones for day / week /
  month shifts

Why the DST `calendar_shift()` case is still manual:

- Datadog documents `calendar_shift()` as taking day / week / month shifts plus
  an IANA time zone code:
  [Timeshift / calendar_shift](https://docs.datadoghq.com/dashboards/functions/timeshift/).
- The current public Elastic ES\|QL date-time function surface documents functions
  such as `DATE_DIFF`, `DATE_TRUNC`, `DATE_FORMAT`, `DATE_PARSE`, and `NOW`:
  [ES|QL date-time functions](https://www.elastic.co/docs/reference/query-languages/esql/functions-operators/date-time-functions).
- We do not currently have a documented source-faithful way to express
  Datadog-style civil-time `calendar_shift()` semantics across DST-observing or
  otherwise offset-changing IANA time zones in the generic query path we emit.
- This exact boundary is also captured in the repo roadmap note:
  [`docs/roadmap/alert-migration-next-steps.md`](../roadmap/alert-migration-next-steps.md).

### Analytical Datadog Monitor Families

The current curated analytical blockers are:

- anomaly monitor:
  `[Postgres] Replication delay is abnormally high on {{host.name}}`
- forecast monitor:
  `Forecasted CPU saturation`
- outlier monitor:
  `Outlier CPU host`

Why these remain blocked:

- Datadog documents anomaly, forecast, and outlier as distinct monitor types in
  [Monitor Types](https://docs.datadoghq.com/monitors/types/).
- The anomaly example in our suite also carries Datadog-specific
  `threshold_windows` and `require_full_window` semantics, which are documented in
  [Monitor API Options](https://docs.datadoghq.com/monitors/guide/monitor_api_options/).
- Elastic's current documented generic rule types that we target
  ([Elasticsearch query](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-type-es-query),
  [Index threshold](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-type-index-threshold),
  [Custom threshold](https://www.elastic.co/docs/solutions/observability/incident-management/create-custom-threshold-rule))
  provide thresholds, aggregations, grouping, and equations, but not a
  source-faithful generic equivalent for Datadog's algorithmic anomaly /
  forecast / outlier semantics in the migration target surface we use today.

### Product-Specific Datadog Monitor Families

The current curated manual-only Datadog families are:

- `Composite monitors`
- `Service check monitors`
- `Event alerts`
- `APM monitors`
- `RUM monitors`
- `Synthetics monitors`
- `CI monitors`
- `SLO monitors`
- `Audit monitors`
- `Cost monitors`
- `Network monitors`
- `Watchdog monitors`

Why these remain blocked:

- Datadog documents these as distinct monitor families with their own semantics in
  [Monitor Types](https://docs.datadoghq.com/monitors/types/).
- Composite monitors are particularly strong evidence of a target-surface gap:
  Datadog documents them as Boolean expressions over other monitor IDs with their
  own group-matching and no-data behavior:
  [Composite Monitor](https://docs.datadoghq.com/monitors/types/composite/).
- Service checks have their own status-count threshold semantics documented in
  [Monitor API Options](https://docs.datadoghq.com/monitors/guide/monitor_api_options/).
- The other families depend on Datadog product-specific data models or event
  streams rather than generic metric or log threshold queries. In the current
  migration target path, there is no source-faithful one-size-fits-all mapping to
  generic Kibana query rules.

### Important Datadog Gaps Even When A Rule Is Emitted

These are not always hard blockers, but they are still parity gaps worth calling
out to the Kibana team:

- The currently automated `High CPU on web hosts` monitor still carries losses for
  `notify_no_data`, `renotify_interval`, `evaluation_delay`,
  `require_full_window`, and notification-handle-to-connector mapping in the
  current emitted rule.
- Datadog documents those source-side monitor options in
  [Monitor API Options](https://docs.datadoghq.com/monitors/guide/monitor_api_options/).
- Some Datadog log alerts are only `draft_requires_review`, not because Kibana
  lacks a basic rule type, but because we still require human validation before
  enablement.

## What Looks Missing Or Insufficient On The Kibana / Elastic Side

These are the most actionable asks suggested by the current blocker set.

### 1. Broader Alert-Time PromQL Support

For Grafana unified alerts, the cleanest unlock would be a first-class PromQL
alert surface, or broader alert-time support for native `PROMQL`, that preserves
documented Prometheus semantics such as:

- `@` and `offset`
- subqueries
- vector matching modifiers such as `on`, `ignoring`, `group_left`, `group_right`
- set operators such as `or` and `unless`
- label mutation functions such as `label_replace()` and `label_join()`
- `changes()` and `scalar()`
- vector-to-vector and nested comparison behavior

### 2. Exact Metric-Semantic Primitives For Alerting

For Datadog metric monitors, current ES\|QL is often close, but not always exact,
for semantics such as:

- `as_rate()`
- `rollup()`
- `default_zero()`
- evaluation-window alignment tied to monitor semantics

The current blocker set suggests a need for exact alert-time primitives rather
than approximate query rewrites.

### 3. Timezone-Aware Civil-Time Arithmetic

Datadog documents `calendar_shift()` with IANA time zones, including DST-observing
zones. The current public ES\|QL date-time surface does not give us a documented,
source-faithful equivalent for alert queries over DST-sensitive civil-time
windows.

### 4. Generic No-Data / Error / Evaluation Parity

Several source-side semantics do not map cleanly today:

- Grafana `No Data` / `Error` behavior and companion datasource alerts
- Datadog `require_full_window`
- Datadog `evaluation_delay`
- Datadog `threshold_windows`
- Datadog `renotify_interval`

Elastic does have some no-data behavior in some Observability rule types, but the
current translated-rule path does not provide a generic parity layer for all of
these source semantics.

### 5. First-Class Support For Higher-Level Alert Families

The manual-only Datadog families suggest a need for either:

- first-class target rule families for composite / service-check / product-level
  monitor types, or
- an extension mechanism richer than a generic query rule

The strongest examples are:

- composite monitors, which are monitor-of-monitors expressions
- service checks, which are status-count semantics rather than generic numeric
  query thresholds
- anomaly / forecast / outlier families, which are algorithmic monitor types

## Likely Repo-Side Vs Platform-Side Work

This distinction may help when triaging the blocker list.

Likely still improvable mostly in this repo:

- broader but still exact safe subsets of existing supported rule families
- more safe fallback ES\|QL shapes where semantics can be proved exact
- more metadata / connector automation around already-emitted rules

Likely dependent on broader Kibana / Elastic surface changes:

- advanced source-faithful PromQL alert execution
- exact Datadog-style rate / rollup / default-zero alert semantics
- DST-aware `calendar_shift()` equivalence
- composite monitor parity
- service-check parity
- anomaly / forecast / outlier parity
- a generic translation target for product-specific Datadog monitor families

## Short Submission Summary

If this needs to be reduced to a short handoff paragraph for the Kibana team, the
core message is:

- Grafana blockers are mostly advanced PromQL semantics plus Grafana-managed
  no-data behavior.
- Datadog blockers split between approximate-but-close metric semantics
  (`as_rate()`, `rollup()`, `default_zero()`), algorithmic monitor types
  (anomaly / forecast / outlier), and product-specific monitor families
  (composite, service check, APM, RUM, Synthetics, CI, SLO, audit, cost,
  network, watchdog, event).
- The highest-value unlocks on the Kibana / Elastic side would be broader
  alert-time PromQL support, exact alert-time metric semantics, timezone-aware
  civil-time shifts, and richer first-class alert families beyond generic query
  rules.
