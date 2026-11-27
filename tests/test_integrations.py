import hashlib
import hmac
import unittest
from unittest.mock import patch

import integrations


class IntegrationTests(unittest.TestCase):
    def test_workspace_config_has_no_fallback(self):
        with patch.dict("os.environ", {"TAYSRIUL_TEBAR": '{"1":{"token":"fixture"}}'}):
            self.assertEqual(integrations.config("TEBAR", 1)["token"], "fixture")
            self.assertEqual(integrations.config("TEBAR", 2), {})

    def test_tebar_uses_idempotency_key_and_confirms_per_target(self):
        with patch("integrations.provider_request") as call:
            call.return_value = {"id": "post-1"}
            self.assertEqual(integrations.create_tebar({"token": "fixture"}, "target-1", "key-1", "Caption", None), "post-1")
            self.assertEqual(call.call_args.kwargs["headers"], {"Idempotency-Key": "key-1"})
            call.return_value = {"targets": [
                {"account_id": "target-2", "status": "published"},
                {"account_id": "target-1", "status": "pending"},
            ]}
            self.assertEqual(integrations.tebar_status({"token": "fixture"}, "post-1", "target-1")[0], "Diproses platform")
            call.return_value["targets"][1]["status"] = "published"
            self.assertEqual(integrations.tebar_status({"token": "fixture"}, "post-1", "target-1")[0], "Terbit")

    def test_balaschat_verifies_exact_body(self):
        raw = b'{"event":"message.received"}'
        signature = "sha256=" + hmac.new(b"secret", raw, hashlib.sha256).hexdigest()
        self.assertTrue(integrations.valid_signature(raw, signature, "secret"))
        self.assertFalse(integrations.valid_signature(raw + b" ", signature, "secret"))
        self.assertFalse(integrations.valid_signature(raw, signature, "different"))

    def test_waba_message_and_reply(self):
        payload = {"conversation_id": 3, "message": {"id": 4, "text": "Halo", "created_at": "2020-11-26T05:00:00+00:00"},
                   "contact": {"phone": "6281234567890", "name": "Pelanggan"}}
        thread = integrations.waba_message(payload)
        self.assertEqual(thread["id"], "3")
        self.assertEqual(thread["messages"]["data"][0]["id"], "4")
        settings = {"token": "fixture", "workspace": "bisnis", "phone_number_id": "123456789"}
        with patch("integrations.provider_request", return_value={"status": True, "data": {"message_id": 5}}) as call:
            with self.assertRaises(ValueError):
                integrations.send_waba(settings, "lain:123456789", "6281234567890", "Halo")
            call.assert_not_called()
            sent = integrations.send_waba(settings, "bisnis:123456789", "6281234567890", "Halo")
            self.assertEqual(sent, {"message_id": "5"})
            self.assertEqual(call.call_args.kwargs["json"]["channel"], "waba")
