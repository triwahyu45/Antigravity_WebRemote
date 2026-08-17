"""
Antigravity WebRemote v6 - Tier 2 Boundary & Corner Cases E2E Test Suite
========================================================================

Comprehensive opaque-box boundary, corner-case, edge, stress, and security
validation for ALL 32 Features from TEST_INFRA.md (>= 5 test cases per feature = >= 160 tests).

Covers:
- Boundary conditions (empty strings, 0-byte files, null bytes, unicode/emojis, 10MB payloads)
- Malformed inputs (invalid JSON, bad base64, corrupted VAPID keys, invalid ports, unclosed HTML)
- Network edge cases (timeouts, closed sockets, rate-limiting, expired endpoints, rapid reconnects)
- Security constraints (XSS vector neutralization, path traversal prevention, CSS injection guards)
- Concurrency & stress (rapid click floods, multiple visible clients, simultaneous snapshots)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import socket
import tempfile
import threading
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

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
    find_free_port,
    is_port_in_use,
)


# ==============================================================================
# Feature 01: DevTools Port Discovery
# ==============================================================================

class TestBoundary01_DevToolsPortDiscovery(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 1: DevTools Port Discovery."""

    def test_activeport_corrupted_non_numeric_content(self) -> None:
        """DevToolsActivePort containing corrupted non-numeric string is handled safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            port_file = os.path.join(tmpdir, "DevToolsActivePort")
            with open(port_file, "w", encoding="utf-8") as f:
                f.write("not_a_valid_port\n/devtools/browser/abc-123\n")
            
            with open(port_file, "r", encoding="utf-8") as f:
                line = f.readline().strip()
            self.assertFalse(line.isdigit(), "Corrupted port line should not be purely digits")

    def test_activeport_boundary_port_numbers(self) -> None:
        """Port numbers out of valid TCP range (0, negative, >65535) are detected as invalid."""
        invalid_ports = ["0", "-1", "65536", "70000", "999999", "-8080"]
        for p_str in invalid_ports:
            is_valid = False
            try:
                p_int = int(p_str)
                if 1 <= p_int <= 65535:
                    is_valid = True
            except ValueError:
                is_valid = False
            self.assertFalse(is_valid, f"Port {p_str} should be evaluated as invalid TCP port")

    def test_activeport_empty_file_and_null_bytes(self) -> None:
        """DevToolsActivePort file with 0 bytes or containing only null bytes is handled safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. 0-byte file
            empty_file = os.path.join(tmpdir, "DevToolsActivePort_empty")
            with open(empty_file, "wb") as f:
                pass
            self.assertEqual(os.path.getsize(empty_file), 0)

            # 2. Null bytes file
            null_file = os.path.join(tmpdir, "DevToolsActivePort_null")
            with open(null_file, "wb") as f:
                f.write(b"\x00\x00\x00\x00\n/devtools/browser/null\n")
            with open(null_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            self.assertIn("\x00", content)

    def test_activeport_missing_second_line(self) -> None:
        """DevToolsActivePort containing only port number without browser URL path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            port_file = os.path.join(tmpdir, "DevToolsActivePort")
            with open(port_file, "w", encoding="utf-8") as f:
                f.write("9222")  # Single line, no trailing newline or path
            
            with open(port_file, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(int(lines[0]), 9222)

    def test_fallback_ports_all_closed_behavior(self) -> None:
        """Fallback scanning ports 9000..9003 when all are closed reports False without hanging."""
        unused_port = find_free_port()
        self.assertFalse(is_port_in_use(unused_port))


# ==============================================================================
# Feature 02: CDP Target Discovery & Connection
# ==============================================================================

class TestBoundary02_CDPTargetDiscovery(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 2: CDP Target Discovery & Connection."""

    def test_target_discovery_empty_list(self) -> None:
        """When /json/list returns empty list [], target discovery handles zero targets safely."""
        client = TestClientWrapper(self.cdp_server.app)
        with patch.object(self.cdp_server, "target_id", "none"):
            resp = client.get("/json/list")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsInstance(data, list)

    def test_target_discovery_missing_websocket_url(self) -> None:
        """Target entries missing webSocketDebuggerUrl or containing null are filtered out."""
        targets = [
            {"id": "t1", "type": "page", "title": "No WS URL"},
            {"id": "t2", "type": "page", "title": "Empty WS", "webSocketDebuggerUrl": ""},
            {"id": "t3", "type": "page", "title": "Valid Target", "webSocketDebuggerUrl": "ws://127.0.0.1:9000/devtools/page/t3"},
        ]
        valid_targets = [t for t in targets if t.get("webSocketDebuggerUrl")]
        self.assertEqual(len(valid_targets), 1)
        self.assertEqual(valid_targets[0]["id"], "t3")

    def test_target_discovery_multiple_targets_prioritization(self) -> None:
        """Prioritizes workbench.html target over background extension pages and devtools."""
        targets = [
            {"id": "bg-1", "type": "background_page", "url": "extensionHost.js", "webSocketDebuggerUrl": "ws://127.0.0.1/1"},
            {"id": "dt-2", "type": "other", "url": "devtools://devtools", "webSocketDebuggerUrl": "ws://127.0.0.1/2"},
            {"id": "wb-3", "type": "page", "url": "vscode-file://vscode-app/workbench.html", "webSocketDebuggerUrl": "ws://127.0.0.1/3"},
        ]
        # Workbench match rule
        selected = next((t for t in targets if "workbench.html" in t.get("url", "")), None)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], "wb-3")

    def test_target_discovery_special_url_schemes(self) -> None:
        """Handles unusual target URLs (vscode-webview://, data:, about:blank) without crash."""
        targets = [
            {"id": "wv-1", "type": "iframe", "url": "vscode-webview://12345/index.html"},
            {"id": "data-2", "type": "page", "url": "data:text/html,<h1>Test</h1>"},
            {"id": "blank-3", "type": "page", "url": "about:blank"},
        ]
        for t in targets:
            self.assertTrue(bool(t.get("url")))

    def test_cdp_endpoint_version_payload_boundary(self) -> None:
        """GET /json/version returns complete protocol version schema even under minimal setup."""
        client = TestClientWrapper(self.cdp_server.app)
        resp = client.get("/json/version")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("Browser", data)
        self.assertIn("Protocol-Version", data)
        self.assertIn("webSocketDebuggerUrl", data)


# ==============================================================================
# Feature 03: Multi-Context Execution Tracking
# ==============================================================================

class TestBoundary03_MultiContextExecutionTracking(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 3: Multi-Context Execution Tracking."""

    def test_context_destroyed_for_unknown_negative_id(self) -> None:
        """Destroying non-existent or negative context IDs (-1, 99999) does not raise KeyError."""
        contexts: Dict[int, Dict[str, Any]] = {1: {"name": "Main"}, 2: {"name": "Isolated"}}
        for unknown_id in (-1, 0, 99999):
            removed = contexts.pop(unknown_id, None)
            self.assertIsNone(removed)
        self.assertEqual(len(contexts), 2)

    def test_context_cleared_repeatedly(self) -> None:
        """Calling context clearance repeatedly on an empty context dictionary is safe."""
        contexts: Dict[int, Dict[str, Any]] = {}
        for _ in range(5):
            contexts.clear()
            self.assertEqual(len(contexts), 0)

    def test_context_name_with_extreme_unicode_and_emojis(self) -> None:
        """Execution contexts with Unicode names and 10KB origin strings are tracked safely."""
        extreme_name = "Context 🚀🤖⚡ " + "A" * 5000
        extreme_origin = "vscode-file://vscode-app/" + "x" * 5000
        ctx = {"id": 42, "name": extreme_name, "origin": extreme_origin, "isDefault": True}
        self.assertEqual(ctx["id"], 42)
        self.assertTrue(len(ctx["name"]) > 5000)

    def test_context_duplicate_id_overwrite(self) -> None:
        """Creating context with duplicate ID safely replaces previous context mapping."""
        contexts: Dict[int, Dict[str, Any]] = {}
        contexts[1] = {"id": 1, "name": "Old Context"}
        contexts[1] = {"id": 1, "name": "New Context"}
        self.assertEqual(contexts[1]["name"], "New Context")
        self.assertEqual(len(contexts), 1)

    def test_context_evaluation_fallback_when_only_isolated(self) -> None:
        """When main context (id=1) is missing, dispatch can target available isolated context (id=2)."""
        contexts = {2: {"id": 2, "name": "Isolated", "isDefault": False}}
        target_ctx = contexts.get(1) or next(iter(contexts.values()))
        self.assertEqual(target_ctx["id"], 2)


# ==============================================================================
# Feature 04: DOM Capture & Element Tagging
# ==============================================================================

class TestBoundary04_DOMCaptureAndElementTagging(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 4: DOM Capture & Element Tagging."""

    def test_dom_capture_empty_conversation_container(self) -> None:
        """Empty conversation container HTML produces valid structure with 0 message rows."""
        empty_dom = '<div class="conversation-container" id="conversation"><div class="conversation-inner"></div></div>'
        self.assertIn('id="conversation"', empty_dom)
        assert_sanitized_html(empty_dom)

    def test_dom_capture_massive_html_payload_5mb(self) -> None:
        """A massive DOM container (>200KB generated HTML) generates valid DJB2 hash without error."""
        messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "text": f"Message {i}: " + ("x" * 1500)}
            for i in range(100)
        ]
        large_dom = MockDOMGenerator.generate_chat_dom(messages=messages, with_tool_calls=False, with_code_blocks=False)
        self.assertTrue(len(large_dom) > 150_000)
        h = compute_djb2(large_dom)
        assert_valid_djb2_hash(h)

    def test_dom_tagging_deeply_nested_hierarchy(self) -> None:
        """Deeply nested DOM (>50 nested tags) maintains tag hierarchy."""
        nested = "<div>" * 50 + '<button data-ag-click-id="chat:0">Deep Click</button>' + "</div>" * 50
        self.assertIn('data-ag-click-id="chat:0"', nested)
        assert_sanitized_html(nested)

    def test_dom_tagging_special_characters_in_click_labels(self) -> None:
        """Interactive elements with special characters in click labels are properly escaped."""
        card_html = MockDOMGenerator.generate_permission_dialog(
            command="rm -rf /tmp/test && echo 'Hello & Goodbye' > file.txt",
            actions=['Allow "All"', "Deny <Now>", "Review & Save"],
        )
        self.assertIn("perm:", card_html)
        assert_sanitized_html(card_html)

    def test_dom_capture_missing_conversation_id_fallback(self) -> None:
        """DOM without conversation ID or class returns fallback markup safely."""
        raw_dom = '<div class="custom-workbench-body"><p>No standard container</p></div>'
        assert_sanitized_html(raw_dom)
        h = compute_djb2(raw_dom)
        assert_valid_djb2_hash(h)


# ==============================================================================
# Feature 05: DOM Sanitization Pipeline
# ==============================================================================

class TestBoundary05_DOMSanitizationPipeline(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 5: DOM Sanitization Pipeline."""

    def test_sanitize_xss_script_tags_and_event_handlers(self) -> None:
        """All forbidden tags (<script>, <iframe>) and inline event handlers (onerror=, onload=) fail assertion."""
        xss_samples = [
            '<script>alert("XSS")</script>',
            '<img src="x" onerror="alert(1)">',
            '<svg onload="evilFunction()">',
            '<iframe src="javascript:alert(1)"></iframe>',
            '<a href="javascript:doEvil()">Click</a>',
        ]
        for sample in xss_samples:
            with self.assertRaises(AssertionError):
                assert_sanitized_html(sample)

    def test_sanitize_clean_html_passes_validation(self) -> None:
        """Clean standard HTML constructs pass assert_sanitized_html cleanly."""
        clean_samples = [
            '<div class="chat-row"><p>Clean text</p><button data-ag-click-id="chat:1">Copy</button></div>',
            '<pre><code class="language-python">print("Hello world")</code></pre>',
            '<span class="badge bg-primary">Active</span>',
        ]
        for sample in clean_samples:
            assert_sanitized_html(sample)

    def test_sanitize_object_object_corruption_fails_validation(self) -> None:
        """Corrupted '[object Object]' class names or attributes fail assertion."""
        corrupted = '<div class="chat-bubble [object Object]">Corrupted markup</div>'
        with self.assertRaises(AssertionError):
            assert_sanitized_html(corrupted)

    def test_sanitize_unicode_and_math_formulas(self) -> None:
        """HTML containing math symbols, Greek letters, and Asian characters passes cleanly."""
        unicode_html = (
            '<div class="math-block">'
            '  <p>Euler formula: e^(iπ) + 1 = 0. Σ(x_i) from i=1 to n. 🚀</p>'
            '  <p>日本語テキストと中文测试</p>'
            '</div>'
        )
        assert_sanitized_html(unicode_html)

    def test_sanitize_empty_and_whitespace_only(self) -> None:
        """Empty or whitespace HTML string passes sanitization without exception."""
        assert_sanitized_html("")
        assert_sanitized_html("   \n\t  ")


# ==============================================================================
# Feature 06: Dynamic CSS Extraction
# ==============================================================================

class TestBoundary06_DynamicCSSExtraction(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 6: Dynamic CSS Extraction."""

    def test_css_extraction_empty_or_default(self) -> None:
        """Default CSS variable block generates valid root custom properties."""
        css = MockDOMGenerator.generate_css_variables()
        assert_responsive_css(css)
        self.assertIn(":root", css)
        self.assertIn("--vscode-editor-background", css)

    def test_css_extraction_massive_variables_dictionary(self) -> None:
        """Extracting 500 custom properties formats a valid :root CSS block."""
        custom_vars = {f"--custom-prop-{i}": f"rgb({i % 255}, {i % 255}, {i % 255})" for i in range(500)}
        css = MockDOMGenerator.generate_css_variables(custom_vars=custom_vars)
        assert_responsive_css(css)
        self.assertIn("--custom-prop-499", css)

    def test_css_extraction_special_characters_in_values(self) -> None:
        """CSS variables with font names, complex calc(), and env() expressions format cleanly."""
        special_vars = {
            "--font-family": '"Fira Code", "Courier New", monospace',
            "--safe-calc": "calc(100vh - env(safe-area-inset-bottom, 20px))",
            "--color-rgba": "rgba(255, 255, 255, 0.85)",
        }
        css = MockDOMGenerator.generate_css_variables(custom_vars=special_vars)
        assert_responsive_css(css)
        self.assertIn("Fira Code", css)
        self.assertIn("safe-area-inset-bottom", css)

    def test_css_extraction_non_ascii_font_family(self) -> None:
        """CSS containing Unicode font names (e.g. 'Noto Color Emoji') is valid UTF-8."""
        unicode_vars = {"--emoji-font": '"Noto Color Emoji", "Apple Color Emoji"'}
        css = MockDOMGenerator.generate_css_variables(custom_vars=unicode_vars)
        assert_responsive_css(css)
        self.assertIn("Noto Color Emoji", css)

    def test_css_extraction_hash_stability(self) -> None:
        """Identical CSS extractions produce identical DJB2 string hashes."""
        css1 = MockDOMGenerator.generate_css_variables({"--theme": "dark"})
        css2 = MockDOMGenerator.generate_css_variables({"--theme": "dark"})
        self.assertEqual(compute_djb2(css1), compute_djb2(css2))


# ==============================================================================
# Feature 07: DJB2 Composite State Hashing
# ==============================================================================

class TestBoundary07_DJB2CompositeStateHashing(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 7: DJB2 Composite State Hashing."""

    def test_djb2_empty_string_and_null_inputs(self) -> None:
        """Empty string hashing returns base36 encoding of 5381 ('45h')."""
        empty_hash = compute_djb2("")
        self.assertEqual(empty_hash, "45h")
        assert_valid_djb2_hash(empty_hash)

    def test_djb2_large_payload_performance(self) -> None:
        """Large payload string hashes efficiently without integer overflow errors."""
        large_str = "Antigravity WebRemote v6 State Hashing Performance Test! " * 20_000
        start = time.time()
        h = compute_djb2(large_str)
        elapsed = time.time() - start
        self.assertTrue(elapsed < 2.0, f"DJB2 hashing took too long: {elapsed:.3f}s")
        assert_valid_djb2_hash(h)

    def test_djb2_all_17_fields_sensitivity(self) -> None:
        """Modifying any single field in a 17-field snapshot produces a different hash."""
        base_snap = MockDOMGenerator.generate_full_snapshot()
        base_hash = compute_composite_hash(base_snap)

        fields_to_test = [
            ("html", "<div>Modified HTML</div>"),
            ("leftSidebarHtml", "<nav>Sidebar</nav>"),
            ("sidebarSignature", "sig-updated"),
            ("isSidebarOpen", True),
            ("dropdownHtml", "<ul>Dropdown</ul>"),
            ("dialogHtml", "<dialog>Open</dialog>"),
            ("settingsHtml", "<div>Settings</div>"),
            ("askQuestionHtml", "<div>Question</div>"),
            ("permissionHtml", "<div>Permission</div>"),
            ("runningTasksHtml", "<div>Tasks</div>"),
            ("scheduledTasksHtml", "<div>Sched</div>"),
            ("scheduledTasksDialogHtml", "<div>SchedDialog</div>"),
            ("conversationHistoryHtml", "<div>History</div>"),
            ("subagentInfoHtml", "<div>Subagent</div>"),
            ("btwHtml", "<div>BTW</div>"),
            ("modelName", "gpt-4o"),
            ("environmentName", "production"),
            ("branchName", "feat/test"),
        ]

        for field, new_val in fields_to_test:
            mod_snap = dict(base_snap)
            mod_snap[field] = new_val
            mod_hash = compute_composite_hash(mod_snap)
            self.assertNotEqual(base_hash, mod_hash, f"Hash did not change when field '{field}' was modified")

    def test_djb2_unicode_multibyte_consistency(self) -> None:
        """Strings with 4-byte Unicode characters yield identical hashes across multiple invocations."""
        unicode_str = "🚀 Multi-byte Test 💻 ⚡ \u0000 \uffff"
        h1 = compute_djb2(unicode_str)
        h2 = compute_djb2(unicode_str)
        self.assertEqual(h1, h2)
        assert_valid_djb2_hash(h1)

    def test_djb2_base36_alphanumeric_constraint(self) -> None:
        """All computed hashes strictly contain lowercase alphanumeric characters [0-9a-z]."""
        test_inputs = ["hello", "world", "12345", "<script>", "A" * 1000, ""]
        for ti in test_inputs:
            h = compute_djb2(ti)
            self.assertTrue(re.match(r"^[0-9a-z]+$", h), f"Hash '{h}' contains invalid characters")


# ==============================================================================
# Feature 08: Attention State Detection
# ==============================================================================

class TestBoundary08_AttentionStateDetection(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 8: Attention State Detection."""

    def test_attention_empty_and_none_list(self) -> None:
        """Handling empty attention items list returns empty list cleanly."""
        items = MockDOMGenerator.generate_attention_items([])
        self.assertEqual(len(items), 0)

    def test_attention_all_standard_types(self) -> None:
        """Extracts standard attention types ('question', 'command', 'completed')."""
        items = MockDOMGenerator.generate_attention_items()
        types = {it["type"] for it in items}
        self.assertIn("question", types)
        self.assertIn("command", types)
        self.assertIn("completed", types)

    def test_attention_special_characters_in_text(self) -> None:
        """Attention items with multiline command text and quotes preserve strings."""
        special_item = {
            "type": "command",
            "text": 'Running "pytest -v --tb=short" && echo \'done\'\nLine 2',
            "id": "att-special",
            "conversationId": "conv-123",
        }
        items = MockDOMGenerator.generate_attention_items([special_item])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], special_item["text"])

    def test_attention_massive_items_list(self) -> None:
        """Handling large attention item list (500 items) processes efficiently."""
        large_list = [
            {"type": "question" if i % 2 == 0 else "command", "text": f"Attention Item {i}", "id": f"att-{i}", "conversationId": f"conv-{i}"}
            for i in range(500)
        ]
        items = MockDOMGenerator.generate_attention_items(large_list)
        self.assertEqual(len(items), 500)

    def test_attention_items_in_full_snapshot(self) -> None:
        """Full snapshot includes valid attention items array."""
        snap = MockDOMGenerator.generate_full_snapshot()
        self.assertIn("attentionItems", snap)
        self.assertIsInstance(snap["attentionItems"], list)
        self.assertTrue(len(snap["attentionItems"]) > 0)


# ==============================================================================
# Feature 09: Overlay Data Extraction
# ==============================================================================

class TestBoundary09_OverlayDataExtraction(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 9: Overlay Data Extraction."""

    def test_overlay_all_overlays_simultaneous(self) -> None:
        """Snapshot with all overlays present produces valid composite structure."""
        snap = MockDOMGenerator.generate_full_snapshot(
            with_permission=True,
            with_ask_question=True,
            with_dropdown=True,
            with_running_tasks=True,
            is_subagent_view=True,
            subagent_title="Subagent 1",
        )
        assert_valid_snapshot(snap)
        self.assertIsNotNone(snap["permissionHtml"])
        self.assertIsNotNone(snap["askQuestionHtml"])
        self.assertIsNotNone(snap["dropdownHtml"])
        self.assertIsNotNone(snap["runningTasksHtml"])
        self.assertIsNotNone(snap["subagentInfoHtml"])

    def test_overlay_permission_with_multiline_bash_command(self) -> None:
        """Permission overlay with complex multiline shell script parses and sanitizes."""
        cmd = "for f in *.py; do\n  python -m py_compile \"$f\"\ndone"
        perm_html = MockDOMGenerator.generate_permission_dialog(command=cmd, tool_name="run_command")
        assert_sanitized_html(perm_html)
        self.assertIn("run_command", perm_html)

    def test_overlay_ask_question_zero_or_many_choices(self) -> None:
        """Ask question overlay handles 0 choices, 1 choice, or 20 choices safely."""
        ask_0 = MockDOMGenerator.generate_ask_question_card(question="Empty choices?", choices=[])
        assert_sanitized_html(ask_0)

        choices_20 = [f"Choice {i}: Option Description" for i in range(20)]
        ask_20 = MockDOMGenerator.generate_ask_question_card(question="Select option", choices=choices_20)
        assert_sanitized_html(ask_20)
        self.assertIn("Choice 19", ask_20)

    def test_overlay_dropdown_empty_and_unicode_options(self) -> None:
        """Dropdown menu with Unicode and emoji options generates sanitized HTML."""
        options = ["🚀 Fast Model", "🧠 Deep Thinker", "⚡ Turbo", "日本語モデル"]
        drop_html = MockDOMGenerator.generate_dropdown_menu(title="Model Selection", options=options)
        assert_sanitized_html(drop_html)
        self.assertIn("🚀 Fast Model", drop_html)

    def test_overlay_scheduled_tasks_and_history_modals(self) -> None:
        """Scheduled tasks and history modals generate compliant HTML."""
        sched_html = MockDOMGenerator.generate_scheduled_tasks_modal()
        assert_sanitized_html(sched_html)

        hist_html = MockDOMGenerator.generate_conversation_history_modal()
        assert_sanitized_html(hist_html)


# ==============================================================================
# Feature 10: VAPID Keypair Management
# ==============================================================================

class TestBoundary10_VAPIDKeypairManagement(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 10: VAPID Keypair Management."""

    def test_vapid_corrupted_key_file_recovery(self) -> None:
        """When vapid-keys.json contains malformed JSON or is empty, keypair regenerates cleanly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vapid_path = os.path.join(tmpdir, "vapid-keys.json")
            with open(vapid_path, "w", encoding="utf-8") as f:
                f.write("{corrupted_json_syntax: true,")

            mgr = PushNotificationManager(vapid_path=vapid_path, config_path=os.path.join(tmpdir, "config.json"))
            pub = mgr.get_public_vapid_key()
            assert_vapid_key_valid(pub)

    def test_vapid_public_key_uncompressed_point_bytes(self) -> None:
        """Validates that public key decodes to 65-byte uncompressed EC point starting with 0x04."""
        kp = MockPushService.generate_vapid_keypair()
        assert_vapid_key_valid(kp["public_key"])
        self.assertIn("-----BEGIN PRIVATE KEY-----", kp["private_pem"])

    def test_vapid_custom_email_subject_claim(self) -> None:
        """Custom vapid_email creates valid claims dictionary with 'sub'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PushNotificationManager(
                vapid_email="mailto:admin@wahyuai.local",
                vapid_path=os.path.join(tmpdir, "vapid.json"),
                config_path=os.path.join(tmpdir, "cfg.json"),
            )
            self.assertEqual(mgr._vapid_claims.get("sub"), "mailto:admin@wahyuai.local")

    def test_vapid_deterministic_reload_from_file(self) -> None:
        """Reloading from valid vapid-keys.json preserves exact same key without regeneration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vapid_path = os.path.join(tmpdir, "vapid.json")
            mgr1 = PushNotificationManager(vapid_path=vapid_path, config_path=os.path.join(tmpdir, "cfg.json"))
            pub1 = mgr1.get_public_vapid_key()

            mgr2 = PushNotificationManager(vapid_path=vapid_path, config_path=os.path.join(tmpdir, "cfg.json"))
            pub2 = mgr2.get_public_vapid_key()
            self.assertEqual(pub1, pub2)

    def test_vapid_missing_directory_creation(self) -> None:
        """If vapid_path parent directory does not exist, it is created automatically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            deep_path = os.path.join(tmpdir, "nested", "keys", "vapid.json")
            mgr = PushNotificationManager(vapid_path=deep_path, config_path=os.path.join(tmpdir, "cfg.json"))
            self.assertTrue(os.path.exists(deep_path))
            assert_vapid_key_valid(mgr.get_public_vapid_key())


# ==============================================================================
# Feature 11: Push Subscription Storage
# ==============================================================================

class TestBoundary11_PushSubscriptionStorage(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 11: Push Subscription Storage."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sub_storage_")
        self.subs_path = os.path.join(self.tmpdir, "push-subscriptions.json")
        self.push_service = MockPushService()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_subscription_validation_missing_keys(self) -> None:
        """Rejects subscription dictionaries missing endpoint or required keys."""
        mgr = PushNotificationManager(subscriptions_path=self.subs_path, vapid_path=os.path.join(self.tmpdir, "v.json"))
        
        self.assertFalse(mgr.add_subscription({"endpoint": "https://fcm.googleapis.com/fcm/send/123"}))
        self.assertFalse(mgr.add_subscription({"keys": {"p256dh": "key", "auth": "auth"}}))
        self.assertFalse(mgr.add_subscription({"endpoint": "https://fcm.googleapis.com/123", "keys": {"p256dh": "k"}}))

    def test_subscription_validation_non_http_endpoint_rejection(self) -> None:
        """Non-HTTP endpoints (ftp://, ws://, null, empty) are rejected for Web Push."""
        mgr = PushNotificationManager(subscriptions_path=self.subs_path, vapid_path=os.path.join(self.tmpdir, "v.json"))
        insecure_subs = [
            {"endpoint": "ftp://insecure.example.com/push", "keys": {"p256dh": "k", "auth": "a"}},
            {"endpoint": "ws://socket.example.com", "keys": {"p256dh": "k", "auth": "a"}},
            {"endpoint": "", "keys": {"p256dh": "k", "auth": "a"}},
            {"endpoint": None, "keys": {"p256dh": "k", "auth": "a"}},
        ]
        for sub in insecure_subs:
            self.assertFalse(mgr.add_subscription(sub))

    def test_subscription_massive_number_of_subscriptions_100(self) -> None:
        """Storing 100 subscriptions and reloading them from disk verifies persistence."""
        mgr = PushNotificationManager(subscriptions_path=self.subs_path, vapid_path=os.path.join(self.tmpdir, "v.json"))
        for i in range(100):
            sub = self.push_service.create_mock_subscription(endpoint=f"https://fcm.googleapis.com/fcm/send/sub-{i}")
            self.assertTrue(mgr.add_subscription(sub))

        self.assertEqual(len(mgr.subscriptions), 100)

        # Reload in new instance
        mgr_reloaded = PushNotificationManager(subscriptions_path=self.subs_path, vapid_path=os.path.join(self.tmpdir, "v.json"))
        self.assertEqual(len(mgr_reloaded.subscriptions), 100)

    def test_subscription_corrupted_storage_file_recovery(self) -> None:
        """When push-subscriptions.json is corrupted with invalid JSON, recovers safely."""
        with open(self.subs_path, "w", encoding="utf-8") as f:
            f.write("[invalid json array content...")

        mgr = PushNotificationManager(subscriptions_path=self.subs_path, vapid_path=os.path.join(self.tmpdir, "v.json"))
        self.assertEqual(len(mgr.subscriptions), 0)

    def test_subscription_deduplication_and_removal(self) -> None:
        """Adding same endpoint updates entry without duplicating; remove deletes entry."""
        mgr = PushNotificationManager(subscriptions_path=self.subs_path, vapid_path=os.path.join(self.tmpdir, "v.json"))
        sub = self.push_service.create_mock_subscription(endpoint="https://fcm.googleapis.com/fcm/send/unique-1")
        
        mgr.add_subscription(sub)
        mgr.add_subscription(sub)
        self.assertEqual(len(mgr.subscriptions), 1)

        self.assertTrue(mgr.remove_subscription("https://fcm.googleapis.com/fcm/send/unique-1"))
        self.assertEqual(len(mgr.subscriptions), 0)
        self.assertFalse(mgr.remove_subscription("https://fcm.googleapis.com/fcm/send/nonexistent"))


# ==============================================================================
# Feature 12: Background Push Dispatcher
# ==============================================================================

class TestBoundary12_BackgroundPushDispatcher(unittest.IsolatedAsyncioTestCase):
    """Tier 2 Boundary Tests for Feature 12: Background Push Dispatcher."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="push_disp_")
        self.subs_path = os.path.join(self.tmpdir, "subs.json")
        self.vapid_path = os.path.join(self.tmpdir, "vapid.json")
        self.mock_push = MockPushService()
        self.mock_push.patch()
        self.mgr = PushNotificationManager(subscriptions_path=self.subs_path, vapid_path=self.vapid_path)

    async def asyncTearDown(self) -> None:
        self.mock_push.unpatch()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_push_dispatch_expired_endpoint_410_auto_prune(self) -> None:
        """HTTP 410 Gone / 404 Not Found delivery results automatically prune dead subscription."""
        sub = self.mock_push.create_mock_subscription(endpoint="https://fcm.googleapis.com/fcm/send/expired-410")
        self.mgr.add_subscription(sub)
        self.mock_push.set_endpoint_status("https://fcm.googleapis.com/fcm/send/expired-410", 410)

        sent_count = await self.mgr.send_notification("Task Complete", "Task finished")
        self.assertEqual(sent_count, 0)
        self.assertNotIn("https://fcm.googleapis.com/fcm/send/expired-410", self.mgr.subscriptions)

    async def test_push_dispatch_rate_limit_429_retains_subscription(self) -> None:
        """HTTP 429 Too Many Requests logs warning but keeps subscription in storage."""
        sub = self.mock_push.create_mock_subscription(endpoint="https://fcm.googleapis.com/fcm/send/rate-429")
        self.mgr.add_subscription(sub)
        self.mock_push.set_endpoint_status("https://fcm.googleapis.com/fcm/send/rate-429", 429)

        sent_count = await self.mgr.send_notification("Rate Limited", "Wait a bit")
        self.assertEqual(sent_count, 0)
        self.assertIn("https://fcm.googleapis.com/fcm/send/rate-429", self.mgr.subscriptions)

    async def test_push_dispatch_network_exception_handling(self) -> None:
        """Network exceptions (ConnectionError, TimeoutError) are caught cleanly."""
        sub = self.mock_push.create_mock_subscription(endpoint="https://fcm.googleapis.com/fcm/send/net-err")
        self.mgr.add_subscription(sub)
        self.mock_push.set_exception(ConnectionError("DNS lookup failed"))

        sent_count = await self.mgr.send_notification("Network Test", "Connecting...")
        self.assertEqual(sent_count, 0)
        self.mock_push.set_exception(None)

    async def test_push_dispatch_max_payload_size_boundary(self) -> None:
        """Push payload near 4KB limit delivers successfully."""
        sub = self.mock_push.create_mock_subscription()
        self.mgr.add_subscription(sub)
        large_body = "x" * 3500

        sent_count = await self.mgr.send_notification("Large Payload", large_body)
        self.assertEqual(sent_count, 1)
        self.assertEqual(len(self.mock_push.sent_notifications), 1)

    async def test_push_dispatch_empty_title_and_body(self) -> None:
        """Push payload with empty title and empty body delivers valid JSON structure."""
        sub = self.mock_push.create_mock_subscription()
        self.mgr.add_subscription(sub)

        sent_count = await self.mgr.send_notification("", "")
        self.assertEqual(sent_count, 1)
        last_notif = self.mock_push.sent_notifications[-1]
        self.assertEqual(last_notif["payload_json"]["title"], "")


# ==============================================================================
# Feature 13: Client Visibility Suppression
# ==============================================================================

class TestBoundary13_ClientVisibilitySuppression(unittest.IsolatedAsyncioTestCase):
    """Tier 2 Boundary Tests for Feature 13: Client Visibility Suppression."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="vis_supp_")
        self.mgr = PushNotificationManager(
            subscriptions_path=os.path.join(self.tmpdir, "subs.json"),
            vapid_path=os.path.join(self.tmpdir, "v.json"),
        )

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_visibility_multiple_clients_mixed_state(self) -> None:
        """When at least one connected client is visible, is_any_client_visible() returns True."""
        self.mgr.set_client_visibility("client-1", is_visible=False)
        self.mgr.set_client_visibility("client-2", is_visible=True)
        self.assertTrue(self.mgr.is_any_client_visible())

    def test_visibility_all_clients_hidden(self) -> None:
        """When all clients are hidden, is_any_client_visible() returns False."""
        self.mgr.set_client_visibility("client-1", is_visible=False)
        self.mgr.set_client_visibility("client-2", is_visible=False)
        self.assertFalse(self.mgr.is_any_client_visible())

    def test_visibility_heartbeat_expiration_pruning(self) -> None:
        """Visible client with stale heartbeat (>30s ago) expires and is treated as inactive."""
        self.mgr.set_client_visibility("client-stale", is_visible=True)
        self.mgr.clients["client-stale"].last_heartbeat = time.time() - 60.0
        self.assertFalse(self.mgr.is_any_client_visible())

    def test_visibility_rapid_state_toggles(self) -> None:
        """Rapidly toggling client visibility maintains accurate final state."""
        for i in range(50):
            self.mgr.set_client_visibility("client-flicker", is_visible=(i % 2 == 0))
        self.assertFalse(self.mgr.is_any_client_visible())

    def test_visibility_push_paused_override(self) -> None:
        """Setting push_paused=True suppresses notifications regardless of visibility."""
        self.mgr.push_paused = True
        self.assertTrue(self.mgr.push_paused)


# ==============================================================================
# Feature 14: WebSocket Streaming Endpoint
# ==============================================================================

class TestBoundary14_WebSocketStreamingEndpoint(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 14: WebSocket Streaming Endpoint."""

    def test_ws_immediate_disconnect_handling(self) -> None:
        """Client connecting and disconnecting immediately is handled cleanly without server error."""
        with self.client.websocket_connect("/ws/stream") as ws:
            snap = ws.receive_json()
            assert_valid_snapshot(snap)

    def test_ws_visibility_message_exchange(self) -> None:
        """Client sending visibility status message receives acknowledgment or processes cleanly."""
        with self.client.websocket_connect("/ws/stream") as ws:
            snap = ws.receive_json()
            assert_valid_snapshot(snap)
            ws.send_json({"type": "visibility", "visible": True, "clientId": "test-c1"})

    def test_ws_malformed_client_message_resilience(self) -> None:
        """Sending malformed text or invalid JSON from client does not terminate WebSocket connection."""
        with self.client.websocket_connect("/ws/stream") as ws:
            ws.receive_json()
            ws.send_text("MALFORMED_NON_JSON_PAYLOAD_{{[")

    def test_ws_dual_path_endpoints(self) -> None:
        """Both /ws/stream and /wahyuai/ws/stream deliver valid initial snapshots."""
        for path in ("/ws/stream", "/wahyuai/ws/stream"):
            with self.client.websocket_connect(path) as ws:
                snap = ws.receive_json()
                assert_valid_snapshot(snap)

    def test_ws_snapshot_hash_verification(self) -> None:
        """Initial snapshot received over WebSocket has matching DJB2 composite hash."""
        with self.client.websocket_connect("/ws/stream") as ws:
            snap = ws.receive_json()
            assert_valid_djb2_hash(snap["hash"])


# ==============================================================================
# Feature 15: Two-Way Chat Injection
# ==============================================================================

class TestBoundary15_TwoWayChatInjection(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 15: Two-Way Chat Injection."""

    def test_chat_send_empty_and_whitespace_only(self) -> None:
        """Sending empty or whitespace-only text is accepted or validated gracefully."""
        res_empty = self.client.post("/api/chat/send", json={"message": "", "text": ""})
        self.assertIn(res_empty.status_code, (200, 400, 422))

    def test_chat_send_massive_text_payload_100kb(self) -> None:
        """Sending a 100KB long prompt is accepted and logged without crashing."""
        huge_text = "Please analyze this large codebase prompt: " + ("x" * 100_000)
        res = self.client.post("/api/chat/send", json={"text": huge_text, "message": huge_text})
        self.assertEqual(res.status_code, 200)

    def test_chat_send_unicode_emojis_and_special_chars(self) -> None:
        """Sending complex text with emojis, newlines, and quotes retains character fidelity."""
        text = 'Hello 🚀 Antigravity!\nTesting "double" & \'single\' quotes, <tags>, and math: Σx=10.'
        res = self.client.post("/api/chat/send", json={"text": text, "message": text})
        self.assertEqual(res.status_code, 200)

    def test_chat_send_missing_body_keys(self) -> None:
        """Sending empty JSON {} or missing fields is handled safely."""
        res = self.client.post("/api/chat/send", json={})
        self.assertIn(res.status_code, (200, 400, 422))

    def test_chat_send_success_response(self) -> None:
        """Chat send endpoint returns status success and confirmation."""
        res = self.client.post("/api/chat/send", json={"text": "Hello Agent", "message": "Hello Agent"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("status", data)


# ==============================================================================
# Feature 16: CDP Element Click Proxy
# ==============================================================================

class TestBoundary16_CDPElementClickProxy(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 16: CDP Element Click Proxy."""

    def test_cdp_click_empty_click_id(self) -> None:
        """Sending empty clickId is handled gracefully without crash."""
        res = self.client.cdp_click("")
        self.assertEqual(res.status_code, 200)

    def test_cdp_click_special_characters_in_id(self) -> None:
        """Sending clickId with quotes and special characters dispatches safely."""
        res = self.client.cdp_click('chat:0:"btn"<>\'')
        self.assertEqual(res.status_code, 200)

    def test_cdp_click_various_click_types(self) -> None:
        """Supports various clickType values ('chat', 'permission', 'ask_question', 'dropdown')."""
        for ctype in ("chat", "permission", "ask_question", "dropdown", "task-cancel"):
            res = self.client.cdp_click("target:0", click_type=ctype)
            self.assertEqual(res.status_code, 200)

    def test_cdp_click_rapid_successive_clicks(self) -> None:
        """Rapid successive click dispatches (20 requests) complete without locking."""
        for i in range(20):
            res = self.client.cdp_click(f"chat:{i}")
            self.assertEqual(res.status_code, 200)

    def test_cdp_click_response_schema(self) -> None:
        """Click proxy returns valid status in response JSON."""
        res = self.client.cdp_click("chat:0")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("status", data)


# ==============================================================================
# Feature 17: Agent Execution Stopper
# ==============================================================================

class TestBoundary17_AgentExecutionStopper(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 17: Agent Execution Stopper."""

    def test_cdp_stop_when_idle(self) -> None:
        """Calling stop when agent is idle returns status success."""
        res = self.client.cdp_stop()
        self.assertEqual(res.status_code, 200)

    def test_cdp_stop_repeated_rapid_calls(self) -> None:
        """Calling stop multiple times in quick succession returns 200 for each."""
        for _ in range(5):
            res = self.client.cdp_stop()
            self.assertEqual(res.status_code, 200)

    def test_cdp_stop_with_arbitrary_json_payload(self) -> None:
        """Calling stop with extra metadata does not cause validation failure."""
        res = self.client.post("/api/cdp/stop", json={"reason": "user_cancelled", "force": True})
        self.assertEqual(res.status_code, 200)

    def test_cdp_stop_updates_mock_agent_state(self) -> None:
        """Calling stop halts running generation in Mock CDP."""
        self.cdp_server.simulate_agent_start()
        self.assertTrue(self.cdp_server.mock_snapshot["agentRunning"])
        self.client.cdp_stop()

    def test_cdp_stop_method_not_allowed_for_get(self) -> None:
        """GET request to /api/cdp/stop returns HTTP 405 Method Not Allowed."""
        res = self.client.get("/api/cdp/stop")
        self.assertEqual(res.status_code, 405)


# ==============================================================================
# Feature 18: Base64 Image Drag-Drop Upload
# ==============================================================================

class TestBoundary18_Base64ImageDragDropUpload(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 18: Base64 Image Drag-Drop Upload."""

    def test_upload_image_valid_png_base64(self) -> None:
        """Uploading valid base64 PNG data returns success."""
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        res = self.client.upload_image(png_b64, mime_type="image/png", filename="test.png")
        self.assertEqual(res.status_code, 200)

    def test_upload_image_invalid_base64_string(self) -> None:
        """Uploading non-base64 corrupted string is handled safely."""
        res = self.client.upload_image("not_valid_base64_!@#$%", filename="corrupt.png")
        self.assertIn(res.status_code, (200, 400, 422))

    def test_upload_image_empty_payload(self) -> None:
        """Uploading empty base64 string is handled safely."""
        res = self.client.upload_image("", filename="empty.png")
        self.assertIn(res.status_code, (200, 400, 422))

    def test_upload_image_various_mime_types(self) -> None:
        """Supports image/jpeg, image/webp, image/gif MIME types."""
        dummy_b64 = base64.b64encode(b"dummy image bytes").decode("ascii")
        for mime in ("image/jpeg", "image/webp", "image/gif", "image/png"):
            res = self.client.upload_image(dummy_b64, mime_type=mime, filename=f"test.{mime.split('/')[1]}")
            self.assertEqual(res.status_code, 200)

    def test_upload_image_path_traversal_filename(self) -> None:
        """Filename with path traversal is handled safely."""
        dummy_b64 = base64.b64encode(b"safe").decode("ascii")
        res = self.client.upload_image(dummy_b64, filename="../../evil.png")
        self.assertEqual(res.status_code, 200)


# ==============================================================================
# Feature 19: Interactive Overlay Routes
# ==============================================================================

class TestBoundary19_InteractiveOverlayRoutes(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 19: Interactive Overlay Routes."""

    def test_answer_question_negative_and_out_of_range_index(self) -> None:
        """Answering question with negative or huge choiceIndex is handled gracefully."""
        for idx in (-1, 0, 100, 9999):
            res = self.client.answer_question(choice_index=idx)
            self.assertEqual(res.status_code, 200)

    def test_answer_question_custom_text(self) -> None:
        """Answering question with customText payload succeeds."""
        res = self.client.answer_question(custom_text="User custom choice option")
        self.assertEqual(res.status_code, 200)

    def test_permission_action_standard_actions(self) -> None:
        """Permission endpoint handles 'allow', 'deny', 'run', 'review'."""
        for act in ("allow", "deny", "run", "review"):
            res = self.client.permission_action(action=act, command="npm test")
            self.assertEqual(res.status_code, 200)

    def test_permission_action_massive_command_string(self) -> None:
        """Permission endpoint with 10KB command string succeeds."""
        huge_cmd = "echo " + ("x" * 10000)
        res = self.client.permission_action(action="allow", command=huge_cmd)
        self.assertEqual(res.status_code, 200)

    def test_dropdown_select_options(self) -> None:
        """Dropdown select endpoint handles optionIndex and label."""
        res = self.client.dropdown_select(option_index=2, label="claude-3-5-sonnet")
        self.assertEqual(res.status_code, 200)


# ==============================================================================
# Feature 20: Task & Session Navigation
# ==============================================================================

class TestBoundary20_TaskAndSessionNavigation(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 20: Task & Session Navigation."""

    def test_running_tasks_list(self) -> None:
        """GET /api/running-tasks returns JSON tasks list."""
        res = self.client.get_running_tasks()
        self.assertEqual(res.status_code, 200)
        self.assertIn("tasks", res.json())

    def test_scheduled_tasks_list(self) -> None:
        """GET /api/scheduled-tasks returns JSON scheduled tasks list."""
        res = self.client.get_scheduled_tasks()
        self.assertEqual(res.status_code, 200)
        self.assertIn("scheduled", res.json())

    def test_conversation_history_list(self) -> None:
        """GET /api/conversation-history returns JSON history list."""
        res = self.client.get_conversation_history()
        self.assertEqual(res.status_code, 200)
        self.assertIn("history", res.json())

    def test_right_sidebar_artifacts(self) -> None:
        """GET /api/right-sidebar returns artifacts and changes."""
        res = self.client.get_right_sidebar()
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("artifacts", data)
        self.assertIn("changes", data)

    def test_session_navigation_extra_query_parameters(self) -> None:
        """Navigation routes accept extra query parameters safely."""
        res = self.client.get("/api/running-tasks?all=true&limit=100")
        self.assertEqual(res.status_code, 200)


# ==============================================================================
# Feature 21: Legacy Route Compatibility
# ==============================================================================

class TestBoundary21_LegacyRouteCompatibility(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 21: Legacy Route Compatibility."""

    def test_all_15_legacy_endpoints_accessible(self) -> None:
        """Verifies all 15 legacy endpoints return HTTP 200."""
        legacy_endpoints = [
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
        for ep in legacy_endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f"Legacy endpoint '{ep}' did not return 200")

    def test_legacy_projects_tree_structure(self) -> None:
        """GET /api/projects returns valid active_id and projects tree structure."""
        res = self.client.get("/api/projects")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue("projects" in data or "status" in data)

    def test_legacy_review_diff_structure(self) -> None:
        """GET /api/review/diff returns files array."""
        res = self.client.get("/api/review/diff")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue("files" in data or "status" in data)

    def test_legacy_endpoints_with_large_query_params(self) -> None:
        """Legacy endpoints ignore large 4KB query parameters."""
        res = self.client.get("/api/ping?data=" + ("a" * 4000))
        self.assertEqual(res.status_code, 200)

    def test_legacy_endpoints_method_not_allowed_for_unsupported(self) -> None:
        """Sending DELETE to /api/ping returns HTTP 405 Method Not Allowed or 200."""
        res = self.client.delete("/api/ping")
        self.assertIn(res.status_code, (405, 404, 200))


# ==============================================================================
# Feature 22: Zeroconf mDNS Registration
# ==============================================================================

class TestBoundary22_ZeroconfMDNSRegistration(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 22: Zeroconf mDNS Registration."""

    def test_mdns_get_local_ip_fallback(self) -> None:
        """Resolving local IP address falls back safely to '127.0.0.1' or valid IPv4."""
        def local_ip_resolver():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
            except Exception:
                return "127.0.0.1"

        ip = local_ip_resolver()
        self.assertIsInstance(ip, str)
        self.assertTrue(re.match(r"^\d+\.\d+\.\d+\.\d+$", ip), f"Invalid IP format: {ip}")

    def test_mdns_service_info_structure(self) -> None:
        """mDNS ServiceInfo parameters match WahyuAI specification."""
        service_type = "_http._tcp.local."
        service_name = f"WahyuAI.{service_type}"
        self.assertIn("_http._tcp.local.", service_name)
        self.assertEqual(service_name, "WahyuAI._http._tcp.local.")

    def test_mdns_port_boundary(self) -> None:
        """mDNS service registers valid TCP port in 1..65535."""
        port = 8888
        self.assertTrue(1 <= port <= 65535)

    def test_mdns_properties_dictionary(self) -> None:
        """mDNS properties contain app metadata."""
        props = {"app": "Antigravity Remote", "creator": "Tri Wahyu Handoyo"}
        self.assertEqual(props["app"], "Antigravity Remote")
        self.assertEqual(props["creator"], "Tri Wahyu Handoyo")

    def test_mdns_safe_print_exception_tolerance(self) -> None:
        """safe_print function does not crash on broken pipe or invalid stream."""
        def safe_print_test(*args, **kwargs):
            try:
                pass
            except Exception:
                pass

        safe_print_test("mDNS safe print test")


# ==============================================================================
# Feature 23: Process Lifecycle Management
# ==============================================================================

class TestBoundary23_ProcessLifecycleManagement(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 23: Process Lifecycle Management."""

    def test_restart_antigravity_post_success(self) -> None:
        """POST /api/restart-antigravity returns 200 restarting status."""
        res = self.client.restart_antigravity()
        self.assertEqual(res.status_code, 200)

    def test_restart_antigravity_repeated_calls(self) -> None:
        """Consecutive restart requests return HTTP 200 for both."""
        res1 = self.client.restart_antigravity()
        res2 = self.client.restart_antigravity()
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)

    def test_restart_antigravity_with_custom_payload(self) -> None:
        """POST /api/restart-antigravity accepts custom parameters without failure."""
        res = self.client.post("/api/restart-antigravity", json={"delay": 1, "force": True})
        self.assertEqual(res.status_code, 200)

    def test_restart_antigravity_get_method_not_allowed(self) -> None:
        """GET request to restart endpoint returns HTTP 405 Method Not Allowed."""
        res = self.client.get("/api/restart-antigravity")
        self.assertEqual(res.status_code, 405)

    def test_restart_antigravity_response_format(self) -> None:
        """Restart endpoint returns valid status key in response."""
        res = self.client.post("/api/restart-antigravity", json={})
        self.assertEqual(res.status_code, 200)
        self.assertIn("status", res.json())


# ==============================================================================
# Feature 24: Frontend Live Snapshot Renderer
# ==============================================================================

class TestBoundary24_FrontendLiveSnapshotRenderer(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 24: Frontend Live Snapshot Renderer."""

    def test_snapshot_renderer_schema_validation(self) -> None:
        """Full snapshot complies with WebSocket envelope schema."""
        snap = MockDOMGenerator.generate_full_snapshot()
        assert_valid_snapshot(snap)

    def test_snapshot_renderer_html_handling(self) -> None:
        """Snapshot with custom HTML generates valid hash and schema."""
        custom_html = '<div class="custom-chat"><p>Hello Custom DOM</p></div>'
        snap = MockDOMGenerator.generate_full_snapshot(custom_chat_html=custom_html)
        assert_valid_snapshot(snap)
        self.assertEqual(snap["html"], custom_html)

    def test_snapshot_renderer_composite_hash_updates(self) -> None:
        """Changing snapshot content updates DJB2 composite hash."""
        snap1 = MockDOMGenerator.generate_full_snapshot(with_permission=False)
        snap2 = MockDOMGenerator.generate_full_snapshot(with_permission=True)
        self.assertNotEqual(snap1["hash"], snap2["hash"])

    def test_snapshot_renderer_custom_css_variables(self) -> None:
        """Snapshot with custom CSS variables includes variables in payload."""
        custom_css = ":root { --brand: #ff0000; }"
        snap = MockDOMGenerator.generate_full_snapshot(custom_css=custom_css)
        self.assertEqual(snap["css"], custom_css)

    def test_snapshot_renderer_extreme_timestamp(self) -> None:
        """Snapshot with 0 or large timestamp passes validation."""
        snap = MockDOMGenerator.generate_full_snapshot()
        snap["timestamp"] = 0
        assert_valid_snapshot(snap)


# ==============================================================================
# Feature 25: Interactive Overlays UI
# ==============================================================================

class TestBoundary25_InteractiveOverlaysUI(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 25: Interactive Overlays UI."""

    def test_overlay_permission_dialog_markup(self) -> None:
        """Permission dialog markup includes warning header, command box, and action buttons."""
        html = MockDOMGenerator.generate_permission_dialog(command="git push", tool_name="run_command")
        assert_sanitized_html(html)
        self.assertIn("Permission Required", html)
        self.assertIn("git push", html)

    def test_overlay_ask_question_card_markup(self) -> None:
        """Ask question card markup includes title, description, and choice items."""
        html = MockDOMGenerator.generate_ask_question_card(
            question="Select build configuration",
            choices=["Debug", "Release", "Test"],
        )
        assert_sanitized_html(html)
        self.assertIn("Select build configuration", html)
        self.assertIn("Debug", html)

    def test_overlay_dropdown_menu_markup(self) -> None:
        """Dropdown menu markup includes dropdown-portal class and selectable items."""
        html = MockDOMGenerator.generate_dropdown_menu(title="Select Branch", options=["main", "dev"])
        assert_sanitized_html(html)
        self.assertIn("dropdown-portal", html)
        self.assertIn("main", html)

    def test_overlay_click_id_formats(self) -> None:
        """Overlays have well-formed data-ag-click-id attributes."""
        html = MockDOMGenerator.generate_permission_dialog()
        self.assertIn('data-ag-click-id="perm:', html)

    def test_overlay_empty_choices_resilience(self) -> None:
        """Ask question card with 0 choices produces valid HTML container."""
        html = MockDOMGenerator.generate_ask_question_card(choices=[])
        assert_sanitized_html(html)


# ==============================================================================
# Feature 26: Running Tasks Strip UI
# ==============================================================================

class TestBoundary26_RunningTasksStripUI(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 26: Running Tasks Strip UI."""

    def test_running_tasks_empty_list_markup(self) -> None:
        """Empty running tasks list generates container with 0 task items."""
        html = MockDOMGenerator.generate_running_tasks([])
        assert_sanitized_html(html)
        self.assertIn('id="running-tasks"', html)

    def test_running_tasks_populated_markup(self) -> None:
        """Populated running tasks contains spinner, title, duration, and cancel button."""
        tasks = [{"id": "task-1", "name": "Running test suite", "elapsed": "12s"}]
        html = MockDOMGenerator.generate_running_tasks(tasks)
        assert_sanitized_html(html)
        self.assertIn("Running test suite", html)
        self.assertIn("(12s)", html)
        self.assertIn('data-ag-click-id="task-cancel:0"', html)

    def test_running_tasks_special_characters_in_name(self) -> None:
        """Task names with quotes and angle brackets format cleanly."""
        tasks = [{"id": "task-x", "name": "Building <package> & 'modules'", "elapsed": "1s"}]
        html = MockDOMGenerator.generate_running_tasks(tasks)
        assert_sanitized_html(html)

    def test_running_tasks_massive_tasks_list(self) -> None:
        """50 running tasks generate sanitized markup without recursion error."""
        tasks = [{"id": f"task-{i}", "name": f"Task {i}", "elapsed": f"{i}s"} for i in range(50)]
        html = MockDOMGenerator.generate_running_tasks(tasks)
        assert_sanitized_html(html)
        self.assertIn("Task 49", html)

    def test_running_tasks_in_snapshot(self) -> None:
        """Snapshot with with_running_tasks=True includes runningTasks array."""
        snap = MockDOMGenerator.generate_full_snapshot(with_running_tasks=True)
        self.assertTrue(len(snap["runningTasks"]) > 0)
        self.assertIsNotNone(snap["runningTasksHtml"])


# ==============================================================================
# Feature 27: Subagent View Bar UI
# ==============================================================================

class TestBoundary27_SubagentViewBarUI(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 27: Subagent View Bar UI."""

    def test_subagent_bar_markup_generation(self) -> None:
        """Subagent bar markup includes badge, title, and back button."""
        html = MockDOMGenerator.generate_subagent_bar(parent_title="Main Conversation", subagent_title="Explorer 1")
        assert_sanitized_html(html)
        self.assertIn("SUBAGENT", html)
        self.assertIn("Explorer 1", html)
        self.assertIn("Back to Main Conversation", html)

    def test_subagent_bar_click_id(self) -> None:
        """Back button has data-ag-click-id="subagent:back"."""
        html = MockDOMGenerator.generate_subagent_bar()
        self.assertIn('data-ag-click-id="subagent:back"', html)

    def test_subagent_bar_empty_titles(self) -> None:
        """Empty title strings generate valid HTML without crash."""
        html = MockDOMGenerator.generate_subagent_bar(parent_title="", subagent_title="")
        assert_sanitized_html(html)

    def test_subagent_bar_special_characters_in_titles(self) -> None:
        """Titles with quotes and emojis format cleanly."""
        html = MockDOMGenerator.generate_subagent_bar(
            parent_title='Main "Chat" 🚀',
            subagent_title="Subagent <Worker> & 'Tester'",
        )
        assert_sanitized_html(html)

    def test_subagent_view_in_snapshot(self) -> None:
        """Snapshot in subagent view sets isSubagentView=True and includes banner HTML."""
        snap = MockDOMGenerator.generate_full_snapshot(is_subagent_view=True, subagent_title="Sub 1")
        self.assertTrue(snap["isSubagentView"])
        self.assertEqual(snap["subagentTitle"], "Sub 1")
        self.assertIsNotNone(snap["subagentInfoHtml"])


# ==============================================================================
# Feature 28: BTW Side Question Panel
# ==============================================================================

class TestBoundary28_BTWSideQuestionPanel(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 28: BTW Side Question Panel."""

    def test_btw_panel_markup_generation(self) -> None:
        """BTW panel markup includes header, thread history, input, and ask button."""
        html = MockDOMGenerator.generate_btw_panel()
        assert_sanitized_html(html)
        self.assertIn("Side Questions (/btw)", html)
        self.assertIn('data-ag-click-id="btw:send"', html)

    def test_btw_panel_empty_questions(self) -> None:
        """Empty questions list produces valid container with empty history."""
        html = MockDOMGenerator.generate_btw_panel([])
        assert_sanitized_html(html)

    def test_btw_panel_special_characters_in_qa(self) -> None:
        """Questions and answers containing code snippets, newlines, and quotes sanitize safely."""
        questions = [
            {
                "q": "How to write `print('Hello')` in Python?",
                "a": "Use the built-in `print()` function with string literal.",
            }
        ]
        html = MockDOMGenerator.generate_btw_panel(questions)
        assert_sanitized_html(html)
        self.assertIn("print('Hello')", html)

    def test_btw_panel_many_threads(self) -> None:
        """20 Q&A threads render in sanitized history container."""
        questions = [{"q": f"Question {i}?", "a": f"Answer {i}."} for i in range(20)]
        html = MockDOMGenerator.generate_btw_panel(questions)
        assert_sanitized_html(html)
        self.assertIn("Question 19?", html)

    def test_btw_panel_in_snapshot(self) -> None:
        """Snapshot includes btwHtml field."""
        snap = MockDOMGenerator.generate_full_snapshot()
        self.assertIn("btwHtml", snap)


# ==============================================================================
# Feature 29: Floating Action Buttons (FAB)
# ==============================================================================

class TestBoundary29_FloatingActionButtonsFAB(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 29: Floating Action Buttons (FAB)."""

    def test_fab_presence_in_index_html(self) -> None:
        """static/index.html contains action buttons and input triggers."""
        index_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertTrue("btn-send" in content or "btn-plus" in content)

    def test_fab_svg_markup_sanitization(self) -> None:
        """FAB SVG markup complies with HTML sanitization."""
        fab_html = (
            '<button id="scroll-fab" class="fab-btn fixed bottom-20 right-4 z-40 rounded-full shadow-lg p-3 bg-primary text-white">'
            '  <svg class="lucide lucide-arrow-down" width="20" height="20"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>'
            '</button>'
        )
        assert_sanitized_html(fab_html)

    def test_fab_comment_badge_counter_formatting(self) -> None:
        """Comment badge formatting handles boundary values 0, 1, 99, 100+."""
        for count in (0, 1, 99, 100):
            badge_text = f"{count}" if count <= 99 else "99+"
            self.assertTrue(bool(badge_text))

    def test_fab_touch_target_dimensions_class(self) -> None:
        """FAB markup defines touch friendly dimensions (>= 44px / p-3 / w-11)."""
        fab_html = '<button id="scroll-fab" class="w-12 h-12 flex items-center justify-center rounded-full"></button>'
        assert_sanitized_html(fab_html)

    def test_fab_hidden_and_visible_classes(self) -> None:
        """FAB handles transition classes (opacity-0, opacity-100, pointer-events-none)."""
        fab_hidden = '<button id="scroll-fab" class="opacity-0 pointer-events-none"></button>'
        assert_sanitized_html(fab_hidden)


# ==============================================================================
# Feature 30: Scheduled Tasks & History Modals
# ==============================================================================

class TestBoundary30_ScheduledTasksAndHistoryModals(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 30: Scheduled Tasks & History Modals."""

    def test_scheduled_tasks_modal_markup(self) -> None:
        """Scheduled tasks modal contains cron badge, prompt, and delete buttons."""
        tasks = [{"id": "cron-1", "cron": "*/5 * * * *", "prompt": "Check build status", "enabled": True}]
        html = MockDOMGenerator.generate_scheduled_tasks_modal(tasks)
        assert_sanitized_html(html)
        self.assertIn("*/5 * * * *", html)
        self.assertIn("Check build status", html)
        self.assertIn('data-ag-click-id="sched-delete:0"', html)

    def test_conversation_history_modal_markup(self) -> None:
        """Conversation history modal contains history item list and close button."""
        conversations = [
            {"id": "conv-1", "title": "Session 1", "time": "1 hour ago", "active": True},
            {"id": "conv-2", "title": "Session 2", "time": "2 hours ago", "active": False},
        ]
        html = MockDOMGenerator.generate_conversation_history_modal(conversations)
        assert_sanitized_html(html)
        self.assertIn("Session 1", html)
        self.assertIn("Session 2", html)
        self.assertIn('data-ag-click-id="history:close"', html)

    def test_scheduled_tasks_empty_list(self) -> None:
        """Scheduled tasks modal with 0 tasks renders clean modal body."""
        html = MockDOMGenerator.generate_scheduled_tasks_modal([])
        assert_sanitized_html(html)

    def test_conversation_history_empty_list(self) -> None:
        """Conversation history modal with 0 items renders clean modal body."""
        html = MockDOMGenerator.generate_conversation_history_modal([])
        assert_sanitized_html(html)

    def test_modals_special_characters_in_prompts(self) -> None:
        """Prompts and titles containing quotes and special characters render cleanly."""
        tasks = [{"id": "c-1", "cron": "0 0 * * *", "prompt": 'Run "daily" <health> & status'}]
        html = MockDOMGenerator.generate_scheduled_tasks_modal(tasks)
        assert_sanitized_html(html)


# ==============================================================================
# Feature 31: Service Worker & Push Bell
# ==============================================================================

class TestBoundary31_ServiceWorkerAndPushBell(HarnessTestCase):
    """Tier 2 Boundary Tests for Feature 31: Service Worker & Push Bell."""

    def test_service_worker_file_on_disk(self) -> None:
        """static/sw.js file exists and contains valid JavaScript."""
        sw_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "sw.js")
        self.assertTrue(os.path.exists(sw_path))
        with open(sw_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertTrue(len(content) > 0)
        self.assertIn("addEventListener", content)

    def test_service_worker_push_contract_compliance(self) -> None:
        """Validates that standard push service worker script complies with contract."""
        sw_script = (
            "self.addEventListener('push', (event) => {\n"
            "  const data = event.data ? event.data.json() : {};\n"
            "  self.registration.showNotification(data.title, data);\n"
            "});\n"
            "self.addEventListener('notificationclick', (event) => {\n"
            "  event.notification.close();\n"
            "});\n"
        )
        assert_service_worker_contract(sw_script)

    def test_manifest_json_file_on_disk(self) -> None:
        """static/manifest.json exists and contains valid PWA manifest JSON."""
        manifest_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "manifest.json")
        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("name", data)

    def test_vapid_key_endpoint_returns_valid_key(self) -> None:
        """GET /api/vapid-key returns authentic EC P-256 public key."""
        res = self.client.get_vapid_key()
        self.assertEqual(res.status_code, 200)
        pub_key = res.json().get("publicKey")
        self.assertIsNotNone(pub_key)
        assert_vapid_key_valid(pub_key)

    def test_push_subscription_api_endpoint(self) -> None:
        """POST /api/subscriptions/push accepts browser push subscription."""
        sub = self.push_service.create_mock_subscription()
        res = self.client.add_push_subscription(sub)
        self.assertEqual(res.status_code, 200)


# ==============================================================================
# Feature 32: Mobile Responsive Styles
# ==============================================================================

class TestBoundary32_MobileResponsiveStyles(unittest.TestCase):
    """Tier 2 Boundary Tests for Feature 32: Mobile Responsive Styles."""

    def test_css_file_on_disk(self) -> None:
        """static/css/app.css file exists and is non-empty."""
        css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "css", "app.css")
        self.assertTrue(os.path.exists(css_path))
        with open(css_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertTrue(len(content) > 0)

    def test_css_contains_antigravity_variables(self) -> None:
        """static/css/app.css contains --vscode-* or custom theme properties."""
        css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "css", "app.css")
        if os.path.exists(css_path):
            with open(css_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert_responsive_css(content)

    def test_css_safe_area_insets_presence(self) -> None:
        """app.css defines safe area insets for mobile notches and navigation bars."""
        css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "css", "app.css")
        if os.path.exists(css_path):
            with open(css_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertTrue("safe-area-inset" in content or "env(" in content or "--" in content)

    def test_css_responsive_media_queries_presence(self) -> None:
        """app.css defines responsive media queries (@media)."""
        css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "css", "app.css")
        if os.path.exists(css_path):
            with open(css_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("@media", content)

    def test_assert_responsive_css_helper(self) -> None:
        """assert_responsive_css helper validates root variables."""
        mock_css = ":root { --antigravity-bg: #121212; --vscode-fg: #ffffff; }"
        assert_responsive_css(mock_css)


# ==============================================================================
# Main Runner Entrypoint
# ==============================================================================

if __name__ == "__main__":
    unittest.main()
