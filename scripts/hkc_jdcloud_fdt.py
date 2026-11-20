"""Strict FDT reader shared from the previously audited HKC host validator."""
import struct

def need(ok, message):
    if not ok:
        raise ValueError(message)


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
