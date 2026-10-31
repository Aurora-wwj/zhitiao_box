"""Four native tools and semantic scope, using only fake PC/SSH processes."""

import json
import contextlib
import io
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import test_real_workflow as fixture
from test_pl_uart import envelope
from zhidiao_agent.agent import Agent
from zhidiao_agent.controller import ReviewedController
from zhidiao_agent.deployment import PLObserverConfig, UARTObserverConfig
from zhidiao_agent.models import OperationResult
from zhidiao_agent.orchestrator import Orchestrator
from zhidiao_agent.session import SessionScope
from zhidiao_agent.tools.commands import CommandResult
from zhidiao_agent.tools.real_backend import RealBackend
from zhidiao_agent.demo_ui import DemoUIClient
from zhidiao_agent.workflow_cli import run_agent_workflow


class FourToolSessionTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ReviewedRealWorkflowTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.config = replace(self.case.config, observer=PLObserverConfig(), uart_observer=UARTObserverConfig())
        self.uart_output = envelope()
        self.uart_calls = 0
        def process(argv, timeout):
            if 'ZHIDIAO_UART_V1' in argv[-1]:
                self.uart_calls += 1
                return CommandResult(0, self.uart_output)
            if 'ZHIDIAO_PL_V1' in argv[-1]:
                ticks = self.case.deployed_period * 100000
                return CommandResult(0, f'ZHIDIAO_PL_V1 100 102 102 1 {ticks} {ticks // 2}')
            return self.case.fake_process(argv, timeout)
        self.runner = Mock(run=Mock(side_effect=process))
        self.backend = RealBackend(self.config, runner=self.runner)
        self.controller = ReviewedController(self.backend, allowed_roots=self.config.allowed_roots)
        self.loop = Orchestrator(self.controller, Agent(self.case.client), self.case.editor,
            task='PA1 full period 1000 ms +/- 50 ms', project_path=str(self.case.project),
            params=self.case.params, include_uart=True)
        self.scope = SessionScope(self.loop)

    def accept_scope(self):
        preview = self.scope.preview()
        self.assertTrue(preview.success, preview.to_dict())
        p = preview.data
        result = self.scope.review_scope(p['proposal_id'], p['fingerprint'], approved=True)
        self.assertTrue(result.success, result.to_dict())
        self.runner.run.assert_not_called()
        return p

    def first_failure(self):
        self.accept_scope()
        self.assertEqual(self.loop.advance().data['decision'], 'AWAITING_EXECUTION_APPROVAL')
        self.assertTrue(self.scope.approve_cycle().success)
        result = self.loop.advance()
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data['decision'], 'AWAITING_APPROVAL')
        return result.data['pending_edit']

    def test_native_four_tool_fail_edit_pass_with_scope_and_diff_review_only(self):
        pending = self.first_failure()
        self.assertEqual(self.uart_calls, 1)
        self.assertIn('= 800;', self.case.source.read_text())
        self.assertEqual(self.loop.advance().data['decision'], 'AWAITING_APPROVAL')
        self.assertEqual(self.uart_calls, 1)
        self.assertTrue(self.scope.review_edit(pending['proposal_id'], pending['fingerprint'], approved=True).success)
        self.assertIn('= 1001;', self.case.source.read_text())
        self.assertEqual(self.loop.advance().data['decision'], 'AWAITING_EXECUTION_APPROVAL')
        self.assertTrue(self.scope.approve_cycle().success)
        final = self.loop.advance()
        self.assertTrue(final.success, final.to_dict())
        self.assertEqual(final.data['decision'], 'PASS')
        self.assertEqual(final.data['verification_scope'], 'gpio_period_and_uart_capture')
        self.assertEqual(self.uart_calls, 2)
        expected = ['build_firmware', 'flash_firmware', 'read_target_log', 'run_hardware_test']
        for cycle in final.data['cycles']:
            self.assertEqual([row['tool_name'] for row in cycle['execution']['audit']], expected)
            self.assertTrue(cycle['execution']['uart_observed'])
            uart = cycle['execution']['audit'][2]['result']
            self.assertEqual(uart['uart_tx_gpio'], 'PA2')
            self.assertNotIn('observed_gpio', uart)
        events = final.data['events']
        kinds = [row['kind'] for row in events]
        for value in ('TASK_ACCEPTED', 'BUILDING', 'FLASHING', 'OBSERVING', 'ANALYZING', 'APPLYING_EDIT', 'PASS'):
            self.assertIn(value, kinds)
        self.assertEqual([row['sequence'] for row in events], sorted(row['sequence'] for row in events))
        self.assertEqual(final.data['session_approval']['mode'], 'semantic')
        self.loop.advance()
        self.assertEqual(self.uart_calls, 2)
        self.assertFalse(self.scope.approve_cycle().success)

    def test_missing_or_rejected_session_never_executes_tools(self):
        self.assertFalse(self.scope.approve_cycle().success)
        preview = self.scope.preview().data
        result = self.scope.review_scope(preview['proposal_id'], preview['fingerprint'], approved=False)
        self.assertFalse(result.success)
        self.assertFalse(self.scope.approve_cycle().success)
        self.runner.run.assert_not_called()

    def test_scope_approval_is_single_use(self):
        preview = self.accept_scope()
        self.assertFalse(self.scope.review_scope(preview['proposal_id'], preview['fingerprint'], approved=True).success)

    def test_changed_capture_duration_cannot_expand_a_session_cycle(self):
        self.accept_scope()
        self.loop.advance()
        self.loop.pending_execution['params']['binding']['duration_s'] = 10
        self.assertEqual(self.scope.approve_cycle().error_code, 'APPROVAL_REQUIRED')
        self.runner.run.assert_not_called()

    def test_report_retains_exact_scope_diff_and_cycle_review_evidence(self):
        pending = self.first_failure()
        self.scope.review_edit(pending['proposal_id'], pending['fingerprint'], approved=True)
        records = self.loop.report()['reviews']
        self.assertEqual([row['kind'] for row in records], ['session', 'cycle', 'source_diff'])
        self.assertIn('-const unsigned int gpio_period_ms = 800;', records[-1]['params']['diff'])
        self.assertEqual(records[-1]['fingerprint'], pending['fingerprint'])
        self.assertTrue(records[-1]['approved'])

    def test_external_selected_source_change_invalidates_scope_before_tools(self):
        self.accept_scope()
        self.case.source.write_text('const int gpio_period_ms = 777;\n')
        self.loop.advance()
        self.assertEqual(self.scope.approve_cycle().error_code, 'APPROVAL_REQUIRED')
        self.runner.run.assert_not_called()

    def test_unselected_source_change_blocks_diff_before_writing(self):
        preview = self.first_failure()
        (self.case.project / 'other.h').write_text('#define OTHER 1\n')
        result = self.scope.review_edit(preview['proposal_id'], preview['fingerprint'], approved=True)
        self.assertEqual(result.error_code, 'APPROVAL_REQUIRED')
        self.assertIn('= 800;', self.case.source.read_text())

    def test_rejected_diff_stops_without_rebuild_or_source_change(self):
        preview = self.first_failure()
        result = self.scope.review_edit(preview['proposal_id'], preview['fingerprint'], approved=False)
        self.assertFalse(result.success)
        self.assertIn('= 800;', self.case.source.read_text())
        self.assertEqual(self.case.build_number, 1)
        self.assertFalse(self.scope.approve_cycle().success)

    def test_changed_target_observer_limits_or_provider_invalidate_session(self):
        for change in ('target', 'gpio', 'uart', 'limits', 'provider'):
            with self.subTest(change=change):
                # Fresh policy isolates each attempted scope mutation.
                policy = SessionScope(self.loop)
                p = policy.preview().data
                self.assertTrue(policy.review_scope(p['proposal_id'], p['fingerprint'], approved=True).success)
                config, limit, provider = self.backend.config, self.controller.max_attempts, self.backend.observations.uart_reader
                if change == 'target': self.backend.config = replace(config, host='192.168.10.3')
                elif change == 'gpio': self.backend.config = replace(config, observer=replace(config.observer, observed_gpio='PB3'))
                elif change == 'uart': self.backend.config = replace(config, uart_observer=replace(config.uart_observer, stm32_tx_gpio='PA3'))
                elif change == 'limits': self.controller.max_attempts = 2
                else: self.backend.observations.uart_reader = Mock()
                self.assertEqual(policy.approve_cycle().error_code, 'APPROVAL_REQUIRED')
                self.backend.config, self.controller.max_attempts = config, limit
                self.backend.observations.uart_reader = provider
        self.runner.run.assert_not_called()

    def test_empty_uart_does_not_block_period_pass(self):
        self.uart_output = envelope(b'')
        self.case.source.write_text('const unsigned int gpio_period_ms = 1000;\n')
        self.accept_scope()
        self.loop.advance()
        self.scope.approve_cycle()
        result = self.loop.advance()
        self.assertEqual(result.data['decision'], 'PASS')
        self.assertEqual(result.data['cycles'][0]['execution']['audit'][2]['result']['logs'], [])

    def test_uart_overflow_truncation_and_hardware_errors_stop_before_ai_edit(self):
        for kwargs in ({'overflow': 1}, {'limited': 1}, {'frame': 1}, {'parity': 1}):
            with self.subTest(kwargs=kwargs):
                # Each loop has independent one-time approvals and attempts.
                self.uart_output = envelope(**kwargs)
                self.backend._begin_observation_cycle()
                controller = ReviewedController(self.backend, allowed_roots=self.config.allowed_roots)
                loop = Orchestrator(controller, Agent(self.case.client), self.case.editor,
                    task='PA1 1000 ms +/- 50 ms', project_path=str(self.case.project), params=self.case.params)
                policy = SessionScope(loop)
                p = policy.preview().data
                policy.review_scope(p['proposal_id'], p['fingerprint'], approved=True)
                loop.advance()
                policy.approve_cycle()
                result = loop.advance()
                self.assertEqual(result.data['reason'], 'LOG_INCOMPLETE')
                self.assertEqual(result.data['decision'], 'FAIL')
        self.case.client.generate.assert_not_called()

    def test_model_context_contains_evidence_without_register_commands_or_ssh_keys(self):
        self.first_failure()
        request = json.loads(self.case.client.generate.call_args.args[0][-1]['content'])
        evidence = json.dumps(request['context'])
        self.assertNotIn('0x43C50000', evidence)
        self.assertNotIn('BatchMode', evidence)
        self.assertNotIn('known_hosts', evidence)
        self.assertIn('real_pl_uart', evidence)

    def test_terminal_semantic_workflow_needs_only_context_scope_and_diff_reviews(self):
        with patch('zhidiao_agent.workflow_cli.DeploymentConfig.load',return_value=self.config), \
                patch('zhidiao_agent.workflow_cli.RealBackend',return_value=self.backend), \
                patch('sys.stdin.isatty',return_value=True), \
                patch('builtins.input',side_effect=['y','y','y']) as approvals, \
                contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            result=run_agent_workflow('PA1 full period 1000 ms tolerance 50 ms',
                config_path='local.json',project_path=str(self.case.project),source_files=('main.c',),
                client_factory=DemoUIClient,strict_approval=False,
                report_dir=str(self.case.root/'reports'))
        self.assertTrue(result.success,result.to_dict())
        self.assertEqual(result.data['decision'],'PASS')
        self.assertEqual(approvals.call_count,3)
        self.assertEqual(self.uart_calls,2)
