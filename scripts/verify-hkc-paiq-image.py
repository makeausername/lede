#!/usr/bin/env python3
"""Offline PAIQ image gate. Never opens a physical disk or contacts a router."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import uuid
import zlib

BOARD = 'paiq-ec3-bt19d4l'
EXPECTED = {1: (512, 131072), 2: (131584, 1835008), 128: (34, 478)}
LINUX = '0fc63daf-8483-4772-8e79-3d69d8477de4'
BIOS = '21686148-6449-6e6f-744e-656564454649'

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha(path):
    with open(path, 'rb') as f:
        h = hashlib.sha256()
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
        return h.hexdigest()

def inspect_gpt(data):
    require(len(data) >= 34 * 512, 'Truncated primary GPT')
    require(data[:2] in (b'\xebH', b'\xebc'), 'Missing BIOS GRUB stage1')
    require(data[510:512] == b'\x55\xaa', 'Invalid MBR signature')
    require(data[450] == 0xee and struct.unpack_from('<I', data, 454)[0] == 1, 'Not protective MBR')
    h = bytearray(data[512:1024])
    require(h[:8] == b'EFI PART', 'Not GPT')
    size, crc = struct.unpack_from('<II', h, 12)
    require(size == 92, 'Unexpected GPT header size')
    struct.pack_into('<I', h, 16, 0)
    require(zlib.crc32(h[:size]) == crc, 'GPT header CRC mismatch')
    lba, count, stride, crc = struct.unpack_from('<QIII', h, 72)
    require((lba, count, stride) == (2, 128, 128), 'Unexpected GPT entry geometry')
    entries = data[lba * 512:lba * 512 + count * stride]
    require(zlib.crc32(entries) == crc, 'GPT partition CRC mismatch')
    parts = {}
    for i in range(count):
        e = entries[i * stride:(i + 1) * stride]
        if e[:16] == bytes(16):
            continue
        start, end = struct.unpack_from('<QQ', e, 32)
        parts[i + 1] = (start, end - start + 1)
        require(str(uuid.UUID(bytes_le=bytes(e[:16]))) == (BIOS if i == 127 else LINUX), 'Partition type mismatch')
    require(parts == EXPECTED, f'Partition layout differs from audited disk: {parts}')
    return {'partitions': {str(k): list(v) for k, v in parts.items()},
            'root_partuuid': str(uuid.UUID(bytes_le=bytes(entries[144:160]))),
            'alternate_header_lba': struct.unpack_from('<Q', h, 32)[0],
            'primary_gpt_crc_valid': True}

def decompress_image(source, dest):
    # fwtool metadata follows the gzip member. Do not pass trailing metadata to gzip.
    d = zlib.decompressobj(31)
    with source.open('rb') as f, dest.open('wb') as out:
        while chunk := f.read(1024 * 1024):
            out.write(d.decompress(chunk))
            if d.eof:
                break
        require(d.eof, 'Truncated gzip stream')

def run(*args):
    return subprocess.check_output([str(a) for a in args])


def read_proxy_binary(root, path):
    # The pinned Mihomo package installs an absolute alternatives link. Older
    # unsquashfs -cat cannot follow that link inside the image. Verify BOTH
    # the entrypoint and its packaged executable, never a host filesystem path.
    if path == 'usr/bin/mihomo':
        target = 'usr/libexec/mihomo'
        listing = run('unsquashfs', '-ll', root, path).decode()
        entries = [line for line in listing.splitlines()
                   if line.startswith('l') and line.endswith('/' + path + ' -> /' + target)]
        require(len(entries) == 1, 'Mihomo alternatives link missing or incorrect')
        listing = run('unsquashfs', '-ll', root, target).decode()
        require(any(line.startswith('-rwx') and line.endswith('/' + target)
                    for line in listing.splitlines()), 'Mihomo target missing or not executable')
        path = target
    return run('unsquashfs', '-cat', root, path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--extract-dir', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--source-commit', required=True)
    a = p.parse_args()
    src, out = a.source.resolve(), a.extract_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    require(run('git', '-C', src, 'rev-parse', 'HEAD').decode().strip() == a.source_commit, 'Source revision mismatch')
    raw = out / 'disk.img'
    decompress_image(a.image, raw)
    with raw.open('rb') as f:
        info = inspect_gpt(f.read(34 * 512))
        require(raw.stat().st_size >= (131584 + 1835008) * 512, 'Truncated root partition')
        require(raw.stat().st_size < 8012390400, 'Image exceeds installed disk')
        f.seek(34 * 512)
        require(any(f.read(478 * 512)), 'Missing BIOS GRUB core in embedding partition')
        f.seek(512 * 512)
        (out / 'boot.fat').write_bytes(f.read(131072 * 512))
        f.seek(131584 * 512)
        header = f.read(96)
        require(header[:4] == b'hsqs', 'Root is not SquashFS')
        used = struct.unpack_from('<Q', header, 40)[0]
        require(96 < used < 1835008 * 512, 'SquashFS exceeds root partition')
        f.seek(131584 * 512)
        (out / 'root.squashfs').write_bytes(f.read(used))
    fwtool = src / 'staging_dir/host/bin/fwtool'
    if not fwtool.exists():
        fwtool = Path(shutil.which('fwtool') or '')
    require(fwtool.is_file(), 'fwtool is required')
    run(fwtool, '-i', out / 'metadata.json', a.image.resolve())
    meta = json.loads((out / 'metadata.json').read_text())
    require(meta.get('supported_devices') == [BOARD], 'Image metadata is not PAIQ-specific')
    boot = out / 'boot.fat'
    grub = run('mtype', '-i', boot, '::/boot/grub/grub.cfg').decode()
    require('root=PARTUUID=' + info['root_partuuid'] in grub, 'GRUB root PARTUUID mismatch')
    require('/boot/vmlinuz' in grub and 'failsafe=true' in grub, 'Missing kernel/failsafe entries')
    require('root=/dev/sd' not in grub, 'Hardcoded boot disk')
    for name in ('/boot/vmlinuz', '/boot/grub/boot.img', '/boot/grub/core.img', '/efi/boot/bootx64.efi'):
        require(len(run('mtype', '-i', boot, '::' + name)) >= 512, 'Missing boot component ' + name)
    root = out / 'root.squashfs'
    def cat(path):
        return run('unsquashfs', '-cat', root, path)
    pairs = {
      'etc/board.d/02_network': 'target/linux/x86/base-files/etc/board.d/02_network',
      'lib/upgrade/platform.sh': 'target/linux/x86/base-files/lib/upgrade/platform.sh',
      'lib/preinit/01_sysinfo': 'target/linux/x86/base-files/lib/preinit/01_sysinfo',
      'etc/init.d/autocore': 'package/lean/autocore/files/x86/autocore',
      'etc/uci-defaults/zz-hkc-minimal-defaults': 'custom/hkc-paiq-defaults.sh',
      'etc/uci-defaults/zz-hkc-lan-ipv4-only': 'custom/hkc-lan-ipv4-only.sh',
      'usr/share/hkc/forced-proxy-domains.list': 'custom/forced-proxy-domains.list',
    }
    for image_path, source_path in pairs.items():
        require(cat(image_path) == (src / source_path).read_bytes(), 'Packaged source mismatch: ' + image_path)
    for path in ('etc/uci-defaults/zz-hkc-minimal-defaults', 'etc/uci-defaults/zz-hkc-lan-ipv4-only', 'etc/init.d/irqbalance'):
        listing = run('unsquashfs', '-ll', root, path).decode()
        require(any(line.startswith('-rwx') and line.endswith('/' + path) for line in listing.splitlines()), 'Not executable: ' + path)
    require(b"enabled '1'" in cat('etc/config/irqbalance'), 'IRQ balancing disabled')
    runtime = {}
    for line in (src / 'custom/hkc-stability-runtime.sha256').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        expected, path = line.split(None, 1)
        actual = hashlib.sha256(cat(path)).hexdigest()
        require(actual == expected, 'Accepted runtime mismatch: ' + path)
        runtime[path] = actual
    require(len(runtime) == 12, 'Accepted runtime inventory changed')
    binaries = ('usr/bin/xray', 'usr/bin/mihomo', 'usr/bin/naive', 'usr/bin/shadow-tls', 'usr/bin/sslocal', 'usr/bin/kcptun-client')
    for path in binaries:
        elf = read_proxy_binary(root, path)
        require(len(elf) >= 20 and elf[:5] == b'\x7fELF\x02' and struct.unpack_from('<H', elf, 18)[0] == 62, 'Wrong CPU binary: ' + path)
    info.update({'source_commit': a.source_commit, 'firmware': a.image.name,
                 'sha256': sha(a.image), 'raw_image_sha256': sha(raw), 'squashfs_bytes_used': used,
                 'runtime_sha256': runtime, 'source_files_verified': list(pairs),
                 'boot_components_verified': True, 'x86_64_binaries_verified': list(binaries),
                 'binary_entrypoint_links': {'usr/bin/mihomo': '/usr/libexec/mihomo'},
                 'limitations': ['First boot, retained configuration migration, throughput and recovery are not device-tested.',
                   'Upstream ptgen omits alternate GPT by default; primary GPT and exact current geometry verified.',
                   'ELF architecture checks do not prove every compiled instruction works on J1900. Device testing required.']})
    a.report.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    print('PASS PAIQ BIOS/GPT/FAT/SquashFS, board defaults, 12 accepted runtime files and x86_64 cores')

if __name__ == '__main__':
    main()
