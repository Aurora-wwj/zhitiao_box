"""LED variant identity, Agent compatibility and host-only HAL behavior tests."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

import stm32_led_check

ROOT = stm32_led_check.ROOT


class STM32LEDReleaseTests(unittest.TestCase):
    def test_complete_lowercase_project_and_supplied_source_identity(self):
        self.assertEqual(stm32_led_check.check(), 92)

    def test_changed_source_and_escaped_keil_reference_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data').mkdir()
            manifest_file = root / 'data/stm32_led_manifest.json'
            shutil.copyfile(ROOT / 'data/stm32_led_manifest.json', manifest_file)
            project = root / stm32_led_check.PROJECT
            shutil.copytree(ROOT / stm32_led_check.PROJECT, project)
            self.assertEqual(stm32_led_check.check(root), 92)
            source = project / 'core/src/main.c'
            original = source.read_bytes()
            source.write_bytes(original.replace(b'HAL_Delay(500)', b'HAL_Delay(300)'))
            with self.assertRaisesRegex(ValueError, 'LED file identity mismatch'):
                stm32_led_check.check(root)
            source.write_bytes(original)
            file = project / 'mdk-arm/gpio_pl_test.uvprojx'
            tree = ET.parse(file)
            tree.find('.//FilePath').text = '../../../outside.s'
            tree.write(file, encoding='utf-8', xml_declaration=True)
            manifest = json.loads(manifest_file.read_text())
            entry = next(x for x in manifest['files'] if x['path'].endswith('.uvprojx'))
            entry['public_sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
            manifest_file.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'LED Keil reference outside project'):
                stm32_led_check.check(root)

    def test_existing_agent_discovers_variant_target_and_output(self):
        program = '''from pathlib import Path
from zhidiao_agent.deployment import DeploymentConfig
from zhidiao_agent.tools.artifacts import keil_target, source_manifest
from zhidiao_agent.editing import SourceEditor
p = Path("src/stm32/gpio_pl_test_led").resolve()
c = DeploymentConfig(allowed_roots=(str(p),), project_file="mdk-arm/gpio_pl_test.uvprojx", target="GPIO_PL_Test")
file, target, artifact = keil_target(p, c)
assert target == "GPIO_PL_Test"
assert file == p / "mdk-arm/gpio_pl_test.uvprojx"
assert artifact == p / "mdk-arm/gpio_pl_test/gpio_pl_test.hex"
sources = SourceEditor(str(p), ("core/src/main.c",)).snapshot()
assert sources.success
inputs = source_manifest(p)
assert sources.data["sources"]["core/src/main.c"]["sha256"] == inputs["core/src/main.c"]
print("AGENT_LED_PROJECT_DISCOVERY_PASSED")
'''
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src/agent/src'))
        result = subprocess.run([sys.executable, '-B', '-c', program], cwd=ROOT,
                                env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('AGENT_LED_PROJECT_DISCOVERY_PASSED', result.stdout)

    def test_supplied_main_mirrors_eight_leds_on_the_same_toggle_loop(self):
        compiler = os.environ.get('CC') or shutil.which('cc') or shutil.which('gcc')
        if not compiler:
            self.skipTest('Install a host C compiler for the HAL substitute test')
        project = ROOT / stm32_led_check.PROJECT
        source = (project / 'core/src/main.c').read_text(encoding='utf-8')
        header = (project / 'core/inc/main.h').read_text(encoding='utf-8')
        helpers = re.search(r'/\* USER CODE BEGIN 0 \*/(.*?)/\* USER CODE END 0 \*/', source, re.S)[1]
        main = source[source.index('int main(void)'):source.index('/**\n  * @brief System Clock Configuration')]
        main = main.replace('int main(void)', 'static void firmware_main(void)', 1)
        defines = '\n'.join(re.findall(r'^#define PL_TEST_OUT_(?:Pin|GPIO_Port)\s+[^\r\n]+', header, re.M))
        self.assertEqual(len(defines.splitlines()), 2)
        harness = (ROOT / 'sim/stm32_led/led_host_check.c').read_text(encoding='utf-8')
        harness = harness.replace('/* INSERT_PL_DEFINES */', defines)
        harness = harness.replace('/* INSERT_HELPERS */', helpers)
        harness = harness.replace('/* INSERT_FIRMWARE_MAIN */', main)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            code = path / 'led_check.c'
            code.write_text(harness, encoding='utf-8')
            binary = path / ('led_check.exe' if os.name == 'nt' else 'led_check')
            build = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O0',
                                    str(code), '-o', str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('LED_HOST_CHECKS_PASSED', run.stdout)
            print(run.stdout, end='')


if __name__ == '__main__':
    unittest.main()
