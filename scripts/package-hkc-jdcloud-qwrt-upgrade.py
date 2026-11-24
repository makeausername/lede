#!/usr/bin/env python3
"""Build a PRIVATE, offline-only QWRT sysupgrade container. Never a flash tool."""
import argparse,gzip,hashlib,io,json,struct,subprocess,tarfile,zlib
from pathlib import Path
from hkc_jdcloud_fdt import fdt

KERNEL_SHA='0ca88f17c3ee8194ad0591425a927ab5e90f363b64f86f879271b058ee8247f8'
ROOT_SHA='bc7a6738004af7d3bf935249a28f7863658d7548bb5c70741d0a9756d0147724'
FWTOOL_SHA='3a38e2ac5fb4e515c2b662bd54e655f78215b8daacf647b6c7fbb97ed47173b9'
BOARD='jdcloud,ax1800-pro'; DIRECTORY='sysupgrade-jdcloud-ax1800-pro'
def need(ok,message):
    if not ok:raise ValueError(message)
def sha(data):return hashlib.sha256(data).hexdigest()
def metadata_info(data):
    # fwtool checks the CRC before decoding the trailer length. Validate both
    # independently; a successful extraction alone does not imply valid JSON.
    need(len(data)>=24,'metadata trailer missing')
    magic,crc,kind,padding,size=struct.unpack('>IIB3sI',data[-16:])
    need(magic==0x46577830 and kind==1 and padding==bytes(3),'metadata trailer type/magic')
    need(24<size<=30*1024+24 and size<=len(data),'metadata trailer length')
    need(crc==(zlib.crc32(data[:-16])^0xffffffff),'metadata CRC mismatch')
    start=len(data)-size
    need(start>0 and start%10240==0,'unexpected tar/metadata boundary')
    need(data[start:start+8]==bytes(8),'unsupported metadata header')
    meta=json.loads(data[start+8:-16])
    need(meta.get('metadata_version')=='1.1' and meta.get('compat_version')=='1.0' and meta.get('supported_devices')==[BOARD],'metadata board/version mismatch')
    return meta
def kernel_info(kernel):
    need(len(kernel)==6291456 and sha(kernel)==KERNEL_SHA,'original kernel partition mismatch')
    nodes=fdt(kernel);components={}
    for path in ['/images/kernel@1','/images/fdt@1']:
        data=nodes[path]['data'];checked=set()
        for name,props in nodes.items():
            if name.startswith(path+'/hash'):
                algo=props['algo'].rstrip(b'\0').decode();need(algo in ['crc32','sha1'],'unknown FIT hash')
                digest=struct.pack('>I',zlib.crc32(data)) if algo=='crc32' else hashlib.sha1(data).digest()
                need(digest==props['value'],'FIT component checksum failed');checked.add(algo)
        need(checked=={'crc32','sha1'},'FIT hash coverage incomplete')
        components[path]={'sha256':sha(data),'bytes':len(data),'hashes':sorted(checked)}
    image=gzip.decompress(nodes['/images/kernel@1']['data'])
    start=image.index(b'IKCFG_ST')+8;end=image.index(b'IKCFG_ED',start)
    config=gzip.decompress(image[start:end]).decode()
    for option in ['SQUASHFS','SQUASHFS_XZ','BLK_DEV_LOOP','EXT4_FS','OVERLAY_FS']:
        need('CONFIG_'+option+'=y\n' in config,'missing kernel feature: '+option)
    dt=fdt(nodes['/images/fdt@1']['data'])
    need(dt['/']['compatible'].split(b'\0')[0]==BOARD.encode(),'kernel board mismatch')
    return {'kernel_partition_sha256':sha(kernel),'image_sha256':sha(image),'config_sha256':sha(config.encode()),'components':components}
def root_info(root):
    need(len(root)>=96 and root[:4]==b'hsqs','not SquashFS')
    block=struct.unpack_from('<I',root,12)[0];compressor=struct.unpack_from('<H',root,20)[0]
    version=struct.unpack_from('<HH',root,28);used=struct.unpack_from('<Q',root,40)[0]
    need(version==(4,0) and compressor==4 and block==262144,'unqualified SquashFS format')
    need(96<=used<=len(root) and len(root)==(used+65535)//65536*65536,'overlay boundary/alignment mismatch')
    need(not any(root[used:]),'nonzero padding')
    need(struct.unpack_from('<Q',root,56)[0]==0xffffffffffffffff,'unqualified xattrs')
    need(len(root)+32*1024*1024<314572800,'insufficient root partition/overlay space')
    return {'bytes':len(root),'bytes_used':used,'sha256':sha(root),'overlay_offset':len(root),'overlay_available':314572800-len(root)}
def check_tar(path,kernel,root):
    expected=[DIRECTORY,DIRECTORY+'/CONTROL',DIRECTORY+'/kernel',DIRECTORY+'/root']
    with tarfile.open(path) as tf:
        members=tf.getmembers();need([m.name.rstrip('/') for m in members]==expected,'archive entries/order mismatch')
        need(members[0].isdir(),'missing first board directory')
        need(all(m.isfile() for m in members[1:]),'unexpected archive member type')
        need(all(m.uid==0 and m.gid==0 and not m.pax_headers for m in members),'unqualified archive metadata')
        need(tf.extractfile(members[1]).read()==b'BOARD=jdcloud-ax1800-pro\n','CONTROL mismatch')
        need(tf.extractfile(members[2]).read()==kernel,'kernel extraction mismatch')
        need(tf.extractfile(members[3]).read()==root,'root extraction mismatch')
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ['kernel','package-dir','fwtool','output']:ap.add_argument('--'+name,type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();need(not out.exists(),'fresh output required')
    for src in [args.kernel,args.package_dir,args.fwtool]:need(not out.is_relative_to(src.resolve()) and not src.resolve().is_relative_to(out),'input/output overlap')
    kernel=args.kernel.read_bytes();ki=kernel_info(kernel)
    root=(args.package_dir/'PRIVATE-NOT-FIRMWARE-hkc-qwrt-rootfs.squashfs').read_bytes();ri=root_info(root)
    need(sha(root)==ROOT_SHA,'unqualified rootfs input')
    report=json.loads((args.package_dir/'PACKAGING-VERIFICATION.json').read_bytes())
    need(report['passed'] and report['rootfs_sha256']==sha(root) and report['accepted_runtime_hashes']==12,'rootfs qualification mismatch')
    need(sha(args.fwtool.read_bytes())==FWTOOL_SHA,'fwtool mismatch')
    out.mkdir(parents=True);image=out/'PRIVATE-OFFLINE-ONLY-QWRT-HKC-sysupgrade.bin'
    with tarfile.open(image,'w',format=tarfile.USTAR_FORMAT) as tf:
        for name,payload in [(DIRECTORY,None),(DIRECTORY+'/CONTROL',b'BOARD=jdcloud-ax1800-pro\n'),(DIRECTORY+'/kernel',kernel),(DIRECTORY+'/root',root)]:
            m=tarfile.TarInfo(name);m.mtime=1738846613;m.mode=0o755 if payload is None else 0o644
            if payload is None:m.type=tarfile.DIRTYPE
            else:m.size=len(payload)
            tf.addfile(m,io.BytesIO(payload) if payload is not None else None)
    metadata={'metadata_version':'1.1','compat_version':'1.0','supported_devices':[BOARD],
              'version':{'dist':'QWRT-HKC-offline-research','version':'NOT-FOR-INSTALLATION','revision':'original-r47727-userspace-candidate','target':'ipq60xx/generic','board':'jdcloud-ax1800-pro'}}
    meta=out/'metadata.json';meta.write_text(json.dumps(metadata,sort_keys=True)+'\n',encoding='utf-8')
    subprocess.run([str(args.fwtool),'-I',str(meta),str(image)],check=True)
    extracted=out/'extracted-metadata.json';subprocess.run([str(args.fwtool),'-i',str(extracted),str(image)],check=True)
    need(json.loads(extracted.read_bytes())==metadata==metadata_info(image.read_bytes()),'metadata roundtrip mismatch');check_tar(image,kernel,root)
    result={'passed':True,'release_ready':False,'board':BOARD,'kernel':ki,'rootfs':ri,'image':image.name,'sha256':sha(image.read_bytes()),'bytes':image.stat().st_size,
            'metadata':metadata,'writes_expected':['0:HLOS','rootfs (including embedded ext4 overlay)'],
            'no_gpt_bootloader_art_payload':True,'original_kernel_unchanged':True,'hardware_boot_tested':False,
            'release_blockers':['Factory LAN generation remains original 192.168.1.1; required 192.168.2.1 fresh-reset behavior not qualified',
                                'Private original rootfs; credential/config sanitization and backup policy not release-qualified',
                                'Physical NSS/Wi-Fi boot, actual upgrade and recovery not tested'],
            'not_an_uboot_recovery_image':True}
    (out/'UPGRADE-VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'sha256':result['sha256'],'bytes':result['bytes'],'release_ready':False}))
if __name__=='__main__':main()
