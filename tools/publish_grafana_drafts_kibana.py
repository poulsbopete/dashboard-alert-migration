#!/usr/bin/env python3
"""
Publish workshop Grafana→Elastic *draft* JSON files into Kibana as Dashboard saved objects
via **POST /api/saved_objects/_import** (multipart NDJSON). Observability Serverless only
exposes **export** and **import** for saved objects—not **POST .../dashboard/{id}** or **_bulk_create**.
Each dashboard carries title + description (PromQL / migration notes); panels start empty—add Lens in UI
or use Path B (Cursor + Agent Skills).

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
    options = {
        "useMargins": True,
        "syncColors": False,
        "syncCursor": True,
        "syncTooltips": False,
        "hidePanelTitles": False,
    }
    search_source = {"query": {"query": "", "language": "kuery"}, "filter": []}
    control_group = {
        "chainingSystem": "HIERARCHICAL",
        "controlStyle": "oneLine",
        "ignoreParentSettingsJSON": json.dumps(
            {
                "ignoreFilters": False,
                "ignoreQuery": False,
                "ignoreTimerange": False,
                "ignoreValidations": False,
            }
        ),
        "panelsJSON": "{}",
    }
    return {
        "attributes": {
            "title": title[:255],
            "description": description,
            "hits": 0,
            "panelsJSON": "[]",
            "optionsJSON": json.dumps(options),
            "version": 1,
            "timeRestore": False,
            "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(search_source)},
            "controlGroupInput": control_group,
        },
        "references": [],
    }


def saved_object_import_line(
    dash_id: str, body: dict[str, Any], core_migration_version: str
) -> dict[str, Any]:
    """One NDJSON record compatible with Kibana import (Serverless)."""
    return {
        "type": "dashboard",
        "id": dash_id,
        "namespaces": ["default"],
        "attributes": body["attributes"],
        "references": body.get("references") or [],
        "coreMigrationVersion": core_migration_version,
        # Dashboard saved-object model version (see Kibana dashboard_saved_object modelVersions); compatibilityMode adjusts.
        "typeMigrationVersion": "3",
    }


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

    import_url = f"{kibana}/api/saved_objects/_import"
    lines: list[str] = []
    meta: list[tuple[Path, str, str]] = []
    for path in files:
        draft = json.loads(path.read_text(encoding="utf-8"))
        title = str(draft.get("title") or path.stem)
        desc = build_description(draft)
        dash_id = sanitize_id(path.stem)
        body = dashboard_payload(title, desc)
        rec = saved_object_import_line(dash_id, body, core_ver)
        lines.append(json.dumps(rec, separators=(",", ":"), ensure_ascii=False))
        meta.append((path, dash_id, title))

    ndjson = "\n".join(lines) + "\n"
    h = api_headers_no_content_type(headers)

    ok = 0
    failed: list[str] = []
    try:
        r = requests.post(
            import_url,
            params={"overwrite": "true", "compatibilityMode": "true"},
            headers=h,
            auth=auth,
            files={"file": ("workshop-grafana.ndjson", ndjson.encode("utf-8"), "application/ndjson")},
            timeout=300,
        )
    except requests.RequestException as e:
        for path, dash_id, _title in meta:
            failed.append(f"{path.name}: {e}")
            print("FAIL", dash_id, e, file=sys.stderr)
        print(f"\nPublished {ok}/{len(files)} dashboards to Kibana.")
        if failed:
            print("\nFailures:", file=sys.stderr)
            for msg in failed[:12]:
                print(f"  {msg}", file=sys.stderr)
        return 1

    if r.status_code not in (200, 201):
        for path, dash_id, _title in meta:
            failed.append(f"{path.name}: HTTP {r.status_code} {r.text[:800]}")
            print("FAIL", dash_id, r.status_code, file=sys.stderr)
    else:
        try:
            payload = r.json()
        except json.JSONDecodeError:
            for path, dash_id, _title in meta:
                failed.append(f"{path.name}: invalid JSON response from Kibana import")
            print("FAIL import: non-JSON body", file=sys.stderr)
        else:
            err_list = payload.get("errors") or []
            ok = int(payload.get("successCount") or 0)
            success_results = payload.get("successResults") or []
            success_ids = {str(x.get("id")) for x in success_results if x.get("id")}

            if err_list:
                for err in err_list:
                    raw = err.get("meta") or err
                    obj = raw if isinstance(raw, dict) else {}
                    oid = str(obj.get("id") or err.get("id") or "")
                    otype = str(obj.get("type") or "")
                    msg = err.get("error", {}).get("message") if isinstance(err.get("error"), dict) else str(
                        err.get("error") or err
                    )
                    failed.append(f"import {otype}/{oid}: {msg}")
                    print("FAIL", oid or "?", file=sys.stderr)
                for _path, dash_id, title in meta:
                    if dash_id in success_ids:
                        print("OK", dash_id, title[:70])
            else:
                ok = int(payload.get("successCount") or 0) or len(meta)
                for _path, dash_id, title in meta:
                    print("OK", dash_id, title[:70])

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
