#!/usr/bin/env python3
"""Offline-only hardening overlay on the exact previously qualified rootfs."""
import argparse,copy,hashlib,importlib.util,io,json,os,subprocess,tarfile
from pathlib import Path
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj
def sha(b):return hashlib.sha256(b).hexdigest()
PIN='05984f1d74ace10512f5bfe13f0fb5a093d4819fbdd90717faeedbf06f4ba0e5'
PAYLOADS={'etc/board.d/99_hkc_lan':('99_hkc_lan',0o755),'lib/upgrade/hkc-image.lua':('hkc-image.lua',0o644),'lib/upgrade/hkc-guard.sh':('hkc-guard.sh',0o644),'lib/upgrade/platform.sh':('platform.sh',0o644)}
def transform(repo,entries,packing):
    old=copy.deepcopy(entries);epoch=1738846613;removed=[]
    key_paths={'etc/easy-rsa/keys/'+n for n in ['01.pem','02.pem','ca.crt','ca.key','client1.crt','client1.csr','client1.key','client1.p12','dh1024.pem','index.txt','index.txt.attr','index.txt.attr.old','index.txt.old','serial','serial.old','server.crt','server.csr','server.key']}
    key_paths|={'etc/openvpn/'+n for n in ['ca.crt','client1.crt','client1.key','dh.pem','server.crt','server.key']}
    for p,(m,data) in list(entries.items()):
        if p in key_paths and m.isfile():
            removed.append(p);del entries[p]
    # Empty host key placeholder is not a usable key; let stock dropbear generate one.
    p='etc/dropbear/dropbear_rsa_host_key'
    if p in entries:
        assert entries[p][1]==b'';removed.append(p);del entries[p]
    def put(p,data,mode=0o644):
        m=copy.copy(entries[p][0]) if p in entries else tarfile.TarInfo(p)
        m.type=tarfile.REGTYPE;m.mode=mode;m.uid=m.gid=0;m.mtime=epoch;m.size=len(data)
        entries[p]=(m,data)
    for target,(source,mode) in PAYLOADS.items():
        data=(repo/'custom/jdcloud-qwrt/hardening'/source).read_bytes();assert b'\r' not in data
        put(target,data,mode)
    # No change to the vendor runner is required: platform_do_upgrade exits on failure.
    owners=packing.owner_map(old);records=packing.package_records(old['usr/lib/opkg/status'][1].decode())
    affected={'hkc-qwrt-integration'}
    for p in removed+list(PAYLOADS):affected.update(owners.get(p,set()))
    for name in sorted(affected):
        prefix='usr/lib/opkg/info/'+name
        control=packing.fields(old[prefix+'.control'][1].decode())
        control['Version'] += '+hkc.safe1'
        paths={packing.path_name(x.lstrip('/')) for x in old[prefix+'.list'][1].decode().splitlines() if x}
        paths-=set(removed)
        if name=='hkc-qwrt-integration':paths|={p for p in PAYLOADS if p not in old}
        control['Installed-Size']=str(sum(len(entries[p][1]) for p in paths if p in entries and entries[p][0].isfile()))
        record=records[name];record.update(Version=control['Version'],Status='install hold installed',**{'Installed-Size':control['Installed-Size']})
        confpath=prefix+'.conffiles'
        if confpath in entries:
            conf=[line for line in entries[confpath][1].decode().splitlines() if line and line.split()[0].lstrip('/') not in removed]
            put(confpath,(''.join(l+'\n' for l in conf)).encode())
            record['Conffiles']='\n'+'\n'.join(' /'+l.split()[0].lstrip('/')+' '+hashlib.md5(entries[l.split()[0].lstrip('/')][1]).hexdigest() for l in conf)
        put(prefix+'.control',packing.encode(control).encode())
        put(prefix+'.list',(''.join('/'+p+'\n' for p in sorted(paths))).encode())
        put(prefix+'.md5sums',(''.join(hashlib.md5(entries[p][1]).hexdigest()+'  '+p+'\n' for p in sorted(paths) if p in entries and entries[p][0].isfile())).encode())
    blocks=[]
    for block in packing.paragraphs(old['usr/lib/opkg/status'][1].decode()):
        name=packing.fields(block)['Package'];blocks.append(packing.encode(records[name]).rstrip('\n') if name in affected else block)
    put('usr/lib/opkg/status',('\n\n'.join(blocks)+'\n\n').encode())
    allowed=set(removed)|set(PAYLOADS)|{'usr/lib/opkg/status'}
    for name in affected:allowed.update('usr/lib/opkg/info/'+name+x for x in ['.control','.list','.md5sums','.conffiles'])
    changed=[];preserved=0
    for p,item in old.items():
        if p not in allowed:assert p in entries and packing.metadata(entries[p])==packing.metadata(item),p;preserved+=1
        elif p not in entries or packing.metadata(entries[p])!=packing.metadata(item):changed.append(p)
    assert set(entries)-set(old)<=allowed
    runtime_count=0
    for line in (repo/'custom/hkc-stability-runtime.sha256').read_text().splitlines():
        if line and not line.startswith('#'):
            digest,p=line.split();assert sha(entries[p][1])==digest,p;runtime_count+=1
    assert runtime_count==12
    # Real PEM blocks in executable files can be parser examples, not credentials.
    # Config-area key material must be absent; never print matching bytes.
    import re
    assert not [p for p,(m,b) in entries.items() if p.startswith('etc/') and re.search(rb'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----',b)]
    return {'removed_generated_key_material':sorted(removed),'changed_existing_paths':sorted(changed),'new_paths':sorted(set(entries)-set(old)),
            'unchanged_inodes':preserved,'packages_changed':sorted(affected),'accepted_runtime_files':12,'total_packages':len(records)}
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ['package-dir','kernel','tools-dir','fwtool','output']:ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args();repo=Path(__file__).resolve().parents[1];out=a.output.resolve()
    assert not out.exists()
    for src in [a.package_dir,a.kernel,a.tools_dir,a.fwtool]:assert not out.is_relative_to(src.resolve()) and not src.resolve().is_relative_to(out)
    packing=module(repo/'scripts/package-hkc-jdcloud-qwrt.py','packing');upgrade=module(repo/'scripts/package-hkc-jdcloud-qwrt-upgrade.py','upgrade')
    src=a.package_dir/'PRIVATE-roundtrip.tar';assert sha(src.read_bytes())==PIN
    kernel=a.kernel.read_bytes();upgrade.kernel_info(kernel)
    assert sha(a.fwtool.read_bytes())==upgrade.FWTOOL_SHA
    spec=json.loads((repo/'custom/jdcloud-qwrt/packaging.json').read_bytes())
    for name,h in spec['tools'].items():assert sha((a.tools_dir/name).read_bytes())==h
    entries=packing.read_tar(src);result=transform(repo,entries,packing)
    out.mkdir(parents=True);tar=out/'PRIVATE-hardened-rootfs.tar';packing.write_tar(tar,entries)
    root=out/'PRIVATE-hardened-rootfs.squashfs'
    with tar.open('rb') as f,(out/'pack.log').open('wb') as log:
        subprocess.run([str(a.tools_dir/'tar2sqfs.exe'),'-s','-c','xz','-b','262144','-j','2','-e',str(root)],stdin=f,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600,env=dict(os.environ,SOURCE_DATE_EPOCH='1738846613'))
    # tar2sqfs pads to 4 KiB; MMC overlay requires explicit 64 KiB padding.
    raw=root.read_bytes(); root.write_bytes(raw+bytes((-len(raw)) % 65536))
    roundtrip=out/'PRIVATE-roundtrip.tar'
    with roundtrip.open('wb') as f:subprocess.run([str(a.tools_dir/'sqfs2tar.exe'),'-s','-r','.',str(root)],stdout=f,check=True)
    restored=packing.read_tar(roundtrip);assert set(restored)==set(entries)
    for p in entries:assert packing.metadata(entries[p])==packing.metadata(restored[p]),p
    data=root.read_bytes();upgrade.root_info(data)
    image=out/'PRIVATE-OFFLINE-ONLY-HKC-QWRT-HARDENED-sysupgrade.bin'
    with tarfile.open(image,'w',format=tarfile.USTAR_FORMAT) as tf:
        for name,payload in [(upgrade.DIRECTORY,None),(upgrade.DIRECTORY+'/CONTROL',b'BOARD=jdcloud-ax1800-pro\n'),(upgrade.DIRECTORY+'/kernel',kernel),(upgrade.DIRECTORY+'/root',data)]:
            m=tarfile.TarInfo(name);m.mtime=1738846613;m.mode=0o755 if payload is None else 0o644
            if payload is None:m.type=tarfile.DIRTYPE
            else:m.size=len(payload)
            tf.addfile(m,io.BytesIO(payload) if payload is not None else None)
    meta={'metadata_version':'1.1','compat_version':'1.0','supported_devices':[upgrade.BOARD],
          'version':{'dist':'HKC-QWRT-offline-research','version':'NOT-FOR-INSTALLATION','target':'ipq60xx/generic','board':'jdcloud-ax1800-pro'},
          'hkc_qwrt':{'schema':1,'kernel_sha256':upgrade.KERNEL_SHA,'rootfs_bytes':len(data),'rootfs_sha256':sha(data)}}
    mp=out/'metadata.json';mp.write_bytes((json.dumps(meta,sort_keys=True)+'\n').encode())
    subprocess.run([str(a.fwtool),'-I',str(mp),str(image)],check=True)
    assert upgrade.metadata_info(image.read_bytes())==meta;upgrade.check_tar(image,kernel,data)
    result.update(passed=True,release_ready=False,source_base_commit='621c00da56335135ed431509333b01d2a870be1d',input_tar_sha256=PIN,rootfs_sha256=sha(data),rootfs_bytes=len(data),image_sha256=sha(image.read_bytes()),
                  original_kernel_sha256=sha(kernel),rootfs_tar_sha256=sha(roundtrip.read_bytes()),
                  candidate_source_hashes={p:sha((repo/'custom/jdcloud-qwrt/hardening'/source).read_bytes()) for p,(source,_) in PAYLOADS.items()},
                  limitations=['No router boot/flash/NSS/Wi-Fi/traffic/recovery validation','Original device may only apply original unguarded installer on first migration','Power loss during root write is not atomic','Stock optional-service default credential policy not yet qualified for commercial release','Retained configuration can retain old private keys and old overrides'])
    (out/'HARDENING-VERIFICATION.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps({k:result[k] for k in ['rootfs_sha256','rootfs_bytes','image_sha256','packages_changed','unchanged_inodes']}))
if __name__=='__main__':main()
