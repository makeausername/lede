#!/usr/bin/env python3
"""Local audit tar only. Contains private base files; NEVER upload or flash it."""
import argparse, hashlib, importlib.util, io, json, shlex, stat, struct, tarfile
from pathlib import Path

def digest(data):
    return hashlib.sha256(data).hexdigest()

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['audit-dir', 'review-dir', 'dependency-dir', 'base-rootfs', 'base-kernel', 'output']:
        p.add_argument('--'+name, required=True, type=Path)
    a=p.parse_args(); repo=Path(__file__).resolve().parents[1]
    audit=a.audit_dir.resolve(); review=a.review_dir.resolve(); pool=a.dependency_dir.resolve(); out=a.output.resolve()
    inputs=[audit,review,pool,a.base_rootfs.resolve(),a.base_kernel.resolve()]
    if out.exists() or any(out.is_relative_to(x) or x.is_relative_to(out) for x in inputs):
        raise ValueError('Fresh output outside inputs required')
    profile=json.loads((repo/'custom/jdcloud-qwrt/profile.json').read_bytes())
    for name,key in [('working-qwrt-file-hashes.json','base_file_manifest_sha256'),('working-qwrt-inode-list.txt','base_inode_manifest_sha256')]:
        assert digest((audit/name).read_bytes()) == profile[key], name
    kernel_sha=digest(a.base_kernel.read_bytes())
    assert kernel_sha=='0ca88f17c3ee8194ad0591425a927ab5e90f363b64f86f879271b058ee8247f8'
    rootdata=a.base_rootfs.read_bytes()
    assert digest(rootdata)=='032374ee2ef2db1ce47db87b1c7a02122e05bcffe8f8aa1eaae58b80f2dace22'
    assert rootdata[:4]==b'hsqs' and struct.unpack_from('<Q',rootdata,56)[0]==0xffffffffffffffff
    buildtime=struct.unpack_from('<I',rootdata,8)[0]
    hashes=json.loads((audit/'working-qwrt-file-hashes.json').read_bytes())
    mapping=json.loads((audit/'working-qwrt-path-map.json').read_bytes())
    entries={}; original={}; changed=set()
    for line in (audit/'working-qwrt-inode-list.txt').read_text().splitlines():
        x=shlex.split(line); kind,path=x[:2]
        if path.startswith('/') or '..' in path.split('/') or path in entries: raise ValueError('Bad base path')
        e={'kind':kind,'mode':int(x[2],8),'uid':int(x[3]),'gid':int(x[4]),'origin':'original-qwrt'}
        if kind=='file':
            data=(audit/'working-qwrt-complete'/mapping[path]).read_bytes()
            assert digest(data)==hashes[path],path
            e.update(data=data,sha256=digest(data))
        elif kind=='slink': e['target']=x[5]
        elif kind=='nod':
            assert x[5:] == ['c','5','1'] and path=='dev/console'
            e.update(major=5,minor=1)
        elif kind!='dir': raise ValueError('Unqualified inode kind: '+kind)
        entries[path]=e; original[path]=e.copy()
    port=module(repo/'scripts/prepare-hkc-jdcloud-qwrt.py','port')
    integration=module(repo/'scripts/hkc-jdcloud-qwrt-integration.py','integration')
    def add(path,data,mode,origin):
        port.safe_path(path)
        if path in entries and entries[path]['kind']!='file':raise ValueError('File/link conflict: '+path)
        old=entries.get(path,{})
        entries[path]={'kind':'file','mode':mode,'uid':old.get('uid',0),'gid':old.get('gid',0),'data':data,'sha256':digest(data),'origin':origin}
        changed.add(path)
    modes=json.loads((review/'MODES.json').read_bytes())
    for path,mode in modes.items():
        assert port.allowed(path) and int(mode,8) in [0o600,0o644,0o755]
        data=port.regular(review/'review-only-files',path).read_bytes()
        assert not data.startswith(b'\x7fELF')
        if path in profile['overlay']:assert digest(data)==profile['overlay'][path]['sha256']
        add(path,data,int(mode,8),'HKC-review')
    lock=json.loads((repo/'custom/jdcloud-qwrt/dependency-lock.json').read_bytes())
    def link(path,target,origin):
        port.safe_path(path)
        if path in entries:raise ValueError('Link overwrite refused: '+path)
        entries[path]={'kind':'slink','mode':0o777,'uid':0,'gid':0,'target':target,'origin':origin};changed.add(path)
    for package in ['nping','xz','xz-utils','liblzma','coreutils-timeout']:
        spec=lock['official_candidates'][package]
        for path,v in spec['files'].items():
            assert path not in entries, path
            data=(pool/package/path).read_bytes();assert digest(data)==v['sha256']
            add(path,data,int(v['mode'],8),'official-'+package)
        for path,target in spec['symlinks'].items():link(path,target,'official-'+package)
    for package,spec in lock['donor_candidates'].items():
        for path,h in spec['files'].items():
            data=(audit/'hkc-diagnostic-complete'/path).read_bytes();assert digest(data)==h
            add(path,data,0o755 if data.startswith(b'\x7fELF') else 0o644,'qualified-donor-'+package)
    for path,(data,mode) in integration.payloads(repo).items():add(path,data,mode,'integration-candidate')
    for path,target in integration.LINKS.items():link(path,target,'integration-candidate')
    # Fresh/reset images need HKC factory SSR defaults; retained user overlay
    # config is handled separately by the conservative first-boot migration.
    factory_path='usr/share/shadowsocksr/shadowsocksr.config'
    factory=entries[factory_path]['data']
    assert digest(factory)==profile['overlay'][factory_path]['sha256']
    add('etc/config/shadowsocksr',factory,0o600,'HKC-factory-SSR-defaults')
    assert max(p for p in entries if p.startswith('etc/uci-defaults/'))=='etc/uci-defaults/zzz_hkc-qwrt'

    for path in list(entries):
        for parent in Path(path).parents:
            name=parent.as_posix()
            if name!='.' and name not in entries:
                entries[name]={'kind':'dir','mode':0o755,'uid':0,'gid':0,'origin':'new-parent'};changed.add(name)
    stable=0
    for line in (repo/'custom/hkc-stability-runtime.sha256').read_text().splitlines():
        if not line or line.startswith('#'):continue
        sha,path=line.split();assert entries[path]['sha256']==sha;stable+=1
    assert stable==12
    # No changes to any original hardware/startup/default-config inode are allowed.
    protected=[]
    for path,e in original.items():
        if path != 'etc/config/shadowsocksr' and (path.startswith(('lib/modules/','lib/firmware/','etc/rc.d/','etc/config/','lib/upgrade/')) or path in ['etc/init.d/network','etc/init.d/boot','sbin/netifd','sbin/procd'] or ('nss' in path.lower() and path not in changed)):
            assert entries[path]==e,path;protected.append(path)
        if path not in changed: assert entries[path]==e,path
    out.mkdir(parents=True)
    tarpath=out/'PRIVATE-NOT-FIRMWARE-rootfs-review.tar'
    with tarfile.open(tarpath,'w',format=tarfile.PAX_FORMAT) as tf:
        for path,e in sorted(entries.items()):
            info=tarfile.TarInfo(path);info.mode=e['mode'];info.uid=e['uid'];info.gid=e['gid'];info.mtime=buildtime
            data=None
            if e['kind']=='file':info.size=len(e['data']);data=io.BytesIO(e['data'])
            elif e['kind']=='dir':info.type=tarfile.DIRTYPE
            elif e['kind']=='slink':info.type=tarfile.SYMTYPE;info.linkname=e['target']
            elif e['kind']=='nod':info.type=tarfile.CHRTYPE;info.devmajor=e['major'];info.devminor=e['minor']
            tf.addfile(info,data)
    # Read archive back through an independent parser; no Windows extraction.
    with tarfile.open(tarpath,'r') as tf:
        found=set()
        for member in tf:
            assert member.name not in found;found.add(member.name);e=entries[member.name]
            assert (member.mode,member.uid,member.gid)==(e['mode'],e['uid'],e['gid'])
            if e['kind']=='file':assert member.isfile() and digest(tf.extractfile(member).read())==e['sha256']
            elif e['kind']=='slink':assert member.issym() and member.linkname==e['target']
            elif e['kind']=='dir':assert member.isdir()
            else:assert member.ischr() and (member.devmajor,member.devminor)==(5,1)
        assert found==set(entries)
    report={'passed':True,'installable':False,'archive_sha256':digest(tarpath.read_bytes()),'original_kernel_sha256':kernel_sha,'original_inodes':len(original),'assembled_inodes':len(entries),'changed_or_added_paths':sorted(changed),'protected_inodes_unchanged':len(protected),'accepted_runtime_hashes':stable,'original_startup_links_unchanged':True,'factory_ssr_default_sha256':digest(factory),'initializer_runs_after_vendor_defaults':True,'added_startup_links':['S99hkc-stability','K14hkc-stability'],'xattrs_in_original':False,'mode_owner_link_content_roundtrip':True,'original_hardware_boot_tested':False,'limitations':['Local private review tar, not SquashFS, FIT, sysupgrade or an installable package','Per-inode timestamps normalized to source filesystem build time; hardlink identity not independently qualified','No package database merge or existing node-schema compatibility qualification','No device boot, upgrade, network, wireless or recovery test']}
    (out/'ASSEMBLY-VERIFICATION.json').write_bytes((json.dumps(report,indent=2)+'\n').encode())
    print(json.dumps({k:v for k,v in report.items() if k!='changed_or_added_paths'},indent=2))

if __name__=='__main__':main()
