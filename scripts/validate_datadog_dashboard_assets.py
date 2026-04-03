#!/usr/bin/env python3
"""
Validate workshop Datadog dashboard JSON under assets/datadog/dashboards/.

Uses the same planning + translation path as datadog-migrate with --field-profile otel.
Exits non-zero if any leaf panel is not_feasible, requires_manual, or skipped.

Usage (from repo root):
  python3 scripts/validate_datadog_dashboard_assets.py
  python3 scripts/validate_datadog_dashboard_assets.py --strict-warnings
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "mig-to-kbn"))

from observability_migration.adapters.source.datadog.field_map import load_profile
from observability_migration.adapters.source.datadog.normalize import normalize_dashboard
from observability_migration.adapters.source.datadog.planner import plan_widget
from observability_migration.adapters.source.datadog.translate import translate_widget

GROUP_WIDGET_TYPES = frozenset({"group", "powerpack"})


def _leaf_widgets(widget, out: list) -> None:
    if widget.widget_type in GROUP_WIDGET_TYPES and widget.children:
        for c in widget.children:
            _leaf_widgets(c, out)
    else:
        out.append(widget)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dashboards-dir",
        type=Path,
        default=REPO / "assets" / "datadog" / "dashboards",
        help="Directory of dashboard JSON files",
    )
    ap.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Also fail if any panel has translator warnings",
    )
    args = ap.parse_args()
    d: Path = args.dashboards_dir
    if not d.is_dir():
        print(f"ERROR: not a directory: {d}", file=sys.stderr)
        return 1

    fm = load_profile("otel")
    files = sorted(d.glob("*.json"))
    if not files:
        print(f"ERROR: no *.json under {d}", file=sys.stderr)
        return 1

    failed = False
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        nd = normalize_dashboard(raw)
        leaves: list = []
        for w in nd.widgets:
            _leaf_widgets(w, leaves)

        status_counts: dict[str, int] = {}
        problems: list[str] = []
        warn_panels: list[str] = []

        for w in leaves:
            plan = plan_widget(w, fm)
            r = translate_widget(w, plan, fm)
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
            if r.status in ("not_feasible", "requires_manual", "skipped"):
                failed = True
                q = w.queries[0].raw_query[:100] if w.queries else ""
                problems.append(f"  {r.status}: {w.title!r} backend={plan.backend} q={q!r}")
            if args.strict_warnings and r.warnings:
                failed = True
                warn_panels.append(f"  {w.title!r}: {'; '.join(r.warnings[:2])}")

        print(f"{path.name}: {nd.title!r}  panels={len(leaves)}  {dict(sorted(status_counts.items()))}")
        for line in problems:
            print(line)
        for line in warn_panels:
            print(line)

    if failed:
        print("\nVALIDATION FAILED", file=sys.stderr)
        return 1
    print("\nOK: all panels translated (no not_feasible / requires_manual / skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
