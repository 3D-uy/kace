"""Explicit source-policy review bound to rendered hardware, not certification."""
import copy
import hashlib

from core.exceptions import GenerationError
from core.heater_verification import (
    PROFILE_SOURCE, _profile_verification_options, _settings, source_verification_options,
)

RECEIPT = "_thermal_policy_confirmation"
ARTIFACT_REVIEW = "_thermal_artifact_review"


def required_policy(board, user=None):
    sources = [source_verification_options(board)]
    sources.append(_profile_verification_options(user) if user is not None
                   else source_verification_options((board or {}).get(PROFILE_SOURCE)))
    combined = {}
    for source in sources:
        for name, fields in source.items():
            settings = _settings(name, fields)
            if name in combined and _settings(name, combined[name]) != settings:
                raise GenerationError(f"[{name}]: conflicting board/profile thermal policies require review.")
            combined.setdefault(name, {}).update(fields)
    required = {name: fields for name, fields in combined.items() if _settings(name, fields) != _settings(name, {})}
    if any(name not in ("verify_heater extruder", "verify_heater heater_bed") for name in required):
        raise GenerationError("Thermal policy generation supports only the primary extruder and heater_bed.")
    return required


def source_identity(user):
    def digest(key):
        raw = user.get(key)
        return hashlib.sha256(raw.replace("\r\n", "\n").encode()).hexdigest() if isinstance(raw, str) else None
    return {"board": user.get("board"), "printer_profile": user.get("printer_profile"),
            "board_source_sha256": digest("board_raw_config"),
            "profile_source_sha256": digest("raw_config") if user.get("_profile_parsed") or user.get("profile_loaded") else None}


def hardware_signature(content, policy):
    from core.managed_config import _section_options
    sections = _section_options(content)
    heaters = {name.split()[1] for name in policy}
    if not heaters <= sections.keys():
        raise GenerationError("Thermal review requires every selected heater in the rendered configuration.")
    # Keep complete affected heater blocks and configured sensor/MCU/alias
    # dependencies. Comparing definitions avoids certifying GPIO equivalence or
    # silently allowing a custom sensor to shadow a previously selected type.
    families = {"mcu", "board_pins", "thermistor", "adc_temperature", "adc_scaled", "temperature_sensor"}
    return {name: fields for name, fields in sections.items()
            if name in heaters or name.split()[0] in families}


def review_payload(board, user, content):
    policy = required_policy(board, user)
    return {"schema": 1, "sources": source_identity(user), "policy": policy,
            "hardware": hardware_signature(content, policy)}


def confirmation_matches(receipt, payload):
    return isinstance(receipt, dict) and type(receipt.get("schema")) is int and receipt == payload


def render_confirmed_policy(payload, user, content):
    if not payload["policy"]:
        return content
    if not confirmation_matches(user.get(RECEIPT), payload):
        names = ", ".join(f"[{name}] ({', '.join(fields)})" for name, fields in payload["policy"].items())
        raise GenerationError(f"selected-source protection requires explicit review for this rendered hardware: {names}.")
    for name, fields in payload["policy"].items():
        content += f"\n[{name}]\n" + "".join(f"{key}: {value}\n" for key, value in sorted(fields.items()))
    return content


def attach_thermal_review(context, user, saved):
    merged = {**saved, **user}
    receipt = merged.get(RECEIPT)
    if saved.get(RECEIPT) is not None and receipt != saved[RECEIPT]:
        raise GenerationError("Thermal confirmation differs from the saved workflow; regenerate its context.")
    if receipt is None:
        return context  # Existing manually prepared artifacts retain B30-B32 checks.
    if (not isinstance(receipt, dict) or type(receipt.get("schema")) is not int
            or receipt.get("schema") != 1 or receipt.get("sources") != source_identity(merged)):
        raise GenerationError("Thermal confirmation source changed; review and regenerate the configuration.")
    result = copy.deepcopy(context) if context is not None else {}
    result[ARTIFACT_REVIEW] = copy.deepcopy(receipt)
    return result


def validate_reviewed_artifact(context, content):
    if ARTIFACT_REVIEW not in context:
        return
    receipt = context[ARTIFACT_REVIEW]
    policy = required_policy(context)
    payload = {"schema": 1, "sources": receipt.get("sources") if isinstance(receipt, dict) else None,
               "policy": policy, "hardware": hardware_signature(content, policy)}
    if not confirmation_matches(receipt, payload):
        raise GenerationError("Reviewed thermal hardware or policy changed; review and regenerate the configuration.")
