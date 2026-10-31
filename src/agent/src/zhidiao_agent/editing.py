"""Single-file, human-approved UTF-8 source updates with stale-input protection."""

import difflib
import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from .approval import ApprovalGate
from .errors import AgentError, ErrorCode
from .models import OperationResult, invoke

MAX_SOURCE_BYTES = 131072


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class _Edit:
    path: str
    before: bytes
    after: bytes
    params: dict


class SourceEditor:
    def __init__(self, project: str, allowed_files: tuple[str, ...], *, approvals: ApprovalGate | None = None):
        self.project = Path(project).resolve()
        self.allowed_files = allowed_files
        self.approvals = approvals if approvals is not None else ApprovalGate()
        self._pending: dict[str, _Edit] = {}

    def _path(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or "\0" in relative:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid source path.")
        posix = PurePosixPath(relative)
        if ("\\" in relative or posix.is_absolute() or PureWindowsPath(relative).drive
                or ".." in posix.parts or relative != posix.as_posix()
                or any(part.casefold() in {".git", ".codex", ".agents", ".zhidiao"} for part in posix.parts)
                or relative not in self.allowed_files or posix.suffix.lower() not in {".c", ".h", ".s", ".cpp", ".hpp"}):
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Source path is outside the explicit edit allowlist.")
        path = self.project
        for part in posix.parts:
            path = path / part
            if path.is_symlink():
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Symlink source paths are not editable.")
        if not path.resolve().is_relative_to(self.project) or not path.is_file():
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require an existing source file inside the project.")
        return path

    def _read(self, path: Path) -> bytes:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Source file exceeds the edit size limit.")
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Only UTF-8 source files are supported.") from None
        if "\0" in text:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Binary source files are not editable.")
        return data

    def snapshot(self) -> OperationResult:
        def operation():
            if not 1 <= len(self.allowed_files) <= 8:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Select one to eight explicit source files.")
            sources = {}
            total = 0
            for name in self.allowed_files:
                content = self._read(self._path(name))
                total += len(content)
                if total > 262144:
                    raise AgentError(ErrorCode.INVALID_ARGUMENT, "Source context exceeds its total size limit.")
                sources[name] = {"sha256": digest(content), "content": content.decode("utf-8")}
            return {"sources": sources}
        return invoke(operation, backend="source_editor")

    def preview(self, edit: dict) -> OperationResult:
        def operation():
            if not isinstance(edit, dict) or set(edit) != {"path", "before_sha256", "content"}:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require one explicit source replacement.")
            path = self._path(edit["path"])
            before = self._read(path)
            if edit["before_sha256"] != digest(before):
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Model used stale source; obtain a fresh decision.")
            if not isinstance(edit["content"], str) or "\0" in edit["content"]:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid replacement source text.")
            after = edit["content"].encode("utf-8")
            if len(after) > MAX_SOURCE_BYTES or after == before:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Replacement is too large or makes no change.")
            lines = difflib.unified_diff(
                before.decode("utf-8").splitlines(keepends=True),
                after.decode("utf-8").splitlines(keepends=True),
                fromfile="a/" + edit["path"], tofile="b/" + edit["path"],
            )
            change = "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)
            params = {"project": str(self.project), "path": edit["path"],
                      "before_sha256": digest(before), "after_sha256": digest(after), "diff": change}
            preview = self.approvals.propose("edit_source", params)
            if not preview.success:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Cannot create edit approval.")
            self._pending[preview.data["proposal_id"]] = _Edit(edit["path"], before, after, params)
            return preview.data
        return invoke(operation, backend="source_editor")

    def apply(self, proposal_id: str) -> OperationResult:
        def operation():
            if not isinstance(proposal_id, str):
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid edit proposal identity.")
            edit = self._pending.pop(proposal_id, None)
            if edit is None:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Edit is missing or already consumed.")
            path = self._path(edit.path)
            if self._read(path) != edit.before:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Source changed after preview; approval is stale.")
            permission = self.approvals.consume(proposal_id, "edit_source", edit.params)
            if not permission.success:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Human approval is required before writing source.")
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".zhidiao-edit-", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(edit.after)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
                if self._read(self._path(edit.path)) != edit.before:
                    raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Source changed while preparing the edit.")
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return {"path": edit.path, "before_sha256": digest(edit.before), "after_sha256": digest(edit.after)}
        return invoke(operation, backend="source_editor")
