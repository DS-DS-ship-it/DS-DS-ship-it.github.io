#!/usr/bin/env python3
"""
Earth Cockpit v22 freshness broker + proxy
Run:
    python3 earth_cockpit_v22_broker.py

Server:
    http://127.0.0.1:8787

Endpoints:
    /health
    /proxy?url=...
    /broker/base?bbox=minLon,minLat,maxLon,maxLat&sentinel_date=YYYY-MM-DD&gee_date=YYYY-MM-DD&sentinel_template=...&gee_template=...&gibs_date=YYYY-MM-DD
"""

from __future__ import annotations

import json
import math
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple


HOST = "127.0.0.1"
PORT = 8787
USER_AGENT = "EarthCockpitV22Broker/1.0"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_date(value: str | None) -> Optional[datetime]:
    if not value:
      return None
    value = value.strip()
    if not value:
      return None
    try:
      if len(value) == 10:
          return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
      dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
      if dt.tzinfo is None:
          dt = dt.replace(tzinfo=timezone.utc)
      return dt.astimezone(timezone.utc)
    except Exception:
      return None


def age_hours(dt: Optional[datetime]) -> float:
    if dt is None:
        return float("inf")
    delta = utc_now() - dt
    return max(0.0, delta.total_seconds() / 3600.0)


def iso_day(dt: Optional[datetime]) -> str:
    if dt is None:
        return "unknown"
    return dt.strftime("%Y-%m-%d")


def safe_float(value: str, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def http_fetch_bytes(url: str, timeout: int = 25, headers: Optional[Dict[str, str]] = None) -> Tuple[int, bytes, Dict[str, str]]:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    context = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        status = getattr(resp, "status", 200)
        body = resp.read()
        hdrs = {k: v for k, v in resp.headers.items()}
        return status, body, hdrs


def http_fetch_text(url: str, timeout: int = 25, headers: Optional[Dict[str, str]] = None) -> Tuple[int, str, Dict[str, str]]:
    status, body, hdrs = http_fetch_bytes(url, timeout=timeout, headers=headers)
    content_type = hdrs.get("Content-Type", "")
    charset = "utf-8"
    m = re.search(r"charset=([^\s;]+)", content_type, re.I)
    if m:
        charset = m.group(1)
    try:
        text = body.decode(charset, errors="replace")
    except Exception:
        text = body.decode("utf-8", errors="replace")
    return status, text, hdrs


@dataclass
class FreshnessRow:
    key: str
    name: str
    enabled: bool
    age_hours: float
    source_date: str
    score: float
    detail: str


def score_source(
    *,
    date_value: Optional[datetime],
    base_penalty_hours: float,
    resolution_bonus_hours: float = 0.0,
    cloud_bonus_hours: float = 0.0,
) -> float:
    h = age_hours(date_value)
    return h + base_penalty_hours - resolution_bonus_hours - cloud_bonus_hours


def build_freshness_rows(
    *,
    sentinel_template: str,
    sentinel_date: str,
    gee_template: str,
    gee_date: str,
    gibs_date: str,
) -> List[FreshnessRow]:
    sentinel_dt = parse_iso_date(sentinel_date)
    gee_dt = parse_iso_date(gee_date)
    gibs_dt = parse_iso_date(gibs_date)

    rows = [
        FreshnessRow(
            key="sentinel_template",
            name="Sentinel template",
            enabled=bool(sentinel_template.strip()),
            age_hours=age_hours(sentinel_dt),
            source_date=iso_day(sentinel_dt) if sentinel_dt else "unset",
            score=score_source(
                date_value=sentinel_dt,
                base_penalty_hours=0.0,
                resolution_bonus_hours=4.0,
            ),
            detail="User-supplied Sentinel XYZ template",
        ),
        FreshnessRow(
            key="gee_template",
            name="Earth Engine template",
            enabled=bool(gee_template.strip()),
            age_hours=age_hours(gee_dt),
            source_date=iso_day(gee_dt) if gee_dt else "unset",
            score=score_source(
                date_value=gee_dt,
                base_penalty_hours=1.0,
                resolution_bonus_hours=2.0,
            ),
            detail="User-supplied Earth Engine XYZ template",
        ),
        FreshnessRow(
            key="gibs_viirs",
            name="NASA GIBS VIIRS",
            enabled=True,
            age_hours=age_hours(gibs_dt),
            source_date=iso_day(gibs_dt) if gibs_dt else "unknown",
            score=score_source(
                date_value=gibs_dt,
                base_penalty_hours=8.0,
                resolution_bonus_hours=0.5,
            ),
            detail="Global browse imagery",
        ),
        FreshnessRow(
            key="gibs_modis",
            name="NASA GIBS MODIS",
            enabled=True,
            age_hours=age_hours(gibs_dt),
            source_date=iso_day(gibs_dt) if gibs_dt else "unknown",
            score=score_source(
                date_value=gibs_dt,
                base_penalty_hours=10.0,
                resolution_bonus_hours=0.25,
            ),
            detail="Global browse imagery",
        ),
        FreshnessRow(
            key="esri",
            name="Esri World Imagery",
            enabled=True,
            age_hours=24.0 * 21.0,
            source_date="rolling mosaic",
            score=24.0 * 21.0,
            detail="Stable general imagery mosaic",
        ),
        FreshnessRow(
            key="osm",
            name="OpenStreetMap",
            enabled=True,
            age_hours=24.0 * 365.0,
            source_date="not imagery",
            score=24.0 * 365.0,
            detail="Vector-derived map tiles, not aerial imagery",
        ),
    ]
    return rows


def choose_best(rows: List[FreshnessRow]) -> FreshnessRow:
    enabled = [r for r in rows if r.enabled]
    if not enabled:
        return FreshnessRow(
            key="esri",
            name="Esri World Imagery",
            enabled=True,
            age_hours=24.0 * 21.0,
            source_date="rolling mosaic",
            score=24.0 * 21.0,
            detail="Fallback",
        )
    enabled.sort(key=lambda r: r.score)
    return enabled[0]


def json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "EarthCockpitV22Broker/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stdout.write("%s - - [%s] %s\n" % (
            self.client_address[0],
            self.log_date_time_string(),
            fmt % args,
        ))

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8", extra_headers: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send(204, b"", content_type="text/plain; charset=utf-8")

    def do_HEAD(self) -> None:
        self._route(head_only=True)

    def do_GET(self) -> None:
        self._route(head_only=False)

    def _route(self, head_only: bool = False) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "/health":
                self.handle_health()
                return
            if path == "/proxy":
                self.handle_proxy(qs)
                return
            if path == "/broker/base":
                self.handle_broker_base(qs)
                return

            self._send(404, json_bytes({"ok": False, "error": "Not found"}))
        except urllib.error.HTTPError as e:
            self._send(e.code, json_bytes({"ok": False, "error": f"Upstream HTTP {e.code}"}))
        except Exception as e:
            self._send(500, json_bytes({"ok": False, "error": str(e)}))

    def handle_health(self) -> None:
        payload = {
            "ok": True,
            "service": "earth-cockpit-v22-broker",
            "time_utc": utc_now().isoformat(),
            "version": "1.0",
        }
        self._send(200, json_bytes(payload))

    def handle_proxy(self, qs: Dict[str, List[str]]) -> None:
        target = (qs.get("url") or [""])[0].strip()
        if not target:
            self._send(400, json_bytes({"ok": False, "error": "Missing url parameter"}))
            return

        parsed = urllib.parse.urlparse(target)
        if parsed.scheme not in ("http", "https"):
            self._send(400, json_bytes({"ok": False, "error": "Only http/https URLs allowed"}))
            return

        try:
            status, body, headers = http_fetch_bytes(target, timeout=35)
            content_type = headers.get("Content-Type", "application/octet-stream")
            passthrough_headers = {}
            if "Last-Modified" in headers:
                passthrough_headers["Last-Modified"] = headers["Last-Modified"]
            if "ETag" in headers:
                passthrough_headers["ETag"] = headers["ETag"]
            self._send(status, body, content_type=content_type, extra_headers=passthrough_headers)
        except urllib.error.HTTPError as e:
            err_body = e.read() if hasattr(e, "read") else b""
            content_type = getattr(e, "headers", {}).get("Content-Type", "text/plain; charset=utf-8") if hasattr(e, "headers") else "text/plain; charset=utf-8"
            self._send(e.code, err_body or json_bytes({"ok": False, "error": f"Proxy upstream HTTP {e.code}"}), content_type=content_type)

    def handle_broker_base(self, qs: Dict[str, List[str]]) -> None:
        bbox_raw = (qs.get("bbox") or [""])[0].strip()
        bbox = [-180.0, -85.0, 180.0, 85.0]
        if bbox_raw:
            parts = [safe_float(x, 0.0) for x in bbox_raw.split(",")]
            if len(parts) == 4:
                bbox = parts

        sentinel_date = (qs.get("sentinel_date") or [""])[0].strip()
        gee_date = (qs.get("gee_date") or [""])[0].strip()
        sentinel_template = (qs.get("sentinel_template") or [""])[0].strip()
        gee_template = (qs.get("gee_template") or [""])[0].strip()
        gibs_date = (qs.get("gibs_date") or [""])[0].strip()

        rows = build_freshness_rows(
            sentinel_template=sentinel_template,
            sentinel_date=sentinel_date,
            gee_template=gee_template,
            gee_date=gee_date,
            gibs_date=gibs_date,
        )
        best = choose_best(rows)

        payload = {
            "ok": True,
            "bbox": bbox,
            "best_key": best.key,
            "best_name": best.name,
            "rows": [asdict(r) for r in rows],
            "time_utc": utc_now().isoformat(),
            "notes": [
                "This broker ranks configured sources by declared scene date plus source penalties/bonuses.",
                "A static client cannot truly fuse all proprietary/newest imagery by itself.",
                "Use real Sentinel Hub / Earth Engine generated XYZ tiles for freshest high-resolution imagery.",
            ],
        }
        self._send(200, json_bytes(payload))


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Earth Cockpit v22 broker listening on http://{HOST}:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
