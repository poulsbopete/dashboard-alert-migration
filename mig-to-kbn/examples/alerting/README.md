# Alert Migration Examples

This directory documents the current correctness-first alert migration boundary.

## Supported Auto-Create

### Grafana Unified Prometheus

Source alert expression:

```text
100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

Threshold step:

```text
> 80 for 5m
```

Expected migration behavior:

- Extract as `grafana_unified`
- Keep `automation_tier = draft_requires_review`
- Create a Kibana `.es-query` rule
- Preserve the source query through native `PROMQL ...`
- Apply the original threshold in the target query

### Datadog Metric / Query Alert

Source monitor query:

```text
avg(last_5m):avg:system.cpu.user{env:production} by {host} > 90
```

Expected migration behavior:

- Extract as `datadog_metric`
- Translate to a Kibana `.es-query` rule only when the active field profile maps `system.cpu.user` and `host` to real target fields
- Preserve the threshold by filtering the translated ES|QL on `value > 90`

### Datadog Log Monitor

Source monitor query:

```text
logs("status:error").index("main").rollup("count").last("5m") > 100
```

Expected migration behavior:

- Extract as `datadog_log`
- Translate to a Kibana `.es-query` rule only when the mapped log fields exist in the target schema
- Keep the result in `draft_requires_review` because Datadog log search semantics and Kibana log filtering still require human review

## Extracted But Manual

### Grafana Legacy Panel Alert

Source shape:

```text
panel.alert.conditions = [...]
```

Expected migration behavior:

- Extract as `grafana_legacy`
- Emit migration artifacts and review notes
- Do not auto-create a Kibana rule unless a real translated query is attached

### Grafana Unified Loki / LogQL

Source alert expression:

```text
count_over_time({job=~".+"} |= "error" [5m])
```

Expected migration behavior:

- Extract as `grafana_unified`
- Record alert metadata and threshold details
- Do not auto-create a Kibana rule yet

### Datadog Metric Monitor

Source monitor query:

```text
sum(last_15m):sum:pipelines.component_errors_total{...} by {component_type,component_id,host,worker_uuid} > 0
```

Expected migration behavior:

- Extract as `datadog_metric`
- Record monitor query, thresholds, and notification metadata
- Do not auto-create a Kibana rule when the translated metric/tag fields are missing from the target schema

### Datadog Log Monitor With Unsupported Shape

Source monitor query:

```text
logs("status:error").index("main").rollup("count").last("5m") > 100
```

Expected migration behavior:

- Extract as `datadog_log`
- Record monitor query and thresholds
- Do not auto-create a Kibana rule unless the log query shape and target schema are both verified as safe
