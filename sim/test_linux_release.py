"""HDF identity and offline rootfs/FIT customization; never run a board image."""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import unittest

import linux_check

ROOT = linux_check.ROOT
spec = importlib.util.spec_from_file_location('customize_rootfs', ROOT / 'build/linux/customize_rootfs.py')
custom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(custom)


def cpio(members):
    result = b''
    for index, (name, mode, payload, links) in enumerate(members + [('TRAILER!!!', 0, b'', 1)]):
        encoded = name.encode() + b'\0'
        fields = [index, mode, 12, 34, links, 123456, len(payload), 0, 0, 1, 3, len(encoded), 0]
        entry = b'070701' + b''.join(f'{n:08x}'.encode() for n in fields) + encoded
        entry += bytes((-len(entry)) % 4)
        entry += payload + bytes((-len(payload)) % 4)
        result += entry
    return result + bytes((-len(result)) % 512)


def fixture_cpio():
    return cpio([('.', stat.S_IFDIR | 0o755, b'', 2),
                 ('etc/network/interfaces', stat.S_IFREG | 0o644,
                  b'auto lo\niface lo inet loopback\nauto eth0\niface eth0 inet dhcp\niface eth1 inet dhcp\n', 1),
                 ('dev/null', stat.S_IFCHR | 0o666, b'', 1),
                 ('bin/sh', stat.S_IFLNK | 0o777, b'busybox', 1),
                 ('etc/issue', stat.S_IFREG | 0o644, b'PetaLinux 2017.4\n', 1)])


def fixture_fit():
    nodes = {'': {'timestamp': struct.pack('>I', 1571389692), '#address-cells': struct.pack('>I', 1)}, '/images': {}}
    payloads = {'kernel@0': b'kernel fixture, never executed', 'fdt@0': b'device tree fixture',
                'ramdisk@0': gzip.compress(fixture_cpio(), mtime=0)}
    for name, kind in custom.COMPONENTS.items():
        path = '/images/' + name
        nodes[path] = {'type': kind.encode() + b'\0', 'compression': b'none\0', 'arch': b'arm\0', 'data': payloads[name]}
        nodes[path + '/hash@1'] = {'algo': b'sha1\0', 'value': hashlib.sha1(payloads[name]).digest()}
    nodes['/configurations'] = {'default': b'conf@1\0'}
    nodes['/configurations/conf@1'] = {'kernel': b'kernel@0\0', 'fdt': b'fdt@0\0', 'ramdisk': b'ramdisk@0\0'}
    names = list(dict.fromkeys(n for props in nodes.values() for n in props))
    strings = b''
    offsets = {}
    for name in names:
        offsets[name] = len(strings)
        strings += name.encode() + b'\0'
    def node(path):
        name = path.rsplit('/', 1)[-1].encode() + b'\0'
        data = struct.pack('>I', 1) + name + bytes((-len(name)) % 4)
        for key, value in nodes[path].items():
            data += struct.pack('>III', 3, len(value), offsets[key]) + value + bytes((-len(value)) % 4)
        for child in nodes:
            if child and child.rsplit('/', 1)[0] == path:
                data += node(child)
        return data + struct.pack('>I', 2)
    structure = node('') + struct.pack('>I', 9)
    return (struct.pack('>10I', 0xd00dfeed, 56 + len(structure) + len(strings), 56,
                        56 + len(structure), 40, 17, 16, 0, len(strings), len(structure))
            + bytes(16) + structure + strings)


class LinuxReleaseTests(unittest.TestCase):
    def test_current_hdf_and_linux_scope(self):
        self.assertEqual(linux_check.check(), 10)
        data = json.loads((ROOT / 'data/linux_platform.json').read_text())
        self.assertEqual(data['runtime_version']['kernel'], '4.9.0-xilinx')
        self.assertFalse(data['source_level_petalinux_rebuild_claimed'])

    def test_changed_hdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = json.loads((ROOT / 'data/linux_platform.json').read_text())
            (root / 'data').mkdir()
            (root / 'data/linux_platform.json').write_text(json.dumps(manifest))
            path = root / manifest['hardware_handoff']['path']
            path.parent.mkdir(parents=True)
            path.write_bytes((ROOT / manifest['hardware_handoff']['path']).read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, 'HDF identity mismatch'):
                linux_check.check(root)

    def test_network_only_change_preserves_special_files_and_metadata(self):
        old = {n: (fields, payload, raw) for n, fields, payload, raw, _ in custom.cpio_records(fixture_cpio())}
        new = {n: (fields, payload, raw) for n, fields, payload, raw, _ in custom.cpio_records(custom.customize_cpio(fixture_cpio()))}
        self.assertEqual(set(old), set(new))
        for name in old:
            if name != 'etc/network/interfaces':
                self.assertEqual(old[name], new[name], name)
        self.assertIn(b'iface eth0 inet static\n    address 192.168.10.2\n    netmask 255.255.255.0', new['etc/network/interfaces'][1])
        self.assertIn(b'iface eth1 inet dhcp', new['etc/network/interfaces'][1])
        self.assertEqual([v for i, v in enumerate(old['etc/network/interfaces'][0]) if i != 6],
                         [v for i, v in enumerate(new['etc/network/interfaces'][0]) if i != 6])

    def test_bad_or_unsafe_cpio_and_linked_network_file_rejected(self):
        for data in (b'bad', fixture_cpio()[:120], cpio([('../outside', stat.S_IFREG, b'x', 1)])):
            with self.subTest(data=data[:12]), self.assertRaises(ValueError):
                custom.cpio_records(data)
        with self.assertRaisesRegex(ValueError, 'Missing network'):
            custom.customize_cpio(cpio([]))
        linked = cpio([('etc/network/interfaces', stat.S_IFLNK | 0o777, b'/outside', 1)])
        with self.assertRaisesRegex(ValueError, 'regular unlinked file'):
            custom.customize_cpio(linked)

    def test_fit_hash_bad_base_and_existing_output_rejected(self):
        data = fixture_fit()
        nodes = custom.fit_nodes(data)
        custom.components(nodes)
        nodes['/images/kernel@0']['data'] = b'changed'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            custom.components(nodes)
        with self.assertRaises(ValueError):
            custom.fit_nodes(data[:60])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'image.ub'
            source.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'Output already exists'):
                custom.repack(source, root)
            with self.assertRaisesRegex(ValueError, 'Base image SHA mismatch'):
                custom.repack(source, root / 'new')
            self.assertFalse((root / 'new').exists())

    def test_actual_mkimage_repack_and_reproducibility(self):
        if not shutil.which('mkimage') or not shutil.which('dtc'):
            self.skipTest('Install U-Boot mkimage and dtc for offline FIT repack')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = fixture_fit()
            source = root / 'input.ub'
            source.write_bytes(data)
            original = custom.inspect(source)
            first = custom.repack(source, root / 'first', expected_sha=custom.sha(data))
            second = custom.repack(source, root / 'second', expected_sha=custom.sha(data))
            self.assertEqual(first['sha256'], second['sha256'])
            for name in ('kernel@0', 'fdt@0'):
                self.assertEqual(first['components'][name], original['components'][name])
            self.assertTrue(first['eth0_static_192_168_10_2'])
            self.assertFalse(first['embedded_dropbear_host_key'])
            self.assertFalse(first['board_tested'])
            self.assertFalse(first['boot_bin_rebuilt'])
