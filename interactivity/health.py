"""Trivial HTTP health endpoint. Cloud Run requires the container to listen on
$PORT even though this process serves no real HTTP (all Slack traffic is over
the Socket Mode WebSocket). Any request gets a 200 "OK"."""
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import HEALTH_PORT  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):  # silence per-request logging
        pass


def start_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[health] listening on :{HEALTH_PORT}")
    return server
