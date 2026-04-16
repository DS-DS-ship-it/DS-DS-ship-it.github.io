#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8787

USER_AGENT = "EarthCockpitV23Broker/1.0"

CACHE_TTL = 120
CACHE: dict[str, tuple[float, dict]] = {}

ESRI_TILE = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
OSM_TILE = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
GIBS_MODIS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/{date}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg"
GIBS_VIIRS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/{date}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg"

LANDSAT_STAC = "https://landsatlook.usgs.gov/stac-server"
EARTHSEARCH_STAC = "https://earth-search.aws.element84.com/v1/search"

def jdump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")

def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def cached_get(key: str):
    item = CACHE.get(key)
    if not item:
        return None
    ts, val = item
    if time.time() - ts > CACHE_TTL:
        CACHE.pop(key, None)
        return None
    return val

def cached_set(key: str, val: dict):
    CACHE[key] = (time.time(), val)

def http_get(url: str, timeout: int = 25, headers: dict | None = None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        **(headers or {})
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.getcode(), dict(resp.headers.items()), resp.read()

def http_post_json(url: str, body: dict, timeout: int = 30, headers: dict | None = None) -> tuple[int, dict, bytes]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        **(headers or {})
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.getcode(), dict(resp.headers.items()), resp.read()

def probe_url(url: str) -> dict:
    try:
        code, headers, _ = http_get(url, timeout=12)
        return {
            "ok": 200 <= code < 400,
            "status": code,
            "last_modified": headers.get("Last-Modified"),
            "etag": headers.get("ETag"),
            "content_type": headers.get("Content-Type")
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def bbox_area(bbox: list[float]) -> float:
    west, south, east, north = bbox
    return abs((east - west) * (north - south))

def parse_bbox(raw: str) -> list[float]:
    nums = [float(x) for x in raw.split(",")]
    if len(nums) != 4:
        raise ValueError("bbox must have 4 numbers")
    return nums

def normalize_bbox(bbox: list[float]) -> list[float]:
    west, south, east, north = bbox
    return [
        max(-180.0, min(180.0, west)),
        max(-85.0, min(85.0, south)),
        max(-180.0, min(180.0, east)),
        max(-85.0, min(85.0, north)),
    ]

def make_geojson_polygon(bbox: list[float]) -> dict:
    west, south, east, north = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south]
        ]]
    }

def search_sentinel_scene(bbox: list[float], cloud_max: float, date_hint: str) -> dict:
    key = f"sentinel:{bbox}:{cloud_max}:{date_hint}"
    cached = cached_get(key)
    if cached:
        return cached

    dt_range = f"{date_hint}T00:00:00Z/{date_hint}T23:59:59Z" if date_hint else None
    body = {
        "collections": ["sentinel-2-l2a"],
        "intersects": make_geojson_polygon(bbox),
        "limit": 20,
        "query": {
            "eo:cloud_cover": {"lte": cloud_max}
        }
    }
    if dt_range:
        body["datetime"] = dt_range

    result = {
        "ok": False,
        "scene_source": "earth-search sentinel-2-l2a",
        "scene_date": None,
        "cloud_rank": None,
        "items": 0
    }

    try:
        _, _, raw = http_post_json(EARTHSEARCH_STAC, body)
        j = json.loads(raw.decode("utf-8"))
        feats = j.get("features", [])
        result["items"] = len(feats)
        if feats:
          feats.sort(key=lambda f: (
              float(f.get("properties", {}).get("eo:cloud_cover", 100.0)),
              f.get("properties", {}).get("datetime", "9999")
          ))
          best = feats[0]
          props = best.get("properties", {})
          result.update({
              "ok": True,
              "scene_date": props.get("datetime"),
              "cloud_rank": props.get("eo:cloud_cover"),
              "id": best.get("id")
          })
    except Exception as e:
        result["error"] = str(e)

    cached_set(key, result)
    return result

def search_landsat_scene(bbox: list[float], cloud_max: float, date_hint: str) -> dict:
    key = f"landsat:{bbox}:{cloud_max}:{date_hint}"
    cached = cached_get(key)
    if cached:
        return cached

    dt_range = f"{date_hint}T00:00:00Z/{date_hint}T23:59:59Z" if date_hint else None
    url = f"{LANDSAT_STAC}/search"
    body = {
        "collections": ["landsat-c2l2-sr"],
        "intersects": make_geojson_polygon(bbox),
        "limit": 20,
        "query": {
            "eo:cloud_cover": {"lte": cloud_max}
        }
    }
    if dt_range:
        body["datetime"] = dt_range

    result = {
        "ok": False,
        "scene_source": "landsatlook landsat-c2l2-sr",
        "scene_date": None,
        "cloud_rank": None,
        "items": 0
    }

    try:
        _, _, raw = http_post_json(url, body)
        j = json.loads(raw.decode("utf-8"))
        feats = j.get("features", [])
        result["items"] = len(feats)
        if feats:
            feats.sort(key=lambda f: (
                float(f.get("properties", {}).get("eo:cloud_cover", 100.0)),
                f.get("properties", {}).get("datetime", "9999")
            ))
            best = feats[0]
            props = best.get("properties", {})
            result.update({
                "ok": True,
                "scene_date": props.get("datetime"),
                "cloud_rank": props.get("eo:cloud_cover"),
                "id": best.get("id")
            })
    except Exception as e:
        result["error"] = str(e)

    cached_set(key, result)
    return result

def choose_base(
    bbox: list[float],
    gibs_date: str,
    sentinel_date: str,
    landsat_date: str,
    sentinel_template: str,
    gee_template: str,
    cloud_max: float
) -> dict:
    area = bbox_area(bbox)

    sentinel_meta = search_sentinel_scene(bbox, cloud_max, sentinel_date)
    landsat_meta = search_landsat_scene(bbox, cloud_max, landsat_date)

    # Honest ranking:
    # 1) licensed / custom template if user actually supplied it
    # 2) if viewport large, NASA daily imagery is often more coherent
    # 3) otherwise Esri fallback
    # 4) OSM as vector/cartography fallback

    if sentinel_template:
        return {
            "recommended_base": "sentinel_template",
            "custom_template": sentinel_template,
            "reason": "custom Sentinel template provided; broker prefers user-supplied freshest legal imagery path",
            "scene_source": sentinel_meta.get("scene_source"),
            "scene_date": sentinel_meta.get("scene_date"),
            "cloud_rank": sentinel_meta.get("cloud_rank"),
            "viewport_area": area
        }

    if gee_template:
        return {
            "recommended_base": "gee_template",
            "custom_template": gee_template,
            "reason": "custom Earth Engine template provided; broker prefers user-supplied processing path",
            "scene_source": landsat_meta.get("scene_source") if landsat_meta.get("ok") else sentinel_meta.get("scene_source"),
            "scene_date": landsat_meta.get("scene_date") or sentinel_meta.get("scene_date"),
            "cloud_rank": landsat_meta.get("cloud_rank") if landsat_meta.get("ok") else sentinel_meta.get("cloud_rank"),
            "viewport_area": area
        }

    if area > 800:
        return {
            "recommended_base": "gibs_viirs",
            "custom_template": "",
            "reason": "very large viewport; daily VIIRS composite is visually stable at continental scale",
            "scene_source": "NASA GIBS VIIRS",
            "scene_date": gibs_date,
            "cloud_rank": None,
            "viewport_area": area
        }

    if area > 150:
        return {
            "recommended_base": "esri",
            "custom_template": "",
            "reason": "medium viewport without licensed custom imagery; Esri provides the best general basemap fallback",
            "scene_source": "Esri World Imagery",
            "scene_date": None,
            "cloud_rank": None,
            "viewport_area": area
        }

    # Small view: still Esri unless user has custom licensed source
    return {
        "recommended_base": "esri",
        "custom_template": "",
        "reason": "small viewport but no legal high-resolution custom tile source was supplied",
        "scene_source": "Esri World Imagery",
        "scene_date": None,
        "cloud_rank": sentinel_meta.get("cloud_rank"),
        "viewport_area": area
    }

class Handler(BaseHTTPRequestHandler):
    server_version = "EarthCockpitV23Broker/1.0"

    def _send(self, code: int, content: bytes, content_type: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "/":
                self._send(200, jdump({
                    "ok": True,
                    "service": "Earth Cockpit v23 broker",
                    "health": "/health",
                    "base": "/broker/base?bbox=west,south,east,north",
                    "time": utc_now()
                }))
                return

            if path == "/health":
                self._send(200, jdump({
                    "ok": True,
                    "service": "Earth Cockpit v23 broker",
                    "time": utc_now(),
                    "cache_entries": len(CACHE)
                }))
                return

            if path == "/broker/base":
                raw_bbox = (qs.get("bbox") or [""])[0]
                if not raw_bbox:
                    self._send(400, jdump({"ok": False, "error": "missing bbox"}))
                    return

                bbox = normalize_bbox(parse_bbox(raw_bbox))
                sentinel_date = (qs.get("sentinel_date") or [""])[0].strip()
                landsat_date = (qs.get("landsat_date") or [""])[0].strip()
                gibs_date = (qs.get("gibs_date") or [""])[0].strip() or time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
                sentinel_template = urllib.parse.unquote((qs.get("sentinel_template") or [""])[0]).strip()
                gee_template = urllib.parse.unquote((qs.get("gee_template") or [""])[0]).strip()
                cloud_max = float((qs.get("cloud_max") or ["20"])[0])

                result = choose_base(
                    bbox=bbox,
                    gibs_date=gibs_date,
                    sentinel_date=sentinel_date,
                    landsat_date=landsat_date,
                    sentinel_template=sentinel_template,
                    gee_template=gee_template,
                    cloud_max=cloud_max
                )
                result["ok"] = True
                result["bbox"] = bbox
                result["time"] = utc_now()
                self._send(200, jdump(result))
                return

            if path == "/proxy":
                target = (qs.get("url") or [""])[0]
                if not target or not re.match(r"^https?://", target, re.I):
                    self._send(400, jdump({"ok": False, "error": "bad url"}))
                    return

                req = urllib.request.Request(target, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read()
                    self.send_response(resp.getcode())
                    self.send_header("Content-Type", resp.headers.get("Content-Type", "application/octet-stream"))
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(body)
                return

            self._send(404, jdump({"ok": False, "error": "Not found"}))

        except Exception as e:
            self._send(500, jdump({"ok": False, "error": str(e)}))

def main():
    print(f"Earth Cockpit v23 broker listening on http://{HOST}:{PORT}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()

if __name__ == "__main__":
    main()
