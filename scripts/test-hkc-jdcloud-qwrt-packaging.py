#!/usr/bin/env python3
"""Archive safety, package control and metadata preservation regression tests."""
import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('packing',Path(__file__).with_name('package-hkc-jdcloud-qwrt.py'))
packing=importlib.util.module_from_spec(spec);spec.loader.exec_module(packing)

class PackagingTests(unittest.TestCase):
    def test_linux_names_without_host_extraction(self):
        self.assertEqual(packing.path_name('./lib/firmware/chip:board.bin'),'lib/firmware/chip:board.bin')
        for value in ['/etc/shadow','../../escape','a/../escape','C:/escape','a\\escape']:
            with self.assertRaises(ValueError):packing.path_name(value)
    def test_vendor_package_names_and_continuations(self):
        text='Package: quectel-CM-5G\nVersion: 1\nConffiles: \n /etc/test abcd\nDescription: first\n second\n'
        value=packing.fields(text)
        self.assertEqual(packing.fields(packing.encode(value)),value)
        self.assertEqual(value['Conffiles'],'\n /etc/test abcd')
    def test_duplicate_packages_and_fields_rejected(self):
        for text in ['Package: a\nPackage: b','Package: ../a']:
            with self.assertRaises(ValueError):packing.fields(text)
        with self.assertRaises(ValueError):packing.package_records('Package: a\n\nPackage: a\n')
    def test_dependency_closure_with_provides(self):
        records={'app':{'Depends':'libfoo, missing'},'actual':{'Provides':'libfoo'}}
        self.assertEqual(packing.missing_dependencies(records,['app']),[('app','missing')])
    def test_metadata_roundtrip_long_link_and_console(self):
        entries={}
        for name,kind,mode in [('.',tarfile.DIRTYPE,0o755),('data',tarfile.REGTYPE,0o640),('link',tarfile.SYMTYPE,0o777),('dev/console',tarfile.CHRTYPE,0o600)]:
            m=tarfile.TarInfo(name);m.type=kind;m.mode=mode;m.uid=12;m.gid=34;m.mtime=1730000000
            if name=='link':m.linkname='long/'+('a'*120)
            if name=='dev/console':m.devmajor=5;m.devminor=1
            entries[name]=(m,b'fixture' if name=='data' else b'')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.tar';packing.write_tar(path,entries);again=packing.read_tar(path)
            self.assertEqual({p:packing.metadata(x) for p,x in entries.items()},{p:packing.metadata(x) for p,x in again.items()})
    def test_hardlinks_require_explicit_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.tar'
            with tarfile.open(path,'w') as tf:
                member=tarfile.TarInfo('link');member.type=tarfile.LNKTYPE;member.linkname='target';tf.addfile(member)
            with self.assertRaises(ValueError):packing.read_tar(path)
    def test_duplicate_tar_entries_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.tar'
            with tarfile.open(path,'w') as tf:
                for _ in range(2):tf.addfile(tarfile.TarInfo('same'))
            with self.assertRaises(ValueError):packing.read_tar(path)

if __name__=='__main__':unittest.main()
