import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import test_v05_workflow as fixture
from zhidiao_agent.demo import ScriptedDemoClient
from zhidiao_agent.demo_ui import DemoUIClient, DemoWebUIService
from zhidiao_agent.desktop import LaunchSettings, build_service, launch
from zhidiao_agent.events import WorkflowEvents
from zhidiao_agent.models import OperationResult
from zhidiao_agent.presentation import view_model
from zhidiao_agent.web_ui import WebUIService, HTML


class GoalAndDecisionClient(ScriptedDemoClient):
    def generate(self, messages):
        request = json.loads(messages[-1]['content'])
        if 'sources' in request:
            return super().generate(messages)
        return DemoUIClient().generate(messages)


class RealSemanticUITests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.FourToolSessionTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.enterContext(patch('zhidiao_agent.web_ui.DeploymentConfig.load', return_value=self.case.config))
        self.enterContext(patch('zhidiao_agent.web_ui.RealBackend', return_value=self.case.backend))

    def service(self, strict=False):
        service = WebUIService('local.json', str(self.case.case.project), ('main.c',), GoalAndDecisionClient,
            strict_approval=strict, report_dir=str(self.case.case.root / 'reports'))
        self.addCleanup(service.close)
        self.assertTrue(service._preflight.success, service._preflight.to_dict())
        return service

    def wait(self, service):
        service._worker.join(3)
        self.assertFalse(service._worker.is_alive())
        state = service.snapshot()
        self.assertTrue(state.success, state.to_dict())
        return state.data['state']

    def review(self, service, state, approved=True):
        p=state['pending']
        self.assertTrue(service.review(p['proposal_id'], p['fingerprint'], approved=approved).success)
        return self.wait(service)

    def start(self, service):
        service.start('把 PA1 完整周期调到 1000 ms，误差不超过 50 ms。', share_context=True)
        return self.wait(service)

    def test_semantic_ui_scope_then_diff_automatically_runs_both_four_tool_cycles(self):
        service = self.service()
        state = self.start(service)
        self.assertEqual(state['pending']['action'], 'run_session')
        self.assertEqual(self.case.case.build_number, 0)
        state = self.review(service, state)
        self.assertEqual(state['phase'], 'AWAITING_APPROVAL')
        self.assertEqual(state['view']['before']['period_ms'], 800)
        self.assertEqual(self.case.uart_calls, 1)
        state = self.review(service, state)
        self.assertEqual(state['phase'], 'PASS', state)
        self.assertEqual(state['view']['after']['period_ms'], 1001)
        self.assertEqual(state['view']['status'], 'PASS')
        self.assertEqual(self.case.uart_calls, 2)
        self.assertEqual(state['view']['verification_scope'], 'gpio_period_and_uart_capture')
        self.assertIn('MOCK:', state['view']['reason'])

    def test_strict_ui_keeps_each_cycle_review(self):
        service = self.service(True)
        state = self.review(service, self.start(service))
        self.assertEqual(state['phase'], 'AWAITING_EXECUTION_APPROVAL')
        self.assertEqual(self.case.case.build_number, 0)
        state = self.review(service, state)
        self.assertEqual(state['phase'], 'AWAITING_APPROVAL')
        state = self.review(service, state)
        self.assertEqual(state['phase'], 'AWAITING_EXECUTION_APPROVAL')
        self.assertEqual(self.case.case.build_number, 1)

    def test_rejecting_session_never_builds_or_captures_uart(self):
        service = self.service()
        state = self.review(service, self.start(service), False)
        self.assertEqual(state['phase'], 'STOPPED')
        self.assertEqual(self.case.uart_calls, 0)
        self.assertEqual(self.case.case.build_number, 0)

    def test_semantic_approval_does_not_allow_an_external_file_change(self):
        service = self.service()
        state = self.review(service, self.start(service))
        (self.case.case.project / 'other.h').write_text('#define CHANGED 1\n')
        state = self.review(service, state)
        self.assertEqual(state['phase'], 'STOPPED')
        self.assertEqual(state['last_result']['error_code'], 'APPROVAL_REQUIRED')
        self.assertIn('= 800;', self.case.case.source.read_text())

    def test_live_build_stage_is_visible_while_the_worker_is_busy(self):
        entered, release = threading.Event(), threading.Event()
        process = self.case.runner.run.side_effect
        def blocked(argv, timeout):
            if argv[0] == self.case.config.keil_executable:
                entered.set()
                release.wait(3)
            return process(argv, timeout)
        self.case.runner.run.side_effect = blocked
        service = self.service()
        state = self.start(service)
        p = state['pending']
        service.review(p['proposal_id'], p['fingerprint'], approved=True)
        try:
            self.assertTrue(entered.wait(1))
            live = service.snapshot().data['state']
            self.assertTrue(live['busy'])
            self.assertEqual(live['view']['stage_label'], '编译固件')
        finally:
            release.set()
            self.wait(service)

    def test_a_poll_cannot_show_a_measurement_from_a_later_event_snapshot(self):
        service = self.service()
        current = [{'kind': 'BUILDING', 'attempt': 1}]
        later = current + [{'kind': 'TOOL_FINISHED', 'attempt': 1,
            'tool_name': 'run_hardware_test', 'period_ms': 1001, 'passed': True}]
        with patch.object(service._events, 'snapshot', side_effect=[current, later]):
            state = service.snapshot().data['state']
        self.assertEqual(state['events'], current)
        self.assertEqual(state['view']['measurements'], [])


class UIPresentationTests(unittest.TestCase):
    def render(self, **changes):
        values = dict(phase='IDLE',scope={},report={},pending=None,events=[])
        return view_model(**{**values, **changes})

    def test_before_after_comes_from_numeric_evidence_and_not_model_claims(self):
        events=[{'kind':'TOOL_FINISHED','attempt':1,'tool_name':'run_hardware_test','period_ms':601.92511,'passed':False},
                {'kind':'TOOL_FINISHED','attempt':2,'tool_name':'run_hardware_test','period_ms':999.92936,'passed':True}]
        view=self.render(phase='PASS',events=events,goal={'params':{'expected_period_ms':1000,'tolerance_ms':50}})
        self.assertEqual(view['before']['period_ms'],601.92511)
        self.assertEqual(view['after']['period_ms'],999.92936)
        self.assertEqual(view['status'],'PASS')
        self.assertEqual(view['attempt'],2)

    def test_transport_errors_are_distinct_from_a_failed_period_goal(self):
        error=self.render(phase='FAIL',report={'reason':'LOG_COLLECTION_FAILED'})
        fail=self.render(phase='FAIL',report={'reason':'ATTEMPTS_EXHAUSTED'})
        self.assertEqual(error['status'],'ERROR')
        self.assertEqual(fail['status'],'FAIL')
        self.assertEqual(self.render(phase='STOPPED',last_result={'error_code':'CANCELLED'})['status'],'STOPPED')

    def test_visible_reason_redacts_common_credentials(self):
        view=self.render(pending={'reason':'token=private-token Bearer private-auth sk-123456789secret'})
        self.assertNotIn('private-token',view['reason'])
        self.assertNotIn('private-auth',view['reason'])
        self.assertNotIn('sk-123456789secret',view['reason'])

    def test_uart_display_never_relabels_old_logs_as_the_next_capture(self):
        def cycle(attempt, texts):
            return {'attempt':attempt,'execution':{'audit':[{'tool_name':'read_target_log',
                'result':{'success':True,'logs':[{'text':value,'timestamp_ms':10} for value in texts]}}]}}
        view=self.render(report={'cycles':[cycle(1,['OLD']),cycle(2,[])]})
        self.assertEqual(view['uart_logs'],[])
        self.assertEqual(view['uart_attempt'],2)
        self.assertTrue(view['uart_success'])

    def test_analysis_completion_is_scoped_to_the_current_attempt(self):
        events = [{'kind': 'TARGET_PARSED', 'attempt': 0},
                  {'kind': 'ANALYSIS_FINISHED', 'attempt': 1},
                  {'kind': 'BUILDING', 'attempt': 2, 'tool_name': 'build_firmware'}]
        view = self.render(phase='RUNNING', busy=True, events=events)
        self.assertEqual(view['steps'][0]['state'], 'done')
        self.assertEqual(view['steps'][1]['state'], 'active')
        self.assertEqual(view['steps'][-1]['state'], 'pending')
        events.append({'kind': 'ANALYZING', 'attempt': 2})
        self.assertEqual(self.render(busy=True, events=events)['steps'][-1]['state'], 'active')
        events.append({'kind': 'ANALYSIS_FINISHED', 'attempt': 2})
        self.assertEqual(self.render(events=events)['steps'][-1]['state'], 'done')
        events.pop()
        events[-1] = {'kind': 'PASS', 'attempt': 2}
        passed = self.render(phase='PASS', events=events)
        self.assertEqual(passed['steps'][-1]['state'], 'skipped')
        self.assertIn('本轮已达标', passed['steps'][-1]['label'])

    def test_skipped_uart_is_not_shown_as_a_completed_capture(self):
        view = self.render(scope={'include_uart': False})
        self.assertEqual(view['steps'][3]['state'], 'skipped')
        self.assertIn('显式跳过', view['steps'][3]['label'])
        self.assertIn('没有采集 UART', view['uart_text'])

    def test_live_uart_failure_replaces_old_text_before_the_report_is_saved(self):
        cycle = {'attempt': 1, 'execution': {'audit': [{'tool_name': 'read_target_log',
            'result': {'success': True, 'logs': [{'text': 'OLD LOG'}]}}]}}
        events = [{'kind': 'TOOL_FINISHED', 'attempt': 2, 'tool_name': 'read_target_log',
                   'success': False, 'error_code': 'SSH_CONNECT_FAILED'}]
        view = self.render(events=events, report={'cycles': [cycle]})
        self.assertIn('采集失败', view['uart_text'])
        self.assertIn('SSH_CONNECT_FAILED', view['uart_text'])
        self.assertNotIn('OLD LOG', view['uart_text'])
        self.assertEqual(view['steps'][3]['state'], 'failed')

    def test_saved_uart_failure_and_successful_empty_capture_have_distinct_text(self):
        cycle = {'attempt': 1, 'execution': {'audit': [{'tool_name': 'read_target_log',
            'result': {'success': False, 'error_code': 'UART_READ_FAILED', 'logs': []}}]}}
        failed = self.render(report={'cycles': [cycle]})
        self.assertIn('采集失败', failed['uart_text'])
        # New successful capture takes precedence while its report is still being assembled.
        events = [{'kind': 'TOOL_FINISHED', 'attempt': 2, 'tool_name': 'read_target_log', 'success': True}]
        self.assertIn('整理证据', self.render(events=events, report={'cycles': [cycle]})['uart_text'])
        cycle['execution']['audit'][0]['result'] = {'success': True, 'logs': []}
        empty = self.render(report={'cycles': [cycle]})
        self.assertIn('采集成功，没有收到日志', empty['uart_text'])

    def test_live_stage_is_structured_and_does_not_search_compiler_log_text(self):
        view=self.render(phase='RUNNING',busy=True,events=[{'kind':'FLASHING','attempt':1}],
                         report={'cycles':[{'execution':{'audit':[]},'model_decision':{'reason':'PASS BUILDING'}}]})
        self.assertEqual(view['stage_label'],'烧录 / 校验 / 复位')
        self.assertEqual(view['status'],'RUNNING')

    def test_page_uses_literal_text_and_keeps_raw_json_in_optional_details(self):
        self.assertNotIn('innerHTML',HTML)
        self.assertNotIn('https://',HTML)
        self.assertIn('textContent=',HTML)
        self.assertIn('BEFORE',HTML)
        self.assertIn('AFTER',HTML)
        self.assertIn('开发 / 审计详情',HTML)
        self.assertIn("p.proposal_id,fingerprint:p.fingerprint",HTML)

    def test_event_journal_is_bounded_and_drops_unserializable_measurements(self):
        events=WorkflowEvents()
        for _ in range(300):events.emit('BUILDING',period_ms=float('nan'),error_code=object())
        rows=events.snapshot()
        self.assertEqual(len(rows),256)
        self.assertEqual(rows[-1]['sequence'],300)
        self.assertNotIn('period_ms',rows[-1])
        json.dumps(rows,allow_nan=False)


class DesktopAndDemoTests(unittest.TestCase):
    def test_demo_ui_runs_offline_with_temporary_source_and_explicit_mock_label(self):
        with TemporaryDirectory() as reports:
            service=DemoWebUIService(report_dir=reports)
            try:
                with patch('zhidiao_agent.nicecode.UrllibTransport.send') as network:
                    service.start('PA1 1000 ms +/- 50 ms',share_context=True)
                    service._worker.join(3)
                    for _ in range(2):
                        state=service.snapshot().data['state'];p=state['pending']
                        service.review(p['proposal_id'],p['fingerprint'],approved=True)
                        service._worker.join(3)
                    state=service.snapshot().data['state']
                    self.assertEqual(state['phase'],'PASS')
                    self.assertEqual(state['view']['evidence_source'],'mock')
                    self.assertEqual([p['period_ms'] for p in state['view']['measurements']],[800,1001])
                    self.assertEqual([e['attempt'] for e in state['events'] if e['kind']=='BUILDING'],[1,2])
                    network.assert_not_called()
            finally:service.close()
            self.assertFalse(Path(service.project_path).exists())

    def test_launcher_keeps_key_out_of_repr_and_defers_model_calls(self):
        settings=LaunchSettings('profile.json','project',('main.c',),api_key='sk-123456789secret')
        self.assertNotIn('sk-',repr(settings))
        with patch.dict(os.environ, {'NICECODE_BASE_URL': 'https://api.nicecode.ai/v1'}), \
                patch('zhidiao_agent.desktop.WebUIService') as web, \
                patch('zhidiao_agent.nicecode.UrllibTransport.send') as network:
            build_service(settings)
            options=web.call_args.kwargs
            self.assertFalse(options['strict_approval'])
            self.assertTrue(options['include_uart'])
            self.assertNotIn('sk-',repr(web.call_args))
            network.assert_not_called()

    def test_native_launcher_cancel_returns_without_starting_a_server(self):
        with patch('zhidiao_agent.desktop._choose_settings',return_value=None),patch('zhidiao_agent.desktop.run_server') as server:
            result=launch()
        self.assertTrue(result.success)
        self.assertEqual(result.data['reason'],'LAUNCH_CANCELLED')
        server.assert_not_called()

    def test_source_checkout_launcher_help_needs_no_pythonpath_or_hardware(self):
        root=Path(__file__).resolve().parents[1]
        environment=dict(os.environ)
        environment.pop('PYTHONPATH',None)
        result=subprocess.run([sys.executable,'-B',str(root/'scripts/start_ui.py'),'--help'],
                              capture_output=True,env=environment,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(b'--demo',result.stdout)

    def test_both_cli_modes_are_available_without_constructing_hardware(self):
        from zhidiao_agent.cli import main
        result=OperationResult(True,None,'mock','mock',data={'decision':'STOPPED'})
        with patch('zhidiao_agent.desktop.launch',return_value=result) as start,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ui','--demo','--no-browser']),0)
        self.assertTrue(start.call_args.kwargs['demo'])
        self.assertFalse(start.call_args.kwargs['open_browser'])
