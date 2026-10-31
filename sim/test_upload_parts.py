"""Offline integrity tests; no user archive or hardware is touched."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from prepare_upload_parts import MIB, digest, join_files, split_file


class UploadPartsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'original.zip'
        self.source.write_bytes(bytes(range(256)) * 9000)
        self.parts = split_file(self.source, self.root / 'parts', part_mib=1)

    def test_out_of_order_parts_restore_identical_bytes_in_small_ordinary_zips(self):
        self.assertEqual(len(self.parts), 3)
        for path in self.parts:
            self.assertTrue(zipfile.is_zipfile(path))
            self.assertLess(path.stat().st_size, 30 * MIB)
        output = join_files(list(reversed(self.parts)), self.root / 'restored.zip')
        self.assertEqual(output.read_bytes(), self.source.read_bytes())
        self.assertEqual(digest(output), digest(self.source))

    def test_missing_or_duplicated_parts_are_rejected(self):
        for parts in (self.parts[:-1], self.parts + self.parts[:1]):
            with self.assertRaises(ValueError):
                join_files(parts, self.root / 'bad.zip')
            self.assertFalse((self.root / 'bad.zip').exists())

    def test_mixed_archives_are_rejected(self):
        other = self.root / 'other.zip'
        other.write_bytes(b'z' * self.source.stat().st_size)
        parts = split_file(other, self.root / 'other-parts', part_mib=1)
        with self.assertRaises(ValueError):
            join_files([parts[0], *self.parts[1:]], self.root / 'bad.zip')

    def test_corrupted_payload_is_rejected_and_partial_output_removed(self):
        path = self.parts[-1]
        with zipfile.ZipFile(path) as z:
            meta, chunk = z.read('manifest.json'), z.read('chunk.bin')
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('manifest.json', meta)
            z.writestr('chunk.bin', b'X' + chunk[1:])
        with self.assertRaises(ValueError):
            join_files(self.parts, self.root / 'bad.zip')
        self.assertFalse((self.root / 'bad.zip').exists())

    def test_existing_input_output_and_parts_are_preserved(self):
        original = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            join_files(self.parts, self.source)
        self.assertEqual(self.source.read_bytes(), original)
        with self.assertRaises(ValueError):
            split_file(self.source, self.root / 'parts')
        with self.assertRaises(ValueError):
            split_file(self.source, self.root / 'new-parts', part_mib=30)


if __name__ == '__main__':
    unittest.main()
