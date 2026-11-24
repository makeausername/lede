from pathlib import Path
import tarfile,stat,struct,gzip,subprocess,json,hashlib,argparse
ap=argparse.ArgumentParser(description="Original unmodified QWRT kernel, RAM-only mount/upgrade simulation; NEVER a device installer")
for name in ['package-dir','image','kernel-image','qemu','output']:ap.add_argument('--'+name,type=Path,required=True)
a=ap.parse_args();out=a.output.resolve();repo=Path(__file__).resolve().parents[1]
if out.exists():raise ValueError('Fresh output required')
for src in [a.package_dir,a.image,a.kernel_image,a.qemu]:
    if out.is_relative_to(src.resolve()) or src.resolve().is_relative_to(out):raise ValueError('Input/output overlap')
pins={a.qemu:'f4ccb59031c56e5f5e8beb1c4f247db4ccfcd1b70f7c75a8cf7f01f0db027efd',
      a.kernel_image:'674c7e455e1a88c737fd757839d834db1ae3b424e0a13913136901071c519002',
      a.package_dir/'PRIVATE-original-metadata.tar':'b1f57e52f988cb66ab2c026e02d4a98c17799ab5056337f54c89f3810f99b589',
      a.package_dir/'PRIVATE-roundtrip.tar':'05984f1d74ace10512f5bfe13f0fb5a093d4819fbdd90717faeedbf06f4ba0e5',
      a.package_dir/'PRIVATE-NOT-FIRMWARE-hkc-qwrt-rootfs.squashfs':'bc7a6738004af7d3bf935249a28f7863658d7548bb5c70741d0a9756d0147724',
      a.image:'37fe5a7e39bc06b2641fe0a5d4e54e96918aac5b0d26cd173d5a1ecd4169265a'}
for path,digest in pins.items():
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Unqualified input: '+path.name)
out.mkdir(parents=True)
entries={}
def put(n,d,m=0o100644,rmajor=0,rminor=0):
    entries[n]=(d,m,rmajor,rminor)
    for p in Path(n).parents:
        if p.as_posix()!='.':entries.setdefault(p.as_posix(),(b'',0o40755,0,0))
with tarfile.open(a.package_dir/'PRIVATE-original-metadata.tar') as t:
    for m in t:
        n=m.name.removeprefix('./')
        if n in ['bin/busybox','usr/sbin/losetup','usr/sbin/mke2fs','usr/bin/fwtool','usr/bin/jshn','lib/upgrade/fwtool.sh','lib/upgrade/mmc.sh','lib/upgrade/platform.sh','lib/functions.sh','lib/config/uci.sh','usr/share/libubox/jshn.sh'] or n.startswith(('lib/','usr/lib/')) and '.so' in Path(n).name and not n.startswith(('lib/modules/','lib/firmware/')):
            if m.isfile():put(n,t.extractfile(m).read(),stat.S_IFREG|m.mode)
            elif m.issym():put(n,m.linkname.encode(),0o120777)
# Tiny static AArch64 ELF: SYS_WRITE0(argv[1]); Linux exit(0). No file APIs.
code=struct.pack('<6I',0xf9400be1,0xd2800080,0xd45e0000,0xd2800000,0xd2800ba8,0xd4000001)
elf=b'\x7fELF'+bytes([2,1,1,0])+bytes(8)+struct.pack('<HHIQQQIHHHHHH',2,183,1,0x400078,64,0,0,64,56,1,0,0,0)
elf+=struct.pack('<IIQQQQQQ',1,5,0,0x400000,0x400000,120+len(code),120+len(code),0x1000)+code
put('semi',elf,0o100755)
for app in ['sh','ash','mount','mkdir','cat','sha256sum','uname','poweroff','echo','sleep','umount','tar','grep','wc','dd','cut','cmp','sync','rm','rmdir','cp']:
    put('bin/'+app,b'busybox',0o120777)
for d in ['proc','sys','dev','tmp','mnt']:put(d,b'',0o40755)
for n,mode,major,minor in [('console',0o20600,5,1),('null',0o20666,1,3),('loop0',0o60600,7,0),('loop-control',0o20600,10,237)]:put('dev/'+n,b'',mode,major,minor)
root=a.package_dir/'PRIVATE-NOT-FIRMWARE-hkc-qwrt-rootfs.squashfs'
put('candidate.squashfs',root.read_bytes())
with tarfile.open(a.package_dir/'PRIVATE-roundtrip.tar') as tf:
    hashes=[]
    for member in tf:
        if member.isfile():
            name=member.name.removeprefix('./')
            assert not any(c in name for c in ['\n','\r','\\'])
            hashes.append(hashlib.sha256(tf.extractfile(member).read()).hexdigest()+'  '+name)
put('expected.sha256',('\n'.join(hashes)+'\n').encode())
for n,major,minor in [('zero',1,5),('loop6',7,6),('loop7',7,7)]:put('dev/'+n,b'',0o20666 if n=='zero' else 0o60600,major,minor)
put('usr/sbin/mkfs.ext4',b'mke2fs',0o120777)
put('etc/mtab',b'/proc/mounts',0o120777)
put('candidate.bin',a.image.read_bytes())
test=(repo/'custom/jdcloud-qwrt/runtime-fixtures/test-upgrade.sh').read_bytes()
env=('export KERNEL_SHA=0ca88f17c3ee8194ad0591425a927ab5e90f363b64f86f879271b058ee8247f8 ROOT_SHA='+hashlib.sha256(root.read_bytes()).hexdigest()+' ROOT_BYTES='+str(root.stat().st_size)+' ROOT_BLOCKS='+str(root.stat().st_size//65536)+'\n').encode()
put('init',test.replace(b'export PATH=',env+b'export PATH=',1),0o100755)
data=bytearray()
for ino,(n,(d,m,major,minor)) in enumerate(sorted(entries.items()),1):
    name=n.encode()+b'\0';fields=[ino,m,0,0,2 if stat.S_ISDIR(m) else 1,0,len(d),0,0,major,minor,len(name),0]
    data.extend(b'070701'+b''.join(f'{x:08x}'.encode() for x in fields)+name);data.extend(b'\0'*(-len(data)%4));data.extend(d);data.extend(b'\0'*(-len(data)%4))
name=b'TRAILER!!!\0';data.extend(b'070701'+b''.join(f'{x:08x}'.encode() for x in [0,0,0,0,1,0,0,0,0,0,0,len(name),0])+name);data.extend(b'\0'*(-len(data)%4))
cpio=out/'PRIVATE-kernel-mount-test.cpio.gz';cpio.write_bytes(gzip.compress(data,compresslevel=1,mtime=0))
args=[str(a.qemu),'-M','virt,gic-version=2','-cpu','cortex-a53','-m','1536','-smp','2','-accel','tcg','-nic','none','-display','none','-serial','none','-monitor','none','-no-reboot','-semihosting-config','enable=on,target=native,userspace=on','-kernel',str(a.kernel_image),'-initrd',str(cpio),'-append','rdinit=/init panic=-1']
with (out/'original-kernel-mount.log').open('wb') as f:
    try:r=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT,timeout=600);print('exit',r.returncode)
    except subprocess.TimeoutExpired:print('bounded probe timed out')
print((out/'original-kernel-mount.log').read_text(errors='replace')[-5000:])

log=(out/'original-kernel-mount.log').read_text(errors='replace')
markers=['Linux (none) 5.4.250','FULL_ROOTFS_HASHES_PASS '+str(len(hashes)), 'ORIGINAL_METADATA_AND_PLATFORM_PASS', 'WRONG_BOARD_REJECTED','UPGRADE_RAM_SIMULATION_PASS reset','UPGRADE_RAM_SIMULATION_PASS preserve','QWRT_ORIGINAL_KERNEL_TEST_END']
passed=all(marker in log for marker in markers) and 'FAIL:' not in log
report={'passed':passed,'kernel_version':'5.4.250','unmodified_kernel_image_sha256':pins[a.kernel_image],
        'rootfs_sha256':hashlib.sha256(root.read_bytes()).hexdigest(),'container_sha256':pins[a.image],
        'regular_file_hashes':len(hashes),'input_hashes':{p.name:h for p,h in pins.items()},
        'no_network':True,'no_host_disks_or_shares':True,'guest_ram_only':True,'physical_device_tested':False,
        'simulation_overrides':['board_name/find_mmc_part use synthetic board and RAM-only loop partitions','losetup --detach-all skipped to retain RAM-backed target partitions','global unmount and reboot intercepted'],
        'missing_markers':[m for m in markers if m not in log]}
(out/'ORIGINAL-KERNEL-VERIFICATION.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
if not passed:raise SystemExit('Original-kernel qualification FAILED; inspect offline log')
