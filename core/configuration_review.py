"""Structured semantic review and terminal rendering for configuration plans."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable

from core.managed_config import HARDWARE_REMOTE, MACROS_REMOTE, ManagedConfigPlan
from core.profile_values import infer_homing_positive_dir


@dataclass(frozen=True)
class ReviewMessage:
    code: str
    message: str


@dataclass(frozen=True)
class SemanticValidation:
    errors: tuple[ReviewMessage, ...] = ()
    warnings: tuple[ReviewMessage, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class SummaryItem:
    status: str
    text: str


@dataclass(frozen=True)
class ConfigurationReview:
    validation: SemanticValidation
    summary: tuple[SummaryItem, ...]
    changed_files: tuple[str, ...]
    important_changes: tuple[str, ...]
    diff: str


_SECTION_RE = re.compile(r"(?m)^\s*\[([^\]\r\n]+)\]\s*(?:[#;].*)?$")
_OPTION_RE = re.compile(r"^\s*([^:=#;]+?)\s*[:=]\s*(.*?)\s*(?:[#;].*)?$")


def _sections(text: str) -> dict[str, dict[str, str]]:
    matches = list(_SECTION_RE.finditer(text))
    result: dict[str, dict[str, str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        options: dict[str, str] = {}
        for line in body.splitlines():
            option = _OPTION_RE.match(line)
            if option:
                options[option.group(1).strip().casefold()] = option.group(2).strip()
        result[match.group(1).strip().casefold()] = options
    return result


def _artifact_text(plan: ManagedConfigPlan, name: str) -> str:
    for artifact in plan.artifacts:
        if artifact.remote_name == name:
            return artifact.content.decode("utf-8", errors="replace")
    return ""


def _header_value(text: str, label: str) -> str:
    match = re.search(rf"(?mi)^#\s*{re.escape(label)}:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def validate_configuration_plan(plan: ManagedConfigPlan) -> SemanticValidation:
    hardware = _artifact_text(plan, HARDWARE_REMOTE)
    macros = _artifact_text(plan, MACROS_REMOTE)
    sections = _sections(hardware)
    errors: list[ReviewMessage] = []
    warnings: list[ReviewMessage] = [
        ReviewMessage("managed-plan", warning) for warning in plan.warnings
    ]

    probe_sections = any(
        name == "bltouch" or name == "probe" or name.startswith("probe ")
        for name in sections
    )
    z_options = sections.get("stepper_z", {})
    virtual_z = z_options.get("endstop_pin", "").casefold() == "probe:z_virtual_endstop"
    if probe_sections != virtual_z:
        errors.append(ReviewMessage(
            "probe-z-endstop",
            "Probe selection and the Z endstop disagree: a probe must use probe:z_virtual_endstop, while a physical Z endstop must not.",
        ))
    if not virtual_z and "stepper_z" in sections and "position_endstop" not in z_options:
        errors.append(ReviewMessage(
            "physical-z-position",
            "Physical Z homing requires position_endstop in [stepper_z].",
        ))

    for axis in ("x", "y", "z"):
        if axis == "z" and virtual_z:
            continue
        options = sections.get(f"stepper_{axis}")
        if not options:
            continue
        geometry_keys = {"position_endstop", "position_min", "position_max"}
        if not (geometry_keys & set(options)):
            # Small integration fixtures and externally managed fragments may
            # contain only pins.  Validate homing only when this plan owns any
            # of the geometry needed to reason about it.
            continue
        if not geometry_keys <= set(options):
            errors.append(ReviewMessage(
                f"homing-{axis}-geometry",
                f"Homing geometry for {axis.upper()} is incomplete; position_min, position_max and position_endstop are required together.",
            ))
            continue
        inferred = infer_homing_positive_dir(
            options.get("position_endstop"),
            options.get("position_min"),
            options.get("position_max"),
        )
        explicit = options.get("homing_positive_dir")
        if explicit is None and inferred is None:
            errors.append(ReviewMessage(
                f"homing-{axis}-ambiguous",
                f"Homing direction for {axis.upper()} is ambiguous; confirm whether it homes toward position_min or position_max in the wizard.",
            ))
        elif explicit is None and inferred is not None:
            warnings.append(ReviewMessage(
                f"homing-{axis}-inferred",
                f"Homing direction for {axis.upper()} will be inferred safely from its endstop position and travel limits; verify it during the first endstop test.",
            ))
        elif explicit is not None and inferred is not None and explicit.casefold() != inferred.casefold():
            errors.append(ReviewMessage(
                f"homing-{axis}-contradiction",
                f"Homing direction for {axis.upper()} contradicts its endstop location and travel limits.",
            ))

    for section_name, macro_name in (("extruder", "PID_HOTEND"), ("heater_bed", "PID_BED")):
        options = sections.get(section_name, {})
        if not options:
            continue
        control = options.get("control", "pid").casefold()
        pid_options = {"pid_kp", "pid_ki", "pid_kd"} & set(options)
        if control == "watermark" and pid_options:
            errors.append(ReviewMessage(
                f"{section_name}-watermark-pid",
                f"[{section_name}] uses watermark control but still contains PID parameters.",
            ))
        if control != "pid" and f"[gcode_macro {macro_name}]".casefold() in macros.casefold():
            errors.append(ReviewMessage(
                f"{section_name}-pid-macro",
                f"Macro {macro_name} is incompatible with [{section_name}] control: {control}.",
            ))

    has_probe_calibration = "PROBE_CALIBRATE" in hardware
    has_endstop_calibration = "Z_ENDSTOP_CALIBRATE" in hardware
    if virtual_z and not has_probe_calibration:
        errors.append(ReviewMessage("probe-calibration-missing", "A configured probe requires a PROBE_CALIBRATE step."))
    if not virtual_z and has_probe_calibration:
        errors.append(ReviewMessage("probe-calibration-extra", "PROBE_CALIBRATE must not be shown when Z uses a physical endstop."))
    if not virtual_z and "stepper_z" in sections and not has_endstop_calibration:
        errors.append(ReviewMessage("endstop-calibration-missing", "Physical Z homing requires Z_ENDSTOP_CALIBRATE guidance."))

    if re.search(r"(?mi)^\s*[^#;\r\n]+[:=]\s*UNRESOLVED\s*$", hardware):
        errors.append(ReviewMessage("active-unresolved", "The generated configuration contains an active UNRESOLVED value."))

    if "=INFERRED" in hardware:
        warnings.append(ReviewMessage(
            "inferred-homing",
            "One or more homing directions were inferred from endstop position and travel limits; verify them during the first endstop test.",
        ))
    return SemanticValidation(tuple(errors), tuple(warnings))


def build_configuration_review(plan: ManagedConfigPlan) -> ConfigurationReview:
    hardware = _artifact_text(plan, HARDWARE_REMOTE)
    sections = _sections(hardware)
    validation = validate_configuration_plan(plan)
    board = _header_value(hardware, "Board") or "configured board"
    kinematics = sections.get("printer", {}).get("kinematics", "unknown")
    drivers = _header_value(hardware, "Stepper Drivers") or "configured"
    z_drivers = _header_value(hardware, "Z Drivers") or "1"
    serial = sections.get("mcu", {}).get("serial")
    summary = [
        SummaryItem("ok", f"MCU/board: {board}"),
        SummaryItem("ok" if serial else "error", "MCU connection configured" if serial else "MCU connection missing"),
        SummaryItem("ok", f"Kinematics: {kinematics}"),
        SummaryItem("ok", f"Z motors/drivers: {z_drivers}"),
        SummaryItem("ok", f"Stepper drivers: {drivers}"),
        SummaryItem("ok" if "extruder" in sections else "error", "Hotend configured"),
        SummaryItem("ok" if "heater_bed" in sections else "warning", "Heated bed configured"),
        SummaryItem("ok" if "exclude_object" in sections else "warning", "Exclude Object enabled"),
    ]
    calibration = ["extruder rotation_distance"]
    if sections.get("extruder", {}).get("control", "pid").casefold() == "pid":
        calibration.append("hotend PID")
    if sections.get("heater_bed", {}).get("control", "pid").casefold() == "pid":
        calibration.append("heated-bed PID")
    calibration.append("probe Z offset" if "probe:z_virtual_endstop" in hardware else "physical Z endstop")
    summary.append(SummaryItem("info", "Calibration after installation: " + ", ".join(calibration)))
    changed = tuple(item.remote_name for item in plan.changed_artifacts)
    changes: list[str] = []
    if "printer.cfg" in changed:
        changes.append("printer.cfg will load the files managed by KACE while preserving unmanaged sections.")
    if HARDWARE_REMOTE in changed:
        changes.append("KACE will publish the generated hardware configuration.")
    if MACROS_REMOTE in changed:
        changes.append("KACE will publish starter macros compatible with the selected hardware.")
    return ConfigurationReview(validation, tuple(summary), changed, tuple(changes), plan.dry_run_diff())


_TEXT = {
    "English": {
        "title": "Configuration summary", "files": "Files to be modified",
        "changes": "Important changes", "warnings": "Warnings", "errors": "Blocking errors",
        "validation_ok": "Semantic validation passed", "validation_bad": "Semantic validation failed",
        "footer": "{files} file(s) will change | {warnings} warning(s) | {validation}",
    },
    "Español": {
        "title": "Resumen de configuración", "files": "Archivos que se modificarán",
        "changes": "Cambios importantes", "warnings": "Advertencias", "errors": "Errores que bloquean la aplicación",
        "validation_ok": "Validación semántica correcta", "validation_bad": "La validación semántica falló",
        "footer": "{files} archivo(s) se modificarán | {warnings} advertencia(s) | {validation}",
    },
    "Português": {
        "title": "Resumo da configuração", "files": "Arquivos que serão modificados",
        "changes": "Alterações importantes", "warnings": "Avisos", "errors": "Erros que bloqueiam a aplicação",
        "validation_ok": "Validação semântica aprovada", "validation_bad": "A validação semântica falhou",
        "footer": "{files} arquivo(s) serão alterados | {warnings} aviso(s) | {validation}",
    },
}


def terminal_supports_color(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM", "").casefold() == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def render_configuration_review(
    review: ConfigurationReview, *, language: str = "English", color: bool | None = None
) -> str:
    labels = _TEXT.get(language, _TEXT["English"])
    if color is None:
        color = terminal_supports_color()
    colors = {"ok": "\033[92m", "warning": "\033[93m", "error": "\033[91m", "info": "\033[96m"}
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "✅⚠✖ℹ".encode(encoding)
        icons = {"ok": "✅", "warning": "⚠", "error": "✖", "info": "ℹ"}
    except (LookupError, UnicodeEncodeError):
        icons = {"ok": "[OK]", "warning": "[!]", "error": "[X]", "info": "[i]"}
    reset = "\033[0m" if color else ""

    def paint(status: str, text: str) -> str:
        prefix = colors.get(status, "") if color else ""
        return f"{prefix}{icons.get(status, '•')} {text}{reset}"

    def localize(text: str) -> str:
        if language == "English":
            return text
        exact = {
            "Español": {
                "MCU connection configured": "Conexión MCU configurada",
                "MCU connection missing": "Falta la conexión MCU",
                "Hotend configured": "Hotend configurado",
                "Heated bed configured": "Cama caliente configurada",
                "Exclude Object enabled": "Exclude Object habilitado",
                "printer.cfg will load the files managed by KACE while preserving unmanaged sections.": "printer.cfg cargará los archivos gestionados por KACE y preservará las secciones no gestionadas.",
                "KACE will publish the generated hardware configuration.": "KACE publicará la configuración de hardware generada.",
                "KACE will publish starter macros compatible with the selected hardware.": "KACE publicará macros iniciales compatibles con el hardware seleccionado.",
            },
            "Português": {
                "MCU connection configured": "Conexão da MCU configurada",
                "MCU connection missing": "Conexão da MCU ausente",
                "Hotend configured": "Hotend configurado",
                "Heated bed configured": "Mesa aquecida configurada",
                "Exclude Object enabled": "Exclude Object habilitado",
                "printer.cfg will load the files managed by KACE while preserving unmanaged sections.": "printer.cfg carregará os arquivos gerenciados pelo KACE e preservará as seções não gerenciadas.",
                "KACE will publish the generated hardware configuration.": "O KACE publicará a configuração de hardware gerada.",
                "KACE will publish starter macros compatible with the selected hardware.": "O KACE publicará macros iniciais compatíveis com o hardware selecionado.",
            },
        }.get(language, {})
        if text in exact:
            return exact[text]
        prefixes = {
            "Español": {
                "MCU/board: ": "MCU/placa: ", "Kinematics: ": "Cinemática: ",
                "Z motors/drivers: ": "Motores/drivers Z: ", "Stepper drivers: ": "Drivers de motores: ",
                "Calibration after installation: ": "Calibración tras la instalación: ",
            },
            "Português": {
                "MCU/board: ": "MCU/placa: ", "Kinematics: ": "Cinemática: ",
                "Z motors/drivers: ": "Motores/drivers Z: ", "Stepper drivers: ": "Drivers dos motores: ",
                "Calibration after installation: ": "Calibração após a instalação: ",
            },
        }.get(language, {})
        for source, target in prefixes.items():
            if text.startswith(source):
                return target + text[len(source):]
        return text

    lines = [paint("info", labels["title"]), ""]
    lines.extend(f"  {paint(item.status, localize(item.text))}" for item in review.summary)
    lines.extend(["", paint("info", labels["files"])])
    if review.changed_files:
        lines.extend(f"  - {name}" for name in review.changed_files)
    else:
        lines.append("  - (none)")
    lines.extend(["", paint("info", labels["changes"])])
    if review.important_changes:
        lines.extend(f"  - {localize(change)}" for change in review.important_changes)
    else:
        lines.append("  - (none)")
    if review.validation.warnings:
        lines.extend(["", paint("warning", labels["warnings"])])
        lines.extend(f"  - {item.message}" for item in review.validation.warnings)
    if review.validation.errors:
        lines.extend(["", paint("error", labels["errors"])])
        lines.extend(f"  - {item.message}" for item in review.validation.errors)
    validation = labels["validation_ok"] if review.validation.valid else labels["validation_bad"]
    lines.extend(["", labels["footer"].format(
        files=len(review.changed_files), warnings=len(review.validation.warnings), validation=validation
    )])
    return "\n".join(lines)
