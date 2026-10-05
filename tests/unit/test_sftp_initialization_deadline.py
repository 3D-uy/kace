"""Exercise Paramiko's real subsystem wait without a network or printer."""
import threading
import struct
from unittest.mock import Mock
import pytest
from core import deployer

paramiko = pytest.importorskip("paramiko", reason="Optional SSH environment is required")


@pytest.mark.parametrize("phase", ["subsystem", "version", "read"])
def test_stalled_sftp_cannot_block_deployment(monkeypatch, phase):
    channel = paramiko.Channel(7)
    transport = Mock()
    transport.is_active.return_value = True
    transport.get_exception.return_value = None
    transport.get_log_channel.return_value = "test.sftp"
    transport.get_hexdump.return_value = False
    transport._sanitize_packet_size.side_effect = lambda size: size
    channel._set_transport(transport)
    channel._set_remote_channel(8, 1024 * 1024, 32768)
    if phase != "subsystem":
        monkeypatch.setattr(channel, "invoke_subsystem", lambda _name: None)
    if phase == "read":
        channel.in_buffer.feed(struct.pack(">IBI", 5, 2, 3))  # SFTP v3 server greeting.
    transport.open_session.return_value = channel
    ssh = Mock()
    ssh.get_transport.return_value = transport
    ssh.open_sftp.side_effect = lambda: paramiko.SFTPClient.from_transport(transport)
    ssh.close.side_effect = channel.close
    monkeypatch.setattr(deployer, "SFTP_TIMEOUT_SECONDS", 0.03, raising=False)
    monkeypatch.setattr(deployer, "_require_paramiko", lambda: paramiko)
    monkeypatch.setattr(deployer, "_connect_ssh_client", lambda *_a, **_k: ssh)
    monkeypatch.setattr(deployer, "_generated_config_bytes", lambda: ("generated.cfg", b"synthetic", None))
    published = []
    def transact(transport, *_args, **_kwargs):
        if phase == "read":
            transport.sftp.stat("fixture.cfg")  # No reply: real Channel.recv deadline.
        published.append(True)
    monkeypatch.setattr(deployer, "_run_config_transaction", transact)
    results = []
    worker = threading.Thread(target=lambda: results.append(deployer.deploy_config({"host":"fixture-printer.invalid","user":"kace","password":"synthetic","dest_path":"~/printer_data/config/printer.cfg"})), daemon=True)
    worker.start()
    worker.join(0.5)
    completed_in_time = not worker.is_alive()
    channel.close()  # External test deadline also wakes the unbounded old implementation.
    worker.join(2)
    assert completed_in_time
    assert published == []
    assert results and not results[0].ok
    ssh.close.assert_called_once()
