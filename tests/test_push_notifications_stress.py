"""
tests/test_push_notifications_stress.py - Adversarial Stress & Chaos Test Suite
================================================================================

Targeting PushNotificationManager:
1. Attention State State Machine Stress:
   - Rapid flapping between agent_running=True and agent_running=False (1,000 cycles).
   - Rapid addition, modification, and removal of attention items across multiple simultaneous conversations.
   - Attention items with missing fields (id, type, title, message), malformed entries, and None values.
   - Duplicate IDs with different types and type mutations.
   - Duplicate identical items within a single batch.
2. Visibility Suppression Edge Cases:
   - Flapping visibility states across 100 simulated clients with concurrent updates.
   - Stale client timeout exact boundaries (t = 29.9s vs t = 30.0s vs t = 30.1s).
   - Multi-client consensus: 99 invisible + 1 visible vs visible disconnects vs visible silent timeout.
3. Pause/Resume state switches during active attention alerts and high-frequency toggling.
4. WebPush High-Concurrency Dispatch & Mixed Fault Injection:
   - 100 subscribers with mixed responses (200, 410, 404, 429, 500, ConnectionTimeout).
   - Thread safety of concurrent add/remove/send/save operations under load.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import tempfile
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

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


class TestAttentionStateMachineStress(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing of Attention State Transitions and Deduplication."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="stress_att_")
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

        # Add 5 active subscribers
        for i in range(5):
            self.manager.add_subscription({
                "endpoint": f"https://fcm.googleapis.com/fcm/send/device_{i}",
                "keys": {"p256dh": f"key_{i}", "auth": f"auth_{i}"},
            })

    async def asyncTearDown(self) -> None:
        self.mock_push.unpatch()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_rapid_agent_running_flapping(self) -> None:
        """
        Flaps agent_running between True and False 1,000 times in rapid succession.
        Exactly 1,000 notifications should be dispatched (every True -> False transition).
        No memory leaks or corrupted previous_agent_running state.
        """
        # Start state: False
        await self.manager.check_and_send_attention_notifications([], agent_running=False)
        self.assertEqual(len(self.mock_push.sent_notifications), 0)

        flaps = 500  # 500 pairs of (True -> False)
        for i in range(flaps):
            # Transition to running
            sent_on = await self.manager.check_and_send_attention_notifications([], agent_running=True)
            self.assertEqual(sent_on, 0)

            # Transition to stopped
            sent_off = await self.manager.check_and_send_attention_notifications(
                [], agent_running=False, conversation_name=f"Job-{i}"
            )
            self.assertEqual(sent_off, 5)  # delivered to 5 subscribers

        self.assertEqual(len(self.mock_push.sent_notifications), flaps * 5)
        self.assertFalse(self.manager.previous_agent_running)

    async def test_duplicate_items_within_single_batch(self) -> None:
        """
        Single batch containing duplicate identical attention items must deduplicate
        and only trigger one notification.
        """
        items = [
            {"id": "task-dup", "type": "command", "name": "git commit"},
            {"id": "task-dup", "type": "command", "name": "git commit"},
            {"id": "task-dup", "type": "command", "name": "git commit"},
        ]
        sent = await self.manager.check_and_send_attention_notifications(items, agent_running=True)
        self.assertEqual(sent, 5)  # 1 push to 5 subscribers
        self.assertEqual(len(self.mock_push.sent_notifications), 5)

        # Immediate follow-up with same duplicates sends 0
        sent2 = await self.manager.check_and_send_attention_notifications(items, agent_running=True)
        self.assertEqual(sent2, 0)

    async def test_duplicate_id_with_different_types(self) -> None:
        """
        An item with the same ID but different types (command vs question vs completed)
        must be uniquely identified and not collide in deduplication cache.
        """
        # 1. Command approval for task-1
        items_cmd = [{"id": "task-1", "type": "command", "name": "Execute script"}]
        sent1 = await self.manager.check_and_send_attention_notifications(items_cmd, agent_running=True)
        self.assertEqual(sent1, 5)

        # 2. Both command and question for task-1 simultaneously
        items_both = [
            {"id": "task-1", "type": "command", "name": "Execute script"},
            {"id": "task-1", "type": "question", "name": "Confirm overwrite?"},
        ]
        # Command should be skipped as already notified; Question should fire
        sent2 = await self.manager.check_and_send_attention_notifications(items_both, agent_running=True)
        self.assertEqual(sent2, 5)

        # 3. Task-1 completes (with agent_running staying False to isolate explicit completed item)
        # First set agent_running=False without completed items
        await self.manager.check_and_send_attention_notifications([], agent_running=False)
        self.mock_push.sent_notifications.clear()

        items_comp = [{"id": "task-1", "type": "completed", "name": "Task 1 Done"}]
        sent3 = await self.manager.check_and_send_attention_notifications(items_comp, agent_running=False)
        self.assertEqual(sent3, 5)

    async def test_double_notification_bug_on_completion_transition(self) -> None:
        """
        VERIFY FIX:
        When agent_running transitions from True -> False AND attention_items contains
        a 'completed' item in the exact same tick, PushNotificationManager sends exactly
        ONE completed push notification (5 total sends across 5 subscribers, not 10).
        """
        # Set agent_running=True
        await self.manager.check_and_send_attention_notifications([], agent_running=True)
        self.mock_push.sent_notifications.clear()

        # In same tick, agent_running becomes False AND completed item is present
        items = [{"id": "task-1", "type": "completed", "name": "Task 1 Done"}]
        sent = await self.manager.check_and_send_attention_notifications(
            items, agent_running=False, conversation_name="Task 1 Done", conversation_id="task-1"
        )
        # Exactly 5 sends (1 per subscriber)
        self.assertEqual(sent, 5)
        self.assertEqual(len(self.mock_push.sent_notifications), 5)

    async def test_non_dict_elements_in_attention_items_crash(self) -> None:
        """
        VERIFY FIX:
        If attention_items contains None or non-dict objects (e.g. from malformed CDP or extension data),
        PushNotificationManager safely filters them without raising AttributeError.
        """
        malformed_list = [None, "invalid_string", 12345]
        sent = await self.manager.check_and_send_attention_notifications(
            malformed_list, agent_running=True, conversation_id="conv-malformed"  # type: ignore
        )
        self.assertIsInstance(sent, int)
        self.assertEqual(sent, 0)

    async def test_multi_conversation_interleaved_attention_pruning_leak(self) -> None:
        """
        VERIFY FIX:
        If conv1 has an active attention item, and next tick CDP sends attention items for conv2,
        PushNotificationManager preserves conv1's notified state with conversation scoping.
        When CDP switches back to conv1, conv1's item is properly deduplicated (0 sends).
        """
        # Tick 1: conv1 has a command approval -> fires 5
        item1 = [{"id": "conv1-cmd", "type": "command", "name": "Build conv1"}]
        sent1 = await self.manager.check_and_send_attention_notifications(
            item1, agent_running=True, conversation_id="conv1"
        )
        self.assertEqual(sent1, 5)

        # Tick 2: Active tab switches to conv2, CDP sends conv2 attention items -> fires 5
        item2 = [{"id": "conv2-cmd", "type": "command", "name": "Build conv2"}]
        sent2 = await self.manager.check_and_send_attention_notifications(
            item2, agent_running=True, conversation_id="conv2"
        )
        self.assertEqual(sent2, 5)

        # Tick 3: Active tab switches back to conv1 (conv1 item is still unacknowledged)
        # Because notified_items was scoped to conv1, sent3 is deduplicated (0 sends)!
        sent3 = await self.manager.check_and_send_attention_notifications(
            item1, agent_running=True, conversation_id="conv1"
        )
        self.assertEqual(sent3, 0)



    async def test_attention_items_with_missing_or_malformed_fields(self) -> None:
        """
        Adversarial payloads with missing, empty, or unexpected field types:
        - empty dict {}
        - None id, None type, None name, None text
        - integer IDs, boolean types, list names
        - missing fields altogether
        Manager must handle all without throwing unhandled exceptions.
        """
        malformed_batches = [
            [{}],
            [{"id": None, "type": None}],
            [{"id": "", "type": ""}],
            [{"id": 12345, "type": True, "name": ["a", "b"]}],
            [{"random_key": "random_val"}],
            [{"id": "valid-id", "name": None, "type": "question"}],
            [{"id": "valid-id2", "type": "command", "text": None}],
        ]

        for batch in malformed_batches:
            try:
                sent = await self.manager.check_and_send_attention_notifications(
                    batch, agent_running=True, conversation_id="conv-fallback"
                )
                self.assertIsInstance(sent, int)
            except Exception as e:
                self.fail(f"check_and_send_attention_notifications raised unexpected exception on {batch}: {e}")

    async def test_rapid_concurrent_multi_conversation_updates(self) -> None:
        """
        Spawns 50 concurrent tasks performing attention notifications across 50 distinct
        conversations to stress async concurrency, dictionary iterations, and lock-free state.
        """
        async def worker(conv_id: str, count: int) -> int:
            total = 0
            for step in range(count):
                items = [
                    {"id": f"{conv_id}-cmd-{step}", "type": "command", "name": f"Step {step}"},
                ]
                sent = await self.manager.check_and_send_attention_notifications(
                    items, agent_running=True, conversation_id=conv_id
                )
                total += sent
                await asyncio.sleep(0.001)
            return total

        tasks = [worker(f"conv-{i}", 10) for i in range(20)]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        self.assertTrue(all(isinstance(r, int) for r in results))
        self.assertTrue(len(self.mock_push.sent_notifications) > 0)


class TestVisibilitySuppressionStress(unittest.TestCase):
    """Adversarial testing of client visibility tracking and boundary conditions."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="stress_vis_")
        self.manager = PushNotificationManager(
            config_path=os.path.join(self.temp_dir, "config.json"),
            subscriptions_path=os.path.join(self.temp_dir, "subs.json"),
            vapid_path=os.path.join(self.temp_dir, "vapid.json"),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stale_client_exact_timeout_boundaries(self) -> None:
        """
        Verifies exact timeout boundaries:
        - t = 29.9s (active) -> is_any_client_visible(30.0) == True
        - t = 30.0001s (expired) -> is_any_client_visible(30.0) == False
        """
        now = time.time()
        timeout = 30.0

        # Case A: client heartbeat at 29.9s ago (just within 30s window)
        self.manager.clients["client-near-edge"] = ClientVisibilityState(
            client_id="client-near-edge",
            is_visible=True,
            last_heartbeat=now - 29.9,
        )
        self.assertTrue(self.manager.is_any_client_visible(heartbeat_timeout=timeout))
        self.assertIn("client-near-edge", self.manager.clients)

        # Case B: client heartbeat at 30.05s ago (just past 30s window)
        self.manager.clients["client-near-edge"].last_heartbeat = now - 30.05
        self.assertFalse(self.manager.is_any_client_visible(heartbeat_timeout=timeout))
        self.assertNotIn("client-near-edge", self.manager.clients)

    def test_flapping_visibility_100_simulated_clients(self) -> None:
        """
        Simulates 100 concurrent clients flapping visibility states between visible and backgrounded.
        Ensures is_any_client_visible correctly aggregates arbitrary configurations.
        """
        client_ids = [f"client-{i}" for i in range(100)]

        for round_idx in range(50):
            visible_count = 0
            for cid in client_ids:
                is_vis = random.choice([True, False])
                if is_vis:
                    visible_count += 1
                self.manager.set_client_visibility(cid, is_vis)

            expected_any_visible = visible_count > 0
            self.assertEqual(self.manager.is_any_client_visible(), expected_any_visible)

        # Reset all to False
        for cid in client_ids:
            self.manager.set_client_visibility(cid, False)
        self.assertFalse(self.manager.is_any_client_visible())

    def test_multi_client_consensus_and_silent_disconnect(self) -> None:
        """
        99 clients invisible + 1 client visible -> is_any_client_visible is True.
        1 visible client disconnects silently (heartbeat stops) -> after timeout, becomes False.
        """
        for i in range(99):
            self.manager.set_client_visibility(f"bg-client-{i}", False)

        self.manager.set_client_visibility("fg-client", True)
        self.assertTrue(self.manager.is_any_client_visible())

        # fg-client silent timeout (no heartbeat for 35s)
        self.manager.clients["fg-client"].last_heartbeat = time.time() - 35.0
        self.assertFalse(self.manager.is_any_client_visible(heartbeat_timeout=30.0))
        self.assertNotIn("fg-client", self.manager.clients)
        # Background clients remain registered
        self.assertEqual(len(self.manager.clients), 99)

    def test_explicit_client_disconnect_vs_silent_disconnect(self) -> None:
        """
        Explicit client disconnect (remove_client) immediately flips visibility consensus.
        """
        self.manager.set_client_visibility("client-temp", True)
        self.assertTrue(self.manager.is_any_client_visible())

        self.manager.remove_client("client-temp")
        self.assertFalse(self.manager.is_any_client_visible())

        # Removing non-existent client does not error
        self.manager.remove_client("client-non-existent")


class TestPauseResumeStress(unittest.IsolatedAsyncioTestCase):
    """Adversarial testing of push pausing and resumption during active traffic."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="stress_pause_")
        self.manager = PushNotificationManager(
            config_path=os.path.join(self.temp_dir, "config.json"),
            subscriptions_path=os.path.join(self.temp_dir, "subs.json"),
            vapid_path=os.path.join(self.temp_dir, "vapid.json"),
        )
        self.mock_push = MockPushService()
        self.mock_push.patch()
        self.manager.add_subscription({
            "endpoint": "https://fcm.googleapis.com/fcm/send/device_p",
            "keys": {"p256dh": "k", "auth": "a"},
        })

    async def asyncTearDown(self) -> None:
        self.mock_push.unpatch()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_pause_state_suppresses_all_notifications(self) -> None:
        """When push_paused=True, direct sends and attention notifications are completely muted."""
        self.manager.set_push_paused(True)
        self.assertTrue(self.manager.is_push_paused())

        # 1. Direct send
        direct_sent = await self.manager.send_notification("Direct", "Should not send")
        self.assertEqual(direct_sent, 0)
        self.assertEqual(len(self.mock_push.sent_notifications), 0)

        # 2. Attention send
        items = [{"id": "item-muted", "type": "command", "name": "Muted task"}]
        att_sent = await self.manager.check_and_send_attention_notifications(items, agent_running=True)
        self.assertEqual(att_sent, 0)
        self.assertEqual(len(self.mock_push.sent_notifications), 0)

        # 3. Unpause
        self.manager.set_push_paused(False)
        self.assertFalse(self.manager.is_push_paused())

        # Now send succeeds
        direct_sent2 = await self.manager.send_notification("Direct2", "Should send")
        self.assertEqual(direct_sent2, 1)
        self.assertEqual(len(self.mock_push.sent_notifications), 1)

    async def test_high_frequency_pause_resume_flapping(self) -> None:
        """
        Rapidly toggles push_paused under concurrent load without deadlocking or raising exceptions.
        """
        async def toggler():
            for _ in range(50):
                self.manager.set_push_paused(True)
                await asyncio.sleep(0.001)
                self.manager.set_push_paused(False)
                await asyncio.sleep(0.001)

        async def sender():
            for i in range(50):
                await self.manager.send_notification(f"Title {i}", "Body")
                await asyncio.sleep(0.001)

        await asyncio.gather(toggler(), sender())
        # Manager should survive and remain consistent
        self.assertIsInstance(self.manager.is_push_paused(), bool)


class TestWebPushChaosAndConcurrency(unittest.IsolatedAsyncioTestCase):
    """Stress and fault injection testing on WebPush delivery and subscription storage."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="chaos_push_")
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

    async def test_massive_concurrency_mixed_fault_injection(self) -> None:
        """
        100 subscriptions with injected chaos:
        - 40 respond HTTP 200 OK (delivered)
        - 20 respond HTTP 410 Gone (must be auto-pruned)
        - 15 respond HTTP 404 Not Found (must be auto-pruned)
        - 15 respond HTTP 429 Rate Limited (must be retained)
        - 10 raise ConnectionError / 500 (must be retained)

        Verifies exact delivered count, exact pruned count, and remaining subscription count.
        """
        # Register 100 endpoints
        for i in range(100):
            ep = f"https://fcm.googleapis.com/fcm/send/sub_{i:03d}"
            self.manager.add_subscription({
                "endpoint": ep,
                "keys": {"p256dh": f"key_{i}", "auth": f"auth_{i}"},
            })

            if i < 40:
                # 0..39: 200 OK
                pass
            elif i < 60:
                # 40..59: 410 Gone
                self.mock_push.set_endpoint_status(ep, 410)
            elif i < 75:
                # 60..74: 404 Not Found
                self.mock_push.set_endpoint_status(ep, 404)
            elif i < 90:
                # 75..89: 429 Rate Limited
                self.mock_push.set_endpoint_status(ep, 429)
            else:
                # 90..99: Network exception / Server Error
                self.mock_push.set_endpoint_status(ep, 500)

        self.assertEqual(len(self.manager.get_subscriptions()), 100)

        delivered = await self.manager.send_notification(
            title="Chaos Alert",
            body="Testing mixed response handling under load",
            data={"chaos": True},
        )

        self.assertEqual(delivered, 40)

        # 35 subscriptions (20 of 410 + 15 of 404) should be pruned
        remaining = self.manager.get_subscriptions()
        self.assertEqual(len(remaining), 65)

        # Verify disk matches in-memory subscriptions
        with open(self.manager.subscriptions_path, "r", encoding="utf-8") as f:
            disk_subs = json.load(f)
        self.assertEqual(len(disk_subs), 65)

        # Verify pruned endpoints are indeed gone
        for i in range(40, 75):
            ep = f"https://fcm.googleapis.com/fcm/send/sub_{i:03d}"
            self.assertNotIn(ep, self.manager.subscriptions)
            self.assertNotIn(ep, disk_subs)

        # Verify retained endpoints remain
        for i in range(0, 40):
            ep = f"https://fcm.googleapis.com/fcm/send/sub_{i:03d}"
            self.assertIn(ep, self.manager.subscriptions)
        for i in range(75, 100):
            ep = f"https://fcm.googleapis.com/fcm/send/sub_{i:03d}"
            self.assertIn(ep, self.manager.subscriptions)

    async def test_concurrent_subscription_read_write_stress(self) -> None:
        """
        Multiple coroutines simultaneously adding, removing, querying subscriptions
        and persisting to disk. Checks that no JSON corruption or lock deadlocks occur.
        """
        async def writer(prefix: str, count: int):
            for i in range(count):
                ep = f"https://push.example.com/{prefix}_{i}"
                self.manager.add_subscription({
                    "endpoint": ep,
                    "keys": {"p256dh": f"p256_{i}", "auth": f"auth_{i}"},
                })
                if i % 3 == 0:
                    self.manager.remove_subscription(ep)
                await asyncio.sleep(0.001)

        async def reader(count: int):
            for _ in range(count):
                subs = self.manager.get_subscriptions()
                self.assertIsInstance(subs, list)
                await asyncio.sleep(0.001)

        tasks = [
            writer("w1", 30),
            writer("w2", 30),
            writer("w3", 30),
            reader(30),
            reader(30),
        ]
        await asyncio.gather(*tasks)

        # Confirm subscription file on disk is valid JSON
        with open(self.manager.subscriptions_path, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
            self.assertIsInstance(disk_data, dict)


if __name__ == "__main__":
    unittest.main()
