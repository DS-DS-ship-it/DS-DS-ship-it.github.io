#!/usr/bin/env python3
import http.server
import socketserver
import urllib.parse
import urllib.request
import ssl

PORT = 8080

ssl_context = ssl.create_default_context()

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path == "/proxy-ping":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK")
            return

        if self.path.startswith("/proxy?url="):
            raw = self.path.split("/proxy?url=", 1)[1]
            target = urllib.parse.unquote(raw)

            if not (target.startswith("http://") or target.startswith("https://")):
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Bad url")
                return

            try:
                req = urllib.request.Request(
                    target,
                    headers={
                        "User-Agent": "EarthCockpitProxy/1.0",
                        "Accept": "*/*",
                    }
                )
                with urllib.request.urlopen(req, timeout=25, context=ssl_context) as resp:
                    data = resp.read()
                    ct = resp.headers.get("Content-Type", "application/octet-stream")
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                return
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Proxy error: {e}".encode("utf-8"))
                return

        return super().do_GET()

if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving on http://127.0.0.1:{PORT}")
        httpd.serve_forever()
