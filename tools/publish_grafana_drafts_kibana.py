#!/usr/bin/env python3
"""
Publish workshop Grafana→Elastic *draft* JSON into Kibana.

**Primary (Observability Serverless):** **POST /api/dashboards?apiVersion=1** with optional **Markdown**
panel holding PromQL / migration notes (see Elastic Dashboards API). Serverless often returns **500** on
hand-crafted **saved_objects/_import** payloads when migration metadata does not match the stack.

**Fallback:** one-object-at-a-time **POST /api/saved_objects/_import** with **minimal** dashboard attributes
(no controlGroupInput / typeMigrationVersion) if the Dashboards API is unavailable.

Requires (after `source ~/.bashrc` on es3-api):
  KIBANA_URL
  ES_API_KEY  (preferred), or ES_USERNAME + ES_PASSWORD

Usage:
  python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import requests


def kibana_client() -> tuple[str, dict[str, str], Any]:
    kibana = (os.environ.get("KIBANA_URL") or "").rstrip("/")
    if not kibana:
        print("ERROR: KIBANA_URL is not set. Run: source ~/.bashrc", file=sys.stderr)
        sys.exit(1)

    api_key = (os.environ.get("ES_API_KEY") or "").strip()
    user = (os.environ.get("ES_USERNAME") or "").strip()
    password = (os.environ.get("ES_PASSWORD") or "").strip()

    headers: dict[str, str] = {"kbn-xsrf": "true", "Content-Type": "application/json"}
    auth: Any = None
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"
    elif user and password:
        auth = (user, password)
    else:
        print(
            "ERROR: Set ES_API_KEY or ES_USERNAME+ES_PASSWORD (source ~/.bashrc on the workshop VM).",
            file=sys.stderr,
        )
        sys.exit(1)
    return kibana, headers, auth


def api_headers_no_content_type(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() != "content-type"}


def fetch_core_migration_version(kibana: str, headers: dict[str, str], auth: Any) -> str:
    """Stack version string for saved-object import metadata (e.g. 9.0.0)."""
    h = api_headers_no_content_type(headers)
    try:
        r = requests.get(f"{kibana}/api/status", headers=h, auth=auth, timeout=30)
        if r.ok:
            data = r.json()
            ver = (data.get("version") or {}).get("number")
            if isinstance(ver, str) and ver.strip():
                return ver.strip()
    except (requests.RequestException, TypeError, ValueError, AttributeError):
        pass
    return "9.0.0"


def sanitize_id(stem: str) -> str:
    base = stem.replace("-elastic-draft", "").lower().replace("_", "-")
    s = re.sub(r"[^a-z0-9-]+", "-", base)
    s = re.sub(r"-+", "-", s).strip("-")[:80] or "dash"
    return f"w-grafana-{s}"


def build_description(draft: dict[str, Any]) -> str:
    parts: list[str] = []
    for pan in (draft.get("panels") or [])[:24]:
        if not isinstance(pan, dict):
            continue
        title = pan.get("title") or "panel"
        mig = pan.get("migration") or {}
        promql = mig.get("promql") or ""
        note = pan.get("note") or ""
        parts.append(f"### {title}\n\nPromQL: `{promql}`\n\n{note}")
    body = "\n\n".join(parts)
    return body[:50000]


def dashboard_payload(title: str, description: str) -> dict[str, Any]:
    """Classic saved-object-shaped attributes (import fallback only)."""
    options = {
        "useMargins": True,
        "syncColors": False,
        "syncCursor": True,
        "syncTooltips": False,
        "hidePanelTitles": False,
    }
    search_source = {"query": {"query": "", "language": "kuery"}, "filter": []}
    return {
        "attributes": {
            "title": title[:255],
            "description": description,
            "panelsJSON": "[]",
            "optionsJSON": json.dumps(options),
            "version": 1,
            "timeRestore": False,
            "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(search_source)},
        },
        "references": [],
    }


def dashboards_api_headers(base: dict[str, str]) -> dict[str, str]:
    h = api_headers_no_content_type(base)
    h["Content-Type"] = "application/json"
    h["Elastic-Api-Version"] = "1"
    h["X-Elastic-Internal-Origin"] = "true"
    return h


def publish_one_dashboards_api(
    kibana: str,
    headers: dict[str, str],
    auth: Any,
    title: str,
    description: str,
) -> tuple[bool, str]:
    """Create a dashboard via the supported Serverless Dashboards API."""
    h = dashboards_api_headers(headers)
    panels: list[dict[str, Any]] = []
    if description.strip():
        panels.append(
            {
                "grid": {"x": 0, "y": 0, "w": 48, "h": 24},
                "config": {"content": description[:50000]},
                "uid": str(uuid.uuid4()),
                "type": "DASHBOARD_MARKDOWN",
            }
        )
    body: dict[str, Any] = {
        "title": title[:255],
        "panels": panels,
        "time_range": {"from": "now-30d", "to": "now"},
    }
    r = requests.post(
        f"{kibana}/api/dashboards?apiVersion=1",
        headers=h,
        auth=auth,
        json=body,
        timeout=120,
    )
    if r.status_code in (200, 201):
        return True, ""
    return False, f"HTTP {r.status_code} {r.text[:600]}"


def saved_object_minimal_import_line(
    dash_id: str, body: dict[str, Any], core_migration_version: str
) -> dict[str, Any]:
    """Minimal NDJSON line—avoids typeMigrationVersion / controlGroupInput / namespaces (common 500 causes)."""
    return {
        "type": "dashboard",
        "id": dash_id,
        "attributes": dict(body["attributes"]),
        "references": body.get("references") or [],
        "coreMigrationVersion": core_migration_version,
    }


def import_one_ndjson(
    kibana: str,
    headers: dict[str, str],
    auth: Any,
    record: dict[str, Any],
) -> tuple[bool, str]:
    h = api_headers_no_content_type(headers)
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
    r = requests.post(
        f"{kibana}/api/saved_objects/_import",
        params={"overwrite": "true", "compatibilityMode": "true"},
        headers=h,
        auth=auth,
        files={"file": ("one.ndjson", line.encode("utf-8"), "application/ndjson")},
        timeout=120,
    )
    if r.status_code not in (200, 201):
        return False, f"HTTP {r.status_code} {r.text[:600]}"
    try:
        payload = r.json()
    except json.JSONDecodeError:
        return False, "non-JSON import response"
    errs = payload.get("errors") or []
    if errs:
        return False, str(errs[0])[:600]
    if payload.get("success") is False and int(payload.get("successCount") or 0) < 1:
        return False, str(payload)[:600]
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Create Kibana dashboards from Grafana migration drafts via HTTP API.")
    ap.add_argument("--drafts-dir", type=Path, default=Path("build/elastic-dashboards"))
    args = ap.parse_args()
    drafts_dir: Path = args.drafts_dir

    if not drafts_dir.is_dir():
        print(f"ERROR: drafts dir missing: {drafts_dir}", file=sys.stderr)
        return 1

    files = sorted(drafts_dir.glob("*-elastic-draft.json"))
    if not files:
        print(f"ERROR: no *-elastic-draft.json under {drafts_dir}", file=sys.stderr)
        return 1

    kibana, headers, auth = kibana_client()
    core_ver = fetch_core_migration_version(kibana, headers, auth)

    ok = 0
    failed: list[str] = []
    for path in files:
        draft = json.loads(path.read_text(encoding="utf-8"))
        title = str(draft.get("title") or path.stem)
        desc = build_description(draft)
        dash_id = sanitize_id(path.stem)
        body = dashboard_payload(title, desc)

        try:
            good, err_dash = publish_one_dashboards_api(kibana, headers, auth, title, desc)
        except requests.RequestException as e:
            good, err_dash = False, str(e)

        if good:
            ok += 1
            print("OK", dash_id, title[:70])
            continue

        rec = saved_object_minimal_import_line(dash_id, body, core_ver)
        try:
            good_imp, err_imp = import_one_ndjson(kibana, headers, auth, rec)
        except requests.RequestException as e:
            good_imp, err_imp = False, str(e)

        if good_imp:
            ok += 1
            print("OK", dash_id, title[:70], "(fallback: saved-objects import)")
            continue

        failed.append(f"{path.name}: Dashboards API: {err_dash} | import: {err_imp}")
        print("FAIL", dash_id, file=sys.stderr)

    print(f"\nPublished {ok}/{len(files)} dashboards to Kibana.")
    if failed:
        print("\nFailures:", file=sys.stderr)
        for msg in failed[:12]:
            print(f"  {msg}", file=sys.stderr)
        if len(failed) > 12:
            print(f"  ... and {len(failed) - 12} more", file=sys.stderr)
        return 1

    if ok == len(files):
        marker = Path("build/.published_grafana_to_kibana_ok")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"count": ok, "drafts": len(files)}), encoding="utf-8")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
