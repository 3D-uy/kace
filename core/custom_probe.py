"""Parsing and typed representation for user-supplied Klipper probe blocks.

The parser intentionally keeps the original text intact.  KACE reads only the
primary probe section and its offsets so that geometry calculations can use
them; it does not turn custom macros or unknown probe options into a dict.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional


_SECTION_HEADER = re.compile(r"^\s*\[([^\[\]\r\n]+)\]\s*(?:#.*)?$")
@dataclass(frozen=True)
class CustomProbeSectionPolicy:
    """Declarative structural policy for a raw custom probe strategy.

    This is not a macro sandbox.  It controls which Klipper sections can share
    a custom probe block and prevents collisions with KACE-owned sections.
    """

    primary_sections: frozenset[str]
    companion_section_prefixes: frozenset[str]
    generated_section_names: frozenset[str]
    prohibited_section_prefixes: frozenset[str]


DEFAULT_SECTION_POLICY = CustomProbeSectionPolicy(
    primary_sections=frozenset({"probe", "dockable_probe"}),
    companion_section_prefixes=frozenset({"gcode_macro", "delayed_gcode"}),
    generated_section_names=frozenset({"safe_z_home", "bed_mesh"}),
    prohibited_section_prefixes=frozenset({
        "gcode_shell_command", "mcu", "printer", "stepper_", "tmc", "heater_",
        "temperature_sensor", "fan", "controller_fan", "output_pin", "pwm_tool",
        "servo", "extruder", "filament_switch_sensor",
    }),
)


class CustomProbeValidationError(ValueError):
    """Raised when a custom probe block is empty, malformed, or out of scope."""


GUIDED_PROBE_DEFAULTS = {
    "samples": 2,
    "samples_tolerance": 0.5,
    "samples_tolerance_retries": 3,
    "speed": 10.0,
    "samples_result": "median",
    "sample_retract_dist": 5.0,
}


@dataclass(frozen=True)
class GuidedCustomProbeSettings:
    """KACE-owned settings collected by the guided custom-probe wizard.

    The raw ``CustomProbeConfig`` remains the generator's custom strategy
    payload.  This intermediate typed model gives the wizard a safe, reusable
    contract for common probe questions; future strategies can extend the
    question flow without teaching the renderer about their UI.
    """

    pin: str
    x_offset: float
    y_offset: float
    z_offset: Optional[float] = None
    samples: int = GUIDED_PROBE_DEFAULTS["samples"]
    samples_tolerance: float = GUIDED_PROBE_DEFAULTS["samples_tolerance"]
    samples_tolerance_retries: int = GUIDED_PROBE_DEFAULTS["samples_tolerance_retries"]
    speed: float = GUIDED_PROBE_DEFAULTS["speed"]
    samples_result: str = GUIDED_PROBE_DEFAULTS["samples_result"]
    sample_retract_dist: float = GUIDED_PROBE_DEFAULTS["sample_retract_dist"]

    def __post_init__(self) -> None:
        if not isinstance(self.pin, str) or not self.pin.strip():
            raise CustomProbeValidationError("Probe pin is required.")
        _finite_number(self.x_offset, "x_offset")
        _finite_number(self.y_offset, "y_offset")
        if self.z_offset is not None:
            _finite_number(self.z_offset, "z_offset")
        if not isinstance(self.samples, int) or self.samples < 1:
            raise CustomProbeValidationError("samples must be a positive whole number.")
        if not isinstance(self.samples_tolerance_retries, int) or self.samples_tolerance_retries < 0:
            raise CustomProbeValidationError("samples_tolerance_retries must be zero or greater.")
        if _finite_number(self.samples_tolerance, "samples_tolerance") < 0:
            raise CustomProbeValidationError("samples_tolerance must be zero or greater.")
        if _finite_number(self.speed, "speed") <= 0:
            raise CustomProbeValidationError("speed must be greater than zero.")
        if _finite_number(self.sample_retract_dist, "sample_retract_dist") <= 0:
            raise CustomProbeValidationError("sample_retract_dist must be greater than zero.")
        if self.samples_result not in {"median", "average"}:
            raise CustomProbeValidationError("samples_result must be median or average.")

    def to_config(self) -> "CustomProbeConfig":
        """Render only guided values into the standard Klipper ``[probe]`` section."""
        lines = [
            "[probe]",
            f"pin: {self.pin.strip()}",
            f"x_offset: {self.x_offset:g}",
            f"y_offset: {self.y_offset:g}",
        ]
        lines.append(f"z_offset: {(self.z_offset if self.z_offset is not None else 0):g}")
        lines.extend([
            f"samples: {self.samples}",
            f"samples_tolerance: {self.samples_tolerance:g}",
            f"samples_tolerance_retries: {self.samples_tolerance_retries}",
            f"speed: {self.speed:g}",
            f"samples_result: {self.samples_result}",
            f"sample_retract_dist: {self.sample_retract_dist:g}",
        ])
        return parse_custom_probe_config("\n".join(lines))


@dataclass(frozen=True)
class CustomProbeConfig:
    """A validated custom probe block and the offsets resolved from it.

    ``config_text`` is deliberately a string rather than parsed key/value data:
    custom probe implementations commonly rely on comments, ordering, unknown
    options, and related macro bodies that KACE must not rewrite.
    """

    config_text: str
    primary_section: str
    x_offset: Optional[float] = None
    y_offset: Optional[float] = None
    z_offset: Optional[float] = None
    policy: CustomProbeSectionPolicy = DEFAULT_SECTION_POLICY

    @property
    def requires_offset_prompt(self) -> bool:
        """Whether X or Y must be supplied for KACE geometry calculations."""
        return self.x_offset is None or self.y_offset is None

    def with_missing_offsets(self, *, x_offset: Optional[str] = None,
                             y_offset: Optional[str] = None) -> "CustomProbeConfig":
        """Append only missing user-supplied X/Y offsets to the primary section.

        Existing options are never changed or duplicated.  Re-parsing the
        resulting text centralizes validation and provides the updated model.
        """
        additions = []
        if self.x_offset is None:
            additions.append(("x_offset", _numeric_text(x_offset, "x_offset")))
        if self.y_offset is None:
            additions.append(("y_offset", _numeric_text(y_offset, "y_offset")))
        if not additions:
            return self

        lines = self.config_text.splitlines()
        primary_index = next(
            index for index, line in enumerate(lines)
            if _section_name(line) == self.primary_section
        )
        insert_at = len(lines)
        for index in range(primary_index + 1, len(lines)):
            if _section_name(lines[index]) is not None:
                insert_at = index
                break
        lines[insert_at:insert_at] = [f"{key}: {value}" for key, value in additions]
        return parse_custom_probe_config("\n".join(lines), policy=self.policy)


def parse_custom_probe_config(
    config_text: str,
    policy: CustomProbeSectionPolicy = DEFAULT_SECTION_POLICY,
) -> CustomProbeConfig:
    """Validate a custom probe block without normalizing its content.

    A block must begin (apart from comments/blank lines) with exactly one
    ``[probe]`` or ``[dockable_probe]`` section.  Related Klipper macro
    sections are allowed because docking/attach/deploy workflows commonly use
    them.  Printer, MCU, motion, thermal, and shell-command sections are
    rejected so a probe input cannot silently become a general printer config.
    """
    if not isinstance(config_text, str) or not config_text.strip():
        raise CustomProbeValidationError("Custom probe configuration cannot be empty.")

    lines = config_text.splitlines()
    first_section = None
    primary_section = None
    primary_count = 0
    current_section = None
    offsets: dict[str, Optional[float]] = {"x_offset": None, "y_offset": None, "z_offset": None}

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        section_name = _section_name(line)
        if stripped.startswith("[") and section_name is None:
            raise CustomProbeValidationError(f"Malformed section header on line {line_number}.")
        if section_name is not None:
            if first_section is None:
                first_section = section_name
            _validate_section(section_name, line_number, policy)
            current_section = section_name
            if section_name in policy.primary_sections:
                primary_count += 1
                primary_section = section_name
            continue

        if first_section is None:
            raise CustomProbeValidationError(
                "Custom probe configuration must start with [probe] or [dockable_probe]."
            )

        if current_section in policy.primary_sections:
            _extract_offset(stripped, offsets, line_number)

    if first_section not in policy.primary_sections:
        raise CustomProbeValidationError(
            "The first section must be [probe] or [dockable_probe]."
        )
    if primary_count != 1 or primary_section is None:
        raise CustomProbeValidationError(
            "Custom probe configuration must contain exactly one primary probe section."
        )

    return CustomProbeConfig(
        config_text=config_text,
        primary_section=primary_section,
        x_offset=offsets["x_offset"],
        y_offset=offsets["y_offset"],
        z_offset=offsets["z_offset"],
        policy=policy,
    )


def _section_name(line: str) -> Optional[str]:
    match = _SECTION_HEADER.match(line)
    if not match:
        return None
    return " ".join(match.group(1).strip().lower().split())


def _validate_section(section_name: str, line_number: int, policy: CustomProbeSectionPolicy) -> None:
    prefix = section_name.split(" ", 1)[0]
    if section_name in policy.primary_sections:
        return
    if prefix in policy.companion_section_prefixes and " " in section_name:
        return
    if section_name in policy.generated_section_names:
        raise CustomProbeValidationError(
            f"Section [{section_name}] conflicts with KACE-generated probe configuration (line {line_number})."
        )
    if any(prefix == prohibited or prefix.startswith(prohibited)
           for prohibited in policy.prohibited_section_prefixes):
        raise CustomProbeValidationError(
            f"Unrelated section [{section_name}] is not allowed in a custom probe block (line {line_number})."
        )
    raise CustomProbeValidationError(
        f"Unsupported section [{section_name}] in a custom probe block (line {line_number}). "
        "Only the configured primary section and related macro sections are supported."
    )


def _extract_offset(line: str, offsets: dict[str, Optional[float]], line_number: int) -> None:
    uncommented = line.split("#", 1)[0].strip()
    if ":" not in uncommented:
        return
    key, value = (part.strip() for part in uncommented.split(":", 1))
    key = key.lower()
    if key not in offsets:
        return
    if offsets[key] is not None:
        raise CustomProbeValidationError(f"Duplicate {key} in primary probe section (line {line_number}).")
    offsets[key] = _numeric_value(value, key)


def _numeric_text(value: Optional[str], key: str) -> str:
    if value is None:
        raise CustomProbeValidationError(f"{key} is required for custom probe geometry.")
    text = str(value).strip()
    _numeric_value(text, key)
    return text


def _numeric_value(value: str, key: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise CustomProbeValidationError(f"{key} must be a numeric Klipper offset.") from None
    if not parsed == parsed or parsed in (float("inf"), float("-inf")):
        raise CustomProbeValidationError(f"{key} must be a finite numeric Klipper offset.")
    return parsed


def _finite_number(value: object, key: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise CustomProbeValidationError(f"{key} must be a finite number.") from None
    if not parsed == parsed or parsed in (float("inf"), float("-inf")):
        raise CustomProbeValidationError(f"{key} must be a finite number.")
    return parsed
