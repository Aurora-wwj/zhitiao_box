"""In-memory approval state for a trusted human-facing application.

Keep this object outside model tools. It is not an authentication system.
No operation is executed here. Approvals expire when the process exits.
"""

import hashlib
import json
import uuid
from typing import Any

from .errors import AgentError, ErrorCode
from .models import OperationResult, invoke


def _fingerprint(action: str, params: dict[str, Any]) -> str:
    if not isinstance(action, str) or not action.strip() or not isinstance(params, dict):
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid approval proposal.")
    try:
        encoded = json.dumps(
            {"action": action, "params": params}, sort_keys=True,
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Proposal must be JSON serializable.") from None
    return hashlib.sha256(encoded).hexdigest()


class ApprovalGate:
    def __init__(self) -> None:
        self._pending: dict[str, str] = {}
        self._approved: dict[str, str] = {}

    def propose(self, action: str, params: dict[str, Any]) -> OperationResult:
        def operation() -> dict[str, Any]:
            fingerprint = _fingerprint(action, params)
            proposal_id = uuid.uuid4().hex
            # Round-trip ensures the preview is detached from mutable input.
            preview = json.loads(json.dumps(params, allow_nan=False))
            self._pending[proposal_id] = fingerprint
            return {
                "proposal_id": proposal_id, "fingerprint": fingerprint,
                "action": action, "params": preview, "state": "pending",
            }
        return invoke(operation, backend="approval")

    def decide(
        self, proposal_id: str, fingerprint: str, *, approved: bool,
    ) -> OperationResult:
        """Only a trusted human-facing caller may invoke this method."""
        def operation() -> dict[str, Any]:
            if not isinstance(proposal_id, str) or not isinstance(fingerprint, str):
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid approval identity.")
            if type(approved) is not bool:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require an explicit boolean decision.")
            if self._pending.get(proposal_id) != fingerprint:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Proposal is missing or changed.")
            del self._pending[proposal_id]
            if not approved:
                raise AgentError(ErrorCode.APPROVAL_REJECTED, "Human rejected the operation.")
            self._approved[proposal_id] = fingerprint
            return {"approval_id": proposal_id, "state": "approved"}
        return invoke(operation, backend="approval")

    def consume(
        self, approval_id: str, action: str, params: dict[str, Any],
    ) -> OperationResult:
        def operation() -> dict[str, Any]:
            fingerprint = _fingerprint(action, params)
            if not isinstance(approval_id, str):
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Approval is required.")
            if self._approved.pop(approval_id, None) != fingerprint:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Approval is missing, used or changed.")
            return {"state": "consumed"}
        return invoke(operation, backend="approval")
