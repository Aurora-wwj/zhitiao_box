"""Check published report/screenshot identity and their documented associations.

Image pixels were reviewed manually. Hashes preserve that review; this is not OCR
or an independent attestation of hardware behavior.
"""
import csv
import hashlib
import json
import math
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    root = Path(root).resolve()

    def local(name):
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Evidence path outside release')
        return path

    def verified(name, expected):
        path = local(name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Evidence SHA mismatch: {name}')
        return path

    sources = json.loads(local('data/report_sources.json').read_text(encoding='utf-8'))
    primary, prior = sources['primary_source'], sources['previous_source']
    report_path = verified(primary['public_path'], primary['public_sha256'])
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if (report['run_id'] != sources['run_id'] or sources['unique_full_loop_runs'] != 1
            or not sources['comparison']['same_run'] or primary['raw_published']
            or report['elapsed_s'] != primary['elapsed_s']):
        raise ValueError('Incorrect report identity or duplicate-run accounting')
    if (sources['comparison']['changed_raw_json_pointers'] != ['/elapsed_s']
            or not math.isclose(primary['elapsed_s'] - prior['elapsed_s'],
                                sources['comparison']['elapsed_delta_s'], abs_tol=1e-12)):
        raise ValueError('Incorrect export-snapshot comparison')
    with local('data/measurements.csv').open(newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    if len(csv_rows) != len(report['cycles']) or len(sources['cycles']) != len(csv_rows):
        raise ValueError('Evidence cycle counts differ')
    expected_tools = ['build_firmware', 'flash_firmware', 'read_target_log', 'run_hardware_test']
    displayed_periods = []
    for cycle, summary, row in zip(report['cycles'], sources['cycles'], csv_rows):
        audit = cycle['execution']['audit']
        hw, uart = audit[3]['result'], audit[2]['result']
        if ([r['tool_name'] for r in audit] != expected_tools or summary['tool_names'] != expected_tools
                or not all(r['result']['success'] for r in audit) or not summary['all_tools_success']):
            raise ValueError('Main evidence is not a complete four-tool cycle')
        period, high = hw['measurements']['period_ms'], hw['measurements']['high_ms']
        error = abs(period - sources['goal']['expected_period_ms'])
        if (summary['attempt'] != cycle['attempt'] or int(row['attempt']) != cycle['attempt']
                or summary['period_ms'] != period or summary['high_ms'] != high
                or summary['passed'] != hw['passed'] or row['passed'] != str(hw['passed']).lower()
                or not math.isclose(summary['error_ms'], error, abs_tol=1e-9)
                or not math.isclose(float(row['error_ms']), error, abs_tol=1e-9)
                or float(row['period_ms']) != period or float(row['high_ms']) != high):
            raise ValueError('JSON, summary and CSV measurements differ')
        if (summary['displayed_period_ms'] != format(period, '.3f')
                or summary['displayed_error_ms'] != format(error, '.3f')):
            raise ValueError('Incorrect UI display rounding')
        if (summary['uart_partial_tail'] != uart['partial_tail'] or summary['uart_truncated'] != uart['truncated']
                or summary['fresh_edges'] != hw['observation']['fresh_edges']
                or int(row['fresh_edges']) != hw['observation']['fresh_edges']):
            raise ValueError('UART/freshness evidence differs')
        displayed_periods.append(format(period, '.3f'))
    edit = sources['source_edit']
    diff = verified(edit['path'], edit['sha256']).read_text(encoding='utf-8')
    approved = next(r for r in report['reviews'] if r.get('kind') == 'source_diff' and r.get('approved'))
    if diff != approved['params']['diff'].replace('\r\n', '\n'):
        raise ValueError('Published diff omitted or changed part of the approved edit')
    if hashlib.sha256(approved['params']['diff'].encode()).hexdigest() != edit['original_diff_utf8_sha256']:
        raise ValueError('Original diff identity mismatch')
    if edit['after_source_sha256'] != report['checkpoint']['source_hashes']['Core/Src/main.c']:
        raise ValueError('Edited source identity mismatch')
    files = sources['screenshots']['files']
    if len(files) != 4 or len({item['path'] for item in files}) != 4:
        raise ValueError('Expected four distinct supplied screenshots')
    captions = local('data/screenshots/README.md').read_text(encoding='utf-8')
    for item in files:
        path = verified(item['path'], item['sha256'])
        data = path.read_bytes()
        if (item['altered'] or len(data) != item['bytes'] or data[:8] != b'\x89PNG\r\n\x1a\n'
                or data[12:16] != b'IHDR' or struct.unpack('>II', data[16:24]) != (item['width'], item['height'])):
            raise ValueError('Screenshot bytes or dimensions changed')
        if path.name not in captions:
            raise ValueError('Screenshot missing from caption index')
        if item['scenario'] == 'pl_only_baseline_already_passed':
            if (item['evidence_scope'] != 'screenshot_only' or item['associated_run_id'] is not None
                    or item['displayed_period_ms'] != ['1000.192']):
                raise ValueError('PL-only screenshot misclassified as main four-tool evidence')
        elif (item['evidence_scope'] != 'full_loop' or item['associated_run_id'] != report['run_id']
                or item['displayed_period_ms'] != displayed_periods):
            raise ValueError('Main screenshot association or displayed values differ')
        if item['scenario'] == 'current_report_with_separate_history_selection':
            if item['displayed_current_report_id'] != report['run_id']:
                raise ValueError('Audit screenshot current report ID differs')
    title = '# ' + sources['registration']['project_name']
    if local('README.md').read_text(encoding='utf-8').splitlines()[0] != title:
        raise ValueError('Project title differs from supplied registration')
    return len(files)


if __name__ == '__main__':
    print(f'PASS: canonical export, CSV, full diff and {check()} original screenshot associations')
