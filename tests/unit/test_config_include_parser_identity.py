"""Include discovery must address exactly the file parsed by pinned Klipper."""
import importlib.util
from pathlib import Path

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState, read_config_state
from core.managed_config import config_includes
from tests.unit.test_config_transaction import FakeTransport, GENERATED


def pinned_reader():
    source = Path(__file__).resolve().parents[2] / ".klipper-contract-source/klippy/configfile.py"
    if not source.is_file():
        pytest.skip("Pinned Klipper parser unavailable")
    spec = importlib.util.spec_from_file_location("pinned_include_identity", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ConfigFileReader()


@pytest.mark.parametrize("line,name", [
    ("[include user.cfg]", "user.cfg"),
    ("[include user.cfg]suffix]", "user.cfg]suffix"),
    ("[include dir/user.cfg]tail] # comment", "dir/user.cfg]tail"),
])
def test_discovery_matches_pinned_parser(tmp_path, line, name):
    actual = tmp_path / name
    actual.parent.mkdir(parents=True, exist_ok=True)
    actual.write_text("[gcode_macro TEST]\ngcode: M105\n", encoding="utf-8")
    parser = pinned_reader()
    parsed = parser.build_fileconfig_with_includes(line + "\n", str(tmp_path / "printer.cfg"))
    assert parsed.has_section("gcode_macro TEST")
    assert list(config_includes((line + "\n").encode(), "printer.cfg"))[0][1] == name


def test_read_state_discovers_the_file_klipper_reads():
    transport = FakeTransport({"printer.cfg": b"[include user.cfg]suffix]\n",
                               "user.cfg": b"# unrelated\n",
                               "user.cfg]suffix": b"# actual include\n"})
    state = read_config_state(transport, GENERATED)
    assert state["user.cfg]suffix"] == b"# actual include\n"
    assert "user.cfg" not in state


def test_changed_actual_include_prevents_writes(tmp_path, monkeypatch):
    # This test isolates include revalidation with a deliberately incomplete
    # fixture; actual Klipper preflight coverage is exercised separately.
    from core import klipper_preflight
    monkeypatch.setattr(klipper_preflight, "validate_plan", lambda plan:
        klipper_preflight.PreflightResult("valid", "test", klipper_preflight.plan_digest(plan)))
    transport = FakeTransport({"printer.cfg": b"[include user.cfg]suffix]\n",
                               "user.cfg": b"# unrelated\n",
                               "user.cfg]suffix": b"# actual include\n"})

    def confirm(_diff):
        transport.files["user.cfg]suffix"] = b"# changed after review\n"
        return True

    result = ConfigDeploymentTransaction(
        transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snap"),
    ).run()
    assert result.state is ConfigTransactionState.PRECONDITION_FAILED
    assert "user.cfg]suffix" in result.detail
    assert not any(call[0] == "upload" for call in transport.calls)
