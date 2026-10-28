#!/usr/bin/env python3
"""AX6000 source isolation and built-image contract checks; never flashes a device."""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import struct
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BOARD = 'xiaomi,redmi-router-ax6000-stock'
LEGACY = 'xiaomi,redmi-router-ax6000'
PROFILE = BOARD.replace(',', '_')
LAYOUT = {'BL2': (0, 0x100000), 'Nvram': (0x100000, 0x40000),
          'Bdata': (0x140000, 0x40000), 'Factory': (0x180000, 0x200000),
          'FIP': (0x380000, 0x200000), 'crash': (0x580000, 0x40000),
          'crash_log': (0x5c0000, 0x40000),
          'ubi_kernel': (0x600000, 0x1e00000), 'ubi': (0x2400000, 0x5000000)}


def need(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def fdt(data):
    need(len(data) >= 40, 'truncated FDT header')
    magic, total, pos, strings = struct.unpack_from('>IIII', data)
    need(magic == 0xd00dfeed and total <= len(data), 'invalid FDT')
    data = data[:total]
    nodes, stack = {}, []
    while pos + 4 <= total:
        token, = struct.unpack_from('>I', data, pos)
        pos += 4
        if token == 1:
            end = data.index(0, pos)
            stack.append(data[pos:end].decode())
            pos = (end + 4) & ~3
            nodes.setdefault('/'.join(stack) or '/', {})
        elif token == 2:
            stack.pop()
        elif token == 3:
            size, offset = struct.unpack_from('>II', data, pos)
            pos += 8
            need(pos + size <= total, 'truncated FDT property')
            end = data.index(0, strings + offset)
            key = data[strings + offset:end].decode()
            nodes['/'.join(stack) or '/'][key] = data[pos:pos + size]
            pos = (pos + size + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
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
                if label not in ('ubi', 'ubi_kernel'):
                    need('read-only' in props, 'boot/calibration partition writable')
    need(found == LAYOUT, 'partition offsets/sizes differ from inspected device')
    return nodes


def test_dtb_validation():
    # Build a minimal FDT to exercise the safety contract without a toolchain.
    def blob(layout, identity=BOARD, protect=True):
        strings, tokens, offsets = bytearray(), bytearray(), {}
        def begin(name):
            tokens.extend(struct.pack('>I', 1) + name.encode() + b'\0')
            tokens.extend(b'\0' * (-len(tokens) % 4))
        def end():
            tokens.extend(struct.pack('>I', 2))
        def prop(key, value):
            if key not in offsets:
                offsets[key] = len(strings)
                strings.extend(key.encode() + b'\0')
            tokens.extend(struct.pack('>III', 3, len(value), offsets[key]) + value)
            tokens.extend(b'\0' * (-len(tokens) % 4))
        begin('')
        prop('compatible', identity.encode() + b'\0mediatek,mt7986a\0')
        begin('partitions')
        for label, (offset, size) in layout.items():
            begin('partition@' + format(offset, 'x'))
            prop('label', label.encode() + b'\0')
            prop('reg', struct.pack('>II', offset, size))
            if protect and label not in ('ubi', 'ubi_kernel'):
                prop('read-only', b'')
            end()
        end()
        end()
        tokens.extend(struct.pack('>I', 9))
        return (struct.pack('>10I', 0xd00dfeed, 56 + len(tokens) + len(strings),
                            56, 56 + len(tokens), 40, 17, 16, 0, len(strings), len(tokens))
                + b'\0' * 16 + tokens + strings)
    check_dtb(blob(LAYOUT))
    for data in (blob(LAYOUT, identity=LEGACY), blob(LAYOUT, protect=False),
                 blob(dict(LAYOUT, ubi=(0x600000, 0x6e00000))), b'bad'):
        try:
            check_dtb(data)
        except (ValueError, KeyError, struct.error):
            continue
        raise ValueError('DTB validator accepted an unsafe fixture')
    print('PASS: DTB safety checks reject wrong identity/layout, writable boot partitions and truncation')


def check_source():
    baseline = json.loads(read('custom/hkc-ax6000-baseline.json'))
    for path, expected in baseline['sha256_lf'].items():
        actual = hashlib.sha256(read(path).encode()).hexdigest()
        need(actual == expected, 'stable N60 source changed: ' + path)
    old = read('configs/hkc-n60-pro.config')
    new = read('configs/hkc-redmi-ax6000-stock.config')
    need(new == old.replace('DEVICE_netcore_n60-pro=y', 'DEVICE_' + PROFILE + '=y'),
         'AX6000 software configuration differs from N60')
    workflow = read('.github/workflows/hkc-redmi-ax6000-stock.yml')
    need('on:\n  workflow_dispatch:\n  push:\n    tags:\n      - \"hkc-ax6000-test-*\"\n\npermissions:' in workflow,
         'only explicit build tags and manual dispatch may build')
    need("if: github.ref == 'refs/heads/codex/redmi-ax6000-stock'" in workflow, 'branch guard missing')
    # Entire application customization/default injection sections remain identical.
    old_workflow = read('.github/workflows/openwrt-ci.yml')
    for start, end in [('      - name: Fetch and pin package feeds',
                        '      - name: Generate and validate build configuration')]:
        need(workflow[workflow.index(start):workflow.index(end)] ==
             old_workflow[old_workflow.index(start):old_workflow.index(end)],
             'shared application/defaults pipeline changed')
    dts = read('target/linux/mediatek/dts/mt7986a-xiaomi-redmi-router-ax6000-stock.dts')
    need('#include "mt7986a-xiaomi-redmi-router-ax6000.dts"' in dts, 'AX6000 wiring not inherited')
    need('/delete-node/ partition@600000;' in dts, 'merged partition not removed')
    for offset, size in (LAYOUT['ubi_kernel'], LAYOUT['ubi']):
        need(f'reg = <0x{offset:x} 0x{size:x}>;' in dts, 'stock partition missing')
    print(f'PASS: {len(baseline["sha256_lf"])} stable files unchanged; software/defaults parity; isolated workflow')


def check_firmware(path):
    with tarfile.open(path) as tar:
        prefix = 'sysupgrade-' + PROFILE + '/'
        def member(name):
            matches = [m for m in tar.getmembers() if m.name == prefix + name and m.isfile()]
            need(len(matches) == 1, 'missing/duplicate image member ' + name)
            return tar.extractfile(matches[0]).read()
        kernel, root = member('kernel'), member('root')
        need(bool(member('CONTROL')), 'empty CONTROL')
    # Leave at least 24 eraseblocks for UBI overhead/reserve and 16 MiB for overlay.
    need(0 < len(kernel) <= (240 - 24) * 126976, 'kernel exceeds conservative UBI budget')
    need(0 < len(root) <= (640 - 24) * 126976 - 16 * 1024 * 1024,
         'rootfs leaves insufficient UBI/overlay space')
    need(root[:4] == b'hsqs', 'rootfs is not squashfs')
    fit = fdt(kernel)
    cfg = fit['/configurations']
    need(text(cfg['default']) == 'config-1', 'unexpected FIT default config')
    cfg = fit['/configurations/config-1']
    k = fit['/images/' + text(cfg['kernel'])]
    dt = fit['/images/' + text(cfg['fdt'])]
    need(text(k['arch']) == 'arm64' and text(k['compression']) == 'lzma', 'unexpected kernel encoding')
    need(k['load'] == k['entry'] == struct.pack('>I', 0x48000000), 'unexpected kernel address')
    image = lzma.decompress(k['data'])
    need(image[56:60] == b'ARM\x64', 'not an ARM64 Image')
    # Modern ARM64 kernel text_offset is zero (old 5.4 image used 0x80000).
    need(struct.unpack_from('<Q', image, 8)[0] == 0, 'ARM64 text_offset/load address needs review')
    check_dtb(dt['data'])
    with tempfile.TemporaryDirectory() as tmp:
        metadata = Path(tmp) / 'metadata.json'
        subprocess.run([str(ROOT / 'staging_dir/host/bin/fwtool'), '-i', str(metadata), str(path)], check=True)
        meta = json.loads(metadata.read_text())
    need(set(meta['supported_devices']) == {BOARD, LEGACY}, 'wrong image supported_devices')
    print('PASS: FIT, DTB identity/protected partitions, 30+80 MiB layout, UBI capacity, metadata')
    print('Firmware SHA256:', hashlib.sha256(path.read_bytes()).hexdigest())


def shell_tests(shell):
    platform = read('target/linux/mediatek/filogic/base-files/lib/upgrade/platform.sh')
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        p = Path(tmp)
        (p / 'platform.sh').write_text(platform, newline='\n')
        script = r'''set -eu
. ./platform.sh
board_name() { echo "$BOARD"; }
get_magic_long() { echo d00dfeed; }
nand_do_platform_check() { [ "$1" = "$BOARD" ]; return "$CHECK_RC"; }
nand_do_upgrade() { printf '%s:%s\n' "${CI_KERN_UBIPART-unset}" "${CI_ROOT_UBIPART-unset}"; }
BOARD=xiaomi,redmi-router-ax6000-stock
CHECK_RC=0
platform_check_image dummy
CHECK_RC=7
if platform_check_image dummy; then echo 'accepted bad image'; exit 1; else rc=$?; fi
[ "$rc" = 7 ]
[ "$(platform_do_upgrade dummy)" = 'ubi_kernel:ubi' ]
BOARD=netcore,n60-pro
[ "$(platform_do_upgrade dummy)" = 'unset:unset' ]
BOARD=xiaomi,redmi-router-ax6000
[ "$(platform_do_upgrade dummy)" = 'unset:unset' ]
echo 'PASS: stock upgrade routes kernel/root separately; bad-image result preserved; N60 and merged AX6000 routes unchanged'
'''
        network = read('target/linux/mediatek/filogic/base-files/etc/board.d/02_network')
        network = network[network.index('mediatek_setup_interfaces()'):network.index('\nboard_config_update')]
        (p / 'network.sh').write_text(network, newline='\n')
        env = read('package/boot/uboot-envtools/files/mediatek_filogic')
        # Extract the case statement only; do not execute UCI file creation.
        env = env[env.index('case "$board" in'):env.index('\nconfig_load ubootenv')]
        (p / 'env.sh').write_text(env, newline='\n')
        script += r'''
. ./network.sh
ucidef_set_interfaces_lan_wan() { printf '%s:%s\n' "$1" "$2"; }
[ "$(mediatek_setup_interfaces xiaomi,redmi-router-ax6000-stock)" = 'lan2 lan3 lan4:wan' ]
[ "$(mediatek_setup_interfaces netcore,n60-pro)" = 'lan1 lan2 lan3 lan4:eth1' ]
find_mtd_index() {
    case "$1" in Nvram) echo "$NV";; Bdata) echo "$BD";; esac
}
ubootenv_add_uci_config() { printf 'env:%s:%s:%s:%s\n' "$1" "$2" "$3" "$4"; }
ubootenv_add_uci_sys_config() { printf 'bdata:%s:%s:%s:%s\n' "$1" "$2" "$3" "$4"; }
board=xiaomi,redmi-router-ax6000-stock
NV=2 BD=3
result=$( . ./env.sh )
[ "$result" = 'env:/dev/mtd2:0x0:0x10000:0x20000
bdata:/dev/mtd3:0x0:0x10000:0x20000' ]
NV=1 BD=2
result=$( . ./env.sh )
[ "$result" = 'env:/dev/mtd1:0x0:0x10000:0x20000
bdata:/dev/mtd2:0x0:0x10000:0x20000' ]
NV= BD=
[ -z "$( . ./env.sh )" ]
echo 'PASS: LAN/WAN mapping; environment labels with both MTD enumerations; no unsafe fallback for missing partitions'
'''
        (p / 'run.sh').write_text(script, newline='\n')
        subprocess.run([shell, 'run.sh'], cwd=p, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--firmware', type=Path)
    ap.add_argument('--shell', help='Run upgrade routing mocks using sh or Bash; no device access')
    ap.add_argument('--dtb', type=Path, help='Validate a compiled stock-layout DTB')
    args = ap.parse_args()
    check_source()
    test_dtb_validation()
    if args.shell:
        shell_tests(args.shell)
    if args.dtb:
        check_dtb(args.dtb.read_bytes())
        print('PASS: compiled device tree')
    if args.firmware:
        check_firmware(args.firmware.resolve())


if __name__ == '__main__':
    main()
