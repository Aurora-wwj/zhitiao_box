"""Regression of deployment goal limits, task-entry audit and model metadata."""

import contextlib
import io
import json
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from test_model_mock_ui import FakeResponsesTransport
import test_v05_workflow as workflow_fixture
from zhidiao_agent.config import NiceCodeConfig
from zhidiao_agent.demo_ui import MockHardwareWebUIService
from zhidiao_agent.deployment import DeploymentConfig, PLObserverConfig
from zhidiao_agent.errors import AgentError
from zhidiao_agent.models import OperationResult
from zhidiao_agent.nicecode import HttpResponse, NiceCodeClient, OpenAIChatAdapter, OpenAIResponsesAdapter
from zhidiao_agent.provenance import describe_model, validate_model_info
from zhidiao_agent.reports import RunStore
from zhidiao_agent.tools.pl_observer import PLPeriodReader
from zhidiao_agent.tools.real_backend import RealBackend
from zhidiao_agent.web_ui import WebUIService
from zhidiao_agent.workflow_cli import run_agent_workflow


class NativeCapabilityTests(unittest.TestCase):
    def reader(self, **changes):
        self.runner = Mock()
        config = DeploymentConfig(allowed_roots=(str(Path.cwd()),), observer=PLObserverConfig(**changes))
        return PLPeriodReader(config, runner=self.runner)

    def check(self, reader, target, tolerance=0, budget=15):
        return reader.validate_goal({'expected_period_ms': target, 'tolerance_ms': tolerance}, budget)

    def test_default_profile_accepts_one_second_and_rejects_sixty_seconds_without_io(self):
        reader = self.reader()
        limit = self.check(reader, 1000, 50)['max_period_ms']
        self.assertAlmostEqual(limit, (15 - .05) / 3 * 1000)
        with self.assertRaises(AgentError) as error:
            self.check(reader, 60000, 50)
        self.assertEqual(error.exception.code.value, 'INVALID_ARGUMENT')
        self.runner.run.assert_not_called()

    def test_entire_tolerance_band_must_fit_the_observation_window(self):
        reader = self.reader()
        self.check(reader, 4900, 50)
        with self.assertRaises(AgentError):
            self.check(reader, 4900, 100)

    def test_counter_width_is_checked_even_when_the_window_is_long(self):
        reader = self.reader(pl_clock_hz=1_000_000_000, timeout_s=120)
        self.check(reader, 4000, 10, 120)
        with self.assertRaises(AgentError):
            self.check(reader, 5000, 10, 120)

    def test_reduced_runtime_budget_and_higher_freshness_requirement_are_enforced(self):
        with self.assertRaises(AgentError):
            self.check(self.reader(), 1000, 50, 2)
        with self.assertRaises(AgentError):
            self.check(self.reader(min_new_edges=10), 1500, 10)
        self.check(self.reader(timeout_s=.3), 50, 10, .3)


class ModelProvenanceTests(unittest.TestCase):
    def test_native_protocols_only_export_allowlisted_request_metadata(self):
        config = NiceCodeConfig('https://api.nicecode.ai/v1', 'audit-model', 'sk-test-placeholder')
        for adapter, protocol in ((OpenAIResponsesAdapter(), 'openai-responses'),
                                  (OpenAIChatAdapter(), 'openai-chat')):
            info = describe_model(NiceCodeClient(config, adapter=adapter))
            self.assertEqual(info, {'source': 'nicecode_api', 'requested_model': 'audit-model', 'protocol': protocol})
            self.assertNotIn(config.api_key, json.dumps(info))
        self.assertEqual(describe_model()['source'], 'uninitialized')
        self.assertEqual(describe_model(Mock())['source'], 'custom')

    def test_metadata_cannot_include_keys_or_arbitrary_objects(self):
        good = {'source': 'custom', 'requested_model': 'unreported', 'protocol': 'custom'}
        for bad in ({**good, 'api_key': 'private'}, {**good, 'source': []},
                    {**good, 'requested_model': Mock()}):
            with self.subTest(bad_type=type(bad['source']).__name__), self.assertRaises(AgentError):
                validate_model_info(bad)


class RealFrontendAuditTests(unittest.TestCase):
    def setUp(self):
        self.case = workflow_fixture.FourToolSessionTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.transport = FakeResponsesTransport(target=1000)
        self.model = NiceCodeConfig('https://api.nicecode.ai/v1', 'audit-model', 'sk-test-placeholder', timeout_s=120)
        self.factory = Mock(side_effect=lambda: NiceCodeClient(self.model,
            adapter=OpenAIResponsesAdapter(), transport=self.transport))
        self.reports = self.case.case.root / 'audit-reports'

    def service(self, strict=False):
        with patch('zhidiao_agent.web_ui.DeploymentConfig.load', return_value=self.case.config), \
                patch('zhidiao_agent.web_ui.RealBackend', return_value=self.case.backend):
            service = WebUIService('local.json', str(self.case.case.project), ('main.c',), self.factory,
                strict_approval=strict, report_dir=str(self.reports), timeout_s=600,
                model_info=describe_model(self.factory.side_effect()))
        self.factory.reset_mock()
        self.addCleanup(service.close)
        self.assertTrue(service._preflight.success, service._preflight.to_dict())
        return service

    def wait(self, service):
        service._worker.join(3)
        self.assertFalse(service._worker.is_alive())
        state = service.snapshot()
        self.assertTrue(state.success, state.to_dict())
        return state.data['state']

    def start(self, service, task='PA1 完整周期 1000 ms，误差 10 ms。'):
        self.assertTrue(service.start(task, share_context=True).success)
        return self.wait(service)

    def review(self, service, state, approved=True):
        p = state['pending']
        self.assertTrue(service.review(p['proposal_id'], p['fingerprint'], approved=approved).success)
        return self.wait(service)

    def test_unsupported_real_goal_is_archived_and_never_reaches_approval_or_build(self):
        self.transport.target = 60000
        service = self.service()
        state = self.start(service, 'PA1 完整周期 60000 ms，误差 10 ms。')
        self.assertEqual(state['last_result']['error_code'], 'INVALID_ARGUMENT')
        self.assertEqual(state['phase'], 'STOPPED')
        self.assertIsNone(state['pending'])
        self.assertEqual(state['report']['metadata']['goal']['expected_period_ms'], 60000)
        saved = service.stored_report(state['report']['run_id'])
        self.assertTrue(saved.success)
        self.assertEqual(saved.data['report']['reason'], 'INVALID_ARGUMENT')
        self.case.runner.run.assert_not_called()

    def test_cycle_api_also_rejects_unsupported_goal_before_creating_a_build_proposal(self):
        result = self.case.controller.preview_cycle(str(self.case.case.project),
            params={'expected_period_ms': 60000, 'tolerance_ms': 10}, include_uart=True)
        self.assertEqual(result.error_code, 'INVALID_ARGUMENT')
        self.case.runner.run.assert_not_called()
        self.assertIsNone(self.case.controller._cycle)

    def test_runtime_budget_exhaustion_is_a_timeout_instead_of_a_new_invalid_goal(self):
        self.case.backend.execution_deadline = time.monotonic() + 5
        result = self.case.backend.run_hardware_test('gpio_period',
            {'expected_period_ms': 1000, 'tolerance_ms': 50})
        self.assertEqual(result.error_code, 'TIMEOUT')
        self.case.runner.run.assert_not_called()

    def test_mock_hardware_keeps_its_own_nonphysical_goal_range(self):
        self.transport.target = 60000
        service = MockHardwareWebUIService(self.factory, model_name=self.model.model, report_dir=str(self.reports))
        self.addCleanup(service.close)
        state = self.start(service, 'PA1 完整周期 60000 ms，误差 10 ms。')
        self.assertEqual(state['phase'], 'AWAITING_GOAL_APPROVAL')
        self.assertEqual(state['scope']['evidence_source'], 'mock')
        self.case.runner.run.assert_not_called()

    def test_preflight_does_not_assume_a_one_second_goal_for_a_short_window_profile(self):
        self.case.config = replace(self.case.config, observer=replace(self.case.config.observer, timeout_s=.3))
        self.case.backend = RealBackend(self.case.config, runner=self.case.runner)
        self.transport.target = 50
        service = self.service()
        state = self.start(service, 'PA1 完整周期 50 ms，误差 10 ms。')
        self.assertEqual(state['phase'], 'AWAITING_GOAL_APPROVAL')
        self.case.runner.run.assert_not_called()

    def test_goal_timeout_and_http_error_are_durable_with_model_task_and_error(self):
        service = self.service()
        for response, code in ((TimeoutError(), 'TIMEOUT'), (HttpResponse(401, b''), 'SERVICE_ERROR')):
            with self.subTest(code=code), patch.object(self.transport, 'send',
                    side_effect=response if isinstance(response, Exception) else None, return_value=response):
                state = self.start(service)
                report = state['report']
                self.assertEqual(state['last_result']['error_code'], code)
                self.assertEqual(report['reason'], code)
                self.assertEqual(report['model_info']['requested_model'], 'audit-model')
                self.assertEqual(report['metadata']['task'], 'PA1 完整周期 1000 ms，误差 10 ms。')
                self.assertEqual(report['report_stage'], 'task_entry')
                self.assertIsNone(report['in_flight'])
                if code == 'SERVICE_ERROR':
                    self.assertEqual(report['task_entry']['last_error']['status_code'], 401)
                saved = service.stored_report(report['run_id'])
                self.assertTrue(saved.success)
                self.assertNotIn(self.model.api_key, json.dumps(saved.data))
        self.assertEqual(len(service.list_runs().data['runs']), 2)
        self.case.runner.run.assert_not_called()

    def test_invalid_goal_response_is_archived_without_starting_hardware(self):
        service = self.service()
        self.transport.reply = lambda request: {'status': 'ready', 'params': 'not a goal'}
        state = self.start(service)
        self.assertEqual(state['last_result']['error_code'], 'INVALID_RESPONSE')
        report = service.stored_report(state['report']['run_id']).data['report']
        self.assertEqual(report['task_entry']['last_error']['error_code'], 'INVALID_RESPONSE')
        self.assertEqual(report['model_info']['requested_model'], 'audit-model')
        self.case.runner.run.assert_not_called()

    def test_one_id_links_inflight_goal_approval_and_complete_real_mode_report(self):
        entered, release = threading.Event(), threading.Event()
        original = self.transport.send
        def wait_for_release(*args):
            entered.set()
            release.wait(3)
            return original(*args)
        service = self.service()
        with patch.object(self.transport, 'send', side_effect=wait_for_release):
            service.start('PA1 完整周期 1000 ms，误差 10 ms。', share_context=True)
            try:
                self.assertTrue(entered.wait(2))
                state = service.snapshot().data['state']
                run_id = state['report']['run_id']
                saved = service.stored_report(run_id).data['report']
                self.assertEqual(saved['in_flight'], 'goal_interpretation')
                self.assertEqual(saved['model_info']['source'], 'nicecode_api')
                self.case.runner.run.assert_not_called()
            finally:
                release.set()
                state = self.wait(service)
        state = self.review(service, state)
        self.assertEqual(state['phase'], 'AWAITING_APPROVAL')
        state = self.review(service, state)
        self.assertEqual(state['phase'], 'PASS', state)
        self.assertEqual(state['report']['run_id'], run_id)
        self.assertEqual(state['report']['model_info']['requested_model'], 'audit-model')
        self.assertEqual(state['report']['report_stage'], 'execution')
        self.assertTrue(state['report']['task_entry']['reviews'][0]['approved'])
        self.assertEqual(service.list_runs().data['runs'], [run_id])

    def test_strict_goal_rejection_has_a_persistent_task_entry_without_build(self):
        service = self.service(strict=True)
        state = self.review(service, self.start(service), False)
        report = service.stored_report(state['report']['run_id']).data['report']
        self.assertEqual(report['reason'], 'APPROVAL_REJECTED')
        self.assertFalse(report['task_entry']['reviews'][0]['approved'])
        self.case.runner.run.assert_not_called()

    def test_audit_save_failure_stops_before_constructing_the_model(self):
        service = self.service()
        with patch.object(service._report_store, 'save', return_value=OperationResult(
                False, 'BACKEND_UNAVAILABLE', 'unit test disk failure', 'run_report')):
            state = self.start(service)
        self.assertEqual(state['last_result']['error_code'], 'BACKEND_UNAVAILABLE')
        self.factory.assert_not_called()
        self.case.runner.run.assert_not_called()

    def test_task_entry_cannot_be_resumed_and_rejection_does_not_rewrite_its_history(self):
        service = self.service()
        with patch.object(self.transport, 'send', side_effect=TimeoutError()):
            state = self.start(service)
        path = Path(state['report']['report_path'])
        before = path.read_bytes()
        self.factory.reset_mock()
        service.resume(state['report']['run_id'], share_context=True)
        state = self.wait(service)
        self.assertEqual(state['last_result']['error_code'], 'APPROVAL_REQUIRED')
        self.assertEqual(path.read_bytes(), before)
        self.factory.assert_not_called()

    def cli(self, approved=True):
        with patch('zhidiao_agent.workflow_cli.DeploymentConfig.load', return_value=self.case.config), \
                patch('zhidiao_agent.workflow_cli.RealBackend', return_value=self.case.backend), \
                patch('zhidiao_agent.workflow_cli.human_review', return_value=OperationResult(
                    True, None, 'unit test human approval', 'mock', data={'approved': approved})), \
                contextlib.redirect_stdout(io.StringIO()):
            return run_agent_workflow('PA1 完整周期 1000 ms，误差 10 ms。', config_path='local.json',
                project_path=str(self.case.case.project), source_files=('main.c',), client_factory=self.factory,
                report_dir=str(self.reports), strict_approval=False)

    def test_cli_goal_error_has_a_persistent_task_report_and_native_model_info(self):
        with patch.object(self.transport, 'send', side_effect=TimeoutError()):
            result = self.cli()
        self.assertEqual(result.error_code, 'TIMEOUT')
        report = result.data['report']
        self.assertEqual(report['model_info']['requested_model'], 'audit-model')
        self.assertEqual(report['reason'], 'TIMEOUT')
        self.assertTrue(report['task_entry']['context_sharing_approved'])
        self.assertEqual(json.loads(Path(report['report_path']).read_text(encoding='utf-8'))['run_id'], report['run_id'])
        self.case.runner.run.assert_not_called()

    def test_declined_cli_context_has_a_durable_rejection_and_no_model_request(self):
        result = self.cli(approved=False)
        self.assertEqual(result.error_code, 'APPROVAL_REJECTED')
        report = result.data['report']
        self.assertFalse(report['task_entry']['context_sharing_approved'])
        self.assertFalse(report['task_entry']['reviews'][0]['approved'])
        self.assertEqual(report['model_info']['source'], 'uninitialized')
        self.assertTrue(Path(report['report_path']).is_file())
        self.factory.assert_not_called()
        self.case.runner.run.assert_not_called()

    def test_cli_real_mode_reports_have_the_same_model_info_as_ui_mode(self):
        result = self.cli()
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data['decision'], 'PASS')
        self.assertEqual(result.data['model_info'], describe_model(self.factory.side_effect()))
        self.assertEqual(result.data['task_entry']['reviews'][0]['action'], 'share_selected_context')
        self.assertEqual(len(list(self.reports.glob('run_*.json'))), 1)

    def test_cli_archive_failure_preserves_completed_tool_evidence_in_returned_report(self):
        original = RunStore.save
        def fail_after_cycle(store, report):
            if report.get('cycles'):
                return OperationResult(False, 'BACKEND_UNAVAILABLE', 'unit test disk failure', 'run_report')
            return original(store, report)
        with patch.object(RunStore, 'save', fail_after_cycle):
            result = self.cli()
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, 'BACKEND_UNAVAILABLE')
        self.assertEqual(result.data['report']['evidence_source'], 'real')
        self.assertEqual(result.data['report']['attempts'], 1)
        self.assertEqual(len(result.data['report']['cycles']), 1)
        self.assertTrue(result.data['report']['cycles'][0]['execution']['audit'][1]['result']['verified'])
