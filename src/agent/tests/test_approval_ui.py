import contextlib
import io
import unittest
from unittest.mock import patch

from zhidiao_agent.approval_ui import human_review


class ApprovalUiTests(unittest.TestCase):
    def setUp(self):
        self.output, self.diff_output = io.StringIO(), io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))
        self.enterContext(contextlib.redirect_stderr(self.diff_output))
        self.preview = {"proposal_id": "bound-proposal", "fingerprint": "a" * 64,
                        "action": "edit_source", "params": {"diff": "-HAL_Delay(300);\n+HAL_Delay(500);\n"}}

    def test_short_human_confirmation_never_requires_hash_copying(self):
        for answer in ("批准", "  approve  ", "Y", "Yes"):
            with self.subTest(answer=answer), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=answer):
                result = human_review(self.preview, title="查看本次修改")
            self.assertTrue(result.success)
            self.assertTrue(result.data["approved"])
        self.assertIn("+HAL_Delay(500);", self.diff_output.getvalue())

    def test_noninteractive_does_not_read_even_piped_yes(self):
        with patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as prompt:
            result = human_review(self.preview, title="review")
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        prompt.assert_not_called()

    def test_diff_is_display_only_and_next_answer_controls_decision(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["diff", "取消"]) as prompt:
            result = human_review(self.preview, title="review")
        self.assertEqual(prompt.call_count, 2)
        self.assertFalse(result.data["approved"])
        self.assertEqual(self.diff_output.getvalue().count("+HAL_Delay(500);"), 2)

    def test_unknown_input_eof_and_interrupt_reject(self):
        for answer in ("", "maybe", "APPROVE wrong"):
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=answer):
                self.assertFalse(human_review(self.preview, title="review").data["approved"])
        for error in (EOFError, KeyboardInterrupt):
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=error):
                self.assertFalse(human_review(self.preview, title="review").data["approved"])

    def test_preview_explains_numeric_goal_and_escapes_terminal_controls(self):
        preview = {**self.preview, "reason": "根据实测更新", "params": {
            "params": {"expected_period_ms": 1000, "tolerance_ms": 50},
            "diff": "-old\n+new\x1b[2J\n", "observation_mode": "gpio_period_only",
            "observed_gpio": "PA1",
        }}
        with patch("sys.stdin.isatty", return_value=False):
            human_review(preview, title="审查")
        shown = self.diff_output.getvalue()
        self.assertIn("1000 ± 50 ms", shown)
        self.assertIn("根据实测更新", shown)
        self.assertIn("物理观测引脚：STM32 PA1", shown)
        self.assertIn("\\u001b[2J", shown)
        self.assertNotIn("\x1b", shown)
