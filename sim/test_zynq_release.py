"""Public Zynq inputs, static build preflight and read-only SD file checks."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

import zynq_check

ROOT = zynq_check.ROOT


def builder():
    spec = importlib.util.spec_from_file_location('openocd_build', ROOT / 'build/openocd/build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ZynqReleaseTests(unittest.TestCase):
    def test_elf_static_and_arm_abi_checks(self):
        module = builder()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture.elf'
            data = bytearray(84)
            data[:7] = b'\x7fELF\x01\x01\x01'
            struct.pack_into('<H', data, 18, 40)
            struct.pack_into('<I', data, 28, 52)
            struct.pack_into('<I', data, 36, 0x05000400)
            struct.pack_into('<HH', data, 42, 32, 1)
            struct.pack_into('<I', data, 52, 1)
            path.write_bytes(data)
            self.assertEqual(module.elf_info(path), {'class': 32, 'machine': 40,
                                                    'static': True, 'arm_hard_float': True})
            struct.pack_into('<I', data, 52, 3)
            path.write_bytes(data)
            self.assertFalse(module.elf_info(path)['static'])
            struct.pack_into('<I', data, 36, 0)
            path.write_bytes(data)
            self.assertFalse(module.elf_info(path)['arm_hard_float'])
            path.write_bytes(b'\x7fELF')
            with self.assertRaisesRegex(ValueError, 'Expected an ELF'):
                module.elf_info(path)

    def test_public_sources_licenses_and_image_inventory(self):
        self.assertEqual(zynq_check.check(), 20)
        info = json.loads((ROOT / 'data/zynq_linux_manifest.json').read_text())
        self.assertEqual(len(info['excluded_secrets']), 2)
        self.assertNotEqual(info['fit_components']['image.ub']['/images/ramdisk@0'],
                            info['fit_components']['image_fixed.ub']['/images/ramdisk@0'])

    def test_build_rejects_modified_source_and_preserves_existing_output(self):
        module = builder()
        module.checked_sources()
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            args = argparse.Namespace(output=tmp, native=True, host=None, jobs=1, timeout_s=30)
            with self.assertRaisesRegex(ValueError, 'Output already exists'):
                module.build(args)
            sources = tmp / 'src/third_party/openocd'
            sources.mkdir(parents=True)
            for name in module.ARCHIVES:
                shutil.copyfile(ROOT / 'src/third_party/openocd' / name, sources / name)
            target = sources / 'libusb-1.0.30.tar.bz2'
            data = target.read_bytes()
            target.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
            module.ROOT = tmp
            with self.assertRaisesRegex(ValueError, 'Source archive SHA mismatch'):
                module.checked_sources()

    def test_readonly_file_checker_and_hash_failure(self):
        shell = shutil.which('sh')
        if not shell:
            self.skipTest('POSIX shell needed for read-only board-script checks')
        script = ROOT / 'board/zynq/check_files.sh'
        syntax = subprocess.run([shell, '-n', str(script)], capture_output=True, text=True, timeout=10)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        with tempfile.TemporaryDirectory() as folder:
            sd = Path(folder)
            for relative in ['tools/openocd/bin/openocd',
                             'tools/openocd/share/openocd/scripts/interface/stlink.cfg',
                             'tools/openocd/share/openocd/scripts/target/stm32g4x.cfg']:
                path = sd / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture; must never execute\n')
            (sd / 'tools/openocd/bin/openocd').chmod(0o755)
            bit = sd / 'pl/zhidiao_observe_v5_led.bit'
            bit.parent.mkdir()
            shutil.copyfile(ROOT / 'build/fpga/zhidiao_observe_v5_led.bit', bit)
            def run():
                return subprocess.run([shell, str(script), str(sd)], capture_output=True, text=True, timeout=10)
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('v5_file_sha256\tMATCH', result.stdout)
            self.assertIn('hardware_result\tNOT_TESTED', result.stdout)
            bit.write_bytes(b'not the approved bitstream')
            result = run()
            self.assertEqual(result.returncode, 1)
            self.assertIn('MISMATCH_OR_UNAVAILABLE', result.stdout)
            (sd / 'tools/openocd/bin/openocd').unlink()
            result = run()
            self.assertEqual(result.returncode, 1)
            self.assertIn('openocd_executable\tMISSING', result.stdout)


if __name__ == '__main__':
    unittest.main()
