#!/usr/bin/env python3
"""
serve_proxy.py — tiny static server + CORS proxy for Earth Cockpit.

Why:
- Cesium/WebGL requires CORS-enabled images to upload into GPU textures.
- Many public tile servers (including some radar tiles) don't send permissive CORS headers.
- This proxy fetches the tile server-side and returns it with Access-Control-Allow-Origin: *

Run:
  python3 serve_proxy.py

Then open:
  http://127.0.0.1:8080/earth-cockpit-v6_1.html
"""

import http.server
import socketserver
import urllib.parse
import urllib.request
import time

PORT = 8080

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Allow this server to be used from your browser freely
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/proxy":
            qs = urllib.parse.parse_qs(parsed.query)
            if "url" not in qs or not qs["url"]:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Missing ?url=")
                return

            target = qs["url"][0]

            # Basic safety: allow only http/https
            if not (target.startswith("http://") or target.startswith("https://")):
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Only http/https allowed.")
                return

            try:
                req = urllib.request.Request(
                    target,
                    headers={
                        "User-Agent": "EarthCockpitProxy/1.0",
                        "Accept": "*/*",
                    },
                    method="GET"
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
                    ctype = resp.headers.get("Content-Type", "application/octet-stream")

                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "public, max-age=120")
                self.send_header("X-Proxied-At", str(int(time.time())))
                self.end_headers()
                self.wfile.write(data)
                return

            except Exception as e:
                msg = f"Proxy fetch failed: {e}\nURL: {target}\n"
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(msg.encode("utf-8"))
                return

        # Otherwise: serve files normally (earth-cockpit-v6_1.html etc.)
        return super().do_GET()


if __name__ == "__main__":
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving on http://127.0.0.1:{PORT}")
        print("Proxy endpoint: /proxy?url=https%3A%2F%2Fexample.com%2Ftile.png")
        httpd.serve_forever()
