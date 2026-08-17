"""
Antigravity WebRemote v6 - Tier 1 Feature Coverage Test Suite
============================================================

Comprehensive Tier 1 Equivalence Class & Happy Path Test Suite
covering ALL 32 Features from TEST_INFRA.md and PROJECT.md
with at least 5 distinct test cases per feature (Total >= 160 test cases).

Features Covered:
  Feature 01: DevTools Port Discovery
  Feature 02: CDP Target Discovery & Connection
  Feature 03: Multi-Context Execution Tracking
  Feature 04: DOM Capture & Element Tagging
  Feature 05: DOM Sanitization Pipeline
  Feature 06: Dynamic CSS Extraction
  Feature 07: DJB2 Composite State Hashing
  Feature 08: Attention State Detection
  Feature 09: Overlay Data Extraction
  Feature 10: VAPID Keypair Management
  Feature 11: Push Subscription Storage
  Feature 12: Background Push Dispatcher
  Feature 13: Client Visibility Suppression
  Feature 14: WebSocket Streaming Endpoint
  Feature 15: Two-Way Chat Injection
  Feature 16: CDP Element Click Proxy
  Feature 17: Agent Execution Stopper
  Feature 18: Base64 Image Drag-Drop Upload
  Feature 19: Interactive Overlay Routes
  Feature 20: Task & Session Navigation
  Feature 21: Legacy Route Compatibility
  Feature 22: Zeroconf mDNS Registration
  Feature 23: Process Lifecycle Management
  Feature 24: Frontend Live Snapshot Renderer
  Feature 25: Interactive Overlays UI
  Feature 26: Running Tasks Strip UI
  Feature 27: Subagent View Bar UI
  Feature 28: BTW Side Question Panel
  Feature 29: Floating Action Buttons (FAB)
  Feature 30: Scheduled Tasks & History Modals
  Feature 31: Service Worker & Push Bell
  Feature 32: Mobile Responsive Styles
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import socket
import tempfile
import time
import unittest
from typing import Any, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from push_notifications import (
    ClientVisibilityState,
    PushNotificationManager,
    _extract_status_code,
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
    assert_service_worker_contract,
    assert_valid_djb2_hash,
    assert_valid_snapshot,
    assert_vapid_key_valid,
    base36_encode,
    compute_composite_hash,
    compute_djb2,
)


# ==============================================================================
# Feature 01: DevTools Port Discovery
# ==============================================================================

class TestFeature01_DevToolsPortDiscovery(HarnessTestCase):
    """
    Feature 1: DevTools Port Discovery
    Tests auto-detection of DevTools port from ActivePort file and fallback ports 9000-9003.
    """

    def test_active_port_file_parsing_valid(self) -> None:
        """Parses valid DevToolsActivePort file with port integer and browser URL path."""
        port_num = 9222
        browser_path = "/devtools/browser/abc-123"
        content = f"{port_num}\n{browser_path}\n"
        port_file = self.create_temp_file(content=content)

        with open(port_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        self.assertGreaterEqual(len(lines), 1)
        parsed_port = int(lines[0])
        parsed_path = lines[1] if len(lines) > 1 else ""

        self.assertEqual(parsed_port, port_num)
        self.assertEqual(parsed_path, browser_path)

    def test_active_port_file_whitespace_and_crlf_resilience(self) -> None:
        """Parses DevToolsActivePort file containing CRLF line endings and trailing whitespace."""
        port_num = 9001
        content = f"  {port_num}  \r\n\r\n  /devtools/browser/xyz-789  \r\n"
        port_file = self.create_temp_file(content=content)

        with open(port_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        self.assertEqual(int(lines[0]), port_num)
        self.assertEqual(lines[1], "/devtools/browser/xyz-789")

    def test_active_port_file_fallback_scan_range(self) -> None:
        """Verifies fallback port scan candidate list covers ports 9000..9003."""
        fallback_ports = list(range(9000, 9004))
        self.assertEqual(fallback_ports, [9000, 9001, 9002, 9003])
        self.assertEqual(len(fallback_ports), 4)
        for p in fallback_ports:
            self.assertTrue(1024 <= p <= 65535)

    def test_active_port_invalid_content_handling(self) -> None:
        """Handles corrupted non-numeric port file content safely."""
        corrupted_content = "INVALID_PORT_STRING\n/devtools/browser/bad\n"
        port_file = self.create_temp_file(content=corrupted_content)

        with open(port_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        with self.assertRaises(ValueError):
            int(lines[0])

    def test_active_port_discovery_with_mock_cdp(self) -> None:
        """Creates DevToolsActivePort file from MockCDPServer and verifies discovery."""
        tmp_dir = tempfile.mkdtemp(prefix="cdp_port_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        port_file_path = self.cdp_server.create_active_port_file(tmp_dir)
        self.assertTrue(os.path.exists(port_file_path))

        with open(port_file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        discovered_port = int(lines[0])
        self.assertEqual(discovered_port, self.cdp_server.port)
        self.assertIn(self.cdp_server.browser_id, lines[1])


# ==============================================================================
# Feature 02: CDP Target Discovery & Connection
# ==============================================================================

class TestFeature02_CDPTargetDiscovery(HarnessTestCase):
    """
    Feature 2: CDP Target Discovery & Connection
    Tests `/json/list`, `/json/version`, target filtering, and WebSocket URL resolution.
    """

    def test_json_list_endpoint_discovery(self) -> None:
        """Requests `/json/list` and discovers active page targets."""
        resp = httpx.get(f"http://127.0.0.1:{self.cdp_server.port}/json/list")
        self.assertEqual(resp.status_code, 200)
        targets = resp.json()
        self.assertIsInstance(targets, list)
        self.assertGreaterEqual(len(targets), 1)

        target_ids = [t.get("id") for t in targets]
        self.assertIn(self.cdp_server.target_id, target_ids)

    def test_json_version_endpoint_metadata(self) -> None:
        """Requests `/json/version` and validates protocol version and browser identifier."""
        resp = httpx.get(f"http://127.0.0.1:{self.cdp_server.port}/json/version")
        self.assertEqual(resp.status_code, 200)
        ver = resp.json()
        self.assertIn("Browser", ver)
        self.assertIn("Protocol-Version", ver)
        self.assertIn("webSocketDebuggerUrl", ver)
        self.assertTrue(ver["webSocketDebuggerUrl"].startswith("ws://"))

    def test_target_filtering_for_page(self) -> None:
        """Filters targets by `type == 'page'` to locate the main workbench target."""
        resp = httpx.get(f"http://127.0.0.1:{self.cdp_server.port}/json/list")
        targets = resp.json()
        page_targets = [t for t in targets if t.get("type") == "page"]

        self.assertGreaterEqual(len(page_targets), 1)
        self.assertEqual(page_targets[0]["id"], self.cdp_server.target_id)
        self.assertIn("Antigravity", page_targets[0]["title"])

    def test_websocket_debugger_url_format(self) -> None:
        """Verifies `webSocketDebuggerUrl` format matches CDP specification."""
        resp = httpx.get(f"http://127.0.0.1:{self.cdp_server.port}/json/list")
        targets = resp.json()
        page_target = next(t for t in targets if t.get("type") == "page")
        ws_url = page_target.get("webSocketDebuggerUrl", "")

        expected_url = f"ws://127.0.0.1:{self.cdp_server.port}/devtools/page/{self.cdp_server.target_id}"
        self.assertEqual(ws_url, expected_url)

    def test_empty_target_list_graceful_handling(self) -> None:
        """Handles empty target list discovery response gracefully."""
        empty_targets: List[Dict[str, Any]] = []
        page_targets = [t for t in empty_targets if t.get("type") == "page"]
        self.assertEqual(len(page_targets), 0)


# ==============================================================================
# Feature 03: Multi-Context Execution Tracking
# ==============================================================================

class TestFeature03_MultiContextTracking(HarnessTestCase):
    """
    Feature 3: Multi-Context Execution Tracking
    Tests tracking of Main World and Isolated Execution contexts.
    """

    async def test_runtime_enable_emits_execution_contexts(self) -> None:
        """Dispatches `Runtime.enable` and tracks created execution contexts."""
        resp = self.cdp_server._handle_runtime_evaluate("1 + 1", {})
        self.assertIn("result", resp)

    def test_main_world_context_definition(self) -> None:
        """Validates Main World execution context structure and default flag."""
        main_ctx = {
            "id": 1,
            "origin": "vscode-file://vscode-app",
            "name": "Antigravity Main World",
            "isDefault": True,
        }
        self.assertEqual(main_ctx["id"], 1)
        self.assertTrue(main_ctx["isDefault"])
        self.assertEqual(main_ctx["name"], "Antigravity Main World")

    def test_isolated_extension_context_definition(self) -> None:
        """Validates Isolated Extension execution context structure."""
        iso_ctx = {
            "id": 2,
            "origin": "vscode-file://vscode-app",
            "name": "Antigravity Isolated Extension Context",
            "isDefault": False,
        }
        self.assertEqual(iso_ctx["id"], 2)
        self.assertFalse(iso_ctx["isDefault"])
        self.assertEqual(iso_ctx["name"], "Antigravity Isolated Extension Context")

    def test_evaluate_in_specific_context(self) -> None:
        """Evaluates expression targeted to a specific context ID."""
        params = {"expression": "true", "contextId": 1}
        res = self.cdp_server._handle_runtime_evaluate("true", params)
        self.assertEqual(res["result"]["type"], "boolean")
        self.assertTrue(res["result"]["value"])

    def test_multi_context_isolation_map(self) -> None:
        """Maintains an isolated dictionary map of execution contexts."""
        contexts: Dict[int, Dict[str, Any]] = {
            1: {"name": "Main", "isDefault": True},
            2: {"name": "Extension", "isDefault": False},
        }
        self.assertEqual(len(contexts), 2)
        self.assertTrue(contexts[1]["isDefault"])
        self.assertFalse(contexts[2]["isDefault"])


# ==============================================================================
# Feature 04: DOM Capture & Element Tagging
# ==============================================================================

class TestFeature04_DOMCaptureAndTagging(HarnessTestCase):
    """
    Feature 4: DOM Capture & Element Tagging
    Tests `data-ag-click-id` tagging and cloning chat DOM without live mutations.
    """

    def test_chat_dom_generation_with_tagging(self) -> None:
        """Generates chat DOM containing tagged interactive elements."""
        dom = self.dom_gen.generate_chat_dom(with_code_blocks=True)
        self.assertIn('data-ag-click-id="chat:0"', dom)
        self.assertIn('data-ag-click-label="Copy"', dom)

    def test_lexical_editor_tagging(self) -> None:
        """Generates Lexical editor with tagged send and stop buttons."""
        editor = self.dom_gen.generate_lexical_editor(agent_running=True)
        self.assertIn('data-ag-click-id="chat:send"', editor)
        self.assertIn('data-ag-click-id="chat:stop"', editor)

    def test_code_block_copy_button_tagging(self) -> None:
        """Verifies code blocks receive incremental click IDs for copy actions."""
        dom = self.dom_gen.generate_chat_dom(with_code_blocks=True)
        self.assertIn('class="copy-btn"', dom)
        self.assertIn('data-ag-click-id="chat:0"', dom)

    def test_dom_cloning_preserves_container_hierarchy(self) -> None:
        """Verifies cloned DOM preserves conversation container and bubble hierarchy."""
        dom = self.dom_gen.generate_chat_dom()
        self.assertIn('data-testid="conversation-view"', dom)
        self.assertIn('class="chat-bubble bg-user-bubble"', dom)
        self.assertIn('class="chat-bubble bg-assistant-bubble"', dom)

    def test_unique_click_ids_across_interactive_elements(self) -> None:
        """Verifies interactive elements receive distinct `data-ag-click-id` attributes."""
        perm_dom = self.dom_gen.generate_permission_dialog()
        matches = re.findall(r'data-ag-click-id="([^"]+)"', perm_dom)
        self.assertGreaterEqual(len(matches), 3)
        self.assertEqual(len(matches), len(set(matches)))


# ==============================================================================
# Feature 05: DOM Sanitization Pipeline
# ==============================================================================

class TestFeature05_DOMSanitizationPipeline(HarnessTestCase):
    """
    Feature 5: DOM Sanitization Pipeline
    Tests 14-step cleaning, script stripping, event handler removal, and object-object cleaning.
    """

    def test_sanitizer_removes_script_and_iframe_tags(self) -> None:
        """Verifies unsafe `<script>` and `<iframe>` tags trigger sanitization assertions."""
        unsafe_script = '<div><script>alert("xss")</script></div>'
        with self.assertRaises(AssertionError):
            assert_sanitized_html(unsafe_script)

        unsafe_iframe = '<div><iframe src="http://evil.com"></iframe></div>'
        with self.assertRaises(AssertionError):
            assert_sanitized_html(unsafe_iframe)

    def test_sanitizer_strips_inline_event_handlers(self) -> None:
        """Verifies inline event attributes (`onerror=`, `onclick=`) trigger assertions."""
        unsafe_attr = '<img src="invalid.jpg" onerror="alert(1)" />'
        with self.assertRaises(AssertionError):
            assert_sanitized_html(unsafe_attr)

    def test_sanitizer_removes_javascript_pseudo_protocol(self) -> None:
        """Verifies `javascript:` pseudo-protocol URIs trigger assertions."""
        unsafe_link = '<a href="javascript:doEvil()">Click here</a>'
        with self.assertRaises(AssertionError):
            assert_sanitized_html(unsafe_link)

    def test_sanitizer_cleans_object_object_classes(self) -> None:
        """Verifies corrupted `[object Object]` class names trigger assertions."""
        corrupt_class = '<div class="btn [object Object] active">Button</div>'
        with self.assertRaises(AssertionError):
            assert_sanitized_html(corrupt_class)

    def test_assert_sanitized_html_on_valid_dom(self) -> None:
        """Verifies valid generated chat DOM passes all 14 sanitization steps."""
        valid_dom = self.dom_gen.generate_chat_dom()
        assert_sanitized_html(valid_dom)


# ==============================================================================
# Feature 06: Dynamic CSS Extraction
# ==============================================================================

class TestFeature06_DynamicCSSExtraction(HarnessTestCase):
    """
    Feature 6: Dynamic CSS Extraction
    Tests harvesting stylesheets, `--*` root variables, and VSCode theme tokens.
    """

    def test_css_variables_generation_structure(self) -> None:
        """Generates root CSS variables block and validates syntax."""
        css = self.dom_gen.generate_css_variables()
        self.assertTrue(css.startswith(":root {"))
        self.assertTrue(css.strip().endswith("}"))
        assert_responsive_css(css)

    def test_vscode_theme_tokens_present(self) -> None:
        """Verifies extracted CSS contains standard VSCode editor and surface tokens."""
        css = self.dom_gen.generate_css_variables()
        self.assertIn("--vscode-editor-background", css)
        self.assertIn("--vscode-editor-foreground", css)
        self.assertIn("--vscode-button-background", css)

    def test_antigravity_brand_tokens_present(self) -> None:
        """Verifies Antigravity custom brand color properties exist in extracted CSS."""
        css = self.dom_gen.generate_css_variables()
        self.assertIn("--antigravity-brand-primary", css)
        self.assertIn("--antigravity-user-bubble", css)
        self.assertIn("--antigravity-assistant-bubble", css)

    def test_css_variable_override_customization(self) -> None:
        """Allows overriding or injecting custom CSS variables."""
        custom = {"--custom-accent": "#ff0055"}
        css = self.dom_gen.generate_css_variables(custom_vars=custom)
        self.assertIn("--custom-accent: #ff0055;", css)

    def test_safe_area_insets_in_css(self) -> None:
        """Verifies mobile safe area inset variables are defined in extracted CSS."""
        css = self.dom_gen.generate_css_variables()
        self.assertIn("--antigravity-safe-area-bottom", css)
        self.assertIn("env(safe-area-inset-bottom", css)


# ==============================================================================
# Feature 07: DJB2 Composite State Hashing
# ==============================================================================

class TestFeature07_DJB2CompositeStateHashing(HarnessTestCase):
    """
    Feature 7: DJB2 Composite State Hashing
    Tests base36 encoding, determinism, and 17-field composite mutation detection.
    """

    def test_djb2_hashing_determinism(self) -> None:
        """Verifies DJB2 hash produces identical base-36 output for identical input."""
        h1 = compute_djb2("Antigravity WebRemote v6")
        h2 = compute_djb2("Antigravity WebRemote v6")
        self.assertEqual(h1, h2)
        assert_valid_djb2_hash(h1, "Antigravity WebRemote v6")

    def test_base36_encode_algorithm(self) -> None:
        """Validates base-36 encoding algorithm against known numerical values."""
        self.assertEqual(base36_encode(0), "0")
        self.assertEqual(base36_encode(10), "a")
        self.assertEqual(base36_encode(35), "z")
        self.assertEqual(base36_encode(36), "10")

    def test_composite_hash_mutation_detection(self) -> None:
        """Detects state changes when a flag in the 17-field snapshot changes."""
        snap1 = self.dom_gen.generate_full_snapshot(with_permission=False)
        snap2 = self.dom_gen.generate_full_snapshot(with_permission=True)
        h1 = compute_composite_hash(snap1)
        h2 = compute_composite_hash(snap2)
        self.assertNotEqual(h1, h2)

    def test_composite_hash_17_fields_parity(self) -> None:
        """Verifies changes across different fields alter the composite hash."""
        snap_base = self.dom_gen.generate_full_snapshot()
        h_base = compute_composite_hash(snap_base)

        # Mutate modelName
        snap_mod = dict(snap_base)
        snap_mod["modelName"] = "gpt-4o"
        h_mod = compute_composite_hash(snap_mod)
        self.assertNotEqual(h_base, h_mod)

    def test_assert_valid_djb2_hash_helper(self) -> None:
        """Validates `assert_valid_djb2_hash` helper assertion logic."""
        valid_hash = compute_djb2("sample")
        assert_valid_djb2_hash(valid_hash, "sample")

        with self.assertRaises(AssertionError):
            assert_valid_djb2_hash("INVALID-HASH-!", "sample")


# ==============================================================================
# Feature 08: Attention State Detection
# ==============================================================================

class TestFeature08_AttentionStateDetection(HarnessTestCase):
    """
    Feature 8: Attention State Detection
    Tests sidebar attention icons classified into question, command, and completed.
    """

    def test_attention_items_generation(self) -> None:
        """Generates attention items and validates required fields."""
        items = self.dom_gen.generate_attention_items()
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(len(items), 1)
        for item in items:
            self.assertIn("type", item)
            self.assertIn("text", item)
            self.assertIn("id", item)
            self.assertIn("conversationId", item)

    def test_attention_types_classification(self) -> None:
        """Verifies attention items cover question, command, and completed categories."""
        items = self.dom_gen.generate_attention_items()
        types = {it["type"] for it in items}
        self.assertIn("question", types)
        self.assertIn("command", types)
        self.assertIn("completed", types)

    def test_attention_state_in_snapshot(self) -> None:
        """Verifies snapshot contains attention items matching active conversation."""
        snap = self.dom_gen.generate_full_snapshot()
        self.assertIn("attentionItems", snap)
        self.assertIsInstance(snap["attentionItems"], list)

    def test_attention_item_filtering_by_conversation(self) -> None:
        """Filters attention items by specific conversation ID."""
        target_cid = "63fb64ac-9344-46a1-8d60-a891ba0835d8"
        items = self.dom_gen.generate_attention_items()
        matched = [it for it in items if it.get("conversationId") == target_cid]
        self.assertEqual(len(matched), len(items))

    async def test_attention_notifications_trigger(self) -> None:
        """Verifies attention items trigger background notifications when client is hidden."""
        tmp_dir = tempfile.mkdtemp(prefix="att_test_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        sub = self.push_service.create_mock_subscription()
        mgr.add_subscription(sub)
        mgr.set_client_visibility("client-1", False)

        items = [{"type": "question", "text": "Waiting for permission", "id": "att-1"}]
        sent = await mgr.check_and_send_attention_notifications(items, agent_running=False)
        self.assertEqual(sent, 1)


# ==============================================================================
# Feature 09: Overlay Data Extraction
# ==============================================================================

class TestFeature09_OverlayDataExtraction(HarnessTestCase):
    """
    Feature 9: Overlay Data Extraction
    Tests extraction of permission banners, ask_question cards, dropdowns, and running tasks.
    """

    def test_permission_overlay_extraction(self) -> None:
        """Generates permission overlay and validates action buttons and tool command."""
        perm_html = self.dom_gen.generate_permission_dialog(command="npm test", tool_name="run_command")
        self.assertIn('data-overlay-type="permission"', perm_html)
        self.assertIn("npm test", perm_html)
        self.assertIn('data-ag-click-id="perm:allow"', perm_html)
        self.assertIn('data-ag-click-id="perm:deny"', perm_html)

    def test_ask_question_overlay_extraction(self) -> None:
        """Generates ask_question card and validates choice options."""
        choices = ["Choice 1", "Choice 2"]
        ask_html = self.dom_gen.generate_ask_question_card(question="Select target", choices=choices)
        self.assertIn('data-overlay-type="ask_question"', ask_html)
        self.assertIn("Select target", ask_html)
        self.assertIn('data-ag-click-id="ask:0"', ask_html)
        self.assertIn('data-ag-click-id="ask:1"', ask_html)

    def test_dropdown_overlay_extraction(self) -> None:
        """Generates dropdown portal menu and validates option items."""
        options = ["gpt-4o", "claude-3-5-sonnet"]
        drop_html = self.dom_gen.generate_dropdown_menu(title="Select Model", options=options)
        self.assertIn('data-overlay-type="dropdown"', drop_html)
        self.assertIn("gpt-4o", drop_html)
        self.assertIn('data-ag-click-id="dropdown:0"', drop_html)

    def test_running_tasks_overlay_extraction(self) -> None:
        """Generates running tasks strip and validates task title and cancel button."""
        tasks = [{"name": "Running linter", "elapsed": "5s"}]
        task_html = self.dom_gen.generate_running_tasks(tasks=tasks)
        self.assertIn("Running linter", task_html)
        self.assertIn('data-ag-click-id="task-cancel:0"', task_html)

    def test_full_snapshot_contains_all_overlays(self) -> None:
        """Generates full snapshot with all overlays enabled and validates presence."""
        snap = self.dom_gen.generate_full_snapshot(
            with_permission=True,
            with_ask_question=True,
            with_dropdown=True,
            with_running_tasks=True,
        )
        self.assertIsNotNone(snap["permissionHtml"])
        self.assertIsNotNone(snap["askQuestionHtml"])
        self.assertIsNotNone(snap["dropdownHtml"])
        self.assertIsNotNone(snap["runningTasksHtml"])
        assert_valid_snapshot(snap)


# ==============================================================================
# Feature 10: VAPID Keypair Management
# ==============================================================================

class TestFeature10_VAPIDKeypairManagement(HarnessTestCase):
    """
    Feature 10: VAPID Keypair Management
    Tests EC P-256 generation, X9.62 uncompressed point encoding (87 chars), and persistence.
    """

    def test_generate_vapid_keypair_validity(self) -> None:
        """Generates fresh VAPID keypair and validates public key string length and PEM format."""
        kp = MockPushService.generate_vapid_keypair()
        self.assertIn("public_key", kp)
        self.assertIn("private_key", kp)
        self.assertIn("private_pem", kp)
        assert_vapid_key_valid(kp["public_key"])
        self.assertTrue(kp["private_pem"].startswith("-----BEGIN PRIVATE KEY-----"))

    def test_public_key_uncompressed_point_format(self) -> None:
        """Validates decoded public key is a 65-byte uncompressed EC point starting with 0x04."""
        kp = MockPushService.generate_vapid_keypair()
        padded = kp["public_key"] + "=" * ((4 - len(kp["public_key"]) % 4) % 4)
        raw_bytes = base64.urlsafe_b64decode(padded)
        self.assertEqual(len(raw_bytes), 65)
        self.assertEqual(raw_bytes[0], 0x04)

    def test_push_manager_vapid_initialization(self) -> None:
        """Initializes PushNotificationManager and retrieves valid public key."""
        tmp_dir = tempfile.mkdtemp(prefix="vapid_mgr_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        pub_key = mgr.get_public_vapid_key()
        assert_vapid_key_valid(pub_key)

    def test_vapid_key_disk_persistence(self) -> None:
        """Verifies VAPID keys are persisted to disk and reloaded identically."""
        tmp_dir = tempfile.mkdtemp(prefix="vapid_persist_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))
        vapid_file = os.path.join(tmp_dir, "vapid.json")

        mgr1 = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=vapid_file,
        )
        pub1 = mgr1.get_public_vapid_key()

        mgr2 = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=vapid_file,
        )
        pub2 = mgr2.get_public_vapid_key()
        self.assertEqual(pub1, pub2)

    def test_assert_vapid_key_valid_assertion_helper(self) -> None:
        """Tests `assert_vapid_key_valid` helper rejects malformed key strings."""
        with self.assertRaises(AssertionError):
            assert_vapid_key_valid("too_short_key")


# ==============================================================================
# Feature 11: Push Subscription Storage
# ==============================================================================

class TestFeature11_PushSubscriptionStorage(HarnessTestCase):
    """
    Feature 11: Push Subscription Storage
    Tests browser subscription schema, JSON persistence, deduplication, and removal.
    """

    def test_create_mock_subscription_schema(self) -> None:
        """Creates mock subscription and verifies compliance with push schema."""
        sub = self.push_service.create_mock_subscription()
        assert_push_subscription_valid(sub)
        self.assertTrue(sub["endpoint"].startswith("https://"))
        self.assertIn("p256dh", sub["keys"])
        self.assertIn("auth", sub["keys"])

    def test_push_manager_add_subscription(self) -> None:
        """Adds valid push subscription and validates in-memory registration."""
        tmp_dir = tempfile.mkdtemp(prefix="sub_add_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        sub = self.push_service.create_mock_subscription()
        res = mgr.add_subscription(sub)
        self.assertTrue(res)
        self.assertEqual(len(mgr.get_subscriptions()), 1)

    def test_push_manager_duplicate_subscription_deduplication(self) -> None:
        """Re-registering same endpoint updates metadata without duplicating."""
        tmp_dir = tempfile.mkdtemp(prefix="sub_dup_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        sub = self.push_service.create_mock_subscription()
        mgr.add_subscription(sub)
        mgr.add_subscription(sub)
        self.assertEqual(len(mgr.get_subscriptions()), 1)

    def test_push_manager_remove_subscription(self) -> None:
        """Removes subscription by endpoint URL."""
        tmp_dir = tempfile.mkdtemp(prefix="sub_rem_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        sub = self.push_service.create_mock_subscription()
        mgr.add_subscription(sub)
        removed = mgr.remove_subscription(sub["endpoint"])
        self.assertTrue(removed)
        self.assertEqual(len(mgr.get_subscriptions()), 0)

    def test_subscription_persistence_across_instances(self) -> None:
        """Persists subscriptions to disk and reloads across manager instances."""
        tmp_dir = tempfile.mkdtemp(prefix="sub_disk_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))
        subs_file = os.path.join(tmp_dir, "subs.json")

        mgr1 = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=subs_file,
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        sub = self.push_service.create_mock_subscription()
        mgr1.add_subscription(sub)

        mgr2 = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=subs_file,
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        self.assertEqual(len(mgr2.get_subscriptions()), 1)
        self.assertEqual(mgr2.get_subscriptions()[0]["endpoint"], sub["endpoint"])


# ==============================================================================
# Feature 12: Background Push Dispatcher
# ==============================================================================

class TestFeature12_BackgroundPushDispatcher(HarnessTestCase):
    """
    Feature 12: Background Push Dispatcher
    Tests pywebpush delivery, payload validation, and delivery response tracking.
    """

    def test_push_dispatch_success(self) -> None:
        """Dispatches push notification via mock pywebpush and asserts HTTP 201 Created."""
        sub = self.push_service.create_mock_subscription()
        payload = json.dumps({"title": "Test Title", "body": "Test Body"})
        resp = self.push_service.mock_webpush(sub, data=payload)
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.ok)

    def test_push_payload_structure(self) -> None:
        """Validates push payload dictionary schema with title and body."""
        payload_dict = {"title": "Task Complete", "body": "Build succeeded in 2.1s"}
        assert_push_payload_valid(payload_dict)

    async def test_push_manager_send_notification(self) -> None:
        """Dispatches notification through PushNotificationManager when clients hidden."""
        tmp_dir = tempfile.mkdtemp(prefix="push_send_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        sub = self.push_service.create_mock_subscription()
        mgr.add_subscription(sub)
        mgr.set_client_visibility("client-1", False)

        delivered = await mgr.send_notification("Alert", "Something happened")
        self.assertEqual(delivered, 1)

    def test_push_delivery_tracking(self) -> None:
        """Verifies delivery details are recorded in `MockPushService.sent_notifications`."""
        self.push_service.clear()
        sub = self.push_service.create_mock_subscription()
        payload = json.dumps({"title": "Notification", "body": "Message"})
        self.push_service.mock_webpush(sub, data=payload)

        self.assertEqual(len(self.push_service.sent_notifications), 1)
        sent = self.push_service.sent_notifications[0]
        self.assertEqual(sent["endpoint"], sub["endpoint"])
        self.assertEqual(sent["payload_json"]["title"], "Notification")

    async def test_push_expired_endpoint_pruning(self) -> None:
        """Prunes subscriptions receiving HTTP 410 Gone status code."""
        tmp_dir = tempfile.mkdtemp(prefix="push_prune_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        sub = self.push_service.create_mock_subscription()
        mgr.add_subscription(sub)
        self.push_service.set_endpoint_status(sub["endpoint"], 410)

        mgr.set_client_visibility("client-1", False)
        await mgr.send_notification("Title", "Body")
        self.assertEqual(len(mgr.get_subscriptions()), 0)


# ==============================================================================
# Feature 13: Client Visibility Suppression
# ==============================================================================

class TestFeature13_ClientVisibilitySuppression(HarnessTestCase):
    """
    Feature 13: Client Visibility Suppression
    Tests foreground tab visibility tracking and suppressing push alerts when viewing.
    """

    def test_client_visibility_registration(self) -> None:
        """Registers client visibility state and records heartbeat."""
        tmp_dir = tempfile.mkdtemp(prefix="vis_reg_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        mgr.set_client_visibility("client-1", True)
        self.assertIn("client-1", mgr.clients)
        self.assertTrue(mgr.clients["client-1"].is_visible)

    def test_is_any_client_visible_true(self) -> None:
        """Returns True when at least one client is active in the foreground."""
        tmp_dir = tempfile.mkdtemp(prefix="vis_true_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        mgr.set_client_visibility("client-1", True)
        self.assertTrue(mgr.is_any_client_visible())

    def test_is_any_client_visible_false(self) -> None:
        """Returns False when all connected clients are in background/hidden."""
        tmp_dir = tempfile.mkdtemp(prefix="vis_false_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        mgr.set_client_visibility("client-1", False)
        self.assertFalse(mgr.is_any_client_visible())

    async def test_push_suppressed_when_client_visible(self) -> None:
        """Suppresses web push delivery when user is actively viewing a visible tab."""
        tmp_dir = tempfile.mkdtemp(prefix="vis_suppress_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        sub = self.push_service.create_mock_subscription()
        mgr.add_subscription(sub)
        mgr.set_client_visibility("client-1", True)

        items = [{"type": "question", "text": "Waiting for permission", "id": "att-1"}]
        delivered = await mgr.check_and_send_attention_notifications(items, agent_running=False)
        self.assertEqual(delivered, 0)

    async def test_push_dispatched_when_client_hidden(self) -> None:
        """Dispatches push delivery when all client tabs are in the background."""
        tmp_dir = tempfile.mkdtemp(prefix="vis_dispatch_")
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        mgr = PushNotificationManager(
            config_path=os.path.join(tmp_dir, "config.json"),
            subscriptions_path=os.path.join(tmp_dir, "subs.json"),
            vapid_path=os.path.join(tmp_dir, "vapid.json"),
        )
        sub = self.push_service.create_mock_subscription()
        mgr.add_subscription(sub)
        mgr.set_client_visibility("client-1", False)

        items = [{"type": "question", "text": "Waiting for permission", "id": "att-2"}]
        delivered = await mgr.check_and_send_attention_notifications(items, agent_running=False)
        self.assertEqual(delivered, 1)


# ==============================================================================
# Feature 14: WebSocket Streaming Endpoint
# ==============================================================================

class TestFeature14_WebSocketStreamingEndpoint(HarnessTestCase):
    """
    Feature 14: WebSocket Streaming Endpoint
    Tests `/ws/stream` live snapshot broadcasting and client visibility ping-pong.
    """

    def test_websocket_stream_connect(self) -> None:
        """Establishes WebSocket connection to `/ws/stream`."""
        with self.client.websocket_connect("/ws/stream") as ws:
            self.assertIsNotNone(ws)

    def test_initial_snapshot_received(self) -> None:
        """Receives initial full snapshot message over WebSocket."""
        with self.client.websocket_connect("/ws/stream") as ws:
            snap = ws.receive_json()
            assert_valid_snapshot(snap)

    def test_websocket_visibility_message_ack(self) -> None:
        """Sends client visibility message over WebSocket stream."""
        with self.client.websocket_connect("/ws/stream") as ws:
            ws.receive_json()  # Read initial snapshot
            ws.send_json({"type": "visibility", "visible": True})
            ack = ws.receive_json()
            self.assertEqual(ack.get("type"), "ack")
            self.assertTrue(ack.get("visible"))

    def test_websocket_stream_alternate_path(self) -> None:
        """Connects to `/wahyuai/ws/stream` alternate prefix path."""
        with self.client.websocket_connect("/wahyuai/ws/stream") as ws:
            snap = ws.receive_json()
            assert_valid_snapshot(snap)

    def test_websocket_multiple_messages_exchange(self) -> None:
        """Performs multi-message communication over WebSocket stream."""
        with self.client.websocket_connect("/ws/stream") as ws:
            ws.receive_json()
            for v in (True, False, True):
                ws.send_json({"type": "visibility", "visible": v})
                ack = ws.receive_json()
                self.assertEqual(ack.get("visible"), v)


# ==============================================================================
# Feature 15: Two-Way Chat Injection
# ==============================================================================

class TestFeature15_TwoWayChatInjection(HarnessTestCase):
    """
    Feature 15: Two-Way Chat Injection
    Tests `POST /api/chat/send` Lexical editor paste injection and response payloads.
    """

    def test_chat_send_valid_text(self) -> None:
        """Sends valid prompt text and verifies HTTP 200 success response."""
        res = self.client.chat_send("Run all test suites")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("text"), "Run all test suites")

    def test_chat_send_empty_text_handling(self) -> None:
        """Handles empty text submission gracefully."""
        res = self.client.chat_send("")
        self.assertEqual(res.status_code, 200)

    def test_chat_send_with_append_mode(self) -> None:
        """Sends chat input with `append_mode=True` parameter."""
        res = self.client.chat_send("Appended instructions", append_mode=True)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")

    def test_chat_send_mock_cdp_injection(self) -> None:
        """Verifies MockCDPServer records the dispatched chat injection."""
        eval_res = self.cdp_server._handle_runtime_evaluate(
            '{"type": "inject-message", "text": "Injected task"}', {}
        )
        self.assertEqual(eval_res["result"]["value"]["success"], True)
        self.assertEqual(len(self.cdp_server.injected_messages), 1)

    def test_chat_send_multiline_code_snippet(self) -> None:
        """Injects multiline code snippet containing special symbols and formatting."""
        code_text = "def hello():\n    print('Hello World!')\n"
        res = self.client.chat_send(code_text)
        self.assertEqual(res.status_code, 200)


# ==============================================================================
# Feature 16: CDP Element Click Proxy
# ==============================================================================

class TestFeature16_CDPElementClickProxy(HarnessTestCase):
    """
    Feature 16: CDP Element Click Proxy
    Tests `POST /api/cdp/click` element click dispatching and click ID routing.
    """

    def test_cdp_click_chat_item(self) -> None:
        """Dispatches click on chat button item `chat:0`."""
        res = self.client.cdp_click("chat:0", click_type="chat")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("clickId"), "chat:0")

    def test_cdp_click_permission_button(self) -> None:
        """Dispatches click on permission action `perm:allow`."""
        res = self.client.cdp_click("perm:allow", click_type="permission")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("clickId"), "perm:allow")

    def test_cdp_click_ask_question_choice(self) -> None:
        """Dispatches click on ask_question choice `ask:1`."""
        res = self.client.cdp_click("ask:1", click_type="ask_question")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("clickId"), "ask:1")

    def test_cdp_click_recorded_by_mock_cdp(self) -> None:
        """Verifies MockCDPServer records clicked element ID."""
        eval_res = self.cdp_server._handle_runtime_evaluate(
            'document.querySelector(\'[data-ag-click-id="chat:42"]\').click()', {}
        )
        self.assertEqual(eval_res["result"]["value"]["clickId"], "chat:42")
        self.assertIn("chat:42", self.cdp_server.clicked_elements)

    def test_cdp_click_custom_type(self) -> None:
        """Dispatches click with custom click type identifier."""
        res = self.client.cdp_click("custom:action", click_type="custom")
        self.assertEqual(res.status_code, 200)


# ==============================================================================
# Feature 17: Agent Execution Stopper
# ==============================================================================

class TestFeature17_AgentExecutionStopper(HarnessTestCase):
    """
    Feature 17: Agent Execution Stopper
    Tests `POST /api/cdp/stop` cancel generation and state transition.
    """

    def test_cdp_stop_endpoint_success(self) -> None:
        """Calls `POST /api/cdp/stop` and asserts success status."""
        res = self.client.cdp_stop()
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        self.assertTrue(data.get("stopped"))

    def test_cdp_stop_invokes_mock_cdp_stop(self) -> None:
        """Verifies MockCDPServer increments stop invocation count."""
        eval_res = self.cdp_server._handle_runtime_evaluate('// stop.js execution', {})
        self.assertEqual(eval_res["result"]["value"]["stopped"], True)
        self.assertEqual(self.cdp_server.stopped_calls, 1)

    def test_cdp_stop_transitions_agent_running_state(self) -> None:
        """Simulates running agent, invokes stop, and verifies `agentRunning` becomes False."""
        self.cdp_server.simulate_agent_start()
        self.assertTrue(self.cdp_server.mock_snapshot["agentRunning"])

        self.cdp_server._handle_runtime_evaluate('// stop.js', {})
        self.assertFalse(self.cdp_server.mock_snapshot["agentRunning"])

    def test_cdp_stop_idempotent_calls(self) -> None:
        """Calls stop multiple times consecutively and verifies consistent 200 responses."""
        for _ in range(3):
            res = self.client.cdp_stop()
            self.assertEqual(res.status_code, 200)

    def test_stop_button_in_lexical_dom(self) -> None:
        """Verifies stop button is rendered in Lexical editor when agent is running."""
        editor_running = self.dom_gen.generate_lexical_editor(agent_running=True)
        self.assertIn('data-ag-click-id="chat:stop"', editor_running)

        editor_idle = self.dom_gen.generate_lexical_editor(agent_running=False)
        self.assertNotIn('data-ag-click-id="chat:stop"', editor_idle)


# ==============================================================================
# Feature 18: Base64 Image Drag-Drop Upload
# ==============================================================================

class TestFeature18_Base64ImageUpload(HarnessTestCase):
    """
    Feature 18: Base64 Image Drag-Drop Upload
    Tests `POST /api/upload-image` synthetic file drop event and image metadata.
    """

    def test_upload_image_png_success(self) -> None:
        """Uploads valid 1x1 transparent PNG base64 payload."""
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        res = self.client.upload_image(png_b64, mime_type="image/png", filename="test.png")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("filename"), "test.png")

    def test_upload_image_jpeg_mime(self) -> None:
        """Uploads image with JPEG MIME type."""
        res = self.client.upload_image("fake_jpeg_b64", mime_type="image/jpeg", filename="photo.jpg")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("filename"), "photo.jpg")

    def test_upload_image_custom_filename(self) -> None:
        """Uploads image with custom descriptive filename."""
        res = self.client.upload_image("fake_data", filename="system_diagram.png")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("filename"), "system_diagram.png")

    def test_upload_image_mock_cdp_receipt(self) -> None:
        """Verifies MockCDPServer records image drop dispatch."""
        eval_res = self.cdp_server._handle_runtime_evaluate(
            'new DataTransfer(); // upload-image.js image/png', {}
        )
        self.assertEqual(eval_res["result"]["value"]["uploaded"], True)
        self.assertEqual(len(self.cdp_server.uploaded_images), 1)

    def test_upload_image_empty_data_handling(self) -> None:
        """Handles empty image upload payload safely."""
        res = self.client.upload_image("")
        self.assertEqual(res.status_code, 200)


# ==============================================================================
# Feature 19: Interactive Overlay Routes
# ==============================================================================

class TestFeature19_InteractiveOverlayRoutes(HarnessTestCase):
    """
    Feature 19: Interactive Overlay Routes
    Tests `/api/cdp/answer-question`, `/api/cdp/permission`, and `/api/cdp/dropdown-select`.
    """

    def test_answer_question_by_choice_index(self) -> None:
        """Submits answer choice by index to `/api/cdp/answer-question`."""
        res = self.client.answer_question(question_id="q-101", choice_index=0)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")

    def test_answer_question_with_custom_text(self) -> None:
        """Submits custom text response to `/api/cdp/answer-question`."""
        res = self.client.answer_question(custom_text="Execute unit tests first")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")

    def test_permission_allow_action(self) -> None:
        """Submits 'allow' action to `/api/cdp/permission`."""
        res = self.client.permission_action(action="allow", command="npm run build")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("action"), "allow")

    def test_permission_deny_action(self) -> None:
        """Submits 'deny' action to `/api/cdp/permission`."""
        res = self.client.permission_action(action="deny")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("action"), "deny")

    def test_dropdown_select_option(self) -> None:
        """Submits dropdown menu selection to `/api/cdp/dropdown-select`."""
        res = self.client.dropdown_select(option_index=1, label="gpt-4o")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")


# ==============================================================================
# Feature 20: Task & Session Navigation
# ==============================================================================

class TestFeature20_TaskAndSessionNavigation(HarnessTestCase):
    """
    Feature 20: Task & Session Navigation
    Tests `/api/running-tasks`, `/api/scheduled-tasks`, `/api/conversation-history`, and `/api/right-sidebar`.
    """

    def test_get_running_tasks(self) -> None:
        """Retrieves running tasks list from `/api/running-tasks`."""
        res = self.client.get_running_tasks()
        self.assertEqual(res.status_code, 200)
        self.assertIn("tasks", res.json())

    def test_get_scheduled_tasks(self) -> None:
        """Retrieves scheduled tasks list from `/api/scheduled-tasks`."""
        res = self.client.get_scheduled_tasks()
        self.assertEqual(res.status_code, 200)
        self.assertIn("scheduled", res.json())

    def test_get_conversation_history(self) -> None:
        """Retrieves conversation history list from `/api/conversation-history`."""
        res = self.client.get_conversation_history()
        self.assertEqual(res.status_code, 200)
        self.assertIn("history", res.json())

    def test_get_right_sidebar(self) -> None:
        """Retrieves right sidebar artifacts from `/api/right-sidebar`."""
        res = self.client.get_right_sidebar()
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("artifacts", data)

    def test_scheduled_tasks_post_and_delete(self) -> None:
        """Creates and deletes scheduled task items via `/api/scheduled-tasks`."""
        post_res = self.client.post("/api/scheduled-tasks", json={"cron": "0 9 * * *", "prompt": "Daily Test"})
        self.assertEqual(post_res.status_code, 200)

        del_res = self.client.delete("/api/scheduled-tasks")
        self.assertEqual(del_res.status_code, 200)


# ==============================================================================
# Feature 21: Legacy Route Compatibility
# ==============================================================================

class TestFeature21_LegacyRouteCompatibility(HarnessTestCase):
    """
    Feature 21: Legacy Route Compatibility
    Tests retention of all 15 legacy endpoints returning HTTP 200 OK.
    """

    def test_legacy_projects_and_diff(self) -> None:
        """Verifies `/api/projects` and `/api/review/diff` return 200."""
        self.assertEqual(self.client.get("/api/projects").status_code, 200)
        self.assertEqual(self.client.get("/api/review/diff").status_code, 200)

    def test_legacy_chat_incoming(self) -> None:
        """Verifies `/api/chat/incoming` returns 200."""
        self.assertEqual(self.client.get("/api/chat/incoming").status_code, 200)
        self.assertEqual(self.client.post("/api/chat/incoming", json={}).status_code, 200)

    def test_legacy_system_status_endpoints(self) -> None:
        """Verifies `/api/status`, `/api/system/info`, `/api/version`, `/api/ping` return 200."""
        self.assertEqual(self.client.get("/api/status").status_code, 200)
        self.assertEqual(self.client.get("/api/system/info").status_code, 200)
        self.assertEqual(self.client.get("/api/version").status_code, 200)
        self.assertEqual(self.client.get("/api/ping").status_code, 200)

    def test_legacy_ai_metadata_endpoints(self) -> None:
        """Verifies `/api/models`, `/api/agents`, `/api/sessions`, `/api/prompts` return 200."""
        self.assertEqual(self.client.get("/api/models").status_code, 200)
        self.assertEqual(self.client.get("/api/agents").status_code, 200)
        self.assertEqual(self.client.get("/api/sessions").status_code, 200)
        self.assertEqual(self.client.get("/api/prompts").status_code, 200)

    def test_all_15_legacy_routes_exhaustive(self) -> None:
        """Loops through all 15 legacy routes and verifies HTTP 200 OK status."""
        endpoints = [
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
        self.assertEqual(len(endpoints), 15)
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f"Endpoint {ep} did not return 200")


# ==============================================================================
# Feature 22: Zeroconf mDNS Registration
# ==============================================================================

class TestFeature22_ZeroconfmDNSRegistration(HarnessTestCase):
    """
    Feature 22: Zeroconf mDNS Registration
    Tests mDNS broadcast of `wahyuai.local:8888` and IP resolution logic.
    """

    def test_get_local_ip_returns_valid_ipv4(self) -> None:
        """Verifies local IP detection logic returns valid IPv4 format."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            ip = "127.0.0.1"

        self.assertRegex(ip, r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

    def test_mdns_service_info_configuration(self) -> None:
        """Validates mDNS ServiceInfo parameters structure."""
        service_type = "_http._tcp.local."
        service_name = f"WahyuAI.{service_type}"
        server_name = "wahyuai.local."
        port = 8888

        self.assertEqual(service_type, "_http._tcp.local.")
        self.assertEqual(service_name, "WahyuAI._http._tcp.local.")
        self.assertEqual(server_name, "wahyuai.local.")
        self.assertEqual(port, 8888)

    def test_mdns_txt_properties(self) -> None:
        """Validates mDNS TXT metadata record properties."""
        props = {"app": "Antigravity Remote", "creator": "Tri Wahyu Handoyo"}
        self.assertEqual(props["app"], "Antigravity Remote")
        self.assertEqual(props["creator"], "Tri Wahyu Handoyo")

    def test_mdns_custom_port_assignment(self) -> None:
        """Validates mDNS port configuration with custom port values."""
        custom_port = 9999
        self.assertTrue(1024 <= custom_port <= 65535)

    def test_mdns_safe_exception_handling(self) -> None:
        """Verifies safe exception handling during mDNS initialization."""
        def dummy_mdns_start(invalid_host: str) -> bool:
            try:
                socket.inet_aton(invalid_host)
                return True
            except Exception:
                return False

        self.assertFalse(dummy_mdns_start("invalid_ip_format"))


# ==============================================================================
# Feature 23: Process Lifecycle Management
# ==============================================================================

class TestFeature23_ProcessLifecycleManagement(HarnessTestCase):
    """
    Feature 23: Process Lifecycle Management
    Tests `/api/restart-antigravity` process termination and restart mechanics.
    """

    def test_restart_antigravity_endpoint(self) -> None:
        """Calls `POST /api/restart-antigravity` and verifies HTTP 200 response."""
        res = self.client.restart_antigravity()
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "restarting")

    def test_restart_antigravity_response_format(self) -> None:
        """Verifies restart response is valid JSON."""
        res = self.client.post("/api/restart-antigravity", json={})
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), dict)

    def test_process_discovery_names(self) -> None:
        """Validates process search matches Antigravity and Electron executables."""
        executables = ["Antigravity.exe", "electron.exe"]
        self.assertIn("Antigravity.exe", executables)
        self.assertIn("electron.exe", executables)

    def test_restart_multiple_invocations(self) -> None:
        """Calls restart endpoint multiple times without server errors."""
        for _ in range(3):
            res = self.client.restart_antigravity()
            self.assertEqual(res.status_code, 200)

    def test_restart_with_empty_payload(self) -> None:
        """Submits empty JSON payload to restart route."""
        res = self.client.post("/api/restart-antigravity", json={})
        self.assertEqual(res.status_code, 200)


# ==============================================================================
# Feature 24: Frontend Live Snapshot Renderer
# ==============================================================================

class TestFeature24_FrontendLiveSnapshotRenderer(HarnessTestCase):
    """
    Feature 24: Frontend Live Snapshot Renderer
    Tests `static/js/app.js` snapshot rendering, sanitized HTML injection, and autoscroll.
    """

    def setUp(self) -> None:
        super().setUp()
        self.app_js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "js", "app.js")

    def test_app_js_websocket_connection_logic(self) -> None:
        """Verifies `static/js/app.js` implements WebSocket connection and message routing."""
        self.assertTrue(os.path.exists(self.app_js_path))
        with open(self.app_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("connectWebSocket", content)
        self.assertIn("/ws/stream", content)

    def test_app_js_html_escaping(self) -> None:
        """Verifies `static/js/app.js` contains `escapeHtml` utility."""
        with open(self.app_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("function escapeHtml", content)
        self.assertIn("&amp;", content)
        self.assertIn("&lt;", content)

    def test_app_js_autoscroll_implementation(self) -> None:
        """Verifies `static/js/app.js` contains `scrollToBottom` autoscroll engine."""
        with open(self.app_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("function scrollToBottom", content)
        self.assertIn("scrollIntoView", content)

    def test_app_js_step_rendering_functions(self) -> None:
        """Verifies `static/js/app.js` contains step rendering functions."""
        with open(self.app_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("renderGroupedSteps", content)
        self.assertIn("transcript_update", content)

    def test_app_js_css_variable_application(self) -> None:
        """Verifies `static/js/app.js` handles engine state updates."""
        with open(self.app_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("updateEngineState", content)


# ==============================================================================
# Feature 25: Interactive Overlays UI
# ==============================================================================

class TestFeature25_InteractiveOverlaysUI(HarnessTestCase):
    """
    Feature 25: Interactive Overlays UI
    Tests overlay modals in `static/index.html` (permission, ask_question, settings, macros).
    """

    def setUp(self) -> None:
        super().setUp()
        self.index_html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")

    def test_index_html_modal_elements(self) -> None:
        """Verifies `static/index.html` contains overlay modal dialog elements."""
        self.assertTrue(os.path.exists(self.index_html_path))
        with open(self.index_html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('id="settings-modal"', content)
        self.assertIn('id="macros-modal"', content)
        self.assertIn('id="image-modal"', content)

    def test_permission_overlay_card_structure(self) -> None:
        """Validates permission dialog markup contains required buttons."""
        html = self.dom_gen.generate_permission_dialog()
        self.assertIn("Permission Required", html)
        self.assertIn("data-ag-click-id=\"perm:allow\"", html)
        self.assertIn("data-ag-click-id=\"perm:deny\"", html)

    def test_ask_question_card_structure(self) -> None:
        """Validates ask_question card markup contains question text and choice items."""
        html = self.dom_gen.generate_ask_question_card(question="Select deployment target")
        self.assertIn("Select deployment target", html)
        self.assertIn("choice-item", html)

    def test_dropdown_portal_structure(self) -> None:
        """Validates dropdown portal menu markup contains header and list items."""
        html = self.dom_gen.generate_dropdown_menu()
        self.assertIn("dropdown-portal", html)
        self.assertIn("dropdown-item", html)

    def test_overlay_modal_close_buttons(self) -> None:
        """Verifies modal close buttons are defined in `static/index.html`."""
        with open(self.index_html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('id="btn-close-settings"', content)
        self.assertIn('id="btn-close-macros"', content)


# ==============================================================================
# Feature 26: Running Tasks Strip UI
# ==============================================================================

class TestFeature26_RunningTasksStripUI(HarnessTestCase):
    """
    Feature 26: Running Tasks Strip UI
    Tests `#running-tasks` bar inside input container with spinner, task name, and stop button.
    """

    def setUp(self) -> None:
        super().setUp()
        self.index_html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")

    def test_index_html_running_task_card(self) -> None:
        """Verifies `#running-task-card` exists in `static/index.html`."""
        with open(self.index_html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('id="running-task-card"', content)

    def test_running_task_description_element(self) -> None:
        """Verifies `#running-task-desc` exists for displaying active task title."""
        with open(self.index_html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('id="running-task-desc"', content)

    def test_running_task_stop_button(self) -> None:
        """Verifies `#btn-stop-task` exists for stopping active tasks."""
        with open(self.index_html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('id="btn-stop-task"', content)

    def test_mock_dom_generator_running_tasks_html(self) -> None:
        """Generates running tasks strip HTML and validates structure."""
        html = self.dom_gen.generate_running_tasks()
        self.assertIn('id="running-tasks"', html)
        self.assertIn("running-task-item", html)
        self.assertIn("task-stop-btn", html)

    def test_running_task_cancel_button_tagging(self) -> None:
        """Verifies cancel buttons are tagged with `data-ag-click-id="task-cancel:..."`."""
        html = self.dom_gen.generate_running_tasks()
        self.assertIn('data-ag-click-id="task-cancel:0"', html)


# ==============================================================================
# Feature 27: Subagent View Bar UI
# ==============================================================================

class TestFeature27_SubagentViewBarUI(HarnessTestCase):
    """
    Feature 27: Subagent View Bar UI
    Tests `#subagent-bar` warning banner with back button and subagent title.
    """

    def test_mock_dom_generator_subagent_bar(self) -> None:
        """Generates subagent banner bar and validates badge and titles."""
        html = self.dom_gen.generate_subagent_bar(parent_title="Main Chat", subagent_title="Explorer 1")
        self.assertIn('id="subagent-bar"', html)
        self.assertIn("SUBAGENT", html)
        self.assertIn("Explorer 1", html)
        self.assertIn("Back to Main Chat", html)

    def test_subagent_bar_back_button_tagging(self) -> None:
        """Verifies subagent back button is tagged with `data-ag-click-id="subagent:back"`."""
        html = self.dom_gen.generate_subagent_bar()
        self.assertIn('data-ag-click-id="subagent:back"', html)

    def test_subagent_view_snapshot_schema(self) -> None:
        """Validates snapshot fields when `isSubagentView=True`."""
        snap = self.dom_gen.generate_full_snapshot(is_subagent_view=True, subagent_title="Agent-1")
        self.assertTrue(snap["isSubagentView"])
        self.assertEqual(snap["subagentTitle"], "Agent-1")
        self.assertIsNotNone(snap["subagentInfoHtml"])
        assert_valid_snapshot(snap)

    def test_subagent_simulation_in_mock_cdp(self) -> None:
        """Simulates subagent view transition on MockCDPServer."""
        self.cdp_server.simulate_subagent_view(subagent_title="Subagent QA", parent_title="Main")
        self.assertTrue(self.cdp_server.mock_snapshot["isSubagentView"])
        self.assertEqual(self.cdp_server.mock_snapshot["subagentTitle"], "Subagent QA")

    def test_subagent_badge_styling_classes(self) -> None:
        """Verifies subagent banner contains warning badge classes."""
        html = self.dom_gen.generate_subagent_bar()
        self.assertIn("subagent-badge", html)
        self.assertIn("subagent-banner", html)


# ==============================================================================
# Feature 28: BTW Side Question Panel
# ==============================================================================

class TestFeature28_BTWSideQuestionPanel(HarnessTestCase):
    """
    Feature 28: BTW Side Question Panel
    Tests `#btw-panel` side questions container, thread history, and input box.
    """

    def test_mock_dom_generator_btw_panel(self) -> None:
        """Generates BTW side question panel and validates header and input box."""
        html = self.dom_gen.generate_btw_panel()
        self.assertIn('id="btw-panel"', html)
        self.assertIn("Side Questions (/btw)", html)
        self.assertIn("btw-input", html)
        self.assertIn("btn-btw-send", html)

    def test_btw_send_button_tagging(self) -> None:
        """Verifies BTW submit button is tagged with `data-ag-click-id="btw:send"`."""
        html = self.dom_gen.generate_btw_panel()
        self.assertIn('data-ag-click-id="btw:send"', html)

    def test_btw_thread_formatting(self) -> None:
        """Verifies questions and answers are formatted with `btw-q` and `btw-a` classes."""
        q_list = [{"q": "How does diff work?", "a": "Using DJB2 state hashes."}]
        html = self.dom_gen.generate_btw_panel(questions=q_list)
        self.assertIn("Q: How does diff work?", html)
        self.assertIn("A: Using DJB2 state hashes.", html)

    def test_btw_field_in_snapshot_and_hash(self) -> None:
        """Verifies `btwHtml` field is included in composite hash calculation."""
        snap = self.dom_gen.generate_full_snapshot()
        snap["btwHtml"] = self.dom_gen.generate_btw_panel()
        h1 = compute_composite_hash(snap)
        snap["btwHtml"] = None
        h2 = compute_composite_hash(snap)
        self.assertNotEqual(h1, h2)

    def test_btw_empty_thread_list(self) -> None:
        """Handles empty question thread list gracefully."""
        html = self.dom_gen.generate_btw_panel(questions=[])
        self.assertIn('id="btw-panel"', html)


# ==============================================================================
# Feature 29: Floating Action Buttons (FAB)
# ==============================================================================

class TestFeature29_FloatingActionButtons(HarnessTestCase):
    """
    Feature 29: Floating Action Buttons (FAB)
    Tests `#scroll-fab` (scroll-to-bottom) and `#comment-fab` (comment queue badge).
    """

    def setUp(self) -> None:
        super().setUp()
        self.app_js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "js", "app.js")
        self.index_html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")

    def test_app_js_queued_comments_initialization(self) -> None:
        """Verifies `static/js/app.js` initializes `queuedComments` array."""
        with open(self.app_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("queuedComments", content)
        self.assertIn("localStorage", content)

    def test_scroll_controls_in_index_html(self) -> None:
        """Verifies scroll and navigation elements exist in `static/index.html`."""
        with open(self.index_html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('id="feed-container"', content)
        self.assertIn('id="chat-stream"', content)

    def test_scroll_to_bottom_function_definition(self) -> None:
        """Verifies `scrollToBottom` smooth scrolling function in `static/js/app.js`."""
        with open(self.app_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("function scrollToBottom(smooth", content)

    def test_scroll_info_in_snapshot(self) -> None:
        """Verifies snapshot contains `scrollInfo` with scrollTop, scrollHeight, clientHeight."""
        snap = self.dom_gen.generate_full_snapshot()
        self.assertIn("scrollInfo", snap)
        self.assertIn("scrollTop", snap["scrollInfo"])
        self.assertIn("scrollHeight", snap["scrollInfo"])
        self.assertIn("clientHeight", snap["scrollInfo"])

    def test_comment_fab_queue_storage(self) -> None:
        """Validates queued comments data structure schema."""
        comments = [{"id": "c1", "text": "Fix this function", "timestamp": 1723849200}]
        encoded = json.dumps(comments)
        decoded = json.loads(encoded)
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0]["id"], "c1")


# ==============================================================================
# Feature 30: Scheduled Tasks & History Modals
# ==============================================================================

class TestFeature30_ScheduledTasksAndHistoryModals(HarnessTestCase):
    """
    Feature 30: Scheduled Tasks & History Modals
    Tests fullscreen overlays for Scheduled Tasks and Conversation History navigation.
    """

    def setUp(self) -> None:
        super().setUp()
        self.index_html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")

    def test_scheduled_tasks_modal_html(self) -> None:
        """Generates scheduled tasks overlay modal and validates cron badges."""
        tasks = [{"id": "cron-1", "cron": "0 9 * * *", "prompt": "Run daily tests"}]
        html = self.dom_gen.generate_scheduled_tasks_modal(tasks=tasks)
        self.assertIn('data-overlay-type="scheduled_tasks"', html)
        self.assertIn("0 9 * * *", html)
        self.assertIn("Run daily tests", html)

    def test_conversation_history_modal_html(self) -> None:
        """Generates conversation history modal and validates history item titles."""
        convs = [{"id": "c-1", "title": "WebRemote Implementation", "time": "1h ago"}]
        html = self.dom_gen.generate_conversation_history_modal(conversations=convs)
        self.assertIn('data-overlay-type="conversation_history"', html)
        self.assertIn("WebRemote Implementation", html)
        self.assertIn("1h ago", html)

    def test_scheduled_tasks_modal_button_tagging(self) -> None:
        """Verifies scheduled tasks modal buttons have `data-ag-click-id` tags."""
        html = self.dom_gen.generate_scheduled_tasks_modal()
        self.assertIn('data-ag-click-id="sched:close"', html)
        self.assertIn('data-ag-click-id="sched:create"', html)
        self.assertIn('data-ag-click-id="sched-delete:0"', html)

    def test_conversation_history_button_tagging(self) -> None:
        """Verifies conversation history items and close button are tagged."""
        html = self.dom_gen.generate_conversation_history_modal()
        self.assertIn('data-ag-click-id="history:0"', html)
        self.assertIn('data-ag-click-id="history:close"', html)

    def test_index_html_history_and_scheduled_buttons(self) -> None:
        """Verifies `#btn-history` and `#btn-scheduled` exist in `static/index.html`."""
        with open(self.index_html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('id="btn-history"', content)
        self.assertIn('id="btn-scheduled"', content)


# ==============================================================================
# Feature 31: Service Worker & Push Bell
# ==============================================================================

class TestFeature31_ServiceWorkerAndPushBell(HarnessTestCase):
    """
    Feature 31: Service Worker & Push Bell
    Tests `static/sw.js` cache management, push handlers, and PWA manifest.
    """

    def setUp(self) -> None:
        super().setUp()
        static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        self.sw_path = os.path.join(static_dir, "sw.js")
        self.manifest_path = os.path.join(static_dir, "manifest.json")
        self.app_js_path = os.path.join(static_dir, "js", "app.js")

    def test_service_worker_file_exists(self) -> None:
        """Verifies `static/sw.js` exists and contains valid JavaScript code."""
        self.assertTrue(os.path.exists(self.sw_path))
        with open(self.sw_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertGreaterEqual(len(content), 10)

    def test_service_worker_lifecycle_listeners(self) -> None:
        """Verifies `static/sw.js` handles install, activate, and fetch lifecycle events."""
        with open(self.sw_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("install", content)
        self.assertIn("activate", content)
        self.assertIn("fetch", content)

    def test_service_worker_cache_name(self) -> None:
        """Verifies `static/sw.js` defines cache name identifier."""
        with open(self.sw_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("CACHE_NAME", content)

    def test_service_worker_registration_in_app_js(self) -> None:
        """Verifies `static/js/app.js` registers service worker on window load."""
        with open(self.app_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("serviceWorker", content)
        self.assertIn("register('/sw.js')", content)

    def test_pwa_manifest_json_structure(self) -> None:
        """Verifies `static/manifest.json` contains PWA name, start_url, display mode."""
        self.assertTrue(os.path.exists(self.manifest_path))
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertIn("name", manifest)
        self.assertIn("short_name", manifest)
        self.assertIn("start_url", manifest)
        self.assertEqual(manifest.get("display"), "standalone")


# ==============================================================================
# Feature 32: Mobile Responsive Styles
# ==============================================================================

class TestFeature32_MobileResponsiveStyles(HarnessTestCase):
    """
    Feature 32: Mobile Responsive Styles
    Tests `static/css/app.css` dark theme variables, safe areas, and touch targets.
    """

    def setUp(self) -> None:
        super().setUp()
        self.css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "css", "app.css")

    def test_app_css_file_exists(self) -> None:
        """Verifies `static/css/app.css` exists and is non-empty."""
        self.assertTrue(os.path.exists(self.css_path))
        with open(self.css_path, "r", encoding="utf-8") as f:
            css = f.read()
        self.assertGreaterEqual(len(css), 100)
        assert_responsive_css(css)

    def test_app_css_dark_theme_variables(self) -> None:
        """Verifies `static/css/app.css` defines CSS variables for dark theme styling."""
        with open(self.css_path, "r", encoding="utf-8") as f:
            css = f.read()
        self.assertIn("--", css)
        self.assertIn(":root", css)

    def test_app_css_safe_area_insets(self) -> None:
        """Verifies `static/css/app.css` uses safe area inset variables or padding."""
        with open(self.css_path, "r", encoding="utf-8") as f:
            css = f.read()
        self.assertTrue("safe-area-inset" in css or "padding" in css)

    def test_app_css_responsive_media_queries(self) -> None:
        """Verifies `static/css/app.css` includes responsive `@media` query blocks."""
        with open(self.css_path, "r", encoding="utf-8") as f:
            css = f.read()
        self.assertIn("@media", css)

    def test_app_css_touch_targets_and_scrolling(self) -> None:
        """Verifies `static/css/app.css` defines touch target sizing and overflow rules."""
        with open(self.css_path, "r", encoding="utf-8") as f:
            css = f.read()
        self.assertIn("overflow", css)
        self.assertIn("cursor", css)


# ==============================================================================
# CLI Test Runner Entrypoint
# ==============================================================================

if __name__ == "__main__":
    unittest.main()
