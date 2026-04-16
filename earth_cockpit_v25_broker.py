#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import json
import ssl

HOST = "127.0.0.1"
PORT = 8787

ssl_ctx = ssl.create_default_context()

def j(obj):
    return json.dumps(obj).encode("utf-8")

class Broker(BaseHTTPRequestHandler):

    def send(self, code=200, ctype="application/json", body=b""):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_OPTIONS(self):
        self.send(204)

    def do_GET(self):

        p = urlparse(self.path)

        # Health check
        if p.path == "/health":
            self.send(200, body=j({
                "status":"ok",
                "service":"earth-cockpit-broker"
            }))
            return

        # Imagery freshness selection
        if p.path == "/broker/base":

            qs = parse_qs(p.query)

            rows = [
                {
                    "key":"gibs_viirs",
                    "name":"NASA VIIRS",
                    "age_hours":24,
                    "source_date":qs.get("gibs_date",[""])[0]
                },
                {
                    "key":"gibs_modis",
                    "name":"NASA MODIS",
                    "age_hours":30,
                    "source_date":qs.get("gibs_date",[""])[0]
                },
                {
                    "key":"esri",
                    "name":"Esri World Imagery",
                    "age_hours":500,
                    "source_date":"mosaic"
                },
                {
                    "key":"osm",
                    "name":"OpenStreetMap",
                    "age_hours":9000,
                    "source_date":"vector"
                }
            ]

            best = sorted(rows, key=lambda r:r["age_hours"])[0]["key"]

            self.send(200, body=j({
                "best_key":best,
                "rows":rows
            }))
            return

        # Proxy for APIs
        if p.path == "/proxy":

            qs = parse_qs(p.query)
            url = qs.get("url",[""])[0]

            if not url:
                self.send(400, body=j({"error":"missing url"}))
                return

            try:
                req = Request(
                    unquote(url),
                    headers={"User-Agent":"EarthCockpitBroker"}
                )

                with urlopen(req, context=ssl_ctx, timeout=20) as r:
                    data = r.read()
                    ctype = r.headers.get("Content-Type","application/octet-stream")

                self.send(200, ctype, data)
                return

            except HTTPError as e:
                self.send(e.code, body=j({"error":"upstream http error"}))
                return

            except URLError:
                self.send(502, body=j({"error":"upstream unreachable"}))
                return

        self.send(404, body=j({"error":"not found"}))


def main():
    server = HTTPServer((HOST, PORT), Broker)
    print(f"Earth Cockpit broker running at http://{HOST}:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    main()
