"""Causal mock: build snapshots a fixture constant; flash deploys that snapshot.

No compiler, SSH, FPGA or physical measurement is used. For software demos only.
"""

import re
from pathlib import Path

from ..errors import AgentError, ErrorCode
from ..models import invoke
from ..observations import gpio_result
from .artifacts import file_digest
from .mock_backend import MockBackend


class FeedbackMockBackend(MockBackend):
    name = "mock_feedback"

    def __init__(self, project: str):
        self.project = Path(project).resolve()
        self.built_period = None
        self.deployed_period = None
        self.built_sha256 = None
        self.artifact = str(self.project / "Objects" / "firmware.hex")

    def build_firmware(self, project_path: str):
        def operation():
            self.built_period = None
            self.deployed_period = None
            if Path(project_path).resolve() != self.project:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Unexpected mock project.")
            source = self.project / "main.c"
            text = source.read_text(encoding="utf-8")
            match = re.search(r"\bgpio_period_ms\s*=\s*([1-9][0-9]*)\s*;", text)
            if not match:
                raise AgentError(ErrorCode.BUILD_FAILED, "Mock fixture must define gpio_period_ms.")
            self.built_period = int(match.group(1))
            self.built_sha256 = file_digest(source)
            return {"artifact_path": self.artifact, "compiler_log": "MOCK: fixture captured; no compiler executed."}
        return invoke(operation, backend=self.name)

    def flash_firmware(self, firmware_path: str):
        def operation():
            if (firmware_path != self.artifact or self.built_period is None
                    or file_digest(self.project / "main.c") != self.built_sha256):
                raise AgentError(ErrorCode.FLASH_PROGRAM_FAILED, "Mock build artifact is missing or stale.")
            self.deployed_period = self.built_period
            return {"verified": True, "artifact_path": self.artifact,
                    "tool_log": "MOCK: build snapshot deployed; no hardware contacted."}
        return invoke(operation, backend=self.name)

    def run_hardware_test(self, test_id: str, params: dict):
        def operation():
            if test_id != "gpio_period":
                raise AgentError(ErrorCode.PL_TEST_UNAVAILABLE, "Unsupported mock test.")
            if self.deployed_period is None:
                raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "Mock firmware has not been flashed.")
            return {**gpio_result(params, {"period_ms": self.deployed_period}), "evidence_source": "mock"}
        return invoke(operation, backend=self.name)
