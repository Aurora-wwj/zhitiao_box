import unittest
from pathlib import PurePosixPath

from zhidiao_agent.config import BoardPaths, NiceCodeConfig
from zhidiao_agent.errors import AgentError, ErrorCode


class ConfigTests(unittest.TestCase):
    def test_valid_api_config_hides_key_in_repr(self):
        config = NiceCodeConfig(
            base_url="https://api.example.com/v1",
            model="test-model",
            api_key="test-secret",
        )
        self.assertEqual(config.timeout_s, 30.0)
        self.assertNotIn("test-secret", repr(config))

    def test_invalid_api_config(self):
        valid = {
            "base_url": "https://api.example.com/v1",
            "model": "test-model",
            "api_key": "test-secret",
        }
        cases = [
            {"base_url": "http://api.example.com"},
            {"base_url": "https://user:password@api.example.com"},
            {"base_url": "https://api.example.com?key=secret"},
            {"base_url": "https://api.example.com#fragment"},
            {"base_url": "https://api.example.com:invalid"},
            {"base_url": "https://api.example.com:65536"},
            {"base_url": "https://api.example.com:0"},
            {"base_url": "https://api.example.com/\npath"},
            {"model": " "},
            {"api_key": ""},
            {"api_key": "key\r\nInjected: value"},
            {"timeout_s": 0},
            {"timeout_s": -1},
            {"timeout_s": float("inf")},
            {"timeout_s": float("nan")},
            {"timeout_s": True},
            {"timeout_s": "30"},
            {"timeout_s": 10 ** 1000},
        ]
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(AgentError) as caught:
                    NiceCodeConfig(**(valid | override))
                self.assertEqual(
                    caught.exception.code,
                    ErrorCode.CONFIGURATION_ERROR,
                )

    def test_default_board_paths_match_contract(self):
        paths = BoardPaths()
        self.assertEqual(
            str(paths.openocd_bin),
            "/sd/tools/openocd/bin/openocd",
        )
        self.assertEqual(
            str(paths.openocd_scripts),
            "/sd/tools/openocd/share/openocd/scripts",
        )
        self.assertEqual(str(paths.log_root), "/sd/logs")
        self.assertEqual(
            str(paths.firmware_path("run_0001")),
            "/sd/firmware/run_0001/firmware.hex",
        )

    def test_reject_invalid_remote_root(self):
        for root in ("relative", "/sd", PurePosixPath("/sd/../etc")):
            with self.subTest(root=root):
                with self.assertRaises(AgentError):
                    BoardPaths(mount_root=root)

    def test_reject_run_id_path_traversal(self):
        for run_id in ("", ".", "..", "../BOOT.BIN", "/etc", "a/b", "a" * 65):
            with self.subTest(run_id=run_id):
                with self.assertRaises(AgentError) as caught:
                    BoardPaths().firmware_path(run_id)
                self.assertEqual(
                    caught.exception.code,
                    ErrorCode.INVALID_ARGUMENT,
                )
