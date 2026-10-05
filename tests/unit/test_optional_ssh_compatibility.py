"""Real loopback SSH handshake with the pinned optional dependency set."""
import io
import socket
import threading
import pytest
from core import deployer

paramiko = pytest.importorskip("paramiko", reason="Optional SSH environment is required")


def ed25519_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    raw = Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    return paramiko.Ed25519Key.from_private_key(io.StringIO(raw.decode()))


@pytest.fixture
def ssh_server(monkeypatch):
    host_key, client_key = ed25519_key(), ed25519_key()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(3)
    stop = threading.Event()
    negotiated = threading.Event()
    errors = []
    transports = []

    class Server(paramiko.ServerInterface):
        def get_allowed_auths(self, username):
            return "password,publickey"

        def check_auth_password(self, username, password):
            return paramiko.AUTH_SUCCESSFUL if (username, password) == ("fixture", "synthetic-secret") else paramiko.AUTH_FAILED

        def check_auth_publickey(self, username, key):
            return paramiko.AUTH_SUCCESSFUL if username == "fixture" and key == client_key else paramiko.AUTH_FAILED

    def serve():
        try:
            connection, _ = listener.accept()
            transport = paramiko.Transport(connection)
            transports.append(transport)
            transport.add_server_key(host_key)
            transport.start_server(server=Server())
            negotiated.set()
            stop.wait(3)
        except (OSError, EOFError, paramiko.SSHException) as exc:
            if not stop.is_set():
                errors.append(exc)
        finally:
            for transport in transports:
                transport.close()

    original_close = paramiko.SSHClient.close

    def close_after_server_negotiation(client):
        # Host-key rejection can close the client before start_server returns.
        # Keep that expected rejection from racing the server's handshake check.
        try:
            assert negotiated.wait(3), "Loopback server did not complete SSH negotiation"
        finally:
            original_close(client)

    monkeypatch.setattr(paramiko.SSHClient, "close", close_after_server_negotiation)
    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    yield listener.getsockname()[1], host_key, client_key
    stop.set()
    listener.close()
    for transport in transports:
        transport.close()
    worker.join(4)
    assert not worker.is_alive()
    assert not errors


@pytest.mark.parametrize("authentication", ["password", "publickey", "wrong_password", "changed_host_key"])
def test_pinned_ssh_authentication_and_host_trust(monkeypatch, tmp_path, ssh_server, authentication):
    port, host_key, client_key = ssh_server
    known_hosts = tmp_path / "known_hosts"
    keys = paramiko.HostKeys()
    keys.add(f"[127.0.0.1]:{port}", host_key.get_name(), ed25519_key() if authentication == "changed_host_key" else host_key)
    keys.save(str(known_hosts))
    known_hosts.write_bytes(known_hosts.read_bytes().replace(b"\r\n", b"\n"))
    original = known_hosts.read_bytes()
    monkeypatch.setattr(deployer, "get_known_hosts_path", lambda: str(known_hosts))
    monkeypatch.setattr(paramiko.SSHClient, "load_system_host_keys", lambda _self: None)
    options = dict(port=port, username="fixture", allow_agent=False, look_for_keys=False, timeout=2, banner_timeout=2, auth_timeout=2)
    options.update(pkey=client_key) if authentication == "publickey" else options.update(password="invalid" if authentication == "wrong_password" else "synthetic-secret")
    if authentication in ("wrong_password", "changed_host_key"):
        exception = paramiko.AuthenticationException if authentication == "wrong_password" else paramiko.BadHostKeyException
        with pytest.raises(exception):
            deployer._connect_ssh_client(paramiko, "127.0.0.1", **options)
    else:
        client = deployer._connect_ssh_client(paramiko, "127.0.0.1", **options)
        try:
            assert client.get_transport().is_authenticated()
            assert client.get_transport().get_remote_server_key() == host_key
        finally:
            client.close()
    assert known_hosts.read_bytes() == original
