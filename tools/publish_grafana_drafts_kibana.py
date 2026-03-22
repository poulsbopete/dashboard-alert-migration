#!/usr/bin/env python3
"""
Publish workshop Grafana→Elastic *draft* JSON files into Kibana as Dashboard saved objects
via **POST /api/saved_objects/_bulk_create** (Observability Serverless does not allow
**POST /api/saved_objects/dashboard/{id}**). Each dashboard carries title + description (PromQL / migration notes);
panels start empty—add Lens in UI or use Path B (Cursor + Agent Skills).

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

    # Observability Serverless rejects POST /api/saved_objects/dashboard/{id}; use bulk create with id in body.
    bulk_url = f"{kibana}/api/saved_objects/_bulk_create"
    bulk: list[dict[str, Any]] = []
    meta: list[tuple[Path, str, str]] = []
    for path in files:
        draft = json.loads(path.read_text(encoding="utf-8"))
        title = str(draft.get("title") or path.stem)
        desc = build_description(draft)
        dash_id = sanitize_id(path.stem)
        body = dashboard_payload(title, desc)
        bulk.append(
            {
                "type": "dashboard",
                "id": dash_id,
                "attributes": body["attributes"],
                "references": body.get("references") or [],
            }
        )
        meta.append((path, dash_id, title))

    ok = 0
    failed: list[str] = []
    try:
        r = requests.post(
            bulk_url,
            params={"overwrite": "true"},
            headers=headers,
            auth=auth,
            json=bulk,
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
            failed.append(f"{path.name}: HTTP {r.status_code} {r.text[:400]}")
            print("FAIL", dash_id, r.status_code, file=sys.stderr)
    else:
        try:
            payload = r.json()
        except json.JSONDecodeError:
            for path, dash_id, _title in meta:
                failed.append(f"{path.name}: invalid JSON response from Kibana")
            print("FAIL bulk_create: non-JSON body", file=sys.stderr)
        else:
            saved = payload.get("saved_objects") or []
            by_id = {str(o.get("id", "")): o for o in saved if o.get("id")}
            for path, dash_id, title in meta:
                item = by_id.get(dash_id)
                if not item:
                    failed.append(
                        f"{path.name}: no entry for id {dash_id!r} in bulk_create response ({len(saved)} objects)"
                    )
                    print("FAIL", dash_id, file=sys.stderr)
                    continue
                err = item.get("error")
                if err:
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    failed.append(f"{path.name}: {msg or err}")
                    print("FAIL", dash_id, file=sys.stderr)
                else:
                    ok += 1
                    print("OK", dash_id, title[:70])

    print(f"\nPublished {ok}/{len(files)} dashboards to Kibana.")
    if failed:
        print("\nFailures:", file=sys.stderr)
        for msg in failed[:12]:
            print(f"  {msg}", file=sys.stderr)
        if len(failed) > 12:
            print(f"  ... and {len(failed) - 12} more", file=sys.stderr)
        return 1

    marker = Path("build/.published_grafana_to_kibana_ok")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"count": ok, "drafts": len(files)}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
