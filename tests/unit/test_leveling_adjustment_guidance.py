"""Generated optional examples describe the pinned adjustment limits precisely."""
import pytest

from core.pin_validator import _read_pin_config
from tests.unit.test_effective_xy_geometry import _generate


@pytest.mark.parametrize("language,cycles,measured,positive,absolute", [
    ("English", "Additional probing cycles", "probed Z values", "positive computed adjustment", "absolute motor travel"),
    ("Español", "Ciclos adicionales de sondeo", "valores Z sondeados", "ajuste positivo calculado", "recorrido absoluto de los motores"),
    ("Português", "Ciclos adicionais de sondagem", "valores Z sondados", "ajuste positivo calculado", "curso absoluto dos motores"),
])
@pytest.mark.parametrize("count,kinematics,section", [(2, "cartesian", "z_tilt"), (4, "corexy", "quad_gantry_level")])
def test_adjustment_examples_keep_values_commented_and_describe_algorithm(
        tmp_path, monkeypatch, language, cycles, measured, positive, absolute, count, kinematics, section):
    monkeypatch.setattr("core.generator.get_lang", lambda: language)
    text = _generate(tmp_path, z_count=count, kinematics=kinematics, language=language).decode()
    assert section not in _read_pin_config(text)[0]
    example = text.split(f"# [{section}]", 1)[1].split("\n[", 1)[0]
    assert "# retries: 5" in example and "# retry_tolerance: 0.0075" in example
    assert cycles in example and measured in example
    if section == "quad_gantry_level":
        assert "# max_adjust: 4" in example
        assert positive in example and absolute in example
