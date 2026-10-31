"""Reviewed local deployment profiles and read-only first-pairing diagnostics.

This module never installs keys, changes networking, loads an FPGA, or edits a
board's boot files. Existing key/host files are checked by metadata, not read.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .approval import ApprovalGate
from .deployment import DeploymentConfig
from .errors import AgentError, ErrorCode
from .models import OperationResult, invoke
from .tools.artifacts import keil_target
from .tools.commands import ProcessRunner
from .tools.ssh import ssh_command
from .tools.remote import clock_helper


def _require(result: OperationResult) -> dict:
    if not result.success:
        try:
            code = ErrorCode(result.error_code)
        except ValueError:
            code = ErrorCode.INTERNAL_ERROR
        raise AgentError(code, result.message)
    return result.data


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _destination(value: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a local profile output path.")
    path = Path(value).absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            raise AgentError(ErrorCode.INVALID_ARGUMENT, "Profile output must not traverse symlinks.")
    if path.exists():
        raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Profile output already exists; existing deployment files are never overwritten.")
    if not path.parent.is_dir() or path.suffix.lower() != ".json":
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Choose a .json file in an existing local directory.")
    return path


def _local_state(config: DeploymentConfig) -> dict:
    checks = []
    signatures = {}

    def check(name, valid, detail):
        checks.append({"name": name, "status": "PASS" if valid else "FAIL", "detail": detail})

    check("python", sys.version_info >= (3, 13), "Python 3.13 or newer is required.")
    root = config.local_path(config.allowed_roots[0])
    check("project", root.is_dir(), str(root))
    check("keil", bool(config.keil_executable and Path(config.keil_executable).is_file()),
          config.keil_executable or "Keil executable is not configured.")
    for name in ("ssh", "scp"):
        found = shutil.which(name)
        check(name, found is not None, found or "Executable is not available on PATH.")
    for name in ("known_hosts", "identity_file"):
        value = getattr(config, name)
        if name == "identity_file" and value is None:
            checks.append({"name": name, "status": "UNKNOWN", "detail": "SSH-agent authentication must be verified remotely."})
            continue
        check(name, bool(value and Path(value).is_file()),
              value or "Required local file is not configured.")
        if value and Path(value).is_file():
            stat = Path(value).stat()
            signatures[name] = {"path": str(Path(value).resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if root.is_dir():
        try:
            project_file, target, artifact = keil_target(root, config)
            stat = project_file.stat()
            signatures["project_file"] = {"path": str(project_file), "size": stat.st_size,
                                          "mtime_ns": stat.st_mtime_ns,
                                          "sha256": hashlib.sha256(project_file.read_bytes()).hexdigest()}
            checks.append({"name": "keil_target", "status": "PASS", "detail": target,
                           "project_file": str(project_file), "artifact_path": str(artifact)})
        except AgentError as exc:
            checks.append({"name": "keil_target", "status": "FAIL", "detail": str(exc)})
    return {"checks": checks, "input_metadata": signatures,
            "local_ready": not any(item["status"] == "FAIL" for item in checks),
            "trust_note": "Existence checks do not verify host-key fingerprints or prove the SSH identity is authorized."}


def diagnostic_plan(config: DeploymentConfig) -> dict:
    """Pure command construction; no transport, register, or key-content access."""
    board = config.board
    observer = config.observer
    script = [
        "set -eu", 'DHOME="${HOME:-}"', "printf 'ZHIDIAO_DEPLOY_V1\\n'",
        "printf 'ssh_connection\\tPASS\\n'",
        'case "$DHOME" in /*) printf \'remote_home\\tPASS\\t%s\\n\' "$DHOME" ;; *) printf \'remote_home\\tFAIL\\n\' ;; esac',
        'if [ -n "$DHOME" ] && [ -r "$DHOME/.ssh/authorized_keys" ] && [ -s "$DHOME/.ssh/authorized_keys" ]; then printf \'authorized_keys\\tPASS\\n\'; else printf \'authorized_keys\\tFAIL\\n\'; fi',
        "if test -x " + shlex.quote(str(board.openocd_bin)) + "; then printf 'openocd\\tPASS\\n'; else printf 'openocd\\tFAIL\\n'; fi",
        "if test -r " + shlex.quote(str(board.openocd_scripts / "interface/stlink.cfg"))
        + " && test -r " + shlex.quote(str(board.openocd_scripts / "target/stm32g4x.cfg"))
        + "; then printf 'openocd_scripts\\tPASS\\n'; else printf 'openocd_scripts\\tFAIL\\n'; fi",
        "if command -v lsusb >/dev/null 2>&1; then usb=$(lsusb 2>/dev/null) || usb=''; case \"$usb\" in *0483:3748*|*0483:374b*|*0483:3752*) printf 'stlink_usb\\tPASS\\n' ;; *) printf 'stlink_usb\\tFAIL\\n' ;; esac; else printf 'stlink_usb\\tUNKNOWN\\n'; fi",
    ]
    if observer is None:
        script.extend(["printf 'busybox\\tUNKNOWN\\n'", "printf 'prog_done\\tUNKNOWN\\n'", "printf 'observer_registers\\tUNKNOWN\\n'"])
    else:
        script.extend([
            "BB=" + shlex.quote(observer.busybox_path), "ready=0",
            'if test -x "$BB"; then printf \'busybox\\tPASS\\n\'; else printf \'busybox\\tFAIL\\n\'; fi',
            "if test -r " + shlex.quote(observer.prog_done_path)
            + ' && [ "$("$BB" cat ' + shlex.quote(observer.prog_done_path) + ' 2>/dev/null)" = "1" ]; then ready=1; printf \'prog_done\\tPASS\\n\'; else printf \'prog_done\\tFAIL\\n\'; fi',
            "registers=PASS",
            'if [ "$ready" = 1 ]; then',
        ])
        for address in (observer.period_addr, observer.high_addr, observer.edge_addr, observer.valid_addr):
            script.extend([
                '  raw=$("$BB" devmem ' + shlex.quote(address) + ' 32 2>/dev/null) || raw=bad',
                '  case "$raw" in 0x*) digits=${raw#0x}; case "$digits" in \'\'|*[!0123456789abcdefABCDEF]*) registers=FAIL ;; *) [ "${#digits}" -le 8 ] || registers=FAIL ;; esac ;; *) registers=FAIL ;; esac',
            ])
        script.extend(['else registers=UNKNOWN; fi', 'printf \'observer_registers\\t%s\\n\' "$registers"'])
    timing = observer or config.uart_observer
    if timing is not None:
        script.extend([
            "BB=" + shlex.quote(timing.busybox_path),
            'if "$BB" usleep 0 >/dev/null 2>&1; then printf \'busybox_usleep\\tPASS\\n\'; else printf \'busybox_usleep\\tFAIL\\n\'; fi',
            clock_helper(timing.monotonic_path),
            'if clock_value=$(clock_ms 2>/dev/null); then printf \'monotonic_clock\\tPASS\\n\'; else printf \'monotonic_clock\\tFAIL\\n\'; fi',
        ])
    else:
        script.extend(["printf 'busybox_usleep\\tUNKNOWN\\n'", "printf 'monotonic_clock\\tUNKNOWN\\n'"])
    checks = ["ssh_connection", "remote_home", "authorized_keys", "openocd", "openocd_scripts",
              "stlink_usb", "busybox", "prog_done", "observer_registers", "busybox_usleep", "monotonic_clock"]
    if config.uart_observer is not None:
        uart = config.uart_observer
        checks.append("uart_registers")
        script.extend([
            "BB=" + shlex.quote(uart.busybox_path),
            "if test -r " + shlex.quote(uart.prog_done_path) + ' && [ "$("$BB" cat '
            + shlex.quote(uart.prog_done_path) + ' 2>/dev/null)" = 1 ]; then',
            '  raw=$("$BB" devmem ' + uart.status_addr + ' 32 2>/dev/null) || raw=bad',
            '  case "$raw" in 0x*) digits=${raw#0x}; case "$digits" in \'\'|*[!0123456789abcdefABCDEF]*) uart=FAIL ;; *) if [ "${#digits}" -le 8 ]; then uart=PASS; else uart=FAIL; fi ;; esac ;; *) uart=FAIL ;; esac',
            'else uart=UNKNOWN; fi',
            'printf \'uart_registers\\t%s\\n\' "$uart"',
        ])
    return {
        "deployment": _json(asdict(config)),
        "commands": [list(ssh_command(config) + ("\n".join(script),))],
        "timeout_s": 20,
        "check_names": checks,
        "effects": "Read-only SSH checks of HOME, authorized_keys presence, OpenOCD files, USB ST-Link candidates and prepared PL registers; no build, flash, key installation, bitstream load or boot changes.",
        "limits": "USB ID presence is not a SWD test; prog_done does not identify the running PL image. Use real-test for freshness and real-flash for SWD verification.",
    }


def _execute_diagnostics(plan: dict, runner) -> dict:
    outcome = runner.run(tuple(plan["commands"][0]), plan["timeout_s"])
    if outcome.returncode == 255:
        raise AgentError(ErrorCode.SSH_CONNECT_FAILED, "SSH authentication, host verification or connection failed.")
    if outcome.returncode != 0:
        raise AgentError(ErrorCode.BACKEND_UNAVAILABLE, "Read-only deployment checks did not complete.")
    lines = outcome.output.splitlines()
    if not lines or lines.pop(0) != "ZHIDIAO_DEPLOY_V1":
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid deployment diagnostic response.")
    expected = set(plan["check_names"])
    checks = []
    seen = set()
    for line in lines:
        fields = line.split("\t")
        if (len(fields) not in (2, 3) or fields[0] not in expected or fields[0] in seen
                or fields[1] not in {"PASS", "FAIL", "UNKNOWN"}
                or (len(fields) == 3 and (fields[0] != "remote_home" or not re.fullmatch(r"/[A-Za-z0-9_./-]+", fields[2])))):
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Malformed deployment diagnostic check.")
        seen.add(fields[0])
        checks.append({"name": fields[0], "status": fields[1], **({"home": fields[2]} if len(fields) == 3 else {})})
    if seen != expected:
        raise AgentError(ErrorCode.INVALID_RESPONSE, "Deployment diagnostic response is incomplete.")
    return {"checks": checks, "decision": "NOT_READY" if any(row["status"] == "FAIL" for row in checks)
            else "INCOMPLETE" if any(row["status"] == "UNKNOWN" for row in checks) else "READY",
            "limits": plan["limits"]}


@dataclass(frozen=True)
class _SetupPlan:
    proposal_id: str
    fingerprint: str
    params: dict


class DeploymentSetup:
    def __init__(self, config: DeploymentConfig, *, runner=None, approvals=None):
        self.config = config
        self.runner = runner if runner is not None else ProcessRunner()
        self.approvals = approvals if approvals is not None else ApprovalGate()
        self._plans: dict[str, _SetupPlan] = {}

    def preview(self, output_path: str, *, check_remote: bool = False) -> OperationResult:
        def operation():
            if type(check_remote) is not bool:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require an explicit remote-check selection.")
            output = _destination(output_path)
            local = _local_state(self.config)
            params = {"output_path": str(output), "profile": _json(asdict(self.config)), "local": local,
                      "remote": diagnostic_plan(self.config) if check_remote else None,
                      "effects": "Create this new local deployment JSON; never overwrite an existing profile. Optional checks are read-only and run only after this approval."}
            proposal = _require(self.approvals.propose("setup_deployment", params))
            self._plans[proposal["proposal_id"]] = _SetupPlan(proposal["proposal_id"], proposal["fingerprint"], _json(params))
            return proposal
        return invoke(operation, backend="deployment_setup")

    def apply(self, proposal_id: str) -> OperationResult:
        def operation():
            plan = self._plans.pop(proposal_id, None)
            if plan is None:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Create and approve a deployment preview first.")
            output = _destination(plan.params["output_path"])
            if _json(asdict(self.config)) != plan.params["profile"] or _local_state(self.config) != plan.params["local"]:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Deployment inputs changed after preview.")
            _require(self.approvals.consume(proposal_id, "setup_deployment", plan.params))
            if not plan.params["local"]["local_ready"]:
                raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Local prerequisites failed; fix the listed checks before creating a profile.")
            remote = _execute_diagnostics(plan.params["remote"], self.runner) if plan.params["remote"] else None
            data = (json.dumps(plan.params["profile"], ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".zhidiao-setup-", delete=False) as stream:
                    temporary = Path(stream.name)
                    os.chmod(temporary, 0o600)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                # A hard link publishes complete contents atomically and fails
                # if another process created the destination after the preview.
                os.link(temporary, output)
            except FileExistsError:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Output was created after preview; it was not overwritten.") from None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return {"profile_path": str(output), "profile_sha256": hashlib.sha256(data).hexdigest(),
                    "local": plan.params["local"], "remote": remote,
                    "decision": remote["decision"] if remote else "CONFIGURED_NOT_VERIFIED"}
        return invoke(operation, backend="deployment_setup")


class DeploymentDiagnostics:
    def __init__(self, config: DeploymentConfig, *, runner=None, approvals=None):
        self.config = config
        self.runner = runner if runner is not None else ProcessRunner()
        self.approvals = approvals if approvals is not None else ApprovalGate()
        self._plans = {}

    def preview(self) -> OperationResult:
        def operation():
            params = diagnostic_plan(self.config)
            proposal = _require(self.approvals.propose("deployment_diagnostics", params))
            self._plans[proposal["proposal_id"]] = _SetupPlan(proposal["proposal_id"], proposal["fingerprint"], _json(params))
            return proposal
        return invoke(operation, backend="deployment_diagnostics")

    def run(self, proposal_id: str) -> OperationResult:
        def operation():
            plan = self._plans.pop(proposal_id, None)
            if plan is None:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Preview and approve deployment diagnostics first.")
            if diagnostic_plan(self.config) != plan.params:
                raise AgentError(ErrorCode.APPROVAL_REQUIRED, "Diagnostic configuration changed after preview.")
            _require(self.approvals.consume(proposal_id, "deployment_diagnostics", plan.params))
            return _execute_diagnostics(plan.params, self.runner)
        return invoke(operation, backend="deployment_diagnostics")
