"""Read-only terminal view of the configured nozzle/bed geometry."""
import math
import shutil
import textwrap

from core.motion_model import PrinterMotionSpace, PrintableGeometryError
from core.terminal import RESET, SECTION
from core.translations import t


def _outside(value, limits):
    low, high = limits
    return value - low if value < low else value - high if value > high else 0.0


def _bed_diagram(bed, width):
    """Label absolute bed edges; nozzle position is stated separately in mm.

    Do not project a point onto a fixed-size box: that made small overhangs look
    large and separated the marker from the dimensions it was meant to explain.
    Very narrow views or long numbers use the textual bounds instead.
    """
    left = f'{bed["x"][0]:g} mm '
    right = f' {bed["x"][1]:g} mm'
    inner = min(17, width - len(left) - len(right) - 2)
    if inner < len(t('nozzle_bed.bed_label')):
        return []
    prefix = ' ' * len(left)
    border = '+' + '-' * inner + '+'
    rows = [
        f'{prefix}+Y: {bed["y"][1]:g} mm',
        f'{left}{border}{right}',
        f'{"-X ":>{len(left)}}|{t("nozzle_bed.bed_label"):^{inner}}| +X',
        f'{prefix}{border}',
        f'{prefix}-Y: {bed["y"][0]:g} mm',
    ]
    return rows if all(len(row) <= width for row in rows) else []


def print_nozzle_bed_preview(data):
    """Use the shared model, never fabricate missing bed/travel/endstop inputs."""
    width = max(12, shutil.get_terminal_size(fallback=(80, 24)).columns - 4)

    def line(text, color=RESET):
        for part in textwrap.wrap(text, width=width, break_on_hyphens=False):
            print(f'  {color}{part}{RESET}')

    line(t('nozzle_bed.title'), SECTION)
    required = [f'{axis}_position_{bound}' for axis in ('x', 'y') for bound in ('min', 'max')]
    required += [f'printable_{axis}_{bound}' for axis in ('x', 'y') for bound in ('min', 'max')]
    try:
        if any(data.get(key) in (None, '') for key in required):
            line(t('nozzle_bed.missing'))
            return
        if any(not math.isfinite(float(data[key])) for key in required):
            raise ValueError('non-finite geometry')
        space = PrinterMotionSpace(data)
        bed, rails = space.printable_bed_area(), space.nozzle_reachable_area()
        if any(bed[axis][0] >= bed[axis][1] or rails[axis][0] >= rails[axis][1] for axis in ('x','y')):
            raise ValueError('empty geometry')
    except (TypeError, ValueError, PrintableGeometryError):
        line(t('nozzle_bed.invalid'))
        return

    line(t('nozzle_bed.orientation'))
    line(t('nozzle_bed.size', x=f'{bed["x"][1]-bed["x"][0]:g}',
           y=f'{bed["y"][1]-bed["y"][0]:g}'))
    line(t('nozzle_bed.schematic'))
    rows = _bed_diagram(bed, width)
    if rows:
        for row in rows:
            print(f'  {SECTION}{row}{RESET}')
    else:
        for axis in ('x', 'y'):
            line(t('nozzle_bed.bed_bounds', axis=axis.upper(),
                   low=f'{bed[axis][0]:g}', high=f'{bed[axis][1]:g}'))
    line(t('nozzle_bed.homing'), SECTION)
    home = {}
    for axis in ('x','y'):
        try:
            value = float(data[f'{axis}_position_endstop'])
            if math.isfinite(value) and rails[axis][0] <= value <= rails[axis][1]:
                home[axis] = value
        except (KeyError, TypeError, ValueError):
            pass
    if len(home) == 2:
        line(t('nozzle_bed.position', x=f'{home["x"]:g}', y=f'{home["y"]:g}'))
    for axis, low_side, high_side in (('x','left','right'),('y','front','back')):
        if axis not in home:
            line(t('nozzle_bed.unknown_home', axis=axis.upper()))
            continue
        distance = _outside(home[axis], bed[axis])
        if distance:
            line(t('nozzle_bed.outside', axis=axis.upper(), distance=f'{abs(distance):g}',
                   side=t('nozzle_bed.' + (low_side if distance < 0 else high_side))))
        else:
            line(t('nozzle_bed.inside', axis=axis.upper()))
    line(t('nozzle_bed.homing_note'))

    line(t('nozzle_bed.travel'), SECTION)
    for axis, low_side, high_side in (('x','left','right'),('y','front','back')):
        low = max(0.0, bed[axis][0]-rails[axis][0])
        high = max(0.0, rails[axis][1]-bed[axis][1])
        line(t('nozzle_bed.travel_bounds', axis=axis.upper(),
               low=f'{rails[axis][0]:g}', high=f'{rails[axis][1]:g}'))
        line(t('nozzle_bed.travel_axis', axis=axis.upper(), low=f'{low:g}', high=f'{high:g}',
               low_side=t('nozzle_bed.'+low_side), high_side=t('nozzle_bed.'+high_side)))
    line(t('nozzle_bed.travel_note'))
