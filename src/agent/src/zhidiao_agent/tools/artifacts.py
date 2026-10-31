"""Validate Intel HEX and discover the actual selected Keil target output."""

import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree

from ..deployment import DeploymentConfig
from ..errors import AgentError, ErrorCode

MAX_HEX_BYTES = 16 * 1024 * 1024


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_hex(path: Path) -> str:
    if not path.is_file() or path.suffix.lower() != ".hex":
        raise AgentError(ErrorCode.ARTIFACT_NOT_FOUND, "Require an existing .hex artifact.")
    if not 0 < path.stat().st_size <= MAX_HEX_BYTES:
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid firmware size.")
    try:
        lines = path.read_text(encoding="ascii").splitlines()
        ended = False
        has_data = False
        for line in lines:
            if not line.strip():
                continue
            if ended or not line.startswith(":") or not re.fullmatch(r":[0-9A-Fa-f]+", line):
                raise ValueError()
            record = bytes.fromhex(line[1:])
            if len(record) < 5 or len(record) != record[0] + 5 or sum(record) % 256:
                raise ValueError()
            kind, size = record[3], record[0]
            if kind not in (0, 1, 2, 3, 4, 5):
                raise ValueError()
            if kind in (1, 2, 3, 4, 5):
                if int.from_bytes(record[1:3], "big") != 0 or size != {1: 0, 2: 2, 3: 4, 4: 2, 5: 4}[kind]:
                    raise ValueError()
            ended = kind == 1
            has_data |= kind == 0 and size > 0
        if not ended or not has_data:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Firmware is not valid Intel HEX.") from None
    return file_digest(path)


def keil_target(project: Path, config: DeploymentConfig) -> tuple[Path, str, Path]:
    if not project.is_dir():
        raise AgentError(ErrorCode.PROJECT_NOT_FOUND, "Project directory does not exist.")
    if config.project_file:
        relative = Path(config.project_file.replace("\\", "/"))
        candidates = [config.local_path(str((project / relative).resolve()))]
    else:
        candidates = list(project.rglob("*.uvprojx"))
    if len(candidates) != 1 or not candidates[0].is_file() or candidates[0].suffix.lower() != ".uvprojx":
        raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Select exactly one Keil .uvprojx project.")
    project_file = config.local_path(str(candidates[0].resolve()))
    if not project_file.is_relative_to(project):
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Keil project must stay inside the selected directory.")
    try:
        if project_file.stat().st_size > 4 * 1024 * 1024:
            raise ValueError()
        xml = project_file.read_bytes()
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ValueError()
        targets = ElementTree.fromstring(xml).findall("./Targets/Target")
        selected = [t for t in targets if config.target is None or t.findtext("TargetName") == config.target]
        if len(selected) != 1:
            raise ValueError()
        target = selected[0]
        name = target.findtext("TargetName")
        common = target.find("./TargetOption/TargetCommonOption")
        output_dir = common.findtext("OutputDirectory")
        output_name = common.findtext("OutputName")
        if not name or common.findtext("CreateHexFile") != "1" or not output_dir:
            raise ValueError()
        if not output_name or not re.fullmatch(r"[A-Za-z0-9_ .-]+", output_name):
            raise ValueError()
        filename = output_name if output_name.lower().endswith(".hex") else output_name + ".hex"
        artifact = config.local_path(str((project_file.parent / output_dir.replace("\\", "/") / filename).resolve()))
        if not artifact.is_relative_to(project):
            raise ValueError()
    except (ElementTree.ParseError, ValueError, AttributeError):
        raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Invalid or ambiguous Keil target output configuration.") from None
    return project_file, name, artifact


def source_manifest(project: Path) -> dict[str, str]:
    """Ordered, bounded hashes of source/config inputs, excluding outputs."""
    suffixes = {".c", ".h", ".cpp", ".hpp", ".s", ".inc", ".sct", ".ld", ".uvprojx", ".uvoptx", ".ioc", ".lib",
                ".bat", ".cmd", ".py", ".sh", ".json", ".ini", ".cfg", ".cmake"}
    manifest = {}
    size = 0
    count = 0
    for path in sorted(project.rglob("*")):
        if path.suffix.lower() not in suffixes or any(part.casefold() in {".git", ".zhidiao"} for part in path.relative_to(project).parts):
            continue
        if not path.resolve().is_relative_to(project) or path.is_symlink():
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Source inputs must stay inside the project.")
        if not path.is_file():
            continue
        count += 1
        size += path.stat().st_size
        if count > 10000 or size > 64 * 1024 * 1024:
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Source snapshot is too large.")
        manifest[path.relative_to(project).as_posix()] = file_digest(path)
    return manifest


def manifest_digest(manifest: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name, value in manifest.items():
        digest.update(name.encode())
        digest.update(bytes.fromhex(value))
    return digest.hexdigest()


def source_digest(project: Path) -> str:
    """Bind approval to source/config inputs, excluding generated build outputs."""
    return manifest_digest(source_manifest(project))
