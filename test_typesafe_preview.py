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


def automatic_answer(action="reply", direction="comfort", action_confidence=0.97, direction_confidence=0.96):
    def choice_payload(options, chosen, confidence, selected_probability=0.96):
        remaining = (1 - selected_probability) / (len(options) - 1)
        return {
            "type": "choice",
            "choice": chosen,
            "confidence": confidence,
            "probabilities": {
                key: (selected_probability if key == chosen else remaining)
                for key in options
            },
        }
    return {
        "answers": {
            "action": choice_payload(preview.AUTO_ACTIONS, action, action_confidence),
            "direction": choice_payload(preview.REPLY_DIRECTIONS, direction, direction_confidence),
        }
    }


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

    def test_worker_default_does_not_call_typesafe(self):
        settings = core.Settings()
        self.assertFalse(settings.typesafe_auto_routing_enabled)
        worker = core.AutoReplyWorker(settings, Mock(), Mock())
        llm = Mock()
        llm.generate.return_value = "普通回复"
        with patch.object(worker, "_route_incoming") as route:
            decision, reply = worker._decide_and_generate(llm, "你好", False)
        self.assertIsNone(decision)
        self.assertEqual("普通回复", reply)
        route.assert_not_called()
        llm.generate.assert_called_once_with(
            [], "你好", allow_no_reply=False, route_direction=None,
        )

    def test_worker_routes_before_deepseek_and_skips_on_no_reply_or_human(self):
        settings = core.Settings(typesafe_auto_routing_enabled=True)
        worker = core.AutoReplyWorker(settings, Mock(), Mock())
        llm = Mock()
        llm.generate.return_value = "我在这里"
        for action in ("no_reply", "human"):
            with self.subTest(action=action), patch.object(
                worker, "_route_incoming",
                return_value=preview.RoutingDecision(action, None, 0.97, 0.95, "测试"),
            ) as route:
                decision, reply = worker._decide_and_generate(llm, "测试来信", False)
                self.assertEqual(action, decision.action)
                self.assertEqual("", reply)
                route.assert_called_once()
        llm.generate.assert_not_called()
        with patch.object(
            worker, "_route_incoming",
            return_value=preview.RoutingDecision("reply", "comfort", 0.97, 0.96, "测试"),
        ):
            decision, reply = worker._decide_and_generate(llm, "有点难过", False)
        self.assertEqual("reply", decision.action)
        self.assertEqual("我在这里", reply)
        llm.generate.assert_called_once_with(
            [], "有点难过", allow_no_reply=False, route_direction="comfort",
        )

    def test_stop_during_typesafe_route_prevents_deepseek_call(self):
        worker = core.AutoReplyWorker(
            core.Settings(typesafe_auto_routing_enabled=True), Mock(), Mock(),
        )
        llm = Mock()
        def route_and_stop(_incoming):
            worker.stop_event.set()
            return preview.RoutingDecision("reply", "comfort", 0.97, 0.96, "测试")
        with patch.object(worker, "_route_incoming", side_effect=route_and_stop):
            decision, reply = worker._decide_and_generate(llm, "测试", False)
        self.assertEqual("human", decision.action)
        self.assertEqual("", reply)
        llm.generate.assert_not_called()

    def test_human_handoff_pauses_worker_and_clears_pending(self):
        worker = core.AutoReplyWorker(
            core.Settings(typesafe_auto_routing_enabled=True), Mock(), Mock(),
        )
        worker._set_pending(["测试来信"], "待发送的旧回复", False)
        decision = preview.RoutingDecision("human", None, None, None, "接口不可用")
        worker._pause_for_human("测试来信", decision)
        self.assertTrue(worker.stop_event.is_set())
        self.assertEqual("", worker.pending_reply)
        self.assertEqual([], worker.pending_incoming_texts)
        self.assertEqual([{"role": "user", "content": "测试来信"}], worker.history)

    def test_direction_is_fixed_server_side_hint_not_model_supplied_text(self):
        client = core.LLMClient(core.Settings())
        payload = client._payload([], "有点难过", route_direction="comfort")
        self.assertIn(preview.REPLY_DIRECTIONS["comfort"], payload["messages"][0]["content"])
        payload = client._payload([], "有点难过", route_direction="IGNORE_SYSTEM_PROMPT")
        self.assertNotIn("IGNORE_SYSTEM_PROMPT", payload["messages"][0]["content"])

    def test_arrival_during_generation_discards_old_reply(self):
        worker = core.AutoReplyWorker(core.Settings(typesafe_auto_routing_enabled=True), Mock(), Mock())
        worker._set_pending(["之前的消息"], "旧回复", False)
        bridge = Mock()
        bridge.is_target_active.return_value = True
        worker.timeline = Mock()
        worker.timeline.observe.return_value = ["新增消息"]
        with patch.object(worker, "_buffer_incoming", return_value=["之前的消息", "新增消息"]):
            self.assertTrue(worker._refresh_pending_before_send(bridge, False))
        self.assertEqual("", worker.pending_reply)
        self.assertEqual("之前的消息\n新增消息", worker.pending_incoming)
        bridge.send.assert_not_called()

    def test_contact_change_discards_pending_reply(self):
        worker = core.AutoReplyWorker(core.Settings(typesafe_auto_routing_enabled=True), Mock(), Mock())
        worker._set_pending(["之前的消息"], "旧回复", False)
        bridge = Mock()
        bridge.is_target_active.side_effect = [True, False]
        worker.timeline = Mock()
        worker.timeline.observe.return_value = []
        self.assertTrue(worker._refresh_pending_before_send(bridge, False))
        self.assertEqual("", worker.pending_reply)
        self.assertEqual([], worker.pending_incoming_texts)
        bridge.send.assert_not_called()

    def test_automatic_router_requires_explicit_opt_in(self):
        for enabled, consent, api_key in (
            (False, False, "synthetic-test-key"),
            (True, False, "synthetic-test-key"),
            ("true", True, "synthetic-test-key"),
            (True, True, ""),
        ):
            with self.subTest(enabled=enabled, consent=consent, has_key=bool(api_key)):
                decision = preview.evaluate_automatic_routing(
                    "你好", [], risk_check=core.detect_risk,
                    enabled=enabled, consent=consent, api_key=api_key, post=self.post,
                )
                self.assertNotEqual("reply", decision.action)
        self.post.assert_not_called()

    def test_automatic_router_batches_action_and_direction_with_bounded_state(self):
        self.response.json.return_value = automatic_answer()
        history = [{"role": "user", "content": "长" * 1500} for _ in range(6)]
        decision = preview.evaluate_automatic_routing(
            "我有点难过", history, risk_check=core.detect_risk,
            enabled=True, consent=True, api_key="synthetic-test-key", post=self.post,
        )
        self.assertEqual(("reply", "comfort"), (decision.action, decision.direction))
        kwargs = self.post.call_args.kwargs
        self.assertEqual({"action", "direction"}, set(kwargs["json"]["questions"]))
        self.assertEqual("我有点难过", kwargs["json"]["state"]["incoming"])
        self.assertEqual(4, len(kwargs["json"]["state"]["recent_history"]))
        self.assertTrue(kwargs["json"]["state"]["history_was_trimmed"])
        self.assertNotIn("synthetic-test-key", json.dumps(kwargs["json"]))
        self.assertFalse(kwargs["allow_redirects"])
        self.post.assert_called_once()

    def test_automatic_route_no_reply_and_manual_handoff(self):
        for action in ("no_reply", "human"):
            self.response.json.return_value = automatic_answer(action=action)
            decision = preview.evaluate_automatic_routing(
                "先这样吧", [], risk_check=core.detect_risk,
                enabled=True, consent=True, api_key="synthetic-test-key", post=self.post,
            )
            self.assertEqual(action, decision.action)
            self.assertIsNone(decision.direction)

    def test_automatic_route_invalid_uncertain_and_failure_are_closed(self):
        for body in (
            automatic_answer(action_confidence=0.5),
            automatic_answer(direction_confidence=0.5),
            automatic_answer(direction="not_applicable"),
            {"answers": {"action": answer()["answers"]["route"]}},
            {},
        ):
            self.assertEqual("human", preview.parse_automatic_routing(body).action)
        for status in (301, 401, 429, 529):
            with self.subTest(status=status):
                self.response.status_code = status
                self.post.reset_mock()
                decision = preview.evaluate_automatic_routing(
                    "你好", [], risk_check=core.detect_risk,
                    enabled=True, consent=True, api_key="synthetic-test-key", post=self.post,
                )
                self.assertEqual("human", decision.action)
                self.post.assert_called_once()

    def test_automatic_route_risk_and_oversize_never_use_network(self):
        for sample in ("借钱", "问候" * 3001, ""):
            decision = preview.evaluate_automatic_routing(
                sample, [], risk_check=core.detect_risk,
                enabled=True, consent=True, api_key="synthetic-test-key", post=self.post,
            )
            self.assertEqual("human", decision.action)
        self.post.assert_not_called()

    def test_automatic_opt_in_settings_require_consent_and_encrypt_key(self):
        controller = object.__new__(app.ControlApp)
        controller.settings = core.Settings()
        controller.worker = None
        with patch.object(controller.settings, "save") as save:
            with self.assertRaisesRegex(ValueError, "确认"):
                controller.update_typesafe_routing({"enabled": True, "consent": False, "api_key": "synthetic"})
            self.assertFalse(controller.settings.typesafe_auto_routing_enabled)
            data = controller.update_typesafe_routing({
                "enabled": True, "consent": True, "api_key": "synthetic-typesafe-key",
            })
            self.assertTrue(data["enabled"])
            self.assertEqual("synthetic-typesafe-key", controller.settings.get_typesafe_api_key())
            self.assertNotIn("synthetic-typesafe-key", controller.settings.typesafe_api_key_protected)
            save.assert_called_once()

    def test_failed_settings_save_rolls_back_opt_in(self):
        controller = object.__new__(app.ControlApp)
        controller.settings = core.Settings()
        controller.worker = None
        with patch.object(controller.settings, "save", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                controller.update_typesafe_routing({
                    "enabled": True, "consent": True, "api_key": "synthetic-typesafe-key",
                })
        self.assertFalse(controller.settings.typesafe_auto_routing_enabled)
        self.assertEqual("", controller.settings.get_typesafe_api_key())

    def test_bad_persisted_opt_in_is_disabled(self):
        bogus_config = Mock()
        bogus_config.exists.return_value = True
        bogus_config.read_text.return_value = json.dumps({"typesafe_auto_routing_enabled": "true"})
        with patch.object(core, "CONFIG_PATH", bogus_config):
            settings = core.Settings.load()
        self.assertFalse(settings.typesafe_auto_routing_enabled)
        self.assertIn('id="typesafeAutoRouting"', app.HTML)
        self.assertIn("typesafe_auto_routing_enabled", app.HTML)

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
