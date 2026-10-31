"""Check the licensed public Zynq inputs without executing ARM programs/images."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'dropbear_rsa_host_key', 'id_rsa', 'id_ed25519', 'id_ecdsa'}


def check():
    manifest = json.loads((ROOT / 'data/zynq_linux_manifest.json').read_text())
    for entry in manifest['published_files']:
        path = (ROOT / entry['path']).resolve(strict=True)
        if not path.is_relative_to(ROOT):
            raise ValueError('Public Zynq input escapes release directory')
        data = path.read_bytes()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError(f"Zynq source/license SHA mismatch: {entry['path']}")
    for filename, top in [('openocd-0.12.0.tar.gz', 'openocd-0.12.0'),
                          ('libusb-1.0.30.tar.bz2', 'libusb-1.0.30')]:
        archive_path = ROOT / 'src/third_party/openocd' / filename
        with tarfile.open(archive_path) as archive:
            names = set()
            for member in archive:
                path = PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or path.parts[0] != top:
                    raise ValueError('Unsafe source-archive member')
                if not (member.isfile() or member.isdir()):
                    raise ValueError('Unexpected link/device in source archive')
                if path.name in FORBIDDEN:
                    raise ValueError('Private key file in public source archive')
                names.add(member.name)
            if top + '/COPYING' not in names or top + '/configure' not in names:
                raise ValueError('Source archive missing license or configure input')
    components = manifest['fit_components']
    for name in ('/images/kernel@0', '/images/fdt@0'):
        if components['image.ub'][name] != components['image_fixed.ub'][name]:
            raise ValueError('Unexpected kernel/device-tree difference')
    comparison = manifest['deployed_script_comparison']
    if comparison['matched_files'] != 887 or comparison['mismatches']:
        raise ValueError('Uploaded deployment scripts do not match source')
    for name in ('BOOT.BIN', 'image.ub', 'image_fixed.ub', 'GPIO1.hex', 'arm_hello'):
        if any((ROOT / 'board/zynq').rglob(name)):
            raise ValueError(f'Unreviewed historical artifact in public board folder: {name}')
    return len(manifest['published_files'])


if __name__ == '__main__':
    print(f'PASS: {check()} Zynq source/license files; source archives and exclusion policy checked')
