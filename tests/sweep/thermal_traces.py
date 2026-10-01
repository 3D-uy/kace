"""Pinned HeaterCheck with synthetic temperatures, no heater/MCU IO."""
import json
import os
from pathlib import Path
import subprocess
import sys


def run_trace(path, gain_time, scenario, temp, target):
    import klippy
    import reactor
    fd = os.open(os.devnull, os.O_RDONLY)
    printer = None
    try:
        printer = klippy.Printer(reactor.Reactor(), None, {
            'config_file': str(path), 'gcode_fd': fd, 'debuginput': os.devnull,
            'software_version': 'thermal-contract', 'start_reason': 'audit'})
        printer._read_config()
        check = printer.lookup_object('verify_heater heater_bed')
        assert check.check_gain_time == gain_time
        assert check.max_error == 120. and check.hysteresis == 5. and check.heating_gain == 2.
        assert printer.lookup_object('verify_heater extruder').check_gain_time == 20.
        faults = []
        printer.invoke_shutdown = faults.append
        class TemperatureTrace:
            def get_temp(self, eventtime):
                return temp, target
        check.heater = TemperatureTrace()
        events = []
        for eventtime in (0., gain_time - .5, gain_time, gain_time + 1.):
            check.check_event(eventtime)
            events.append(dict(time=eventtime, faults=len(faults), approaching_target=check.approaching_target))
        if scenario == 'not-heating':
            assert [e['faults'] for e in events] == [0, 0, 0, 1]
            assert len(faults) == 1 and 'not heating at expected rate' in faults[0]
        else:
            assert not faults
        return dict(file=path.name, scenario=scenario, gain_time=gain_time, events=events, faults=faults)
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
    records = [run_trace(manifest_path.parent / spec['config_path'], spec['gain_time'], scenario, temp, target)
               for spec in manifest['thermal_traces']
               for scenario, temp, target in (('not-heating', 25., 100.), ('target-zero', 25., 0.), ('at-target', 100., 100.))]
    result_path.write_text(json.dumps(dict(klipper_ref=revision, traces=records,
        scope='Synthetic temperatures/event times; no connection, heating, real-time or physical test.'), indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
