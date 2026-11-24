#!/usr/bin/env python3
"""Fail-closed format/alignment/partition and sysupgrade extraction tests."""
import importlib.util,io,struct,tarfile,tempfile,unittest,json,zlib
from pathlib import Path
spec=importlib.util.spec_from_file_location('upgrade',Path(__file__).with_name('package-hkc-jdcloud-qwrt-upgrade.py'))
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
def root():
    data=bytearray(65536);data[:4]=b'hsqs';struct.pack_into('<I',data,12,262144)
    struct.pack_into('<H',data,20,4);struct.pack_into('<HH',data,28,4,0)
    struct.pack_into('<Q',data,40,100);struct.pack_into('<Q',data,56,0xffffffffffffffff)
    return data
class UpgradeTests(unittest.TestCase):
    def test_metadata_crc_length_and_board(self):
        def make(board=u.BOARD):
            meta=json.dumps({'metadata_version':'1.1','compat_version':'1.0','supported_devices':[board]}).encode()
            data=bytes(10240)+bytes(8)+meta
            return data+struct.pack('>IIB3sI',0x46577830,zlib.crc32(data)^0xffffffff,1,bytes(3),len(meta)+24)
        good=make();self.assertEqual(u.metadata_info(good)['supported_devices'],[u.BOARD])
        for position in [0,-1,-9,-16]:
            bad=bytearray(good);bad[position]^=1
            with self.assertRaises(ValueError):u.metadata_info(bad)
        with self.assertRaises(ValueError):u.metadata_info(make('other,board'))
    def test_padded_overlay_boundary(self):
        r=u.root_info(root());self.assertEqual(r['overlay_offset'],65536);self.assertEqual(r['overlay_available'],314507264)
    def test_wrong_compression_and_version_rejected(self):
        for offset,value in [(20,6),(28,3)]:
            data=root();struct.pack_into('<H',data,offset,value)
            with self.assertRaises(ValueError):u.root_info(data)
    def test_short_or_nonzero_padding_rejected(self):
        data=root();data[-1]=1
        for v in [data,root()[:-1],root()+bytes(65536)]:
            with self.assertRaises(ValueError):u.root_info(v)
    def test_invalid_used_or_xattrs_rejected(self):
        for offset,value in [(40,0),(40,65537),(56,100)]:
            data=root();struct.pack_into('<Q',data,offset,value)
            with self.assertRaises(ValueError):u.root_info(data)
    def test_original_kernel_identity_required(self):
        for data in [b'',bytes(6291456)]:
            with self.assertRaises(ValueError):u.kernel_info(data)
    def test_container_member_types_duplicates_and_payloads(self):
        directory=u.DIRECTORY;items=[(directory,None),(directory+'/CONTROL',b'BOARD=jdcloud-ax1800-pro\n'),(directory+'/kernel',b'kernel'),(directory+'/root',b'root')]
        def write(path,entries):
            with tarfile.open(path,'w',format=tarfile.USTAR_FORMAT) as tf:
                for name,data in entries:
                    m=tarfile.TarInfo(name)
                    if data is None:m.type=tarfile.DIRTYPE
                    else:m.size=len(data)
                    tf.addfile(m,io.BytesIO(data) if data is not None else None)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.bin';write(path,items);u.check_tar(path,b'kernel',b'root')
            for bad in [items+[(directory+'/kernel',b'other')],items[1:],items+[(directory+'/uboot',b'bad')],list(reversed(items))]:
                write(path,bad)
                with self.assertRaises(ValueError):u.check_tar(path,b'kernel',b'root')
            write(path,items)
            with self.assertRaises(ValueError):u.check_tar(path,b'wrong',b'root')
if __name__=='__main__':unittest.main()
