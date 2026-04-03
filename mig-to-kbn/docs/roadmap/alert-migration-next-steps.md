# Alert Migration Next Steps

## Purpose

This note captures the current alert-migration prioritization so the next work can
be taken up without redoing the coverage analysis.

## Current Support Snapshot

Based on the generated alert standings:

- Grafana: `27` curated cases -> `6 automated`, `5 draft_requires_review`, `16 manual_required`
- Datadog: `35` curated cases -> `15 automated`, `4 draft_requires_review`, `16 manual_required`

After running `scripts/generate_alert_support_report.py`, the generated standings
are available locally in:

- `examples/alerting/generated/alert_support_standings.md`
- `examples/alerting/generated/alert_support_standings.json`

## Priority Decision

### Work next on strict unified Grafana native PromQL

This is the highest-value **coherent and solvable** next family.

Why:

- The family already has source-faithful target queries.
- It already maps to Kibana `.es-query` rules through the native `PROMQL ...` path.
- The remaining blockers are mostly metadata / policy portability issues, not query translation failures.
- The current curated review-only examples are:
  - `Memory pressure alert`
  - `High CPU usage`
  - `Mimir request saturation`
  - `Prometheus Target Down`
  - `High Load 5m`

The generated Grafana comparison artifact now also exposes `target.review_gates`
for unified rules, including `no_data_only_blocks_strict_automation`, so
reviewers can tell when a rule is blocked only by the strict-subset policy (for
example `noDataState=NoData`) rather than by a query translation failure.

### Strict subset boundary

Only automate unified Grafana rules when all of the following are true:

- Source query is Prometheus or Mimir and passes the existing native PromQL boundary.
- Rule shape is the standard Grafana unified flow: query -> reduce -> threshold.
- There is a single source datasource query.
- Threshold shape is simple and already source-faithful.
- `noDataState` is only a value Kibana can match safely for an Elasticsearch query rule.
- Grafana labels are either absent or static non-templated key/value labels that can be preserved as Kibana rule tags.
- No dashboard-link annotations require manual linkage.

In practice, this means **do not auto-promote** rules whose semantics still depend on:

- Grafana `NoData` handling
- Dynamic or semantic Grafana labels that cannot be represented safely as Kibana rule tags
- Grafana dashboard-link annotations

## Important Constraint: NoData

Do **not** treat Grafana `noDataState=NoData` as automated for Kibana Elasticsearch query rules.

Reason:

- Kibana Elasticsearch query rules do not currently support "alert on no data" for ES|QL-backed queries, so Grafana `NoData` cannot be reproduced exactly in this path.

Reference:

- [Elasticsearch query rule docs](https://elastic.co/guide/en/kibana/current/rule-type-es-query.html)
- [Elastic issue about no-data support for ES|QL query rules](https://github.com/elastic/kibana/issues/245832)

## Important Constraint: Labels

Grafana labels should not be silently treated as exact equivalents of Kibana rule tags.

Reason:

- Kibana rule tags are useful metadata and are inherited by alerts, but they are not a full replacement for Grafana alert labels and their routing / grouping semantics.
- Static non-templated labels can still be preserved safely as rule tags in the strict subset, but dynamic or semantic labels should continue to require review.

Reference:

- [Create and manage alerting rules with Kibana](https://www.elastic.co/guide/en/kibana/master/create-and-manage-rules.html)
- [Kibana tags docs](https://elastic.co/guide/en/kibana/current/managing-tags.html)

## What Not To Do Next

Do **not** prioritize the Grafana `Native subset exclusions` bucket first even though it has the largest count.

Reason:

- It is not one problem.
- It is a bundle of different PromQL semantic gaps:
  - `topk()`
  - `bottomk()`
  - subqueries
  - `@` modifier
  - `changes()`
  - `label_replace()`
  - `label_join()`
  - `scalar()`
  - nested comparisons
  - vector-to-vector comparisons
  - `or`
  - `unless`
  - known server bug patterns

These should be handled one exact family at a time.

## ESQL Fallback Strategy

Fallback ESQL for PromQL is worth doing, but only when the target semantics can be
reproduced exactly or with a clearly bounded safe subset.

Good principle:

- Use fallback ES|QL only for **provably equivalent** PromQL families.
- Do not use ES|QL as a blanket "best effort" replacement for unsupported PromQL.

Candidate future family:

- Implemented: `topk()` / `bottomk()` exact subset for unified Grafana Prometheus/Mimir alerts when:
  - the source query is instant-like (`instant: true` or `range: false`)
  - the outer ranking has no PromQL `by` / `without` bucket modifier
  - the inner PromQL expression stays inside the native server-supported subset
  - the rule shape is still query -> reduce(last) -> threshold
  - the final ranking is reproduced by taking the last native PromQL step per series and then applying ES|QL `SORT` + `LIMIT`

Still not supported in this family:

- range-query `topk()` / `bottomk()` where Grafana could keep series that were only present in earlier ranked steps
- outer `topk by (...)` / `bottomk by (...)` bucketed ranking
- inner expressions that are themselves outside the native PromQL boundary

Reference:

- [ES|QL TOP function](https://www.elastic.co/docs/reference/query-languages/esql/functions-operators/aggregation-functions/top)

## Datadog Roadmap Item

Implemented with correctness-first boundaries:

- stricter exact `exclude_null()` subset for grouped metric/query alerts when:
  - `exclude_null()` wraps a grouped metric query
  - the grouped tag fields can be mapped directly to target keyword fields
  - the underlying metric/query translation is already warning-free
  - the target query removes groups where grouped tag values are missing or equal to `N/A`

- broader `exclude_null()` composition when:
  - `exclude_null()` still wraps a grouped metric/query alert
  - the grouped tag fields can be mapped directly to target keyword fields
  - the wrapped metric/query translation already carries approximation warnings such as `rollup()`
  - the target query still applies the exact null / `N/A` group filtering
  - the migrated alert remains `manual_required` because the wrapped query warning boundary is unchanged

- exact unshifted gauge-arithmetic formulas when:
  - the formula is plain arithmetic over metric refs and numeric literals
  - every metric ref is unshifted
  - every metric ref uses the same supported time aggregation and matching scope / group-by
  - no metric ref uses `as_rate()`, `as_count()`, or inner metric functions

- exact `calendar_shift()` subset for shifted formula/query alerts when:
  - `calendar_shift()` uses explicit `UTC` or an IANA timezone whose UTC offset stays stable under current tzdata
  - the shift uses day/week/month units (`d` / `w` / `mo`)
  - the rest of the shifted-formula query stays inside the existing exact shifted-formula boundary
  - month shifts use ES|QL calendar month arithmetic while Kibana evaluation windows stay conservatively wide enough to cover the shifted source range
  - non-UTC automation is limited to stable-offset zones where local calendar arithmetic is exact-equivalent to the current UTC translation

Keep the following Datadog cases pending:

- `calendar_shift()` with DST-observing or otherwise offset-changing IANA time zones
- non-UTC `calendar_shift()` shapes whose timezone offset changes across the shifted comparison window

These should continue under the same correctness-first policy used for the
current Datadog monitor coverage work.
