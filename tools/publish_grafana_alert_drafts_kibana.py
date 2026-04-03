#!/usr/bin/env python3
"""
Publish Grafana→Kibana rule payloads from grafana-migrate --fetch-alerts output.

Reads alert_comparison_results.json (rows with payload_emitted + rule_payload), then
POST/PUT /api/alerting/rule/{id} with stable ids workshop-grafana-<grafana_uid>.

Env (after source ~/.bashrc on es3-api):
  KIBANA_URL, KIBANA_API_KEY or ES_API_KEY (or ES_USERNAME + ES_PASSWORD)

Usage:
  python3 tools/publish_grafana_alert_drafts_kibana.py \\
    --comparison build/mig-grafana/alert_comparison_results.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
MIG_ROOT = ROOT / "mig-to-kbn"


def _collect_emitted(report: dict[str, Any]) -> list[dict[str, Any]]:
    if not MIG_ROOT.is_dir():
        return []
    sys.path = [p for p in sys.path if p != str(MIG_ROOT)]
    sys.path.insert(0, str(MIG_ROOT))
    from observability_migration.targets.kibana.alerting import collect_emitted_rule_payloads

    return collect_emitted_rule_payloads(report)


def kibana_client() -> tuple[str, dict[str, str], Any]:
    kibana = (os.environ.get("KIBANA_URL") or "").rstrip("/")
    if not kibana:
        print("ERROR: KIBANA_URL is not set. Run: source ~/.bashrc", file=sys.stderr)
        sys.exit(1)
    api_key = (os.environ.get("KIBANA_API_KEY") or os.environ.get("ES_API_KEY") or "").strip()
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
            "ERROR: Set KIBANA_API_KEY or ES_API_KEY (or ES_USERNAME+ES_PASSWORD).",
            file=sys.stderr,
        )
        sys.exit(1)
    return kibana, headers, auth


def _rule_id_for_source(alert_id: str, fallback_name: str) -> str:
    base = (alert_id or fallback_name or "rule").strip()
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-") or "rule"
    rid = f"workshop-grafana-{base}"
    return rid[:100]


def _api_body(payload: dict[str, Any]) -> dict[str, Any]:
    sched = payload.get("schedule")
    if not isinstance(sched, dict) or not str((sched.get("interval") or "")).strip():
        sched = {"interval": "1m"}
    return {
        "rule_type_id": str(payload.get("rule_type_id") or ""),
        "name": str(payload.get("name") or "unnamed"),
        "consumer": str(payload.get("consumer") or "stackAlerts"),
        "schedule": sched,
        "params": payload.get("params") if isinstance(payload.get("params"), dict) else {},
        "actions": payload.get("actions") if isinstance(payload.get("actions"), list) else [],
        "enabled": bool(payload.get("enabled", False)),
        "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
    }


def _post_or_put(
    kibana: str,
    headers: dict[str, str],
    auth: Any,
    rule_id: str,
    body: dict[str, Any],
) -> tuple[bool, str]:
    h = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    h["Content-Type"] = "application/json"
    enc = quote(rule_id, safe="")
    url = f"{kibana}/api/alerting/rule/{enc}"
    r = requests.post(url, headers=h, auth=auth, json=body, timeout=120)
    if r.status_code in (200, 201):
        return True, ""
    if r.status_code == 409 or (
        r.status_code == 400 and "already exists" in (r.text or "").lower()
    ):
        r2 = requests.put(url, headers=h, auth=auth, json=body, timeout=120)
        if r2.ok:
            return True, ""
        return False, f"PUT HTTP {r2.status_code} {r2.text[:500]}"

    if (
        r.status_code == 400
        and body.get("rule_type_id") == ".es-query"
        and body.get("consumer") == "observability"
    ):
        alt = dict(body)
        alt["consumer"] = "stackAlerts"
        r3 = requests.post(url, headers=h, auth=auth, json=alt, timeout=120)
        if r3.status_code in (200, 201):
            return True, ""
        if r3.status_code == 409:
            r4 = requests.put(url, headers=h, auth=auth, json=alt, timeout=120)
            if r4.ok:
                return True, ""
            return False, f"PUT(stackAlerts) HTTP {r4.status_code} {r4.text[:500]}"
        return False, f"POST(observability) HTTP {r.status_code}; POST(stackAlerts) HTTP {r3.status_code} {r3.text[:400]}"

    return False, f"HTTP {r.status_code} {r.text[:600]}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--comparison",
        type=Path,
        default=Path("build/mig-grafana/alert_comparison_results.json"),
        help="Path to alert_comparison_results.json from grafana-migrate --fetch-alerts",
    )
    args = ap.parse_args()
    path: Path = args.comparison
    if not path.is_file():
        print(f"ERROR: comparison file missing: {path}", file=sys.stderr)
        return 1

    if not MIG_ROOT.is_dir():
        print(f"ERROR: vendored mig-to-kbn missing at {MIG_ROOT}", file=sys.stderr)
        return 1

    report = json.loads(path.read_text(encoding="utf-8"))
    items = _collect_emitted(report)
    if not items:
        print(f"No emitted rule payloads in {path} (nothing to publish).")
        return 0

    kibana, headers, auth = kibana_client()
    ok = 0
    skipped = 0
    failed: list[str] = []
    for item in items:
        payload = item.get("payload")
        if not isinstance(payload, dict) or not payload.get("rule_type_id"):
            continue
        if str(payload.get("rule_type_id") or "").startswith("xpack.ml."):
            print(f"SKIP {item.get('name')}: ML rule type may be unavailable on Serverless", file=sys.stderr)
            skipped += 1
            continue
        rule_id = _rule_id_for_source(str(item.get("alert_id") or ""), str(item.get("name") or ""))
        body = _api_body(payload)
        good, err = _post_or_put(kibana, headers, auth, rule_id, body)
        if good:
            ok += 1
            print("OK", rule_id, item.get("name"))
        else:
            failed.append(f"{rule_id}: {err}")

    print(f"\nPublished {ok}/{len(items)} Grafana-derived rules ({skipped} skipped).")
    if failed:
        print("Failures:", file=sys.stderr)
        for m in failed[:8]:
            print(f"  {m}", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
