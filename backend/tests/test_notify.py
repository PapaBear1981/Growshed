import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from growshed.notify import Notification, Notifier, ping


@pytest.fixture
def server():
    """A tiny local stand-in for the ntfy server that records what it receives."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, dict(self.headers), json.loads(body)))
            self.send_response(500 if "fail" in body.decode() else 200)
            self.end_headers()

        def do_GET(self):
            received.append((self.path, dict(self.headers), None))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", received
    httpd.shutdown()


async def test_send_posts_json_to_the_topic(server):
    url, received = server
    notifier = Notifier(f"{url}/growshed-secret", token="tok")
    note = Notification("CRITICAL: Leak detected", "Tent 1 · Floor leak", 5, ("rotating_light",))
    assert await notifier.send(note) is True
    path, headers, body = received[0]
    assert path == "/" and headers["Authorization"] == "Bearer tok"
    assert body == {
        "topic": "growshed-secret",
        "title": "CRITICAL: Leak detected",
        "message": "Tent 1 · Floor leak",  # non-ASCII survives because it travels as JSON
        "priority": 5,
        "tags": ["rotating_light"],
    }


async def test_send_reports_failure_instead_of_raising(server):
    url, _ = server
    assert await Notifier(f"{url}/topic").send(Notification("x", "fail")) is False
    assert await Notifier("http://127.0.0.1:9/topic").send(Notification("x", "y")) is False


async def test_unconfigured_notifier_is_a_quiet_no_op():
    for url in (None, "", "https://ntfy.sh"):  # no topic in the URL
        notifier = Notifier(url)
        assert not notifier.configured
        assert await notifier.send(Notification("x", "y")) is True


async def test_ping(server):
    url, received = server
    assert await ping(f"{url}/alive") is True
    assert received[0][0] == "/alive"
    assert await ping("http://127.0.0.1:9/alive") is False
