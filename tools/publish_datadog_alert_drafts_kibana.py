#!/usr/bin/env python3
"""
POST workshop Datadog→Elastic rule drafts (from datadog_to_elastic_alert.py) to Kibana.

Reads JSON files matching monitor-*-elastic.json, strips non-API keys (e.g. migration),
and creates or updates rules via POST/PUT /api/alerting/rule/{id}.

Env (after source ~/.bashrc on es3-api):
  KIBANA_URL, ES_API_KEY (or ES_USERNAME + ES_PASSWORD)

Usage:
  python3 tools/publish_datadog_alert_drafts_kibana.py --alerts-dir build/elastic-alerts
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

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


def _put_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Kibana rule PUT rejects bodies that include read-only fields like ``rule_type_id``."""
    body = dict(payload)
    body.pop("rule_type_id", None)
    return body


def _clean_payload(raw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data = dict(raw)
    rid = str(data.pop("id", "") or "datadog-import-rule").strip()
    rid = rid.replace("/", "-")[:100] or "datadog-import-rule"
    data.pop("migration", None)
    if "actions" not in data:
        data["actions"] = []
    if "enabled" not in data:
        data["enabled"] = False
    return rid, data


def _post_or_put(
    kibana: str,
    headers: dict[str, str],
    auth: Any,
    rule_id: str,
    payload: dict[str, Any],
) -> tuple[bool, str]:
    h = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    h["Content-Type"] = "application/json"
    enc = quote(rule_id, safe="")
    url = f"{kibana}/api/alerting/rule/{enc}"
    r = requests.post(url, headers=h, auth=auth, json=payload, timeout=120)
    if r.status_code in (200, 201):
        return True, ""
    if r.status_code == 409 or (
        r.status_code == 400 and "already exists" in (r.text or "").lower()
    ):
        r2 = requests.put(url, headers=h, auth=auth, json=_put_payload(payload), timeout=120)
        if r2.ok:
            return True, ""
        return False, f"PUT HTTP {r2.status_code} {r2.text[:500]}"

    # Observability Serverless sometimes expects stackAlerts for .es-query
    if (
        r.status_code == 400
        and payload.get("rule_type_id") == ".es-query"
        and payload.get("consumer") == "observability"
    ):
        alt = dict(payload)
        alt["consumer"] = "stackAlerts"
        r3 = requests.post(url, headers=h, auth=auth, json=alt, timeout=120)
        if r3.status_code in (200, 201):
            return True, ""
        if r3.status_code == 409:
            r4 = requests.put(url, headers=h, auth=auth, json=_put_payload(alt), timeout=120)
            if r4.ok:
                return True, ""
            return False, f"PUT(stackAlerts) HTTP {r4.status_code} {r4.text[:500]}"
        return False, f"POST(observability) HTTP {r.status_code}; POST(stackAlerts) HTTP {r3.status_code} {r3.text[:400]}"

    return False, f"HTTP {r.status_code} {r.text[:600]}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish Datadog-derived alert drafts to Kibana.")
    ap.add_argument(
        "--alerts-dir",
        type=Path,
        default=Path("build/elastic-alerts"),
        help="Directory with monitor-*-elastic.json files",
    )
    args = ap.parse_args()
    d: Path = args.alerts_dir
    if not d.is_dir():
        print(f"ERROR: alerts dir missing: {d}", file=sys.stderr)
        return 1
    files = sorted(d.glob("monitor-*-elastic.json"))
    if not files:
        print(f"ERROR: no monitor-*-elastic.json under {d}", file=sys.stderr)
        return 1

    kibana, headers, auth = kibana_client()
    ok = 0
    skipped = 0
    failed: list[str] = []
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rule_id, payload = _clean_payload(raw)
        is_ml = str(payload.get("rule_type_id") or "").startswith("xpack.ml.")
        good, err = _post_or_put(kibana, headers, auth, rule_id, payload)
        if good:
            ok += 1
            print("OK", rule_id, path.name)
        elif is_ml:
            print(
                f"SKIP {path.name}: ML rule type may be unavailable on Serverless — {err[:220]}",
                file=sys.stderr,
            )
            skipped += 1
        else:
            failed.append(f"{path.name}: {err}")

    print(f"\nPublished {ok}/{len(files)} rules ({skipped} skipped).")
    if failed:
        print("Failures:", file=sys.stderr)
        for m in failed[:8]:
            print(f"  {m}", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
