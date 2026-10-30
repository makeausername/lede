#!/usr/bin/env python3
"""Validate a built slot1 research image. No factory packaging or device access."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from hkc_n60pro_image import BOARD, PROFILE, ROOT, need, metadata, read_payload, check_fit, check_root
from hkc_n60pro_stock_check import OVERLAY_BYTES, EXTRA_FREE_LEBS


def check_metadata(meta):
    need(meta.get('supported_devices') == [BOARD], 'wrong maintenance-image identity')
    need(meta.get('compat_version', '1.0') == '1.0', 'unexpected compatibility version')
    need('up_model' not in meta, 'research maintenance image must not claim original-Web compatibility')
    version = meta.get('version', {})
    need(version.get('target') == 'mediatek/filogic', 'wrong target platform')
    need(version.get('board') == PROFILE, 'wrong profile metadata')


def verify(path, fwtool, unsquashfs, commit):
    need(bool(re.fullmatch('[0-9a-f]{40}', commit)), 'source commit must be a full SHA')
    need(path.stat().st_size <= 96 * 1024 * 1024, 'oversized image')
    meta = metadata(path, fwtool)
    check_metadata(meta)
    payload = read_payload(path)
    check_fit(payload['kernel'])
    check_root(payload['root'], unsquashfs)
    sizes = {name: len(payload[name]) for name in ('kernel', 'root')}
    leb = 126976
    needed = sum((size + leb - 1) // leb for size in [*sizes.values(), OVERLAY_BYTES]) + EXTRA_FREE_LEBS
    runtime_lines = (ROOT / 'custom/hkc-stability-runtime.sha256').read_text().splitlines()
    runtime_count = len([line for line in runtime_lines if line and not line.startswith('#')])
    return {
        'source_commit': commit, 'image': path.name,
        'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'image_metadata': meta, 'payload_bytes': sizes,
        'payload_sha256': {name: hashlib.sha256(payload[name]).hexdigest() for name in sizes},
        'verified_stability_runtime_files': runtime_count,
        'required_free_lebs_before_first_install': needed, 'leb_bytes': leb,
        'isolated_overlay_bytes': OVERLAY_BYTES, 'additional_free_lebs': EXTRA_FREE_LEBS,
        'checks': ['FIT hashes, ARM64 load/entry and text_offset', 'dedicated DTB identity and partition layout',
                   '12 accepted stability/clock runtime files', 'SSR monitor, subscription UI and defaults',
                   'Chinese catalog, LAN IPv4-only script', 'migration helpers, LED/network/Wi-Fi MAC routes'],
        'image_validation_passed': True, 'release_ready': False, 'flash_authorized': False,
        'limitations': ['fresh device probe/capacity check still required',
                        'not an original-Web first-install package', 'boot and recovery remain unverified',
                        'not a production release']}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', type=Path, required=True)
    ap.add_argument('--fwtool', type=Path, required=True)
    ap.add_argument('--unsquashfs', type=Path, required=True)
    ap.add_argument('--commit', required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    report = verify(args.image, args.fwtool, args.unsquashfs, args.commit)
    # Do not leave a success report when any validation above fails.
    with args.report.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2); output.write('\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
