"""Human-facing rendering for typed KACE workflow outcomes.

Machine protocols remain owned by :mod:`core.workflow_outcome`.  This module
deliberately contains only presentation policy so callers do not infer outcome
semantics from terminal text.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

from core.translations import get_lang
from core.workflow_outcome import WorkflowOutcome, WorkflowResult


_MESSAGES = {
    WorkflowOutcome.CANCELLED: {
        "English": (
            "Installation cancelled",
            "No configuration changes were applied.",
            "KACE finished safely.",
        ),
        "Español": (
            "Instalación cancelada",
            "No se aplicaron cambios en la configuración.",
            "KACE finalizó de forma segura.",
        ),
        "Português": (
            "Instalação cancelada",
            "Nenhuma alteração foi aplicada à configuração.",
            "O KACE foi encerrado com segurança.",
        ),
    },
    WorkflowOutcome.DEPLOYED_PENDING_ACTIVATION: {
        "English": (
            "Installation pending activation",
            "The prepared changes are safe, but still require the indicated action.",
            "Complete that action before using the new configuration.",
        ),
        "Español": (
            "Instalación pendiente de activación",
            "Los cambios preparados son seguros, pero aún requieren la acción indicada.",
            "Complete esa acción antes de usar la nueva configuración.",
        ),
        "Português": (
            "Instalação aguardando ativação",
            "As alterações preparadas são seguras, mas ainda exigem a ação indicada.",
            "Conclua essa ação antes de usar a nova configuração.",
        ),
    },
}

_FAILURE_TITLES = {
    "English": "Installation failed",
    "Español": "La instalación falló",
    "Português": "A instalação falhou",
}

_FAILURE_HINTS = {
    "English": "Correct the reported error and run KACE again.",
    "Español": "Corrija el error indicado y vuelva a ejecutar KACE.",
    "Português": "Corrija o erro indicado e execute o KACE novamente.",
}


def machine_output_enabled() -> bool:
    """Return whether the explicit diagnostic/machine channel was requested."""
    return (
        os.environ.get("KACE_MACHINE_OUTPUT") == "1"
        or os.environ.get("KACE_DEBUG") == "1"
    )


def _supports_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM", "").casefold() == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def render_workflow_result(
    result: WorkflowResult,
    *,
    stream: TextIO | None = None,
    color: bool | None = None,
) -> str:
    """Render normal non-success outcomes without exposing internal details."""
    messages = _MESSAGES.get(result.outcome)
    is_failure = result.outcome not in (
        WorkflowOutcome.SUCCESS,
        WorkflowOutcome.CANCELLED,
        WorkflowOutcome.DEPLOYED_PENDING_ACTIVATION,
    )
    if messages is None and not is_failure:
        return ""
    stream = stream or sys.stdout
    language = get_lang()
    if is_failure:
        title = _FAILURE_TITLES.get(language, _FAILURE_TITLES["English"])
        explanation = result.detail or title
        closing = _FAILURE_HINTS.get(language, _FAILURE_HINTS["English"])
        icon = "✖"
        ansi = "\033[91m"
    else:
        title, explanation, closing = messages.get(language, messages["English"])
        icon = "⚠"
        ansi = (
            "\033[93m"
            if result.outcome is WorkflowOutcome.CANCELLED
            else "\033[96m"
        )
    if color is None:
        color = _supports_color(stream)
    heading = f"{icon} {title}"
    if color:
        heading = f"{ansi}{heading}\033[0m"
    return f"\n{heading}\n\n{explanation}\n{closing}"


def print_workflow_result(result: WorkflowResult, *, stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    rendered = render_workflow_result(result, stream=stream)
    if rendered:
        print(rendered, file=stream, flush=True)
    if machine_output_enabled():
        print(result.marker(), file=stream, flush=True)
