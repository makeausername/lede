#!/usr/bin/env python3
"""Isolated source/boot contract tests, including rejection and write-failure tests."""
import gzip, hashlib, importlib.util, io, json, os, shutil, struct, subprocess, tarfile, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('verify',ROOT/'scripts/verify-hkc-jdcloud-image.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
def read(p):return (ROOT/p).read_text(encoding='utf-8')
def blob(nodes):
    strings=bytearray();offsets={};tokens=bytearray()
    def node(name,props,children):
        tokens.extend(struct.pack('>I',1)+name.encode()+b'\0');tokens.extend(b'\0'*(-len(tokens)%4))
        for key,value in props.items():
            if key not in offsets:offsets[key]=len(strings);strings.extend(key.encode()+b'\0')
            tokens.extend(struct.pack('>III',3,len(value),offsets[key])+value);tokens.extend(b'\0'*(-len(tokens)%4))
        for child in children:node(*child)
        tokens.extend(struct.pack('>I',2))
    node(*nodes);tokens.extend(struct.pack('>I',9))
    return struct.pack('>10I',0xd00dfeed,56+len(tokens)+len(strings),56,56+len(tokens),40,17,16,0,len(strings),len(tokens))+bytes(16)+tokens+strings
def dtb(board=v.BOARD,ram=0x40000000,wan_phy=4):
    cell=lambda *n:struct.pack('>'+('I'*len(n)),*n)
    aliases={f'ethernet{i}'.encode().decode():f'/soc@0/dp{i+1}\0'.encode() for i in range(1,5)}
    soc=[]
    for i,label in enumerate(['lan1','lan2','lan3','wan'],1):
        soc.append((f'dp{i+1}',{'label':label.encode()+b'\0','status':b'okay\0','phy-handle':cell(i)},[]))
        soc.append((f'phy@{i}',{'reg':cell(wan_phy if i==4 else i),'phandle':cell(i)},[]))
    soc.extend([('wifi',{'status':b'okay\0','qcom,ath11k-calibration-variant':b'JDC-RE-SS-01\0'},[]),('nss',{'compatible':b'qcom,nss\0'},[]),('sdhc',{'bus-width':cell(8),'status':b'okay\0','non-removable':b''},[])])
    return blob(('',{'compatible':board.encode()+b'\0qcom,ipq6018\0'},[('aliases',aliases,[]),('memory',{'device_type':b'memory\0','reg':cell(0,0x40000000,0,ram)},[]),('reserved-memory',{},[('memory@40000000',{'reg':cell(0,0x40000000,0,0x1000000),'no-map':b''},[])]),('soc@0',{},soc)]))
def fit(dt=None,load=0x41000000):
    raw=bytearray(64);raw[56:60]=b'ARM\x64';kernel=gzip.compress(raw)
    def image(name,data,props):
        return (name,dict(props,data=data),[('hash@1',{'algo':b'sha256\0','value':hashlib.sha256(data).digest()},[])])
    return blob(('',{},[('images',{},[image('kernel@1',kernel,{'arch':b'arm64\0','compression':b'gzip\0','load':struct.pack('>I',load),'entry':struct.pack('>I',load),'type':b'kernel\0'}),image('fdt@1',dt or dtb(),{'compression':b'none\0','type':b'flat_dt\0'})]),('configurations',{'default':b'config@cp03-c2\0'},[('config@cp03-c2',{'kernel':b'kernel@1\0','fdt':b'fdt@1\0'},[])])]))
def root_image():
    data=bytearray(65536);data[:4]=b'hsqs';struct.pack_into('<Q',data,40,96);return bytes(data)
def archive(path,extra=False,link=False):
    with tarfile.open(path,'w',format=tarfile.USTAR_FORMAT) as tf:
        prefix='sysupgrade-jdcloud_re-ss-01'
        d=tarfile.TarInfo(prefix+'/');d.type=tarfile.DIRTYPE;tf.addfile(d)
        for name,data in [('CONTROL',b'BOARD=jdcloud_re-ss-01\n'),('kernel',fit()),('root',root_image())]:
            ti=tarfile.TarInfo(prefix+'/'+name);ti.size=len(data)
            if link and name=='root':ti.type=tarfile.SYMTYPE;ti.linkname='/dev/mmcblk0';ti.size=0;tf.addfile(ti)
            else:tf.addfile(ti,io.BytesIO(data))
        if extra:
            ti=tarfile.TarInfo(prefix+'/kernel');ti.size=1;tf.addfile(ti,io.BytesIO(b'x'))

class Source(unittest.TestCase):
    def test_protected_source_and_software_parity(self):
        contract=json.loads(read('custom/hkc-jdcloud-baseline.json'))
        for p,h in contract['sha256_lf'].items():self.assertEqual(hashlib.sha256(read(p).encode()).hexdigest(),h,p)
        old=read('configs/hkc-n60-pro.config').splitlines();new=read('configs/hkc-jdcloud-ax1800-pro.config').splitlines()
        app=lambda ls:[x for x in ls if x.startswith(('CONFIG_PACKAGE_','# CONFIG_PACKAGE_')) and x!='CONFIG_PACKAGE_kmod-fs-ext4=y']
        self.assertEqual(app(old),app(new))
        self.assertIn('CONFIG_TARGET_PREINIT_IP="192.168.2.1"',new)
    def test_stable_workflow_gates_retained(self):
        old=read('.github/workflows/openwrt-ci.yml');new=read('.github/workflows/hkc-jdcloud-ax1800-pro.yml')
        for a,b in [('      - name: Fetch and pin package feeds','      - name: Generate and validate build configuration')]:
            self.assertEqual(old[old.index(a):old.index(b)],new[new.index(a):new.index(b)])
        a='          inspect_dir="$(mktemp -d)"';b='          sha256sum "$firmware"'
        self.assertEqual(old[old.index(a):old.index(b)],new[new.index(a):new.index(b)])
        self.assertIn('hkc-jdcloud-ax1800-test-*',new);self.assertNotIn('branches:',new)
    def test_target_dts_and_upgrade_contract(self):
        text=read('target/linux/qualcommax/image/ipq60xx.mk');section=text.split('define Device/jdcloud_re-ss-01\n')[1].split('endef')[0]
        for s in ['KERNEL_SIZE := 6144k','IMAGES := sysupgrade.bin','SUPPORTED_DEVICES += jdcloud,ax1800-pro','DEVICE_DTS := ipq6000-re-ss-01-hkc']:self.assertIn(s,section)
        d=read('target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq6000-re-ss-01-hkc.dts')
        self.assertIn('#include "ipq6000-re-ss-01.dts"',d)
        for i in range(1,5):self.assertIn(f'ethernet{i} = &dp{i+1};',d)
        self.assertIn('0x0 0x40000000 0x0 0x40000000',d)
    def test_shell_syntax_and_rejection(self):
        shell=os.environ.get('HKC_TEST_SHELL') or shutil.which('bash') or shutil.which('sh')
        self.assertTrue(shell,'A POSIX shell is required')
        helper=read('target/linux/qualcommax/ipq60xx/base-files/lib/upgrade/hkc-jdcloud.sh')
        platform=read('target/linux/qualcommax/ipq60xx/base-files/lib/upgrade/platform.sh')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'helper.sh').write_text(helper,newline='\n')
            (p/'platform.sh').write_text(platform.replace('. /lib/upgrade/hkc-jdcloud.sh','. ./helper.sh'),newline='\n')
            archive(p/'valid.tar');archive(p/'duplicate.tar',extra=True);archive(p/'link.tar',link=True)
            for f in ['helper.sh','platform.sh']:subprocess.run([shell,'-n',f],cwd=tmp,check=True)
            script='''set -eu
. ./helper.sh
# GNU/MSYS hosts may lack hexdump; this fixture supplies its byte-format operation.
hexdump() { od -An -tx1 | tr -d ' \\n'; }
hkc_jdcloud_archive valid.tar
hkc_jdcloud_sizes 6291456 297795584
for pair in '6291457 65536' '1 297861120' '1 65537' '0 65536' '1 0' 'x 65536'; do
 if hkc_jdcloud_sizes $pair; then exit 11; fi
done
# No raw device functions can run in this fixture environment.
board_name() { echo unrelated,device; }
find_mmc_part() { echo /dev/invalid; }
if hkc_jdcloud_check_image valid.tar; then exit 12; fi
if hkc_jdcloud_do_upgrade valid.tar; then exit 13; fi
if hkc_jdcloud_archive duplicate.tar; then exit 14; fi
if hkc_jdcloud_archive link.tar; then exit 15; fi
# Simulate an incomplete extraction; writer must stop before device I/O.
hkc_jdcloud_check_image() { HKC_KERNEL_BYTES=100; HKC_ROOT_BYTES=65536; return 0; }
dd() { echo UNSAFE_WRITE; exit 99; }
if hkc_jdcloud_do_upgrade valid.tar; then exit 16; fi
# A partial block-device write must return failure; never initialize overlay.
hkc_jdcloud_check_image() { HKC_KERNEL_BYTES=$(tar xOf valid.tar sysupgrade-jdcloud_re-ss-01/kernel | wc -c); HKC_ROOT_BYTES=65536; HKC_KERNEL=/dev/invalid; HKC_ROOT=/dev/invalid; }
losetup() { return 0; }
dd() { return 7; }
mkfs.ext4() { echo UNSAFE_FORMAT; exit 98; }
if hkc_jdcloud_do_upgrade valid.tar; then exit 17; fi
echo PASS_REJECTION_AND_WRITE_FAILURE
'''
            (p/'test.sh').write_text(script,newline='\n')
            result=subprocess.run([shell,'test.sh'],cwd=tmp,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertNotIn('UNSAFE_',result.stdout)
            self.assertIn('PASS_REJECTION',result.stdout)
    def test_partition_geometry_and_fail_closed_route(self):
        shell=os.environ.get('HKC_TEST_SHELL') or shutil.which('bash') or shutil.which('sh')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            helper=read('target/linux/qualcommax/ipq60xx/base-files/lib/upgrade/hkc-jdcloud.sh')
            (p/'helper.sh').write_text(helper,newline='\n')
            platform=read('target/linux/qualcommax/ipq60xx/base-files/lib/upgrade/platform.sh').replace('. /lib/upgrade/hkc-jdcloud.sh', ':')
            (p/'platform.sh').write_text(platform,newline='\n')
            script='''set -eu
. ./helper.sh
board_name() { echo jdcloud,re-ss-01; }
find_mmc_part() { case "$1" in 0:HLOS) echo /dev/mmcblk0p16 ;; rootfs) echo /dev/mmcblk0p17 ;; esac; }
[() { if test "$1" = -b; then return 0; fi; command [ "$@"; }
cat() { case "$1" in */mmcblk0p16/start) echo "$START" ;; */mmcblk0p16/size) echo 12288 ;; */mmcblk0p17/start) echo 28706 ;; */mmcblk0p17/size) echo "$SIZE" ;; *) return 1 ;; esac; }
START=16418; SIZE=614400
hkc_jdcloud_layout
START=16419
if hkc_jdcloud_layout; then exit 21; fi
START=16418; SIZE=614399
if hkc_jdcloud_layout; then exit 22; fi
. ./platform.sh
hkc_jdcloud_check_image() { return 37; }
hkc_jdcloud_do_upgrade() { return 38; }
if platform_check_image invalid; then exit 23; else test "$?" = 37; fi
if ( platform_do_upgrade invalid; echo UNSAFE_COMPLETED; exit 0 ); then exit 24; else test "$?" = 1; fi
echo PASS_GEOMETRY_AND_PROPAGATION
'''
            (p/'geometry.sh').write_text(script,newline='\n')
            r=subprocess.run([shell,'geometry.sh'],cwd=tmp,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertNotIn('UNSAFE_COMPLETED',r.stdout)

class Images(unittest.TestCase):
    def test_valid_fit_and_ports(self):v.check_fit(fit())
    def test_wrong_board(self):
        with self.assertRaises(ValueError):v.check_fit(fit(dtb(board='netcore,n60-pro')))
    def test_wrong_memory(self):
        with self.assertRaises(ValueError):v.check_fit(fit(dtb(ram=0x20000000)))
    def test_swapped_wan_phy(self):
        with self.assertRaises(ValueError):v.check_fit(fit(dtb(wan_phy=1)))
    def test_wrong_load_address(self):
        with self.assertRaises(ValueError):v.check_fit(fit(load=0x48000000))
    def test_truncated_fit(self):
        with self.assertRaises(ValueError):v.check_fit(fit()[:100])
    def test_corrupt_fit_payload(self):
        data=bytearray(fit());index=data.index(b'JDC-RE-SS-01');data[index]=ord('X')
        with self.assertRaises(ValueError):v.check_fit(bytes(data))
    def test_capacity(self):
        v.check_sizes(6291456,297795584)
        for k,r in [(6291457,65536),(0,65536),(1,65537),(1,297861120)]:
            with self.subTest(k=k,r=r),self.assertRaises(ValueError):v.check_sizes(k,r)
    def test_tar_reject_duplicates_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image';archive(path);v.payload(path)
            archive(path,extra=True)
            with self.assertRaises(ValueError):v.payload(path)
            archive(path,link=True)
            with self.assertRaises(ValueError):v.payload(path)
    def test_metadata_exact_compatibility(self):
        meta={'supported_devices':[v.BOARD,v.LEGACY],'version':{'target':'qualcommax/ipq60xx','board':v.PROFILE}}
        v.check_metadata(meta)
        for bad in [dict(meta,supported_devices=[v.BOARD]),dict(meta,compat_version='2.0'),dict(meta,supported_devices=[v.BOARD,v.LEGACY,'generic'])]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):v.check_metadata(bad)

if __name__=='__main__':unittest.main(verbosity=2)
