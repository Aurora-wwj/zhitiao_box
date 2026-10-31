"""Read-only checks of the FPGA release and derivation of report metrics."""
import hashlib
import csv
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BIT_SHA = 'fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6'


def report_metrics(label):
    folder = ROOT / 'build/fpga/reports' / label
    utilization = (folder / 'system_wrapper_utilization_placed.rpt').read_text()
    timing = (folder / 'system_wrapper_timing_summary_routed.rpt').read_text()
    result = {}
    for key, name in [('lut', 'Slice LUTs'), ('ff', 'Slice Registers'),
                      ('bram', 'Block RAM Tile'), ('dsp', 'DSPs'), ('iob', 'Bonded IOB')]:
        match = re.search(r'^\|\s*' + re.escape(name) + r'\s*\|\s*([\d.]+)\s*\|', utilization, re.M)
        if not match:
            raise ValueError(f'Missing {name}: {label}')
        result[key] = float(match[1])
    summary = timing[timing.index('WNS(ns)'):].splitlines()[2].split()
    for key, index in [('wns_ns', 0), ('tns_ns', 1), ('setup_failing_endpoints', 2),
                       ('whs_ns', 4), ('ths_ns', 5), ('hold_failing_endpoints', 6),
                       ('wpws_ns', 8), ('tpws_ns', 9), ('pulse_failing_endpoints', 10)]:
        result[key] = float(summary[index])
    for key, pattern in [
        ('unconstrained_pins', r'There are (\d+) pins that are not constrained for maximum delay\.'),
        ('inputs_without_delay', r'There are (\d+) input ports with no input delay specified\.'),
        ('outputs_without_delay', r'There are (\d+) ports with no output delay specified\.'),
    ]:
        match = re.search(pattern, timing)
        if not match:
            raise ValueError(f'Missing timing coverage check {key}: {label}')
        result[key] = int(match[1])
    if 'All user specified timing constraints are met.' not in timing:
        raise ValueError(f'Timing did not meet all specified constraints: {label}')
    return result


def check():
    manifest = json.loads((ROOT / 'data/fpga_manifest.json').read_text())
    for entry in manifest['files']:
        path = (ROOT / entry['path']).resolve(strict=True)
        if not path.is_relative_to(ROOT):
            raise ValueError('FPGA path outside release')
        data = path.read_bytes()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['public_sha256']:
            raise ValueError(f"FPGA identity mismatch: {entry['path']}")
    bit = ROOT / 'build/fpga/zhidiao_observe_v5_led.bit'
    if hashlib.sha256(bit.read_bytes()).hexdigest() != BIT_SHA:
        raise ValueError('Golden v5 bitstream mismatch')
    project = ROOT / 'src/fpga/zhidiao_measure'
    tree = ET.parse(project / 'linux_ov5640.xpr')
    if tree.find(".//Option[@Name='Part']").get('Val') != 'xc7z020clg400-2':
        raise ValueError('Unexpected FPGA part')
    for node in tree.findall('.//File'):
        relative = node.get('Path', '').replace('$PSRCDIR/', 'linux_ov5640.srcs/')
        path = (project / relative).resolve(strict=True)
        if not path.is_relative_to(project) or not path.is_file():
            raise ValueError(f'Unresolved FPGA source: {relative}')
    expected = json.loads((ROOT / 'data/fpga_metrics.json').read_text())
    for label in ('baseline', 'final'):
        if report_metrics(label) != expected[label]:
            raise ValueError(f'Published metrics differ from original reports: {label}')
    with (ROOT / 'data/fpga_metrics.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != len(expected['final']) or {row['metric'] for row in rows} != set(expected['final']):
        raise ValueError('Metrics CSV has missing or duplicate metrics')
    for row in rows:
        key = row['metric']
        before, after = expected['baseline'][key], expected['final'][key]
        if [float(row[k]) for k in ('baseline', 'final', 'delta')] != [before, after, round(after - before, 6)]:
            raise ValueError(f'Incorrect CSV metrics: {key}')
    final = expected['final']
    if [final[k] for k in ('lut', 'ff', 'bram', 'dsp', 'iob', 'wns_ns', 'tns_ns')] != [7274, 12083, 20.5, 0, 44, .709, 0]:
        raise ValueError('Unexpected final implementation results')
    return len(manifest['files'])


if __name__ == '__main__':
    print(f'PASS: {check()} FPGA identities, XPR inputs and baseline/final resource/timing reports')
