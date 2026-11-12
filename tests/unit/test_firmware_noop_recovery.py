"""No rollback activation when firmware config writes were never attempted."""
import pytest

from core.moonraker_deployer import ConfigArtifact, Deployer, DeploymentManifest, McuTarget
from core.snapshot import DeploymentSnapshot
from tests.unit.test_moonraker_deployer import Client


class ConditionalClient(Client):
    def __init__(self, fail_prewrite=False):
        super().__init__({})
        self.fail_prewrite = fail_prewrite
        self.remote = {"printer.cfg": b"[printer]\nkinematics: corexy\n"}

    def read_config_files(self, names):
        if self.fail_prewrite and names:
            raise OSError("simulated prewrite read failed")
        return super().read_config_files(names)

    def restore_snapshot(self, snapshot, *, expected_files=None):
        assert expected_files == {}
        self.calls.append("rollback")
        return []


def make_snapshot():
    return DeploymentSnapshot("id", "now", "board", "version", "", ("mcu",), False,
                              {"printer.cfg": b"[printer]\nold: true\n"})


def make_deployer(client, manifest, snap, verify=None):
    deployer = Deployer(client, manifest, snapshot=snap, verify_firmware=False,
                        verify_active_configuration=lambda: None, verify_config_state=verify,
                        event_sink=lambda _event: None)
    deployer.POLL_INTERVAL_S = 0.001
    deployer.POLL_BACKOFF_MAX_S = 0.002
    return deployer


@pytest.mark.parametrize("with_snapshot", [False, True])
def test_noop_verification_failure_does_not_restart_or_claim_rollback(with_snapshot):
    client = ConditionalClient()
    external = dict(client.remote)
    manifest = DeploymentManifest([McuTarget("mcu", "kace-good")], "unused", config_artifacts=[])
    def conflict():
        raise RuntimeError("concurrent include changed")
    result = make_deployer(client, manifest, make_snapshot() if with_snapshot else None, conflict).run()
    assert result.rollback_succeeded is None
    assert "no configuration files were written" in result.detail
    assert "restart" not in client.calls
    assert "rollback" not in client.calls
    assert client.remote == external


def test_prewrite_read_failure_does_not_restore_or_restart(tmp_path):
    client = ConditionalClient(fail_prewrite=True)
    external = dict(client.remote)
    path = tmp_path / "proposal.cfg"
    path.write_bytes(b"[printer]\nkinematics: cartesian\n")
    manifest = DeploymentManifest([McuTarget("mcu", "kace-good")], str(path),
                                  config_artifacts=[ConfigArtifact(str(path), "printer.cfg", path.read_bytes())])
    result = make_deployer(client, manifest, make_snapshot()).run()
    assert result.rollback_succeeded is None
    assert "no configuration files were written" in result.detail
    assert not any(isinstance(call, tuple) and call[0] == "upload" for call in client.calls)
    assert "restart" not in client.calls
    assert "rollback" not in client.calls
    assert client.remote == external
