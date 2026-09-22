import json
import unittest
from unittest.mock import Mock, patch

import core
import typesafe_preview as preview
import app


def answer(choice="reply", confidence=0.95):
    return {"answers": {"route": {
        "type": "choice", "choice": choice, "confidence": confidence,
        "probabilities": {key: (0.96 if key == choice else 0.02) for key in preview.OPTIONS},
    }}}


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.post = Mock()
        self.response = Mock(status_code=200)
        self.response.json.return_value = answer()
        self.post.return_value = self.response

    def evaluate(self, text="今天过得怎么样？", **overrides):
        args = dict(risk_check=core.detect_risk, enabled=True, consent=True,
                    api_key="synthetic-test-key", post=self.post)
        args.update(overrides)
        return preview.evaluate(text, **args)

    def test_default_disabled_and_each_gate(self):
        result = preview.evaluate("你好", risk_check=core.detect_risk, post=self.post)
        self.assertEqual("disabled", result.action)
        for values in ({"enabled": False}, {"consent": False}, {"enabled": "true"}, {"consent": 1}):
            self.assertEqual("disabled", self.evaluate(**values).action)
        self.post.assert_not_called()

    def test_missing_key(self):
        self.assertEqual("human", self.evaluate(api_key=" ").action)
        self.post.assert_not_called()

    def test_all_existing_risk_terms_preempt_network(self):
        for terms in core.RISK_TERMS.values():
            for term in terms:
                with self.subTest(term=term):
                    result = self.evaluate("虚构测试：" + term)
                    self.assertEqual("human", result.action)
        self.post.assert_not_called()

    def test_risk_check_failure_is_closed(self):
        self.assertEqual("human", self.evaluate(risk_check=Mock(side_effect=RuntimeError())).action)
        self.post.assert_not_called()

    def test_empty_oversize_and_nontext_are_not_uploaded(self):
        for text in ("", " ", "你" * 2001, None, 123):
            self.assertEqual("human", self.evaluate(text).action)
        self.post.assert_not_called()

    def test_payload_minimization_and_transport(self):
        result = self.evaluate()
        url = self.post.call_args.args[0]
        args = self.post.call_args.kwargs
        self.assertEqual(preview.ENDPOINT, url)
        self.assertEqual({"incoming": "今天过得怎么样？"}, args["json"]["state"])
        self.assertEqual({"state", "model", "questions"}, set(args["json"]))
        self.assertNotIn("synthetic-test-key", json.dumps(args["json"]))
        self.assertEqual((3.05, 8), args["timeout"])
        self.assertFalse(args["allow_redirects"])
        self.assertEqual("reply", result.action)
        self.assertFalse(result.automatic_send_allowed)
        self.response.close.assert_called_once()

    def test_each_suggestion_never_authorizes_send(self):
        for choice in preview.OPTIONS:
            self.response.json.return_value = answer(choice)
            result = self.evaluate()
            self.assertEqual(choice, result.action)
            self.assertFalse(result.automatic_send_allowed)

    def test_uncertainty_requires_human(self):
        for confidence in (0, 0.5, 0.849):
            self.assertEqual("human", preview.parse_answer(answer(confidence=confidence)).action)
        payload = answer()
        payload["answers"]["route"]["probabilities"] = {"reply": 0.6, "human": 0.2, "no_reply": 0.2}
        self.assertEqual("human", preview.parse_answer(payload).action)

    def test_invalid_response_shapes_and_numbers(self):
        payloads = [None, [], {}, {"answers": []}, {"answers": {"route": None}}]
        for field, value in (("type", "noul"), ("choice", "send_now"), ("choice", []),
                             ("probabilities", {}), ("probabilities", None),
                             ("confidence", True), ("confidence", "1"),
                             ("confidence", float("nan")), ("confidence", float("inf")),
                             ("confidence", -0.1), ("confidence", 1.1)):
            payload = answer()
            payload["answers"]["route"][field] = value
            payloads.append(payload)
        for value in (-1, 2, True, "1", float("nan"), float("inf")):
            payload = answer()
            payload["answers"]["route"]["probabilities"]["reply"] = value
            payloads.append(payload)
        payload = answer()
        payload["answers"]["route"]["choice"] = "no_reply"
        payloads.append(payload)
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual("human", preview.parse_answer(payload).action)

    def test_service_errors_do_not_retry_or_leak(self):
        for code in (301, 401, 422, 429, 500, 529):
            self.post.reset_mock()
            self.response.status_code = code
            result = self.evaluate()
            self.assertEqual("human", result.action)
            self.post.assert_called_once()
        self.post.side_effect = RuntimeError("synthetic-test-key private-message")
        result = self.evaluate()
        self.assertEqual("human", result.action)
        self.assertNotIn("synthetic-test-key", str(result))
        self.assertNotIn("private-message", str(result))

    def test_bad_json_is_closed_and_response_closed(self):
        self.response.json.side_effect = ValueError("private body")
        result = self.evaluate()
        self.assertEqual("human", result.action)
        self.assertNotIn("private body", str(result))
        self.response.close.assert_called_once()

    def test_cli_default_has_no_network_or_key_lookup(self):
        with patch("sys.argv", ["typesafe_preview.py"]), patch("builtins.input", return_value="你好"), \
             patch("builtins.print"), patch.object(preview.os.environ, "get") as env:
            self.assertEqual(0, preview.main())
            self.assertFalse(any(call.args and call.args[0] == "TYPESAFE_API_KEY"
                                 for call in env.call_args_list))

    def test_existing_worker_not_wired_to_preview(self):
        # Stage one is manual-only, including the pre-existing risk warning path.
        import inspect
        source = inspect.getsource(core.AutoReplyWorker)
        self.assertNotIn("typesafe", source.lower())

    def test_desktop_preview_encrypts_key_and_does_not_log_sample(self):
        settings = core.Settings()
        controller = app.ControlApp()
        controller.settings = settings
        sample = "虚构的普通问候"
        with patch.object(settings, "save") as save, patch.object(
            app, "evaluate_typesafe", return_value=preview.Preview("reply", "test", 0.99)
        ) as evaluate:
            result = controller.preview_typesafe({
                "sample": sample, "api_key": "synthetic-typesafe-key", "consent": True,
            })
        self.assertEqual("reply", result["action"])
        self.assertEqual("synthetic-typesafe-key", settings.get_typesafe_api_key())
        self.assertNotIn("synthetic-typesafe-key", settings.typesafe_api_key_protected)
        self.assertNotIn(sample, "\n".join(controller.logs))
        evaluate.assert_called_once()
        save.assert_called_once()
        self.assertFalse(result["automatic_send_allowed"])

    def test_desktop_preview_requires_explicit_consent(self):
        controller = app.ControlApp()
        controller.settings = core.Settings()
        with patch.object(app, "evaluate_typesafe") as evaluate:
            with self.assertRaisesRegex(ValueError, "同意"):
                controller.preview_typesafe({"sample": "虚构样例", "consent": False})
        evaluate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
