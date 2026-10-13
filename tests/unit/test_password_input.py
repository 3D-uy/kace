"""Secret input must never downgrade to getpass's echoing fallback."""
import getpass
import io
import warnings
from unittest.mock import patch

import pytest

from core.exceptions import WizardExit
from core.menu import password_input
from core.deployer import deploy_moonraker
from core.translations import t
from core.workflow_outcome import WorkflowOutcome


@pytest.fixture(autouse=True)
def real_prompt_helpers():
    with patch("core.menu._MOCK_PROMPTS_ACTIVE", False), patch("core.menu._is_auto", return_value=False):
        yield


@pytest.mark.parametrize("value", ["", "  synthetic-secret  "])
def test_hidden_input_preserves_empty_and_exact_values_without_output(value, capsys):
    with patch("core.menu.getpass.getpass", return_value=value) as hidden, \
            patch("builtins.input") as visible:
        assert password_input("API key: ") == value
    hidden.assert_called_once_with(prompt="  API key: ")
    visible.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("error", [KeyboardInterrupt, EOFError])
def test_interrupted_hidden_input_cancels_before_network(error, capsys):
    with patch("core.menu.simple_input", side_effect=["https://pi.local", "7125"]), \
            patch("core.config_transaction.local_moonraker_available", return_value=False), \
            patch("core.menu.getpass.getpass", side_effect=error), \
            patch("core.moonraker.check_moonraker") as check, \
            patch("core.config_transaction.configuration_transport") as transport, \
            patch("core.deployer._run_config_transaction") as deploy:
        result = deploy_moonraker({})
    assert result.outcome is WorkflowOutcome.CANCELLED
    check.assert_not_called()
    transport.assert_not_called()
    deploy.assert_not_called()
    assert capsys.readouterr().err == ""


def test_getpass_fallback_aborts_before_reading_visible_secret(capsys):
    # Execute the standard library fallback itself; the warning occurs before
    # its visible stdin read. This exercises Windows redirected stdin and POSIX
    # terminal-control failure without requiring a physical terminal in CI.
    with patch("core.menu.getpass.getpass", side_effect=getpass.fallback_getpass), \
            patch("getpass._raw_input", return_value="must-not-be-read") as visible, \
            patch("sys.stdin", io.StringIO("must-not-be-read\n")):
        with pytest.raises(WizardExit):
            password_input("API key")
    visible.assert_not_called()
    output = capsys.readouterr()
    assert "must-not-be-read" not in output.out + output.err
    assert t("menu.secret_input_unavailable") in output.out


def test_insecure_prompt_failure_stops_before_network(capsys):
    with patch("core.menu.simple_input", side_effect=["https://pi.local", "7125"]), \
            patch("core.config_transaction.local_moonraker_available", return_value=False), \
            patch("core.menu.getpass.getpass", side_effect=getpass.fallback_getpass), \
            patch("getpass._raw_input") as visible, \
            patch("core.moonraker.check_moonraker") as check, \
            patch("core.config_transaction.configuration_transport") as transport:
        result = deploy_moonraker({})
    assert result.outcome is WorkflowOutcome.CANCELLED
    visible.assert_not_called()
    check.assert_not_called()
    transport.assert_not_called()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_terminal_failure_is_localized_and_does_not_print_exception_details(language, capsys, caplog):
    with patch("core.translations._state._current_lang", language), \
            patch("core.menu.getpass.getpass", side_effect=OSError("synthetic-private-data")):
        with pytest.raises(WizardExit) as cancelled:
            password_input("API key")
        output = capsys.readouterr()
        assert t("menu.secret_input_unavailable") in output.out
        assert "menu.secret_input_unavailable" not in output.out
    assert "synthetic-private-data" not in output.out + output.err + caplog.text + str(cancelled.value)
    assert cancelled.value.__suppress_context__


def test_ignored_warnings_cannot_enable_visible_fallback_and_filter_is_restored():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", getpass.GetPassWarning)
        filters_before = list(warnings.filters)
        with patch("core.menu.getpass.getpass", side_effect=getpass.fallback_getpass), \
                patch("getpass._raw_input") as visible:
            with pytest.raises(WizardExit):
                password_input("API key")
        visible.assert_not_called()
        assert warnings.filters == filters_before


def test_auto_mode_keeps_anonymous_input_without_requesting_a_secret():
    with patch("core.menu._is_auto", return_value=True), patch("core.menu.getpass.getpass") as hidden:
        assert password_input("API key") == ""
    hidden.assert_not_called()
