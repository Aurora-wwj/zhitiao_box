"""Source suggestions for the published and existing local project layouts."""

from pathlib import Path
import tempfile
import unittest

from zhidiao_agent.desktop import suggested_source


class DesktopSourceTests(unittest.TestCase):
    def test_published_lowercase_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'core/src/main.c'
            source.parent.mkdir(parents=True)
            source.write_text('int main(void) {}')
            (root / 'main.c').write_text('other project entry')
            self.assertEqual(suggested_source(root), 'core/src/main.c')

    def test_existing_legacy_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'Core/Src/main.c'
            source.parent.mkdir(parents=True)
            source.write_text('int main(void) {}')
            # On Windows the first, lowercase candidate names the same file.
            chosen = suggested_source(root)
            self.assertIsNotNone(chosen)
            self.assertTrue((root / chosen).samefile(source))

    def test_flat_project_and_no_existing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(suggested_source(root))
            (root / 'main.c').write_text('int main(void) {}')
            self.assertEqual(suggested_source(root), 'main.c')
