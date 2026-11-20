#!/usr/bin/env python3
"""Offline JDCloud image verification; no router access and no flash operation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tarfile
import tempfile
import zlib
from hkc_jdcloud_fdt import fdt

ROOT = Path(__file__).resolve().parents[1]
BOARD = 'jdcloud,re-ss-01'
LEGACY = 'jdcloud,ax1800-pro'
PROFILE = 'jdcloud_re-ss-01'
KERNEL_LIMIT = 6291456
ROOT_LIMIT = 297795584  # 300 MiB partition less 16 MiB for the overlay.

def need(ok, message):
    if not ok: raise ValueError(message)

def txt(value): return value.rstrip(b'\0').decode()
def number(value): return int.from_bytes(value, 'big')

def check_sizes(kernel, root):
    need(0 < kernel <= KERNEL_LIMIT, 'kernel exceeds audited 6 MiB HLOS')
    need(65536 <= root <= ROOT_LIMIT and root % 65536 == 0, 'root capacity/alignment invalid')

def payload(path):
    need(path.stat().st_size <= KERNEL_LIMIT + ROOT_LIMIT + 1024*1024, 'oversized archive')
    with tarfile.open(path, 'r:') as tf:
        prefix='sysupgrade-'+PROFILE
        members=tf.getmembers()
        expected={prefix,prefix+'/CONTROL',prefix+'/kernel',prefix+'/root'}
        need(len(members)==4 and {m.name.rstrip('/') for m in members}==expected, 'unexpected/duplicate archive members')
        data={}
        for m in members:
            if m.name.rstrip('/')==prefix:
                need(m.isdir(), 'archive prefix not directory'); continue
            need(m.isfile() and not m.pax_headers, 'nonregular/PAX image member')
            limit=4096 if m.name.endswith('/CONTROL') else KERNEL_LIMIT if m.name.endswith('/kernel') else ROOT_LIMIT
            need(0 < m.size <= limit, 'oversized member')
            data[m.name.rsplit('/',1)[1]]=tf.extractfile(m).read()
    need(data['CONTROL']==b'BOARD=jdcloud_re-ss-01\n', 'wrong CONTROL')
    check_sizes(len(data['kernel']),len(data['root']))
    need(data['root'][:4]==b'hsqs', 'root is not SquashFS')
    used=struct.unpack_from('<Q',data['root'],40)[0]
    need(96 <= used <= len(data['root']) and len(data['root'])-used <65536, 'invalid SquashFS bytes_used/padding')
    return data

def check_dtb(data):
    nodes=fdt(data)
    need(nodes['/']['compatible'].split(b'\0')[:-1]==[BOARD.encode(),b'qcom,ipq6018'], 'wrong DTB board')
    memory=[v for p,v in nodes.items() if p.count('/')==1 and v.get('device_type')==b'memory\0']
    need(len(memory)==1 and memory[0]['reg']==struct.pack('>4I',0,0x40000000,0,0x40000000), 'not audited 1GiB memory')
    aliases=nodes['/aliases']
    for i,label in enumerate(('lan1','lan2','lan3','wan'),1):
        path=txt(aliases['ethernet'+str(i)])
        props=nodes[path]
        need(props.get('label')==label.encode()+b'\0' and props.get('status')==b'okay\0', 'port mapping differs: '+label)
        ph=props['phy-handle']
        phy=[v for v in nodes.values() if v.get('phandle')==ph]
        need(len(phy)==1 and number(phy[0]['reg'])==i, 'PHY mapping differs: '+label)
    wifi=[v for v in nodes.values() if v.get('qcom,ath11k-calibration-variant')==b'JDC-RE-SS-01\0']
    need(len(wifi)==1 and wifi[0].get('status')==b'okay\0', 'WiFi calibration variant missing')
    nss=[v for p,v in nodes.items() if p.startswith('/reserved-memory/') and v.get('reg')==struct.pack('>4I',0,0x40000000,0,0x1000000)]
    need(len(nss)==1 and 'no-map' in nss[0], 'NSS reserved memory missing')
    need(any(b'qcom,nss\0' in v.get('compatible',b'') for v in nodes.values()), 'NSS hardware description missing')
    need(any(v.get('bus-width')==struct.pack('>I',8) and v.get('status')==b'okay\0' and 'non-removable' in v for v in nodes.values()), 'eMMC controller missing')
    return {'memory_bytes':1073741824,'ports':['lan1/phy1','lan2/phy2','lan3/phy3','wan/phy4'],'calibration':'JDC-RE-SS-01'}

def check_fit(kernel):
    nodes=fdt(kernel)
    need(txt(nodes['/configurations']['default'])=='config@cp03-c2', 'bootipq FIT config mismatch')
    config=nodes['/configurations/config@cp03-c2']
    k=nodes['/images/'+txt(config['kernel'])]; dt=nodes['/images/'+txt(config['fdt'])]
    need(k['arch']==b'arm64\0' and k['compression']==b'gzip\0', 'wrong kernel architecture/compression')
    need(number(k['load'])==number(k['entry'])==0x41000000, 'kernel boot address mismatch')
    # Bound decompression so malformed input cannot allocate arbitrary memory.
    dec=zlib.decompressobj(31);raw=dec.decompress(k['data'],64*1024*1024)
    need(dec.eof and not dec.unused_data and raw[56:60]==b'ARM\x64', 'invalid ARM64 gzip payload')
    need(struct.unpack_from('<Q',raw,8)[0]==0, 'unexpected kernel text_offset')
    for path,v in nodes.items():
        if path.startswith('/images/') and 'data' in v:
            hashes=[h for n,h in nodes.items() if n.startswith(path+'/hash')]
            need(any(txt(h['algo']) in ('sha1','sha256') for h in hashes), 'cryptographic FIT hash missing')
            for h in hashes:
                alg=txt(h['algo']);need(alg in ('sha1','sha256','crc32'),'unsupported FIT hash')
                actual=struct.pack('>I',zlib.crc32(v['data'])&0xffffffff) if alg=='crc32' else hashlib.new(alg,v['data']).digest()
                need(actual==h['value'], 'FIT payload hash mismatch')
    need(dt.get('compression')==b'none\0','compressed DTB unsupported')
    return check_dtb(dt['data'])

def check_metadata(meta):
    need(set(meta['supported_devices'])=={BOARD,LEGACY} and len(meta['supported_devices'])==2, 'metadata board identities differ')
    need(meta.get('compat_version','1.0')=='1.0','old QWRT metadata compatibility lost')
    need(meta['version']['target']=='qualcommax/ipq60xx','wrong target')
    need(meta['version']['board']==PROFILE,'wrong profile')

def check_root(data, tool):
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'root';path.write_bytes(data)
        def cat(name):return subprocess.check_output([str(tool),'-cat',str(path),name])
        count=0
        for line in (ROOT/'custom/hkc-stability-runtime.sha256').read_text().splitlines():
            if not line or line.startswith('#'):continue
            digest,name=line.split(None,1)
            need(hashlib.sha256(cat(name)).hexdigest()==digest,'accepted runtime differs: '+name);count+=1
        need(count==12,'runtime contract changed')
        for name,source in {
            'lib/upgrade/hkc-jdcloud.sh':'target/linux/qualcommax/ipq60xx/base-files/lib/upgrade/hkc-jdcloud.sh',
            'lib/upgrade/platform.sh':'target/linux/qualcommax/ipq60xx/base-files/lib/upgrade/platform.sh',
            'etc/board.d/02_network':'target/linux/qualcommax/ipq60xx/base-files/etc/board.d/02_network',
            'etc/uci-defaults/30_uboot-envtools':'package/boot/uboot-envtools/files/qualcommax',
            'etc/uci-defaults/zz-hkc-lan-ipv4-only':'custom/hkc-lan-ipv4-only.sh',
            'lib/preinit/81_fix_eeprom':'target/linux/qualcommax/ipq60xx/base-files/lib/preinit/81_fix_eeprom',
            'etc/hotplug.d/firmware/11-ath11k-caldata':'target/linux/qualcommax/ipq60xx/base-files/etc/hotplug.d/firmware/11-ath11k-caldata',
        }.items():
            need(cat(name)==(ROOT/source).read_bytes().replace(b'\r\n',b'\n'),'image helper differs: '+name)
        config=cat('etc/preinit')+cat('lib/preinit/00_preinit.conf')
        need(b'192.168.2.1' in config,'default management address missing')
        for name in ['usr/bin/xray','usr/libexec/mihomo','usr/bin/naive','usr/bin/shadow-tls','usr/bin/sslocal']:
            binary=cat(name)
            need(binary[:5]==b'\x7fELF\x02' and int.from_bytes(binary[18:20],'little')==183,'wrong/missing AArch64 client: '+name)
        return count

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image',type=Path,required=True);ap.add_argument('--fwtool',type=Path,required=True)
    ap.add_argument('--unsquashfs',required=True);ap.add_argument('--commit',required=True);ap.add_argument('--report',type=Path,required=True)
    args=ap.parse_args();need(re.fullmatch('[0-9a-f]{40}',args.commit),'full source commit required')
    with tempfile.TemporaryDirectory() as tmp:
        m=Path(tmp)/'metadata';subprocess.run([str(args.fwtool),'-i',str(m),str(args.image)],check=True,capture_output=True)
        meta=json.loads(m.read_text());check_metadata(meta)
    data=payload(args.image);hardware=check_fit(data['kernel']);count=check_root(data['root'],args.unsquashfs)
    report={'source_commit':args.commit,'image':args.image.name,'sha256':hashlib.sha256(args.image.read_bytes()).hexdigest(),'metadata':meta,'payload_bytes':{k:len(data[k]) for k in ['kernel','root']},'hardware':hardware,'verified_runtime_files':count,'offline_verification_passed':True,'device_upgrade_tested':False,'boot_tested':False,'production_ready':False,'limitations':['Current QWRT migration must not preserve old full configuration.','Router sysupgrade -T, real boot, wireless/NSS/proxy behavior and recovery remain untested.','No bootloader, GPT or data partition should be changed.']}
    with args.report.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
