"""Temporary-source UI modes with exclusively simulated hardware."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .agent import Agent
from .controller import Controller
from .demo import ScriptedDemoClient
from .editing import SourceEditor
from .errors import AgentError, ErrorCode
from .models import OperationResult
from .observations import gpio_result, number
from .orchestrator import Orchestrator
from .reports import RunStore
from .tools.feedback_mock import FeedbackMockBackend
from .web_ui import WebUIService, _require


class DemoUIClient(ScriptedDemoClient):
    def generate(self, messages):
        request = json.loads(messages[-1]["content"])
        if "sources" in request:
            result = super().generate(messages)
            decision = json.loads(result.data["content"])
            decision["reason"] = "离线演示：模拟完整周期 800 ms 未达到 1000 ±50 ms。建议将临时源码中的周期常量改为 1001 ms，再通过模拟构建、烧录和测量验证；当前没有连接真实硬件或 NiceCode。"
            return OperationResult(True, None, result.message, result.backend,
                                   data={"content": json.dumps(decision, ensure_ascii=False)})
        # This mode demonstrates exactly one fixed, clearly labelled mock task.
        data = {"status": "ready", "test_id": "gpio_period", "observed_gpio": "PA1",
                "params": {"expected_period_ms": 1000, "tolerance_ms": 50},
                "summary": "离线演示固定目标：模拟 PA1 完整周期 1000 ±50 ms。"}
        return OperationResult(True, None, "Offline demo goal", "scripted_mock",
                               data={"content": json.dumps(data, ensure_ascii=False)})


class MockHardwareWebUIService(WebUIService):
    """Real or scripted model, fixed temporary project, four simulated tools.

    The backend is selected here, never from browser input or model output.
    A model request is deferred until start() receives context-sharing consent.
    """

    def __init__(self, client_factory, *, model_source="nicecode_api", model_name="",
                 timeout_s=600, report_dir=None):
        if model_source not in {"nicecode_api", "scripted"} or not isinstance(model_name, str) or not model_name.strip():
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Select a supported simulation model source and name.")
        if number(timeout_s) > 1800:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Workflow timeout must not exceed 1800 seconds.")
        self._model_source, self._model_name = model_source, model_name
        self._temporary = TemporaryDirectory(prefix="zhidiao-ui-demo-")
        root = Path(self._temporary.name).resolve()
        try:
            (root / "main.c").write_text(
                "// SIMULATION ONLY: PA1 is a virtual observation channel.\n"
                "// No C compiler, SSH, MCU or physical measurements are used.\n"
                "// The mock backend reads gpio_period_ms as the COMPLETE cycle\n"
                "// period in milliseconds, not a half-cycle or toggle delay.\n"
                "// Keep one positive decimal integer literal assignment below.\n"
                "const unsigned int gpio_period_ms = 800;\n", encoding="utf-8")
            super().__init__("", str(root), ("main.c",), client_factory, include_uart=True,
                             strict_approval=True, report_dir=report_dir, timeout_s=timeout_s,
                             model_info={"source": model_source, "requested_model": model_name,
                                         "protocol": "openai-responses" if model_source == "nicecode_api" else "scripted"})
        except BaseException:
            self._temporary.cleanup()
            raise

    def _prepare(self):
        self._editor = SourceEditor(self.project_path, self.source_files)
        self._sources = _require(self._editor.snapshot())["sources"]
        self._report_store = RunStore(self.report_dir)
        _require(self._report_store.list_runs())
        self._backend = FeedbackMockBackend(self.project_path)
        self._scope.update({"project_path": self.project_path, "observed_gpio": "PA1",
                            "target": "模拟硬件 · 无 Keil / SSH", "evidence_source": "mock",
                            "approval_mode": "semantic", "model": self._model_name,
                            "model_source": self._model_source,
                            "temporary_project": True,
                            "source_files": {name: {"sha256": row["sha256"]} for name, row in self._sources.items()}})
        return {"ready": True, "hardware_source": "mock", "model_source": self._model_source}

    def _new_loop(self):
        controller = Controller(self._backend, allowed_roots=(self.project_path,), max_attempts=3)
        controller.events = self._events
        return Orchestrator(controller, Agent(self._client), self._editor,
            task=self._task, project_path=self.project_path, params=self._goal["params"],
            report_store=self._report_store, include_uart=True, timeout_s=self._check(),
            recovery_report=self._recovery_report,
            model_info=self._model_info,
            run_id=self._entry.run_id if self._entry is not None else None,
            task_entry=self._entry.context() if self._entry is not None else None)

    def _validate_goal(self):
        gpio_result(self._goal["params"], {"period_ms": 1})

    def close(self):
        result = super().close()
        if self._worker is None or not self._worker.is_alive():
            self._temporary.cleanup()
        return result


class DemoWebUIService(MockHardwareWebUIService):
    """Completely offline, fixed-goal scripted demonstration."""

    def __init__(self, *, report_dir=None):
        super().__init__(DemoUIClient, model_source="scripted", model_name="脚本模拟（不调用 NiceCode）",
                         timeout_s=1800, report_dir=report_dir)
