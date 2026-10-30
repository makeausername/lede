#!/usr/bin/env python3
"""Host-side validation for the dedicated N60 PRO slot1 image."""
import hashlib
import json
import lzma
import struct
import subprocess
import tarfile
import tempfile
import zlib
from pathlib import Path
from hkc_n60pro_stock_check import PARTITIONS
BOARD = 'netcore,n60-pro-stock-slot1'
PROFILE = BOARD.replace(',', '_')
LAYOUT = PARTITIONS
ROOT = Path(__file__).resolve().parents[1]

def need(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def fdt(data):
    need(len(data) >= 40, 'truncated FDT header')
    magic, total, pos, strings, reserve, version, last, cpu, names_size, st_size = struct.unpack_from('>10I', data)
    need(magic == 0xd00dfeed and 40 <= total <= len(data) and version == 17 and last <= 17,
         'invalid FDT')
    limit = pos + st_size
    need(40 <= reserve < pos < limit <= strings and strings + names_size <= total,
         'invalid FDT block bounds')
    data = data[:total]
    nodes, stack = {}, []
    while pos + 4 <= limit:
        token, = struct.unpack_from('>I', data, pos)
        pos += 4
        if token == 1:
            end = data.index(0, pos, limit)
            name = data[pos:end].decode()
            need('/' not in name and (bool(name) if stack else not name), 'invalid FDT node name')
            stack.append(name)
            pos = (end + 4) & ~3
            path = '/'.join(stack) or '/'
            need(path not in nodes, 'duplicate FDT node')
            nodes[path] = {}
        elif token == 2:
            need(bool(stack), 'unbalanced FDT nodes')
            stack.pop()
        elif token == 3:
            need(bool(stack) and pos + 8 <= limit, 'invalid FDT property header')
            size, offset = struct.unpack_from('>II', data, pos)
            pos += 8
            need(pos + size <= limit and offset < names_size, 'truncated FDT property')
            end = data.index(0, strings + offset, strings + names_size)
            key = data[strings + offset:end].decode()
            props = nodes['/'.join(stack) or '/']
            need(bool(key) and key not in props, 'duplicate or empty FDT property')
            props[key] = data[pos:pos + size]
            pos = (pos + size + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            need(not stack and '/' in nodes and pos == limit, 'unbalanced/trailing FDT structure')
            return nodes
        else:
            raise ValueError('invalid FDT token')
    raise ValueError('missing FDT end')


def text(value):
    return value.rstrip(b'\0').decode()


def check_dtb(data):
    nodes = fdt(data)
    need(nodes['/']['compatible'].split(b'\0')[:-1] ==
         [BOARD.encode(), b'mediatek,mt7986a'], 'wrong DTB identity')
    found = {}
    for path, props in nodes.items():
        if '/partitions/' in path and 'label' in props:
            label = text(props['label'])
            if label in LAYOUT:
                need(label not in found, 'duplicate partition')
                found[label] = struct.unpack('>II', props['reg'])
                if label in ('BL2', 'Factory', 'FIP'):
                    need('read-only' in props, 'boot/calibration partition writable')
    need(found == LAYOUT, 'partition offsets/sizes differ from inspected device')
    return nodes


def read_payload(path):
    need(path.stat().st_size <= 96 * 1024 * 1024, 'oversized candidate image')
    with tarfile.open(path, mode='r:') as tar:
        members = tar.getmembers()
        prefix = 'sysupgrade-' + PROFILE
        expected = {prefix, prefix + '/CONTROL', prefix + '/kernel', prefix + '/root'}
        need(len(members) == 4 and {m.name.rstrip('/') for m in members} == expected,
             'wrong, duplicate or extra tar members')
        result = {}
        for m in members:
            if m.name.rstrip('/') == prefix:
                need(m.isdir(), 'archive root is not a directory')
                continue
            need(m.isfile() and not m.pax_headers, 'nonregular/PAX archive member')
            limit = 4096 if m.name.endswith('/CONTROL') else 64 * 1024 * 1024
            need(0 < m.size <= limit, 'invalid member size')
            result[m.name.rsplit('/', 1)[1]] = tar.extractfile(m).read()
        need(result['CONTROL'] == ('BOARD=' + PROFILE + '\n').encode(), 'wrong CONTROL identity')
        need(result['root'][:4] == b'hsqs', 'rootfs is not SquashFS')
        return result


def check_kernel_fit(kernel):
    fit = fdt(kernel)
    cfg = fit['/configurations']
    need(text(cfg['default']) == 'config-1', 'unexpected FIT configuration')
    cfg = fit['/configurations/config-1']
    k = fit['/images/' + text(cfg['kernel'])]
    dt = fit['/images/' + text(cfg['fdt'])]
    need(text(k['arch']) == 'arm64' and text(k['compression']) == 'lzma', 'wrong kernel encoding')
    need(k['load'] == k['entry'] == struct.pack('>I', 0x48000000), 'kernel load/entry needs review')
    dec = lzma.LZMADecompressor()
    raw = dec.decompress(k['data'], max_length=64 * 1024 * 1024)
    need(dec.eof and len(raw) >= 64 and raw[56:60] == b'ARM\x64', 'invalid/oversized ARM64 kernel')
    need(struct.unpack_from('<Q', raw, 8)[0] == 0, 'kernel text_offset needs review')
    need(b'netcore,n60-pro-stock-slot1' in raw and b'rootfs2' in raw, 'slot1 kernel selector missing')
    check_dtb(dt['data'])
    # FIT hashes protect each embedded image independently of outer tar metadata.
    for node, props in fit.items():
        if node.startswith('/images/') and 'data' in props:
            hashes = [v for n, v in fit.items() if n.startswith(node + '/hash')]
            need(bool(hashes), 'missing FIT image hash')
            # mkits.sh emits CRC32 alongside SHA; verify both, never skip CRC32.
            need(any(text(h['algo']) in ('sha1', 'sha256') for h in hashes),
                 'missing FIT cryptographic hash')
            for h in hashes:
                algo = text(h['algo'])
                need(algo in ('crc32', 'sha1', 'sha256'), 'unsupported FIT hash algorithm: ' + algo)
                digest = (struct.pack('>I', zlib.crc32(props['data']) & 0xffffffff)
                          if algo == 'crc32' else hashlib.new(algo, props['data']).digest())
                need(digest == h['value'], 'FIT hash mismatch: ' + algo)


def check_fit(kernel, root):
    check_kernel_fit(kernel)
    from hkc_n60pro_fit import check_rootfs_fit
    return check_rootfs_fit(kernel, root)


def check_root(root, unsquashfs):
    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / 'root.squashfs'; image.write_bytes(root)
        def member(name):
            return subprocess.run([str(unsquashfs), '-cat', str(image), name], capture_output=True, check=True).stdout
        for line in (ROOT / 'custom/hkc-stability-runtime.sha256').read_text().splitlines():
            if not line or line.startswith('#'): continue
            digest, name = line.split(None, 1)
            need(hashlib.sha256(member(name)).hexdigest() == digest, 'accepted runtime differs: ' + name)
        for name in ['lib/upgrade/hkc-n60pro-slot1.sh', 'lib/preinit/79_hkc_stock_overlay', 'lib/upgrade/platform.sh',
                     'etc/hotplug.d/ieee80211/11_fix_wifi_mac', 'etc/board.d/01_leds', 'etc/board.d/02_network',
                     'etc/uci-defaults/31_hkc_stock_env']:
            expected = (ROOT / 'target/linux/mediatek/filogic/base-files' / name).read_bytes().replace(b'\r\n', b'\n')
            need(member(name) == expected, 'migration helper differs: ' + name)
        # Carry forward the stable workflow's source-to-image UI/default checks.
        feed = ROOT / 'feeds/helloworld/luci-app-ssr-plus'
        for target, source in {
            'usr/bin/ssr-monitor': 'root/usr/bin/ssr-monitor',
            'usr/share/shadowsocksr/gen_config.lua': 'root/usr/share/shadowsocksr/gen_config.lua',
            'usr/bin/ssr-rules': 'root/usr/bin/ssr-rules',
            'usr/lib/lua/luci/model/cbi/shadowsocksr/servers.lua': 'luasrc/model/cbi/shadowsocksr/servers.lua',
            'usr/lib/lua/luci/model/cbi/shadowsocksr/advanced.lua': 'luasrc/model/cbi/shadowsocksr/advanced.lua',
            'usr/lib/lua/luci/view/shadowsocksr/servers_subscribe_url_style.htm': 'luasrc/view/shadowsocksr/servers_subscribe_url_style.htm',
            'usr/lib/lua/luci/view/shadowsocksr/subscribe.htm': 'luasrc/view/shadowsocksr/subscribe.htm',
            'usr/share/shadowsocksr/shadowsocksr.config': 'root/usr/share/shadowsocksr/shadowsocksr.config',
            'etc/uci-defaults/luci-ssr-plus': 'root/etc/uci-defaults/luci-ssr-plus',
        }.items():
            expected = feed / source
            need(expected.is_file(), 'prepared, patched build tree is required: ' + source)
            need(member(target) == expected.read_bytes().replace(b'\r\n', b'\n'), 'stable feature differs: ' + target)
        need(member('etc/uci-defaults/zz-hkc-lan-ipv4-only') ==
             (ROOT / 'custom/hkc-lan-ipv4-only.sh').read_bytes().replace(b'\r\n', b'\n'), 'LAN IPv4 defaults differ')
        need(hashlib.sha256(member('usr/lib/lua/luci/i18n/hkc-ssr-ui.zh-cn.lmo')).hexdigest() ==
             '70f4115597cfe7610e3ccc2fae18ad27690e8f888a6910aa36f7ed9c4177737e', 'bilingual catalog differs')
        lib = member('lib/libfstools.so')
        need(b'netcore,n60-pro-stock-slot1' in lib and b'hkc_data' in lib, 'private-overlay fstools not included')
        block = member('sbin/block')
        need(b'netcore,n60-pro-stock-slot1' in block and b'hkc_data' in block,
             'stock configuration isolation missing from block extroot')


def metadata(path, fwtool):
    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / 'meta.json'
        subprocess.run([str(fwtool), '-i', str(file), str(path)], check=True, capture_output=True)
        return json.loads(file.read_text())
