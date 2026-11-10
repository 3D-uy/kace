"""The Pi accepts only an exact, bounded result on the current Studio tunnel."""
import base64
import json
import socket
import threading

import pytest

from core import studio_preflight as client
from core.klipper_preflight import _digest


IDENTITY = {"pin": "a" * 40, "engine_sha256": "b" * 64,
            "dockerfile_sha256": "c" * 64, "worker_sha256": "d" * 64}
FILES = {"printer.cfg": b"[include macros.cfg]\n", "macros.cfg": b"# preserved\n"}
TOKEN = "e" * 64
SESSION = "f" * 32


@pytest.fixture(autouse=True)
def bridge_environment(monkeypatch):
    monkeypatch.setenv(client.PORT_ENV, "32123")
    monkeypatch.setenv(client.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(client.SESSION_ENV, SESSION)


def response(request, **changes):
    result = {key: value for key, value in request.items() if key not in {"token", "files"}}
    result.update(status="valid", detail="fan references checked in pinned image")
    result.update(changes)
    return json.dumps(result).encode()


class Connection:
    def __init__(self, reply=response, *, fragment=7):
        self.reply = reply
        self.fragment = fragment
        self.received = b""
        self.timeouts = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def sendall(self, data):
        assert int.from_bytes(data[:4], "big") == len(data[4:])
        self.request = json.loads(data[4:])
        payload = self.reply(self.request)
        self.received = len(payload).to_bytes(4, "big") + payload

    def recv(self, limit):
        chunk = self.received[:min(limit, self.fragment)]
        self.received = self.received[len(chunk):]
        return chunk


def connect(monkeypatch, reply=response):
    connection = Connection(reply)
    destinations = []

    def open_connection(address, *, timeout):
        destinations.append(address)
        assert 0 < timeout <= client.TIMEOUT_SECONDS
        return connection

    monkeypatch.setattr(client.socket, "create_connection", open_connection)
    return connection, destinations


def validate(files=None, identity=None, digest=None):
    files = FILES if files is None else files
    return client.validate_files(files, IDENTITY if identity is None else identity,
                                 _digest(files) if digest is None else digest)


@pytest.mark.parametrize("status", ["valid", "invalid", "unverified"])
def test_exact_current_result_and_binary_tree_cross_only_loopback(monkeypatch, status):
    connection, destinations = connect(monkeypatch, lambda request: response(request, status=status))
    files = {**FILES, "nested/unchanged.cfg": b"\x00\xff\r\n"}
    result = validate(files)
    assert result["status"] == status
    assert result["tree_digest"] == _digest(files)
    assert destinations == [("127.0.0.1", 32123)]
    assert connection.closed
    assert len(connection.request["request_id"]) == 32
    assert {item["path"]: base64.b64decode(item["content_base64"], validate=True)
            for item in connection.request["files"]} == files
    assert TOKEN not in repr(result)


@pytest.mark.parametrize("field,value", [
    ("schema", "kace-studio-preflight/v2"), ("session", "0" * 32),
    ("request_id", "0" * 32), ("pin", "0" * 40), ("tree_digest", "0" * 64),
    ("engine_sha256", "0" * 64), ("dockerfile_sha256", "0" * 64),
    ("worker_sha256", "0" * 64), ("status", True), ("status", "approved"),
    ("detail", {}), ("detail", "x" * 4097), ("session", None),
])
def test_stale_or_malformed_result_cannot_approve(monkeypatch, field, value):
    connect(monkeypatch, lambda request: response(request, **{field: value}))
    assert validate()["status"] == "unverified"


@pytest.mark.parametrize("name,value", [
    (client.PORT_ENV, ""), (client.PORT_ENV, "0"), (client.PORT_ENV, "65536"),
    (client.PORT_ENV, "127.0.0.1:80"), (client.PORT_ENV, " 80"),
    (client.TOKEN_ENV, ""), (client.TOKEN_ENV, "secret"),
    (client.SESSION_ENV, ""), (client.SESSION_ENV, "x" * 32),
])
def test_partial_environment_never_falls_back_or_connects(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(client.socket, "create_connection", lambda *_a, **_k: pytest.fail("must not connect"))
    assert client.configured()
    result = validate()
    assert result["status"] == "unverified"
    assert TOKEN not in result["detail"]


def test_presence_of_even_one_empty_variable_selects_fail_closed_bridge(monkeypatch):
    for name in (client.PORT_ENV, client.TOKEN_ENV, client.SESSION_ENV):
        monkeypatch.delenv(name)
    assert not client.configured()
    monkeypatch.setenv(client.PORT_ENV, "")
    assert client.configured()
    assert validate()["status"] == "unverified"


@pytest.mark.parametrize("payload", [b"{}", b"[]", b"not json", b"\xff",
                                       b'{"schema": 1,"schema": 2}', b'{"status": NaN}',
                                       b'[' * 2000 + b'0' + b']' * 2000])
def test_malformed_json_and_duplicate_keys_fail_closed(monkeypatch, payload):
    connect(monkeypatch, lambda _request: payload)
    assert validate()["status"] == "unverified"


def test_unknown_fields_and_echoed_secrets_fail_closed(monkeypatch):
    connect(monkeypatch, lambda request: response(request, token=TOKEN))
    result = validate()
    assert result["status"] == "unverified"
    assert TOKEN not in repr(result)


def test_diagnostic_redacts_token_even_from_successful_server(monkeypatch):
    connect(monkeypatch, lambda request: response(request, detail="diagnostic " + TOKEN))
    result = validate()
    assert result["status"] == "valid"
    assert result["detail"] == "diagnostic [redacted]"


@pytest.mark.parametrize("exception", [TimeoutError(TOKEN), OSError(TOKEN), ConnectionRefusedError(TOKEN)])
def test_transport_failures_are_unverified_and_do_not_leak_credentials(monkeypatch, exception):
    def unavailable(*_args, **_kwargs):
        raise exception
    monkeypatch.setattr(client.socket, "create_connection", unavailable)
    result = validate()
    assert result["status"] == "unverified"
    assert TOKEN not in repr(result)


def test_disconnection_before_complete_frame_is_unverified(monkeypatch):
    connection, _ = connect(monkeypatch)
    connection.recv = lambda _limit: b""
    assert validate()["status"] == "unverified"
    assert connection.closed


def test_response_length_is_rejected_before_body_is_read(monkeypatch):
    connection, _ = connect(monkeypatch)
    calls = []
    def oversized(limit):
        calls.append(limit)
        assert len(calls) == 1
        return (client.MAX_RESPONSE_BYTES + 1).to_bytes(4, "big")
    connection.recv = oversized
    assert validate()["status"] == "unverified"
    assert calls == [4]


def test_partial_progress_does_not_reset_absolute_deadline(monkeypatch):
    connection, _ = connect(monkeypatch)
    elapsed = [0.0]
    monkeypatch.setattr(client.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(client, "TIMEOUT_SECONDS", 3.0)
    original_recv = connection.recv
    def slow_receive(limit):
        elapsed[0] += 1.0
        return original_recv(min(limit, 1))
    connection.recv = slow_receive
    result = validate()
    assert result["status"] == "unverified"
    assert "timed out" in result["detail"]
    assert elapsed[0] == 3.0
    assert connection.closed


@pytest.mark.parametrize("files", [
    {}, {"printer.cfg": "not bytes"}, {"printer.cfg": b"", "../outside": b""},
    {"printer.cfg": b"", "/absolute": b""}, {"printer.cfg": b"", "C:/other": b""},
    {"printer.cfg": b"", "folder\\other.cfg": b""},
    {"printer.cfg": b"", "a//b.cfg": b""},
    {"printer.cfg": b"", "a": b"", "a/b.cfg": b""},
])
def test_invalid_paths_or_types_are_not_sent(monkeypatch, files):
    monkeypatch.setattr(client.socket, "create_connection", lambda *_a, **_k: pytest.fail("must not connect"))
    assert validate(files, digest="0" * 64)["status"] == "unverified"


def test_changed_tree_and_limits_are_rejected_before_connect(monkeypatch):
    monkeypatch.setattr(client.socket, "create_connection", lambda *_a, **_k: pytest.fail("must not connect"))
    assert validate({**FILES, "macros.cfg": b"changed"}, digest=_digest(FILES))["status"] == "unverified"
    monkeypatch.setattr(client, "MAX_CONTENT_BYTES", 3)
    assert validate()["status"] == "unverified"
    monkeypatch.setattr(client, "MAX_CONTENT_BYTES", 1024)
    monkeypatch.setattr(client, "MAX_FILES", 1)
    assert validate()["status"] == "unverified"
    monkeypatch.setattr(client, "MAX_FILES", 128)
    monkeypatch.setattr(client, "MAX_REQUEST_BYTES", 3)
    assert validate()["status"] == "unverified"


@pytest.mark.parametrize("identity", [{}, {**IDENTITY, "extra": "field"}, {**IDENTITY, "pin": "latest"},
                                        {**IDENTITY, "engine_sha256": None}])
def test_unknown_validator_identity_is_not_sent(monkeypatch, identity):
    monkeypatch.setattr(client.socket, "create_connection", lambda *_a, **_k: pytest.fail("must not connect"))
    assert validate(identity=identity)["status"] == "unverified"


def test_two_requests_have_distinct_nonce_and_old_response_is_rejected(monkeypatch):
    connection, _ = connect(monkeypatch)
    assert validate()["status"] == "valid"
    prior_response = response(connection.request)
    prior_nonce = connection.request["request_id"]
    second, _ = connect(monkeypatch, lambda _request: prior_response)
    assert validate()["status"] == "unverified"
    assert second.request["request_id"] != prior_nonce


def test_actual_loopback_framing_without_docker(monkeypatch):
    errors = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(2)
        monkeypatch.setenv(client.PORT_ENV, str(listener.getsockname()[1]))
        def serve():
            try:
                with listener.accept()[0] as connection:
                    deadline = client.time.monotonic() + 2
                    size = int.from_bytes(client._receive_exact(connection, 4, deadline), "big")
                    request = json.loads(client._receive_exact(connection, size, deadline))
                    assert request["session"] == SESSION and request["token"] == TOKEN
                    payload = response(request, status="invalid", detail="Unknown heater 'missing'")
                    connection.sendall(len(payload).to_bytes(4, "big") + payload)
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        result = validate()
        worker.join(3)
        assert not worker.is_alive()
        assert not errors
        assert result["status"] == "invalid"
