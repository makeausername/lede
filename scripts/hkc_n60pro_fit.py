"""Stock MediaTek boot verifier binding: hash exactly SquashFS bytes_used.

The bootloader reads bytes_used before verifying /rootfs; hashing padded tar
member length passes a RAM-only check but fails the actual flash boot check.
Only embedded-data FITs are supported. Existing image nodes remain byte exact.
"""
import hashlib
import struct
import zlib
from hkc_n60pro_image import need, fdt, text


def rootfs_size(root):
    need(len(root) >= 96 and root[:4] == b'hsqs', 'invalid SquashFS superblock')
    size, = struct.unpack_from('<Q', root, 40)
    need(96 <= size <= len(root) and size <= 0xffffffff, 'invalid SquashFS bytes_used')
    return size


def rootfs_properties(root):
    size = rootfs_size(root)
    data = root[:size]
    return {
        '/rootfs': {'size': struct.pack('>I', size)},
        '/rootfs/hash-1': {'algo': b'crc32\0', 'value': struct.pack('>I', zlib.crc32(data) & 0xffffffff)},
        '/rootfs/hash-2': {'algo': b'sha1\0', 'value': hashlib.sha1(data).digest()},
    }


def check_rootfs_fit(kernel, root):
    nodes = fdt(kernel)
    expected = rootfs_properties(root)
    actual = {k: v for k, v in nodes.items() if k == '/rootfs' or k.startswith('/rootfs/')}
    need(actual == expected, 'FIT rootfs size/CRC32/SHA1 binding missing or incorrect')
    return {'bytes_used': rootfs_size(root), 'padded_bytes': len(root),
            'crc32': expected['/rootfs/hash-1']['value'].hex(),
            'sha1': expected['/rootfs/hash-2']['value'].hex()}


def bind_rootfs(kernel, root):
    nodes = fdt(kernel)
    if '/rootfs' in nodes:
        check_rootfs_fit(kernel, root)  # Never silently repair an incorrect existing binding.
        return kernel
    header = list(struct.unpack_from('>10I', kernel))
    magic, total, st, strings, reserve, version, last, cpu, names_size, st_size = header
    need(total == len(kernel) and version == 17 and last <= 17 and
         40 <= reserve < st and st + st_size == strings and
         strings + names_size <= total, 'unsupported FIT block layout')
    need(kernel[st + st_size - 8:st + st_size] == struct.pack('>II', 2, 9),
         'unsupported FIT structure ending')
    for props in nodes.values():
        need(not {'data-offset', 'data-position', 'data-size'} & props.keys(), 'external FIT data unsupported')
    names = bytearray(kernel[strings:strings + names_size])
    extra = bytearray()
    def word(value): extra.extend(struct.pack('>I', value))
    def pad():
        while len(extra) % 4: extra.append(0)
    def node(name, props):
        word(1); extra.extend(name.encode() + b'\0'); pad()
        for key, value in props.items():
            offset = len(names); names.extend(key.encode() + b'\0')
            word(3); word(len(value)); word(offset); extra.extend(value); pad()
    wanted = rootfs_properties(root)
    node('rootfs', wanted['/rootfs'])
    for name in ('hash-1', 'hash-2'):
        node(name, wanted['/rootfs/' + name]); word(2)
    word(2)
    structure = kernel[st:st + st_size - 8] + extra + struct.pack('>II', 2, 9)
    header[1] = st + len(structure) + len(names)
    header[3] = st + len(structure)
    header[8] = len(names); header[9] = len(structure)
    result = struct.pack('>10I', *header) + kernel[40:st] + structure + names
    need(fdt(result) == {**nodes, **wanted}, 'FIT mutation changed existing nodes')
    check_rootfs_fit(result, root)
    return bytes(result)
