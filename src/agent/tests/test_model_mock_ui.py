"""Native NiceCode protocol with a fake HTTP transport and four mock tools."""

import contextlib
import io
import json
import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from zhidiao_agent.config import NiceCodeConfig
from zhidiao_agent.demo_ui import MockHardwareWebUIService
from zhidiao_agent.desktop import MockLaunchSettings, build_mock_service, launch
from zhidiao_agent.errors import AgentError
from zhidiao_agent.models import OperationResult
from zhidiao_agent.nicecode import HttpResponse, NiceCodeClient, OpenAIResponsesAdapter
from zhidiao_agent.web_ui import run_server


class FakeResponsesTransport:
    def __init__(self, target=1500):
        self.target = target
        self.requests = []
        self.reply = None

    def send(self, url, headers, body, timeout_s):
        data = json.loads(body)
        request = json.loads(data['input'][-1]['content'])
        self.requests.append({'url': url, 'body': data, 'request': request, 'timeout_s': timeout_s})
        if self.reply is not None:
            content = self.reply(request)
        elif 'sources' not in request:
            content = {'status': 'ready', 'test_id': 'gpio_period', 'observed_gpio': 'PA1',
                'params': {'expected_period_ms': self.target, 'tolerance_ms': 10},
                'summary': f'PA1 完整周期 {self.target} ms，误差不超过 10 ms。'}
        else:
            source = request['sources']['main.c']
            content = {'action': 'edit', 'reason': '根据模拟测量调整完整周期常量，再重新验证。',
                'edit': {'path': 'main.c', 'before_sha256': source['sha256'],
                    'content': re.sub(r'gpio_period_ms\s*=\s*[0-9]+;',
                                      f'gpio_period_ms = {self.target};', source['content'])}}
        return HttpResponse(200, json.dumps({'status': 'completed', 'output': [
            {'type': 'message', 'role': 'assistant', 'status': 'completed',
             'content': [{'type': 'output_text', 'text': json.dumps(content, ensure_ascii=False)}]}]
        }, ensure_ascii=False).encode('utf-8'))


class ModelMockUITests(unittest.TestCase):
    def setUp(self):
        reports = TemporaryDirectory()
        self.addCleanup(reports.cleanup)
        self.reports = reports.name
        self.transport = FakeResponsesTransport()
        self.config = NiceCodeConfig('https://api.nicecode.ai/v1', 'test-request-model',
                                      'sk-unit-test-placeholder', timeout_s=120)
        self.factory = Mock(side_effect=lambda: NiceCodeClient(self.config,
            adapter=OpenAIResponsesAdapter(), transport=self.transport))
        # This mode must not depend on a deployment or reach an external tool.
        self.enterContext(patch('zhidiao_agent.web_ui.DeploymentConfig.load',
                                side_effect=AssertionError('No deployment in simulation')))
        self.enterContext(patch('zhidiao_agent.web_ui.RealBackend',
                                side_effect=AssertionError('No real backend in simulation')))
        self.enterContext(patch('zhidiao_agent.tools.commands.subprocess.Popen',
                                side_effect=AssertionError('No subprocess in simulation')))
        self.service = MockHardwareWebUIService(self.factory, model_name=self.config.model,
                                                report_dir=self.reports)
        self.addCleanup(self.service.close)
        self.source = Path(self.service.project_path) / 'main.c'
        self.assertTrue(self.service._preflight.success, self.service._preflight.to_dict())

    def wait(self):
        self.service._worker.join(3)
        self.assertFalse(self.service._worker.is_alive())
        result = self.service.snapshot()
        self.assertTrue(result.success, result.to_dict())
        return result.data['state']

    def start(self, task='把 PA1 完整周期调到 1500 ms，误差不超过 10 ms。', consent=True):
        self.assertTrue(self.service.start(task, share_context=consent).success)
        return self.wait()

    def review(self, state, approved=True):
        proposal = state['pending']
        self.assertTrue(self.service.review(proposal['proposal_id'], proposal['fingerprint'], approved=approved).success)
        return self.wait()

    def test_native_api_goal_diff_and_two_mock_cycles_follow_a_non_demo_target(self):
        self.factory.assert_not_called()
        state = self.start()
        self.assertEqual(state['phase'], 'AWAITING_GOAL_APPROVAL')
        self.assertEqual(state['scope']['model_source'], 'nicecode_api')
        self.assertEqual(state['view']['goal']['expected_period_ms'], 1500)
        self.assertEqual(self.transport.requests[0]['request']['evidence_source'], 'mock')
        self.assertIsNone(self.service._backend.built_period)
        state = self.review(state)
        self.assertEqual(state['phase'], 'AWAITING_APPROVAL')
        self.assertEqual(state['view']['before']['period_ms'], 800)
        self.assertIn('= 800;', self.source.read_text(encoding='utf-8'))
        self.assertIn('+const unsigned int gpio_period_ms = 1500;', state['pending']['params']['diff'])
        # Polling/advancing while a diff waits must not apply it or request more API calls.
        self.service.snapshot()
        self.assertEqual(len(self.transport.requests), 2)
        state = self.review(state)
        self.assertEqual(state['phase'], 'PASS', state)
        self.assertEqual(state['view']['after']['period_ms'], 1500)
        self.assertEqual(state['report']['evidence_source'], 'mock')
        self.assertEqual(state['report']['model_info'], {'source': 'nicecode_api',
            'requested_model': 'test-request-model', 'protocol': 'openai-responses'})
        self.assertEqual(state['report']['metadata']['model_info'], state['report']['model_info'])
        for cycle in state['report']['cycles']:
            self.assertEqual([row['tool_name'] for row in cycle['execution']['audit']],
                ['build_firmware', 'flash_firmware', 'read_target_log', 'run_hardware_test'])
        for row in self.transport.requests:
            self.assertEqual(row['url'], 'https://api.nicecode.ai/v1/responses')
            self.assertEqual(row['body']['model'], 'test-request-model')
            self.assertFalse(row['body']['store'])
            self.assertLessEqual(row['timeout_s'], 120)
        saved = self.service._report_store.load(state['report']['run_id'])
        self.assertTrue(saved.success)
        self.assertEqual(saved.data['report']['model_info']['source'], 'nicecode_api')
        self.assertNotIn(self.config.api_key, json.dumps(state, ensure_ascii=False))
        self.assertNotIn(self.config.api_key, Path(state['report']['report_path']).read_text(encoding='utf-8'))

    def test_no_sharing_consent_means_no_client_or_tool_calls(self):
        state = self.start(consent=False)
        self.assertEqual(state['phase'], 'STOPPED')
        self.assertEqual(state['last_result']['error_code'], 'APPROVAL_REQUIRED')
        self.factory.assert_not_called()
        self.assertIsNone(self.service._backend.built_period)

    def test_reject_goal_never_runs_a_mock_cycle(self):
        state = self.review(self.start(), False)
        self.assertEqual(state['phase'], 'STOPPED')
        self.assertEqual(len(self.transport.requests), 1)
        self.assertIsNone(self.service._backend.built_period)

    def test_reject_diff_keeps_initial_source_and_does_not_run_second_cycle(self):
        state = self.review(self.review(self.start()), False)
        self.assertEqual(state['phase'], 'STOPPED')
        self.assertIn('= 800;', self.source.read_text(encoding='utf-8'))
        self.assertEqual(state['report']['attempts'], 1)
        self.assertEqual(self.service._backend.deployed_period, 800)

    def test_clarification_uses_api_answer_before_any_cycle(self):
        calls = 0
        def clarify(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {'status': 'clarification', 'question': '请说明完整周期和允许误差。'}
            self.assertEqual(request['clarifications'][0]['answer'], '完整周期 1500 ms，误差 10 ms。')
            self.transport.reply = None
            return {'status': 'ready', 'test_id': 'gpio_period', 'observed_gpio': 'PA1',
                'params': {'expected_period_ms': 1500, 'tolerance_ms': 10}, 'summary': 'PA1 完整周期 1500 ±10 ms。'}
        self.transport.reply = clarify
        state = self.start('调整 PA1 周期')
        self.assertEqual(state['phase'], 'NEEDS_CLARIFICATION')
        self.assertIsNone(self.service._backend.built_period)
        self.assertTrue(self.service.clarify('完整周期 1500 ms，误差 10 ms。').success)
        state = self.wait()
        self.assertEqual(state['phase'], 'AWAITING_GOAL_APPROVAL')
        self.assertEqual(len(self.transport.requests), 2)

    def test_unsupported_pin_is_rejected_without_api_calls(self):
        state = self.start('把 PB3 的完整周期调到 1500 ms，误差 10 ms。')
        self.assertEqual(state['last_result']['error_code'], 'INVALID_ARGUMENT')
        self.factory.assert_not_called()

    def test_timeout_and_service_errors_stop_before_mock_build(self):
        for response, code in ((TimeoutError(), 'TIMEOUT'), (HttpResponse(401, b''), 'SERVICE_ERROR')):
            with self.subTest(code=code), patch.object(self.transport, 'send', side_effect=response
                    if isinstance(response, Exception) else None, return_value=response):
                state = self.start()
                self.assertEqual(state['last_result']['error_code'], code)
                self.assertEqual(state['scope']['evidence_source'], 'mock')
                self.assertIsNone(self.service._backend.built_period)

    def test_model_cannot_claim_pass_or_select_another_file(self):
        for bad in ({'action': 'pass', 'reason': 'trust me'},
                    {'action': 'edit', 'reason': 'outside', 'edit': {
                        'path': '../outside.c', 'before_sha256': '0' * 64, 'content': 'bad'}}):
            with self.subTest(action=bad['action']):
                self.transport.reply = None
                state = self.start()
                self.transport.reply = lambda request: bad
                state = self.review(state)
                self.assertEqual(state['phase'], 'STOPPED')
                self.assertEqual(state['last_result']['error_code'], 'INVALID_RESPONSE')
                self.assertIn('= 800;', self.source.read_text(encoding='utf-8'))

    def test_external_source_change_invalidates_the_displayed_diff(self):
        state = self.review(self.start())
        self.source.write_text('const unsigned int gpio_period_ms = 900;\n', encoding='utf-8')
        state = self.review(state)
        self.assertEqual(state['phase'], 'STOPPED')
        self.assertEqual(state['last_result']['error_code'], 'APPROVAL_REQUIRED')
        self.assertIn('= 900;', self.source.read_text(encoding='utf-8'))
        self.assertEqual(self.service._backend.deployed_period, 800)

    def test_failed_model_repairs_stop_at_three_attempts(self):
        state = self.start()
        def inadequate(request):
            source = request['sources']['main.c']
            value = 800 + 100 * request['context']['attempt']
            return {'action': 'edit', 'reason': '模拟未达标修复。', 'edit': {'path': 'main.c',
                'before_sha256': source['sha256'], 'content': re.sub(r'gpio_period_ms\s*=\s*[0-9]+;',
                    f'gpio_period_ms = {value};', source['content'])}}
        self.transport.reply = inadequate
        for _ in range(3):
            state = self.review(state)
        self.assertEqual(state['phase'], 'FAIL')
        self.assertEqual(state['report']['attempts'], 3)
        self.assertEqual(state['report']['reason'], 'ATTEMPTS_EXHAUSTED')
        self.assertEqual(len(self.transport.requests), 3)

    def test_close_removes_temporary_source_but_keeps_saved_report(self):
        state = self.review(self.review(self.start()))
        report = Path(state['report']['report_path'])
        self.assertTrue(self.service.close().success)
        self.assertFalse(self.source.parent.exists())
        self.assertTrue(report.is_file())


class MockLauncherTests(unittest.TestCase):
    def test_network_opt_in_and_key_are_required_before_service_creation(self):
        with patch.dict(os.environ, {'NICECODE_API_KEY': ''}), \
                patch('zhidiao_agent.demo_ui.MockHardwareWebUIService') as service:
            for settings, code in ((MockLaunchSettings(api_key='unit-key'), 'APPROVAL_REQUIRED'),
                                   (MockLaunchSettings(allow_network=True), 'CONFIGURATION_ERROR')):
                with self.subTest(code=code), self.assertRaises(AgentError) as error:
                    build_mock_service(settings)
                self.assertEqual(error.exception.code.value, code)
            service.assert_not_called()

    def test_configuring_the_launcher_defers_all_network_calls_and_hides_key(self):
        settings = MockLaunchSettings(api_key='sk-unit-test-placeholder', allow_network=True)
        self.assertNotIn(settings.api_key, repr(settings))
        with patch.dict(os.environ, {'NICECODE_BASE_URL': 'https://api.nicecode.ai/v1'}), \
                patch('zhidiao_agent.nicecode.UrllibTransport.send') as network:
            service = build_mock_service(settings)
            try:
                self.assertEqual(service.snapshot().data['state']['scope']['model_source'], 'nicecode_api')
                network.assert_not_called()
            finally:
                service.close()

    def test_mock_launcher_cancel_does_not_open_server_or_hardware_dialog(self):
        with patch('zhidiao_agent.desktop._choose_mock_settings', return_value=None), \
                patch('zhidiao_agent.desktop._choose_settings') as real_dialog, \
                patch('zhidiao_agent.desktop.run_server') as server:
            result = launch(mock_hardware=True)
            self.assertTrue(result.success)
            self.assertEqual(result.data['reason'], 'LAUNCH_CANCELLED')
            real_dialog.assert_not_called()
            server.assert_not_called()

    def test_cli_selects_mock_hardware_without_changing_offline_demo(self):
        from zhidiao_agent.cli import main
        result = OperationResult(True, None, 'unit test', 'mock', data={'decision': 'STOPPED'})
        with patch('zhidiao_agent.desktop.launch', return_value=result) as launcher, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ui', '--mock-hardware', '--no-browser']), 0)
            self.assertTrue(launcher.call_args.kwargs['mock_hardware'])
            self.assertFalse(launcher.call_args.kwargs['demo'])
            self.assertEqual(main(['serve-demo', '--no-browser']), 0)
            self.assertTrue(launcher.call_args.kwargs['demo'])
            self.assertFalse(launcher.call_args.kwargs['mock_hardware'])

    def test_port_binding_failure_still_cleans_up_the_service(self):
        service = Mock()
        service.close.return_value = OperationResult(True, None, 'closed', 'mock')
        with patch('zhidiao_agent.web_ui.create_server', side_effect=OSError('port in use')), \
                patch('builtins.print'):
            result = run_server(service)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, 'NETWORK_UNREACHABLE')
        service.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
