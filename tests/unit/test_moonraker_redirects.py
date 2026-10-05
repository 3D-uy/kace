"""HTTP regressions with synthetic loopback endpoints; no printer access."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.fixture
def endpoints():
    seen = []
    mode = {"code": 302, "relative": False, "direct": False}

    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            seen.append((self.server.role, self.command, self.path, dict(self.headers), data))
            if self.server.role == "origin" and self.path != "/sink" and not mode["direct"]:
                self.send_response(mode["code"])
                target = "/sink" if mode["relative"] is True else f"http://127.0.0.1:{destination.server_port}/sink"
                if mode["relative"] == "scheme":
                    target = target.replace("http:", "https:", 1)
                self.send_header("Location", target)
                self.end_headers()
            else:
                body = json.dumps({"result": {"devices": [{"device": "main_psu", "status": "on"}]}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        do_GET = do_POST = do_DELETE = handle_request

        def log_message(self, *_args):
            pass

    servers = []
    workers = []
    for role in ("destination", "origin"):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.role = role
        servers.append(server)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        workers.append(worker)
    destination, origin = servers
    try:
        yield f"http://127.0.0.1:{origin.server_port}", mode, seen
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for worker in workers:
            worker.join(2)

from core import moonraker


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("relative", [False, True, "scheme"])
@pytest.mark.parametrize("operation", ["get", "post", "delete", "multipart", "download"])
def test_redirect_never_sends_a_second_request(endpoints, code, relative, operation):
    base, mode, seen = endpoints
    mode.update(code=code, relative=relative)
    key = "synthetic-audit-api-key"
    if operation == "get":
        result = moonraker._get(base + "/request", api_key=key)
    elif operation == "post":
        result = moonraker._post(base + "/request", data=b'{"action":"on"}', api_key=key)
    elif operation == "delete":
        result = moonraker._delete(base + "/request", api_key=key)
    elif operation == "multipart":
        result = moonraker._post_multipart(base + "/request", "file", "printer.cfg", b"synthetic config", api_key=key)
    else:
        result = moonraker.download_printer_cfg(base, 7125, "printer.cfg", api_key=key)
    assert result[0] is False
    message = result[1].decode() if isinstance(result[1], bytes) else result[1]
    assert "redirect" in message.lower()
    assert key not in message
    assert len(seen) == 1
    assert seen[0][0] == "origin"
    assert seen[0][3]["X-Api-Key"] == key


def test_direct_json_and_binary_requests_remain_available(endpoints):
    base, mode, seen = endpoints
    mode["direct"] = True
    assert moonraker._get(base + "/request")[0] is True
    assert moonraker._post(base + "/request")[0] is True
    assert moonraker._delete(base + "/request")[0] is True
    assert moonraker.download_printer_cfg(base, 7125, "printer.cfg")[0] is True
    assert len(seen) == 4
