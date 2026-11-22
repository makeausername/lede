#!/usr/bin/env python3
"""Local-only QWRT application-port preparation. Never builds an installable image."""
import argparse
import hashlib
import json
import posixpath
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def safe_path(value, allow_linux_colon=False):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or '..' in p.parts or '\\' in value or (':' in value and not allow_linux_colon):
        raise ValueError('Unsafe image path: ' + value)
    return p.as_posix()

def allowed(path):
    path = safe_path(path)
    exact = {'etc/init.d/shadowsocksr', 'etc/init.d/hkc-stability',
             'etc/hotplug.d/iface/99-ssrplus-pppoe', 'etc/hotplug.d/ntp/90-hkc-time',
             'etc/uci-defaults/luci-ssr-plus', 'etc/uci-defaults/30_luci-theme-argon', 'etc/uci-defaults/luci-i18n-ssr-plus-zh-cn',
             'www/luci-static/resources/menu-argon.js',
             'usr/bin/ssr-switch', 'usr/bin/ssr-monitor', 'usr/bin/ssr-rules',
             'usr/lib/lua/luci/controller/shadowsocksr.lua',
             'usr/share/ucitrack/luci-app-ssr-plus.json',
             'usr/share/rpcd/acl.d/luci-app-ssr-plus.json'}
    prefixes = ('usr/share/shadowsocksr/', 'usr/libexec/hkc-',
                'usr/lib/lua/luci/model/cbi/shadowsocksr/',
                'usr/lib/lua/luci/view/shadowsocksr/',
                'usr/lib/lua/luci/view/themes/argon/',
                'usr/lib/lua/luci/i18n/ssr-plus.', 'usr/lib/lua/luci/i18n/hkc-ssr-ui.', 'www/luci-static/argon/',
                'etc/ssrplus/')
    return path in exact or path.startswith(prefixes)

def regular(root, path):
    path = safe_path(path)
    root = Path(root).resolve()
    target = root / path
    if not target.is_file() or target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError('Not a confined regular file: ' + path)
    return target

def validate_payload(profile, donor):
    result = {}
    for path, spec in profile['overlay'].items():
        if not allowed(path):
            raise ValueError('Hardware/configuration path prohibited: ' + path)
        f = regular(donor, path)
        payload = f.read_bytes()
        if payload.startswith(b'\x7fELF'):
            raise ValueError('Unqualified executable/library prohibited: ' + path)
        if hashlib.sha256(payload).hexdigest() != spec['sha256']:
            raise ValueError('Donor digest mismatch: ' + path)
        mode = int(spec['mode'], 8)
        if mode not in (0o600, 0o644, 0o755):
            raise ValueError('Unapproved mode: ' + path)
        result[path] = payload
    return result

def theme_payloads(profile, legacy):
    result = {}
    for target, spec in profile.get('legacy_theme', {}).get('files', {}).items():
        if not allowed(target):
            raise ValueError('Theme path prohibited: ' + target)
        payload = regular(legacy, spec['source']).read_bytes()
        if hashlib.sha256(payload).hexdigest() != spec['sha256'] or payload.startswith(b'\x7fELF'):
            raise ValueError('Theme source mismatch: ' + target)
        if target.endswith('/header.htm'):
            if profile['legacy_theme'].get('dispatcher') != 'legacy-lua-tree':
                raise ValueError('Unsupported QWRT theme dispatcher')
            for token in (b'disp.lookup(', b'/luci.js', b"L.require("):
                if token in payload:
                    raise ValueError('Modern dispatcher dependency in legacy theme')
            old = b'<a class="brand" href="#"><%=boardinfo.hostname or "?"%></a>'
            if payload.count(old) != 2:
                raise ValueError('Theme branding anchor drift')
            payload = payload.replace(old, b'<a class="brand" href="#">HKC</a>')
        if target.endswith(('/footer.htm','/footer_login.htm')):
            start = payload.index(b'<a class="luci-link"')
            end = payload.index(b'<%= ver.distversion %>', start) + len(b'<%= ver.distversion %>')
            payload = payload[:start] + b'<span>HKC</span>' + payload[end:]
        if target.endswith('/sysauth.htm'):
            old = b'<%+header_login%>'
            if payload.count(old) != 1:
                raise ValueError('Login include anchor drift')
            payload = payload.replace(old, b'<%+themes/argon/out_header_login%>')
            payload = payload.replace(b'<%=striptags( (boardinfo.hostname or "?") ) %>', b'HKC')
        if target == 'etc/uci-defaults/30_luci-theme-argon':
            # Upstream 18.06 postinst rewrites dispatcher.lua and a global template.
            # QWRT already supports theme sysauth. Register the theme only.
            payload = b'#!/bin/sh\n[ "$(cat /tmp/sysinfo/board_name 2>/dev/null)" = \'jdcloud,ax1800-pro\' ] || exit 1\nuci -q get luci.main >/dev/null || exit 1\nuci -q batch <<\'EOF\'\nset luci.themes.Argon=\'/luci-static/argon\'\nset luci.main.mediaurlbase=\'/luci-static/argon\'\ncommit luci\nEOF\n'
        result[target] = payload
    return result

def write_review_overlay(profile, donor, output, legacy=None):
    donor = Path(donor).resolve()
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(donor) or donor.is_relative_to(output):
        raise ValueError('Output must be a fresh directory outside input')
    payloads = validate_payload(profile, donor)  # Finish all checks before output writes.
    if profile.get('legacy_theme'):
        if legacy is None: raise ValueError('Pinned legacy theme source required')
        if output.is_relative_to(Path(legacy).resolve()) or Path(legacy).resolve().is_relative_to(output):
            raise ValueError('Output overlaps theme input')
        theme = theme_payloads(profile, legacy)
        if set(theme) & set(payloads): raise ValueError('Theme overlay collision')
        payloads.update(theme)
    output.mkdir(parents=True)
    for path, payload in payloads.items():
        f = output / 'review-only-files' / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(payload)
    (output / 'MODES.json').write_text(json.dumps({p:s['mode'] for p,s in {**profile['overlay'], **profile.get('legacy_theme',{}).get('files',{})}.items()},indent=2)+'\n')
    report = {'installable': False, 'boot_tested': False, 'files':len(payloads),
              'missing_dependency_names':profile['required_new_packages'],
              'pending_gates':profile['not_installable_until'],
              'note':'No installer, postinst, image, bootloader or kernel is generated. Modes are recorded, not applied on Windows.'}
    (output / 'STATUS.json').write_text(json.dumps(report,indent=2)+'\n')
    (output / 'NOT-AN-INSTALLABLE-PACKAGE.txt').write_text('Offline review inputs only. Do not upload, install or flash.\n')
    return report

def validate_base(audit, profile, image):
    audit = Path(audit)
    if digest(image) != profile['base_image_sha256']:
        raise ValueError('Wrong QWRT base image')
    manifest = audit/'working-qwrt-file-hashes.json'
    inode = audit/'working-qwrt-inode-list.txt'
    if digest(manifest)!=profile['base_file_manifest_sha256'] or digest(inode)!=profile['base_inode_manifest_sha256']:
        raise ValueError('Untrusted base inventory')
    hashes=json.loads(manifest.read_text(encoding='utf-8'))
    mapping=json.loads((audit/'working-qwrt-path-map.json').read_text(encoding='utf-8'))
    if set(mapping)!=set(hashes) or len({p.casefold() for p in mapping.values()})!=len(mapping):
        raise ValueError('Invalid case-safe extraction map')
    root=audit/'working-qwrt-complete'
    for path, expected in hashes.items():
        safe_path(path, allow_linux_colon=True)
        if digest(regular(root,mapping[path]))!=expected:
            raise ValueError('Base file drift: '+path)
    return len(hashes)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit-dir',type=Path,required=True)
    p.add_argument('--base-image',type=Path,required=True)
    p.add_argument('--donor-image',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--legacy-theme',type=Path,required=True)
    args=p.parse_args()
    profile=json.loads((ROOT/'custom/jdcloud-qwrt/profile.json').read_text())
    if digest(args.donor_image)!=profile['donor_image_sha256']:
        raise ValueError('Wrong donor image')
    count=validate_base(args.audit_dir,profile,args.base_image)
    # Never allow output inside the verified base or any audit input directory.
    if args.output.resolve().is_relative_to(args.audit_dir.resolve()) or args.audit_dir.resolve().is_relative_to(args.output.resolve()):
        raise ValueError('Output overlaps input audit directory')
    report=write_review_overlay(profile,args.audit_dir/'hkc-diagnostic-complete',args.output,args.legacy_theme)
    report['base_files_rehashed']=count
    (args.output/'STATUS.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
