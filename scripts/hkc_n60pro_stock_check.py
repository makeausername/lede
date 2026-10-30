#!/usr/bin/env python3
"""Offline assessment only. Never connects to or writes a router, never emits images."""
import argparse
import json
import hashlib
from pathlib import Path

PARTITIONS = {'BL2': (0, 0x100000), 'u-boot-env': (0x100000, 0x80000),
              'Factory': (0x180000, 0x200000), 'FIP': (0x380000, 0x200000),
              'ubi': (0x580000, 0x7280000)}
EXPECTED = {'schema': '1', 'board': 'mediatek,mt7986a-2500wan-spim-snand-rfb',
            'model': 'N60PRO', 'vendor_version': '2.0.260529.121244',
            'dual_boot': 'Y', 'boot_image_slot': '0', 'upgrade_image_slot': '1',
            'boot_kernel_part': 'kernel', 'boot_rootfs_part': 'rootfs',
            'upgrade_kernel_part': 'kernel2', 'upgrade_rootfs_part': 'rootfs2',
            'rootfs_data_part': 'rootfs_data', 'reserve_rootfs_data': 'Y',
            'encryption_key': 'absent', 'ignore_signature': 'absent', 'ubi.ro_mode': '0', 'ubi.reserved_for_bad': '19'}
OVERLAY_BYTES = 8 * 1024 * 1024
EXTRA_FREE_LEBS = 16
# Narrow retry allowlist: the failed 7ba9f9c44 candidate read back on 2026-10-30.
# This is not permission to erase an arbitrary occupied slot or a working HKC slot.
FAILED_SLOT1 = {
    'kernel2': ('ubi0_5', 36, '27e18f0736e7da8b179762ee75ce5ba949b1f240bbb06eec7ccecee766699279'),
    'rootfs2': ('ubi0_6', 360, '3fc3d1c91a373a3f4d4a94015bbe677d3d8f9e1073b4c8b8398d863104703b4e'),
}
FAILED_ENV_SHA256 = 'd9913dc891bbe2dfc19fbd2a2a423538737ed1e0ec89b534bfafb4e71181e04c'


def retry_fields():
    result = {'env_state': 'valid', 'env_current_slot': '0', 'env_slot_1_invalid': '1',
              'env_sha256': FAILED_ENV_SHA256, 'ubi.mtd_num': '5', 'web_auto_flashes': '3'}
    for name, (device, lebs, digest) in FAILED_SLOT1.items():
        result.update({f'volume.{name}': str(lebs), f'volume_device.{name}': device,
                       f'volume_type.{name}': 'dynamic', f'volume_corrupted.{name}': '0',
                       f'volume_upd_marker.{name}': '0', f'volume_sha256.{name}': digest})
    return result


def verify_retry_backup(manifest, probe):
    """Verify every private local backup file; bind slot volumes/env to fresh probe."""
    report = json.loads(manifest.read_text(encoding='utf-8'))
    if report.get('two_live_hash_reads_agree') is not True or report.get('router_changes') is not False:
        raise ValueError('backup was not verified against unchanged live device')
    devices, names = {}, set()
    for entry in report['files']:
        name = entry['file']
        if name in names or Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('duplicate or unsafe backup path')
        names.add(name)
        path = manifest.parent / name
        if path.is_symlink() or path.resolve().parent != manifest.parent.resolve():
            raise ValueError('backup path escapes directory')
        data = path.read_bytes()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('backup hash/size mismatch: ' + name)
        if 'device' in entry:
            if entry['device'] in devices or entry.get('matches_live_hash') is not True:
                raise ValueError('backup device duplicate or unverified')
            devices[entry['device']] = entry['sha256']
    required = {'/dev/mtd1', '/dev/mtd2', '/dev/mtd3', '/dev/mtd4', '/dev/mtd5',
                '/dev/ubi0_0', '/dev/ubi0_5', '/dev/ubi0_6', '/sys/firmware/fdt'}
    if set(devices) != required or 'config-private.tar.gz' not in names:
        raise ValueError('incomplete device/config backup')
    for name, (device, lebs, digest) in FAILED_SLOT1.items():
        if devices['/dev/' + device] != digest or probe.get('volume_sha256.' + name) != digest:
            raise ValueError('failed slot1 backup/live identity mismatch')
    if devices['/dev/ubi0_0'] != FAILED_ENV_SHA256 or probe.get('env_sha256') != FAILED_ENV_SHA256:
        raise ValueError('failed slot1 boot environment mismatch')

def parse(text):
    result = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, sep, val = line.partition('=')
        if not sep or key in result:
            raise ValueError('malformed or duplicate probe field: ' + key)
        result[key] = val
    return result

def assess(p, kernel_size=None, root_size=None, *, retry_failed_slot1=False):
    errors = [f'{key}: unsupported or missing value' for key, val in EXPECTED.items() if p.get(key) != val]
    for name, (offset, size) in PARTITIONS.items():
        for field, expected in [('offset', offset), ('size', size), ('count', 1)]:
            if p.get(f'mtd.{name}.{field}') != str(expected):
                errors.append(f'mtd.{name}.{field}: mismatch')
    for name in ['u-boot-env', 'kernel', 'rootfs', 'rootfs_ext', 'rootfs_data']:
        if 'volume.' + name not in p:
            errors.append('missing stock volume: ' + name)
    reclaimed = 0
    if retry_failed_slot1:
        errors.extend(key + ': failed-slot1 retry mismatch' for key, value in retry_fields().items()
                      if p.get(key) != value)
        expected_volumes = {'u-boot-env', 'kernel', 'rootfs', 'rootfs_ext', 'rootfs_data', 'kernel2', 'rootfs2'}
        if {key[7:] for key in p if key.startswith('volume.')} != expected_volumes:
            errors.append('unexpected or missing volumes for failed-slot1 retry')
        reclaimed = sum(item[1] for item in FAILED_SLOT1.values())
    for name in (['hkc_data'] if retry_failed_slot1 else ['kernel2', 'rootfs2', 'hkc_data']):
        if 'volume.' + name in p:
            errors.append('destination is not empty: ' + name)
    if p.get('ubi.bad_peb_count') != '0':
        errors.append('bad-block state needs separate assessment')
    warnings = []
    if p.get('env_state') == 'default_bad_crc':
        warnings.append('boot environment is not CRC-valid; backup analysis and bootloader recovery validation required')
    elif p.get('env_state') != 'valid' or p.get('env_current_slot') != '0':
        errors.append('boot environment state unsupported')
    capacity = None
    if kernel_size is not None and root_size is not None:
        try:
            leb = int(p['ubi.eraseblock_size']); free = int(p['ubi.avail_eraseblocks'])
            assert leb == 126976 and kernel_size > 0 and root_size > 0
            needed = sum((n + leb - 1) // leb for n in [kernel_size, root_size, OVERLAY_BYTES]) + EXTRA_FREE_LEBS
            assert free >= 0 and kernel_size <= 16 * 1024 * 1024 and root_size <= 64 * 1024 * 1024
            available = free + reclaimed
            capacity = {'required_lebs': needed, 'available_lebs': available, 'currently_free_lebs': free,
                        'reclaim_failed_slot1_lebs': reclaimed, 'fits': needed <= available}
            if needed > available:
                errors.append('insufficient free space for image, isolated overlay and additional reserve')
        except (KeyError, ValueError, AssertionError):
            errors.append('invalid capacity inputs')
    return {'hardware_candidate': not errors, 'errors': errors, 'warnings': warnings,
            'capacity': capacity, 'release_ready': False,
            'pending_gates': ['compiled first-boot overlay and maintenance updater validation',
                              'complete kernel/fstools/image validation', 'bootloader recovery verification',
                              'real Web factory artifact validation with vendor sysupgrade -T', 'real-device acceptance']}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('probe', type=Path)
    ap.add_argument('--kernel-size', type=int)
    ap.add_argument('--root-size', type=int)
    args = ap.parse_args()
    if (args.kernel_size is None) != (args.root_size is None):
        ap.error('supply both kernel and root sizes')
    result = assess(parse(args.probe.read_text(encoding='utf-8')), args.kernel_size, args.root_size)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['hardware_candidate'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
