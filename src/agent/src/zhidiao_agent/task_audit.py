"""Persist task entry before the first model call; never restore permissions."""

import json
import time
import uuid

from .errors import AgentError, ErrorCode
from .models import OperationResult
from .provenance import validate_model_info
from .reports import RunStore


class TaskAudit:
    def __init__(self, store: RunStore, *, task: str, project_path: str, source_files: dict,
                 observed_gpio: str, include_uart: bool, max_attempts: int, timeout_s: float,
                 model_info: dict, resume_from: str | None = None, context_sharing_approved: bool = False):
        self.store = store
        self.run_id = "run_" + uuid.uuid4().hex
        self.started = time.monotonic()
        self.wall_started_at = time.time()
        self.metadata = {"task": task, "project_path": project_path,
                         "allowed_sources": list(source_files), "source_files": source_files,
                         "include_uart": include_uart, "timeout_s": timeout_s, "goal": None}
        self.observed_gpio, self.max_attempts = observed_gpio, max_attempts
        self.model_info = validate_model_info(model_info)
        self.resume_from = resume_from
        self.context_sharing_approved = context_sharing_approved
        self.goal = None
        self.clarifications = []
        self.reviews = []
        self.error = None

    def record_error(self, result: OperationResult):
        values = result.to_dict()
        self.error = {name: values[name] for name in ("error_code", "message", "backend", "duration_ms", "status_code")
                      if name in values}

    def record_review(self, action, preview, *, approved, error_code=None):
        self.reviews.append({"action": action, "proposal_id": preview["proposal_id"],
                             "fingerprint": preview["fingerprint"], "approved": approved,
                             "error_code": error_code,
                             "params": json.loads(json.dumps(preview.get("params", {}), allow_nan=False))})
        self.reviews = self.reviews[-16:]

    def context(self) -> dict:
        return json.loads(json.dumps({"wall_started_at": self.wall_started_at,
            "elapsed_s": max(0, time.monotonic() - self.started),
            "context_sharing_approved": self.context_sharing_approved,
            "model_info": self.model_info, "goal_response": self.goal,
            "clarifications": self.clarifications, "reviews": self.reviews,
            "last_error": self.error, "resume_from": self.resume_from}, allow_nan=False))

    def render(self, phase, *, reason=None, events=()) -> dict:
        context = self.context()
        metadata = {**self.metadata, "goal": self.goal.get("params") if isinstance(self.goal, dict) else None,
                    "model_info": self.model_info}
        return {"run_id": self.run_id, "report_schema": "1.0", "report_stage": "task_entry",
                "decision": phase, "reason": reason or phase, "attempts": 0, "max_attempts": self.max_attempts,
                "metadata": metadata, "model_info": self.model_info, "task_entry": context,
                "observed_gpio": self.observed_gpio, "evidence_source": "none",
                "verification_scope": "gpio_period_and_uart_capture" if metadata["include_uart"] else "gpio_period_only",
                "wall_started_at": self.wall_started_at, "elapsed_s": context["elapsed_s"],
                "report_path": str(self.store.root / (self.run_id + ".json")),
                "parent_run_id": self.resume_from, "hardware_state_uncertain": False,
                "checkpoint": None, "in_flight": "goal_interpretation" if phase == "ANALYZING_GOAL" else None,
                "events": list(events), "reviews": list(self.reviews), "cycles": []}

    def save(self, phase, *, reason=None, events=()) -> dict:
        report = self.render(phase, reason=reason, events=events)
        saved = self.store.save(report)
        if not isinstance(saved, OperationResult) or not saved.success:
            raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "Cannot persist the task-entry audit report.")
        return report
