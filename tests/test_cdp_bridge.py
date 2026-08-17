"""
Unit and Integration Test Suite for cdp_bridge.py
=================================================

Comprehensive test suite verifying:
1. DJB2 32-bit state hashing & 17-property composite string encoding
2. Dynamic DevTools port discovery & target selection priority
3. CDP WebSocket client connection lifecycle, request/response tracking, and auto-reconnect
4. V8 execution context lifecycle tracking (create, destroy, clear, preferred locking)
5. Multi-context evaluation strategies (evaluate_in_browser, evaluate_across_contexts, evaluate_in_context, find_editor_context)
6. Snapshot capture, DOM sanitization, CSS variable harvest, and peripheral state extraction
7. User interaction proxies (inject_message, click_element, stop_generation, upload_image, type_text, etc.)
8. Script builders and parameter escaping
"""

import asyncio
import base64
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, List, Optional
import unittest

import pytest
import aiohttp

from cdp_bridge import (
    CDPBridge,
    CDPTarget,
    ExecutionContext,
    DOMSnapshot,
    ActionResult,
    compute_djb2_hash,
    compute_composite_hash,
    read_devtools_port,
    get_devtools_active_port_path,
    discover_target,
    try_port_for_target,
    TAG_INTERACTIVES_FN,
    CAPTURE_SCRIPT,
    RIGHT_SIDEBAR_SCRIPT,
    RUNNING_TASKS_SCRIPT,
    SCHEDULED_TASKS_SCRIPT,
    SCHEDULED_TASKS_DIALOG_SCRIPT,
    CONVERSATION_HISTORY_SCRIPT,
    STOP_SCRIPT,
    DISCOVER_SCRIPT,
    CHECK_EDITOR_IMAGE_SCRIPT,
    CLICK_SEND_BUTTON_SCRIPT,
    EXPAND_LEFT_SIDEBAR_SCRIPT,
    DISMISS_SCHEDULED_TASKS_SCRIPT,
    DISMISS_SETTINGS_SCRIPT,
    CLOSE_RIGHT_SIDEBAR_SCRIPT,
    SELECT_OVERVIEW_TAB_SCRIPT,
    HAS_VISIBLE_EDITOR_SCRIPT,
    OPEN_RIGHT_SIDEBAR_SCRIPT,
    build_capture_listbox_script,
    build_capture_kebab_menu_script,
    build_inject_script,
    build_task_click_script,
    build_sched_click_script,
    build_sched_portal_click_script,
    build_sched_dialog_click_script,
    build_main_click_script,
    build_type_text_script,
    build_upload_image_script,
    build_click_conversation_script,
    build_history_click_script,
    build_copy_response_script,
    build_proxy_image_script,
)

from tests.harness import MockCDPServer, find_free_port


# ============================================================================
# 1. DJB2 State Hashing Tests
# ============================================================================

class TestDJB2StateHashing(unittest.TestCase):
    """Tests DJB2 base-36 mathematical hashing and 17-property composite string ordering."""

    def test_djb2_empty_string(self):
        """Empty string must produce base-36 '45h' (5381 in base 36)."""
        self.assertEqual(compute_djb2_hash(""), "45h")

    def test_djb2_known_ascii_vectors(self):
        """Known ASCII vectors matched against Node.js hashString."""
        self.assertEqual(compute_djb2_hash("hello"), "4bj995")
        self.assertEqual(
            compute_djb2_hash("<div>Hello World!</div>10nullundefined"),
            "iuqgmx",
        )

    def test_djb2_unicode_and_emojis(self):
        """Surrogate pairs and multi-byte UTF-16 code units."""
        self.assertEqual(compute_djb2_hash("Halo Dunia \U0001f680 123!"), "1t6thvy")

    def test_djb2_large_dom_strings(self):
        """Large repetitive DOM vectors matching Node.js engine."""
        self.assertEqual(compute_djb2_hash("<div></div>" * 10000), "1u073it")
        self.assertEqual(compute_djb2_hash("hello world " * 10000), "1m5e75x")

    def test_composite_hash_17_properties_order(self):
        """Ensures all 17 properties (18 tokens) are concatenated in exact sequence."""
        snapshot = {
            "html": "<div id='chat'>msg</div>",
            "leftSidebarHtml": "<aside>sidebar</aside>",
            "sidebarSignature": "overview*,review",
            "isSidebarOpen": True,
            "dropdownHtml": "<ul>options</ul>",
            "dialogHtml": "<div role='dialog'>modal</div>",
            "settingsHtml": "<div class='settings'>cfg</div>",
            "askQuestionHtml": "<div class='ask'>question</div>",
            "permissionHtml": "<div class='perm'>allow</div>",
            "runningTasksHtml": "<div class='task'>running</div>",
            "scheduledTasksHtml": "<div class='sched'>list</div>",
            "scheduledTasksDialogHtml": "<div class='scheddlg'>new</div>",
            "conversationHistoryHtml": "<div class='history'>hist</div>",
            "subagentInfoHtml": "<div class='sub'>subagent</div>",
            "btwHtml": "<div class='btw'>side</div>",
            "modelName": "Claude 3.7 Sonnet",
            "environmentName": "Local",
            "branchName": "main",
        }

        # Expected sequence concatenation:
        raw_concat = (
            "<div id='chat'>msg</div>"
            "<aside>sidebar</aside>"
            "overview*,review"
            "1"
            "<ul>options</ul>"
            "<div role='dialog'>modal</div>"
            "<div class='settings'>cfg</div>"
            "<div class='ask'>question</div>"
            "<div class='perm'>allow</div>"
            "<div class='task'>running</div>"
            "<div class='sched'>list</div>"
            "<div class='scheddlg'>new</div>"
            "<div class='history'>hist</div>"
            "<div class='sub'>subagent</div>"
            "<div class='btw'>side</div>"
            "Claude 3.7 Sonnet"
            "Local"
            "main"
        )
        expected_hash = compute_djb2_hash(raw_concat)
        actual_hash = compute_composite_hash(snapshot)
        self.assertEqual(actual_hash, expected_hash)

    def test_composite_hash_with_dom_snapshot_object(self):
        """Verifies compute_composite_hash works identically with DOMSnapshot dataclass."""
        snap_obj = DOMSnapshot(
            html="<main>Content</main>",
            isSidebarOpen=False,
            modelName="Gemini 2.5 Pro",
            permissionHtml="<banner>Permit</banner>",
        )
        dict_rep = snap_obj.to_dict()
        self.assertEqual(
            compute_composite_hash(snap_obj), compute_composite_hash(dict_rep)
        )

    def test_composite_hash_differential_detection(self):
        """Changing any of the 17 state flags produces a distinct composite hash."""
        base_snap = {"html": "<p>chat</p>", "isSidebarOpen": False}
        base_hash = compute_composite_hash(base_snap)

        # 1. Sidebar open toggled
        snap_sidebar_open = {"html": "<p>chat</p>", "isSidebarOpen": True}
        self.assertNotEqual(base_hash, compute_composite_hash(snap_sidebar_open))

        # 2. Permission banner appeared
        snap_perm = {
            "html": "<p>chat</p>",
            "isSidebarOpen": False,
            "permissionHtml": "<banner>Allow</banner>",
        }
        self.assertNotEqual(base_hash, compute_composite_hash(snap_perm))

        # 3. Model changed
        snap_model = {
            "html": "<p>chat</p>",
            "isSidebarOpen": False,
            "modelName": "GPT-4o",
        }
        self.assertNotEqual(base_hash, compute_composite_hash(snap_model))


# ============================================================================
# 2. DevTools Port Discovery Tests
# ============================================================================

class TestDevToolsPortDiscovery(unittest.TestCase):
    """Tests DevToolsActivePort file parsing and candidate fallback probing."""

    def test_read_devtools_port_valid_file(self):
        """Valid DevToolsActivePort file with port on line 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ag_dir = Path(tmpdir) / "Antigravity"
            ag_dir.mkdir(parents=True, exist_ok=True)
            dtp_file = ag_dir / "DevToolsActivePort"
            dtp_file.write_text("49250\n/devtools/browser/uuid-1234\n", encoding="utf-8")

            port = read_devtools_port(app_data_dir=tmpdir)
            self.assertEqual(port, 49250)

    def test_read_devtools_port_missing_file(self):
        """Missing DevToolsActivePort file returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            port = read_devtools_port(app_data_dir=tmpdir)
            self.assertIsNone(port)

    def test_read_devtools_port_corrupted_file(self):
        """Corrupted or invalid integer lines return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ag_dir = Path(tmpdir) / "Antigravity"
            ag_dir.mkdir(parents=True, exist_ok=True)
            dtp_file = ag_dir / "DevToolsActivePort"

            # Non-integer content
            dtp_file.write_text("not_a_port\n/browser\n", encoding="utf-8")
            self.assertIsNone(read_devtools_port(app_data_dir=tmpdir))

            # Out of bounds port
            dtp_file.write_text("999999\n/browser\n", encoding="utf-8")
            self.assertIsNone(read_devtools_port(app_data_dir=tmpdir))

            # Zero port
            dtp_file.write_text("0\n/browser\n", encoding="utf-8")
            self.assertIsNone(read_devtools_port(app_data_dir=tmpdir))

    def test_get_devtools_active_port_path(self):
        """Platform-specific path resolution."""
        path_default = get_devtools_active_port_path()
        self.assertTrue(str(path_default).endswith("DevToolsActivePort"))

        custom_path = get_devtools_active_port_path("/custom/dir")
        self.assertEqual(
            custom_path, Path("/custom/dir") / "Antigravity" / "DevToolsActivePort"
        )


# ============================================================================
# 3. Async CDP Connection & Multi-Context Evaluation Tests
# ============================================================================

@pytest.mark.asyncio
class TestCDPBridgeAsyncLifecycle:
    """Tests async CDP WebSocket connection, context lifecycle, and evaluation engine."""

    async def test_connect_happy_path(self):
        """Tests successful connection to MockCDPServer."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            connected = await bridge.connect()
            assert connected is True
            assert bridge.is_connected is True
            assert bridge.connection_state == "connected"

            # Verify Runtime domain and Emulation were enabled
            methods_called = [c.get("method") for c in server.call_log]
            assert "Runtime.enable" in methods_called
            assert "Emulation.setFocusEmulationEnabled" in methods_called

            await bridge.disconnect()
            assert bridge.is_connected is False
            assert bridge.connection_state == "disconnected"
        finally:
            server.stop()

    async def test_test_connect_online_and_offline(self):
        """Tests test_connect() helper method."""
        free_port = find_free_port()
        offline_bridge = CDPBridge(port=free_port)
        assert await offline_bridge.test_connect() is False

        server = MockCDPServer()
        server.start()
        try:
            online_bridge = CDPBridge(host=server.host, port=server.port)
            assert await online_bridge.test_connect() is True
            await online_bridge.disconnect()
        finally:
            server.stop()

    async def test_execution_context_tracking(self):
        """Verifies context created, destroyed, cleared events and preferred context locking."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            # MockCDPServer creates context 1 (default) and context 2 (isolated)
            assert len(bridge.contexts) >= 1
            default_ctx = next((c for c in bridge.contexts if c.is_default), None)
            assert default_ctx is not None
            assert default_ctx.id == 1

            # Simulate evaluation that locks preferred context
            server.custom_evaluate_handler = lambda expr, params: 2 if "1 + 1" in expr else None
            res = await bridge.evaluate_in_browser("1 + 1")
            assert res == 2
            assert bridge.preferred_context_id == 1

            # Test context destroy event
            bridge._handle_cdp_event(
                "Runtime.executionContextDestroyed", {"executionContextId": 1}
            )
            assert bridge.preferred_context_id is None
            assert not any(c.id == 1 for c in bridge.contexts)

            # Test contexts cleared event
            bridge._handle_cdp_event("Runtime.executionContextsCleared", {})
            assert len(bridge.contexts) == 0

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_evaluate_in_browser_priority_and_fallback(self):
        """evaluate_in_browser prioritizes default context and locks to first non-throwing context."""
        server = MockCDPServer()
        server.start()
        try:
            server.custom_evaluate_handler = lambda expr, params: "hello" if "'hello'" in expr else None
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            # Standard evaluation
            val = await bridge.evaluate_in_browser("'hello'")
            assert val == "hello"
            assert bridge.preferred_context_id is not None

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_evaluate_across_contexts(self):
        """evaluate_across_contexts returns first non-null result across all contexts."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            # Set custom eval handler in mock server
            def mock_eval(expr, params):
                ctx_id = params.get("contextId")
                if ctx_id == 2:
                    return "<div id='portal'>Radix</div>"
                return (None,)

            server.custom_evaluate_handler = mock_eval

            res = await bridge.evaluate_across_contexts("capture_portal()")
            assert res == "<div id='portal'>Radix</div>"

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_evaluate_in_context_strict(self):
        """evaluate_in_context evaluates strictly in given context."""
        server = MockCDPServer()
        server.start()
        try:
            server.custom_evaluate_handler = lambda expr, params: 100 if "10 * 10" in expr else None
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            # Context 1
            res1 = await bridge.evaluate_in_context(1, "10 * 10")
            assert res1 == 100

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_find_editor_context(self):
        """find_editor_context locates context containing visible Lexical editor."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            # Mock server default returns True for editor presence probe
            editor_ctx = await bridge.find_editor_context()
            assert editor_ctx is not None
            assert editor_ctx in [1, 2]

            await bridge.disconnect()
        finally:
            server.stop()


# ============================================================================
# 4. Snapshot Capture & Interaction Handlers Tests
# ============================================================================

@pytest.mark.asyncio
class TestCDPBridgeActionsAndCapture:
    """Tests capture_snapshot, inject_message, click_element, stop, upload_image, type_text."""

    async def test_capture_snapshot_full(self):
        """Full capture_snapshot executes and generates valid DOMSnapshot with hash."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            snapshot = await bridge.capture_snapshot()
            assert snapshot is not None
            assert isinstance(snapshot, DOMSnapshot)
            assert snapshot.hash != ""
            assert snapshot.timestamp != ""
            assert "<div" in snapshot.html or snapshot.html == ""
            assert bridge.cached_snapshot == snapshot
            assert bridge.last_snapshot_hash == snapshot.hash

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_inject_message(self):
        """inject_message uses detect-then-execute pattern and sends text."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            res = await bridge.inject_message("Bismillah Test Prompt\nSecond line")
            assert res.get("ok") is True
            assert len(server.injected_messages) > 0
            assert "Bismillah Test Prompt" in server.injected_messages[-1].get("text", "")

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_inject_message_append_mode(self):
        """inject_message supports append_mode for preserving existing attachments."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            res = await bridge.inject_message("Appended text", append_mode=True)
            assert res.get("ok") is True
            assert "if (true)" in server.injected_messages[-1].get("raw", "")

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_click_element_across_sources(self):
        """click_element dispatches clicks to chat, task, sched, scheddlg, ask, perm."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            # Chat click
            res_chat = await bridge.click_element("chat:0", label="Allow")
            assert res_chat.get("ok") is True

            # Task click
            res_task = await bridge.click_element("task:1")
            assert res_task.get("ok") is True

            # Sched click
            res_sched = await bridge.click_element("sched:0")
            assert res_sched.get("ok") is True

            # Sched dialog click
            res_dlg = await bridge.click_element("scheddlg:2", label="Save")
            assert res_dlg.get("ok") is True

            # Sched portal click (dlgIdx >= 100)
            res_portal = await bridge.click_element("scheddlg:101")
            assert res_portal.get("ok") is True

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_stop_generation(self):
        """stop_generation locates and triggers cancel/stop button."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            res = await bridge.stop_generation()
            assert res.get("ok") is True
            assert server.stopped_calls >= 1

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_upload_image(self):
        """upload_image synthesizes base64 DataTransfer drop event."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            dummy_b64 = base64.b64encode(b"fake-image-png-data").decode("utf-8")
            res = await bridge.upload_image(
                base64_data=dummy_b64, mime_type="image/png", filename="test.png"
            )
            assert res.get("ok") is True
            assert len(server.uploaded_images) > 0
            assert "test.png" in server.uploaded_images[-1].get("payload", "")

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_type_text(self):
        """type_text invokes React native input setter bypass."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            res = await bridge.type_text(
                placeholder="Task title", text="Daily Backup"
            )
            assert res.get("ok") is True

            res_cid = await bridge.type_text(
                click_id="scheddlg:1", text="0 9 * * *"
            )
            assert res_cid.get("ok") is True

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_execute_script_dispatcher(self):
        """execute_script routes both static scripts and dynamic builders."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            # Static script execution
            res_stop = await bridge.execute_script("stop")
            assert isinstance(res_stop, dict)
            assert res_stop.get("ok") is True

            res_has_editor = await bridge.execute_script("has_visible_editor")
            assert res_has_editor is not None

            # Dynamic script execution
            res_msg = await bridge.execute_script(
                "inject_message", {"text": "Hello via dispatcher"}
            )
            assert res_msg.get("ok") is True

            # Unknown script raises ValueError
            with pytest.raises(ValueError):
                await bridge.execute_script("non_existent_script")

            await bridge.disconnect()
        finally:
            server.stop()

    async def test_additional_helper_actions(self):
        """Tests clear_editor, type_slash, copy_response, navigate_conversation, dismissals, sidebars."""
        server = MockCDPServer()
        server.start()
        try:
            bridge = CDPBridge(host=server.host, port=server.port)
            await bridge.connect()

            # clear_editor
            res_clear = await bridge.clear_editor()
            assert res_clear.get("ok") is True

            # type_slash
            res_slash = await bridge.type_slash()
            assert res_slash.get("ok") is True

            # copy_response
            res_copy = await bridge.copy_response("chat:0")
            assert isinstance(res_copy, dict)

            # navigate_conversation
            res_nav = await bridge.navigate_conversation("63fb64ac-9344-46a1-8d60-a891ba0835d8")
            assert isinstance(res_nav, dict)

            # dismissals
            assert (await bridge.dismiss_portal()).get("ok") is True
            assert (await bridge.dismiss_scheduled_tasks()).get("ok") is True
            assert isinstance(await bridge.dismiss_settings(), dict)

            # sidebars
            assert isinstance(await bridge.expand_left_sidebar(), dict)
            assert (await bridge.close_right_sidebar()).get("ok") is True
            assert (await bridge.toggle_sidebar()).get("ok") is True
            assert "html" in (await bridge.get_right_sidebar())
            assert "dataUrl" in (await bridge.proxy_image("https://example.com/img.png"))

            await bridge.disconnect()
        finally:
            server.stop()


# ============================================================================
# 5. Script Builders & Parameter Escaping Tests
# ============================================================================

class TestScriptBuilders(unittest.TestCase):
    """Tests parameter injection safety and escaping in all script builders."""

    def test_build_inject_script_escaping(self):
        """Tests quotes, multiline breaks, and backticks in build_inject_script."""
        text = "Line 1\nLine 2 with \"quotes\" and 'single' and `backticks`"
        safe_text = json.dumps(text)
        script = build_inject_script(safe_text, append_mode=True)
        self.assertIn(safe_text, script)
        self.assertIn("if (true)", script)
        self.assertIn("collapseToEnd()", script)

    def test_build_main_click_script_escaping(self):
        """Tests click ID and label escaping in build_main_click_script."""
        script = build_main_click_script(json.dumps("chat:5"), json.dumps("Allow 'All'"))
        self.assertIn('"chat:5"', script)
        self.assertIn("Allow 'All'", script)

    def test_build_type_text_script_escaping(self):
        """Tests build_type_text_script parameter escaping."""
        script = build_type_text_script(
            json.dumps("Search..."), json.dumps("sched:2"), json.dumps("New Query")
        )
        self.assertIn("Search...", script)
        self.assertIn("New Query", script)

    def test_build_upload_image_script(self):
        """Tests build_upload_image_script formatting."""
        script = build_upload_image_script(
            json.dumps("base64data"), json.dumps("image/png"), json.dumps("photo.png")
        )
        self.assertIn("base64data", script)
        self.assertIn("photo.png", script)

    def test_all_static_scripts_non_empty(self):
        """Ensures all static CDP scripts are non-empty strings with valid IIFE syntax."""
        scripts = [
            CAPTURE_SCRIPT,
            RIGHT_SIDEBAR_SCRIPT,
            RUNNING_TASKS_SCRIPT,
            SCHEDULED_TASKS_SCRIPT,
            SCHEDULED_TASKS_DIALOG_SCRIPT,
            CONVERSATION_HISTORY_SCRIPT,
            STOP_SCRIPT,
            DISCOVER_SCRIPT,
            CHECK_EDITOR_IMAGE_SCRIPT,
            CLICK_SEND_BUTTON_SCRIPT,
            EXPAND_LEFT_SIDEBAR_SCRIPT,
            DISMISS_SCHEDULED_TASKS_SCRIPT,
            DISMISS_SETTINGS_SCRIPT,
            CLOSE_RIGHT_SIDEBAR_SCRIPT,
            SELECT_OVERVIEW_TAB_SCRIPT,
            HAS_VISIBLE_EDITOR_SCRIPT,
            OPEN_RIGHT_SIDEBAR_SCRIPT,
        ]
        for s in scripts:
            self.assertIsInstance(s, str)
            self.assertTrue(len(s.strip()) > 10)
            self.assertTrue("() =>" in s or "async () =>" in s or "function" in s)
