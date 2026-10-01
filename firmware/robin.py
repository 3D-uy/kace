"""Finite Robin encoding with separate native and delivery evidence.

XOR operation/pattern from Klipper scripts/update_mks_robin.py,
Copyright (C) 2020 Kevin O'Connor <kevin@koconnor.net>, GNU GPLv3.
Validated against the exact upstream revision and script content below.
"""
import hashlib
import os
from pathlib import Path
import tempfile

from firmware.board_serial import KINGROON, SAPPHIRE, board_serial_ports
from firmware.identity import FirmwareIdentityError
from firmware.startup_gpio import verify_startup_artifact

REVISION = 'fe4eb8650bd7de4c2100a14eaf09b0965c430e29'
SCRIPT_SHA256 = '3a31d672edc333b79345be753906e88f069b782504a18310632b73d690c57811'
SCHEMA = 'kace-robin-delivery/v1'
_PATTERN = bytes.fromhex('a3 bd ad 0d 41 11 bb 8d dc 80 2d d0 d2 c4 9b 1e 26 eb e3 33 4a 15 e4 0a b3 b1 3c 93 bb af f7 3e')


def final_filename(board, lcd_removed):
    if board == KINGROON and lcd_removed is None:
        return 'Robin_nano.bin'
    if board in SAPPHIRE and type(lcd_removed) is bool:
        return 'Robin_nano43.bin' if lcd_removed else 'Robin_nano35.bin'
    raise FirmwareIdentityError('Robin requires an exact reviewed board and an explicit physical LCD choice for Sapphire')


def _encode(native):
    result = bytearray(native)
    for pos in range(320, min(31040, len(result))):
        result[pos] ^= _PATTERN[pos & 31]
    return bytes(result)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _native(path, identity, board, port):
    metadata = identity.to_dict() if hasattr(identity, 'to_dict') else identity
    if not isinstance(metadata, dict) or metadata.get('klipper_commit') != REVISION:
        raise FirmwareIdentityError('Robin transformation requires the reviewed Klipper revision')
    if metadata.get('artifact_format') != 'BIN' or port not in board_serial_ports(board):
        raise FirmwareIdentityError('Robin transformation requires native BIN and an explicit board USART')
    source = Path(path)
    try:
        if source.name != 'klipper.bin' or not 320 < source.stat().st_size <= 32 * 1024 * 1024:
            raise FirmwareIdentityError('Robin source must be a bounded native klipper.bin')
        verify_startup_artifact(board, source, metadata, serial_port=port)
        raw = source.read_bytes()
    except OSError as exc:
        raise FirmwareIdentityError(f'Cannot read native Robin firmware: {exc}') from exc
    if len(raw) != metadata.get('artifact_size') or _sha(raw) != metadata.get('artifact_sha256'):
        raise FirmwareIdentityError('Native Robin bytes changed after the verified build')
    return raw, metadata


def prepare_robin(native_path, identity, *, board, serial_port, lcd_removed, output_dir):
    """Encode only verified native bytes; never overwrite an existing final image."""
    filename = final_filename(board, lcd_removed)
    raw, metadata = _native(native_path, identity, board, serial_port)
    folder = Path(output_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / filename
    # Exclusive publication avoids blessing or replacing an earlier image.
    encoded = _encode(raw)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, final)
    except OSError as exc:
        raise FirmwareIdentityError(f'Cannot publish Robin image exclusively: {exc}') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    evidence = {'schema': SCHEMA, 'board': board, 'serial_port': serial_port,
        'lcd_removed': lcd_removed, 'klipper_commit': REVISION, 'script_sha256': SCRIPT_SHA256,
        'native_path': str(Path(native_path).resolve()), 'native_sha256': metadata['artifact_sha256'],
        'final_path': str(final), 'final_filename': filename, 'final_sha256': _sha(encoded), 'size_bytes': len(raw)}
    verify_robin(evidence, identity, board=board, serial_port=serial_port, lcd_removed=lcd_removed)
    return evidence


def verify_robin(evidence, identity, *, board, serial_port, lcd_removed):
    """Recompute the full relation; a stored pair of hashes alone is insufficient."""
    keys = {'schema', 'board', 'serial_port', 'lcd_removed', 'klipper_commit', 'script_sha256',
            'native_path', 'native_sha256', 'final_path', 'final_filename', 'final_sha256', 'size_bytes'}
    if not isinstance(evidence, dict) or set(evidence) != keys:
        raise FirmwareIdentityError('Incomplete Robin transformation evidence')
    filename = final_filename(board, lcd_removed)
    if (evidence['schema'] != SCHEMA or evidence['board'] != board or evidence['serial_port'] != serial_port
            or type(evidence['lcd_removed']) is not type(lcd_removed) or evidence['lcd_removed'] != lcd_removed
            or evidence['klipper_commit'] != REVISION or evidence['script_sha256'] != SCRIPT_SHA256
            or evidence['final_filename'] != filename):
        raise FirmwareIdentityError('Robin transformation choice or authority changed')
    if not all(isinstance(evidence[k], str) and evidence[k] for k in ('native_path', 'final_path')):
        raise FirmwareIdentityError('Robin paths are missing')
    raw, metadata = _native(evidence['native_path'], identity, board, serial_port)
    final = Path(evidence['final_path'])
    try:
        if final.name != filename or final.stat().st_size != len(raw):
            raise FirmwareIdentityError('Robin final filename or size changed')
        encoded = final.read_bytes()
    except OSError as exc:
        raise FirmwareIdentityError(f'Cannot read final Robin image: {exc}') from exc
    if (evidence['native_sha256'] != metadata['artifact_sha256'] or evidence['size_bytes'] != len(raw)
            or evidence['final_sha256'] != _sha(encoded) or encoded != _encode(raw) or encoded == raw):
        raise FirmwareIdentityError('Robin image does not match its exact native-to-final transformation')
    return evidence['native_path']
