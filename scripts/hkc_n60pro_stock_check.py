#!/usr/bin/env python3
"""Offline assessment only. Never connects to or writes a router, never emits images."""
import argparse
import json
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

def assess(p, kernel_size=None, root_size=None):
    errors = [f'{key}: unsupported or missing value' for key, val in EXPECTED.items() if p.get(key) != val]
    for name, (offset, size) in PARTITIONS.items():
        for field, expected in [('offset', offset), ('size', size), ('count', 1)]:
            if p.get(f'mtd.{name}.{field}') != str(expected):
                errors.append(f'mtd.{name}.{field}: mismatch')
    for name in ['u-boot-env', 'kernel', 'rootfs', 'rootfs_ext', 'rootfs_data']:
        if 'volume.' + name not in p:
            errors.append('missing stock volume: ' + name)
    for name in ['kernel2', 'rootfs2', 'hkc_data']:
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
            capacity = {'required_lebs': needed, 'available_lebs': free, 'fits': needed <= free}
            if needed > free:
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
