#!/usr/bin/env python3
"""
radar_cache_server.py
Local radar tile recorder + XYZ tile server.

- Runs on http://localhost:8765
- Serves:
  GET /manifest -> {"times":[unix,...]}
  GET /tiles/{t}/{z}/{x}/{y}.png -> cached (or fetched+cached) radar tile

This builds multi-day history while it is running.
It does NOT magically download a full 7-day archive on day 1 unless upstream provides it.
"""

import os
import json
import time
import threading
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765

CACHE_DIR = Path(os.environ.get("RADAR_CACHE_DIR", "./radar_cache")).resolve()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

RAINVIEWER_API = "https://api.rainviewer.com/public/weather-maps.json"

POLL_SECONDS = 120
RETENTION_DAYS = 8

times_lock = threading.Lock()
known_times = []

def fetch_json(url: str):
  with urllib.request.urlopen(url, timeout=20) as r:
    return json.loads(r.read().decode("utf-8"))

def rainviewer_frames():
  j = fetch_json(RAINVIEWER_API)
  host = j.get("host", "https://tilecache.rainviewer.com")
  radar = j.get("radar", {}) or {}
  past = radar.get("past", []) or []
  nowcast = radar.get("nowcast", []) or []
  allf = past + nowcast
  times = []
  for f in allf:
    t = f.get("time")
    if isinstance(t, int):
      times.append(t)
  times = sorted(set(times))
  return host, times

def cleanup_old():
  cutoff = time.time() - (RETENTION_DAYS * 86400)
  for tdir in CACHE_DIR.glob("*/"):
    try:
      t = int(tdir.name)
    except:
      continue
    if t < cutoff:
      try:
        for p in tdir.rglob("*"):
          if p.is_file():
            p.unlink(missing_ok=True)
        for p in sorted(tdir.rglob("*"), reverse=True):
          if p.is_dir():
            p.rmdir()
        tdir.rmdir()
      except:
        pass

def recorder_loop():
  global known_times
  while True:
    try:
      _, times = rainviewer_frames()
      with times_lock:
        known_times = times[-2000:]
      cleanup_old()
    except Exception:
      pass
    time.sleep(POLL_SECONDS)

def tile_cache_path(t: int, z: int, x: int, y: int) -> Path:
  return CACHE_DIR / str(t) / str(z) / str(x) / f"{y}.png"

def ensure_parent(p: Path):
  p.parent.mkdir(parents=True, exist_ok=True)

def fetch_tile_rainviewer(host: str, t: int, z: int, x: int, y: int) -> bytes:
  url = f"{host}/v2/radar/{t}/256/{z}/{x}/{y}/2/1_1.png"
  with urllib.request.urlopen(url, timeout=20) as r:
    return r.read()

class Handler(BaseHTTPRequestHandler):
  def _send(self, code=200, ctype="application/json", body=b""):
    self.send_response(code)
    self.send_header("Content-Type", ctype)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()
    self.wfile.write(body)

  def do_OPTIONS(self):
    self.send_response(200)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "*")
    self.end_headers()

  def do_GET(self):
    try:
      path = urlparse(self.path).path

      if path == "/manifest":
        with times_lock:
          times = list(known_times)
        body = json.dumps({
          "times": times,
          "template": "/tiles/{t}/{z}/{x}/{y}.png",
          "note": "History grows while this recorder runs. Provider archive length varies."
        }).encode("utf-8")
        return self._send(200, "application/json", body)

      if path.startswith("/tiles/"):
        parts = path.split("/")
        if len(parts) != 6:
          return self._send(404, "text/plain", b"bad tile path")

        t = int(parts[2]); z = int(parts[3]); x = int(parts[4])
        ystr = parts[5]
        if not ystr.endswith(".png"):
          return self._send(404, "text/plain", b"bad tile y")
        y = int(ystr[:-4])

        out = tile_cache_path(t, z, x, y)
        if out.exists():
          return self._send(200, "image/png", out.read_bytes())

        host, _ = rainviewer_frames()
        data = fetch_tile_rainviewer(host, t, z, x, y)
        ensure_parent(out)
        out.write_bytes(data)
        return self._send(200, "image/png", data)

      return self._send(404, "text/plain", b"not found")
    except Exception as e:
      return self._send(500, "text/plain", f"error: {e}".encode("utf-8"))

def main():
  print(f"[radar_cache_server] cache dir: {CACHE_DIR}")
  print(f"[radar_cache_server] serving on http://{HOST}:{PORT}")
  t = threading.Thread(target=recorder_loop, daemon=True)
  t.start()
  HTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
  main()
