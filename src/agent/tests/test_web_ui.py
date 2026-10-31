import http.client
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from zhidiao_agent.deployment import DeploymentConfig, PLObserverConfig
from zhidiao_agent.agent import Agent
from zhidiao_agent.controller import Controller
from zhidiao_agent.models import OperationResult
from zhidiao_agent.orchestrator import Orchestrator
from zhidiao_agent.tools.feedback_mock import FeedbackMockBackend
from zhidiao_agent.web_ui import WebUIService, create_server, run_server, HTML


def success(data=None):
    return OperationResult(True, None, "mock", "mock", data=data or {})


class WebServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="zhidiao-web-ui-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        self.source = self.project / "main.c"
        self.source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
        self.config = DeploymentConfig(allowed_roots=(str(self.project),), observer=PLObserverConfig())
        self.enterContext(patch("zhidiao_agent.web_ui.DeploymentConfig.load", return_value=self.config))
        self.backend = self.enterContext(patch("zhidiao_agent.web_ui.RealBackend")).return_value
        self.backend.preview_build.return_value = success()
        self.backend.preview_observation.return_value = success()
        self.client = Mock()
        self.factory = Mock(return_value=self.client)
        self.loop_class = self.enterContext(patch("zhidiao_agent.web_ui.Orchestrator"))
        self.loop = self.loop_class.return_value
        self.loop.cancel.return_value = success({"decision": "STOPPED", "reason": "HUMAN_CANCELLED"})
        self.loop.report.return_value = {"decision": "STOPPED", "cycles": []}
        self.loop.review_execution.return_value = success({"decision": "READY"})
        self.loop.review_edit.return_value = success({"decision": "READY"})
        self.service = WebUIService("local.json", str(self.project), ("main.c",), self.factory,
                                    include_uart=False, report_dir=str(self.project / ".zhidiao" / "runs"))
        self.addCleanup(self.service.close)
        self.ready_goal = {"status": "ready", "test_id": "gpio_period", "observed_gpio": "PA1",
                           "params": {"expected_period_ms": 1000, "tolerance_ms": 50},
                           "summary": "PA1 完整周期 1000 ±50 ms"}
        self.respond(self.ready_goal)

    def respond(self, data):
        self.client.generate.return_value = success({"content": json.dumps(data)})

    def wait(self):
        self.service._worker.join(timeout=3)
        self.assertFalse(self.service._worker.is_alive())
        return self.service.snapshot().data["state"]

    def start(self):
        self.assertTrue(self.service.start("把 PA1 完整周期调到 1000 ms，误差不超过 50 ms", share_context=True).success)
        state = self.wait()
        self.assertEqual(state["phase"], "AWAITING_GOAL_APPROVAL", state)
        return state

    def review(self, pending, approved=True):
        self.assertTrue(self.service.review(pending["proposal_id"], pending["fingerprint"], approved=approved).success)
        return self.wait()

    def test_preflight_and_scope_do_not_construct_model_or_touch_hardware(self):
        state = self.service.snapshot().data["state"]
        self.assertEqual(state["phase"], "IDLE")
        self.assertEqual(state["scope"]["observed_gpio"], "PA1")
        self.factory.assert_not_called()
        self.backend.build_firmware.assert_not_called()

    def test_context_sharing_consent_is_explicit(self):
        self.service.start("PA1 完整周期 1000 ms，误差 50 ms", share_context=False)
        state = self.wait()
        self.assertEqual(state["last_result"]["error_code"], "APPROVAL_REQUIRED")
        self.factory.assert_not_called()
        self.loop_class.assert_not_called()

    def test_wrong_physical_gpio_is_rejected_before_model(self):
        self.service.start("把 PB3 完整周期调到 1000 ms，误差 50 ms", share_context=True)
        state = self.wait()
        self.assertEqual(state["last_result"]["error_code"], "INVALID_ARGUMENT")
        self.factory.assert_not_called()

    def test_invalid_unicode_is_rejected_before_any_model_request(self):
        self.service.start("bad\ud800", share_context=True)
        state = self.wait()
        self.assertEqual(state["last_result"]["error_code"], "INVALID_ARGUMENT")
        self.factory.assert_not_called()

    def test_goal_confirmation_precedes_any_orchestrator_cycle(self):
        state = self.start()
        self.assertEqual(state["pending"]["params"]["observed_gpio"], "PA1")
        self.loop_class.assert_not_called()
        self.backend.build_firmware.assert_not_called()

    def test_goal_rejection_never_starts_tools(self):
        state = self.review(self.start()["pending"], False)
        self.assertEqual(state["phase"], "STOPPED")
        self.assertEqual(state["last_result"]["error_code"], "APPROVAL_REJECTED")
        self.loop_class.assert_not_called()

    def test_browser_review_uses_exact_pending_identity_for_cycle_and_edit(self):
        cycle = {"proposal_id": "cycle-1", "fingerprint": "c" * 64, "params": {"steps": ["build", "flash", "measure"]}}
        edit = {"proposal_id": "edit-1", "fingerprint": "e" * 64, "params": {"diff": "--- main.c\n-old\n+new\n"}, "reason": "Measured too fast"}
        self.loop.advance.side_effect = [
            success({"decision": "AWAITING_EXECUTION_APPROVAL", "pending_execution": cycle}),
            success({"decision": "AWAITING_APPROVAL", "pending_edit": edit}),
            success({"decision": "PASS", "cycles": [{"measurement": 1001}]}),
        ]
        goal = self.start()["pending"]
        state = self.review(goal)
        self.assertEqual(state["phase"], "AWAITING_EXECUTION_APPROVAL")
        self.loop.review_execution.assert_not_called()
        state = self.review(state["pending"])
        self.assertEqual(state["phase"], "AWAITING_APPROVAL")
        self.loop.review_execution.assert_called_once_with("cycle-1", "c" * 64, approved=True)
        state = self.review(state["pending"])
        self.assertEqual(state["phase"], "PASS")
        self.loop.review_edit.assert_called_once_with("edit-1", "e" * 64, approved=True)
        self.assertIn("report_store", self.loop_class.call_args.kwargs)

    def test_changed_identity_does_not_approve_a_goal(self):
        pending = self.start()["pending"]
        state = self.review({**pending, "fingerprint": "wrong"})
        self.assertEqual(state["last_result"]["error_code"], "APPROVAL_REQUIRED")
        self.loop_class.assert_not_called()

    def test_source_change_while_goal_is_reviewed_stops_before_cycle(self):
        goal = self.start()["pending"]
        self.source.write_text("externally changed\n")
        state = self.review(goal)
        self.assertEqual(state["last_result"]["error_code"], "APPROVAL_REQUIRED")
        self.loop_class.assert_not_called()

    def test_clarification_retains_original_task_and_explicit_answer(self):
        self.respond({"status": "clarification", "question": "误差允许多少毫秒？"})
        self.service.start("把 PA1 完整周期调到 1000 ms", share_context=True)
        state = self.wait()
        self.assertEqual(state["phase"], "NEEDS_CLARIFICATION")
        self.respond(self.ready_goal)
        self.service.clarify("误差不超过 50 ms")
        state = self.wait()
        self.assertEqual(state["phase"], "AWAITING_GOAL_APPROVAL", state)
        request = json.loads(self.client.generate.call_args.args[0][-1]["content"])
        self.assertEqual(request["task"], "把 PA1 完整周期调到 1000 ms")
        self.assertEqual(request["clarifications"][-1]["answer"], "误差不超过 50 ms")

    def test_cancel_during_model_request_prevents_later_goal_or_tool_approval(self):
        entered, release = threading.Event(), threading.Event()
        def model(messages):
            entered.set()
            release.wait(2)
            return success({"content": json.dumps(self.ready_goal)})
        self.client.generate.side_effect = model
        self.service.start("PA1 完整周期 1000 ms，误差 50 ms", share_context=True)
        self.assertTrue(entered.wait(1))
        self.assertTrue(self.service.cancel().success)
        release.set()
        state = self.wait()
        self.assertEqual(state["phase"], "STOPPED")
        self.assertEqual(state["last_result"]["error_code"], "CANCELLED")
        self.loop_class.assert_not_called()

    def test_concurrent_review_is_not_queued_or_auto_approved(self):
        entered, release = threading.Event(), threading.Event()
        def model(messages):
            entered.set()
            release.wait(2)
            return success({"content": json.dumps(self.ready_goal)})
        self.client.generate.side_effect = model
        self.service.start("PA1 完整周期 1000 ms，误差 50 ms", share_context=True)
        self.assertTrue(entered.wait(1))
        result = self.service.review("made-up", "x" * 64, approved=True)
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        release.set()
        self.wait()
        self.loop_class.assert_not_called()

    def test_history_resume_reprompts_goal_and_never_restores_saved_approval(self):
        run_id = "run_" + "a" * 32
        saved = {"run_id": run_id, "report_schema": "1.0", "decision": "AWAITING_EXECUTION_APPROVAL",
                 "observed_gpio": "PA1", "max_attempts": 3, "attempts": 0,
                 "pending_execution": {"proposal_id": "old", "fingerprint": "old"},
                 "metadata": {"task": "PA1 完整周期 1000 ms，误差 50 ms", "goal": self.ready_goal["params"],
                              "project_path": str(self.project), "allowed_sources": ["main.c"],
                              "include_uart": False, "timeout_s": 299.5}}
        store = self.service._report_store = Mock()
        store.root = self.project / ".zhidiao" / "runs"
        store.save.return_value = success()
        store.load.return_value = success({"report": saved})
        store.list_runs.return_value = success({"runs": [run_id]})
        self.assertEqual(self.service.list_runs().data["runs"], [run_id])
        self.assertTrue(self.service.resume(run_id, share_context=True).success)
        state = self.wait()
        self.assertEqual(state["phase"], "AWAITING_GOAL_APPROVAL")
        self.assertNotEqual(state["pending"]["proposal_id"], "old")
        self.client.generate.assert_not_called()
        self.loop_class.assert_not_called()
        self.loop.advance.return_value = success({"decision": "AWAITING_EXECUTION_APPROVAL",
                                                 "pending_execution": {"proposal_id": "fresh", "fingerprint": "new", "params": {}}})
        self.review(state["pending"])
        self.assertEqual(self.loop_class.call_args.kwargs["recovery_report"], saved)
        self.assertEqual(self.loop_class.call_args.kwargs["timeout_s"], 299.5)
        self.loop.review_execution.assert_not_called()

    def test_recovery_scope_mismatch_never_constructs_model(self):
        store = self.service._report_store = Mock()
        store.load.return_value = success({"report": {"run_id": "run_" + "a" * 32,
            "observed_gpio": "PB3", "metadata": {"project_path": str(self.project)}}})
        self.service.resume("run_" + "a" * 32, share_context=True)
        state = self.wait()
        self.assertEqual(state["last_result"]["error_code"], "APPROVAL_REQUIRED")
        self.factory.assert_not_called()
        self.loop_class.assert_not_called()

    def test_close_waits_for_model_response_and_finishes_cancellation(self):
        entered, release = threading.Event(), threading.Event()
        def model(messages):
            entered.set()
            release.wait(3)
            return success({"content": json.dumps(self.ready_goal)})
        self.client.generate.side_effect = model
        self.service.start("PA1 完整周期 1000 ms，误差 50 ms", share_context=True)
        self.assertTrue(entered.wait(1))
        delayed_response = threading.Timer(1.25, release.set)
        delayed_response.start()
        try:
            self.service.close()
            self.assertFalse(self.service._worker.is_alive())
            state = self.service.snapshot().data["state"]
            self.assertEqual(state["phase"], "STOPPED")
            self.assertFalse(state["busy"])
            self.assertIsNone(state["pending"])
            self.assertEqual(state["last_result"]["error_code"], "CANCELLED")
            self.loop_class.assert_not_called()
        finally:
            release.set()
            delayed_response.join(timeout=2)
            self.service._worker.join(timeout=3)

    def test_close_stops_native_command_and_saves_terminal_report_before_returning(self):
        # The patch replaces only RealBackend; its configured process runner is real.
        from zhidiao_agent import web_ui
        runner = web_ui.RealBackend.call_args.kwargs["runner"]
        self.service._loop = Orchestrator(
            Controller(FeedbackMockBackend(str(self.project)), allowed_roots=(str(self.project),)),
            Agent(self.client), self.service._editor, task="PA1 1000 ms +/- 50 ms",
            project_path=str(self.project), params=self.ready_goal["params"],
            report_store=self.service._report_store,
        )
        ready, finished = self.project / "ready", self.project / "should-not-finish"
        script = ("from pathlib import Path; import time; "
                  f"Path({str(ready)!r}).write_text('ready'); "
                  f"time.sleep(2); Path({str(finished)!r}).write_text('continued')")
        def operation():
            runner.run((sys.executable, "-B", "-c", script), 5)
            return {"unexpected": "command completed"}
        self.service._schedule(operation)
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            threading.Event().wait(.01)
        try:
            self.assertTrue(ready.exists())
            self.service.close()
            self.assertFalse(self.service._worker.is_alive())
            self.assertFalse(finished.exists())
            state = self.service.snapshot().data["state"]
            self.assertEqual(state["last_result"]["error_code"], "CANCELLED")
            self.assertFalse(state["busy"])
            saved = self.service._report_store.load(self.service._loop.run_id)
            self.assertTrue(saved.success, saved.to_dict())
            self.assertEqual(saved.data["report"]["decision"], "STOPPED")
            self.assertIsNone(saved.data["report"]["in_flight"])
        finally:
            self.service._worker.join(timeout=6)

    def test_cancel_before_worker_starts_cannot_be_cleared_by_start(self):
        start_thread = threading.Thread.start
        def cancel_then_start(thread):
            self.service.cancel()
            start_thread(thread)
        with patch("zhidiao_agent.web_ui.threading.Thread.start", cancel_then_start):
            self.service.start("PA1 完整周期 1000 ms，误差 50 ms", share_context=True)
        state = self.wait()
        self.assertEqual(state["last_result"]["error_code"], "CANCELLED")
        self.assertEqual(state["phase"], "STOPPED")
        self.factory.assert_not_called()

    def test_closed_service_rejects_new_work_and_close_is_idempotent(self):
        self.service.close()
        self.service.close()
        result = self.service.start("PA1 完整周期 1000 ms，误差 50 ms", share_context=True)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "BACKEND_UNAVAILABLE")
        self.factory.assert_not_called()

    def test_close_preserves_completed_pass_evidence(self):
        report = {"decision": "PASS", "attempts": 2, "cycles": [{"period_ms": 1001}]}
        self.service._set(phase="PASS", report=report)
        self.service.close()
        state = self.service.snapshot().data["state"]
        self.assertEqual(state["phase"], "PASS")
        self.assertEqual(state["report"], report)

    def test_close_reports_failure_to_persist_final_state(self):
        self.service._loop = self.loop
        self.service._set(phase="AWAITING_EXECUTION_APPROVAL")
        self.loop.cancel.return_value = OperationResult(
            False, "BACKEND_UNAVAILABLE", "Cannot save final report.", "run_report")
        result = self.service.close()
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "BACKEND_UNAVAILABLE")
        self.assertEqual(self.service.snapshot().data["state"]["last_result"]["error_code"],
                         "BACKEND_UNAVAILABLE")

    def test_worker_cleanup_failure_preserves_hardware_evidence_and_is_reported_on_close(self):
        self.service._loop = self.loop
        report = {"decision": "STOPPED", "hardware_state_uncertain": True,
                  "cycles": [{"execution": {"reason": "FLASH_NOT_VERIFIED"}}]}
        self.loop.report.return_value = report
        self.loop.cancel.return_value = OperationResult(
            False, "BACKEND_UNAVAILABLE", "Cannot save final report.", "run_report")
        self.service._cancel.set()
        self.service._schedule(lambda: {"remaining": self.service._check()})
        self.wait()
        result = self.service.close()
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "BACKEND_UNAVAILABLE")
        self.assertEqual(self.service.snapshot().data["state"]["report"], report)

    def test_new_task_after_cancellation_gets_a_fresh_budget(self):
        self.service._started = time.monotonic() - 1000
        self.service._cancel.set()
        self.service._set(phase="STOPPED")
        state = self.start()
        self.assertFalse(state["cancel_requested"])
        self.assertEqual(state["phase"], "AWAITING_GOAL_APPROVAL")


class ServerShutdownTests(unittest.TestCase):
    def test_server_socket_is_closed_when_service_cleanup_fails(self):
        service, server = Mock(), Mock()
        service.close.return_value = OperationResult(
            False, "BACKEND_UNAVAILABLE", "Cannot save final report.", "web_ui")
        server.server_address = ("127.0.0.1", 8765)
        server.serve_forever.side_effect = KeyboardInterrupt()
        with patch("zhidiao_agent.web_ui.create_server", return_value=server), patch("builtins.print"):
            result = run_server(service)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "BACKEND_UNAVAILABLE")
        service.close.assert_called_once()
        server.server_close.assert_called_once()


class WebHTTPTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.service.snapshot.return_value = success({"state": {"phase": "IDLE", "report": {"decision": "PASS"}}})
        self.service.start.return_value = success({"accepted": True})
        self.service.review.return_value = success({"accepted": True})
        self.service.clarify.return_value = success({"accepted": True})
        self.service.cancel.return_value = success({"accepted": True})
        self.service.list_runs.return_value = success({"runs": ["run_" + "a" * 32]})
        self.service.stored_report.return_value = success({"report": {"decision": "PASS"}})
        self.server = create_server(self.service, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.host = "127.0.0.1:" + str(self.port)
        self.addCleanup(self.stop)
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.csrf = re.search(r"const csrf='([^']+)'", body.decode()).group(1)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, data=None, *, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            supplied = {"Host": self.host}
            if data is not None:
                supplied.update({"Content-Type": "application/json", "Origin": "http://" + self.host,
                                 "X-CSRF-Token": self.csrf})
                body = json.dumps(data)
            else:
                body = None
            supplied.update(headers or {})
            connection.request(method, path, body=body, headers=supplied)
            result = connection.getresponse()
            return result.status, dict(result.getheaders()), result.read()
        finally:
            connection.close()

    def test_loopback_binding_csp_and_literal_dom_rendering(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, headers, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn(".textContent=", HTML)
        self.assertNotIn("innerHTML", HTML)
        self.assertNotIn("https://", HTML)

    @unittest.skipUnless(shutil.which("node"), "JavaScript runtime is unavailable")
    def test_browser_renderer_exposes_bidi_and_terminal_controls_without_changing_payload(self):
        begin = HTML.index("function visible(value)")
        end = HTML.index("\nconst el=", begin)
        original = "main.c\u202e // approve\x1b[2J\n\tint value;"
        script = HTML[begin:end] + "\nconst raw=" + json.dumps(original) + ";process.stdout.write(JSON.stringify({raw,shown:visible(raw)}));"
        # Reproduce Windows installations whose default text encoding is GBK.
        with patch("subprocess._text_encoding", return_value="gbk"):
            process = subprocess.run([shutil.which("node"), "-e", script], capture_output=True,
                                     text=True, encoding="utf-8", timeout=5, check=True)
        rendered = json.loads(process.stdout)
        self.assertEqual(rendered["raw"], original)
        self.assertIn("\\u202e", rendered["shown"])
        self.assertIn("\\u001b", rendered["shown"])
        self.assertNotIn("\u202e", rendered["shown"])
        self.assertNotIn("\x1b", rendered["shown"])
        self.assertIn("\n\tint value;", rendered["shown"])

    def test_exact_review_request_reaches_trusted_service_only_with_csrf_and_origin(self):
        data = {"proposal_id": "p", "fingerprint": "f", "approved": True}
        self.assertEqual(self.request("POST", "/api/review", data)[0], 202)
        self.service.review.assert_called_once_with("p", "f", approved=True)
        for headers in ({"X-CSRF-Token": "bad"}, {"Origin": "https://evil.example"},
                        {"Host": "evil.example:" + str(self.port)}, {"Origin": ""}, {"X-CSRF-Token": "é"}):
            self.assertEqual(self.request("POST", "/api/review", data, headers=headers)[0], 403)
        self.assertEqual(self.service.review.call_count, 1)

    def test_unknown_fields_paths_and_form_requests_cannot_start_tools(self):
        self.assertEqual(self.request("POST", "/api/start", {"task": "task", "share_context": True, "project": "/other"})[0], 400)
        self.assertEqual(self.request("POST", "/api/start", {"task": "task", "share_context": True}, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/api/execute", {})[0], 400)
        self.assertEqual(self.request("POST", "/api/start", {"task": "bad\ud800", "share_context": True})[0], 400)
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "evil.example"})[0], 403)
        self.service.start.assert_not_called()

    def test_report_download_is_read_only_and_does_not_replay(self):
        status, headers, body = self.request("GET", "/api/report")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(json.loads(body), {"decision": "PASS"})
        self.service.review.assert_not_called()
        self.service.start.assert_not_called()

    def test_historical_reports_are_read_only_and_paths_are_not_browser_configurable(self):
        run_id = "run_" + "a" * 32
        self.assertEqual(self.request("GET", "/api/runs")[0], 200)
        status, headers, body = self.request("GET", "/api/report/" + run_id)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"decision": "PASS"})
        self.service.stored_report.assert_called_once_with(run_id)
        self.service.review.assert_not_called()
        self.service.resume.assert_not_called()
