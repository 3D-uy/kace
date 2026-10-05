"""The environment that runs tests must preserve the runtime package versions."""
from pathlib import Path
import re


def versions(path):
    return dict(re.findall(r"^([a-zA-Z0-9_-]+)==([^\s\\]+)", path.read_text(encoding="utf-8"), re.MULTILINE))


def test_development_lock_contains_exact_runtime_versions():
    root = Path(__file__).resolve().parents[2]
    runtime = versions(root / "requirements.txt")
    development = versions(root / "requirements-dev.txt")
    assert runtime
    assert {name: development.get(name) for name in runtime} == runtime
