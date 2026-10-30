#!/usr/bin/env python3
"""Offline fixtures only. Never contacts a router or invokes real flash tools."""
import argparse
import hashlib
import importlib.util
import io
import lzma
from pathlib import Path
import shlex
import struct
import subprocess
import tarfile
import tempfile
import unittest
import zlib
import hkc_n60pro_image as image

spec = importlib.util.spec_from_file_location('pack', Path(__file__).with_name('package-hkc-n60pro-stock.py'))
pack = importlib.util.module_from_spec(spec); spec.loader.exec_module(pack)
ROOT = Path(__file__).resolve().parents[1]
HELPER = (ROOT / 'target/linux/mediatek/filogic/base-files/lib/upgrade/hkc-n60pro-slot1.sh').read_text()
SHELL = '/bin/sh'
def q(p):
    value = str(p).replace('\\', '/')
    if len(value)>2 and value[1:3]==':/': value='/'+value[0].lower()+value[2:]
    return shlex.quote(value)
def run(s): return subprocess.run([SHELL], input=s, text=True, capture_output=True)
def u32(n): return struct.pack('>I', n)
def string(s): return s.encode() + b'\0'
def blob(tree):
    names = bytearray(); st = bytearray()
    def word(n): st.extend(u32(n))
    def pad():
        while len(st) % 4: st.append(0)
    def node(name, props, children):
        word(1); st.extend(string(name)); pad()
        for key, value in props.items():
            off = len(names); names.extend(string(key))
            word(3); word(len(value)); word(off); st.extend(value); pad()
        for name, item in children.items(): node(name, *item)
        word(2)
    node('', *tree); word(9)
    return struct.pack('>10I', 0xd00dfeed, 56+len(st)+len(names), 56, 56+len(st), 40, 17, 16, 0, len(names), len(st)) + bytes(16) + st + names

def dtb(board=image.BOARD, bad_layout=False, writable=False):
    children = {}
    for i, (label, (offset, size)) in enumerate(image.LAYOUT.items()):
        props = {'label': string(label), 'reg': u32(offset + (1 if bad_layout else 0)) + u32(size)}
        if label in ('BL2','Factory','FIP') and not writable: props['read-only'] = b''
        children['partition@'+str(i)] = (props, {})
    return blob(({'compatible': string(board)+string('mediatek,mt7986a')}, {'partitions': ({}, children)}))

def fit(load=0x48000000, bad_hash=False, hash_algorithms=('sha256',), corrupt_algorithm=None, **kwargs):
    raw = bytearray(64); raw[56:60] = b'ARM\x64'; raw.extend(string(image.BOARD)+b'rootfs2')
    kernel = lzma.compress(bytes(raw), format=lzma.FORMAT_ALONE); tree = dtb(**kwargs)
    def part(data, extra):
        hashes = {}
        for index, algo in enumerate(hash_algorithms, 1):
            digest = (u32(zlib.crc32(data) & 0xffffffff) if algo == 'crc32'
                      else hashlib.new(algo, data).digest())
            if bad_hash or algo == corrupt_algorithm: digest = bytes(len(digest))
            hashes['hash-' + str(index)] = ({'algo': string(algo), 'value': digest}, {})
        return ({'data':data, **extra}, hashes)
    return blob(({}, {'images': ({}, {'kernel-1': part(kernel, {'arch':string('arm64'),'compression':string('lzma'),'load':u32(load),'entry':u32(load)}), 'fdt-1': part(tree,{})}),
                     'configurations': ({'default':string('config-1')}, {'config-1':({'kernel':string('kernel-1'),'fdt':string('fdt-1')},{})})}))

def payload(): return {'CONTROL': ('BOARD='+image.PROFILE+'\n').encode(), 'kernel':fit(), 'root':b'hsqs' + bytes(100)}

class ImageTests(unittest.TestCase):
    def test_fit_and_dtb(self):
        image.check_fit(fit())
        for args in [{'load':0x48080000},{'bad_hash':True},{'board':'netcore,n60-pro'},{'bad_layout':True},{'writable':True}]:
            with self.subTest(args=args), self.assertRaises(ValueError): image.check_fit(fit(**args))
    def test_fit_crc32_and_sha_are_both_verified(self):
        for crypto in ('sha1', 'sha256'):
            with self.subTest(crypto=crypto):
                image.check_fit(fit(hash_algorithms=('crc32', crypto)))
                for corrupted in ('crc32', crypto):
                    with self.assertRaisesRegex(ValueError, 'FIT hash mismatch: ' + corrupted):
                        image.check_fit(fit(hash_algorithms=('crc32', crypto), corrupt_algorithm=corrupted))
    def test_fit_rejects_crc_only_missing_and_unknown_hashes(self):
        for algorithms in [('crc32',), (), ('crc32', 'sha256', 'md5')]:
            with self.subTest(algorithms=algorithms), self.assertRaises(ValueError):
                image.check_fit(fit(hash_algorithms=algorithms))
    def test_metadata_isolation(self):
        source={'supported_devices':[image.BOARD], 'version':{'revision':'fixture'}}
        meta=pack.factory_metadata(source, '0'*64)
        self.assertEqual(meta['supported_devices'], [pack.VENDOR_BOARD]); self.assertEqual(meta['up_model'],'N60PRO')
        source['supported_devices']=['netcore,n60-pro']
        with self.assertRaises(ValueError): pack.factory_metadata(source,'0'*64)
    def test_tar_roundtrip_and_wrong_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.bin'; data=payload(); pack.write_tar(p,data)
            self.assertEqual(image.read_payload(p),data)
            data['CONTROL']=b'BOARD=netcore_n60-pro\n'; pack.write_tar(p,data)
            with self.assertRaises(ValueError): image.read_payload(p)
    def test_extra_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.bin'; pack.write_tar(p,payload())
            with tarfile.open(p,'a') as tar:
                item=tarfile.TarInfo('../outside'); item.size=1; tar.addfile(item,io.BytesIO(b'x'))
            with self.assertRaises(ValueError): image.read_payload(p)

class RuntimeTests(unittest.TestCase):
    def test_overlay_creation_reuse_and_rejections(self):
        for free, existing, context, active, create, expected in [(83,0,0,0,0,0),(82,0,0,0,0,1),(83,0,1,0,0,1),(83,0,0,1,0,1),(83,0,0,0,1,1),(0,1,0,0,0,0)]:
            script=HELPER+f'''
existing={existing}
hkc_slot1_context() {{ HKC_UBI=ubi0; HKC_FREE={free}; return {context}; }}
hkc_slot1_active_root() {{ return {active}; }}
hkc_slot1_volume() {{ [ "$existing" = 1 ] && echo ubi0_7; }}
hkc_slot1_read() {{ echo 67; }}
ubimkvol() {{ echo "CREATE $*"; existing=1; return {create}; }}
sync() {{ :; }}
hkc_slot1_overlay || exit 1
hkc_slot1_overlay
'''
            result=run(script)
            with self.subTest(free=free,existing=existing,context=context,active=active,create=create):
                self.assertEqual(result.returncode,expected,result.stderr)
                self.assertLessEqual(result.stdout.count('CREATE'),1)
                if 'CREATE' in result.stdout: self.assertIn('-N hkc_data -s 8388608',result.stdout)
    def test_writer_success_and_each_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); archive=folder/'image.tar'; pack.write_tar(archive,payload())
            for fail in ['0', *map(str,range(1,12)), 'space','root-hash','kernel-hash','restore']:
                (folder/'counter').write_text('0'); (folder/'trace').write_text('')
                backup=folder/'backup.tgz'
                if fail=='restore': backup.write_bytes(b'fixture')
                elif backup.exists(): backup.unlink()
                script=HELPER.replace('/tmp/sysupgrade.tgz',str(backup).replace('\\','/'))+f'''
cd {q(folder)} || exit 99
FAIL={q(fail)}
hkc_slot1_context() {{ HKC_UBI=ubi0; HKC_FREE=500; HKC_LEB=126976; }}
hkc_slot1_capacity() {{ [ "$FAIL" != space ]; }}
hkc_slot1_volume() {{ case "$1" in rootfs2) echo ubi0_5;; kernel2) echo ubi0_6;; hkc_data) echo ubi0_7;; *) return 1;; esac; }}
identify_tar() {{ case "$2" in */kernel) echo fit;; */root) echo squashfs;; esac; }}
step() {{ local n=$(cat counter); n=$((n+1)); echo "$n" >counter; echo "$*" >>trace; [ "$FAIL" != "$n" ]; }}
nand_remove_ubiblock() {{ step BLOCK "$@"; }}
ubirmvol() {{ step REMOVE "$@"; }}
ubimkvol() {{ step CREATE "$@"; }}
ubiupdatevol() {{ step WRITE "$@" || return 1; cat >"${{1##*/}}"; }}
head() {{ case "$3" in /dev/ubi0_5) [ "$FAIL" != root-hash ] || {{ echo corrupt; return; }};; /dev/ubi0_6) [ "$FAIL" != kernel-hash ] || {{ echo corrupt; return; }};; esac; command head -c "$2" "${{3##*/}}"; }}
hkc_slot1_restore() {{ echo RESTORE >>trace; [ "$FAIL" != restore ]; }}
sync() {{ :; }}
hkc_slot1_write {q(archive)}
'''
                result=run(script); trace=(folder/'trace').read_text()
                with self.subTest(fail=fail):
                    self.assertEqual(result.returncode,0 if fail=='0' else 1,result.stderr+trace)
                    for line in trace.splitlines():
                        if line.startswith(('REMOVE','CREATE')): self.assertIn(line.split()[3],['kernel2','rootfs2','hkc_data'])
                    if fail=='space': self.assertEqual(trace,'')
                    if fail=='root-hash': self.assertNotIn('WRITE /dev/ubi0_6',trace)
    def test_restore_failure_propagation(self):
        for fail in ['none','mkdir','mount','cp','umount','rmdir']:
            script=HELPER+f'''
FAIL={q(fail)}
hkc_slot1_volume() {{ [ "$1" = hkc_data ] && echo ubi0_7; }}
mkdir() {{ echo MKDIR; [ "$FAIL" != mkdir ]; }}
mount() {{ echo "MOUNT $*"; [ "$FAIL" != mount ]; }}
cp() {{ echo "COPY $*"; [ "$FAIL" != cp ]; }}
umount() {{ echo UMOUNT; [ "$FAIL" != umount ]; }}
rmdir() {{ echo RMDIR; [ "$FAIL" != rmdir ]; }}
sync() {{ :; }}
hkc_slot1_restore /fixture-backup
'''
            result=run(script)
            with self.subTest(fail=fail):
                self.assertEqual(result.returncode,0 if fail=='none' else 1,result.stderr)
                if 'MOUNT ' in result.stdout: self.assertIn('/dev/ubi0_7 /tmp/hkc-new-root',result.stdout)
                if fail=='mount': self.assertNotIn('COPY',result.stdout)
                if fail=='cp': self.assertIn('UMOUNT',result.stdout)
    def test_wifi_mac_route_matches_stable(self):
        source=(ROOT/'target/linux/mediatek/filogic/base-files/etc/hotplug.d/ieee80211/11_fix_wifi_mac').read_text()
        source=source.replace('. /lib/functions.sh',':').replace('. /lib/functions/system.sh',':')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'macaddress'
            source=source.replace('/sys${DEVPATH}/macaddress', q(out))
            for board in [image.BOARD,'netcore,n60-pro']:
                for phy in [0,1]:
                    out.write_text('unchanged')
                    script=f'''ACTION=add
DEVPATH=/fixture/phy{phy}
board_name() {{ echo {q(board)}; }}
get_mac_label() {{ echo 00:11:22:33:44:55; }}
macaddr_setbit_la() {{ echo 02:11:22:33:44:55; }}
'''+source
                    run(script)
                    self.assertEqual(out.read_text().strip(),'02:11:22:33:44:55' if phy==1 else 'unchanged')
    def test_preinit_isolation(self):
        source=(ROOT/'target/linux/mediatek/filogic/base-files/lib/preinit/79_hkc_stock_overlay').read_text()
        # Replace only source statements; mocked helpers cannot access the machine.
        source=source.replace('. /lib/upgrade/hkc-n60pro-slot1.sh',':').replace('. /lib/upgrade/nand.sh',':')
        for initramfs,board,expected in [(1,image.BOARD,''),(0,'netcore,n60-pro',''),(0,'xiaomi,redmi-router-ax6000',''),(0,image.BOARD,'OVERLAY')]:
            script='boot_hook_add() { :; }\n'+source+f'''
INITRAMFS={initramfs}
hkc_slot1_board() {{ echo {q(board)}; }}
hkc_slot1_overlay() {{ echo OVERLAY; }}
hkc_stock_overlay_preinit
'''
            result=run(script); self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(result.stdout.strip(),expected)
    def test_actual_capacity_boundary(self):
        for free, expected in [(0,1),(83,0)]:
            result=run(HELPER+f'''
HKC_FREE={free}; HKC_LEB=126976; HKC_KERNEL_SIZE=126976; HKC_ROOT_SIZE=126976
hkc_slot1_volume() {{ echo ubi0_5; }}
hkc_slot1_read() {{ echo 1; }}
hkc_slot1_capacity
''')
            self.assertEqual(result.returncode,expected,result.stderr)
    def test_actual_context_and_active_root_with_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            def put(name,value):
                p=folder/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(value if isinstance(value,bytes) else str(value).encode())
            put('proc/device-tree/compatible',string(image.BOARD)+string('mediatek,mt7986a'))
            for i,(label,(offset,size)) in enumerate(image.LAYOUT.items()):
                for key,value in [('name',label),('offset',offset),('size',size)]: put(f'sys/class/mtd/mtd{i}/{key}',value)
            for key,value in [('mtd_num',4),('ro_mode',0),('eraseblock_size',126976),('avail_eraseblocks',100),('reserved_for_bad',19)]: put('sys/class/ubi/ubi0/'+key,value)
            put('sys/class/block/ubiblock0_6/dev','254:6')
            put('proc/self/mountinfo','1 0 254:6 / /rom ro - squashfs /dev/root ro\n')
            source=HELPER.replace('/sys/',folder.as_posix()+'/sys/').replace('/proc/',folder.as_posix()+'/proc/')
            script=source+'\nnand_find_ubi() { echo ubi0; }\nhkc_slot1_volume() { echo ubi0_6; }\nhkc_slot1_context && hkc_slot1_active_root\n'
            self.assertEqual(run(script).returncode,0)
            for path,bad in [('sys/class/mtd/mtd4/offset','1'),('sys/class/ubi/ubi0/reserved_for_bad','17'),('sys/class/block/ubiblock0_6/dev','254:2'),('proc/device-tree/compatible',string('netcore,n60-pro'))]:
                old=(folder/path).read_bytes(); put(path,bad)
                with self.subTest(path=path): self.assertNotEqual(run(script).returncode,0)
                put(path,old)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--shell',default=SHELL); args=ap.parse_args(); SHELL=args.shell
    if not unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))).wasSuccessful(): raise SystemExit(1)
    print('PASS offline fixtures and fault injection only; no flash tools or router access')
