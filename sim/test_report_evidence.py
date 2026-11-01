"""Regression for evidence identity, scene separation and full source diff."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import report_check

ROOT = report_check.ROOT


class ReportEvidenceTests(unittest.TestCase):
    def copy_evidence(self, target):
        paths = ['README.md', 'data/report_sources.json', 'data/final_run_sanitized.json',
                 'data/measurements.csv', 'data/final_source_change.diff', 'data/screenshots/readme.md']
        sources = json.loads((ROOT / 'data/report_sources.json').read_text())
        paths += [item['path'] for item in sources['screenshots']['files']]
        for name in paths:
            output = target / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, output)

    def test_evidence_and_ui_precision_match_one_complete_run(self):
        self.assertEqual(report_check.check(), 4)

    def test_changed_pixels_or_csv_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.copy_evidence(root)
            self.assertEqual(report_check.check(root), 4)
            image = root / 'data/screenshots/ui_four_tool_pass.png'
            data = image.read_bytes()
            image.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
            with self.assertRaisesRegex(ValueError, 'Evidence SHA mismatch'):
                report_check.check(root)
            image.write_bytes(data)
            csv = root / 'data/measurements.csv'
            csv.write_text(csv.read_text().replace('1001.08682', '1000.0'))
            with self.assertRaisesRegex(ValueError, 'measurements differ'):
                report_check.check(root)

    def test_pl_only_cannot_count_as_full_loop_and_diff_cannot_be_shortened(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.copy_evidence(root)
            manifest = root / 'data/report_sources.json'
            data = json.loads(manifest.read_text())
            pl = next(item for item in data['screenshots']['files'] if item['scenario'] == 'pl_only_baseline_already_passed')
            pl['evidence_scope'] = 'full_loop'
            manifest.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'PL-only screenshot misclassified'):
                report_check.check(root)
            pl['evidence_scope'] = 'screenshot_only'
            manifest.write_text(json.dumps(data))
            patch = root / 'data/final_source_change.diff'
            patch.write_text('-HAL_Delay(300);\n+HAL_Delay(500);\n')
            with self.assertRaisesRegex(ValueError, 'Evidence SHA mismatch'):
                report_check.check(root)


if __name__ == '__main__':
    unittest.main()
