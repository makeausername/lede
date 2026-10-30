#!/usr/bin/env python3
"""Finalize only the dedicated slot1 raw sysupgrade tar, before append-metadata."""
import argparse
import importlib.util
from pathlib import Path
from hkc_n60pro_image import read_payload, check_kernel_fit, check_fit, need
from hkc_n60pro_fit import bind_rootfs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    need(not args.output.exists(), 'refusing to overwrite FIT output')
    payload = read_payload(args.input)
    check_kernel_fit(payload['kernel'])
    payload['kernel'] = bind_rootfs(payload['kernel'], payload['root'])
    check_fit(payload['kernel'], payload['root'])
    spec = importlib.util.spec_from_file_location('pack', Path(__file__).with_name('package-hkc-n60pro-stock.py'))
    pack = importlib.util.module_from_spec(spec); spec.loader.exec_module(pack)
    # Exclusive open also protects against a race between the check and creation.
    with args.output.open('xb') as out:
        pack.write_tar(out, payload)
    need(read_payload(args.output) == payload, 'finalized tar round trip differs')


if __name__ == '__main__':
    main()
