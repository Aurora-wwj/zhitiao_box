"""Verify the current HDF handoff and the documented prebuilt-Linux route."""

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    root = Path(root)
    platform = json.loads((root / 'data/linux_platform.json').read_text(encoding='utf-8'))
    if platform['source_level_petalinux_rebuild_claimed'] or platform['reproduction_recipe']['rebuild_boot_bin']:
        raise ValueError('Incorrect Linux implementation scope')
    info = platform['hardware_handoff']
    path = root / info['path']
    if len(path.read_bytes()) != info['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
        raise ValueError('HDF identity mismatch')
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != {m['name'] for m in info['members']} or archive.testzip():
            raise ValueError('HDF members or CRC mismatch')
        for member in info['members']:
            data = archive.read(member['name'])
            if len(data) != member['bytes'] or hashlib.sha256(data).hexdigest() != member['sha256']:
                raise ValueError('HDF member identity mismatch')
        definition = ET.fromstring(archive.read('sysdef.xml'))
        if (definition.find('TOOL_VERSION').get('Version') != '2017.4'
                or definition.find('SYSTEMINFO').get('PART') != 'xc7z020clg400-2'):
            raise ValueError('Wrong hardware handoff tool or part')
        if archive.read('system_wrapper.bit') != (root / info['embedded_bitstream_matches']).read_bytes():
            raise ValueError('HDF embedded bitstream differs from golden v5')
        if archive.read('system_bd.tcl') != (root / info['embedded_bd_tcl_matches']).read_bytes():
            raise ValueError('HDF embedded BD differs from delivered v5')
        hwh = ET.fromstring(archive.read('system.hwh'))
        for instance, address in [('zhidiao_measure_regs', 0x43C30000), ('zhidiao_measure_status', 0x43C40000),
                                  ('zhidiao_uart_log', 0x43C50000), ('zhidiao_status_gpio', 0x43C60000)]:
            module = hwh.find(".//MODULE[@INSTANCE='" + instance + "']")
            values = {n.get('NAME'): n.get('VALUE') for n in module.findall('./PARAMETERS/PARAMETER')}
            if int(values['C_BASEADDR'], 16) != address:
                raise ValueError('HDF register map mismatch')
            if instance == 'zhidiao_status_gpio' and (values['C_GPIO_WIDTH'] != '4'
                                                       or int(values['C_DOUT_DEFAULT'], 16) != 15):
                raise ValueError('HDF LED configuration mismatch')
            if instance == 'zhidiao_uart_log' and values['C_BAUDRATE'] != '115200':
                raise ValueError('HDF UART configuration mismatch')
    return len(info['members'])


if __name__ == '__main__':
    print(f'PASS: {check()} HDF members; v5 bitstream, BD, registers and Linux scope')
