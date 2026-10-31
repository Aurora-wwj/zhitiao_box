"""Durable, bounded run snapshots. Loading a report never restores approvals."""

import json
import os
import re
import tempfile
from pathlib import Path

from .errors import AgentError, ErrorCode
from .models import OperationResult, invoke

MAX_REPORT_BYTES = 4 * 1024 * 1024
RUN_ID = re.compile(r"run_[0-9a-f]{32}")
_SECRET_FIELDS = {"api_key", "authorization", "password", "private_key", "access_token", "refresh_token"}


def _no_symlinks(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Report paths must not contain symlinks.")


def _redact(value):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if key.casefold() in _SECRET_FIELDS else _redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                       "[REDACTED]", value, flags=re.S)
        return re.sub(r"(?i)\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
    return value


def _document(raw: bytes) -> dict:
    if len(raw) > MAX_REPORT_BYTES:
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Run report exceeds its size limit.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
        json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError, RecursionError):
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Run report must be finite, valid UTF-8 JSON.") from None
    if (not isinstance(document, dict) or not isinstance(document.get("run_id"), str)
            or RUN_ID.fullmatch(document["run_id"]) is None
            or document.get("report_schema") != "1.0"
            or not isinstance(document.get("decision"), str)
            or type(document.get("attempts")) is not int
            or not 0 <= document["attempts"] <= 3):
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid run report schema.")
    return document


def read_report(filename: str) -> OperationResult:
    """Read an exported snapshot for review; this API grants no execution rights."""
    def operation():
        path = Path(filename).absolute()
        _no_symlinks(path)
        if not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require an existing bounded report file.")
        with path.open("rb") as stream:
            document = _document(stream.read(MAX_REPORT_BYTES + 1))
        return {"report": document, "path": str(path), "restores_approvals": False}
    return invoke(operation, backend="run_report")


class RunStore:
    """One atomic owner-readable JSON file per run, with no secret configuration."""
    def __init__(self, root: str | Path):
        self.root = Path(root).absolute()

    def _path(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or RUN_ID.fullmatch(run_id) is None:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid run report identity.")
        _no_symlinks(self.root)
        path = self.root / (run_id + ".json")
        _no_symlinks(path)
        return path

    def save(self, report: dict) -> OperationResult:
        def operation():
            if not isinstance(report, dict):
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a run report object.")
            try:
                raw = json.dumps(_redact(report), ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
            except (TypeError, ValueError, UnicodeError, RecursionError):
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Run report must contain finite JSON data.") from None
            document = _document(raw)
            path = self._path(document["run_id"])
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.exists() and not path.is_file():
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Report destination is not a regular file.")
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.root, prefix=".run-", delete=False) as stream:
                    temporary = Path(stream.name)
                    os.chmod(temporary, 0o600)
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                _no_symlinks(path)
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return {"path": str(path), "run_id": document["run_id"], "restores_approvals": False}
        return invoke(operation, backend="run_report")

    def load(self, run_id: str) -> OperationResult:
        result = invoke(lambda: {"path": str(self._path(run_id))}, backend="run_report")
        if not result.success:
            return result
        loaded = read_report(result.data["path"])
        if loaded.success and loaded.data["report"]["run_id"] != run_id:
            return OperationResult(False, ErrorCode.INVALID_RESPONSE.value,
                                   "Report file identity does not match its name.", "run_report")
        return loaded

    def list_runs(self) -> OperationResult:
        def operation():
            _no_symlinks(self.root)
            if not self.root.exists():
                return {"runs": []}
            if not self.root.is_dir():
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Report directory is not accessible.")
            paths = sorted(self.root.glob("run_*.json"))
            if len(paths) > 10000:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Report directory exceeds its listing limit.")
            return {"runs": [path.stem for path in paths if RUN_ID.fullmatch(path.stem) and not path.is_symlink()]}
        return invoke(operation, backend="run_report")
