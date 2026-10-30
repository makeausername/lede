#!/usr/bin/env python3
"""Offline boot-envelope and failed-slot retry regression. No device access."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import hkc_n60pro_image as image
import hkc_n60pro_stock_check as stock
from hkc_n60pro_fit import bind_rootfs, check_rootfs_fit, rootfs_properties


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


fixture = module('runtime_fixture', 'test-hkc-n60pro-runtime.py')
stock_fixture = module('stock_fixture', 'test-hkc-n60pro-stock.py')


def root():
    data = bytearray(b'hsqs' + bytes(range(96)) * 3)
    struct.pack_into('<Q', data, 40, 200)
    return bytes(data)


def retry():
    p = stock_fixture.fixture(); p.update(stock.retry_fields())
    p['ubi.avail_eraseblocks'] = '118'
    return p


class BootFitTests(unittest.TestCase):
    def test_old_missing_binding_rejected(self):
        with self.assertRaisesRegex(ValueError, 'rootfs'):
            image.check_fit(fixture.fit(), root())

    def test_exact_bytes_used_and_original_nodes_preserved(self):
        old = fixture.fit(); data = root(); new = bind_rootfs(old, data)
        report = image.check_fit(new, data)
        self.assertEqual(report['bytes_used'], 200)
        nodes = image.fdt(new)
        for name, props in image.fdt(old).items(): self.assertEqual(nodes[name], props)
        self.assertEqual(bind_rootfs(new, data), new)
        # Actual flash reader supplies only bytes_used; padding must be excluded.
        check_rootfs_fit(new, data[:200])
        check_rootfs_fit(new, data[:200] + b'changed padding')
        bad = bytearray(data); bad[100] ^= 1
        with self.assertRaises(ValueError): check_rootfs_fit(new, bad)
        with self.assertRaises(ValueError): bind_rootfs(new, bad)

    def test_invalid_squashfs_sizes_rejected(self):
        for size in (0, 95, len(root()) + 1, 2**32):
            data = bytearray(root()); struct.pack_into('<Q', data, 40, size)
            with self.subTest(size=size), self.assertRaises(ValueError): bind_rootfs(fixture.fit(), data)

    def test_both_hashes_and_size_are_required(self):
        data = root(); valid = bind_rootfs(fixture.fit(), data)
        props = rootfs_properties(data)
        for value in (props['/rootfs']['size'], props['/rootfs/hash-1']['value'], props['/rootfs/hash-2']['value']):
            offset = valid.rindex(value); bad = bytearray(valid); bad[offset] ^= 1
            with self.assertRaises(ValueError): image.check_fit(bad, data)
        for value in (b'crc32\0', b'sha1\0'):
            bad = valid.replace(value, b'x' + value[1:])
            with self.assertRaises(ValueError): image.check_fit(bad, data)

    def test_duplicate_fdt_and_bounds_rejected(self):
        old = fixture.fit()
        for index, value in ((1, 10), (3, len(old) + 4), (8, len(old)*2), (9, len(old)*2)):
            bad = bytearray(old); struct.pack_into('>I', bad, index * 4, value)
            with self.assertRaises(ValueError): bind_rootfs(bad, root())
        valid = bind_rootfs(old, root())
        bad = valid.replace(b'hash-2\0', b'hash-1\0')
        with self.assertRaises(ValueError): image.fdt(bad)

    def test_future_build_finalizer_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            before, after = Path(tmp)/'before.bin', Path(tmp)/'after.bin'
            p = fixture.payload(); p['root'] = root(); fixture.pack.write_tar(before, p)
            args = [sys.executable, '-B', str(Path(__file__).with_name('hkc-n60pro-fit-rootfs.py')),
                    '--input', str(before), '--output', str(after)]
            run = subprocess.run(args, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr.decode(errors='replace'))
            final = image.read_payload(after); image.check_fit(final['kernel'], final['root'])
            self.assertEqual(final['root'], p['root']); self.assertEqual(final['CONTROL'], p['CONTROL'])
            self.assertNotEqual(final['kernel'], p['kernel'])
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
        mk = (image.ROOT/'target/linux/mediatek/image/filogic.mk').read_text()
        self.assertEqual(mk.count('sysupgrade-tar | hkc-n60pro-rootfs-fit | append-metadata'), 1)
        profile = mk.split('define Device/netcore_n60-pro-stock-slot1\n')[1].split('endef')[0]
        self.assertIn('hkc-n60pro-rootfs-fit', profile)


class RetryTests(unittest.TestCase):
    def test_only_known_invalid_slot_may_be_reclaimed(self):
        p = retry()
        self.assertFalse(stock.assess(p, 4481940, 45681664)['hardware_candidate'])
        r = stock.assess(p, 4481940, 45681664, retry_failed_slot1=True)
        self.assertTrue(r['hardware_candidate'], r)
        self.assertEqual(r['capacity']['available_lebs'], 514)
        self.assertEqual(r['capacity']['reclaim_failed_slot1_lebs'], 396)
        self.assertEqual(r['capacity']['required_lebs'], 479)
        for key in stock.retry_fields():
            bad = dict(p); bad[key] = 'unexpected'
            with self.subTest(key=key):
                self.assertFalse(stock.assess(bad, 4481940, 45681664, retry_failed_slot1=True)['hardware_candidate'])

    def test_private_overlay_unknown_volume_and_capacity_rejected(self):
        for change in ({'volume.hkc_data': '67'}, {'volume.unknown': '1'}, {'ubi.avail_eraseblocks': '82'},
                       {'boot_image_slot': '1'}, {'env_slot_1_invalid': '0'}):
            p = retry(); p.update(change)
            with self.subTest(change=change):
                self.assertFalse(stock.assess(p, 4481940, 45681664, retry_failed_slot1=True)['hardware_candidate'])

    def test_backup_hashes_and_probe_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); entries = []
            devices = ['/dev/mtd'+str(n) for n in range(1,6)] + ['/dev/ubi0_0','/dev/ubi0_5','/dev/ubi0_6','/sys/firmware/fdt']
            for index, device in enumerate(devices + [None]):
                name = str(index)+'.bin' if device else 'config-private.tar.gz'
                data = (name + 'fixture').encode(); (folder/name).write_bytes(data)
                row = {'file':name, 'sha256':hashlib.sha256(data).hexdigest(), 'bytes':len(data)}
                if device: row.update(device=device, matches_live_hash=True)
                entries.append(row)
            manifest = folder/'manifest.json'
            manifest.write_text(json.dumps({'files':entries,'two_live_hash_reads_agree':True,'router_changes':False}))
            hashes = {r['device']:r['sha256'] for r in entries if 'device' in r}
            failed = {n:(d,l,hashes['/dev/'+d]) for n,(d,l,h) in stock.FAILED_SLOT1.items()}
            with patch.object(stock,'FAILED_SLOT1',failed), patch.object(stock,'FAILED_ENV_SHA256',hashes['/dev/ubi0_0']):
                p = retry(); stock.verify_retry_backup(manifest,p)
                bad = dict(p); bad['env_sha256'] = '0'*64
                with self.assertRaises(ValueError): stock.verify_retry_backup(manifest,bad)
                (folder/entries[0]['file']).write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError,'hash/size'): stock.verify_retry_backup(manifest,p)


if __name__ == '__main__': unittest.main(verbosity=2)
