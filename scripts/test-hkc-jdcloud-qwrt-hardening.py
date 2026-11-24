#!/usr/bin/env python3
import copy,hashlib,importlib.util,io,json,os,shutil,struct,subprocess,tarfile,tempfile,unittest,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj
packing=module('package-hkc-jdcloud-qwrt');h=module('build-hkc-jdcloud-qwrt-hardened')
class DeltaTests(unittest.TestCase):
    def base(self,root):
        entries={}
        def put(n,b):
            m=tarfile.TarInfo(n);m.mode=0o644;m.size=len(b);entries[n]=(m,b)
        for name in ['base-files','hkc-qwrt-integration','openvpn']:
            control=('Package: '+name+'\nVersion: 1\nArchitecture: all\n').encode()
            for suffix,data in [('.control',control),('.list',b'')]:put('usr/lib/opkg/info/'+name+suffix,data)
        put('usr/lib/opkg/status',b'\n'.join(entries['usr/lib/opkg/info/'+n+'.control'][1] for n in ['base-files','hkc-qwrt-integration','openvpn']))
        put('lib/upgrade/platform.sh',b'vendor fixture\n')
        put('usr/lib/opkg/info/base-files.list',b'/lib/upgrade/platform.sh\n')
        put('etc/openvpn/server.key',b'-----BEGIN PRIVATE KEY-----\nsynthetic\n')
        put('etc/openvpn/custom.conf',b'# Keep application settings\n')
        put('usr/lib/opkg/info/openvpn.list',b'/etc/openvpn/server.key\n/etc/openvpn/custom.conf\n')
        put('usr/lib/opkg/info/openvpn.conffiles',b'/etc/openvpn/server.key\n/etc/openvpn/custom.conf\n')
        put('lib/firmware/unchanged.bin',b'original-hardware-fixture')
        lines=[]
        for i in range(12):
            p='usr/share/runtime-'+str(i);b=('runtime-'+str(i)).encode();put(p,b);lines.append(hashlib.sha256(b).hexdigest()+'  '+p)
        (root/'custom').mkdir();(root/'custom/hkc-stability-runtime.sha256').write_text('\n'.join(lines)+'\n')
        shutil.copytree(ROOT/'custom/jdcloud-qwrt/hardening',root/'custom/jdcloud-qwrt/hardening')
        return entries
    def test_only_explicit_defaults_upgrade_and_keys_change(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);entries=self.base(root);before=copy.deepcopy(entries);report=h.transform(root,entries,packing)
            self.assertNotIn('etc/openvpn/server.key',entries)
            for p in ['etc/openvpn/custom.conf','lib/firmware/unchanged.bin']:
                self.assertEqual(packing.metadata(entries[p]),packing.metadata(before[p]))
            self.assertNotIn(b'/etc/openvpn/server.key',entries['usr/lib/opkg/info/openvpn.list'][1])
            self.assertNotIn(b'/etc/openvpn/server.key',entries['usr/lib/opkg/info/openvpn.conffiles'][1])
            self.assertEqual(report['accepted_runtime_files'],12)
    def test_unrecognized_private_key_stops_packaging(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);entries=self.base(root);m=tarfile.TarInfo('etc/unexpected.key');entries[m.name]=(m,b'-----BEGIN PRIVATE KEY-----\nfixture')
            with self.assertRaises(AssertionError):h.transform(root,entries,packing)

LUA=os.environ.get('HKC_TEST_LUA') or shutil.which('lua5.1') or shutil.which('lua')
if os.environ.get('CI') and not LUA:raise RuntimeError('Linux CI must install Lua 5.1')
@unittest.skipUnless(LUA,'Native Lua parser tested in QWRT VM; Linux CI requires Lua 5.1')
class ParserTests(unittest.TestCase):
    def image(self):
        root=bytearray(65536);root[:4]=b'hsqs';struct.pack_into('<I',root,12,262144);struct.pack_into('<H',root,20,4);struct.pack_into('<HH',root,28,4,0);struct.pack_into('<Q',root,40,100);struct.pack_into('<Q',root,56,0xffffffffffffffff)
        b=io.BytesIO();directory='sysupgrade-jdcloud-ax1800-pro'
        with tarfile.open(fileobj=b,mode='w',format=tarfile.USTAR_FORMAT) as tf:
            for name,data in [(directory,None),(directory+'/CONTROL',b'BOARD=jdcloud-ax1800-pro\n'),(directory+'/kernel',bytes(6291456)),(directory+'/root',root)]:
                m=tarfile.TarInfo(name)
                if data is None:m.type=tarfile.DIRTYPE
                else:m.size=len(data)
                tf.addfile(m,io.BytesIO(data) if data is not None else None)
        meta=b'{}';data=b.getvalue()+bytes(8)+meta
        return data+struct.pack('>IIB3sI',0x46577830,zlib.crc32(data)^0xffffffff,1,bytes(3),len(meta)+24)
    def check(self,data,ok,root_size='65536'):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fixture.bin';p.write_bytes(data)
            result=subprocess.run([LUA,str(ROOT/'custom/jdcloud-qwrt/hardening/hkc-image.lua'),str(p),root_size],capture_output=True)
            self.assertEqual(result.returncode==0,ok,result.stderr.decode(errors='replace'))
    def test_valid_structure(self):self.check(self.image(),True)
    def test_malformed_header_truncation_and_metadata_length(self):
        good=self.image()
        self.check(good[:2048],False)
        for i in [0,148,-1]:
            bad=bytearray(good);bad[i]^=1;self.check(bad,False)
    def test_root_boundaries_and_compression(self):
        good=self.image();self.check(good,False,'65537');self.check(good,False,'314572800')
        pos=good.index(b'hsqs');bad=bytearray(good);bad[pos+20]=6;self.check(bad,False)
        bad=bytearray(good);bad[pos+65535]=1;self.check(bad,False)
if __name__=='__main__':unittest.main()
