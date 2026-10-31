"""FPGA evidence, external-IP checker and delivered RTL regression."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import fpga_check

ROOT = fpga_check.ROOT


class FpgaReleaseTests(unittest.TestCase):
    def test_published_files_and_derived_metrics(self):
        self.assertEqual(fpga_check.check(), 14)
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            manifest = json.loads((ROOT / 'data/fpga_manifest.json').read_text())
            inputs = [entry['path'] for entry in manifest['files']]
            inputs += ['data/fpga_manifest.json', 'data/fpga_metrics.json', 'data/fpga_metrics.csv']
            for relative in inputs:
                target = tmp / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            try:
                fpga_check.ROOT = tmp
                self.assertEqual(fpga_check.check(), 14)
                bit = tmp / 'build/fpga/zhidiao_observe_v5_led.bit'
                data = bit.read_bytes()
                bit.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
                with self.assertRaisesRegex(ValueError, 'FPGA identity mismatch'):
                    fpga_check.check()
            finally:
                fpga_check.ROOT = ROOT

    def test_constraints_and_bd_contract(self):
        source = ROOT / 'src/fpga/zhidiao_measure'
        tcl = (source / 'system_bd.tcl').read_text()
        for address in ('0x43C30000', '0x43C40000', '0x43C50000', '0x43C60000'):
            self.assertIn(address, tcl)
        self.assertIn('CONFIG.C_DOUT_DEFAULT {0x0000000F}', tcl)
        self.assertIn('CONFIG.C_GPIO_WIDTH {4}', tcl)
        self.assertIn('CONFIG.PCW_CLK0_FREQ {100000000}', tcl)
        self.assertIn('CONFIG.C_BAUDRATE {115200}', tcl)
        xdc = (source / 'linux_ov5640.srcs/constrs_1/new/zhidiao_measure.xdc').read_text()
        for pin in ('M18', 'M17', 'J14', 'K14', 'J18', 'H18'):
            self.assertIn('PACKAGE_PIN ' + pin, xdc)

    def test_external_ip_hash_and_vlnv_rejection(self):
        spec = importlib.util.spec_from_file_location('check_ip_repo', ROOT / 'build/fpga/check_ip_repo.py')
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            with self.assertRaises(FileNotFoundError):
                checker.check(tmp)
            manifest = json.loads((ROOT / 'data/fpga_external_ips.json').read_text())
            for ip in manifest['ips']:
                path = tmp / ip['directory'] / 'component.xml'
                path.parent.mkdir(parents=True)
                path.write_text('<component/>')
            with self.assertRaisesRegex(ValueError, 'VLNV mismatch'):
                checker.check(tmp)

    def test_external_ip_positive_then_tamper(self):
        spec = importlib.util.spec_from_file_location('check_ip_repo', ROOT / 'build/fpga/check_ip_repo.py')
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            (tmp / 'data').mkdir()
            ip = tmp / 'ip_repo/example'
            ip.mkdir(parents=True)
            component = ip / 'component.xml'
            component.write_text('<component xmlns="http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009">'
                                 '<vendor>example.org</vendor><library>user</library><name>demo</name>'
                                 '<version>1.0</version></component>')
            data = component.read_bytes()
            manifest = {'ips': [{'vlnv': 'example.org:user:demo:1.0', 'directory': 'example',
                                'files': [{'path': 'example/component.xml', 'bytes': len(data),
                                           'sha256': hashlib.sha256(data).hexdigest()}]}]}
            (tmp / 'data/fpga_external_ips.json').write_text(json.dumps(manifest))
            checker.ROOT = tmp
            self.assertEqual(checker.check(tmp / 'ip_repo'), 1)
            component.write_bytes(data + b'\n')
            with self.assertRaisesRegex(ValueError, 'IP content mismatch'):
                checker.check(tmp / 'ip_repo')

    def test_tcl_syntax_and_build_control_flow(self):
        tclsh = shutil.which('tclsh')
        if not tclsh:
            self.skipTest('Tcl interpreter is needed for build control-flow checks')
        for path in [ROOT / 'build/fpga/build.tcl', ROOT / 'src/fpga/zhidiao_measure/system_bd.tcl']:
            script = 'set f [open {' + str(path) + '} r]; set s [read $f]; close $f; if {![info complete $s]} {exit 1}\n'
            result = subprocess.run([tclsh], input=script, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            ip = tmp / 'ips'
            manifest = json.loads((ROOT / 'data/fpga_external_ips.json').read_text())
            for item in manifest['ips']:
                component = ip / item['directory'] / 'component.xml'
                component.parent.mkdir(parents=True)
                component.touch()
            for scenario, error in [('ok', ''), ('version', 'Use Vivado 2017.4'),
                                    ('missing_ip', 'Required IP not in catalog'),
                                    ('bd_failed', 'Delivered BD script failed'),
                                    ('synthesis', 'Synthesis did not complete'),
                                    ('implementation', 'Implementation did not complete'),
                                    ('timing', 'Negative max slack'),
                                    ('existing', 'Output already exists')]:
                output = tmp / scenario
                if scenario == 'existing':
                    output.mkdir()
                with self.subTest(scenario=scenario):
                    result = subprocess.run([tclsh, str(ROOT / 'sim/fpga/build_mock.tcl'),
                                             str(ROOT), scenario, str(output), str(ip)],
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 1 if error else 0, result.stdout + result.stderr)
                    if error:
                        self.assertIn(error, result.stderr)
                    else:
                        self.assertIn('BUILD_COMPLETE:', result.stdout)

    def test_rtl_behavior(self):
        compiler = os.environ.get('IVERILOG') or shutil.which('iverilog')
        runner = os.environ.get('VVP') or shutil.which('vvp')
        if not compiler or not runner:
            self.skipTest('Install Icarus Verilog (iverilog + vvp) for RTL simulation')
        with tempfile.TemporaryDirectory() as folder:
            image = str(Path(folder) / 'measure.vvp')
            command = [compiler]
            if os.environ.get('IVERILOG_BASE'):
                command += ['-B', os.environ['IVERILOG_BASE']]
            command += ['-g2012', '-s', 'measure_core_tb', '-o', image,
                        str(ROOT / 'sim/fpga/measure_core_tb.v'),
                        str(ROOT / 'src/fpga/zhidiao_measure/linux_ov5640.srcs/sources_1/new/zhidiao_measure_core.v')]
            compile_result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run([runner, image], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('ALL RTL CHECKS PASSED', result.stdout)
            print(result.stdout, end='')


if __name__ == '__main__':
    unittest.main()
