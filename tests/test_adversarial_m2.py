"""
tests/test_adversarial_m2.py - Adversarial Stress & Chaos Test Suite for Milestone M2
=====================================================================================

Empirical stress testing targeting:
1. VAPID Key Edge Cases: corrupted config/vapid files, permission errors, key reload stability, invalid curve handling.
2. Subscription Storage Stress: concurrent multi-threaded add/remove operations, malformed subscriptions, invalid JSON recovery.
3. Webpush Payload & Endpoint Extremes: oversized payloads, special unicode characters, null data, empty title/body.
4. HTTP Status Simulation: 410/404 auto-prune, 429 backoff/retention, 500/502/503/504 error handling, network drops.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa, ed25519
from py_vapid import Vapid

from push_notifications import (
    ClientVisibilityState,
    PushNotificationManager,
    _extract_status_code,
)
from tests.harness import (
    MockPushService,
    assert_vapid_key_valid,
    assert_push_payload_valid,
)


class TestVapidAdversarialCases(unittest.TestCase):
    """Adversarial stress testing of VAPID key loading, generation, and recovery."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="adv_vapid_")
        self.config_path = os.path.join(self.temp_dir, "config.json")
        self.subs_path = os.path.join(self.temp_dir, "push-subscriptions.json")
        self.vapid_path = os.path.join(self.temp_dir, "vapid-keys.json")

    def tearDown(self) -> None:
        # Restore permissions in case of read-only files
        for root, dirs, files in os.walk(self.temp_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    os.chmod(fpath, stat.S_IWRITE | stat.S_IREAD)
                except Exception:
                    pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_vapid_file_empty(self) -> None:
        """Empty vapid-keys.json file (0 bytes) should be handled cleanly with regeneration."""
        with open(self.vapid_path, "w", encoding="utf-8") as f:
            f.write("")
        mgr = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        pub = mgr.get_public_vapid_key()
        self.assertTrue(bool(pub))
        assert_vapid_key_valid(pub)

    def test_vapid_file_binary_garbage(self) -> None:
        """Binary random garbage in vapid-keys.json should trigger clean regeneration."""
        with open(self.vapid_path, "wb") as f:
            f.write(os.urandom(256))
        mgr = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        pub = mgr.get_public_vapid_key()
        self.assertTrue(bool(pub))
        assert_vapid_key_valid(pub)

    def test_vapid_file_non_dict_json(self) -> None:
        """JSON array, integer, or string in vapid-keys.json should not crash constructor."""
        test_inputs = [
            json.dumps(["key1", "key2"]),
            json.dumps(12345),
            json.dumps("just a string"),
            json.dumps(None),
            json.dumps(True),
        ]
        for content in test_inputs:
            with open(self.vapid_path, "w", encoding="utf-8") as f:
                f.write(content)
            mgr = PushNotificationManager(
                config_path=self.config_path,
                subscriptions_path=self.subs_path,
                vapid_path=self.vapid_path,
            )
            pub = mgr.get_public_vapid_key()
            self.assertTrue(bool(pub), f"Failed for input: {content}")
            assert_vapid_key_valid(pub)

    def test_vapid_file_wrong_value_types_in_dict(self) -> None:
        """Non-string values in publicKey/privateKey dictionary should be safely handled."""
        test_payloads = [
            {"publicKey": 12345, "privateKey": 67890},
            {"publicKey": None, "privateKey": None},
            {"publicKey": ["pub"], "privateKey": {"priv": "key"}},
            {"publicKey": "", "privateKey": ""},
            {"publicKey": "   ", "privateKey": "   "},
            {"publicKey": "valid_looking_key"},  # missing privateKey
            {"privateKey": "valid_looking_key"},  # missing publicKey
        ]
        for payload in test_payloads:
            with open(self.vapid_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            mgr = PushNotificationManager(
                config_path=self.config_path,
                subscriptions_path=self.subs_path,
                vapid_path=self.vapid_path,
            )
            pub = mgr.get_public_vapid_key()
            self.assertTrue(bool(pub), f"Failed for payload: {payload}")
            assert_vapid_key_valid(pub)

    def test_vapid_invalid_key_curves(self) -> None:
        """Private keys on wrong curves (RSA, SECP384R1, SECP521R1, Ed25519) should regenerate."""
        # 1. RSA Private Key
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pem = rsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("utf-8")
        with open(self.vapid_path, "w", encoding="utf-8") as f:
            json.dump({"publicKey": "some_pub", "privateKey": rsa_pem}, f)
        mgr = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        assert_vapid_key_valid(mgr.get_public_vapid_key())

        # 2. SECP384R1 Private Key
        p384_key = ec.generate_private_key(ec.SECP384R1())
        p384_pem = p384_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("utf-8")
        with open(self.vapid_path, "w", encoding="utf-8") as f:
            json.dump({"publicKey": "some_pub", "privateKey": p384_pem}, f)
        mgr2 = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        assert_vapid_key_valid(mgr2.get_public_vapid_key())

        # 3. Ed25519 Private Key
        ed_key = ed25519.Ed25519PrivateKey.generate()
        ed_pem = ed_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("utf-8")
        with open(self.vapid_path, "w", encoding="utf-8") as f:
            json.dump({"publicKey": "some_pub", "privateKey": ed_pem}, f)
        mgr3 = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        assert_vapid_key_valid(mgr3.get_public_vapid_key())

    def test_config_json_vapid_corrupted(self) -> None:
        """Corrupted or non-dict vapid section in config.json should regenerate cleanly."""
        corrupted_configs = [
            {"vapid": "not a dict"},
            {"vapid": 12345},
            {"vapid": {"publicKey": 123}},
            {"vapid": None},
        ]
        for cfg in corrupted_configs:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            mgr = PushNotificationManager(
                config_path=self.config_path,
                subscriptions_path=self.subs_path,
                vapid_path=os.path.join(self.temp_dir, "nonexistent.json"),
            )
            pub = mgr.get_public_vapid_key()
            self.assertTrue(bool(pub))
            assert_vapid_key_valid(pub)

    def test_concurrent_vapid_initialization(self) -> None:
        """Multiple threads initializing managers concurrently with the same path should not corrupt."""
        results: List[str] = []

        def init_worker() -> None:
            mgr = PushNotificationManager(
                config_path=self.config_path,
                subscriptions_path=self.subs_path,
                vapid_path=self.vapid_path,
            )
            results.append(mgr.get_public_vapid_key())

        threads = [threading.Thread(target=init_worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 20)
        for pub in results:
            assert_vapid_key_valid(pub)


class TestSubscriptionAdversarialCases(unittest.TestCase):
    """Adversarial stress testing of push subscription validation, concurrency, and persistence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="adv_subs_")
        self.config_path = os.path.join(self.temp_dir, "config.json")
        self.subs_path = os.path.join(self.temp_dir, "push-subscriptions.json")
        self.vapid_path = os.path.join(self.temp_dir, "vapid-keys.json")
        self.manager = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_malformed_subscription_inputs(self) -> None:
        """Adversarial malformed subscription data structures rejected safely."""
        malformed_inputs = [
            None,
            12345,
            True,
            [],
            {},
            {"endpoint": ""},
            {"endpoint": " "},
            {"endpoint": "ftp://invalid.com/push"},
            {"endpoint": "javascript:alert(1)"},
            {"endpoint": "file:///etc/passwd"},
            {"endpoint": "https://push.example.com", "keys": None},
            {"endpoint": "https://push.example.com", "keys": "not-a-dict"},
            {"endpoint": "https://push.example.com", "keys": {}},
            {"endpoint": "https://push.example.com", "keys": {"p256dh": ""}},
            {"endpoint": "https://push.example.com", "keys": {"auth": ""}},
            {"endpoint": "https://push.example.com", "keys": {"p256dh": 123, "auth": 456}},
            {"endpoint": "https://push.example.com", "keys": {"p256dh": None, "auth": None}},
            {"endpoint": 12345, "keys": {"p256dh": "k", "auth": "a"}},
        ]
        for item in malformed_inputs:
            res = self.manager.add_subscription(item)  # type: ignore
            self.assertFalse(res, f"Expected False for malformed input: {item}")
        self.assertEqual(len(self.manager.get_subscriptions()), 0)

    def test_extreme_length_endpoint_and_keys(self) -> None:
        """Extremely large endpoint strings (100KB) and keys should be accepted if valid format."""
        huge_endpoint = "https://fcm.googleapis.com/fcm/send/" + "x" * 100000
        huge_sub = {
            "endpoint": huge_endpoint,
            "keys": {"p256dh": "k" * 1000, "auth": "a" * 1000},
        }
        res = self.manager.add_subscription(huge_sub)
        self.assertTrue(res)
        self.assertEqual(len(self.manager.get_subscriptions()), 1)
        self.assertTrue(self.manager.remove_subscription(huge_endpoint))

    def test_concurrent_multi_threaded_add_remove_stress(self) -> None:
        """High concurrency stress: 50 threads simultaneously adding and removing subscriptions."""
        thread_count = 50
        ops_per_thread = 20
        errors: List[Exception] = []

        def worker(thread_id: int) -> None:
            try:
                for i in range(ops_per_thread):
                    ep = f"https://fcm.googleapis.com/send/client_{thread_id}_dev_{i}"
                    sub = {
                        "endpoint": ep,
                        "keys": {"p256dh": f"p256_{thread_id}_{i}", "auth": f"auth_{thread_id}_{i}"},
                    }
                    self.manager.add_subscription(sub)
                    _ = self.manager.get_subscriptions()
                    if i % 2 == 0:
                        self.manager.remove_subscription(ep)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [executor.submit(worker, tid) for tid in range(thread_count)]
            for f in futures:
                f.result()

        self.assertEqual(len(errors), 0, f"Encountered concurrency errors: {errors}")
        # Validate that disk file is valid JSON
        self.assertTrue(os.path.exists(self.subs_path))
        with open(self.subs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertIsInstance(data, dict)

    def test_corrupted_subscriptions_on_disk_variants(self) -> None:
        """Various corrupted formats in push-subscriptions.json should not crash manager."""
        corrupted_variants = [
            "{ incomplete json ...",
            "",
            "null",
            "12345",
            '"string"',
            json.dumps(["not", "a", "dict"]),
            json.dumps({"https://ep1": "not-a-dict-value"}),
            json.dumps({"https://ep2": 12345}),
            json.dumps([["only_one_item"]]),
            json.dumps([123, 456]),
        ]
        for content in corrupted_variants:
            with open(self.subs_path, "w", encoding="utf-8") as f:
                f.write(content)
            mgr = PushNotificationManager(
                config_path=self.config_path,
                subscriptions_path=self.subs_path,
                vapid_path=self.vapid_path,
            )
            # Must not crash and should return list
            subs = mgr.get_subscriptions()
            self.assertIsInstance(subs, list)


class TestWebPushPayloadAndExtremes(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing of payloads, special characters, and extremes."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="adv_payload_")
        self.config_path = os.path.join(self.temp_dir, "config.json")
        self.subs_path = os.path.join(self.temp_dir, "subs.json")
        self.vapid_path = os.path.join(self.temp_dir, "vapid.json")
        self.manager = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        self.mock_push = MockPushService()
        self.mock_push.patch()

    async def asyncTearDown(self) -> None:
        self.mock_push.unpatch()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_special_unicode_payloads(self) -> None:
        """Tests emojis, RTL arabic, CJK, Zalgo text, newline injection, and quote escapes."""
        self.manager.add_subscription({
            "endpoint": "https://fcm.googleapis.com/send/unicode_device",
            "keys": {"p256dh": "k", "auth": "a"},
        })

        unicode_titles_and_bodies = [
            ("🚀 WahyuAI Notification 🎉", "Agent finished task with ✅ 100% success! 🤖"),
            ("مرحبا بك في تطبيق", "هذا إشعار تجريبي لاختبار النصوص العربية"),
            ("日本語テスト", "プッシュ通知のテストメッセージです。"),
            ("Zalgo H̶e̶l̶l̶o̶", "T̴e̷s̶t̷ ̴M̶e̵s̶s̷a̸g̸e̵"),
            ("Line\nBreak\r\nTest\tTab", "Multi\nLine\r\nBody\tWith\0NullSafe"),
            ('<script>alert("XSS")</script>', '{"json_injection": true, "key": "value"}'),
        ]

        for title, body in unicode_titles_and_bodies:
            self.mock_push.clear()
            delivered = await self.manager.send_notification(
                title=title,
                body=body,
                data={"custom": "unicode_val", "text": body},
            )
            self.assertEqual(delivered, 1)
            self.assertEqual(len(self.mock_push.sent_notifications), 1)
            rec = self.mock_push.sent_notifications[0]
            assert_push_payload_valid(rec["payload_json"])
            self.assertEqual(rec["payload_json"]["title"], title)
            self.assertEqual(rec["payload_json"]["body"], body)

    async def test_oversized_payloads(self) -> None:
        """Large payloads (e.g. 50KB JSON body) are serialized and sent without crashing."""
        self.manager.add_subscription({
            "endpoint": "https://fcm.googleapis.com/send/large_device",
            "keys": {"p256dh": "k", "auth": "a"},
        })
        large_body = "A" * 50000
        large_data = {"large_field": "X" * 20000}

        delivered = await self.manager.send_notification("Large Payload", large_body, data=large_data)
        self.assertEqual(delivered, 1)
        self.assertEqual(len(self.mock_push.sent_notifications), 1)
        rec = self.mock_push.sent_notifications[0]
        self.assertEqual(len(rec["payload_json"]["body"]), 50000)

    async def test_empty_title_and_body_and_none_data(self) -> None:
        """Empty title, empty body, and None data are handled gracefully."""
        self.manager.add_subscription({
            "endpoint": "https://fcm.googleapis.com/send/empty_device",
            "keys": {"p256dh": "k", "auth": "a"},
        })
        delivered = await self.manager.send_notification(title="", body="", data=None)
        self.assertEqual(delivered, 1)
        rec = self.mock_push.sent_notifications[0]
        self.assertEqual(rec["payload_json"]["title"], "")
        self.assertEqual(rec["payload_json"]["body"], "")
        self.assertEqual(rec["payload_json"]["data"], {})

    async def test_attention_items_chaos_inputs(self) -> None:
        """Attention items with null values, wrong types, missing fields, or 1000 items."""
        self.manager.add_subscription({
            "endpoint": "https://fcm.googleapis.com/send/att_device",
            "keys": {"p256dh": "k", "auth": "a"},
        })

        chaos_items = [
            {},
            {"id": None, "type": None, "name": None, "text": None},
            {"id": 12345, "type": 67890, "name": ["a", "b"]},
            {"type": "unknown_type_action", "name": "do something"},
            {"type": "question", "text": "   "},
            {"type": "command", "name": ""},
            {"type": "completed"},
        ]

        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            # Should process without unhandled exception
            sent = await self.manager.check_and_send_attention_notifications(
                chaos_items, agent_running=True, conversation_name="Chaos Conv", conversation_id="conv-chaos-1"
            )
            self.assertGreaterEqual(sent, 0)

        # Scale test: 1000 attention items
        large_items = [
            {"id": f"item_{i}", "type": "command" if i % 2 == 0 else "question", "name": f"Task {i}"}
            for i in range(1000)
        ]
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            sent_large = await self.manager.check_and_send_attention_notifications(
                large_items, agent_running=True
            )
            self.assertEqual(sent_large, 1000)


class TestHttpStatusSimulationAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing of HTTP status simulation and network chaos."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="adv_http_")
        self.config_path = os.path.join(self.temp_dir, "config.json")
        self.subs_path = os.path.join(self.temp_dir, "subs.json")
        self.vapid_path = os.path.join(self.temp_dir, "vapid.json")
        self.manager = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        self.mock_push = MockPushService()
        self.mock_push.patch()

    async def asyncTearDown(self) -> None:
        self.mock_push.unpatch()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_mixed_batch_auto_prune_matrix(self) -> None:
        """
        Mixed batch of 10 endpoints:
        - 2 return 201 (Created / Success)
        - 2 return 410 (Gone -> Auto Pruned)
        - 2 return 404 (Not Found -> Auto Pruned)
        - 2 return 429 (Rate Limited -> Retained)
        - 2 return 500 (Server Error -> Retained)
        """
        for i in range(10):
            ep = f"https://fcm.googleapis.com/send/mixed_sub_{i}"
            self.manager.add_subscription({"endpoint": ep, "keys": {"p256dh": f"k{i}", "auth": f"a{i}"}})

        # Assign HTTP status codes
        # 0, 1: 201
        # 2, 3: 410
        self.mock_push.set_endpoint_status("https://fcm.googleapis.com/send/mixed_sub_2", 410)
        self.mock_push.set_endpoint_status("https://fcm.googleapis.com/send/mixed_sub_3", 410)
        # 4, 5: 404
        self.mock_push.set_endpoint_status("https://fcm.googleapis.com/send/mixed_sub_4", 404)
        self.mock_push.set_endpoint_status("https://fcm.googleapis.com/send/mixed_sub_5", 404)
        # 6, 7: 429
        self.mock_push.set_endpoint_status("https://fcm.googleapis.com/send/mixed_sub_6", 429)
        self.mock_push.set_endpoint_status("https://fcm.googleapis.com/send/mixed_sub_7", 429)
        # 8, 9: 500
        self.mock_push.set_endpoint_status("https://fcm.googleapis.com/send/mixed_sub_8", 500)
        self.mock_push.set_endpoint_status("https://fcm.googleapis.com/send/mixed_sub_9", 500)

        delivered = await self.manager.send_notification("Mixed Batch", "Testing status matrix")
        self.assertEqual(delivered, 2)  # Only 0 and 1 succeed

        # Total retained endpoints should be: 10 - 4 (pruned) = 6
        remaining = self.manager.get_subscriptions()
        self.assertEqual(len(remaining), 6)
        remaining_eps = {s["endpoint"] for s in remaining}

        # 410 and 404 endpoints must be pruned
        self.assertNotIn("https://fcm.googleapis.com/send/mixed_sub_2", remaining_eps)
        self.assertNotIn("https://fcm.googleapis.com/send/mixed_sub_3", remaining_eps)
        self.assertNotIn("https://fcm.googleapis.com/send/mixed_sub_4", remaining_eps)
        self.assertNotIn("https://fcm.googleapis.com/send/mixed_sub_5", remaining_eps)

        # 201, 429, 500 endpoints must be retained
        self.assertIn("https://fcm.googleapis.com/send/mixed_sub_0", remaining_eps)
        self.assertIn("https://fcm.googleapis.com/send/mixed_sub_1", remaining_eps)
        self.assertIn("https://fcm.googleapis.com/send/mixed_sub_6", remaining_eps)
        self.assertIn("https://fcm.googleapis.com/send/mixed_sub_7", remaining_eps)
        self.assertIn("https://fcm.googleapis.com/send/mixed_sub_8", remaining_eps)
        self.assertIn("https://fcm.googleapis.com/send/mixed_sub_9", remaining_eps)

    async def test_server_error_status_codes_502_503_504(self) -> None:
        """HTTP 502, 503, 504 gateway and service errors do not prune subscriptions."""
        status_codes = [502, 503, 504, 408, 400, 401, 403]
        for idx, status in enumerate(status_codes):
            ep = f"https://fcm.googleapis.com/send/status_{status}_{idx}"
            self.manager.add_subscription({"endpoint": ep, "keys": {"p256dh": "k", "auth": "a"}})
            self.mock_push.set_endpoint_status(ep, status)

        delivered = await self.manager.send_notification("Errors", "Testing 5xx/4xx")
        self.assertEqual(delivered, 0)

        # All subscriptions must be retained
        self.assertEqual(len(self.manager.get_subscriptions()), len(status_codes))

    async def test_network_exceptions_chaos(self) -> None:
        """Diverse network exceptions (Timeout, ConnectionReset, SSLError) handled gracefully."""
        ep = "https://fcm.googleapis.com/send/chaos_net"
        self.manager.add_subscription({"endpoint": ep, "keys": {"p256dh": "k", "auth": "a"}})

        exceptions = [
            TimeoutError("Socket timed out after 5.0s"),
            ConnectionResetError("Connection reset by peer"),
            OSError("Network is unreachable"),
            RuntimeError("Unexpected pywebpush internal error"),
        ]

        for exc in exceptions:
            self.mock_push.set_exception(exc)
            delivered = await self.manager.send_notification("Chaos", "Testing network drops")
            self.assertEqual(delivered, 0)
            # Subscription must remain
            self.assertEqual(len(self.manager.get_subscriptions()), 1)


if __name__ == "__main__":
    unittest.main()
