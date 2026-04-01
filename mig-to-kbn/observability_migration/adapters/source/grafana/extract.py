"""Grafana dashboard extraction and text-panel normalization."""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlparse

import requests


def extract_dashboards_from_grafana(grafana_url, user, password):
    """Extract all dashboards from Grafana via HTTP API."""
    session = requests.Session()
    session.auth = (user, password)
    search_resp = session.get(f"{grafana_url}/api/search?type=dash-db&limit=500")
    search_resp.raise_for_status()
    dashboard_list = search_resp.json()
    dashboards = []
    for entry in dashboard_list:
        uid = entry.get("uid", "")
        resp = session.get(f"{grafana_url}/api/dashboards/uid/{uid}")
        if resp.status_code == 200:
            data = resp.json()
            dashboard = data.get("dashboard", data)
            dashboard["_grafana_meta"] = data.get("meta", {})
            dashboards.append(dashboard)
    return dashboards


def extract_dashboards_from_files(directory):
    """Load dashboards from local JSON files."""
    dashboards = []
    for f in sorted(Path(directory).glob("*.json")):
        with open(f) as fh:
            try:
                d = json.load(fh)
                if "panels" in d or "rows" in d:
                    d["_source_file"] = f.name
                    dashboards.append(d)
            except json.JSONDecodeError:
                print(f"  WARN: Could not parse {f.name}")
    return dashboards


_HTML_BLOCK_TAGS = {"br", "p", "div", "li", "ul", "ol", "table", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6"}


def _normalize_inline_text(value):
    text = unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _escape_markdown_label(value):
    return str(value or "").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _fallback_link_label(href, title=""):
    cleaned_title = _normalize_inline_text(title)
    if cleaned_title:
        return cleaned_title.split(" - ", 1)[0].strip()
    parsed = urlparse(str(href or ""))
    path_parts = [part for part in str(parsed.path or "").split("/") if part]
    if path_parts:
        tail = re.sub(r"\.[a-z0-9]+$", "", path_parts[-1], flags=re.IGNORECASE)
        tail = re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", tail)
        tail = tail.replace("-", " ").replace("_", " ").strip()
        tail = re.sub(r"\s+", " ", tail)
        if tail and tail.lower() not in {"index", "home"}:
            return " ".join(word.capitalize() for word in tail.split())
    host = (parsed.netloc or parsed.path or "").strip().lower()
    host = re.sub(r"^www\.", "", host)
    if host:
        stem = host.split(".", 1)[0].replace("-", " ").replace("_", " ").strip()
        if stem:
            return " ".join(part.capitalize() for part in stem.split())
        return host
    return "Link"


class _HtmlToMarkdownTextPanelParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._parts = []
        self._links = []

    def handle_starttag(self, tag, attrs):
        attr_map = {str(key): str(value or "") for key, value in attrs}
        lowered = str(tag or "").lower()
        if lowered == "a":
            self._links.append(
                {
                    "href": attr_map.get("href", "").strip(),
                    "title": attr_map.get("title", "").strip(),
                    "parts": [],
                }
            )
            return
        if lowered == "img":
            alt_text = _normalize_inline_text(attr_map.get("alt") or attr_map.get("title") or "")
            if self._links:
                if alt_text:
                    self._emit(alt_text)
                return
            src = attr_map.get("src", "").strip()
            if src:
                label = alt_text or _fallback_link_label(src, "")
                self._emit(f"![{_escape_markdown_label(label)}]({src})")
            elif alt_text:
                self._emit(alt_text)
            return
        if lowered == "iframe":
            src = attr_map.get("src", "").strip()
            if src:
                label = _fallback_link_label(src, attr_map.get("title", "")) or "Embedded content"
                self._emit(f"[{_escape_markdown_label(label)}]({src})")
            return
        if lowered in _HTML_BLOCK_TAGS:
            self._emit("\n")

    def handle_endtag(self, tag):
        lowered = str(tag or "").lower()
        if lowered == "a" and self._links:
            link = self._links.pop()
            label = _normalize_inline_text("".join(link["parts"]))
            if not label:
                label = _fallback_link_label(link.get("href", ""), link.get("title", ""))
            rendered = f"[{_escape_markdown_label(label)}]({link.get('href', '')})" if link.get("href") else label
            self._emit(rendered)
            return
        if lowered in _HTML_BLOCK_TAGS:
            self._emit("\n")

    def handle_data(self, data):
        self._emit(unescape(data))

    def handle_entityref(self, name):
        self._emit(unescape(f"&{name};"))

    def handle_charref(self, name):
        self._emit(unescape(f"&#{name};"))

    def _emit(self, value):
        if not value:
            return
        if self._links:
            self._links[-1]["parts"].append(value)
        else:
            self._parts.append(value)

    def render(self):
        return "".join(self._parts)


def _cleanup_markdown_text_panel_content(content):
    text = str(content or "").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]*\|[ \t]*\n[ \t]*", " | ", text)
    text = re.sub(r"[ \t]*\|[ \t]*", " | ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.splitlines()]
    merged = []
    for line in lines:
        if not line:
            if merged and merged[-1] != "":
                merged.append("")
            continue
        if merged and (merged[-1].endswith("|") or line.startswith("|")):
            merged[-1] = merged[-1].rstrip(" |") + " | " + line.lstrip(" |")
        else:
            merged.append(line)
    return "\n".join(merged).strip()


def _normalize_text_panel_content(content, mode=""):
    raw = str(content or "")
    if not raw.strip():
        return ""
    lowered_mode = str(mode or "").strip().lower()
    if lowered_mode == "html" or re.search(r"<[a-zA-Z][^>]*>", raw):
        parser = _HtmlToMarkdownTextPanelParser()
        parser.feed(raw)
        parser.close()
        return _cleanup_markdown_text_panel_content(parser.render())
    return raw


def _grafana_session(grafana_url, user="", password="", token=""):
    """Build a requests session with Bearer token or HTTP basic auth."""
    session = requests.Session()
    tok = str(token or "").strip()
    if tok:
        session.headers["Authorization"] = f"Bearer {tok}"
    elif user:
        session.auth = (user, str(password or ""))
    return session


def _fetch_unified_provisioning_json(session, base_url, path, empty_on_error, resource_label):
    """GET JSON from Grafana unified provisioning; warn and return empty on failure."""
    url = f"{base_url}{path}"
    try:
        resp = session.get(url, timeout=60)
        if resp.status_code == 404:
            print(
                f"  WARN: {resource_label} not found (404); unified alerting may be disabled."
            )
            return empty_on_error
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        print(f"  WARN: Failed to fetch {resource_label}: {exc}")
        return empty_on_error
    except ValueError as exc:
        print(f"  WARN: Invalid JSON for {resource_label}: {exc}")
        return empty_on_error


def extract_unified_alert_rules(grafana_url, user="", password="", token=""):
    """Fetch all Grafana Unified Alerting rules (GET /api/v1/provisioning/alert-rules)."""
    base = str(grafana_url or "").rstrip("/")
    session = _grafana_session(grafana_url, user=user, password=password, token=token)
    data = _fetch_unified_provisioning_json(
        session,
        base,
        "/api/v1/provisioning/alert-rules",
        [],
        "unified alert rules",
    )
    return data if isinstance(data, list) else []


def extract_unified_contact_points(grafana_url, user="", password="", token=""):
    """Fetch contact points (GET /api/v1/provisioning/contact-points)."""
    base = str(grafana_url or "").rstrip("/")
    session = _grafana_session(grafana_url, user=user, password=password, token=token)
    data = _fetch_unified_provisioning_json(
        session,
        base,
        "/api/v1/provisioning/contact-points",
        [],
        "unified contact points",
    )
    return data if isinstance(data, list) else []


def extract_unified_notification_policies(grafana_url, user="", password="", token=""):
    """Fetch notification policy tree (GET /api/v1/provisioning/policies)."""
    base = str(grafana_url or "").rstrip("/")
    session = _grafana_session(grafana_url, user=user, password=password, token=token)
    data = _fetch_unified_provisioning_json(
        session,
        base,
        "/api/v1/provisioning/policies",
        {},
        "unified notification policies",
    )
    return data if isinstance(data, dict) else {}


def extract_unified_mute_timings(grafana_url, user="", password="", token=""):
    """Fetch mute timings (GET /api/v1/provisioning/mute-timings)."""
    base = str(grafana_url or "").rstrip("/")
    session = _grafana_session(grafana_url, user=user, password=password, token=token)
    data = _fetch_unified_provisioning_json(
        session,
        base,
        "/api/v1/provisioning/mute-timings",
        [],
        "unified mute timings",
    )
    return data if isinstance(data, list) else []


def extract_unified_templates(grafana_url, user="", password="", token=""):
    """Fetch notification templates (GET /api/v1/provisioning/templates)."""
    base = str(grafana_url or "").rstrip("/")
    session = _grafana_session(grafana_url, user=user, password=password, token=token)
    data = _fetch_unified_provisioning_json(
        session,
        base,
        "/api/v1/provisioning/templates",
        [],
        "unified notification templates",
    )
    return data if isinstance(data, list) else []


def extract_datasources(grafana_url, user="", password="", token=""):
    """Fetch Grafana datasources and return a UID-keyed metadata map."""
    base = str(grafana_url or "").rstrip("/")
    session = _grafana_session(grafana_url, user=user, password=password, token=token)
    data = _fetch_unified_provisioning_json(
        session,
        base,
        "/api/datasources",
        [],
        "datasources",
    )
    datasources: dict[str, dict[str, str]] = {}
    if not isinstance(data, list):
        return datasources
    for item in data:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("uid", "") or "")
        if not uid:
            continue
        datasources[uid] = {
            "uid": uid,
            "type": str(item.get("type", "") or ""),
            "name": str(item.get("name", "") or ""),
        }
    return datasources


def extract_all_alerting_resources(grafana_url, user="", password="", token=""):
    """Fetch all unified alerting provisioning resources; each part degrades gracefully."""
    return {
        "alert_rules": extract_unified_alert_rules(
            grafana_url, user=user, password=password, token=token
        ),
        "contact_points": extract_unified_contact_points(
            grafana_url, user=user, password=password, token=token
        ),
        "notification_policies": extract_unified_notification_policies(
            grafana_url, user=user, password=password, token=token
        ),
        "mute_timings": extract_unified_mute_timings(
            grafana_url, user=user, password=password, token=token
        ),
        "templates": extract_unified_templates(
            grafana_url, user=user, password=password, token=token
        ),
        "datasources": extract_datasources(
            grafana_url, user=user, password=password, token=token
        ),
    }


__all__ = [
    "_cleanup_markdown_text_panel_content",
    "_normalize_text_panel_content",
    "extract_all_alerting_resources",
    "extract_datasources",
    "extract_dashboards_from_files",
    "extract_dashboards_from_grafana",
    "extract_unified_alert_rules",
    "extract_unified_contact_points",
    "extract_unified_mute_timings",
    "extract_unified_notification_policies",
    "extract_unified_templates",
]
