#!/usr/bin/env python3
"""Probe Elasticsearch for columns and PROMQL used by workshop Grafana → Kibana dashboards.

Requires env (same as migrate / verify scripts):
  ES_URL, ES_API_KEY  (or ES_USERNAME + ES_PASSWORD)

Exit 0 if critical probes pass; non-zero if any critical probe fails.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _auth_header() -> tuple[str, str]:
    key = (os.environ.get("ES_API_KEY") or "").strip()
    user = (os.environ.get("ES_USERNAME") or "").strip()
    password = (os.environ.get("ES_PASSWORD") or "").strip()
    if key:
        return "Authorization", f"ApiKey {key}"
    if user and password:
        import base64

        tok = base64.b64encode(f"{user}:{password}".encode()).decode()
        return "Authorization", f"Basic {tok}"
    print("ERROR: Set ES_API_KEY or ES_USERNAME+ES_PASSWORD", file=sys.stderr)
    sys.exit(2)


def esql(base: str, query: str, timeout: int = 90) -> dict:
    name, val = _auth_header()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/_query",
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={name: val, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error": {"type": "http_error", "reason": str(e), "body": body[:800]}}


def main() -> int:
    base = (os.environ.get("ES_URL") or "").strip()
    if not base:
        print("ERROR: ES_URL is not set", file=sys.stderr)
        return 2

    critical_fail = 0
    warn = 0

    print("==> 1) metrics-* document volume (24h)")
    r = esql(base, "FROM metrics-*\n| WHERE @timestamp > NOW() - 24 hours\n| STATS docs = COUNT(*)\n| LIMIT 1")
    if r.get("error"):
        print("FAIL", json.dumps(r, indent=2)[:1200])
        return 1
    rows = r.get("values") or []
    docs = rows[0][0] if rows else 0
    print(f"    docs={docs}")
    if not docs or int(docs) < 1:
        print("FAIL: no metrics-* docs in last 24h (start OTLP or widen time range)", file=sys.stderr)
        return 1

    probes: list[tuple[str, str, bool]] = [
        (
            "BY service.name on http counter",
            "FROM metrics-*\n| WHERE @timestamp > NOW() - 6 hours\n| STATS c = COUNT(*) BY `service.name`\n| SORT c DESC\n| LIMIT 5",
            True,
        ),
        (
            "BY http.route",
            "FROM metrics-*\n| WHERE @timestamp > NOW() - 6 hours\n| STATS c = COUNT(*) BY `http.route`\n| SORT c DESC\n| LIMIT 5",
            True,
        ),
        (
            "BY http.request.method",
            "FROM metrics-*\n| WHERE @timestamp > NOW() - 6 hours\n| STATS c = COUNT(*) BY `http.request.method`\n| SORT c DESC\n| LIMIT 5",
            True,
        ),
        (
            "BY http.response.status_code",
            "FROM metrics-*\n| WHERE @timestamp > NOW() - 6 hours\n| STATS c = COUNT(*) BY `http.response.status_code`\n| SORT c DESC\n| LIMIT 5",
            True,
        ),
        (
            "BY host.name",
            "FROM metrics-*\n| WHERE @timestamp > NOW() - 6 hours\n| STATS c = COUNT(*) BY `host.name`\n| SORT c DESC\n| LIMIT 5",
            False,
        ),
        (
            "histogram bucket field le",
            "FROM metrics-*\n| WHERE @timestamp > NOW() - 6 hours\n| WHERE `http_request_duration_seconds_bucket` IS NOT NULL\n| STATS c = COUNT(*)\n| LIMIT 1",
            False,
        ),
    ]

    print("\n==> 2) Column / aggregation probes (workshop dashboard dimensions)")
    for title, q, crit in probes:
        out = esql(base, q)
        if out.get("error"):
            msg = json.dumps(out.get("error"), indent=2)[:600]
            print(f"    {'FAIL' if crit else 'WARN'} [{title}]: {msg}")
            if crit:
                critical_fail += 1
            else:
                warn += 1
        else:
            n = len(out.get("values") or [])
            print(f"    OK   [{title}] rows={n}")

    promql_tests = [
        ("scalar total rate", "PROMQL index=metrics-* step=1m value=(sum(rate(http_requests_total[5m])))"),
        (
            "by service.name",
            "PROMQL index=metrics-* step=1m value=(sum by (service.name) (rate(http_requests_total[5m])))",
        ),
        (
            "by http.response.status_code",
            "PROMQL index=metrics-* step=1m value=(sum by (http.response.status_code) (rate(http_requests_total[5m])))",
        ),
        (
            "5xx ratio matcher",
            "PROMQL index=metrics-* step=1m value=(sum(rate(http_requests_total{http.response.status_code=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m])))",
        ),
    ]

    print("\n==> 3) Native PROMQL (same family as migrated Lens panels)")
    for title, q in promql_tests:
        out = esql(base, f"{q}\n| LIMIT 20")
        if out.get("error"):
            print(f"    FAIL [{title}]: {json.dumps(out.get('error'), indent=2)[:700]}")
            critical_fail += 1
        else:
            n = len(out.get("values") or [])
            print(f"    OK   [{title}] rows={n}")

    print("\n==> Summary")
    if critical_fail:
        print(f"    Critical failures: {critical_fail} (warnings: {warn})")
        return 1
    print(f"    All critical probes passed (warnings: {warn})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
