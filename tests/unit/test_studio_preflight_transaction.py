"""Studio remote validation keeps KACE's write gate and plan identity checks."""
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import klipper_preflight as preflight
from core import studio_preflight as client
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_studio_preflight import Connection, response


@pytest.fixture(autouse=True)
def studio_without_pi_docker(monkeypatch):
    monkeypatch.setenv(client.PORT_ENV, "32123")
    monkeypatch.setenv(client.TOKEN_ENV, "e" * 64)
    monkeypatch.setenv(client.SESSION_ENV, "f" * 32)
    monkeypatch.setattr(preflight, "_run", lambda *_a, **_k: pytest.fail("Pi must not invoke Docker"))
    monkeypatch.setattr(preflight.engine, "validate_files", lambda *_a, **_k: pytest.fail("Pi Docker fallback forbidden"))
    monkeypatch.setattr(preflight.shutil, "which", lambda *_a: pytest.fail("Pi must not discover Docker"))


def wire(monkeypatch, **changes):
    connection = Connection(lambda request: response(request, **changes))
    monkeypatch.setattr(client.socket, "create_connection", lambda *_a, **_k: connection)
    return connection


def transaction(tmp_path, review=None):
    transport = FakeTransport({"printer.cfg": b"# original\n"})
    flow = ConfigDeploymentTransaction(
        transport, GENERATED, None, activation="none", snapshot_root=str(tmp_path),
        review=review,
    )
    return flow, transport


@pytest.mark.parametrize("changes", [{"status": "invalid"}, {"status": "unverified"},
                                    {"request_id": "0" * 32}, {"tree_digest": "0" * 64},
                                    {"session": "0" * 32}, {"pin": "0" * 40}])
def test_remote_rejection_or_stale_receipt_precedes_review_and_writes(tmp_path, monkeypatch, changes):
    wire(monkeypatch, **changes)
    review = Mock(return_value=True)
    flow, transport = transaction(tmp_path, review)
    before = dict(transport.files)
    result = flow.run()
    assert result.state is ConfigTransactionState.PRECONDITION_FAILED, result.detail
    review.assert_not_called()
    assert not any(call[0] in {"upload", "delete", "restart", "restart_moonraker"} for call in transport.calls)
    assert transport.files == before
    assert result.snapshot is None


def test_remote_disconnect_blocks_publication_without_fallback(tmp_path, monkeypatch):
    def disconnected(*_a, **_k):
        raise ConnectionResetError("SSH session lost")
    monkeypatch.setattr(client.socket, "create_connection", disconnected)
    review = Mock(return_value=True)
    flow, transport = transaction(tmp_path, review)
    result = flow.run()
    assert result.state is ConfigTransactionState.PRECONDITION_FAILED
    review.assert_not_called()
    assert not any(call[0] == "upload" for call in transport.calls)


def test_partial_bridge_environment_cannot_fall_back_to_pi_docker(tmp_path, monkeypatch):
    monkeypatch.delenv(client.TOKEN_ENV)
    monkeypatch.setattr(client.socket, "create_connection", lambda *_a, **_k: pytest.fail("partial session must not connect"))
    flow, transport = transaction(tmp_path, Mock(return_value=True))
    result = flow.run()
    assert result.state is ConfigTransactionState.PRECONDITION_FAILED
    assert not any(call[0] == "upload" for call in transport.calls)


def test_remote_success_keeps_exact_identity_and_normal_publication(tmp_path, monkeypatch):
    connection = wire(monkeypatch)
    flow, transport = transaction(tmp_path, Mock(return_value=True))
    result = flow.run()
    assert result.state is ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, result.detail
    assert any(call[0] == "upload" for call in transport.calls)
    assert connection.request["tree_digest"] == preflight.plan_digest(flow.plan)
    assert {key: connection.request[key] for key in client.IDENTITY_FIELDS} == preflight._studio_identity()


def test_review_cannot_replace_plan_after_remote_validation(tmp_path, monkeypatch):
    wire(monkeypatch)
    flow, transport = transaction(tmp_path)
    before = dict(transport.files)

    def change_after_validation(_review):
        artifact = flow.plan.artifacts[0]
        flow.plan = replace(flow.plan, artifacts=(
            replace(artifact, content=artifact.content + b"# altered after Studio validation\n"),
            *flow.plan.artifacts[1:],
        ))
        return True

    flow.review = change_after_validation
    result = flow.run()
    assert result.state is ConfigTransactionState.PRECONDITION_FAILED
    assert "changed after Klipper preflight" in result.detail
    assert not any(call[0] == "upload" for call in transport.calls)
    assert transport.files == before


def test_identity_canonicalizes_resource_line_endings_only(tmp_path, monkeypatch):
    expected = {}
    for attribute, key in (("_ENGINE", "engine_sha256"), ("_WORKER", "worker_sha256"),
                           ("_DOCKERFILE", "dockerfile_sha256")):
        resource = tmp_path / attribute
        resource.write_bytes(b"first\r\nsecond\r\n")
        monkeypatch.setattr(preflight, attribute, resource)
        expected[key] = sha256(b"first\nsecond\n").hexdigest()
    assert preflight._studio_identity() == {"pin": preflight.PIN, **expected}


def test_configured_pin_mismatch_cannot_be_sent_to_studio(monkeypatch):
    monkeypatch.setattr(preflight, "load_klipper_source_contract", lambda: SimpleNamespace(validated_commit="0" * 40))
    monkeypatch.setattr(client.socket, "create_connection", lambda *_a, **_k: pytest.fail("pin mismatch must not connect"))
    result = preflight.validate_plan(SimpleNamespace(source_files=(("printer.cfg", b"# config\n"),), artifacts=()))
    assert result.status == "unverified"
    assert "pin" in result.detail
