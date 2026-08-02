# Reproduced configuration compatibility findings

These findings were recorded before applying the minimal generator fixes. The
matrix regression tests preserve the expected behavior.

## MATRIX-01: Delta was accepted without a delta template

`generate_config()` accepted `kinematics=delta`, but `printer.cfg.j2` emitted
`[stepper_x]`, `[stepper_y]`, and `[stepper_z]`. Stock Klipper delta requires
delta rails and therefore cannot load that generated configuration. KACE must
reject delta safely until it has a dedicated implementation.

Reproduction:

```text
python -m unittest tests.unit.test_config_matrix.TestGenerationFlow -v
unexpected_generation: KACE accepted a case marked for safe rejection
```

## MATRIX-02: Structured probe section names did not match Klipper

KACE emitted `[cr-touch]` and `[inductive]`. The pinned stock Klipper commit
provides `[bltouch]` and `[probe]`; it has no modules named `cr-touch` or
`inductive`. CR Touch must use the BLTouch-compatible section and an inductive
probe must use the generic probe section.

## MATRIX-03: Dockable probe requires an external Klipper module

KACE accepted verbatim `[dockable_probe]`, but the pinned stock Klipper commit
does not contain `klippy/extras/dockable_probe.py`. Until KACE has an explicit
extension contract, generation must reject this selection safely instead of
producing a configuration that stock Klipper cannot load.

## MATRIX-04: Optional rotation distances rendered as `None`

The wizard data contract contains rotation-distance keys with `None` values.
Jinja's one-argument `default` filter only replaces undefined values, so KACE
emitted `rotation_distance: None`. The pinned Klipper loader rejected it with
`Unable to parse option 'rotation_distance' in section 'stepper_x'`.

## MATRIX-05: A custom probe without `z_offset` was not loadable

The custom-probe model treated `z_offset` as optional and preserved a raw block
without it. Stock Klipper requires `z_offset` in `[probe]`, so the loader failed
with `Option 'z_offset' in section 'probe' must be specified`. Guided setup now
emits a neutral zero and raw custom input must specify the value explicitly.
