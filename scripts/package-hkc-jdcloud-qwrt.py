#!/usr/bin/env python3
"""Preserve vendor inode metadata and reconcile an offline QWRT application rootfs.

Outputs are private research root filesystems, NOT uploadable firmware.
No installer, network client, router operation or package maintainer script runs.
"""
import argparse
import copy
import hashlib
import io
import json
import os
import re
import struct
import subprocess
import tarfile
from pathlib import Path

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def path_name(name):
    while name.startswith('./'):
        name = name[2:]
    name = name.rstrip('/') or '.'
    require(not name.startswith('/') and '\\' not in name and not re.match(r'^[A-Za-z]:', name) and
            '..' not in name.split('/'), 'unsafe archive path')
    return name

def read_tar(path):
    entries = {}
    with tarfile.open(path, 'r:*') as archive:
        for member in archive:
            name = path_name(member.name)
            require(name not in entries, 'duplicate archive path: '+name)
            require(member.isfile() or member.isdir() or member.issym() or member.ischr(),
                    'unqualified inode type: '+name)
            require(set(member.pax_headers) <= {"path", "linkpath", "mtime"}, 'unqualified extended metadata: '+name)
            data = archive.extractfile(member).read() if member.isfile() else b''
            entries[name] = (copy.copy(member), data)
    return entries

def metadata(item):
    member, data = item
    return (member.type, member.mode, member.uid, member.gid, int(member.mtime),
            member.linkname, member.devmajor, member.devminor, sha(data))

def write_tar(path, entries):
    with tarfile.open(path, 'w', format=tarfile.PAX_FORMAT) as archive:
        for name, (member, data) in sorted(entries.items()):
            m = copy.copy(member); m.name = name; m.pax_headers = {}
            m.size = len(data) if m.isfile() else 0
            archive.addfile(m, io.BytesIO(data) if m.isfile() else None)

def paragraphs(text):
    return [x for x in text.strip('\n').split('\n\n') if x]

def fields(text):
    result = {}; last = None
    for line in text.splitlines():
        if line.startswith((' ', '\t')) and last:
            result[last] += '\n'+line
        elif ':' in line:
            last, value = line.split(':', 1)
            require(last not in result, 'duplicate package field')
            result[last] = value.lstrip()
        else:
            raise ValueError('malformed package control')
    require('Package' in result and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.-]*', result['Package']),
            'invalid package name')
    return result

def encode(record):
    return '\n'.join(k+': '+v for k, v in record.items())+'\n'

def package_records(text):
    result = {}
    for paragraph in paragraphs(text):
        record = fields(paragraph); name = record['Package']
        require(name not in result, 'duplicate installed package: '+name)
        result[name] = record
    return result

def owner_map(entries):
    owners = {}
    for path, (member, data) in entries.items():
        if path.startswith('usr/lib/opkg/info/') and path.endswith('.list'):
            package = Path(path).name[:-5]
            for raw in data.decode().splitlines():
                name = path_name(raw.lstrip('/'))
                owners.setdefault(name, set()).add(package)
    return owners

def dependency_names(record):
    return [part.strip().split()[0] for part in record.get('Depends', '').split(',') if part.strip()]

def missing_dependencies(records, selected):
    provided = set(records)
    for record in records.values():
        provided.update(part.strip().split()[0] for part in record.get('Provides', '').split(',') if part.strip())
    return [(p, dep) for p in selected for dep in dependency_names(records[p]) if dep not in provided]

def ipk_control(path, expected):
    require(sha(path.read_bytes()) == expected, 'official IPK hash mismatch')
    with tarfile.open(path) as outer:
        matches = [m for m in outer if path_name(m.name) == 'control.tar.gz']
        require(len(matches) == 1, 'IPK control archive missing')
        payload = outer.extractfile(matches[0]).read()
    with tarfile.open(fileobj=io.BytesIO(payload)) as inner:
        matches = [m for m in inner if path_name(m.name) == 'control']
        require(len(matches) == 1, 'IPK control missing')
        return fields(inner.extractfile(matches[0]).read().decode())

def reconcile(repo, entries, original, spec, pool, donor, epoch):
    profile = json.loads((repo/'custom/jdcloud-qwrt/profile.json').read_bytes())
    lock = json.loads((repo/'custom/jdcloud-qwrt/dependency-lock.json').read_bytes())
    old = package_records(original['usr/lib/opkg/status'][1].decode())
    records = copy.deepcopy(old); owners = owner_map(original)
    modified = set(spec['mutated_existing_packages']); custom = spec['new_custom_packages']
    package_files = {}; controls = {}
    def put(path, data):
        member = copy.copy(entries[path][0]) if path in entries else tarfile.TarInfo(path)
        member.type = tarfile.REGTYPE; member.mode = 0o644; member.uid = member.gid = 0
        member.mtime = epoch; member.size = len(data)
        entries[path] = (member, data)
    def register(name, control, paths):
        require(name not in old, 'new package already installed: '+name)
        require(control['Package'] == name, 'package identity mismatch')
        require(control['Architecture'] in ['all', 'aarch64_cortex-a53'], 'wrong package architecture')
        controls[name] = dict(control); package_files[name] = set(paths); modified.add(name)
    for name in ['nping', 'xz', 'xz-utils', 'liblzma', 'coreutils-timeout']:
        p = lock['official_candidates'][name]
        control = ipk_control(pool/Path(p['url']).name, p['sha256'])
        require(control['Version'] == p['version'] and control.get('Depends', '') == p['depends'],
                'official control mismatch')
        paths = set(p['files']) | set(p['symlinks'])
        for path, v in p['files'].items(): require(sha(entries[path][1]) == v['sha256'], 'native file drift')
        for path, target in p['symlinks'].items(): require(entries[path][0].linkname == target, 'native link drift')
        if name == 'coreutils-timeout': paths.add('usr/bin/timeout')
        register(name, control, paths)
    for name, expected in spec['donor_controls'].items():
        payload = (donor/'usr/lib/opkg/info'/(name+'.control')).read_bytes()
        require(sha(payload) == expected, 'donor control drift: '+name)
        candidate = lock['donor_candidates'][name]
        for path, digest in candidate['files'].items(): require(sha(entries[path][1]) == digest, 'donor file drift')
        register(name, fields(payload.decode()), candidate['files'])
    for name, version in spec['mutated_existing_packages'].items():
        control = fields(original['usr/lib/opkg/info/'+name+'.control'][1].decode())
        control['Version'] = version; controls[name] = control
        package_files[name] = {p for p, v in owners.items() if name in v}
    for name, v in custom.items():
        register(name, {'Package':name, 'Version':v['version'], 'Depends':v['depends'],
                       'Architecture':'all', 'Section':'luci',
                       'Description':'HKC offline-qualified QWRT userspace integration candidate'}, [])
    app = 'luci-app-ssr-plus'; theme = 'luci-theme-argon'; integration = 'hkc-qwrt-integration'
    translation = 'luci-i18n-ssr-plus-zh-cn'
    controls[app]['Depends'] += ', '+', '.join(spec['ssr_extra_dependencies'])
    assigned = {p:n for n, files in package_files.items() for p in files}
    for path, (member, data) in entries.items():
        if member.isdir() or path.startswith('usr/lib/opkg/'): continue
        changed = path not in original or metadata((member, data)) != metadata(original[path])
        if not changed: continue
        if path in assigned: continue
        if path in profile['legacy_theme']['files']: name = theme
        elif path.startswith(('usr/libexec/hkc-', 'etc/hotplug.d/', 'etc/rc.d/')) or path in ['etc/init.d/hkc-stability', 'etc/uci-defaults/zzz_hkc-qwrt']:
            name = integration
        elif path.endswith('.lmo'): name = translation
        elif path in profile['overlay'] or path == 'etc/config/shadowsocksr': name = app
        else: raise ValueError('No package owner for changed path: '+path)
        require(not owners.get(path) or owners[path] == {name}, 'unapproved ownership transfer: '+path)
        package_files[name].add(path); assigned[path] = name
    for name in sorted(modified):
        control = controls[name]; paths = package_files[name]
        for path in paths: require(path in entries, 'package owns missing file: '+name+' '+path)
        control['Installed-Size'] = str(sum(len(entries[p][1]) for p in paths if entries[p][0].isfile()))
        control['Description'] = control.get('Description', '')+'\n HKC QWRT local integration; pinned userspace candidate, not a hardware validation.'
        status = dict(old.get(name, {}))
        for key in ['Package','Version','Depends','Architecture','Installed-Size','Provides']:
            if key in control: status[key] = control[key]
        status.update(Status='install hold installed', **{'Installed-Time':str(epoch)})
        confpath = 'usr/lib/opkg/info/'+name+'.conffiles'
        if confpath in entries:
            lines = []
            for raw in entries[confpath][1].decode().splitlines():
                path = path_name(raw.split()[0].lstrip('/'))
                require(path in entries and entries[path][0].isfile(), 'missing conffile')
                lines.append(' /'+path+' '+hashlib.md5(entries[path][1]).hexdigest())
            status['Conffiles'] = '\n'+'\n'.join(lines)
        records[name] = status
        prefix = 'usr/lib/opkg/info/'+name
        put(prefix+'.control', encode(control).encode())
        put(prefix+'.list', ('\n'.join('/'+p for p in sorted(paths))+'\n').encode() if paths else b'')
        put(prefix+'.md5sums', ''.join(hashlib.md5(entries[p][1]).hexdigest()+'  '+p+'\n' for p in sorted(paths) if entries[p][0].isfile()).encode())
    require(not missing_dependencies(records, modified), 'unresolved candidate package dependency')
    # Keep untouched status paragraphs byte-for-byte, including vendor extensions.
    blocks = []; seen = set()
    for paragraph in paragraphs(original['usr/lib/opkg/status'][1].decode()):
        name = fields(paragraph)['Package']; seen.add(name)
        blocks.append(encode(records[name]).rstrip('\n') if name in modified else paragraph)
    blocks.extend(encode(records[name]).rstrip('\n') for name in sorted(set(records)-seen))
    put('usr/lib/opkg/status', ('\n\n'.join(blocks)+'\n\n').encode())
    finalowners = owner_map(entries)
    for name, paths in package_files.items():
        for path in paths:
            if not entries[path][0].isdir(): require(finalowners[path] == {name}, 'duplicate candidate ownership: '+path)
    return records, sorted(modified)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['base-rootfs', 'base-kernel', 'assembly-dir', 'dependency-dir', 'donor-dir', 'tools-dir', 'output']:
        p.add_argument('--'+name, required=True, type=Path)
    a = p.parse_args(); repo = Path(__file__).resolve().parents[1]
    spec = json.loads((repo/'custom/jdcloud-qwrt/packaging.json').read_bytes())
    profile = json.loads((repo/'custom/jdcloud-qwrt/profile.json').read_bytes())
    out = a.output.resolve()
    require(not out.exists(), 'fresh output required')
    for source in [a.base_rootfs,a.base_kernel,a.assembly_dir,a.dependency_dir,a.donor_dir,a.tools_dir]:
        require(not out.is_relative_to(source.resolve()) and not source.resolve().is_relative_to(out), 'input/output overlap')
    base = a.base_rootfs.read_bytes(); require(sha(base) == profile['base_image_sha256'], 'base image hash mismatch')
    kernel_sha = sha(a.base_kernel.read_bytes())
    require(kernel_sha == '0ca88f17c3ee8194ad0591425a927ab5e90f363b64f86f879271b058ee8247f8', 'kernel hash mismatch')
    archive = a.assembly_dir/'PRIVATE-NOT-FIRMWARE-rootfs-review.tar'
    require(sha(archive.read_bytes()) == spec['assembly_sha256'], 'unqualified assembly input')
    for name, digest in spec['tools'].items(): require(sha((a.tools_dir/name).read_bytes()) == digest, 'tool hash mismatch')
    require(struct.unpack_from('<Q',base,56)[0] == 0xffffffffffffffff, 'original xattrs need qualification')
    require(struct.unpack_from('<H',base,20)[0] == 4, 'expected original XZ compressor')
    epoch = struct.unpack_from('<I',base,8)[0]; block = struct.unpack_from('<I',base,12)[0]
    out.mkdir(parents=True)
    def unpack(image, dest):
        with dest.open('wb') as f:
            subprocess.run([str(a.tools_dir/'sqfs2tar.exe'),'-s','-r','.',str(image)],stdout=f,check=True)
    original_tar = out/'PRIVATE-original-metadata.tar'; unpack(a.base_rootfs, original_tar)
    original = read_tar(original_tar); entries = read_tar(archive)
    require('.' in original, 'root inode absent')
    # Restore per-inode original timestamps and the root itself; do not use host metadata.
    for name, item in original.items():
        if name == '.': entries[name] = copy.deepcopy(item)
        else:
            require(name in entries, 'original inode missing: '+name)
            entries[name][0].mtime = item[0].mtime
    records, modified = reconcile(repo, entries, original, spec, a.dependency_dir, a.donor_dir, epoch)
    for name in list(entries):
        for parent in Path(name).parents:
            key=parent.as_posix()
            if key not in entries:
                member=tarfile.TarInfo(key);member.type=tarfile.DIRTYPE;member.mode=0o755;member.mtime=epoch
                entries[key]=(member,b'')
    allowed_changes = set(json.loads((a.assembly_dir/'ASSEMBLY-VERIFICATION.json').read_bytes())['changed_or_added_paths']) | {'etc/config/shadowsocksr','usr/lib/opkg/status'}
    for name in modified:
        allowed_changes.update('usr/lib/opkg/info/'+name+suffix for suffix in ['.control','.list','.md5sums'])
    preserved = 0
    for name,item in original.items():
        if name not in allowed_changes:
            require(metadata(entries[name]) == metadata(item), 'unapproved original inode change: '+name); preserved += 1
    protected = []
    for name, item in original.items():
        if name != 'etc/config/shadowsocksr' and (name.startswith(('lib/modules/','lib/firmware/','etc/rc.d/','etc/config/','lib/upgrade/')) or name in ['.','etc/init.d/network','etc/init.d/boot','sbin/netifd','sbin/procd'] or 'nss' in name.lower()):
            require(metadata(entries[name]) == metadata(item), 'protected inode changed: '+name); protected.append(name)
    count = 0
    for line in (repo/'custom/hkc-stability-runtime.sha256').read_text().splitlines():
        if not line or line.startswith('#'): continue
        expected, name = line.split(); require(sha(entries[name][1]) == expected, 'accepted runtime drift'); count += 1
    require(count == 12, 'runtime manifest incomplete')
    merged = out/'PRIVATE-NOT-FIRMWARE-packaged-rootfs.tar'; write_tar(merged, entries)
    image = out/'PRIVATE-NOT-FIRMWARE-hkc-qwrt-rootfs.squashfs'
    with merged.open('rb') as f, (out/'pack.log').open('wb') as log:
        subprocess.run([str(a.tools_dir/'tar2sqfs.exe'),'-s','-c','xz','-b',str(block),'-j','2','-e',str(image)],stdin=f,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600,env=dict(os.environ,SOURCE_DATE_EPOCH=str(epoch)))
    require(image.stat().st_size < spec['rootfs_partition_bytes'], 'rootfs exceeds device partition')
    roundtrip = out/'PRIVATE-roundtrip.tar'; unpack(image, roundtrip)
    restored = read_tar(roundtrip)
    require(set(restored) == set(entries), 'roundtrip inode set mismatch')
    for name in entries: require(metadata(restored[name]) == metadata(entries[name]), 'roundtrip mismatch: '+name)
    require(package_records(restored['usr/lib/opkg/status'][1].decode()) == records, 'package DB changed during packing')
    expected = {name:records[name]['Version'] for name in modified}
    # Only status/control/list/hash/path metadata goes to the NIC-less VM; no config values or scripts.
    db_entries = {name:item for name,item in restored.items() if name=='usr/lib/opkg/status' or
                  name.startswith('usr/lib/opkg/info/') and name.endswith(('.control','.list','.conffiles','.md5sums'))}
    dbtar=out/'PACKAGE-DB-TEST.tar';write_tar(dbtar,db_entries)
    (out/'PACKAGE-DB-EXPECTED.json').write_bytes((json.dumps({'packages':expected,'tar_sha256':sha(dbtar.read_bytes()),'total_packages':len(records)},indent=2)+'\n').encode())
    report={'passed':True,'installable':False,'base_image_sha256':sha(base),'original_kernel_sha256':kernel_sha,
            'assembly_sha256':spec['assembly_sha256'],'rootfs_sha256':sha(image.read_bytes()),'rootfs_bytes':image.stat().st_size,
            'compression':'xz','block_size':block,'roundtrip_inodes':len(entries),'root_and_timestamps_preserved':True,
            'original_inodes_preserved_in_full':preserved,'original_hardlinks':0,'original_xattrs':False,'protected_inodes_unchanged':len(protected),
            'accepted_runtime_hashes':count,'packages':expected,'total_packages':len(records),'candidate_dependency_closure':True,
            'package_metadata_native_tested':False,'hardware_boot_tested':False,
            'limitations':['Private root filesystem only; no FIT/sysupgrade/upgrade container; NEVER upload it',
                           'No QWRT 5.4 kernel mounting or physical boot, NSS/Wi-Fi, proxy throughput or recovery test',
                           'Candidate packages are held; future upgrades require explicit compatibility review']}
    (out/'PACKAGING-VERIFICATION.json').write_bytes((json.dumps(report,indent=2)+'\n').encode())
    print(json.dumps(report,indent=2))

if __name__ == '__main__': main()
