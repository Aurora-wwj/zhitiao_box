import json
import unittest
from unittest.mock import Mock

from zhidiao_agent.goals import GoalInterpreter
from zhidiao_agent.deployment import PLObserverConfig
from zhidiao_agent.errors import AgentError
from zhidiao_agent.models import OperationResult


class GoalTests(unittest.TestCase):
    def client(self, data):
        return Mock(generate=Mock(return_value=OperationResult(
            True, None, "mock", "mock", data={"content": json.dumps(data)})))

    def goal(self):
        return {"status": "ready", "test_id": "gpio_period", "observed_gpio": "PA1", "params": {
            "expected_period_ms": 1000, "tolerance_ms": 50,
        }, "summary": "GPIO 完整周期 1000 ± 50 ms"}

    def test_natural_goal_only_extracts_parameters_no_tools(self):
        client = self.client(self.goal())
        result = GoalInterpreter(client).interpret("把 GPIO 完整周期调到 1 秒，允许误差 0.05 秒")
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["params"], self.goal()["params"])
        self.assertNotIn("passed", result.data)
        prompt = client.generate.call_args.args[0][0]["content"]
        self.assertIn("COMPLETE CYCLE", prompt)
        self.assertIn("Never invent", prompt)
        self.assertEqual(result.data["observed_gpio"], "PA1")
        payload = json.loads(client.generate.call_args.args[0][1]["content"])
        self.assertEqual(payload["observed_gpio"], "PA1")

    def test_explicit_other_pin_never_calls_model(self):
        for task in ("把 PB3 完整周期调到 1000 ms，误差 50 ms", "把PB3周期调到1000ms",
                     "GPIOB.3 完整周期 1000±50ms", "ｐｂ３周期1000±50ms", "PA16周期1000±50ms"):
            with self.subTest(task=task):
                client = self.client(self.goal())
                result = GoalInterpreter(client).interpret(task)
                self.assertEqual(result.error_code, "INVALID_ARGUMENT")
                client.generate.assert_not_called()

    def test_model_cannot_change_pin_or_describe_another_pin(self):
        for changes in ({"observed_gpio": "PB3"}, {"observed_gpio": "pa1"},
                        {"summary": "PB3完整周期1000±50ms"}):
            actual = GoalInterpreter(self.client({**self.goal(), **changes})).interpret("GPIO完整周期1000±50ms")
            self.assertEqual(actual.error_code, "INVALID_RESPONSE")
        goal = self.goal()
        del goal["observed_gpio"]
        self.assertEqual(GoalInterpreter(self.client(goal)).interpret("GPIO周期1000±50ms").error_code, "INVALID_RESPONSE")

    def test_profile_selects_actual_observed_pin_without_hardcoding_pa1(self):
        data = {**self.goal(), "observed_gpio": "PB3"}
        result = GoalInterpreter(self.client(data), observed_gpio="PB3").interpret("PB3完整周期1000±50ms")
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.data["observed_gpio"], "PB3")
        for pin in ("PA16", "PA01", "PB-3", "PA1;reboot", "pa1", None):
            with self.subTest(pin=pin), self.assertRaises(AgentError):
                PLObserverConfig(observed_gpio=pin)

    def test_clarifications_keep_original_task_and_bound_pin(self):
        client = self.client(self.goal())
        conversation = ({"question": "完整周期和容差？", "answer": "PA1完整周期1000ms，误差50ms"},)
        result = GoalInterpreter(client).interpret("把灯调慢", clarifications=conversation)
        self.assertTrue(result.success, result.to_dict())
        payload = json.loads(client.generate.call_args.args[0][1]["content"])
        self.assertEqual(payload["task"], "把灯调慢")
        self.assertEqual(payload["clarifications"], list(conversation))
        client.generate.reset_mock()
        actual = GoalInterpreter(client).interpret("把灯调慢", clarifications=(
            {"question": "哪个引脚？", "answer": "PB3"},))
        self.assertEqual(actual.error_code, "INVALID_ARGUMENT")
        client.generate.assert_not_called()

    def test_clarification_history_is_bounded_and_typed(self):
        client = self.client(self.goal())
        for rows in ([{}], ["bad"], [{"question": "q", "answer": "a"}] * 4,
                     [{"question": "q", "answer": "a" * 1001}], [{"question": "", "answer": "a"}]):
            actual = GoalInterpreter(client).interpret("任务", clarifications=rows)
            self.assertEqual(actual.error_code, "INVALID_ARGUMENT")
        client.generate.assert_not_called()

    def test_missing_or_unsupported_goal_needs_clarification(self):
        data = {"status": "clarification", "question": "目标是完整周期还是高电平时长？容差是多少？"}
        result = GoalInterpreter(self.client(data)).interpret("让灯慢点闪")
        self.assertEqual(result.data, data)

    def test_model_cannot_add_tools_approval_limits_or_verdict(self):
        for key, value in (("passed", True), ("max_attempts", 99), ("command", "ssh"), ("approved", True)):
            goal = self.goal()
            goal[key] = value
            self.assertEqual(GoalInterpreter(self.client(goal)).interpret("任务").error_code, "INVALID_RESPONSE")

    def test_only_finite_supported_period_and_tolerance(self):
        for target, tolerance in ((True, 50), (0, 50), (-1, 50), (float("nan"), 50),
                                  (1000, float("inf")), (1000, -1), (60001, 50), (1000, 1000)):
            data = self.goal()
            data["params"] = {"expected_period_ms": target, "tolerance_ms": tolerance}
            self.assertEqual(GoalInterpreter(self.client(data)).interpret("任务").error_code, "INVALID_RESPONSE")

    def test_invalid_goal_never_calls_model(self):
        client = Mock()
        for task in (None, "", " " * 10, "x" * 4001):
            self.assertEqual(GoalInterpreter(client).interpret(task).error_code, "INVALID_ARGUMENT")
        client.generate.assert_not_called()

    def test_model_error_and_timeout_captured(self):
        client = Mock(generate=Mock(return_value=OperationResult(False, "SERVICE_ERROR", "error", "mock",
                                                                 data={"status_code": 503})))
        result = GoalInterpreter(client).interpret("任务")
        self.assertEqual(result.error_code, "SERVICE_ERROR")
        self.assertEqual(result.data["status_code"], 503)
        client.generate.side_effect = TimeoutError("private data")
        result = GoalInterpreter(client).interpret("任务")
        self.assertEqual(result.error_code, "TIMEOUT")
        self.assertNotIn("private data", result.message)

    def test_bad_json_duplicate_fields_and_unknown_schema_rejected(self):
        client = self.client(self.goal())
        for data in ('{"status":"ready","status":"clarification","question":"q"}',
                     '```json\n{}\n```', '[]', '{}',
                     json.dumps({"status": "clarification", "question": ""}),
                     json.dumps({"status": "clarification", "question": "\ud800"}),
                     json.dumps({**self.goal(), "summary": "\ud800"}),
                     json.dumps({**self.goal(), "test_id": "raw_devmem"})):
            client.generate.return_value = OperationResult(True, None, "mock", "mock", data={"content": data})
            self.assertEqual(GoalInterpreter(client).interpret("任务").error_code, "INVALID_RESPONSE")
