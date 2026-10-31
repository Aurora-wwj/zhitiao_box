"""Offline feedback/edit demo, optionally using an explicitly enabled model API."""

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from .agent import Agent
from .approval_ui import human_review
from .controller import Controller
from .editing import SourceEditor
from .models import OperationResult
from .orchestrator import Orchestrator
from .tools.feedback_mock import FeedbackMockBackend


class ScriptedDemoClient:
    """A deterministic model stand-in; not a real AI model or physical evidence."""

    def generate(self, messages):
        data = json.loads(messages[-1]["content"])
        source = data["sources"]["main.c"]
        content = re.sub(r"gpio_period_ms\s*=\s*[0-9]+\s*;", "gpio_period_ms = 1001;", source["content"])
        decision = {"action": "edit", "reason": "MOCK: period 800 ms misses 1000 ±50 ms; propose 1001 ms for the next simulated build.",
                    "edit": {"path": "main.c", "before_sha256": source["sha256"], "content": content}}
        return OperationResult(True, None, "Scripted demo decision", "scripted_mock", data={"content": json.dumps(decision)})


def run_agent_demo(client=None) -> OperationResult:
    with TemporaryDirectory(prefix="zhidiao-agent-demo-") as directory:
        project = Path(directory).resolve()
        # Only initialize our newly-created temporary fixture, never user source.
        (project / "main.c").write_text("// MOCK ONLY: no compiler or hardware used.\nconst unsigned int gpio_period_ms = 800;\n", encoding="utf-8")
        editor = SourceEditor(str(project), ("main.c",))
        loop = Orchestrator(
            Controller(FeedbackMockBackend(str(project)), allowed_roots=(str(project),), max_attempts=3),
            Agent(client if client is not None else ScriptedDemoClient()), editor,
            task="把 GPIO 的完整周期调到 1000 ms，允许误差 50 ms。只依据模拟证据提出修改。",
            project_path=str(project), params={"expected_period_ms": 1000, "tolerance_ms": 50},
        )
        while True:
            result = loop.advance()
            if not result.success or result.data["decision"] != "AWAITING_APPROVAL":
                break
            preview = result.data["pending_edit"]
            review = human_review(preview, title="模拟闭环：批准此临时源码差异后，重新模拟构建、烧录和测量。")
            if not review.success:
                break
            fingerprint = preview["fingerprint"]
            result = loop.review_edit(preview["proposal_id"], fingerprint, approved=review.data["approved"])
            if not result.success:
                break
        if result.success:
            return OperationResult(True, None, "Mock demo state", "agent_demo", data={
                **result.data, "model_mode": "nicecode" if client is not None else "scripted_mock",
                "temporary_project_removed_on_exit": True,
            })
        return result
