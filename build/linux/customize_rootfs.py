"""Repack the received ALINX FIT with only the eth0 rootfs configuration changed.

Offline file operations only: no rootfs extraction, board access or bootloader build.
Requires Python 3.13 and U-Boot mkimage/dtc for repack; inspect uses the stdlib.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess

BASE_SHA = '224b9b884352a931244541017024fdbff69297feeaadab2b1e5eb0d030bb0344'
COMPONENTS = {'kernel@0': 'kernel', 'fdt@0': 'flat_dt', 'ramdisk@0': 'ramdisk'}
OUTPUT_NAMES = {'kernel@0': 'kernel.bin', 'fdt@0': 'system.dtb', 'ramdisk@0': 'ramdisk.cpio.gz'}
LIMIT = 64 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fit_nodes(data):
    """Read the inline-data FIT format used by the received image; do not execute it."""
    if len(data) < 40 or len(data) > LIMIT:
        raise ValueError('Invalid FIT size')
    magic, total, start, strings_start, reserve, version, _, _, strings_size, size = struct.unpack_from('>10I', data)
    if (magic != 0xd00dfeed or version != 17 or total > len(data)
            or not 40 <= start < start + size <= total
            or not 40 <= strings_start <= strings_start + strings_size <= total
            or reserve < 40 or data[reserve:reserve + 16] != bytes(16)):
        raise ValueError('Unsupported or malformed FIT header')
    strings = data[strings_start:strings_start + strings_size]
    pos, end, stack, nodes = start, start + size, [], {}
    while pos + 4 <= end:
        token = struct.unpack_from('>I', data, pos)[0]
        pos += 4
        if token == 1:
            zero = data.find(b'\0', pos, end)
            if zero < 0:
                raise ValueError('Unterminated FIT node')
            name = data[pos:zero].decode('ascii')
            if name and not re.fullmatch(r'[A-Za-z0-9_#.,+@-]+', name):
                raise ValueError('Unsupported FIT node name')
            stack.append(name)
            path = '/'.join(stack)
            if path in nodes:
                raise ValueError('Duplicate FIT node')
            nodes[path] = {}
            pos = (zero + 4) & ~3
        elif token == 2:
            if not stack:
                raise ValueError('Unbalanced FIT nodes')
            stack.pop()
        elif token == 3:
            if not stack or pos + 8 > end:
                raise ValueError('Invalid FIT property')
            length, offset = struct.unpack_from('>II', data, pos)
            pos += 8
            zero = strings.find(b'\0', offset)
            if offset >= len(strings) or zero < 0 or pos + length > end:
                raise ValueError('FIT property out of bounds')
            name = strings[offset:zero].decode('ascii')
            props = nodes['/'.join(stack)]
            if not re.fullmatch(r'[A-Za-z0-9_#.,+@-]+', name) or name in props:
                raise ValueError('Invalid or duplicate FIT property')
            props[name] = data[pos:pos + length]
            pos = (pos + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            if stack:
                raise ValueError('Unbalanced FIT tree')
            return nodes
        else:
            raise ValueError('Invalid FIT token')
    raise ValueError('Missing FIT end token')


def components(nodes):
    if nodes.get('/configurations', {}).get('default') != b'conf@1\0':
        raise ValueError('Unsupported FIT boot configuration')
    conf = nodes.get('/configurations/conf@1', {})
    result = {}
    for name, kind in COMPONENTS.items():
        path = '/images/' + name
        node = nodes.get(path, {})
        if (node.get('type') != kind.encode() + b'\0' or node.get('compression') != b'none\0'
                or node.get('arch') != b'arm\0' or 'data' not in node
                or conf.get('fdt' if kind == 'flat_dt' else kind) != name.encode() + b'\0'):
            raise ValueError('Unsupported FIT component: ' + name)
        hashes = [value for key, value in nodes.items() if key.startswith(path + '/hash')]
        if not hashes or any(h.get('algo') != b'sha1\0'
                             or h.get('value') != hashlib.sha1(node['data']).digest() for h in hashes):
            raise ValueError('FIT component hash mismatch: ' + name)
        result[name] = node['data']
    if {p for p in nodes if p.startswith('/images/') and p.count('/') == 2} != set('/images/' + n for n in COMPONENTS):
        raise ValueError('Unexpected FIT image component')
    if any('/signature' in path or 'data-offset' in value or 'data-position' in value for path, value in nodes.items()):
        raise ValueError('Signed or external-data FIT is not supported')
    return result


def cpio_records(data):
    pos, entries, seen = 0, [], set()
    while pos + 110 <= len(data):
        start = pos
        header = data[pos:pos + 110]
        if header[:6] != b'070701':
            raise ValueError('Only newc CPIO is supported')
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        length, namesize = fields[6], fields[11]
        if namesize < 1 or pos + 110 + namesize > len(data):
            raise ValueError('Invalid CPIO name size')
        encoded = data[pos + 110:pos + 110 + namesize]
        if encoded[-1:] != b'\0':
            raise ValueError('Unterminated CPIO name')
        original_name = encoded[:-1].decode('utf-8')
        name = original_name[2:] if original_name.startswith('./') else original_name
        if PurePosixPath(name).is_absolute() or '..' in name.split('/') or name in seen:
            raise ValueError('Unsafe or duplicate CPIO path')
        seen.add(name)
        payload_start = (pos + 110 + namesize + 3) & ~3
        pos = (payload_start + length + 3) & ~3
        if pos > len(data):
            raise ValueError('Truncated CPIO member')
        entries.append((name, fields, data[payload_start:payload_start + length], data[start:pos], encoded))
        if name == 'TRAILER!!!':
            if any(data[pos:]):
                raise ValueError('Unexpected appended CPIO data')
            return entries
    raise ValueError('Missing CPIO trailer')


def unpack_ramdisk(payload):
    # Keep device nodes, symlinks, owners, modes and hardlinks as archive records.
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('Ramdisk exceeds supported size')
    return data


def customize_cpio(data):
    result, changed = [], 0
    for name, fields, payload, raw, encoded in cpio_records(data):
        if name == 'etc/network/interfaces':
            if not stat.S_ISREG(fields[1]) or fields[4] != 1:
                raise ValueError('Network configuration must be a regular unlinked file')
            text = payload.decode('utf-8')
            replacement = 'iface eth0 inet static\n    address 192.168.10.2\n    netmask 255.255.255.0'
            text, count = re.subn(r'(?m)^iface eth0 inet dhcp[ \t]*$', replacement, text)
            if count != 1 or not re.search(r'(?m)^auto eth0\s*$', text):
                raise ValueError('Expected one enabled DHCP eth0 stanza')
            new = text.encode('utf-8')
            fields = list(fields)
            fields[6] = len(new)
            raw = b'070701' + b''.join(f'{value:08x}'.encode() for value in fields) + encoded
            raw += bytes((-len(raw)) % 4)
            raw += new + bytes((-len(new)) % 4)
            changed += 1
        result.append(raw)
    if changed != 1:
        raise ValueError('Missing network configuration')
    result = b''.join(result)
    return result + bytes((-len(result)) % 512)


def its_text(nodes):
    lines = ['/dts-v1/;', '/ {']
    def emit(path, depth):
        for name, value in nodes[path].items():
            if name == 'data' and path.startswith('/images/'):
                line = f'{name} = /incbin/("{OUTPUT_NAMES[path.rsplit("/", 1)[1]]}");'
            elif name == 'value' and '/hash' in path:
                continue  # mkimage recalculates component digests.
            else:
                line = name + ' = [' + value.hex(' ') + '];' if value else name + ';'
            lines.append('  ' * depth + line)
        for child in nodes:
            if child and child.rsplit('/', 1)[0] == path:
                lines.append('  ' * depth + child.rsplit('/', 1)[1] + ' {')
                emit(child, depth + 1)
                lines.append('  ' * depth + '};')
    emit('', 1)
    lines.append('};')
    return '\n'.join(lines) + '\n'


def inspect(path):
    raw = Path(path).read_bytes()
    parts = components(fit_nodes(raw))
    entries = {n: payload for n, _, payload, _, _ in cpio_records(unpack_ramdisk(parts['ramdisk@0']))}
    network = entries.get('etc/network/interfaces', b'').decode('utf-8')
    return {'bytes': len(raw), 'sha256': sha(raw),
            'components': {n: {'bytes': len(v), 'sha256': sha(v)} for n, v in parts.items()},
            'rootfs_issue': entries.get('etc/issue', b'').decode('utf-8').strip(),
            'eth0_static_192_168_10_2': 'iface eth0 inet static' in network
            and re.search(r'(?m)^\s+address 192\.168\.10\.2\s*$', network) is not None,
            'embedded_dropbear_host_key': any(n.startswith('etc/dropbear/') and n.endswith('_key') for n in entries)}


def repack(source, output, mkimage='mkimage', *, expected_sha=BASE_SHA):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Output already exists; select a new directory')
    raw = source.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError('Base image SHA mismatch; use the received image.ub')
    nodes = fit_nodes(raw)
    parts = components(nodes)
    old_cpio = unpack_ramdisk(parts['ramdisk@0'])
    if any(n.startswith('etc/dropbear/') and n.endswith('_key') for n, *_ in cpio_records(old_cpio)):
        raise ValueError('Base image contains a device-specific SSH host key')
    parts['ramdisk@0'] = gzip.compress(customize_cpio(old_cpio), compresslevel=9, mtime=0)
    executable = shutil.which(mkimage)
    if not executable or not shutil.which('dtc'):
        raise ValueError('Install U-Boot mkimage and device-tree-compiler (dtc)')
    executable = str(Path(executable).resolve())
    output.mkdir(parents=True, exist_ok=False)
    for name, value in parts.items():
        (output / OUTPUT_NAMES[name]).write_bytes(value)
    (output / 'image.its').write_text(its_text(nodes), encoding='ascii')
    # Stable FIT timestamps; legacy kernel/FDT and load/entry/configuration are kept.
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(struct.unpack('>I', nodes['']['timestamp'])[0]))
    built = subprocess.run([executable, '-f', 'image.its', 'image_fixed.ub'], cwd=output,
                           env=env, capture_output=True, text=True, timeout=60)
    (output / 'mkimage.log').write_text(built.stdout + built.stderr)
    if built.returncode:
        raise ValueError('mkimage failed; inspect the new output directory log')
    result = inspect(output / 'image_fixed.ub')
    rebuilt_nodes = fit_nodes((output / 'image_fixed.ub').read_bytes())
    for path, props in nodes.items():
        for name, value in props.items():
            if name in {'timestamp', 'data', 'value'}:
                continue
            if rebuilt_nodes.get(path, {}).get(name) != value:
                raise ValueError('FIT metadata changed: ' + path + '/' + name)
    for name in ('kernel@0', 'fdt@0'):
        if result['components'][name]['sha256'] != sha(parts[name]):
            raise ValueError('Kernel or FDT changed during repack')
    if not result['eth0_static_192_168_10_2'] or result['embedded_dropbear_host_key']:
        raise ValueError('Unexpected customized rootfs state')
    result.update(base_sha256=sha(raw), changed_rootfs_paths=['etc/network/interfaces'],
                  boot_bin_rebuilt=False, board_tested=False,
                  mkimage_version=subprocess.check_output([executable, '-V'], text=True).strip())
    (output / 'build_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    view = sub.add_parser('inspect')
    view.add_argument('image', type=Path)
    build = sub.add_parser('repack')
    build.add_argument('image', type=Path)
    build.add_argument('--output', type=Path, required=True)
    build.add_argument('--mkimage', default='mkimage')
    args = parser.parse_args()
    try:
        result = inspect(args.image) if args.command == 'inspect' else repack(args.image, args.output, args.mkimage)
    except (OSError, ValueError, struct.error, UnicodeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'FAILED: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
