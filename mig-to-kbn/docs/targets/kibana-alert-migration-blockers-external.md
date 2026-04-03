# External Report: Kibana Alert Migration Blockers For Grafana And Datadog

Snapshot date: `2026-04-02`

## Purpose

This document is an external-facing summary of the alert and monitor families that
we cannot currently migrate into Kibana with source-faithful semantics.

It is written so it can be pasted into a GitHub issue, design discussion, or
email thread without any internal repo references.

## Scope

- This report is based on a curated validation suite containing `27` Grafana alert
  cases and `35` Datadog monitor cases.
- It distinguishes between:
  exact automatic migration,
  translation that still needs human review before enablement,
  and cases that still require manual handling.
- The standard applied here is semantic fidelity, not "close enough" query
  similarity. If a translated Kibana rule would materially drift from the source
  system's documented behavior, the case is treated as blocked for automatic
  migration.

## Executive Summary

| Source | Total cases | Exact automatic migration | Review before enablement | Manual handling still required |
| --- | ---: | ---: | ---: | ---: |
| Grafana | 27 | 6 | 5 | 16 |
| Datadog | 35 | 11 | 4 | 20 |

The highest-level findings are:

- Grafana blockers are dominated by advanced PromQL semantics and by Grafana's
  first-class `No Data` / `Error` alert-state model.
- Datadog blockers split into four broad groups:
  metric semantics that are close but not exact in ES|QL,
  formula and civil-time semantics that are not fully portable,
  algorithmic monitor families such as anomaly / forecast / outlier,
  and product-specific monitor types such as composite, service check, APM, RUM,
  Synthetics, CI, SLO, audit, cost, network, and Watchdog.
- A key Datadog nuance is that some monitors already have a plausible Kibana
  query candidate, but we still intentionally do not emit an automatic rule
  because the remaining semantics are approximate.

## Why This Matters

There is already a strong base of translatable alert content:

- simple Grafana threshold alerts over native PromQL
- a narrow exact subset of Grafana `topk()` / `bottomk()` alerts
- warning-free Datadog metric and log threshold monitors
- a strict exact subset of Datadog `as_count()` formulas, aligned unshifted
  gauge-arithmetic formulas, and selected shifted comparisons

The remaining blockers are therefore not mostly "missing parser coverage". They
are primarily product-parity and semantic-equivalence gaps.

## Grafana: Current Exact-Migration Blockers

### Summary

Grafana currently has `16` cases that still require manual handling out of the
`27` validated alert examples.

The blockers group into three buckets:

| Bucket | Cases | What is missing |
| --- | ---: | --- |
| Advanced PromQL semantics outside the current exact boundary | 13 | Source-faithful handling of selector-time modifiers, subqueries, vector matching, set operators, label-mutation functions, and certain comparison patterns |
| Non-PromQL datasource alert families | 3 | A source-faithful alert-query path for Loki / LogQL and Graphite |
| Grafana-managed alert state semantics | cross-cutting | A generic Kibana equivalent for Grafana `No Data`, `Error`, and the related datasource alert behavior |

### 1. Advanced PromQL Semantics

The blocked Grafana PromQL families in the current validated set are:

- `@` modifier
- subqueries
- `changes()`
- `label_replace()`
- `label_join()`
- `scalar()`
- vector-to-vector comparison
- nested comparison
- `or`
- `unless`
- broader `topk()` shapes outside the currently safe subset
- broader `bottomk()` shapes outside the currently safe subset
- one filesystem expression family that appears to hit a planner/runtime issue in
  the current target path rather than a simple syntax gap

Concrete blocked examples include:

- `Pinned timestamp CPU`
- `Subquery request rate`
- `Boot time changed`
- `Label replace CPU`
- `Label join CPU`
- `Scalar node time`
- `Vector comparison memory`
- `Nested comparison count`
- `CPU or vector fallback`
- `CPU unless network down`
- `Topk CPU usage`
- `Bottom CPU usage`

Why these remain blocked:

- Prometheus explicitly documents selector-time modifiers such as `offset` and
  `@`, range subqueries, and the ordering rules around those modifiers in
  [Querying basics](https://prometheus.io/docs/prometheus/latest/querying/basics/).
- Prometheus explicitly documents vector matching, `on`, `ignoring`,
  `group_left`, `group_right`, as well as set operators such as `or` and
  `unless`, in [Operators](https://prometheus.io/docs/prometheus/latest/querying/operators/).
- Prometheus explicitly documents `changes()`, `label_replace()`,
  `label_join()`, and `scalar()` in
  [Functions](https://prometheus.io/docs/prometheus/latest/querying/functions/).

These constructs are not just syntactic flourishes. They change which series are
selected, how timestamps are interpreted, how label sets are matched, which
series survive comparisons, and how values are transformed. That makes them poor
candidates for approximate rewrites in alerting.

Important nuance:

- A narrow exact subset of `topk()` / `bottomk()` alerting is already supportable
  when the query shape is effectively "instant-like last-value ranking".
- The still-blocked cases are the broader shapes where the ranking semantics,
  source query form, or alert reduction path are not yet proven equivalent.

### 2. Non-PromQL Grafana Datasource Alerts

The current curated non-PromQL blockers are:

- Loki / LogQL
- Graphite

Concrete examples:

- `Error log spike`
- `High Error Rate in Logs`
- `Graphite queue depth`

These are blocked for a straightforward reason: the current target path is built
around Kibana rules running against Elasticsearch-backed data. A source-faithful
automatic migration for Grafana alert queries written in LogQL or Graphite
requires either:

- a first-class target query/runtime surface that matches those source languages,
  or
- a source-faithful translation layer that preserves alert semantics rather than
  just dashboard-query intent

Today, that exact alerting path is not available.

### 3. Grafana `No Data` / `Error` Semantics

Even some Grafana cases that do emit a Kibana rule payload still have parity gaps
around alert-state behavior.

Why this matters:

- Grafana documents `No Data` and `Error` as first-class alert states for
  Grafana-managed alerts:
  [No Data and Error states](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rules/state-and-health/).
- Grafana also documents configurable behavior for those states, including
  transitions to `Alerting`, `Normal`, `Error`, or `Keep Last State`, plus
  companion `DatasourceNoData` and `DatasourceError` alerts.

This is materially richer than a plain threshold query over a time window.

Elastic does document some no-data behavior in observability rule types such as:

- [Create a custom threshold rule](https://www.elastic.co/docs/solutions/observability/incident-management/create-custom-threshold-rule)
- [Create a metric threshold rule](https://www.elastic.co/docs/solutions/observability/incident-management/create-metric-threshold-rule)

However, the generic rule surface typically used for translated query alerts is:

- [Elasticsearch query rule](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-type-es-query)

That rule type is useful for query matching, grouping, and thresholds, but it is
not a generic drop-in equivalent for Grafana's documented `DatasourceNoData` /
`DatasourceError` model.

### Grafana-Side Ask To Kibana

The clearest coverage unlocks for Grafana alert migration are:

- broader alert-time PromQL support that preserves documented PromQL semantics
- a better generic parity layer for source `No Data` / `Error` behavior
- richer support for non-PromQL alert query families

## Datadog: Current Exact-Migration Blockers

### Summary

Datadog currently has `20` cases that still require manual handling out of the
`35` validated monitor examples.

The blockers group into four buckets:

| Bucket | Cases | What is missing |
| --- | ---: | --- |
| Query candidate exists, but exact semantics are still approximate | 4 | Exact equivalents for `as_rate()`, `rollup()`, `default_zero()`, and related wrapped shapes |
| Formula and civil-time boundaries | 1 | DST-safe `calendar_shift()` equivalence |
| Algorithmic monitor families | 3 | Generic source-faithful equivalents for anomaly / forecast / outlier monitor behavior |
| Product-specific monitor families | 12 | First-class parity for composite, service-check, and other product-level monitor types |

## Datadog: Cases With A Candidate Query But No Automatic Rule Emission

These are especially important because they show where the translation is already
close, but still not safe enough to automate.

### 1. `as_rate()`

Example:

- `Checkout request rate is high`

Why it is blocked:

- Datadog documents `as_rate()` as a metric-type modifier that disables
  interpolation, forces `SUM`, and normalizes by the sampling interval:
  [Metric Type Modifiers](https://docs.datadoghq.com/metrics/custom_metrics/type_modifiers/?tab=count).
- A naive or approximate ES|QL rewrite can compute a rate-like value, but that is
  not automatically the same as Datadog's documented monitor-time semantics.

This is therefore not a parsing gap. It is an exact-rate-semantics gap.

### 2. `rollup()`

Example:

- `CPU rollup is high`

Why it is blocked:

- Datadog documents `.rollup()` as controlling both aggregation method and
  time-bucket interval:
  [Rollup](https://docs.datadoghq.com/dashboards/functions/rollup/).
- Datadog also explicitly warns that rollups in monitors can misalign with the
  evaluation window if not handled carefully.

In practice, this means an ES|QL query that looks numerically similar may still
not preserve the source monitor's exact bucket-boundary semantics.

### 3. `default_zero()`

Example:

- `[Kubernetes] Pod {{pod_name.name}} is CrashloopBackOff on namespace {{kube_namespace.name}}`

Why it is blocked:

- Datadog documents `default_zero()` as filling empty intervals with `0` or, when
  interpolation is active, with interpolated values:
  [Interpolation](https://docs.datadoghq.com/dashboards/functions/interpolation/),
  [Interpolation and the Fill Modifier](https://docs.datadoghq.com/metrics/guide/interpolation-the-fill-modifier-explained/).
- Datadog explicitly notes that this affects monitor behavior and can resolve a
  monitor before it enters a no-data state.

A simple `COALESCE(..., 0)` at query time is therefore not a full semantic
equivalent.

### 4. `exclude_null()` Wrapped Around An Approximate Query

Example:

- `CPU exclude_null rollup wrapper`

Why it is blocked:

- `exclude_null()` itself is supportable in a narrow exact subset.
- But when the wrapped query still depends on approximate `rollup()` behavior, the
  overall monitor remains approximate and therefore not safe to auto-emit.

### The Key Takeaway

For these Datadog cases, the problem is not "we have no Kibana query". The
problem is "we do have a query candidate, but it is still not source-faithful
enough to claim exact automatic migration".

## Datadog: Remaining Formula And Civil-Time Gap

### 1. DST-Sensitive `calendar_shift()`

Example:

- `CPU calendar_shift timezone-sensitive`

Why it is blocked:

- Datadog documents `calendar_shift()` as comparing equivalent day / week / month
  windows and accepting an IANA timezone code such as `UTC`,
  `America/New_York`, or `Asia/Tokyo`:
  [Timeshift / calendar_shift](https://docs.datadoghq.com/dashboards/functions/timeshift/).
- Elastic publicly documents ES|QL date-time functions such as `DATE_DIFF`,
  `DATE_EXTRACT`, `DATE_FORMAT`, `DATE_PARSE`, `DATE_TRUNC`, and `NOW`:
  [ES|QL date-time functions](https://www.elastic.co/docs/reference/query-languages/esql/functions-operators/date-time-functions).

That ES|QL surface is useful, but it does not by itself give a documented,
source-faithful way to represent Datadog-style civil-time `calendar_shift()`
behavior for DST-observing or offset-changing IANA time zones.

Current exact boundary:

- strict arithmetic formulas over the supported `as_count()` subset
- aligned unshifted gauge-arithmetic formulas with matching aggregation, scope,
  and group-by
- UTC `calendar_shift()`
- stable-offset IANA time zones whose UTC offset does not change across the
  shifted comparison window

Still blocked:

- DST-observing or otherwise offset-changing time zones such as
  `America/New_York`

## Datadog: Algorithmic Monitor Families

The currently blocked algorithmic monitor families are:

- anomaly monitors
- forecast monitors
- outlier monitors

Concrete examples:

- `[Postgres] Replication delay is abnormally high on {{host.name}}`
- `Forecasted CPU saturation`
- `Outlier CPU host`

Why these remain blocked:

- Datadog documents anomaly, forecast, and outlier as distinct monitor types:
  [Monitor Types](https://docs.datadoghq.com/monitors/types/).
- The anomaly case in particular also depends on Datadog-specific monitor options
  such as `threshold_windows` and `require_full_window`, which are documented in
  [Monitor API Options](https://docs.datadoghq.com/monitors/guide/monitor_api_options/).

Elastic's generic rule surfaces are documented here:

- [Elasticsearch query rule](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-type-es-query)
- [Index threshold rule](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-type-index-threshold)
- [Custom threshold rule](https://www.elastic.co/docs/solutions/observability/incident-management/create-custom-threshold-rule)

Those rule types provide thresholds, aggregations, grouping, and equations. They
do not provide a generic one-to-one equivalent for Datadog's documented anomaly /
forecast / outlier monitor semantics in the migration path considered here.

## Datadog: Product-Specific Monitor Families

The currently blocked product-specific families in the validated set are:

- composite monitors
- service check monitors
- event alert monitors
- APM monitors
- RUM monitors
- Synthetics monitors
- CI monitors
- SLO monitors
- audit monitors
- cost monitors
- network monitors
- Watchdog monitors

These are not just alternate query syntaxes. They are distinct monitor products
with their own data models and status semantics.

### Composite Monitors

Composite monitors are the clearest example of a true target-surface gap.

Datadog documents composite monitors as Boolean expressions over other monitors,
for example `A && B`, with their own common-group logic and no-data behavior:
[Composite Monitor](https://docs.datadoghq.com/monitors/types/composite/).

That is fundamentally different from a single query threshold rule. A generic
query rule can approximate the output of a computation over documents, but it is
not inherently a "monitor of monitors" surface.

### Service Check Monitors

Datadog service checks have their own status-count threshold semantics, separate
from ordinary metric queries. Datadog documents this distinction in
[Monitor API Options](https://docs.datadoghq.com/monitors/guide/monitor_api_options/).

This makes them a poor fit for a plain ES|QL threshold rewrite unless Kibana has
or exposes a first-class status-based equivalent.

### APM / RUM / Synthetics / CI / SLO / Audit / Cost / Network / Watchdog

These are product-level alert families rather than generic metric-threshold or
log-threshold expressions.

In practice, automatic migration here usually requires one of two things:

- a first-class matching Elastic product surface with compatible alert semantics,
  or
- a formal mapping layer that knows how to reinterpret product-specific monitor
  intent into an equivalent Elastic rule family

Without that, the safest classification remains manual handling.

## Datadog: Source-Side Operational Semantics That Still Lack Exact Parity

Even some Datadog monitors that are otherwise translatable still expose parity
gaps in operational behavior.

Datadog documents monitor options such as:

- `notify_no_data`
- `no_data_timeframe`
- `require_full_window`
- `renotify_interval`
- `renotify_statuses`
- `evaluation_delay`
- `threshold_windows` for anomaly monitors

Reference:

- [Monitor API Options](https://docs.datadoghq.com/monitors/guide/monitor_api_options/)

Why this matters:

- A translated threshold query may compute the right metric value, but still fail
  to reproduce how the source monitor waits for a full window, delays evaluation,
  re-notifies, or handles no data.
- These are not decorative notification settings. They affect alert timing,
  recovery timing, and operator-visible behavior.

## Additional Datadog Monitor Types That Should Be Assumed Manual Until Evaluated

Datadog publicly documents additional monitor families beyond those exercised in
the current validated suite:

- Analysis
- Data Observability
- Database Monitoring
- Error Tracking
- Host
- Integration
- Live Process
- Network Path
- Cloud Network Monitoring
- NetFlow
- Process Check

Reference:

- [Monitor Types](https://docs.datadoghq.com/monitors/types/)

These are not counted in the statistics above, because they were not part of the
validated blocker suite used for this report.

However, because they are distinct monitor families rather than generic query
thresholds, they should be assumed manual until evaluated individually against a
matching Kibana / Elastic target surface.

## What Appears Missing Or Insufficient On The Kibana / Elastic Side

The blocker set suggests five high-value platform asks.

### 1. Broader Alert-Time PromQL Support

The most important Grafana unlock is a broader alert-time PromQL path that
preserves documented PromQL semantics, especially:

- `@`
- `offset`
- subqueries
- vector matching
- set operators
- label mutation functions
- comparison semantics across vectors

### 2. Exact Alert-Time Metric Semantics

The most important Datadog metric-monitor unlock is exact alert-time handling for:

- `as_rate()`
- `rollup()`
- `default_zero()`
- evaluation-window alignment that matches source monitor behavior

### 3. Timezone-Aware Civil-Time Arithmetic

A source-faithful equivalent for Datadog-style `calendar_shift()` over
DST-sensitive IANA time zones would unlock a class of currently manual shifted
monitors.

### 4. Richer No-Data / Error / Evaluation Behavior

The blocker set repeatedly points to the need for a generic parity layer for:

- source `No Data` / `Error` semantics
- delayed evaluation
- full-window requirements
- re-notify behavior
- recovery / trigger windows for algorithmic monitors

### 5. First-Class Rule Families Beyond Generic Query Thresholds

Some sources simply do not fit a generic query-rule model:

- composite monitors
- service-check monitors
- algorithmic monitors such as anomaly / forecast / outlier
- product-specific surfaces such as APM, SLO, Synthetics, and Watchdog

Those families likely need first-class Kibana / Elastic rule types or a richer
extension model rather than more query-rewrite logic.

## Suggested Framing For Kibana Team Discussion

If this report is turned into an issue or design discussion, the most useful
questions to ask are:

1. Can Kibana support a broader source-faithful PromQL alert surface rather than
   forcing all migrations through generic query rules?
2. Is there an exact alert-time equivalent planned for rate / rollup / fill /
   default-value semantics that match source observability products more closely?
3. Is there or will there be a timezone-aware civil-time surface suitable for
   DST-safe `calendar_shift()`-style alerting?
4. What is the intended Elastic rule-family story for composite, service-check,
   algorithmic, and product-specific monitor types?
5. Is there a recommended extensibility model for source systems whose alert
   semantics are richer than a threshold over a single query?

## Public References

### Elastic

- [Elasticsearch query rule](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-type-es-query)
- [Index threshold rule](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-type-index-threshold)
- [Custom threshold rule](https://www.elastic.co/docs/solutions/observability/incident-management/create-custom-threshold-rule)
- [Metric threshold rule](https://www.elastic.co/docs/solutions/observability/incident-management/create-metric-threshold-rule)
- [ES|QL date-time functions](https://www.elastic.co/docs/reference/query-languages/esql/functions-operators/date-time-functions)

### Grafana

- [No Data and Error states](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rules/state-and-health/)

### Prometheus

- [Querying basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Operators](https://prometheus.io/docs/prometheus/latest/querying/operators/)
- [Functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)

### Datadog

- [Monitor Types](https://docs.datadoghq.com/monitors/types/)
- [Composite Monitor](https://docs.datadoghq.com/monitors/types/composite/)
- [Metric Type Modifiers](https://docs.datadoghq.com/metrics/custom_metrics/type_modifiers/?tab=count)
- [Rollup](https://docs.datadoghq.com/dashboards/functions/rollup/)
- [Interpolation](https://docs.datadoghq.com/dashboards/functions/interpolation/)
- [Interpolation and the Fill Modifier](https://docs.datadoghq.com/metrics/guide/interpolation-the-fill-modifier-explained/)
- [Timeshift / calendar_shift](https://docs.datadoghq.com/dashboards/functions/timeshift/)
- [Monitor API Options](https://docs.datadoghq.com/monitors/guide/monitor_api_options/)
