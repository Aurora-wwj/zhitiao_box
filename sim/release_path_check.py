"""Check published names and preserve the provenance of the path-only migration."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# These are the two explicit README spellings in the official directory example.
OFFICIAL_NAMES = {'README.md', 'skill/README.md'}


def validate_paths(paths):
    seen = set()
    for name in paths:
        parts = name.split('/')
        if (not name or PurePosixPath(name).is_absolute() or any(p in ('', '.', '..') for p in parts)
                or (name not in OFFICIAL_NAMES and any(not re.fullmatch(r'[a-z0-9_.-]+', p) for p in parts))):
            raise ValueError('Noncompliant release path: ' + name)
        key = name.casefold()
        if key in seen:
            raise ValueError('Duplicate or case-colliding release path: ' + name)
        seen.add(key)


def public_files(root):
    if (root / '.git').exists():
        result = subprocess.run(['git', '-C', str(root), 'ls-files', '--cached', '--others',
                                 '--exclude-standard', '-z'], check=True, capture_output=True)
        return sorted({p for p in result.stdout.decode('utf-8').split('\0') if p and (root / p).exists()})
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
                  and not any(s in {'.git', '__pycache__', '.venv', '.zhidiao'} for s in p.relative_to(root).parts))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(root=ROOT):
    root = Path(root).resolve()
    names = public_files(root)
    validate_paths(names)
    if any((root / name).is_symlink() for name in names):
        raise ValueError('Release inputs must not be symbolic links')
    manifest = json.loads((root / 'data/repository_path_map.json').read_text(encoding='utf-8'))
    entries = manifest['renames']
    originals = [entry['source_path'] for entry in entries]
    published = [entry['public_path'] for entry in entries]
    if len(entries) != 123 or len(set(originals)) != len(entries) or len(set(published)) != len(entries):
        raise ValueError('Incomplete path migration mapping')
    validate_paths(published)
    stm32_adaptations = set()
    for entry in entries:
        old, new = entry['source_path'], entry['public_path']
        if old == new or new != old.lower():
            raise ValueError('Incorrect lowercase mapping: ' + old)
        path = root / new
        if not path.is_file() or digest(path) != entry['public_sha256']:
            raise ValueError('Migrated file identity mismatch: ' + new)
        if old.startswith('src/third_party/openocd/licenses/') and entry['source_sha256'] != entry['public_sha256']:
            raise ValueError('Upstream license contents changed: ' + new)
        if old.startswith('src/stm32/gpio_pl_test/') and entry['source_sha256'] != entry['public_sha256']:
            stm32_adaptations.add(new.removeprefix('src/stm32/gpio_pl_test/'))
    if stm32_adaptations != {'gpio_pl_test.ioc', 'mdk-arm/gpio_pl_test.uvprojx',
                             'drivers/stm32g4xx_hal_driver/inc/stm32g4xx_hal_def.h'}:
        raise ValueError('Unexpected STM32 content change during path migration')
    for entry in manifest['unchanged_evidence']:
        if digest(root / entry['path']) != entry['sha256']:
            raise ValueError('Historical evidence changed: ' + entry['path'])
    return len(names)


if __name__ == '__main__':
    print(f'PASS: {check()} published paths; lowercase naming and historical evidence preserved')
