from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from zhidiao_agent.editing import MAX_SOURCE_BYTES, SourceEditor, digest


class EditingTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="zhidiao-editor-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.file = self.root / "main.c"
        self.before = b"const int gpio_period_ms = 800;\r\n"
        self.after = "const int gpio_period_ms = 1001;\r\n"
        self.file.write_bytes(self.before)
        self.editor = SourceEditor(str(self.root), ("main.c",))

    def preview(self):
        return self.editor.preview({"path": "main.c", "before_sha256": digest(self.before), "content": self.after})

    def approve(self, preview):
        self.assertTrue(preview.success, preview.to_dict())
        self.assertTrue(self.editor.approvals.decide(preview.data["proposal_id"], preview.data["fingerprint"], approved=True).success)

    def test_snapshot_preserves_hash_and_crlf_without_writing(self):
        result = self.editor.snapshot()
        self.assertTrue(result.success)
        self.assertEqual(result.data["sources"]["main.c"], {"sha256": digest(self.before), "content": self.before.decode()})
        self.assertEqual(self.file.read_bytes(), self.before)

    def test_preview_diff_and_unapproved_apply_do_not_write(self):
        preview = self.preview()
        self.assertTrue(preview.success)
        self.assertIn("-const int gpio_period_ms = 800;", preview.data["params"]["diff"])
        self.assertIn("+const int gpio_period_ms = 1001;", preview.data["params"]["diff"])
        self.assertEqual(self.file.read_bytes(), self.before)
        result = self.editor.apply(preview.data["proposal_id"])
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.assertEqual(self.file.read_bytes(), self.before)

    def test_approved_edit_writes_exact_bytes_and_is_single_use(self):
        preview = self.preview()
        self.approve(preview)
        identity = preview.data["proposal_id"]
        self.assertTrue(self.editor.apply(identity).success)
        self.assertEqual(self.file.read_bytes(), self.after.encode())
        self.assertEqual(self.editor.apply(identity).error_code, "APPROVAL_REQUIRED")
        self.assertEqual(list(self.root.glob(".zhidiao-edit-*")), [])

    def test_rejected_edit_and_changed_source_cannot_apply(self):
        preview = self.preview()
        self.editor.approvals.decide(preview.data["proposal_id"], preview.data["fingerprint"], approved=False)
        self.assertFalse(self.editor.apply(preview.data["proposal_id"]).success)
        self.assertEqual(self.file.read_bytes(), self.before)
        preview = self.preview()
        self.approve(preview)
        self.file.write_text("changed by user", encoding="utf-8")
        self.assertEqual(self.editor.apply(preview.data["proposal_id"]).error_code, "APPROVAL_REQUIRED")
        self.assertEqual(self.file.read_text(), "changed by user")

    def test_preview_mutation_does_not_change_approved_content(self):
        preview = self.preview()
        preview.data["params"]["path"] = "other.c"
        preview.data["params"]["diff"] = "+untrusted replacement"
        self.approve(preview)
        self.assertTrue(self.editor.apply(preview.data["proposal_id"]).success)
        self.assertEqual(self.file.read_bytes(), self.after.encode())

    def test_traversal_absolute_paths_metadata_and_unknown_files_are_rejected(self):
        paths = ("../main.c", "nested/../../main.c", "/main.c", "C:/main.c", "C:\\main.c", "other.c", ".git/config.c")
        for path in paths:
            with self.subTest(path=path):
                result = self.editor.preview({"path": path, "before_sha256": digest(self.before), "content": self.after})
                self.assertFalse(result.success)
        self.assertEqual(self.file.read_bytes(), self.before)

    def test_noop_oversize_stale_hash_and_non_utf8_are_rejected(self):
        for content, before_hash in ((self.before.decode(), digest(self.before)),
                                     ("x" * (MAX_SOURCE_BYTES + 1), digest(self.before)),
                                     (self.after, "0" * 64)):
            result = self.editor.preview({"path": "main.c", "before_sha256": before_hash, "content": content})
            self.assertFalse(result.success)
        self.file.write_bytes(b"\xff")
        self.assertEqual(self.editor.snapshot().error_code, "INVALID_ARGUMENT")

    def test_failed_atomic_replace_preserves_source_and_cleans_temporary_file(self):
        preview = self.preview()
        self.approve(preview)
        with patch("zhidiao_agent.editing.os.replace", side_effect=OSError("private details")):
            result = self.editor.apply(preview.data["proposal_id"])
        self.assertFalse(result.success)
        self.assertNotIn("private details", result.message)
        self.assertEqual(self.file.read_bytes(), self.before)
        self.assertEqual(list(self.root.glob(".zhidiao-edit-*")), [])

    def test_diff_handles_source_without_trailing_newline(self):
        self.file.write_bytes(b"old")
        result = self.editor.preview({"path": "main.c", "before_sha256": digest(b"old"), "content": "new"})
        self.assertIn("-old\n\\ No newline at end of file\n", result.data["params"]["diff"])
        self.assertIn("+new\n\\ No newline at end of file\n", result.data["params"]["diff"])

    def test_metadata_is_blocked_even_if_accidentally_allowlisted(self):
        metadata = self.root / ".GIT"
        metadata.mkdir()
        (metadata / "config.c").write_text("metadata", encoding="utf-8")
        editor = SourceEditor(str(self.root), (".GIT/config.c",))
        self.assertEqual(editor.snapshot().error_code, "INVALID_ARGUMENT")

    def test_symlink_detection_blocks_source_reading(self):
        with patch("zhidiao_agent.editing.Path.is_symlink", return_value=True):
            self.assertEqual(self.editor.snapshot().error_code, "INVALID_ARGUMENT")
