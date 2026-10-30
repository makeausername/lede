#!/usr/bin/env python3
"""Offline regression for a NOT RELEASED stock-Web migration research target."""
import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check', ROOT / 'scripts/hkc_n60pro_stock_check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def fixture():
    p = dict(check.EXPECTED)
    for n, (o, s) in check.PARTITIONS.items():
        p.update({f'mtd.{n}.offset': str(o), f'mtd.{n}.size': str(s), f'mtd.{n}.count': '1'})
    p.update({'volume.' + n: '1' for n in ['u-boot-env', 'kernel', 'rootfs', 'rootfs_ext', 'rootfs_data']})
    p.update({'ubi.bad_peb_count': '0', 'ubi.eraseblock_size': '126976',
              'ubi.avail_eraseblocks': '514', 'env_state': 'default_bad_crc'})
    return p


class AssessmentTests(unittest.TestCase):
    def test_observed_device_is_candidate_but_never_release(self):
        r = check.assess(fixture(), 4480212, 45677568)
        self.assertTrue(r['hardware_candidate'])
        self.assertTrue(r['capacity']['fits'])
        self.assertFalse(r['release_ready'])
        self.assertTrue(r['warnings'])

    def test_reject_each_incompatible_identity_or_slot_field(self):
        for key in check.EXPECTED:
            with self.subTest(key=key):
                p = fixture(); p[key] = 'unexpected'
                self.assertFalse(check.assess(p)['hardware_candidate'])

    def test_reject_each_partition_offset_size_and_duplicates(self):
        for n in check.PARTITIONS:
            for k in ['offset', 'size', 'count']:
                with self.subTest(n=n, k=k):
                    p = fixture(); p[f'mtd.{n}.{k}'] = '-1'
                    self.assertFalse(check.assess(p)['hardware_candidate'])

    def test_reject_occupied_destination(self):
        for n in ['kernel2', 'rootfs2', 'hkc_data']:
            p = fixture(); p['volume.' + n] = '1'
            self.assertFalse(check.assess(p)['hardware_candidate'])

    def test_reject_insufficient_capacity(self):
        p = fixture(); p['ubi.avail_eraseblocks'] = '1'
        self.assertFalse(check.assess(p, 4480212, 45677568)['hardware_candidate'])

    def test_invalid_or_incomplete_inputs_fail_closed(self):
        self.assertFalse(check.assess({})['hardware_candidate'])
        self.assertFalse(check.assess(fixture(), -1, 1)['hardware_candidate'])
        with self.assertRaises(ValueError): check.parse('model=N60PRO\nmodel=N60PRO')
        with self.assertRaises(ValueError): check.parse('invalid line')

    def test_unknown_environment_not_allowed(self):
        p = fixture(); p['env_state'] = 'unknown'
        self.assertFalse(check.assess(p)['hardware_candidate'])


class IsolationTests(unittest.TestCase):
    def test_frozen_stable_sources(self):
        b = json.loads((ROOT / 'custom/hkc-n60pro-stock-baseline.json').read_text())
        for name, expected in b['sha256_lf'].items():
            with self.subTest(name=name):
                data = (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)

    def test_only_target_changed_in_configuration(self):
        original = (ROOT / 'configs/hkc-n60-pro.config').read_text()
        candidate = (ROOT / 'configs/hkc-n60-pro-stock-slot1.config').read_text()
        self.assertEqual(candidate, original.replace('DEVICE_netcore_n60-pro=y', 'DEVICE_netcore_n60-pro-stock-slot1=y'))

    def test_no_vendor_accepted_factory_export(self):
        profile = (ROOT / 'target/linux/mediatek/image/filogic.mk').read_text().split('define Device/netcore_n60-pro-stock-slot1\n')[1].split('endef')[0]
        self.assertNotIn('mediatek,mt7986a-2500wan-spim-snand-rfb', profile)
        self.assertNotIn('factory.bin', profile)
        self.assertIn('SUPPORTED_DEVICES := netcore,n60-pro-stock-slot1', profile)

    def test_only_isolated_workflow_added(self):
        self.assertEqual(sorted(p.name for p in (ROOT / '.github/workflows').iterdir()), ['hkc-n60pro-stock.yml', 'openwrt-ci.yml'])


def shell_tests(shell):
    paths = ['scripts/hkc-n60pro-stock-probe.sh',
             'target/linux/mediatek/filogic/base-files/lib/upgrade/platform.sh',
             'target/linux/mediatek/filogic/base-files/etc/board.d/01_leds',
             'target/linux/mediatek/filogic/base-files/etc/board.d/02_network',
             'target/linux/mediatek/filogic/base-files/lib/upgrade/hkc-n60pro-slot1.sh',
             'target/linux/mediatek/filogic/base-files/lib/preinit/79_hkc_stock_overlay',
             'target/linux/mediatek/filogic/base-files/etc/hotplug.d/ieee80211/11_fix_wifi_mac']
    for path in paths:
        subprocess.run([shell, '-n', str(ROOT / path)], check=True)
    source = (ROOT / paths[1]).read_text()
    for board, expected in [('netcore,n60-pro-stock-slot1', ['SLOT1', 'SLOT1_CHECK']),
                            ('netcore,n60-pro', ['NAND', 'CHECK']),
                            ('xiaomi,redmi-router-ax6000', ['NAND', 'CHECK'])]:
        script = source + '\nboard_name() { echo "' + board + '"; }\n'
        script += 'nand_do_upgrade() { echo NAND; }\nget_magic_long() { echo 00000000; }\nnand_do_platform_check() { echo CHECK; }\n'
        script += 'hkc_slot1_write() { echo SLOT1; }\nhkc_slot1_check() { echo SLOT1_CHECK; }\n'
        script += 'platform_do_upgrade /nonexistent-image\nplatform_check_image /nonexistent-image\n'
        result = subprocess.run([shell], input=script, text=True, capture_output=True, check=True)
        assert result.stdout.strip().splitlines() == expected, result.stdout
    script = source + '\nboard_name() { echo netcore,n60-pro-stock-slot1; }\nhkc_slot1_write() { return 1; }\nplatform_do_upgrade image\necho UNSAFE_SUCCESS\n'
    result = subprocess.run([shell], input=script, text=True, capture_output=True)
    assert result.returncode == 1 and 'UNSAFE_SUCCESS' not in result.stdout, result
    print('PASS shell syntax, isolated platform routes and stage2 failure stops success/reboot')


def patch_tests(references, patch):
    def apply(folder, path):
        subprocess.run([patch, '-p1', '--batch', '--fuzz=0', '-i', str(path)], cwd=folder, check=True, capture_output=True)
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp); f = folder / 'drivers/mtd/ubi/block.c'; f.parent.mkdir(parents=True)
        f.write_bytes((references / 'linux-block.c').read_bytes())
        for p in ['491-ubi-auto-create-ubiblock-device-for-rootfs.patch', '493-ubi-set-ROOT_DEV-to-ubiblock-rootfs-if-unset.patch']:
            apply(folder, ROOT / 'target/linux/generic/pending-6.12' / p)
        apply(folder, ROOT / 'target/linux/mediatek/patches-6.12/999-hkc-n60pro-stock-slot1-root.patch')
        code = f.read_text()
        assert code.count('hkc_is_rootfs(vi->name)') == 2
        assert '"rootfs2" : "rootfs"' in code
        f = folder / 'libfstools/volume.c'; f.parent.mkdir(parents=True)
        f.write_bytes((references / 'fstools-volume.c').read_bytes())
        apply(folder, ROOT / 'package/system/fstools/patches/100-hkc-n60pro-stock-slot1-overlay.patch')
        code = f.read_text()
        assert 'name = "hkc_data"' in code and 'if (hkc_stock_slot1())' in code
    print('PASS Linux 6.12.95 and pinned fstools patches apply with zero fuzz (not a compiler or boot test)')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--shell', default='/bin/sh')
    ap.add_argument('--references', type=Path)
    ap.add_argument('--patch-tool', default='patch')
    args = ap.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise SystemExit(1)
    shell_tests(args.shell)
    if args.references:
        patch_tests(args.references, args.patch_tool)
    print('Candidate checks passed. NOT RELEASE READY; no flashable factory image was produced.')
