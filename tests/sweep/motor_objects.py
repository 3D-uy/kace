"""Inspect actual pinned Klipper rails/fan consumers without MCU connection.

Executed in the existing loader image with a manifest and result path.
No global connect/ready event or G-code is dispatched.
"""
import json
import os
from pathlib import Path
import subprocess
import sys


def inspect_objects(config_path, expected):
    import klippy
    import reactor
    fd = os.open(os.devnull, os.O_RDONLY)
    printer = None
    try:
        printer = klippy.Printer(reactor.Reactor(), None, {
            'config_file': str(config_path), 'gcode_fd': fd, 'debuginput': os.devnull,
            'software_version': 'motor-scenario-contract', 'start_reason': 'audit'})
        printer._read_config()
        rail = printer.lookup_object('toolhead').get_kinematics().rails[2]
        ownership = {name: sorted(s.get_name() for s in endstop.get_steppers())
                     for endstop, name in rail.get_endstops()}
        assert ownership == expected['z_endstops'], f'Z endstop ownership: {ownership}'
        z_steppers = sorted(s.get_name() for s in rail.get_steppers())
        assert z_steppers == expected['z_steppers'], f'Z rail motors: {z_steppers}'
        from extras.probe import HomingViaProbeHelper
        virtual = isinstance(rail.get_endstops()[0][0], HomingViaProbeHelper)
        assert virtual is expected['virtual_z'], 'Wrong virtual/physical Z endstop'
        if virtual:
            # Official HomingViaProbeHelper.get_steppers() is intentionally []:
            # probing uses its own MCU endstop and later LookupZSteppers callback.
            # Do not fake that callback or dispatch mcu_identify to fill this list.
            assert printer.lookup_object('probe') is not None
        fans = {}
        for name, target in expected['controller_fans'].items():
            controller = printer.lookup_object(name)
            # This specific callback resolves objects only. It neither connects
            # MCUs nor starts the periodic fan callback (handle_ready).
            controller.handle_connect()
            actual = {'steppers': sorted(controller.stepper_names),
                      'heaters': sorted(h.get_name() for h in controller.heaters)}
            assert actual == target, f'Controller consumers: {name}: {actual}'
            fans[name] = actual
        return dict(valid=True, z_endstops=ownership, z_steppers=z_steppers,
                    virtual_z=virtual, controller_fans=fans)
    except Exception as exc:
        return dict(valid=False, reason=str(exc), exception=type(exc).__name__)
    finally:
        if printer is not None:
            printer.send_event('klippy:disconnect')
        os.close(fd)


def main():
    root = Path(os.environ.get('KLIPPER_ROOT', '/opt/klipper'))
    sys.path.insert(0, str(root / 'klippy'))
    manifest_path, result_path = map(Path, sys.argv[1:])
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    assert revision == manifest['klipper_ref'], 'Wrong official source'
    results = {c['id']: inspect_objects(manifest_path.parent / c['config_path'], c['expected_objects'])
               for c in manifest['cases'] + manifest['object_controls']}
    result_path.write_text(json.dumps(dict(klipper_ref=revision, results=results), indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
