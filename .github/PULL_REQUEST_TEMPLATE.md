## Description
Provide a summary of the changes and the reasoning behind them.

## Related Issues
Fixes #[issue-number]

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Checklist:
- [ ] I have run the test suite locally (`python tests/run_tests.py`) and verified all tests pass.
- [ ] I have run YAML schema validation (`python tests/run_tests.py --yaml-check`) if I modified boards or MCU data.
- [ ] My code does not contain hardcoded UI strings; I have used translating calls `t()`.
- [ ] My changes do not leak local paths or credentials (passes local pre-commit hook checks).
