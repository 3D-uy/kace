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


def _bed_diagram(point=None, *, travel=False):
    """Schematic, not to scale: normalized point may lie beyond either edge."""
    grid = [[' '] * 27 for _ in range(9)]
    for y in (2, 6):
        grid[y][4:23] = list('+' + '-' * 17 + '+')
    for y in range(3, 6):
        grid[y][4] = grid[y][22] = '|'
    if travel:
        grid[4][1], grid[4][25] = '<', '>'
        grid[0][13], grid[8][13] = '^', 'v'
    elif point is not None:
        x, y = point
        col = 1 if x < 0 else 25 if x > 1 else 4 + round(x * 18)
        row = 8 if y < 0 else 0 if y > 1 else 6 - round(y * 4)
        grid[row][col] = 'N'
    return [''.join(row).rstrip() for row in grid]


def print_nozzle_bed_preview(data):
    """Use the shared model, never fabricate missing bed/travel/endstop inputs."""
    width = max(28, shutil.get_terminal_size(fallback=(80, 24)).columns - 4)

    def line(text, color=RESET):
        for part in textwrap.wrap(text, width=width, break_on_hyphens=False):
            print(f'  {color}{part}{RESET}')

    def diagram(point=None, *, travel=False):
        for row in _bed_diagram(point, travel=travel):
            print(f'  {SECTION}{row}{RESET}')

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
    line(t('nozzle_bed.schematic'))
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
        diagram(tuple((home[axis]-bed[axis][0])/(bed[axis][1]-bed[axis][0]) for axis in ('x','y')))
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
    diagram(travel=True)
    for axis, low_side, high_side in (('x','left','right'),('y','front','back')):
        low = max(0.0, bed[axis][0]-rails[axis][0])
        high = max(0.0, rails[axis][1]-bed[axis][1])
        line(t('nozzle_bed.travel_axis', axis=axis.upper(), low=f'{low:g}', high=f'{high:g}',
               low_side=t('nozzle_bed.'+low_side), high_side=t('nozzle_bed.'+high_side)))
    line(t('nozzle_bed.travel_note'))
