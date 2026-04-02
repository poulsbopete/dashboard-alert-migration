# Alert Support Reporting

This directory holds curated Grafana and Datadog alert/monitor example suites.
The generated support standings derived from real tool output are written under
`examples/alerting/generated/` as local artifacts and are intentionally ignored
by git.

## Source Of Truth

Do not hand-maintain the support matrix in this README.

Regenerate the current standings with:

```bash
.venv/bin/python scripts/generate_alert_support_report.py
```

Verify that every emitted alert payload uploads to Kibana disabled by default:

```bash
set -a && source serverless_creds.env && set +a
.venv/bin/python scripts/verify_alert_rule_uploads.py
```

Audit existing migrated Kibana rules and optionally disable the enabled subset:

```bash
set -a && source serverless_creds.env && set +a
.venv/bin/python scripts/audit_migrated_rules.py
# .venv/bin/python scripts/audit_migrated_rules.py --disable-enabled
```

Notes:
- Audit-only mode exits non-zero when any migrated rules are still enabled.
- `--disable-enabled` exits non-zero only if one or more disable attempts fail.

Generated outputs land in the ignored local artifact directory:

- `examples/alerting/generated/alert_support_standings.md`
- `examples/alerting/generated/alert_support_standings.json`
- `examples/alerting/generated/grafana/alert_comparison_results.json`
- `examples/alerting/generated/datadog/monitor_migration_results.json`
- `examples/alerting/generated/datadog/monitor_comparison_results.json`

## Example Suites

- Grafana file-based examples: `examples/alerting/grafana`
- Datadog monitor examples: `examples/alerting/monitors/datadog_monitors.json`
- The Datadog dashboard placeholder used for file-mode reporting is synthesized
  by `scripts/generate_alert_support_report.py`; it is not a tracked source file.
- Direct Datadog file-mode monitor runs expect monitor JSON under
  `<input-dir>/monitors/` and at least one dashboard JSON in the same tree,
  because the current CLI loads dashboards before monitor extraction.

## Purpose

The generated standings document should answer:

- Which alert families are currently `automated`
- Which are only `draft_requires_review`
- Which are `manual_required`
- Which concrete example queries prove each current boundary

When the pipeline improves, regenerate the report and the document will show the
new standing automatically.
