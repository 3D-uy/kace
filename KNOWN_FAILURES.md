# Known Test Failures

**Suite baseline:** 306 tests — 301 PASS · 0 FAIL · 0 ERROR · 5 SKIP  
**Last verified:** 2026-06-15 · main

> No open failures. If you run the suite and see any failures, those are yours to investigate before shipping.

---

## Fixed

| ID | Test | Fixed | Notes |
|----|------|-------|-------|
| F-1 | `test_two_motors_z_tilt_template_comment_present` | 2026-06-14 | Moved `z_tilt` scaffold out of probe guard in `printer.cfg.j2` |
| F-2 | `test_corexy_four_motors_quad_gantry_comment_present` | 2026-06-14 | Moved `quad_gantry_level` scaffold out of probe guard in `printer.cfg.j2` |
| E-1 | `test_run_display_setup_step_none` | 2026-06-14 | Replaced `✅` with `[OK]` in `display_wizard.py:433` |
| E-2 | `test_complete_e2e_runtime_pipeline` | 2026-06-14 | Replaced `✔` with `[OK]` in `deployer.py:35,460,479,500` |
| F-3 | `test_module_works_without_yaml` | N/A | Was a false attribution — test-collection contamination side-effect of E-1/E-2. Passes cleanly in isolation. |

---

## Template fix details (F-1 / F-2)

**Root cause:** Both leveling scaffold blocks (`# [z_tilt]` and `# [quad_gantry_level]`) were nested inside the
`{%- if user.probe != 'None' %}` guard in `templates/printer.cfg.j2`. This made them unreachable for the
common case of multi-Z printers without a probe — which is also the majority of production boards.

**Fix:** Closed the probe guard after `[bed_mesh]` (after `fade_target`). The leveling blocks are now governed
only by their own `z_motors` and `kinematics` conditions, which is the correct semantic.

**Snapshot impact:** Zero. All golden fixtures use `z_motors='1'`, so the newly reachable blocks never
trigger for any existing snapshot. No `--update-snapshots` run was needed.

**Klipper safety:** The leveling blocks are fully commented out (`# [z_tilt]`). Klipper never parses them at
startup. Users must explicitly uncomment and fill in `z_positions` before Klipper uses them. No risk of
Klipper rejecting an empty `z_positions` — the block doesn't exist as far as Klipper is concerned until
the user enables it.
