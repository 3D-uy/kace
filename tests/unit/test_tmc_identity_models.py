"""The six admitted TMC section families retain their literal identity."""
import pytest

from core.config_sections import section_identity


@pytest.mark.parametrize('model', ['tmc2208', 'tmc2209', 'tmc2130', 'tmc2240', 'tmc2660', 'tmc5160'])
@pytest.mark.parametrize('separator', [' ', '\t'])
def test_supported_tmc_name_keeps_case_and_separator(model, separator):
    name = f'{model}{separator}extruder_stepper Mix'
    assert section_identity(name) == name
    assert section_identity(name) != section_identity(name.replace('Mix', 'mix'))


def test_unrecognized_tmc_family_keeps_existing_folded_identity():
    assert section_identity('tmc9999 extruder_stepper Mix') == 'tmc9999 extruder_stepper mix'
