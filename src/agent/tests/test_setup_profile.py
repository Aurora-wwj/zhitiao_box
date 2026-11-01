"""Exercise actual setup CLI approval and persisted v5 hardware profiles."""

import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from zhidiao_agent.cli import main
from zhidiao_agent.deployment import DeploymentConfig


class SetupProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="zhidiao-setup-profile-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "test.uvprojx").write_text(
            "<Project><Targets><Target><TargetName>GPIO</TargetName>"
            "<TargetOption><TargetCommonOption><OutputDirectory>.\\Objects\\</OutputDirectory>"
            "<OutputName>GPIO</OutputName><CreateHexFile>1</CreateHexFile>"
            "</TargetCommonOption></TargetOption></Target></Targets></Project>",
            encoding="utf-8",
        )
        for name in ("UV4.exe", "known_hosts"):
            (self.root / name).write_text("test fixture, never executed", encoding="utf-8")
        self.output = self.root / "deployment.local.json"
        self.args = [
            "deployment-setup", "--project", str(self.project),
            "--keil", str(self.root / "UV4.exe"),
            "--known-hosts", str(self.root / "known_hosts"),
            "--output", str(self.output),
        ]
        self.enterContext(patch("zhidiao_agent.pairing.shutil.which", side_effect=lambda name: "/mock/" + name))
        self.command = self.enterContext(patch("zhidiao_agent.pairing.ProcessRunner.run"))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def create_and_compare(self, extra, example):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="批准"):
            self.assertEqual(main(self.args + extra), 0)
        actual = json.loads(self.output.read_text(encoding="utf-8"))
        expected = json.loads((Path(__file__).resolve().parents[1] / example).read_text(encoding="utf-8"))
        for section in ("observer", "uart_observer", "status_indicator"):
            self.assertEqual(actual[section], expected[section], section)
        self.assertEqual(Path(actual["observer"]["bitstream"]).name, "zhidiao_observe_v5_led.bit")
        self.assertEqual(actual["observer"]["prepare_policy"], "check_only")
        DeploymentConfig.load(str(self.output))
        self.command.assert_not_called()

    def test_approved_setup_writes_current_v5_led_and_uart_profile(self):
        self.create_and_compare([], "deployment.example.json")

    def test_no_led_keeps_v5_and_uart_without_status_writes(self):
        self.create_and_compare(["--no-led"], "deployment.no-led.example.json")

    def test_preview_and_rejection_never_write_or_connect(self):
        with patch("builtins.input") as prompt:
            self.assertEqual(main(self.args + ["--preview-only"]), 0)
            prompt.assert_not_called()
        self.assertFalse(self.output.exists())
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="取消"):
            self.assertEqual(main(self.args), 1)
        self.assertFalse(self.output.exists())
        self.command.assert_not_called()
