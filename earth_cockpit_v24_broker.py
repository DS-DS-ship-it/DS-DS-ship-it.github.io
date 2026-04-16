#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8787
USER_AGENT = "EarthCockpitV24Broker/1.0"
CACHE_TTL = 180

CACHE: dict[str, tuple[float, dict]] = {}

EARTHSEARCH_STAC = "https://earth-search.aws.element84.com/v1/search"
LANDSATLOOK_STAC = "https://landsatlook.usgs.gov/stac-server/search"

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
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.getcode(), dict(resp.headers.items()), resp.read()

def http_post_json(url: str, body: dict, timeout: int = 30, headers: dict | None = None) -> tuple[int, dict, bytes]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})}
    )
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
            "content_type": headers.get("Content-Type"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def parse_bbox(raw: str) -> list[float]:
    nums = [float(x) for x in raw.split(",")]
    if len(nums) != 4:
        raise ValueError("bbox must have 4 comma-separated numbers")
    return nums

def normalize_lon(lon: float) -> float:
    while lon < -180.0:
        lon += 360.0
    while lon > 180.0:
        lon -= 360.0
    return lon

def normalize_bbox(bbox: list[float]) -> list[float]:
    west, south, east, north = bbox
    west = normalize_lon(west)
    east = normalize_lon(east)
    south = max(-85.0, min(85.0, south))
    north = max(-85.0, min(85.0, north))
    if east < west:
        east += 360.0
    return [west, south, east, north]

def bbox_area(bbox: list[float]) -> float:
    west, south, east, north = bbox
    return abs((east - west) * (north - south))

def make_geojson_polygon(bbox: list[float]) -> dict:
    west, south, east, north = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south]
        ]]
    }

def pick_best_feature(features: list[dict]) -> dict | None:
    if not features:
        return None
    features = sorted(
        features,
        key=lambda f: (
            float(f.get("properties", {}).get("eo:cloud_cover", 100.0)),
            -_date_score(f.get("properties", {}).get("datetime", "")),
        )
    )
    return features[0]

def _date_score(s: str) -> float:
    if not s:
        return 0.0
    try:
        st = s[:19]
        t = time.strptime(st, "%Y-%m-%dT%H:%M:%S")
        return time.mktime(t)
    except Exception:
        return 0.0

def search_sentinel_scene(bbox: list[float], cloud_max: float, date_hint: str) -> dict:
    key = f"sentinel:{bbox}:{cloud_max}:{date_hint}"
    cached = cached_get(key)
    if cached:
        return cached

    body = {
        "collections": ["sentinel-2-l2a"],
        "intersects": make_geojson_polygon(bbox),
        "limit": 25,
        "query": {"eo:cloud_cover": {"lte": cloud_max}}
    }
    if date_hint:
        body["datetime"] = f"{date_hint}T00:00:00Z/{date_hint}T23:59:59Z"

    result = {
        "ok": False,
        "scene_source": "sentinel-2-l2a",
        "scene_date": None,
        "cloud_rank": None,
        "id": None,
        "items": 0
    }

    try:
        _, _, raw = http_post_json(EARTHSEARCH_STAC, body)
        j = json.loads(raw.decode("utf-8"))
        feats = j.get("features", [])
        result["items"] = len(feats)
        best = pick_best_feature(feats)
        if best:
            props = best.get("properties", {})
            result.update({
                "ok": True,
                "id": best.get("id"),
                "scene_date": props.get("datetime"),
                "cloud_rank": props.get("eo:cloud_cover"),
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

    body = {
        "collections": ["landsat-c2l2-sr"],
        "intersects": make_geojson_polygon(bbox),
        "limit": 25,
        "query": {"eo:cloud_cover": {"lte": cloud_max}}
    }
    if date_hint:
        body["datetime"] = f"{date_hint}T00:00:00Z/{date_hint}T23:59:59Z"

    result = {
        "ok": False,
        "scene_source": "landsat-c2l2-sr",
        "scene_date": None,
        "cloud_rank": None,
        "id": None,
        "items": 0
    }

    try:
        _, _, raw = http_post_json(LANDSATLOOK_STAC, body)
        j = json.loads(raw.decode("utf-8"))
        feats = j.get("features", [])
        result["items"] = len(feats)
        best = pick_best_feature(feats)
        if best:
            props = best.get("properties", {})
            result.update({
                "ok": True,
                "id": best.get("id"),
                "scene_date": props.get("datetime"),
                "cloud_rank": props.get("eo:cloud_cover"),
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
    landsat_template: str,
    commercial_template: str,
    cloud_max: float
) -> dict:
    area = bbox_area(bbox)
    sentinel_meta = search_sentinel_scene(bbox, cloud_max, sentinel_date)
    landsat_meta = search_landsat_scene(bbox, cloud_max, landsat_date)

    if commercial_template:
        return {
            "recommended_base": "commercial_template",
            "custom_template": commercial_template,
            "reason": "licensed commercial template supplied by user",
            "scene_source": "commercial user template",
            "scene_date": None,
            "cloud_rank": None,
            "sentinel_scene_date": sentinel_meta.get("scene_date"),
            "landsat_scene_date": landsat_meta.get("scene_date"),
            "viewport_area": area
        }

    if sentinel_template:
        return {
            "recommended_base": "sentinel_template",
            "custom_template": sentinel_template,
            "reason": "custom Sentinel template supplied by user",
            "scene_source": sentinel_meta.get("scene_source"),
            "scene_date": sentinel_meta.get("scene_date"),
            "cloud_rank": sentinel_meta.get("cloud_rank"),
            "sentinel_scene_date": sentinel_meta.get("scene_date"),
            "landsat_scene_date": landsat_meta.get("scene_date"),
            "viewport_area": area
        }

    if landsat_template:
        return {
            "recommended_base": "landsat_template",
            "custom_template": landsat_template,
            "reason": "custom Landsat template supplied by user",
            "scene_source": landsat_meta.get("scene_source"),
            "scene_date": landsat_meta.get("scene_date"),
            "cloud_rank": landsat_meta.get("cloud_rank"),
            "sentinel_scene_date": sentinel_meta.get("scene_date"),
            "landsat_scene_date": landsat_meta.get("scene_date"),
            "viewport_area": area
        }

    if area > 800:
        return {
            "recommended_base": "gibs_viirs",
            "custom_template": "",
            "reason": "large viewport; daily VIIRS composite is stable for continental/global viewing",
            "scene_source": "NASA GIBS VIIRS",
            "scene_date": gibs_date,
            "cloud_rank": None,
            "sentinel_scene_date": sentinel_meta.get("scene_date"),
            "landsat_scene_date": landsat_meta.get("scene_date"),
            "viewport_area": area
        }

    if area > 150:
        return {
            "recommended_base": "esri",
            "custom_template": "",
            "reason": "medium viewport; Esri is the best general fallback without custom licensed high-resolution tiles",
            "scene_source": "Esri",
            "scene_date": None,
            "cloud_rank": sentinel_meta.get("cloud_rank"),
            "sentinel_scene_date": sentinel_meta.get("scene_date"),
            "landsat_scene_date": landsat_meta.get("scene_date"),
            "viewport_area": area
        }

    return {
        "recommended_base": "esri",
        "custom_template": "",
        "reason": "small viewport but no higher-resolution licensed custom tiles were supplied",
        "scene_source": "Esri",
        "scene_date": None,
        "cloud_rank": sentinel_meta.get("cloud_rank"),
        "sentinel_scene_date": sentinel_meta.get("scene_date"),
        "landsat_scene_date": landsat_meta.get("scene_date"),
        "viewport_area": area
    }

def lidar_availability_stub(bbox: list[float]) -> dict:
    # Public lidar is patchy; this endpoint is a broker-side availability hook, not a universal guarantee.
    area = bbox_area(bbox)
    return {
        "ok": True,
        "available": area < 50.0,
        "note": "public lidar/DEM may be available for smaller regional viewports; connect OpenTopography-specific dataset lookup here",
        "bbox": bbox
    }

class Handler(BaseHTTPRequestHandler):
    server_version = "EarthCockpitV24Broker/1.0"

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
                    "service": "Earth Cockpit v24 broker",
                    "health": "/health",
                    "base": "/broker/base?bbox=west,south,east,north",
                    "lidar": "/broker/lidar?bbox=west,south,east,north",
                    "time": utc_now()
                }))
                return

            if path == "/health":
                self._send(200, jdump({
                    "ok": True,
                    "service": "Earth Cockpit v24 broker",
                    "time": utc_now(),
                    "cache_entries": len(CACHE)
                }))
                return

            if path == "/broker/lidar":
                raw_bbox = (qs.get("bbox") or [""])[0]
                if not raw_bbox:
                    self._send(400, jdump({"ok": False, "error": "missing bbox"}))
                    return
                bbox = normalize_bbox(parse_bbox(raw_bbox))
                result = lidar_availability_stub(bbox)
                result["time"] = utc_now()
                self._send(200, jdump(result))
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
                landsat_template = urllib.parse.unquote((qs.get("landsat_template") or [""])[0]).strip()
                commercial_template = urllib.parse.unquote((qs.get("commercial_template") or [""])[0]).strip()
                cloud_max = float((qs.get("cloud_max") or ["20"])[0])

                result = choose_base(
                    bbox=bbox,
                    gibs_date=gibs_date,
                    sentinel_date=sentinel_date,
                    landsat_date=landsat_date,
                    sentinel_template=sentinel_template,
                    landsat_template=landsat_template,
                    commercial_template=commercial_template,
                    cloud_max=cloud_max
                )
                result["ok"] = True
                result["bbox"] = bbox
                result["time"] = utc_now()
                self._send(200, jdump(result))
                return

            if path == "/proxy":
                target = (qs.get("url") or [""])[0]
                if not target.startswith("http://") and not target.startswith("https://"):
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
    print(f"Earth Cockpit v24 broker listening on http://{HOST}:{PORT}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()

if __name__ == "__main__":
    main()
