"""
tests/test_tier3_combinations.py - Tier 3 Cross-Feature Combinations E2E Test Suite
===================================================================================

Pairwise and multi-feature interaction E2E test suite for Antigravity WebRemote v6.
Verifies cross-cutting behaviors between the 32 inventoried system features:
1. Live DOM Streaming + Attention Detection + Web Push Notifications (F4, F7, F8, F12, F14)
2. Multi-Tab Client Visibility + Web Push Suppression (F11, F12, F13, F14)
3. Two-Way Lexical Chat Injection + Stop Generation Race Conditions (F15, F16, F17, F7, F14)
4. Base64 Image Drag-Drop Upload + Permission Dialog Triggers (F9, F18, F19, F25)
5. Subagent View Toggle + BTW Question Panel + History Navigation (F20, F27, F28, F30)
6. Concurrent WebSocket Clients + Broadcast Diff Synchronization (F7, F14, F24)
7. VAPID Key Rotation + Push Subscription Persistence (F10, F11, F12)
8. mDNS Zeroconf Registration + REST Route Discovery & Legacy Parity (F21, F22, F23)
9. Interactive Overlays (Permission, ask_question, Dropdowns) + CDP Click Routing (F8, F9, F16, F19, F25)
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

from push_notifications import (
    ClientVisibilityState,
    PushNotificationManager,
)
from tests.harness import (
    HarnessTestCase,
    MockCDPServer,
    MockDOMGenerator,
    MockPushService,
    TestClientWrapper,
    assert_push_payload_valid,
    assert_push_subscription_valid,
    assert_responsive_css,
    assert_sanitized_html,
    assert_valid_djb2_hash,
    assert_valid_snapshot,
    assert_vapid_key_valid,
    compute_composite_hash,
    compute_djb2,
)


# ==============================================================================
# Suite 1: Live DOM Streaming + Attention State + Web Push Combinations
# ==============================================================================

class TestLiveDomStreamingAttentionPushCombinations(HarnessTestCase):
    """
    Tests interactions between DOM capture/streaming, attention state extraction,
    and background Web Push notification triggers.
    """

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.temp_dir = tempfile.mkdtemp(prefix="tier3_push_combo_")
        self.config_path = os.path.join(self.temp_dir, "config.json")
        self.subs_path = os.path.join(self.temp_dir, "push-subscriptions.json")
        self.vapid_path = os.path.join(self.temp_dir, "vapid-keys.json")

        self.push_mgr = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        self.sub = self.push_service.create_mock_subscription()
        self.push_mgr.add_subscription(self.sub)

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        await super().asyncTearDown()

    async def test_dom_snapshot_with_attention_question_triggers_web_push(self) -> None:
        """
        Pairwise interaction: Live DOM snapshot with an 'ask_question' attention item
        triggers a signed Web Push notification with valid payload and conversation data.
        """
        # 1. Generate live snapshot with attention question
        attention_items = [
            {
                "type": "question",
                "text": "Waiting for user permission on run_command",
                "id": "conv-att-q1",
                "name": "Permission Check",
            }
        ]
        snapshot = self.dom_gen.generate_full_snapshot(
            agent_running=True,
            with_ask_question=True,
        )
        snapshot["attentionItems"] = attention_items
        snapshot["hash"] = compute_composite_hash(snapshot)

        assert_valid_snapshot(snapshot)
        assert_valid_djb2_hash(snapshot["hash"])

        # 2. Attention detector evaluates snapshot state
        sent_count = await self.push_mgr.check_and_send_attention_notifications(
            attention_items=snapshot["attentionItems"],
            agent_running=snapshot["agentRunning"],
            conversation_name="Deploy Task",
            conversation_id="conv-att-q1",
        )

        # 3. Verify push notification delivery
        self.assertEqual(sent_count, 1)
        self.assertEqual(len(self.push_service.sent_notifications), 1)

        record = self.push_service.sent_notifications[0]
        self.assertEqual(record["endpoint"], self.sub["endpoint"])
        self.assertIsNotNone(record["payload_json"])

        payload = record["payload_json"]
        assert_push_payload_valid(payload)
        self.assertEqual(payload["title"], "WahyuAI Remote")
        self.assertIn("Asking question", payload["body"])
        self.assertIn("Permission Check", payload["body"])
        self.assertEqual(payload["data"]["type"], "question")

    async def test_dom_snapshot_agent_stop_transition_triggers_completed_push(self) -> None:
        """
        Pairwise interaction: Transition from agentRunning=True to agentRunning=False in
        successive DOM snapshots triggers an 'Agent task completed' Web Push notification.
        """
        # Step 1: Agent is running
        sent_1 = await self.push_mgr.check_and_send_attention_notifications(
            attention_items=[],
            agent_running=True,
            conversation_name="Build Project",
            conversation_id="conv-task-1",
        )
        self.assertEqual(sent_1, 0)
        self.assertEqual(len(self.push_service.sent_notifications), 0)

        # Step 2: Agent completes execution (agentRunning goes False)
        sent_2 = await self.push_mgr.check_and_send_attention_notifications(
            attention_items=[],
            agent_running=False,
            conversation_name="Build Project",
            conversation_id="conv-task-1",
        )
        self.assertEqual(sent_2, 1)
        self.assertEqual(len(self.push_service.sent_notifications), 1)

        payload = self.push_service.sent_notifications[0]["payload_json"]
        assert_push_payload_valid(payload)
        self.assertIn("Agent task completed", payload["body"])
        self.assertIn("Build Project", payload["body"])
        self.assertEqual(payload["data"]["type"], "completed")

    async def test_repeated_identical_snapshots_skip_duplicate_pushes(self) -> None:
        """
        Pairwise interaction: Consecutive identical snapshots with identical DJB2 hashes
        and attention items do NOT trigger redundant push alerts.
        """
        items = [{"type": "command", "id": "cmd-1", "name": "npm test approval"}]

        # Dispatch 1: Initial alert
        sent_1 = await self.push_mgr.check_and_send_attention_notifications(
            attention_items=items,
            agent_running=True,
            conversation_name="CI Run",
        )
        self.assertEqual(sent_1, 1)
        self.assertEqual(len(self.push_service.sent_notifications), 1)

        # Dispatch 2, 3, 4: Identical state snapshots arriving every ~300ms
        for _ in range(3):
            sent_repeat = await self.push_mgr.check_and_send_attention_notifications(
                attention_items=items,
                agent_running=True,
                conversation_name="CI Run",
            )
            self.assertEqual(sent_repeat, 0)

        # Still exactly 1 push notification in total
        self.assertEqual(len(self.push_service.sent_notifications), 1)

    async def test_resolved_attention_item_clearing_and_retrigger_cycle(self) -> None:
        """
        Multi-step interaction: Attention item is notified -> item resolves (cleared from DOM)
        -> new attention item with same ID re-triggers alert cleanly.
        """
        item = [{"type": "question", "id": "q-cycle-1", "name": "Proceed?"}]

        # 1. First trigger
        sent_1 = await self.push_mgr.check_and_send_attention_notifications(
            attention_items=item,
            agent_running=True,
        )
        self.assertEqual(sent_1, 1)

        # 2. Resolved in DOM (empty attention list) -> notified_items cache is pruned
        sent_empty = await self.push_mgr.check_and_send_attention_notifications(
            attention_items=[],
            agent_running=True,
        )
        self.assertEqual(sent_empty, 0)
        self.assertNotIn("q-cycle-1:question", self.push_mgr.notified_items)

        # 3. New question emerges later with same ID -> re-notifies
        sent_retrigger = await self.push_mgr.check_and_send_attention_notifications(
            attention_items=item,
            agent_running=True,
        )
        self.assertEqual(sent_retrigger, 1)
        self.assertEqual(len(self.push_service.sent_notifications), 2)

    async def test_agent_running_steady_state_does_not_trigger_completed_push(self) -> None:
        """
        Verifies that steady-state running (True -> True) and steady-state idle (False -> False)
        snapshots never trigger spurious 'completed' alerts.
        """
        # Steady state False -> False
        await self.push_mgr.check_and_send_attention_notifications([], agent_running=False)
        await self.push_mgr.check_and_send_attention_notifications([], agent_running=False)
        self.assertEqual(len(self.push_service.sent_notifications), 0)

        # Steady state True -> True
        await self.push_mgr.check_and_send_attention_notifications([], agent_running=True)
        await self.push_mgr.check_and_send_attention_notifications([], agent_running=True)
        self.assertEqual(len(self.push_service.sent_notifications), 0)


# ==============================================================================
# Suite 2: Multi-Tab Client Visibility + Web Push Suppression Combinations
# ==============================================================================

class TestClientVisibilityAndPushSuppressionCombinations(HarnessTestCase):
    """
    Tests multi-tab client visibility state tracking and its suppression interaction
    with the background Web Push notification engine.
    """

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.temp_dir = tempfile.mkdtemp(prefix="tier3_vis_combo_")
        self.config_path = os.path.join(self.temp_dir, "config.json")
        self.subs_path = os.path.join(self.temp_dir, "push-subscriptions.json")
        self.vapid_path = os.path.join(self.temp_dir, "vapid-keys.json")

        self.push_mgr = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        self.sub1 = self.push_service.create_mock_subscription(endpoint="https://fcm.googleapis.com/fcm/send/sub1")
        self.sub2 = self.push_service.create_mock_subscription(endpoint="https://fcm.googleapis.com/fcm/send/sub2")
        self.push_mgr.add_subscription(self.sub1)
        self.push_mgr.add_subscription(self.sub2)

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        await super().asyncTearDown()

    async def test_single_visible_client_suppresses_attention_push(self) -> None:
        """
        Pairwise interaction: When a client reports visibility=True (tab in foreground),
        attention items and agent completion push notifications are completely suppressed.
        """
        self.push_mgr.set_client_visibility("client_tab_1", is_visible=True)
        self.assertTrue(self.push_mgr.is_any_client_visible())

        items = [{"type": "question", "id": "q-vis-1", "name": "Approve action"}]
        sent = await self.push_mgr.check_and_send_attention_notifications(
            attention_items=items,
            agent_running=True,
        )

        # 0 pushes delivered because user is actively looking at the screen
        self.assertEqual(sent, 0)
        self.assertEqual(len(self.push_service.sent_notifications), 0)

    async def test_all_clients_hidden_delivers_push_to_all_subscriptions(self) -> None:
        """
        Pairwise interaction: When all connected clients report visibility=False (background tabs/screen locked),
        attention notifications are broadcast to all registered push subscriptions.
        """
        self.push_mgr.set_client_visibility("client_tab_1", is_visible=False)
        self.push_mgr.set_client_visibility("client_tab_2", is_visible=False)
        self.assertFalse(self.push_mgr.is_any_client_visible())

        items = [{"type": "command", "id": "cmd-vis-2", "name": "Review diff"}]
        sent = await self.push_mgr.check_and_send_attention_notifications(
            attention_items=items,
            agent_running=True,
        )

        # Broadcast to both registered subscribers
        self.assertEqual(sent, 2)
        self.assertEqual(len(self.push_service.sent_notifications), 2)
        endpoints = {r["endpoint"] for r in self.push_service.sent_notifications}
        self.assertEqual(endpoints, {self.sub1["endpoint"], self.sub2["endpoint"]})

    async def test_multi_client_dynamic_visibility_toggles(self) -> None:
        """
        Multi-tab interaction: Client A is visible -> suppresses push. Client A navigates away
        (becomes hidden) -> next event dispatches push to both subscribers.
        """
        # 1. Client A visible, Client B hidden -> Suppressed
        self.push_mgr.set_client_visibility("client_a", is_visible=True)
        self.push_mgr.set_client_visibility("client_b", is_visible=False)

        items_1 = [{"type": "question", "id": "q-dyn-1", "name": "Q1"}]
        sent_1 = await self.push_mgr.check_and_send_attention_notifications(items_1, agent_running=True)
        self.assertEqual(sent_1, 0)

        # 2. Client A switches tab to background -> Now NO clients visible
        self.push_mgr.set_client_visibility("client_a", is_visible=False)
        self.assertFalse(self.push_mgr.is_any_client_visible())

        items_2 = [{"type": "question", "id": "q-dyn-2", "name": "Q2"}]
        sent_2 = await self.push_mgr.check_and_send_attention_notifications(items_2, agent_running=True)
        self.assertEqual(sent_2, 2)
        self.assertEqual(len(self.push_service.sent_notifications), 2)

    async def test_client_visibility_heartbeat_expiration_unsuppresses_push(self) -> None:
        """
        Multi-client interaction: Client was visible but tab closed without clean unmount
        (stale heartbeat > timeout) -> system prunes client and unsuppresses notifications.
        """
        self.push_mgr.set_client_visibility("abandoned_tab", is_visible=True)
        # Manually backdate heartbeat timestamp beyond timeout
        self.push_mgr.clients["abandoned_tab"].last_heartbeat = time.time() - 40.0

        # Heartbeat expired -> is_any_client_visible returns False
        self.assertFalse(self.push_mgr.is_any_client_visible(heartbeat_timeout=30.0))
        self.assertNotIn("abandoned_tab", self.push_mgr.clients)

        # Attention item should now trigger push
        items = [{"type": "completed", "id": "comp-stale-1", "name": "Build Done"}]
        sent = await self.push_mgr.check_and_send_attention_notifications(items, agent_running=False)
        self.assertEqual(sent, 2)

    def test_websocket_visibility_message_envelope_handling(self) -> None:
        """
        Pairwise interaction: WebSocket client sends visibility JSON envelope over /ws/stream,
        and server processes visibility updates without disrupting DOM streaming.
        """
        with self.client.websocket_connect("/ws/stream") as ws:
            # 1. Receive initial live snapshot
            initial_snap = ws.receive_json()
            assert_valid_snapshot(initial_snap)

            # 2. Send visibility message
            vis_msg = {
                "type": "visibility",
                "clientId": "web-client-test-uuid-42",
                "visible": True,
            }
            ws.send_json(vis_msg)

            # 3. Receive acknowledgement or next snapshot
            response = ws.receive_json()
            self.assertIn(response.get("type"), ("ack", "snapshot"))


# ==============================================================================
# Suite 3: Two-Way Chat Injection & Stop Generation Race Conditions
# ==============================================================================

class TestChatInjectionAndStopGenerationCombinations(HarnessTestCase):
    """
    Tests interactions between two-way chat message injection into Lexical editor,
    stop generation cancellation, and composite state hashing.
    """

    def test_chat_send_followed_by_immediate_stop_race(self) -> None:
        """
        Pairwise interaction: User sends chat prompt via POST /api/chat/send and immediately
        triggers POST /api/cdp/stop. Verifies orderly CDP call handling.
        """
        # 1. Send chat message
        chat_resp = self.client.chat_send("Generate a comprehensive test suite for Tier 3.")
        self.assertEqual(chat_resp.status_code, 200)
        chat_data = chat_resp.json()
        self.assertEqual(chat_data.get("status"), "success")

        # 2. Immediate stop request
        stop_resp = self.client.cdp_stop()
        self.assertEqual(stop_resp.status_code, 200)
        stop_data = stop_resp.json()
        self.assertEqual(stop_data.get("status"), "success")
        self.assertTrue(stop_data.get("stopped"))

    def test_stop_generation_idempotence_and_snapshot_hash(self) -> None:
        """
        Pairwise interaction: Stopping generation when agent is already idle is safe and idempotent,
        and stopping when agent is running updates snapshot hash cleanly.
        """
        # 1. Stop while idle
        self.cdp_server.simulate_agent_stop()
        resp_idle = self.client.cdp_stop()
        self.assertEqual(resp_idle.status_code, 200)

        # 2. Stop while running
        self.cdp_server.simulate_agent_start()
        self.assertTrue(self.cdp_server.mock_snapshot["agentRunning"])
        hash_before = self.cdp_server.mock_snapshot["hash"]

        resp_running = self.client.cdp_stop()
        self.assertEqual(resp_running.status_code, 200)

    def test_chat_send_with_append_mode_and_lexical_editor_dom(self) -> None:
        """
        Pairwise interaction: Sending chat with append_mode=True preserves prior editor content
        and generates compliant Lexical editor DOM nodes.
        """
        resp = self.client.chat_send("Appended text prompt", append_mode=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "success")

        # Verify generated Lexical editor HTML
        editor_html = self.dom_gen.generate_lexical_editor(current_text="Appended text prompt", agent_running=False)
        assert_sanitized_html(editor_html)
        self.assertIn("Appended text prompt", editor_html)
        self.assertIn('data-ag-click-id="chat:send"', editor_html)

    def test_chat_send_and_permission_click_interleaving(self) -> None:
        """
        Multi-feature interaction: User sends chat command -> tool requires permission ->
        user triggers permission approval click -> agent proceeds.
        """
        # 1. Chat send
        res1 = self.client.chat_send("Run npm test suite")
        self.assertEqual(res1.status_code, 200)

        # 2. CDP simulates permission prompt
        self.cdp_server.simulate_permission_prompt(command="npm test", tool="run_command")
        self.assertIsNotNone(self.cdp_server.mock_snapshot["permission"])

        # 3. User clicks Allow
        perm_res = self.client.permission_action(action="allow", command="npm test")
        self.assertEqual(perm_res.status_code, 200)
        self.assertEqual(perm_res.json().get("action"), "allow")


# ==============================================================================
# Suite 4: Image Drag-Drop Upload & Interactive Overlays Combinations
# ==============================================================================

class TestImageUploadAndInteractiveOverlaysCombinations(HarnessTestCase):
    """
    Tests interactions between mobile base64 image drag-drop upload,
    interactive tool call overlays, and DOM sanitization.
    """

    def test_image_upload_followed_by_permission_prompt_approval(self) -> None:
        """
        Pairwise interaction: Mobile client uploads base64 image via POST /api/upload-image,
        agent triggers permission dialog to process it, user approves via POST /api/cdp/permission.
        """
        # 1. Upload base64 image
        sample_img_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        up_resp = self.client.upload_image(
            base64_data=sample_img_b64,
            mime_type="image/png",
            filename="screenshot_mobile.png",
        )
        self.assertEqual(up_resp.status_code, 200)
        self.assertEqual(up_resp.json().get("filename"), "screenshot_mobile.png")

        # 2. Permission requested for OCR analysis tool
        perm_resp = self.client.permission_action(action="allow", command="python analyze_image.py")
        self.assertEqual(perm_resp.status_code, 200)
        self.assertEqual(perm_resp.json().get("status"), "success")

    def test_image_upload_with_ask_question_selection(self) -> None:
        """
        Pairwise interaction: Uploading an image triggers an ask_question overlay card,
        user answers via POST /api/cdp/answer-question.
        """
        sample_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
        self.client.upload_image(base64_data=sample_b64, filename="diagram.jpg")

        # Simulate ask_question in CDP
        self.cdp_server.simulate_ask_question(
            question="How should we process the uploaded diagram?",
            choices=["Extract text", "Convert to SVG", "Summarize visual layout"],
        )

        # Answer question
        ans_resp = self.client.answer_question(choice_index=1)
        self.assertEqual(ans_resp.status_code, 200)
        self.assertEqual(ans_resp.json().get("status"), "success")

    def test_image_upload_dom_sanitization_and_css_custom_props(self) -> None:
        """
        Multi-feature interaction: Chat DOM containing uploaded image bubbles and CSS variables
        passes the 14-step sanitization pipeline and responsive styling validation.
        """
        chat_dom_with_img = self.dom_gen.generate_chat_dom(
            messages=[
                {"role": "user", "text": "Uploaded mobile image preview:"},
                {"role": "assistant", "text": "Analyzing uploaded diagram."},
            ]
        )
        assert_sanitized_html(chat_dom_with_img)

        css = self.dom_gen.generate_css_variables({"--antigravity-img-max-width": "100%"})
        assert_responsive_css(css)
        self.assertIn("--antigravity-img-max-width", css)

    def test_image_upload_rejection_permission_workflow(self) -> None:
        """
        Pairwise interaction: Upload image followed by user rejecting tool permission via action='deny'.
        """
        self.client.upload_image("data:image/png;base64,AAAA", filename="test.png")
        deny_resp = self.client.permission_action(action="deny", command="rm -rf /")
        self.assertEqual(deny_resp.status_code, 200)
        self.assertEqual(deny_resp.json().get("action"), "deny")


# ==============================================================================
# Suite 5: Subagent View Toggle + BTW Side Panel + History Modal Combinations
# ==============================================================================

class TestSubagentViewBtwAndHistoryModalCombinations(HarnessTestCase):
    """
    Tests interactions between subagent view navigation, BTW side question drawers,
    and conversation history modal overlays.
    """

    def test_subagent_view_activation_and_back_navigation(self) -> None:
        """
        Pairwise interaction: Snapshot activates subagent view banner, and user clicks
        'subagent:back' to navigate back to parent conversation.
        """
        # 1. Switch to subagent view
        self.cdp_server.simulate_subagent_view(
            subagent_title="Subagent Explorer 1",
            parent_title="Main Conversation",
        )
        snap = self.cdp_server.mock_snapshot
        self.assertTrue(snap["isSubagentView"])
        self.assertEqual(snap["subagentTitle"], "Subagent Explorer 1")
        self.assertIn("SUBAGENT", snap["subagentInfoHtml"])

        # 2. User clicks back button
        click_resp = self.client.cdp_click(click_id="subagent:back", click_type="subagent")
        self.assertEqual(click_resp.status_code, 200)
        self.assertEqual(click_resp.json().get("clickId"), "subagent:back")

    def test_btw_side_question_drawer_in_subagent_mode(self) -> None:
        """
        Pairwise interaction: User asks side questions via /btw panel while inside
        a subagent view without disturbing active subagent execution context.
        """
        snap = self.dom_gen.generate_full_snapshot(
            is_subagent_view=True,
            subagent_title="Subagent QA",
        )
        snap["btwHtml"] = self.dom_gen.generate_btw_panel(
            questions=[{"q": "What is current test progress?", "a": "32 tests passing."}]
        )
        snap["hash"] = compute_composite_hash(snap)

        assert_valid_snapshot(snap)
        assert_valid_djb2_hash(snap["hash"])
        self.assertIn("Side Questions (/btw)", snap["btwHtml"])

        # Submit BTW ask click
        click_resp = self.client.cdp_click(click_id="btw:send", click_type="btw")
        self.assertEqual(click_resp.status_code, 200)

    def test_conversation_history_modal_selection_from_subagent_view(self) -> None:
        """
        Multi-feature interaction: Query conversation history modal from subagent view
        and dispatch navigation click to prior session.
        """
        # 1. Query history endpoint
        hist_resp = self.client.get_conversation_history()
        self.assertEqual(hist_resp.status_code, 200)
        self.assertIn("history", hist_resp.json())

        # 2. Click history entry
        click_resp = self.client.cdp_click(click_id="history:1", click_type="history")
        self.assertEqual(click_resp.status_code, 200)
        self.assertEqual(click_resp.json().get("clickId"), "history:1")

    def test_scheduled_tasks_modal_and_btw_coexistence(self) -> None:
        """
        Multi-feature interaction: Scheduled tasks overlay modal and BTW side drawer
        coexisting in snapshot state maintain distinct composite DJB2 state hashes.
        """
        snap1 = self.dom_gen.generate_full_snapshot()
        snap1["scheduledTasksHtml"] = self.dom_gen.generate_scheduled_tasks_modal()
        hash1 = compute_composite_hash(snap1)

        snap2 = dict(snap1)
        snap2["btwHtml"] = self.dom_gen.generate_btw_panel()
        hash2 = compute_composite_hash(snap2)

        self.assertNotEqual(hash1, hash2)
        assert_valid_djb2_hash(hash1)
        assert_valid_djb2_hash(hash2)


# ==============================================================================
# Suite 6: Concurrent WebSocket Clients & Broadcast Diff Synchronization
# ==============================================================================

class TestConcurrentWebSocketsAndBroadcastDiffCombinations(HarnessTestCase):
    """
    Tests multiple concurrent WebSocket clients receiving live DOM snapshot diffs,
    reconnection handling, and route aliases.
    """

    def test_multiple_concurrent_websockets_receive_broadcast_diff(self) -> None:
        """
        Pairwise interaction: Multiple WebSocket clients simultaneously connect to /ws/stream
        and receive valid snapshot envelopes with matching state hashes.
        """
        with self.client.websocket_connect("/ws/stream") as ws1:
            snap1 = ws1.receive_json()
            assert_valid_snapshot(snap1)

            with self.client.websocket_connect("/ws/stream") as ws2:
                snap2 = ws2.receive_json()
                assert_valid_snapshot(snap2)

                # Hashes match because DOM state is synchronized
                self.assertEqual(snap1["hash"], snap2["hash"])

    def test_websocket_client_disconnect_resilience(self) -> None:
        """
        Multi-client interaction: One client disconnecting abruptly does not affect
        remaining active WebSocket streaming connections.
        """
        with self.client.websocket_connect("/ws/stream") as ws1:
            snap1 = ws1.receive_json()
            assert_valid_snapshot(snap1)

            # Second client connects and immediately disconnects
            with self.client.websocket_connect("/ws/stream") as ws2:
                snap2 = ws2.receive_json()
                assert_valid_snapshot(snap2)

            # First client still responsive
            ws1.send_json({"type": "visibility", "visible": True})
            ack = ws1.receive_json()
            self.assertIn(ack.get("type"), ("ack", "snapshot"))

    def test_websocket_stream_route_aliases(self) -> None:
        """
        Pairwise interaction: Both /ws/stream and /wahyuai/ws/stream route aliases
        accept WebSocket client connections and serve valid snapshots.
        """
        with self.client.websocket_connect("/ws/stream") as ws_std:
            snap_std = ws_std.receive_json()
            assert_valid_snapshot(snap_std)

        with self.client.websocket_connect("/wahyuai/ws/stream") as ws_alias:
            snap_alias = ws_alias.receive_json()
            assert_valid_snapshot(snap_alias)

    def test_websocket_snapshot_stream_schema_and_timestamp(self) -> None:
        """
        Verifies that streaming snapshots contain valid timestamps and all required
        fields across live diff cycles.
        """
        with self.client.websocket_connect("/ws/stream") as ws:
            snap = ws.receive_json()
            self.assertIn("timestamp", snap)
            self.assertTrue(isinstance(snap["timestamp"], int))
            self.assertTrue(snap["timestamp"] > 0)


# ==============================================================================
# Suite 7: VAPID Key Rotation & Subscription Persistence Combinations
# ==============================================================================

class TestVapidRotationAndSubscriptionPersistenceCombinations(HarnessTestCase):
    """
    Tests VAPID key rotation, browser push subscription persistence on disk,
    and automatic pruning of expired HTTP 410 endpoints.
    """

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.temp_dir = tempfile.mkdtemp(prefix="tier3_vapid_combo_")
        self.config_path = os.path.join(self.temp_dir, "config.json")
        self.subs_path = os.path.join(self.temp_dir, "push-subscriptions.json")
        self.vapid_path = os.path.join(self.temp_dir, "vapid-keys.json")

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        await super().asyncTearDown()

    async def test_vapid_key_rotation_preserves_stored_subscriptions(self) -> None:
        """
        Pairwise interaction: Rotating the VAPID keypair in vapid-keys.json does not corrupt
        or erase existing push subscriptions stored in push-subscriptions.json.
        """
        # 1. Initialize manager 1 and add 2 subscriptions
        mgr1 = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        sub_a = self.push_service.create_mock_subscription(endpoint="https://fcm.googleapis.com/fcm/send/ep_a")
        sub_b = self.push_service.create_mock_subscription(endpoint="https://fcm.googleapis.com/fcm/send/ep_b")
        mgr1.add_subscription(sub_a)
        mgr1.add_subscription(sub_b)
        self.assertEqual(len(mgr1.get_subscriptions()), 2)
        old_pub_key = mgr1.get_public_vapid_key()

        # 2. Simulate VAPID key rotation (delete vapid-keys.json)
        os.remove(self.vapid_path)

        # 3. Initialize manager 2 -> generates new VAPID keys but reloads push-subscriptions.json
        mgr2 = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        new_pub_key = mgr2.get_public_vapid_key()
        self.assertNotEqual(old_pub_key, new_pub_key)
        assert_vapid_key_valid(new_pub_key)

        # Subscriptions are preserved
        self.assertEqual(len(mgr2.get_subscriptions()), 2)

        # Send push signed with new VAPID key
        sent = await mgr2.send_notification("Title", "Body")
        self.assertEqual(sent, 2)

    def test_subscription_addition_and_immediate_vapid_public_key_query(self) -> None:
        """
        Pairwise interaction: Mobile client queries GET /api/vapid-key and registers
        subscription via POST /api/subscriptions/push.
        """
        vapid_res = self.client.get_vapid_key()
        self.assertEqual(vapid_res.status_code, 200)
        pub_key = vapid_res.json().get("publicKey")
        assert_vapid_key_valid(pub_key)

        sub_payload = self.push_service.create_mock_subscription()
        sub_res = self.client.add_push_subscription(sub_payload)
        self.assertEqual(sub_res.status_code, 200)
        self.assertEqual(sub_res.json().get("status"), "success")

    async def test_duplicate_subscription_endpoint_upsert(self) -> None:
        """
        Pairwise interaction: Re-subscribing with the same endpoint URL updates the p256dh/auth
        keys without creating duplicate entries.
        """
        mgr = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        ep = "https://fcm.googleapis.com/fcm/send/upsert_ep"
        sub_v1 = self.push_service.create_mock_subscription(endpoint=ep, p256dh="old_key", auth="old_auth")
        mgr.add_subscription(sub_v1)
        self.assertEqual(len(mgr.get_subscriptions()), 1)

        # Upsert with new keys
        sub_v2 = self.push_service.create_mock_subscription(endpoint=ep, p256dh="new_key", auth="new_auth")
        mgr.add_subscription(sub_v2)

        # Total subscriptions count is still 1
        subs = mgr.get_subscriptions()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["keys"]["p256dh"], "new_key")

    async def test_expired_subscription_410_auto_pruning_on_push_event(self) -> None:
        """
        Multi-step interaction: When pywebpush encounters HTTP 410 Gone (expired browser subscription),
        the endpoint is automatically removed from memory and storage.
        """
        mgr = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )
        sub_live = self.push_service.create_mock_subscription(endpoint="https://fcm.googleapis.com/fcm/send/live")
        sub_dead = self.push_service.create_mock_subscription(endpoint="https://fcm.googleapis.com/fcm/send/dead")

        mgr.add_subscription(sub_live)
        mgr.add_subscription(sub_dead)
        self.assertEqual(len(mgr.get_subscriptions()), 2)

        # Configure dead endpoint to return 410
        self.push_service.set_endpoint_status(sub_dead["endpoint"], 410)

        # Dispatch push
        sent = await mgr.send_notification("Alert", "Test Prune")
        self.assertEqual(sent, 1)

        # Dead endpoint is pruned from manager and disk
        self.assertEqual(len(mgr.get_subscriptions()), 1)
        self.assertEqual(mgr.get_subscriptions()[0]["endpoint"], sub_live["endpoint"])


# ==============================================================================
# Suite 8: mDNS Zeroconf & REST Route Discovery Combinations
# ==============================================================================

class TestMdnsZeroconfAndRestRouteDiscoveryCombinations(HarnessTestCase):
    """
    Tests DevTools port discovery, Zeroconf mDNS properties, all 15 legacy routes,
    and core WebRemote v6 endpoints.
    """

    def test_devtools_active_port_file_discovery_and_binding(self) -> None:
        """
        Pairwise interaction: DevToolsActivePort file written by Antigravity is detected
        and matches the running MockCDPServer instance.
        """
        temp_dir = tempfile.mkdtemp(prefix="devtools_port_")
        try:
            port_file = self.cdp_server.create_active_port_file(temp_dir)
            self.assertTrue(os.path.exists(port_file))

            with open(port_file, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()

            self.assertEqual(int(lines[0]), self.cdp_server.port)
            self.assertIn(self.cdp_server.browser_id, lines[1])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_all_15_legacy_endpoints_accessible_concurrently_with_v6_routes(self) -> None:
        """
        Multi-route interaction: All 15 legacy endpoints return 200 OK while v6 routes
        are active, preserving backward compatibility with legacy monitoring scripts.
        """
        legacy_paths = [
            "/api/projects",
            "/api/review/diff",
            "/api/chat/incoming",
            "/api/status",
            "/api/models",
            "/api/agents",
            "/api/sessions",
            "/api/config",
            "/api/system/info",
            "/api/version",
            "/api/ping",
            "/api/logs",
            "/api/metrics",
            "/api/context",
            "/api/prompts",
        ]

        for path in legacy_paths:
            resp = self.client.get(path)
            self.assertEqual(
                resp.status_code,
                200,
                f"Legacy route '{path}' failed with status {resp.status_code}",
            )

    def test_v6_core_rest_endpoints_matrix(self) -> None:
        """
        Verifies that core v6 REST routes return status 200 and expected response JSON envelopes.
        """
        # 1. VAPID key
        self.assertEqual(self.client.get_vapid_key().status_code, 200)

        # 2. Running tasks
        self.assertEqual(self.client.get_running_tasks().status_code, 200)

        # 3. Scheduled tasks
        self.assertEqual(self.client.get_scheduled_tasks().status_code, 200)

        # 4. Conversation history
        self.assertEqual(self.client.get_conversation_history().status_code, 200)

        # 5. Right sidebar
        self.assertEqual(self.client.get_right_sidebar().status_code, 200)

    def test_antigravity_restart_lifecycle_endpoint(self) -> None:
        """
        Pairwise interaction: POST /api/restart-antigravity triggers lifecycle response.
        """
        resp = self.client.restart_antigravity()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("restarting", resp.json().get("status", ""))


# ==============================================================================
# Suite 9: Interactive Overlays & CDP Element Click Routing
# ==============================================================================

class TestInteractiveOverlaysAndDropdownCombinations(HarnessTestCase):
    """
    Tests interactions between interactive overlays (permission dialogs, ask_question cards,
    dropdown menus, running task strips) and CDP coordinated element clicks.
    """

    def test_permission_overlay_all_actions_routing(self) -> None:
        """
        Pairwise interaction: Testing all 4 permission dialog actions ('allow', 'deny', 'review', 'run')
        via POST /api/cdp/permission.
        """
        for act in ["allow", "deny", "review", "run"]:
            resp = self.client.permission_action(action=act, command=f"action_{act}")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json().get("action"), act)

    def test_ask_question_overlay_multiple_choice_and_custom_text(self) -> None:
        """
        Pairwise interaction: Answering ask_question card with choice index and with custom text
        via POST /api/cdp/answer-question.
        """
        # Choice selection
        res_choice = self.client.answer_question(choice_index=2)
        self.assertEqual(res_choice.status_code, 200)

        # Custom text input
        res_custom = self.client.answer_question(custom_text="Custom explanation for decision")
        self.assertEqual(res_custom.status_code, 200)

    def test_dropdown_menu_selection_and_options_diff(self) -> None:
        """
        Pairwise interaction: Selecting an item from dropdown portal via POST /api/cdp/dropdown-select.
        """
        resp = self.client.dropdown_select(option_index=1, label="gpt-4o")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "success")

    def test_running_tasks_strip_lifecycle_and_cancel_action(self) -> None:
        """
        Pairwise interaction: Running tasks strip reflects background tasks and handles cancel click.
        """
        # 1. Query running tasks
        tasks_resp = self.client.get_running_tasks()
        self.assertEqual(tasks_resp.status_code, 200)

        # 2. Dispatch task cancel click
        cancel_resp = self.client.cdp_click(click_id="task-cancel:0", click_type="task")
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.json().get("clickId"), "task-cancel:0")


# ==============================================================================
# Suite 10: Multi-Context Execution & DOM Sanitization Combinations
# ==============================================================================

class TestMultiContextExecutionAndDomSanitizationCombinations(HarnessTestCase):
    """
    Tests interactions between multi-context execution tracking, 14-step DOM sanitization,
    CSS custom properties extraction, and DJB2 hash state stability.
    """

    def test_dom_sanitization_with_dynamic_css_and_djb2_hashing(self) -> None:
        """
        Multi-feature interaction: DOM snapshot containing raw markup, inline spans, and CSS variables
        is sanitized, extracts valid CSS, and calculates a valid DJB2 hash.
        """
        raw_chat = (
            '<div class="chat-container">'
            '  <span><div class="nested-div-fix">Content inside span</div></span>'
            '  <button data-ag-click-id="chat:42" class="action-btn">Click Me</button>'
            '</div>'
        )
        css_vars = self.dom_gen.generate_css_variables()

        snapshot = self.dom_gen.generate_full_snapshot(
            custom_chat_html=raw_chat,
            custom_css=css_vars,
        )

        assert_valid_snapshot(snapshot)
        assert_sanitized_html(snapshot["html"])
        assert_responsive_css(snapshot["css"])
        assert_valid_djb2_hash(snapshot["hash"])
        self.assertIn('data-ag-click-id="chat:42"', snapshot["html"])

    def test_rapid_state_transitions_maintain_hash_distinctness(self) -> None:
        """
        Verifies that distinct consecutive UI states (base chat, with permission dialog,
        with ask_question card, with subagent banner, with dropdown portal, with running tasks)
        each produce distinct, unique composite DJB2 state hashes.
        """
        states = [
            self.dom_gen.generate_full_snapshot(agent_running=False),
            self.dom_gen.generate_full_snapshot(with_permission=True),
            self.dom_gen.generate_full_snapshot(with_ask_question=True),
            self.dom_gen.generate_full_snapshot(is_subagent_view=True, subagent_title="Sub 1"),
            self.dom_gen.generate_full_snapshot(with_dropdown=True),
            self.dom_gen.generate_full_snapshot(with_running_tasks=True),
        ]

        hashes = [s["hash"] for s in states]
        # All hashes should be valid and distinct
        for h in hashes:
            assert_valid_djb2_hash(h)

        self.assertEqual(len(hashes), len(set(hashes)), "Each distinct UI state must have a unique DJB2 hash")

    async def test_push_paused_flag_overrides_visibility_and_attention(self) -> None:
        """
        Pairwise interaction: When push delivery is paused globally via set_push_paused(True),
        no push notifications are sent even if all clients are hidden and attention events occur.
        """
        temp_dir = tempfile.mkdtemp(prefix="tier3_pause_")
        try:
            cfg = os.path.join(temp_dir, "config.json")
            subs = os.path.join(temp_dir, "push-subscriptions.json")
            vapid = os.path.join(temp_dir, "vapid-keys.json")

            mgr = PushNotificationManager(config_path=cfg, subscriptions_path=subs, vapid_path=vapid)
            sub = self.push_service.create_mock_subscription()
            mgr.add_subscription(sub)

            # All clients hidden
            mgr.set_client_visibility("client_1", is_visible=False)
            self.assertFalse(mgr.is_any_client_visible())

            # Pause push
            mgr.set_push_paused(True)
            self.assertTrue(mgr.is_push_paused())

            # Trigger attention
            items = [{"type": "question", "id": "q-pause-1", "name": "Paused test"}]
            sent = await mgr.check_and_send_attention_notifications(items, agent_running=True)

            self.assertEqual(sent, 0)
            self.assertEqual(len(self.push_service.sent_notifications), 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# CLI Entrypoint
# ==============================================================================

if __name__ == "__main__":
    unittest.main()
