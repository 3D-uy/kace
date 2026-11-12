"""Normal-mode errors retain a concise observed cause without common secrets."""
import pytest

from core.outcome_renderer import render_workflow_result
from core.translations import get_lang, get_mode, set_lang, set_mode
from core.workflow_outcome import failed, WorkflowOutcome


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("mode", ["Beginner", "Advanced"])
def test_failure_cause_is_visible_and_credentials_are_filtered(language, mode):
    previous = get_lang(), get_mode()
    try:
        set_lang(language)
        set_mode(mode)
        detail = ("activation error: state=error (Unknown pin); "
                  "https://alice:secret@pi.local/?api_key=key123&password='secret phrase'; "
                  "Authorization: Bearer token123\n\x1b[31m")
        result = failed(WorkflowOutcome.DEPLOYMENT_FAILED, detail)
        text = render_workflow_result(result, color=False)
        assert "state=error (Unknown pin)" in text
        assert not any(secret in text for secret in ("alice", "secret", "key123", "token123", "\x1b"))
        assert "KACE_RESULT" not in text
        assert result.detail == detail and result.exit_code == 40
    finally:
        set_lang(previous[0])
        set_mode(previous[1])
