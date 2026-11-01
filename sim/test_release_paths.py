"""Submission naming, migrated inputs and case-sensitive include closure."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from xml.etree import ElementTree as ET

import release_path_check

ROOT = release_path_check.ROOT


class ReleasePathTests(unittest.TestCase):
    def test_release_names_and_historical_evidence(self):
        self.assertGreaterEqual(release_path_check.check(), 423)

    def test_invalid_names_and_case_collisions_rejected(self):
        release_path_check.validate_paths(['README.md', 'skill/README.md', 'license', 'core/src/main.c'])
        for name in ['Core/Src/main.c', 'docs/README.md', 'src/测试.c', 'src/main file.c',
                     '../outside.c', '/outside.c', 'src//main.c']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                release_path_check.validate_paths([name])
        with self.assertRaisesRegex(ValueError, 'case-colliding'):
            release_path_check.validate_paths(['README.md', 'readme.md'])

    def test_missing_migrated_input_and_changed_license_rejected(self):
        manifest = json.loads((ROOT / 'data/repository_path_map.json').read_text())
        paths = {x['public_path'] for x in manifest['renames']}
        paths.update(x['path'] for x in manifest['unchanged_evidence'])
        paths.add('data/repository_path_map.json')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in paths:
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, dest)
            release_path_check.check(root)
            source = root / 'src/stm32/gpio_pl_test/core/src/main.c'
            original = source.read_bytes()
            source.unlink()
            with self.assertRaisesRegex(ValueError, 'Migrated file identity mismatch'):
                release_path_check.check(root)
            source.write_bytes(original)
            entry = next(x for x in manifest['renames']
                         if x['public_path'].endswith('/licenses/openocd-0.12.0/copying'))
            license_path = root / entry['public_path']
            license_path.write_bytes(license_path.read_bytes() + b'\nchanged\n')
            with self.assertRaisesRegex(ValueError, 'Migrated file identity mismatch'):
                release_path_check.check(root)

    def test_both_keil_projects_have_resolvable_headers(self):
        compiler = shutil.which('gcc')
        if not compiler:
            self.skipTest('Install GCC for host-only preprocessing; not an ARM firmware build')
        for variant in ('gpio_pl_test', 'gpio_pl_test_led'):
            project = ROOT / 'src/stm32' / variant
            keil = project / 'mdk-arm/gpio_pl_test.uvprojx'
            xml = ET.parse(keil)
            includes = [p for n in xml.findall('.//IncludePath') if n.text for p in n.text.split(';')]
            sources = [n.text for n in xml.findall('.//FilePath') if n.text.endswith('.c')]
            self.assertEqual(len(sources), 21)
            for name in sources:
                with self.subTest(project=variant, source=name):
                    command = [compiler, '-E', '-DUSE_HAL_DRIVER', '-DSTM32G431xx']
                    for include in includes:
                        command.extend(['-I', str(keil.parent / include.replace('\\', '/'))])
                    # Avoid source/build outputs in either published project.
                    with tempfile.TemporaryDirectory() as folder:
                        command.extend([str(keil.parent / name.replace('\\', '/')),
                                        '-o', str(Path(folder) / 'headers.i')])
                        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
