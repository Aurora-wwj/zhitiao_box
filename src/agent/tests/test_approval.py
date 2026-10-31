import unittest

from zhidiao_agent.approval import ApprovalGate


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.gate = ApprovalGate()
        self.params = {"command": "reviewed command", "diff": "+ reviewed change"}

    def approve(self):
        preview = self.gate.propose("shell", self.params).data
        result = self.gate.decide(
            preview["proposal_id"], preview["fingerprint"], approved=True,
        )
        self.assertTrue(result.success)
        return result.data["approval_id"]

    def test_approval_is_single_use(self):
        token = self.approve()
        self.assertTrue(self.gate.consume(token, "shell", self.params).success)
        self.assertEqual(self.gate.consume(token, "shell", self.params).error_code, "APPROVAL_REQUIRED")

    def test_changed_action_or_payload_is_not_authorized(self):
        token = self.approve()
        self.assertFalse(self.gate.consume(token, "push", self.params).success)
        token = self.approve()
        self.assertFalse(self.gate.consume(token, "shell", {"command": "other"}).success)

    def test_rejection_never_authorizes(self):
        preview = self.gate.propose("shell", self.params).data
        result = self.gate.decide(preview["proposal_id"], preview["fingerprint"], approved=False)
        self.assertEqual(result.error_code, "APPROVAL_REJECTED")
        self.assertFalse(self.gate.consume(preview["proposal_id"], "shell", self.params).success)

    def test_missing_and_implicit_decisions_fail(self):
        self.assertFalse(self.gate.consume("invented", "shell", self.params).success)
        preview = self.gate.propose("shell", self.params).data
        result = self.gate.decide(preview["proposal_id"], preview["fingerprint"], approved="yes")
        self.assertEqual(result.error_code, "INVALID_ARGUMENT")

    def test_preview_does_not_follow_input_mutation(self):
        preview = self.gate.propose("shell", self.params).data
        self.params["command"] = "changed"
        self.assertEqual(preview["params"]["command"], "reviewed command")
