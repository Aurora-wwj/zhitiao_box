"""Read-only identity and Keil-reference checks for the supplied LED variant."""

import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'src/stm32/gpio_pl_test_led'
MAIN_SHA = '053697e2f914f435bae950c1529dd6b68af01532c12b94318ae622115a7debfd'


def check(root=ROOT):
    root = Path(root).resolve()
    project = root / PROJECT
    manifest = json.loads((root / 'data/stm32_led_manifest.json').read_text(encoding='utf-8'))
    if (manifest['public_root'] != PROJECT or manifest['requested_display_name'] != 'GPIO_PL_Test_LED'
            or manifest['original_test_directory_name'] != 'GPIO_PL_Test'
            or manifest['validation_boundary']['old_final_run_is_evidence_for_this_variant'] is not False):
        raise ValueError('Incorrect LED variant identity or evidence scope')
    paths = []
    for entry in manifest['files']:
        name = entry['path']
        path = (root / name).resolve()
        if (not path.is_relative_to(project) or any(not re.fullmatch(r'[a-z0-9_.-]+', part)
                                                  for part in Path(name).parts)):
            raise ValueError('LED release path must be local and lowercase')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['public_sha256']:
            raise ValueError('LED file identity mismatch: ' + name)
        paths.append(name)
    if len(paths) != 92 or len(set(paths)) != len(paths):
        raise ValueError('Incomplete LED source input set')
    if hashlib.sha256((project / 'core/src/main.c').read_bytes()).hexdigest() != MAIN_SHA:
        raise ValueError('Supplied LED main.c changed')
    for name in ('drivers/cmsis/license.txt', 'drivers/cmsis/device/st/stm32g4xx/license.txt',
                 'drivers/stm32g4xx_hal_driver/license.txt'):
        if PROJECT + '/' + name not in paths:
            raise ValueError('LED variant missing third-party license')
    project_file = project / 'mdk-arm/gpio_pl_test.uvprojx'
    tree = ET.parse(project_file)
    if (tree.findtext('.//TargetName') != 'GPIO_PL_Test'
            or tree.findtext('.//Device') != 'STM32G431RBTx'
            or tree.findtext('.//PackID') != 'Keil.STM32G4xx_DFP.2.0.0'
            or tree.findtext('.//OutputDirectory') != 'gpio_pl_test\\'
            or tree.findtext('.//OutputName') != 'gpio_pl_test'):
        raise ValueError('LED Keil target or output changed')
    refs = [n.text for n in tree.findall('.//FilePath')]
    includes = [part for n in tree.findall('.//IncludePath') if n.text for part in n.text.split(';')]
    if len(refs) != 22 or len(includes) != 5:
        raise ValueError('Incomplete LED Keil inputs')
    for name in refs + includes:
        path = (project_file.parent / name.replace('\\', '/')).resolve()
        if not path.is_relative_to(project) or not path.exists():
            raise ValueError('LED Keil reference outside project or missing: ' + name)
    ioc = (project / 'gpio_pl_test.ioc').read_text(encoding='utf-8')
    if ('ProjectManager.ProjectFileName=gpio_pl_test.ioc' not in ioc
            or 'ProjectManager.ProjectName=gpio_pl_test' not in ioc or 'Mcu.CPN=STM32G431RBT6' not in ioc):
        raise ValueError('LED CubeMX name or device mismatch')
    main = (project / 'core/src/main.c').read_text(encoding='utf-8')
    if ('HAL_Delay(500);' not in main or 'HAL_Delay(300);' in main
            or 'DK117E_LED_VISIBLE_PINS DK117E_LED_ALL_PINS' not in main
            or not re.search(r'HAL_GPIO_TogglePin\([^;]+;\s*DK117E_LED_FollowPA1\(\);', main)):
        raise ValueError('LED behavior differs from the supplied 500 ms source')
    return len(paths)


if __name__ == '__main__':
    print(f'PASS: {check()} LED source inputs / lowercase paths / Keil references; hardware_result=NOT_TESTED')
