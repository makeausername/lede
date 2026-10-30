#!/usr/bin/env python3
"""Offline packager: verified slot1 maintenance image -> original-Web TEST candidate.
No SSH, upload, boot environment access or firmware writes. Does not authorize flashing.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import subprocess
from hkc_n60pro_stock_check import parse, assess, verify_retry_backup
from hkc_n60pro_image import BOARD, PROFILE, need, read_payload, check_kernel_fit, check_fit, check_root, metadata
from hkc_n60pro_fit import bind_rootfs
VENDOR_BOARD = 'mediatek,mt7986a-2500wan-spim-snand-rfb'


def factory_metadata(source, source_sha):
    need(source.get('supported_devices') == [BOARD], 'not a slot1 maintenance image')
    need(source.get('compat_version', '1.0') == '1.0', 'unsupported compatibility version')
    return {'metadata_version': '1.1', 'compat_version': '1.0', 'up_model': 'N60PRO',
            'supported_devices': [VENDOR_BOARD], 'version': source['version'],
            'hkc_image_role': 'stock-first-install-slot1-test', 'hkc_source_sha256': source_sha}


def write_tar(path, payload):
    prefix = 'sysupgrade-' + PROFILE
    options = {'fileobj': path} if hasattr(path, 'write') else {'name': path}
    with tarfile.open(mode='w', format=tarfile.USTAR_FORMAT, **options) as tar:
        d = tarfile.TarInfo(prefix); d.type = tarfile.DIRTYPE; d.mode = 0o755
        tar.addfile(d)
        for name in ['CONTROL', 'kernel', 'root']:
            m = tarfile.TarInfo(prefix + '/' + name); m.mode = 0o644; m.size = len(payload[name])
            tar.addfile(m, io.BytesIO(payload[name]))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', type=Path, required=True)
    ap.add_argument('--sha256', required=True, help='expected hash from the verified build artifact')
    ap.add_argument('--probe', type=Path, required=True, help='fresh stock read-only probe, still boot slot0')
    ap.add_argument('--fwtool', type=Path, required=True)
    ap.add_argument('--unsquashfs', type=Path, required=True)
    ap.add_argument('--retry-failed-slot1-backup', type=Path,
                    help='explicitly allow only the identified failed slot1; verified backup manifest required')
    ap.add_argument('--output', type=Path, help='omit to validate only; must end in -stock-first-install-slot1.candidate.bin')
    args = ap.parse_args()
    digest = hashlib.sha256(args.image.read_bytes()).hexdigest()
    need(digest == args.sha256.lower(), 'source image SHA256 mismatch')
    payload = read_payload(args.image)
    check_kernel_fit(payload['kernel']); check_root(payload['root'], args.unsquashfs)
    original_kernel_sha = hashlib.sha256(payload['kernel']).hexdigest()
    payload['kernel'] = bind_rootfs(payload['kernel'], payload['root'])
    boot_binding = check_fit(payload['kernel'], payload['root'])
    probe = parse(args.probe.read_text(encoding='utf-8'))
    if args.retry_failed_slot1_backup:
        verify_retry_backup(args.retry_failed_slot1_backup, probe)
    result = assess(probe, len(payload['kernel']), len(payload['root']),
                    retry_failed_slot1=bool(args.retry_failed_slot1_backup))
    need(result['hardware_candidate'] and result['capacity']['fits'], 'stock probe/capacity rejected: ' + str(result['errors']))
    meta = factory_metadata(metadata(args.image, args.fwtool), digest)
    report = {'source_sha256': digest, 'source_metadata': meta, 'capacity': result['capacity'],
              'stock_boot_rootfs_binding': boot_binding, 'original_kernel_sha256': original_kernel_sha,
              'kernel_sha256': hashlib.sha256(payload['kernel']).hexdigest(),
              'root_sha256': hashlib.sha256(payload['root']).hexdigest(),
              'retry_failed_slot1': bool(args.retry_failed_slot1_backup),
              'probe_sha256': hashlib.sha256(args.probe.read_bytes()).hexdigest(),
              'release_ready': False, 'flash_authorized': False,
              'limitations': ['bootloader recovery unverified', 'first boot unverified', 'not a production release',
                              'stock Web starts flashing immediately after validation; do not upload for a test']}
    if args.output:
        out = args.output.resolve()
        need(out.name.endswith('-stock-first-install-slot1.candidate.bin'), 'wrong output role/name')
        need(not out.exists() and out != args.image.resolve(), 'refusing to overwrite a file')
        with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
            candidate = Path(tmp) / 'candidate.bin'; write_tar(candidate, payload)
            mf = Path(tmp) / 'metadata.json'; mf.write_text(json.dumps(meta), encoding='utf-8')
            subprocess.run([str(args.fwtool), '-I', str(mf), str(candidate)], check=True, capture_output=True)
            need(metadata(candidate, args.fwtool) == meta, 'metadata round trip differs')
            check = read_payload(candidate)
            need(check == payload, 'payload changed during packaging')
            report['factory_sha256'] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            # Exclusive creation, never replace an existing image, even after a race.
            with out.open('xb') as f: f.write(candidate.read_bytes())
        out.with_suffix(out.suffix + '.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
