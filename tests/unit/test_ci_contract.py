import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class ReproducibleCiContractTests(unittest.TestCase):
    def test_source_validation_jobs_install_hashed_development_and_ssh_locks(self):
        workflow = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        )
        lock = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        self.assertRegex(lock, r"(?m)^jsonschema==[^\n]+\n\s+--hash=sha256:")
        for job in ("unit-tests", "regression-tests"):
            with self.subTest(job=job):
                steps = workflow["jobs"][job]["steps"]
                install = next(i for i, step in enumerate(steps)
                               if "pip install" in step.get("run", ""))
                validation = next(i for i, step in enumerate(steps)
                                  if "tests/run_tests.py --verbose" in step.get("run", ""))
                self.assertLess(install, validation)
                self.assertEqual(
                    steps[install]["run"],
                    "python3 -m pip install --require-hashes -r requirements-dev.txt -r requirements-ssh.txt",
                )
                setup = next(step for step in steps
                             if step.get("uses", "").startswith("actions/setup-python@"))
                self.assertEqual(setup["with"]["cache-dependency-path"], "requirements-dev.txt")

    def test_workflow_pins_actions_runners_python_and_hashed_dependencies(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("ubuntu-latest", workflow)
        self.assertIn('python-version: "3.11.14"', workflow)
        self.assertIn("--require-hashes -r requirements.txt", workflow)
        action_refs = re.findall(r"uses:\s*[^@\s]+@([^\s]+)", workflow)
        self.assertTrue(action_refs)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs))

    def test_reviewed_scenarios_keep_required_check_and_fail_closed(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["full-klipper-sweep"]
        self.assertEqual(job["name"], "Full Klipper Config Sweep (192+ configs)")
        self.assertEqual(job["needs"], "regression-tests")
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        self.assertEqual(" ".join(job["if"].split()),
            "github.event_name == 'pull_request' || "
            "(github.event_name == 'push' && github.ref == 'refs/heads/main') || "
            "(github.event_name == 'workflow_dispatch' && inputs.full_klipper_sweep)")
        self.assertNotIn("continue-on-error", job)
        steps = job["steps"]
        gates = [(i, step) for i, step in enumerate(steps)
                 if "tests.sweep.scenario_contract" in step.get("run", "")]
        self.assertEqual(len(gates), 1)
        gate_index, gate = gates[0]
        self.assertEqual(gate["run"],
            "python3 -m tests.sweep.scenario_contract --artifacts tests/results/reviewed-scenarios")
        self.assertNotIn("if", gate)
        self.assertNotIn("env", gate)  # No optimized Python or test bypass environment.
        self.assertNotIn("env", job)
        for step in steps:
            self.assertNotIn("continue-on-error", step)
        preparation = next(i for i, step in enumerate(steps)
                           if "git init .klipper-contract-source" in step.get("run", ""))
        self.assertLess(preparation, gate_index)
        command = steps[preparation]["run"]
        self.assertNotIn("if", steps[preparation])
        self.assertIn("from tests.klipper_contract import KLIPPER_REPO_URL, KLIPPER_REF", command)
        self.assertIn('fetch --depth 1 origin "${klipper_source[1]}"', command)
        self.assertIn("checkout --detach FETCH_HEAD", command)
        self.assertIn('test "$(git -C .klipper-contract-source rev-parse HEAD)" = "${klipper_source[1]}"', command)
        install = next(i for i, step in enumerate(steps) if "pip install" in step.get("run", ""))
        self.assertLess(install, preparation)
        self.assertEqual(steps[install]["run"],
                         "python3 -m pip install --require-hashes -r requirements.txt")

    def test_reviewed_scenario_evidence_is_uploaded_even_after_failure(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        steps = workflow["jobs"]["full-klipper-sweep"]["steps"]
        gate_index = next(i for i, step in enumerate(steps)
                          if "tests.sweep.scenario_contract" in step.get("run", ""))
        uploads = [(i, step) for i, step in enumerate(steps)
                   if step.get("uses", "").startswith("actions/upload-artifact@")]
        self.assertEqual(len(uploads), 1)
        index, upload = uploads[0]
        self.assertGreater(index, gate_index)
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["name"], "kace-klipper-full-sweep")
        self.assertEqual(upload["with"]["path"], "tests/results/reviewed-scenarios/")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")

    def test_source_collectors_run_after_pinned_preparation_and_keep_failures(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        steps = workflow["jobs"]["unit-tests"]["steps"]
        prepare = next(i for i, step in enumerate(steps) if step.get("id") == "klipper")
        unit = next(i for i, step in enumerate(steps) if "tests/run_tests.py --verbose" in step.get("run", ""))
        full = next(i for i, step in enumerate(steps) if "python3 -m pytest tests" in step.get("run", ""))
        self.assertLess(prepare, unit)
        self.assertLess(prepare, full)
        self.assertIn("!cancelled()", steps[full]["if"])
        self.assertIn("steps.klipper.outcome == 'success'", steps[full]["if"])
        for step in (steps[unit], steps[full]):
            self.assertEqual(step["shell"], "bash")  # Actions bash uses -eo pipefail.
            self.assertNotIn("continue-on-error", step)
        upload = steps[-1]
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")

    def test_real_builds_are_required_independent_and_retained(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["docker-firmware-build"]
        self.assertEqual(job["name"], "Docker MCU Firmware Builds (LPC1769, STM32, RP2040, AVR)")
        self.assertEqual(job["needs"], "lint")
        run = next(step for step in job["steps"] if "run_real_builds.py" in step.get("run", ""))
        self.assertEqual(run["shell"], "bash")
        self.assertNotIn("continue-on-error", run)
        self.assertNotIn("continue-on-error", job)
        upload = job["steps"][-1]
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")

    def test_firmware_container_pins_base_digest_and_hashed_locks(self):
        dockerfile = (ROOT / "docker" / "ci" / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(
            dockerfile,
            r"(?m)^FROM python:3[.]11-slim-bookworm@sha256:[0-9a-f]{64}$",
        )
        self.assertIn("--require-hashes -r requirements.txt", dockerfile)
        self.assertIn("--require-hashes -r requirements-ssh.txt", dockerfile)
        self.assertNotIn("pip install --no-cache-dir paramiko==", dockerfile)

    def test_critical_shell_scripts_have_pinned_syntax_and_shellcheck_gates(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("SHELLCHECK_VERSION: v0.11.0", workflow)
        self.assertRegex(workflow, r"SHELLCHECK_SHA256: [0-9a-f]{64}")
        for script in ("install.sh", "scripts/bootstrap.sh", "docker/ci/entrypoint.sh"):
            self.assertIn(f"bash -n {script}", workflow)
        self.assertIn(
            "shellcheck --severity=warning install.sh scripts/bootstrap.sh docker/ci/entrypoint.sh",
            workflow,
        )

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
