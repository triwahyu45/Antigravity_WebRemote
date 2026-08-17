"""
tests/test_push_notifications.py - Unit Test Suite for PushNotificationManager
==============================================================================

Comprehensive test suite verifying:
1. VAPID keypair generation, X9.62 uncompressed point encoding (87 chars), and persistence.
2. Browser push subscription validation, deduplication, atomic file storage, and reload.
3. Multi-client visibility tracking, heartbeat expiration, and foreground suppression.
4. Attention state watcher: command approvals, questions, agent running transitions,
   deduplication, resolved item pruning, and startup guards.
5. WebPush dispatching via pywebpush with async threading, HTTP 410/404 auto-pruning,
   429 rate-limiting tolerance, and network error resilience.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import tempfile
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid

from push_notifications import (
    ClientVisibilityState,
    PushNotificationManager,
    _extract_status_code,
)
from tests.harness import (
    MockPushService,
    assert_push_payload_valid,
    assert_push_subscription_valid,
    assert_vapid_key_valid,
)


class TestVapidKeyManagement(unittest.TestCase):
    """Tests VAPID EC P-256 key generation, format verification, and persistence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="vapid_test_")
        self.config_path = os.path.join(self.temp_dir, "config.json")
        self.subs_path = os.path.join(self.temp_dir, "push-subscriptions.json")
        self.vapid_path = os.path.join(self.temp_dir, "vapid-keys.json")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_vapid_key_generation_when_missing(self) -> None:
        """When vapid-keys.json does not exist, a new valid EC P-256 keypair is generated."""
        manager = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        pub_key = manager.get_public_vapid_key()

        # Public key must exist and be valid
        self.assertTrue(bool(pub_key))
        assert_vapid_key_valid(pub_key)

        # File must be created on disk
        self.assertTrue(os.path.exists(self.vapid_path))
        with open(self.vapid_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data.get("publicKey"), pub_key)
            self.assertIn("-----BEGIN PRIVATE KEY-----", data.get("privateKey", ""))

    def test_vapid_key_persistence_and_reload(self) -> None:
        """Loading from an existing vapid-keys.json preserves the identical public key."""
        manager1 = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        pub1 = manager1.get_public_vapid_key()

        # Instantiate second manager pointing to same file
        manager2 = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        pub2 = manager2.get_public_vapid_key()

        self.assertEqual(pub1, pub2)

    def test_vapid_key_load_from_config_json(self) -> None:
        """If vapid-keys.json does not exist but config.json contains vapid keys, load them."""
        priv = ec.generate_private_key(ec.SECP256R1())
        raw_pub = priv.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        pub_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode("ascii")
        pem_priv = priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("utf-8")

        config_data = {
            "vapid": {
                "publicKey": pub_b64,
                "privateKey": pem_priv,
            }
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f)

        manager = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=os.path.join(self.temp_dir, "nonexistent_vapid.json"),
        )
        self.assertEqual(manager.get_public_vapid_key(), pub_b64)

    def test_vapid_key_corrupted_file_recovery(self) -> None:
        """If vapid-keys.json is corrupted, manager regenerates valid keys without failing."""
        with open(self.vapid_path, "w", encoding="utf-8") as f:
            f.write("{ INVALID JSON CORRUPTED ...")

        manager = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        pub = manager.get_public_vapid_key()
        self.assertTrue(bool(pub))
        assert_vapid_key_valid(pub)

    def test_vapid_key_raw_scalar_format_support(self) -> None:
        """Supports Node.js web-push style 32-byte base64url raw scalar private keys."""
        priv = ec.generate_private_key(ec.SECP256R1())
        raw_pub = priv.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        pub_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode("ascii")
        d_scalar = priv.private_numbers().private_value.to_bytes(32, "big")
        raw_priv_b64 = base64.urlsafe_b64encode(d_scalar).rstrip(b"=").decode("ascii")

        with open(self.vapid_path, "w", encoding="utf-8") as f:
            json.dump({"publicKey": pub_b64, "privateKey": raw_priv_b64}, f)

        manager = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        self.assertEqual(manager.get_public_vapid_key(), pub_b64)
        self.assertIsNotNone(manager.vapid)

    def test_vapid_key_invalid_length_or_curve_recovery(self) -> None:
        """Invalid length or corrupted public/private key pairs trigger automatic valid key generation."""
        with open(self.vapid_path, "w", encoding="utf-8") as f:
            json.dump({"publicKey": "short_key", "privateKey": "invalid_priv"}, f)

        manager = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        pub = manager.get_public_vapid_key()
        self.assertTrue(bool(pub))
        assert_vapid_key_valid(pub)


class TestSubscriptionStorage(unittest.TestCase):
    """Tests browser push subscription validation, deduplication, and atomic persistence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="subs_test_")
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

    def test_add_valid_subscription(self) -> None:
        """Adding a valid push subscription succeeds and persists to disk."""
        sub_data = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/device_token_1",
            "keys": {
                "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DQA",
                "auth": "tBHItJI5svbpez7KI4CCXg",
            },
            "expirationTime": None,
        }
        res = self.manager.add_subscription(sub_data)
        self.assertTrue(res)

        subs = self.manager.get_subscriptions()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["endpoint"], sub_data["endpoint"])

        # Check persisted file
        self.assertTrue(os.path.exists(self.subs_path))
        with open(self.subs_path, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
            self.assertIn(sub_data["endpoint"], disk_data)

    def test_add_invalid_subscription_rejected(self) -> None:
        """Invalid subscriptions missing endpoint, keys, or malformed data are rejected."""
        # Non-dict
        self.assertFalse(self.manager.add_subscription("not a dict"))  # type: ignore

        # Missing endpoint
        self.assertFalse(self.manager.add_subscription({"keys": {"p256dh": "k", "auth": "a"}}))

        # Invalid endpoint scheme
        self.assertFalse(
            self.manager.add_subscription(
                {"endpoint": "ftp://invalid.com", "keys": {"p256dh": "k", "auth": "a"}}
            )
        )

        # Missing keys dict
        self.assertFalse(self.manager.add_subscription({"endpoint": "https://push.example.com/sub"}))

        # Missing p256dh or auth in keys
        self.assertFalse(
            self.manager.add_subscription(
                {"endpoint": "https://push.example.com/sub", "keys": {"auth": "a"}}
            )
        )
        self.assertFalse(
            self.manager.add_subscription(
                {"endpoint": "https://push.example.com/sub", "keys": {"p256dh": "k"}}
            )
        )

        self.assertEqual(len(self.manager.get_subscriptions()), 0)

    def test_subscription_deduplication_and_update(self) -> None:
        """Adding a subscription with an existing endpoint updates it without duplicating."""
        endpoint = "https://fcm.googleapis.com/fcm/send/duplicate_device"
        sub1 = {
            "endpoint": endpoint,
            "keys": {"p256dh": "key1", "auth": "auth1"},
        }
        sub2 = {
            "endpoint": endpoint,
            "keys": {"p256dh": "key2", "auth": "auth2"},
        }

        self.manager.add_subscription(sub1)
        self.assertEqual(len(self.manager.get_subscriptions()), 1)

        self.manager.add_subscription(sub2)
        subs = self.manager.get_subscriptions()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["keys"]["auth"], "auth2")

    def test_remove_subscription(self) -> None:
        """Removing existing subscription returns True; removing non-existent returns False."""
        endpoint = "https://fcm.googleapis.com/fcm/send/remove_device"
        sub = {"endpoint": endpoint, "keys": {"p256dh": "k", "auth": "a"}}
        self.manager.add_subscription(sub)
        self.assertEqual(len(self.manager.get_subscriptions()), 1)

        # Remove existing
        self.assertTrue(self.manager.remove_subscription(endpoint))
        self.assertEqual(len(self.manager.get_subscriptions()), 0)

        # Remove non-existent
        self.assertFalse(self.manager.remove_subscription(endpoint))
        self.assertFalse(self.manager.remove_subscription(""))

    def test_corrupted_subscriptions_file_recovery(self) -> None:
        """Manager handles corrupted push-subscriptions.json by resetting gracefully."""
        with open(self.subs_path, "w", encoding="utf-8") as f:
            f.write("CORRUPTED NOT JSON")

        mgr = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        self.assertEqual(len(mgr.get_subscriptions()), 0)

        # Adding new works fine
        mgr.add_subscription({"endpoint": "https://fcm.googleapis.com/sub", "keys": {"p256dh": "k", "auth": "a"}})
        self.assertEqual(len(mgr.get_subscriptions()), 1)

    def test_corrupted_dict_values_in_subscriptions_filtered(self) -> None:
        """Subscriptions file with non-dict or invalid values filters out bad entries."""
        corrupted_data = {
            "https://fcm.googleapis.com/valid": {
                "endpoint": "https://fcm.googleapis.com/valid",
                "keys": {"p256dh": "k1", "auth": "a1"},
            },
            "https://fcm.googleapis.com/invalid_str": "not_a_dict",
            "https://fcm.googleapis.com/invalid_int": 12345,
            "https://fcm.googleapis.com/missing_keys": {"endpoint": "https://fcm.googleapis.com/missing_keys"},
        }
        with open(self.subs_path, "w", encoding="utf-8") as f:
            json.dump(corrupted_data, f)

        mgr = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        subs = mgr.get_subscriptions()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["endpoint"], "https://fcm.googleapis.com/valid")


class TestClientVisibility(unittest.TestCase):
    """Tests multi-client visibility tracking, heartbeat timeouts, and suppression checks."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="vis_test_")
        self.manager = PushNotificationManager(
            config_path=os.path.join(self.temp_dir, "config.json"),
            subscriptions_path=os.path.join(self.temp_dir, "subs.json"),
            vapid_path=os.path.join(self.temp_dir, "vapid.json"),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_visibility_state_changes(self) -> None:
        """Client visibility toggles correctly between True and False."""
        self.assertFalse(self.manager.is_any_client_visible())

        self.manager.set_client_visibility("client-1", True)
        self.assertTrue(self.manager.is_any_client_visible())

        self.manager.set_client_visibility("client-1", False)
        self.assertFalse(self.manager.is_any_client_visible())

    def test_multi_client_visibility_aggregation(self) -> None:
        """If any one of multiple clients is visible, is_any_client_visible returns True."""
        self.manager.set_client_visibility("client-1", False)
        self.manager.set_client_visibility("client-2", False)
        self.assertFalse(self.manager.is_any_client_visible())

        self.manager.set_client_visibility("client-2", True)
        self.assertTrue(self.manager.is_any_client_visible())

        self.manager.set_client_visibility("client-2", False)
        self.assertFalse(self.manager.is_any_client_visible())

    def test_client_disconnect_removal(self) -> None:
        """Calling remove_client purges the client and updates visibility aggregation."""
        self.manager.set_client_visibility("client-1", True)
        self.assertTrue(self.manager.is_any_client_visible())

        self.manager.remove_client("client-1")
        self.assertFalse(self.manager.is_any_client_visible())

    def test_heartbeat_timeout_pruning(self) -> None:
        """Clients whose last heartbeat exceeds the timeout are cleaned up."""
        self.manager.set_client_visibility("stale-client", True)
        # Manually alter last_heartbeat to 40s ago
        self.manager.clients["stale-client"].last_heartbeat = time.time() - 40.0

        # With 30s timeout, stale client should be pruned and visibility should be False
        self.assertFalse(self.manager.is_any_client_visible(heartbeat_timeout=30.0))
        self.assertNotIn("stale-client", self.manager.clients)


class TestAttentionWatcher(unittest.IsolatedAsyncioTestCase):
    """Tests attention state transitions, deduplication, and notification triggers."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="att_test_")
        self.manager = PushNotificationManager(
            config_path=os.path.join(self.temp_dir, "config.json"),
            subscriptions_path=os.path.join(self.temp_dir, "subs.json"),
            vapid_path=os.path.join(self.temp_dir, "vapid.json"),
        )
        # Add a dummy subscription
        self.manager.add_subscription({
            "endpoint": "https://fcm.googleapis.com/fcm/send/device_1",
            "keys": {"p256dh": "test_p256dh", "auth": "test_auth"},
        })

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_startup_guard_prevents_false_alarm(self) -> None:
        """Initial check_and_send_attention_notifications call does not fire completion alert."""
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            # First tick: agent_running is False on initial startup
            sent = await self.manager.check_and_send_attention_notifications([], agent_running=False)
            self.assertEqual(sent, 0)
            mock_send.assert_not_called()

    async def test_agent_running_completion_transition(self) -> None:
        """Transitioning agent_running from True to False triggers task completed push."""
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            # Tick 1: Agent starts running
            await self.manager.check_and_send_attention_notifications([], agent_running=True)
            mock_send.assert_not_called()

            # Tick 2: Agent completes running
            sent = await self.manager.check_and_send_attention_notifications(
                [], agent_running=False, conversation_name="Build Task"
            )
            self.assertEqual(sent, 1)
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            self.assertEqual(kwargs.get("title") or args[0], "WahyuAI Remote")
            self.assertIn("Agent task completed", kwargs.get("body") or args[1])

    async def test_command_approval_attention_trigger(self) -> None:
        """Attention item with type='command' triggers Command approval push."""
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            items = [{"id": "item-cmd-1", "type": "command", "name": "npm test"}]
            sent = await self.manager.check_and_send_attention_notifications(items, agent_running=True)
            self.assertEqual(sent, 1)
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            body = kwargs.get("body") or args[1]
            self.assertIn("Command approval | npm test", body)

    async def test_question_attention_trigger(self) -> None:
        """Attention item with type='question' triggers Asking question push."""
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            items = [{"id": "item-q-1", "type": "question", "name": "Select environment"}]
            sent = await self.manager.check_and_send_attention_notifications(items, agent_running=True)
            self.assertEqual(sent, 1)
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            body = kwargs.get("body") or args[1]
            self.assertIn("Asking question | Select environment", body)

    async def test_attention_deduplication(self) -> None:
        """Consecutive ticks with the same unhandled item only send one push notification."""
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            items = [{"id": "item-1", "type": "command", "name": "run build"}]
            # Tick 1: sends push
            sent1 = await self.manager.check_and_send_attention_notifications(items, agent_running=True)
            self.assertEqual(sent1, 1)
            self.assertEqual(mock_send.call_count, 1)

            # Tick 2: duplicate item, should not send push
            sent2 = await self.manager.check_and_send_attention_notifications(items, agent_running=True)
            self.assertEqual(sent2, 0)
            self.assertEqual(mock_send.call_count, 1)

    async def test_attention_item_pruning_and_reactivation(self) -> None:
        """When an item leaves the attention list and reappears later, it alerts again."""
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            item = {"id": "item-repeat", "type": "command", "name": "Deploy"}
            # Tick 1: active item
            await self.manager.check_and_send_attention_notifications([item], agent_running=True)
            self.assertEqual(mock_send.call_count, 1)

            # Tick 2: item resolved (empty attention list)
            await self.manager.check_and_send_attention_notifications([], agent_running=True)
            self.assertNotIn("item-repeat:command", self.manager.notified_items)

            # Tick 3: new attention item with same ID
            await self.manager.check_and_send_attention_notifications([item], agent_running=True)
            self.assertEqual(mock_send.call_count, 2)

    async def test_visibility_suppression_and_foreground_registration(self) -> None:
        """
        When a client is visible:
        1. Push notification is suppressed (not sent over network).
        2. The item is still recorded in notified_items so backgrounding later does not fire.
        """
        self.manager.set_client_visibility("client-tab", True)
        self.assertTrue(self.manager.is_any_client_visible())

        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            item = {"id": "item-vis", "type": "question", "name": "Confirm Action"}
            sent = await self.manager.check_and_send_attention_notifications([item], agent_running=True)
            self.assertEqual(sent, 0)
            mock_send.assert_not_called()

            # Item must be in notified memory
            self.assertIn("item-vis:question", self.manager.notified_items)

            # Tab is now backgrounded
            self.manager.set_client_visibility("client-tab", False)
            self.assertFalse(self.manager.is_any_client_visible())

            # Next tick with same item: still NOT sent because already marked as seen
            sent2 = await self.manager.check_and_send_attention_notifications([item], agent_running=True)
            self.assertEqual(sent2, 0)
            mock_send.assert_not_called()

    async def test_pause_notifications(self) -> None:
        """When push_paused is True, no notifications are dispatched."""
        self.manager.set_push_paused(True)
        self.assertTrue(self.manager.is_push_paused())

        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            item = {"id": "item-p", "type": "command", "name": "test"}
            sent = await self.manager.check_and_send_attention_notifications([item], agent_running=True)
            self.assertEqual(sent, 0)
            mock_send.assert_not_called()

    async def test_double_completion_prevention_on_transition_and_completed_item(self) -> None:
        """
        When agent_running transitions True -> False and attention_items contains a
        'completed' item simultaneously, exactly one completion notification is fired.
        """
        # Start running
        await self.manager.check_and_send_attention_notifications([], agent_running=True)

        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            items = [{"id": "task-done", "type": "completed", "name": "Finished Task"}]
            sent = await self.manager.check_and_send_attention_notifications(
                items, agent_running=False, conversation_name="Finished Task", conversation_id="conv-1"
            )
            # Exactly 1 send call
            self.assertEqual(sent, 1)
            self.assertEqual(mock_send.call_count, 1)

    async def test_conversation_scoped_attention_deduplication(self) -> None:
        """
        Interleaved attention checks between multiple conversations do not thrash
        the deduplication cache or cause duplicate pushes.
        """
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            item1 = [{"id": "cmd-1", "type": "command", "name": "Build 1"}]
            item2 = [{"id": "cmd-2", "type": "command", "name": "Build 2"}]

            # Tick 1: conv1 alert
            s1 = await self.manager.check_and_send_attention_notifications(item1, agent_running=True, conversation_id="conv1")
            self.assertEqual(s1, 1)
            self.assertEqual(mock_send.call_count, 1)

            # Tick 2: conv2 alert
            s2 = await self.manager.check_and_send_attention_notifications(item2, agent_running=True, conversation_id="conv2")
            self.assertEqual(s2, 1)
            self.assertEqual(mock_send.call_count, 2)

            # Tick 3: conv1 still active and unhandled -> deduplicated, sends 0!
            s3 = await self.manager.check_and_send_attention_notifications(item1, agent_running=True, conversation_id="conv1")
            self.assertEqual(s3, 0)
            self.assertEqual(mock_send.call_count, 2)

    async def test_attention_non_dict_items_ignored_safely(self) -> None:
        """Non-dict and None elements in attention_items are filtered out without exceptions."""
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            malformed_items = [None, "invalid", 12345, {"id": "valid", "type": "command", "name": "Run"}]
            sent = await self.manager.check_and_send_attention_notifications(
                malformed_items, agent_running=True, conversation_id="conv-safe"  # type: ignore
            )
            self.assertEqual(sent, 1)
            self.assertEqual(mock_send.call_count, 1)


class TestWebPushDispatcher(unittest.IsolatedAsyncioTestCase):
    """Tests pywebpush integration, async dispatching, and WebPushException error handling."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="push_disp_test_")
        self.manager = PushNotificationManager(
            config_path=os.path.join(self.temp_dir, "config.json"),
            subscriptions_path=os.path.join(self.temp_dir, "subs.json"),
            vapid_path=os.path.join(self.temp_dir, "vapid.json"),
        )
        self.mock_push = MockPushService()
        self.mock_push.patch()

    async def asyncTearDown(self) -> None:
        self.mock_push.unpatch()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_successful_webpush_dispatch(self) -> None:
        """Dispatches valid WebPush payload to all subscribers in parallel."""
        sub1 = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/sub_1",
            "keys": {"p256dh": "key1", "auth": "auth1"},
        }
        sub2 = {
            "endpoint": "https://updates.push.services.mozilla.com/wpush/v2/sub_2",
            "keys": {"p256dh": "key2", "auth": "auth2"},
        }
        self.manager.add_subscription(sub1)
        self.manager.add_subscription(sub2)

        delivered = await self.manager.send_notification(
            title="Antigravity Alert",
            body="Task finished",
            data={"conversationId": "c-123", "url": "/?conv=c-123"},
        )

        self.assertEqual(delivered, 2)
        self.assertEqual(len(self.mock_push.sent_notifications), 2)

        # Validate recorded payload
        rec = self.mock_push.sent_notifications[0]
        assert_push_payload_valid(rec["payload_json"])
        self.assertEqual(rec["payload_json"]["title"], "Antigravity Alert")
        self.assertEqual(rec["payload_json"]["body"], "Task finished")
        self.assertEqual(rec["payload_json"]["data"]["conversationId"], "c-123")

    async def test_auto_prune_on_410_gone(self) -> None:
        """When push service returns HTTP 410 Gone, subscription is automatically pruned."""
        endpoint = "https://fcm.googleapis.com/fcm/send/expired_sub"
        self.manager.add_subscription({
            "endpoint": endpoint,
            "keys": {"p256dh": "k", "auth": "a"},
        })
        self.assertEqual(len(self.manager.get_subscriptions()), 1)

        # Configure mock to return 410 Gone for this endpoint
        self.mock_push.set_endpoint_status(endpoint, 410)

        delivered = await self.manager.send_notification("Test", "Expired Alert")
        self.assertEqual(delivered, 0)

        # Subscription must be pruned from memory and disk
        self.assertEqual(len(self.manager.get_subscriptions()), 0)
        with open(self.manager.subscriptions_path, "r", encoding="utf-8") as f:
            disk_subs = json.load(f)
            self.assertNotIn(endpoint, disk_subs)

    async def test_auto_prune_on_404_not_found(self) -> None:
        """When push service returns HTTP 404 Not Found, subscription is automatically pruned."""
        endpoint = "https://fcm.googleapis.com/fcm/send/not_found_sub"
        self.manager.add_subscription({
            "endpoint": endpoint,
            "keys": {"p256dh": "k", "auth": "a"},
        })
        self.mock_push.set_endpoint_status(endpoint, 404)

        delivered = await self.manager.send_notification("Test", "404 Alert")
        self.assertEqual(delivered, 0)
        self.assertEqual(len(self.manager.get_subscriptions()), 0)

    async def test_transient_error_retention_429_and_500(self) -> None:
        """HTTP 429 Too Many Requests or 500 Server Errors do NOT prune subscriptions."""
        ep_429 = "https://fcm.googleapis.com/fcm/send/rate_limited"
        ep_500 = "https://fcm.googleapis.com/fcm/send/server_error"
        self.manager.add_subscription({"endpoint": ep_429, "keys": {"p256dh": "k1", "auth": "a1"}})
        self.manager.add_subscription({"endpoint": ep_500, "keys": {"p256dh": "k2", "auth": "a2"}})

        self.mock_push.set_endpoint_status(ep_429, 429)
        self.mock_push.set_endpoint_status(ep_500, 500)

        delivered = await self.manager.send_notification("Test", "Transient Alert")
        self.assertEqual(delivered, 0)

        # Both subscriptions must be retained
        self.assertEqual(len(self.manager.get_subscriptions()), 2)

    async def test_network_exception_retention(self) -> None:
        """Network/Connection exceptions do NOT prune subscriptions."""
        ep = "https://fcm.googleapis.com/fcm/send/net_err"
        self.manager.add_subscription({"endpoint": ep, "keys": {"p256dh": "k", "auth": "a"}})

        self.mock_push.set_exception(ConnectionError("DNS resolution failed"))

        delivered = await self.manager.send_notification("Test", "Net Alert")
        self.assertEqual(delivered, 0)
        self.assertEqual(len(self.manager.get_subscriptions()), 1)

    async def test_send_notification_empty_subscriptions(self) -> None:
        """Sending notification with zero subscriptions returns 0 immediately."""
        self.assertEqual(len(self.manager.get_subscriptions()), 0)
        delivered = await self.manager.send_notification("Title", "Body")
        self.assertEqual(delivered, 0)
        self.assertEqual(len(self.mock_push.sent_notifications), 0)


class TestPushEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Tests additional edge cases and boundary conditions."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="edge_test_")
        self.manager = PushNotificationManager(
            config_path=os.path.join(self.temp_dir, "config.json"),
            subscriptions_path=os.path.join(self.temp_dir, "subs.json"),
            vapid_path=os.path.join(self.temp_dir, "vapid.json"),
        )
        self.mock_push = MockPushService()
        self.mock_push.patch()

    async def asyncTearDown(self) -> None:
        self.mock_push.unpatch()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_subscriptions_from_list_format(self) -> None:
        """Supports loading subscriptions saved as a list of dicts or list of tuples."""
        list_data = [
            {"endpoint": "https://fcm.googleapis.com/sub1", "keys": {"p256dh": "k1", "auth": "a1"}},
            {"endpoint": "https://fcm.googleapis.com/sub2", "keys": {"p256dh": "k2", "auth": "a2"}},
        ]
        with open(self.manager.subscriptions_path, "w", encoding="utf-8") as f:
            json.dump(list_data, f)

        mgr = PushNotificationManager(
            config_path=os.path.join(self.temp_dir, "config.json"),
            subscriptions_path=self.manager.subscriptions_path,
            vapid_path=os.path.join(self.temp_dir, "vapid.json"),
        )
        self.assertEqual(len(mgr.get_subscriptions()), 2)
        self.assertIn("https://fcm.googleapis.com/sub1", mgr.subscriptions)

    def test_cleanup_stale_clients_partial(self) -> None:
        """cleanup_stale_clients prunes only expired clients and returns correct count."""
        now = time.time()
        self.manager.clients["active-1"] = ClientVisibilityState("active-1", True, now - 5.0)
        self.manager.clients["stale-1"] = ClientVisibilityState("stale-1", True, now - 35.0)
        self.manager.clients["stale-2"] = ClientVisibilityState("stale-2", False, now - 45.0)

        cleaned = self.manager.cleanup_stale_clients(timeout_seconds=30.0)
        self.assertEqual(cleaned, 2)
        self.assertEqual(len(self.manager.clients), 1)
        self.assertIn("active-1", self.manager.clients)
        self.assertTrue(self.manager.is_any_client_visible())

    async def test_completed_attention_item_trigger(self) -> None:
        """Attention item with type='completed' triggers task completion alert."""
        self.manager.add_subscription({"endpoint": "https://fcm.googleapis.com/sub1", "keys": {"p256dh": "k", "auth": "a"}})
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            items = [{"id": "comp-1", "type": "completed", "name": "Refactor Module"}]
            sent = await self.manager.check_and_send_attention_notifications(items, agent_running=False)
            self.assertEqual(sent, 1)
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            body = kwargs.get("body") or args[1]
            self.assertIn("Agent task completed | Refactor Module", body)

    async def test_attention_item_without_id(self) -> None:
        """Attention item without explicit id uses fallback and still deduplicates."""
        self.manager.add_subscription({"endpoint": "https://fcm.googleapis.com/sub1", "keys": {"p256dh": "k", "auth": "a"}})
        with patch.object(self.manager, "send_notification", return_value=1) as mock_send:
            items = [{"type": "command", "name": "Run script"}]
            sent1 = await self.manager.check_and_send_attention_notifications(items, agent_running=True, conversation_id="fallback-conv")
            self.assertEqual(sent1, 1)

            # Second call should dedup
            sent2 = await self.manager.check_and_send_attention_notifications(items, agent_running=True, conversation_id="fallback-conv")
            self.assertEqual(sent2, 0)


class TestExtractStatusCode(unittest.TestCase):
    """Tests _extract_status_code helper across diverse exception structures."""

    def test_extract_from_response_object(self) -> None:
        class FakeResponse:
            status_code = 410

        class FakeEx(Exception):
            response = FakeResponse()

        self.assertEqual(_extract_status_code(FakeEx()), 410)

    def test_extract_from_camelcase_status_code(self) -> None:
        class FakeResponse:
            statusCode = 404

        class FakeEx(Exception):
            response = FakeResponse()

        self.assertEqual(_extract_status_code(FakeEx()), 404)

    def test_extract_from_integer_response(self) -> None:
        class FakeEx(Exception):
            response = 429

        self.assertEqual(_extract_status_code(FakeEx()), 429)

    def test_extract_from_direct_attribute(self) -> None:
        class FakeEx(Exception):
            status_code = 500

        self.assertEqual(_extract_status_code(FakeEx()), 500)

    def test_extract_from_none(self) -> None:
        self.assertIsNone(_extract_status_code(ValueError("general error")))


if __name__ == "__main__":
    unittest.main()

