import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ReproducibleCiContractTests(unittest.TestCase):
    def test_workflow_pins_actions_runners_python_and_hashed_dependencies(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("ubuntu-latest", workflow)
        self.assertIn('python-version: "3.11.14"', workflow)
        self.assertIn("--require-hashes -r requirements.txt", workflow)
        action_refs = re.findall(r"uses:\s*[^@\s]+@([^\s]+)", workflow)
        self.assertTrue(action_refs)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs))

    def test_firmware_container_pins_base_digest_and_hashed_locks(self):
        dockerfile = (ROOT / "docker" / "ci" / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(
            dockerfile,
            r"(?m)^FROM python:3[.]11-slim-bookworm@sha256:[0-9a-f]{64}$",
        )
        self.assertIn("--require-hashes -r requirements.txt", dockerfile)
        self.assertIn("--require-hashes -r requirements-ssh.txt", dockerfile)
        self.assertNotIn("pip install --no-cache-dir paramiko==", dockerfile)

    def test_simulated_hardware_lab_is_an_explicit_merge_gate(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("simulated-hardware-integration:", workflow)
        self.assertIn(
            "python3 -m unittest tests.integration.test_simulated_firmware_lab -v",
            workflow,
        )
        self.assertIn(
            "needs: [unit-tests, simulated-hardware-integration, yaml-integrity]",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
