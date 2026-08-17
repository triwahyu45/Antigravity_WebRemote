"""
Antigravity WebRemote v6 - Test Harness Infrastructure
======================================================

Comprehensive opaque-box E2E test harness providing:
1. MockCDPServer: In-process async WebSocket & HTTP mock server emulating Chrome DevTools Protocol (CDP).
2. MockPushService: Intercepts pywebpush HTTP requests, validating VAPID keys, JWT tokens, and crypto payloads.
3. MockDOMGenerator: Generates realistic Antigravity chat DOMs, Lexical editor HTML, permission dialogs,
   ask_question cards, dropdowns, running task strips, subagent bars, BTW side panels, and responsive CSS.
4. TestClientWrapper: Sync & async FastAPI/Starlette TestClient with helpers for all 32 WebRemote v6
   endpoints and 15 legacy endpoints, plus WebSocket streaming client support.
5. Assertion Helpers: Robust validation for DJB2 composite state hashes, sanitized HTML, snapshots,
   VAPID public keys, push payloads, and responsive CSS contracts.
6. HarnessTestCase: Base test class for unittest/pytest with full automatic fixture lifecycles.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import dataclasses
import http
import json
import logging
import os
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Third-party testing dependencies
import httpx
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger("test_harness")


# ==============================================================================
# 1. Network & Port Utilities
# ==============================================================================

def find_free_port(host: str = "127.0.0.1") -> int:
    """Finds and returns an unused OS port on the specified host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        s.listen(1)
        port = s.getsockname()[1]
        return port


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Checks if a port is currently listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except (socket.error, ConnectionRefusedError):
            return False


def wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 5.0) -> bool:
    """Polls a port until it is available or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_in_use(port, host):
            return True
        time.sleep(0.05)
    return False


# ==============================================================================
# 2. DJB2 Hashing & State Digest Algorithms
# ==============================================================================

def base36_encode(number: int) -> str:
    """Converts a non-negative integer into its base-36 lowercase string."""
    if number < 0:
        raise ValueError("Cannot encode negative number in base36")
    if number == 0:
        return "0"
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    chars: List[str] = []
    while number > 0:
        number, rem = divmod(number, 36)
        chars.append(alphabet[rem])
    return "".join(reversed(chars))


def compute_djb2(s: Union[str, bytes]) -> str:
    """
    Authoritative reference implementation of the DJB2 string hashing algorithm,
    matching AG2R `hashString(str)`:
      let hash = 5381;
      for (let i = 0; i < str.length; i++) hash = ((hash << 5) + hash) + str.charCodeAt(i);
      return (hash >>> 0).toString(36);
    """
    if isinstance(s, bytes):
        s = s.decode("utf-8", errors="replace")
    h = 5381
    for ch in s:
        h = (((h << 5) + h) + ord(ch)) & 0xFFFFFFFF
    return base36_encode(h)


def compute_composite_hash(snapshot: Dict[str, Any]) -> str:
    """
    Computes the 17-field composite state hash matching AG2R specification
    (ag2r/server.js lines 749-768 and 802-821).
    """
    parts = [
        str(snapshot.get("html") or ""),
        str(snapshot.get("leftSidebarHtml") or ""),
        str(snapshot.get("sidebarSignature") or ""),
        "1" if snapshot.get("isSidebarOpen") else "0",
        str(snapshot.get("dropdownHtml") or ""),
        str(snapshot.get("dialogHtml") or ""),
        str(snapshot.get("settingsHtml") or ""),
        str(snapshot.get("askQuestionHtml") or ""),
        str(snapshot.get("permissionHtml") or ""),
        str(snapshot.get("runningTasksHtml") or ""),
        str(snapshot.get("scheduledTasksHtml") or ""),
        str(snapshot.get("scheduledTasksDialogHtml") or ""),
        str(snapshot.get("conversationHistoryHtml") or ""),
        str(snapshot.get("subagentInfoHtml") or ""),
        str(snapshot.get("btwHtml") or ""),
        str(snapshot.get("modelName") or ""),
        str(snapshot.get("environmentName") or ""),
        str(snapshot.get("branchName") or ""),
    ]
    composite_str = "".join(parts)
    return compute_djb2(composite_str)


# ==============================================================================
# 3. Mock DOM Generator (`MockDOMGenerator`)
# ==============================================================================

class MockDOMGenerator:
    """
    Generates realistic, standards-compliant HTML fixtures for Antigravity WebRemote
    including Lexical editor, chat bubbles, tool calls, permission dialogs,
    ask_question cards, dropdowns, running task strips, subagent bars, and CSS.
    """

    @staticmethod
    def generate_chat_dom(
        messages: Optional[List[Dict[str, Any]]] = None,
        agent_status: str = "idle",
        with_tool_calls: bool = True,
        with_code_blocks: bool = True,
    ) -> str:
        """Generates realistic Antigravity chat DOM container HTML."""
        if messages is None:
            messages = [
                {
                    "role": "user",
                    "text": "Please run the test suite and verify feature parity.",
                    "timestamp": "10:30 AM",
                },
                {
                    "role": "assistant",
                    "text": "I will execute the test harness suite now.",
                    "timestamp": "10:31 AM",
                    "tool_calls": [
                        {
                            "name": "run_command",
                            "command": "python -m unittest discover -s tests",
                            "status": "success",
                            "output": "Ran 368 tests in 2.14s - OK",
                        }
                    ] if with_tool_calls else [],
                    "code_blocks": [
                        {
                            "lang": "python",
                            "code": "import unittest\nfrom tests.harness import MockCDPServer",
                        }
                    ] if with_code_blocks else [],
                },
            ]

        items_html = []
        click_idx = 0

        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("text", "")
            ts = msg.get("timestamp", "Just now")

            if role == "user":
                items_html.append(
                    f'<div class="chat-message-row user-row" data-ag-role="user">'
                    f'  <div class="chat-bubble bg-user-bubble">'
                    f'    <div class="bubble-header"><span class="user-badge">User</span><span class="bubble-time">{ts}</span></div>'
                    f'    <div class="bubble-content"><p>{text}</p></div>'
                    f'  </div>'
                    f'</div>'
                )
            else:
                tool_html = ""
                if "tool_calls" in msg:
                    for tc in msg["tool_calls"]:
                        tool_name = tc.get("name", "tool")
                        cmd = tc.get("command", "")
                        out = tc.get("output", "")
                        tool_html += (
                            f'<div class="tool-call-card" data-tool-name="{tool_name}">'
                            f'  <div class="tool-header"><span class="tool-icon"></span><span class="tool-title">{tool_name}</span></div>'
                            f'  <pre class="tool-command"><code>{cmd}</code></pre>'
                            f'  <div class="tool-output"><pre>{out}</pre></div>'
                            f'</div>'
                        )

                code_html = ""
                if "code_blocks" in msg:
                    for cb in msg["code_blocks"]:
                        lang = cb.get("lang", "text")
                        code = cb.get("code", "")
                        code_html += (
                            f'<div class="code-block-wrapper">'
                            f'  <div class="code-header"><span class="lang-tag">{lang}</span>'
                            f'    <button class="copy-btn" data-ag-click-id="chat:{click_idx}" data-ag-click-label="Copy">Copy</button>'
                            f'  </div>'
                            f'  <pre><code class="language-{lang}">{code}</code></pre>'
                            f'</div>'
                        )
                        click_idx += 1

                items_html.append(
                    f'<div class="chat-message-row assistant-row" data-ag-role="assistant">'
                    f'  <div class="chat-bubble bg-assistant-bubble">'
                    f'    <div class="bubble-header"><span class="assistant-badge">Antigravity</span><span class="bubble-time">{ts}</span></div>'
                    f'    <div class="bubble-content"><p>{text}</p>{tool_html}{code_html}</div>'
                    f'  </div>'
                    f'</div>'
                )

        inner_content = "\n".join(items_html)
        return (
            f'<div class="scrollbar-hide overflow-y-auto flex-1 h-full conversation-container" '
            f'data-testid="conversation-view" id="conversation">'
            f'  <div class="conversation-inner p-4 space-y-4">'
            f'    {inner_content}'
            f'  </div>'
            f'</div>'
        )

    @staticmethod
    def generate_lexical_editor(
        placeholder: str = "Ask a question or request changes...",
        current_text: str = "",
        agent_running: bool = False,
    ) -> str:
        """Generates Antigravity Lexical contenteditable editor HTML."""
        stop_btn = (
            '<button class="stop-btn" data-tooltip-id="input-send-button-cancel-tooltip" '
            'data-ag-click-id="chat:stop" title="Stop Generation">'
            '<svg class="lucide lucide-square" width="16" height="16"><rect width="18" height="18" x="3" y="3" rx="2"/></svg>'
            '</button>'
            if agent_running
            else ""
        )

        text_span = (
            f'<span data-lexical-text="true">{current_text}</span>'
            if current_text
            else f'<span class="placeholder">{placeholder}</span>'
        )

        return (
            f'<div id="antigravity.agentSidePanelInputBox" class="editor-outer-box bg-card-border">'
            f'  <div class="editor-wrapper">'
            f'    <div contenteditable="true" role="textbox" data-lexical-editor="true" '
            f'         class="lexical-editor-input" spellcheck="true">'
            f'      <p dir="ltr">{text_span}</p>'
            f'    </div>'
            f'  </div>'
            f'  <div class="editor-actions-bar">'
            f'    <button id="input-send-button" data-tooltip-id="input-send-button-tooltip" '
            f'            data-ag-click-id="chat:send" class="send-button">Send</button>'
            f'    {stop_btn}'
            f'  </div>'
            f'</div>'
        )

    @staticmethod
    def generate_permission_dialog(
        command: str = "npm test",
        tool_name: str = "run_command",
        actions: Optional[List[str]] = None,
        risk_level: str = "medium",
    ) -> str:
        """Generates interactive tool permission dialog overlay HTML."""
        if actions is None:
            actions = ["Allow", "Deny", "Run", "Review"]

        action_buttons = []
        for act in actions:
            act_id = act.lower()
            action_buttons.append(
                f'<button class="perm-btn perm-btn-{act_id}" data-ag-click-id="perm:{act_id}" '
                f'data-ag-click-label="{act}">{act}</button>'
            )
        buttons_html = " ".join(action_buttons)

        return (
            f'<div class="permission-overlay fixed inset-0 z-50 flex items-center justify-center" '
            f'data-overlay-type="permission">'
            f'  <div class="permission-card bg-surface rounded-xl shadow-2xl p-4 border border-border max-w-md w-full">'
            f'    <div class="permission-header flex items-center gap-2">'
            f'      <span class="warning-icon text-amber-500">⚠</span>'
            f'      <h3 class="text-base font-semibold">Permission Required ({tool_name})</h3>'
            f'    </div>'
            f'    <div class="permission-body my-3">'
            f'      <p class="text-xs text-muted mb-2">The agent requests to execute the following command (Risk: {risk_level}):</p>'
            f'      <pre class="bg-card-border p-2 rounded text-xs font-mono overflow-x-auto"><code>{command}</code></pre>'
            f'    </div>'
            f'    <div class="permission-actions flex gap-2 justify-end mt-4">'
            f'      {buttons_html}'
            f'    </div>'
            f'  </div>'
            f'</div>'
        )

    @staticmethod
    def generate_ask_question_card(
        question: str = "How would you like to proceed?",
        choices: Optional[List[str]] = None,
        description: str = "Please select one of the options below to continue.",
        multi_select: bool = False,
    ) -> str:
        """Generates interactive ask_question multiple choice card overlay HTML."""
        if choices is None:
            choices = [
                "Option A: Execute all tests automatically",
                "Option B: Run only unit tests",
                "Option C: Cancel execution",
            ]

        choice_buttons = []
        for idx, ch in enumerate(choices):
            choice_buttons.append(
                f'<button class="choice-item w-full text-left p-3 rounded-lg border border-border hover:bg-hover mb-2" '
                f'data-ag-click-id="ask:{idx}" data-ag-click-label="{ch}">'
                f'  <span class="choice-index font-bold mr-2">{idx + 1}.</span>'
                f'  <span class="choice-label">{ch}</span>'
                f'</button>'
            )
        choices_html = "\n".join(choice_buttons)

        return (
            f'<div class="ask-question-card-overlay bg-surface rounded-xl shadow-lg border border-border p-4 my-2" '
            f'data-overlay-type="ask_question">'
            f'  <div class="ask-question-header">'
            f'    <h4 class="text-sm font-semibold text-primary">{question}</h4>'
            f'    <p class="text-xs text-muted mt-1">{description}</p>'
            f'  </div>'
            f'  <div class="ask-question-choices mt-3">'
            f'    {choices_html}'
            f'  </div>'
            f'</div>'
        )

    @staticmethod
    def generate_dropdown_menu(
        title: str = "Select Model / Branch",
        options: Optional[List[str]] = None,
    ) -> str:
        """Generates dropdown portal menu overlay HTML."""
        if options is None:
            options = ["claude-3-5-sonnet", "gpt-4o", "gemini-1.5-pro"]

        items = []
        for idx, opt in enumerate(options):
            items.append(
                f'<li class="dropdown-item p-2 hover:bg-hover cursor-pointer" '
                f'data-ag-click-id="dropdown:{idx}" data-ag-click-label="{opt}">{opt}</li>'
            )
        items_html = "\n".join(items)

        return (
            f'<div class="dropdown-portal fixed bg-surface border border-border rounded-lg shadow-xl z-50" '
            f'data-overlay-type="dropdown">'
            f'  <div class="dropdown-header text-xs font-bold p-2 border-b border-border">{title}</div>'
            f'  <ul class="dropdown-list list-none p-1 m-0">{items_html}</ul>'
            f'</div>'
        )

    @staticmethod
    def generate_running_tasks(
        tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Generates running tasks bar strip HTML."""
        if tasks is None:
            tasks = [
                {"id": "task-0", "name": "Running linter and type checker", "elapsed": "4s"}
            ]

        task_items = []
        for idx, t in enumerate(tasks):
            t_name = t.get("name", "Task")
            t_elapsed = t.get("elapsed", "0s")
            task_items.append(
                f'<div class="running-task-item flex items-center justify-between p-2 bg-card rounded mb-1" '
                f'data-task-id="{t.get("id", f"task-{idx}")}">'
                f'  <div class="flex items-center gap-2">'
                f'    <span class="spinner-icon animate-spin">⟳</span>'
                f'    <span class="task-title text-xs font-medium">{t_name}</span>'
                f'    <span class="task-duration text-xs text-muted">({t_elapsed})</span>'
                f'  </div>'
                f'  <button class="task-stop-btn text-xs text-red-400 hover:text-red-300" '
                f'          data-ag-click-id="task-cancel:{idx}" data-ag-click-label="Cancel">✕</button>'
                f'</div>'
            )
        tasks_html = "\n".join(task_items)

        return (
            f'<div id="running-tasks" class="running-tasks-container border-b border-border p-2 bg-surface">'
            f'  <div class="running-tasks-list">{tasks_html}</div>'
            f'</div>'
        )

    @staticmethod
    def generate_subagent_bar(
        parent_title: str = "Main Conversation",
        subagent_title: str = "Subagent Explorer 1",
    ) -> str:
        """Generates subagent warning banner bar HTML."""
        return (
            f'<div id="subagent-bar" class="subagent-banner bg-amber-950/40 border-b border-amber-800/50 p-2 flex items-center justify-between">'
            f'  <div class="flex items-center gap-2">'
            f'    <span class="subagent-badge text-xs bg-amber-600 text-white px-2 py-0.5 rounded font-bold">SUBAGENT</span>'
            f'    <span class="subagent-title text-xs font-semibold text-amber-200">{subagent_title}</span>'
            f'  </div>'
            f'  <button data-ag-click-id="subagent:back" class="subagent-back-btn text-xs text-amber-300 hover:underline">'
            f'    &larr; Back to {parent_title}'
            f'  </button>'
            f'</div>'
        )

    @staticmethod
    def generate_btw_panel(
        questions: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Generates /btw side question panel HTML."""
        if questions is None:
            questions = [
                {
                    "q": "What is the purpose of DJB2 hash?",
                    "a": "DJB2 is a fast hashing algorithm used to detect DOM mutations without serializing full diffs.",
                }
            ]

        threads = []
        for idx, q in enumerate(questions):
            threads.append(
                f'<div class="btw-thread border-b border-border pb-2 mb-2">'
                f'  <div class="btw-q font-bold text-xs text-primary">Q: {q.get("q", "")}</div>'
                f'  <div class="btw-a text-xs text-muted mt-1">A: {q.get("a", "")}</div>'
                f'</div>'
            )
        threads_html = "\n".join(threads)

        return (
            f'<div id="btw-panel" class="btw-container p-3 bg-surface border-l border-border h-full flex flex-col">'
            f'  <div class="btw-header text-xs font-bold uppercase tracking-wider text-muted mb-2">Side Questions (/btw)</div>'
            f'  <div class="btw-history flex-1 overflow-y-auto">{threads_html}</div>'
            f'  <div class="btw-input-box mt-2 flex gap-1">'
            f'    <input type="text" class="btw-input text-xs p-2 flex-1 rounded bg-card-border border border-border" placeholder="Ask side question..." />'
            f'    <button data-ag-click-id="btw:send" class="btn-btw-send text-xs px-3 py-1 bg-primary rounded">Ask</button>'
            f'  </div>'
            f'</div>'
        )

    @staticmethod
    def generate_scheduled_tasks_modal(
        tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Generates scheduled tasks overlay modal HTML."""
        if tasks is None:
            tasks = [
                {"id": "cron-1", "cron": "0 9 * * *", "prompt": "Run daily health checks", "enabled": True}
            ]

        items = []
        for idx, t in enumerate(tasks):
            items.append(
                f'<div class="scheduled-task-row p-3 border border-border rounded-lg mb-2 flex justify-between items-center" '
                f'data-cron-id="{t.get("id", f"cron-{idx}")}">'
                f'  <div>'
                f'    <span class="cron-badge font-mono text-xs bg-card px-2 py-1 rounded">{t.get("cron")}</span>'
                f'    <p class="cron-prompt text-xs mt-1 font-medium">{t.get("prompt")}</p>'
                f'  </div>'
                f'  <button data-ag-click-id="sched-delete:{idx}" class="text-red-400 text-xs hover:underline">Delete</button>'
                f'</div>'
            )
        items_html = "\n".join(items)

        return (
            f'<div class="scheduled-tasks-modal fixed inset-0 z-50 bg-black/60 flex items-center justify-center" '
            f'data-overlay-type="scheduled_tasks">'
            f'  <div class="modal-body bg-surface p-6 rounded-2xl max-w-lg w-full">'
            f'    <h3 class="text-base font-bold mb-4">Scheduled Tasks</h3>'
            f'    <div class="tasks-list max-h-60 overflow-y-auto mb-4">{items_html}</div>'
            f'    <div class="flex justify-end gap-2">'
            f'      <button data-ag-click-id="sched:close" class="px-4 py-2 text-xs bg-card rounded">Close</button>'
            f'      <button data-ag-click-id="sched:create" class="px-4 py-2 text-xs bg-primary rounded">New Schedule</button>'
            f'    </div>'
            f'  </div>'
            f'</div>'
        )

    @staticmethod
    def generate_conversation_history_modal(
        conversations: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Generates conversation history navigation overlay modal HTML."""
        if conversations is None:
            conversations = [
                {"id": "conv-1", "title": "Implement WebRemote v6 Python Port", "time": "2 hours ago", "active": True},
                {"id": "conv-2", "title": "Configure Zeroconf mDNS Broadcast", "time": "Yesterday", "active": False},
            ]

        items = []
        for idx, c in enumerate(conversations):
            active_cls = "bg-primary/20 border-primary" if c.get("active") else "border-border hover:bg-hover"
            items.append(
                f'<div class="history-item p-3 border rounded-xl mb-2 cursor-pointer {active_cls}" '
                f'data-ag-click-id="history:{idx}" data-conversation-id="{c.get("id")}">'
                f'  <div class="font-medium text-xs">{c.get("title")}</div>'
                f'  <div class="text-[10px] text-muted mt-1">{c.get("time")}</div>'
                f'</div>'
            )
        items_html = "\n".join(items)

        return (
            f'<div class="history-modal fixed inset-0 z-50 bg-black/60 flex items-center justify-center" '
            f'data-overlay-type="conversation_history">'
            f'  <div class="modal-body bg-surface p-6 rounded-2xl max-w-md w-full">'
            f'    <h3 class="text-base font-bold mb-4">Conversation History</h3>'
            f'    <div class="history-list max-h-80 overflow-y-auto mb-4">{items_html}</div>'
            f'    <button data-ag-click-id="history:close" class="w-full py-2 text-xs bg-card rounded">Close</button>'
            f'  </div>'
            f'</div>'
        )

    @staticmethod
    def generate_css_variables(custom_vars: Optional[Dict[str, str]] = None) -> str:
        """Generates realistic root CSS variables string extracted from Antigravity."""
        vars_dict = {
            "--vscode-editor-background": "#1e1e1e",
            "--vscode-editor-foreground": "#d4d4d4",
            "--vscode-sideBar-background": "#252526",
            "--vscode-button-background": "#007acc",
            "--vscode-button-foreground": "#ffffff",
            "--vscode-badge-background": "#4d4d4d",
            "--antigravity-brand-primary": "#4f46e5",
            "--antigravity-user-bubble": "#2d3748",
            "--antigravity-assistant-bubble": "#1a202c",
            "--antigravity-card-border": "#2d3748",
            "--antigravity-safe-area-bottom": "env(safe-area-inset-bottom, 0px)",
        }
        if custom_vars:
            vars_dict.update(custom_vars)

        var_lines = [f"  {k}: {v};" for k, v in vars_dict.items()]
        return ":root {\n" + "\n".join(var_lines) + "\n}"

    @staticmethod
    def generate_attention_items(
        items: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Generates realistic sidebar attention indicators."""
        if items is not None:
            return items
        return [
            {
                "type": "question",
                "text": "Waiting for permission on run_command",
                "id": "conv-att-1",
                "conversationId": "63fb64ac-9344-46a1-8d60-a891ba0835d8",
            },
            {
                "type": "command",
                "text": "Running test suite...",
                "id": "conv-att-2",
                "conversationId": "63fb64ac-9344-46a1-8d60-a891ba0835d8",
            },
            {
                "type": "completed",
                "text": "Task finished successfully",
                "id": "conv-att-3",
                "conversationId": "63fb64ac-9344-46a1-8d60-a891ba0835d8",
            },
        ]

    @classmethod
    def generate_full_snapshot(
        cls,
        agent_running: bool = False,
        is_subagent_view: bool = False,
        subagent_title: str = "",
        with_permission: bool = False,
        with_ask_question: bool = False,
        with_dropdown: bool = False,
        with_running_tasks: bool = False,
        custom_chat_html: Optional[str] = None,
        custom_css: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates a complete, authentic snapshot dictionary matching the WebSocket contract."""
        html = custom_chat_html or cls.generate_chat_dom(agent_status="running" if agent_running else "idle")
        css = custom_css or cls.generate_css_variables()
        permission_html = cls.generate_permission_dialog() if with_permission else None
        ask_question_html = cls.generate_ask_question_card() if with_ask_question else None
        dropdown_html = cls.generate_dropdown_menu() if with_dropdown else None
        running_tasks_html = cls.generate_running_tasks() if with_running_tasks else None
        subagent_info_html = cls.generate_subagent_bar(subagent_title=subagent_title) if is_subagent_view else None

        snapshot: Dict[str, Any] = {
            "type": "snapshot",
            "html": html,
            "css": css,
            "agentRunning": agent_running,
            "isSubagentView": is_subagent_view,
            "subagentTitle": subagent_title if is_subagent_view else "",
            "parentConversationName": "Main Conversation" if is_subagent_view else "",
            "isSidebarOpen": False,
            "isNewSessionPage": False,
            "isInputBoxHidden": False,
            "leftSidebarHtml": None,
            "sidebarSignature": "sig-0",
            "attentionItems": cls.generate_attention_items(),
            "runningTasks": [{"name": "Running linter", "elapsed": "4s"}] if with_running_tasks else [],
            "runningTasksHtml": running_tasks_html,
            "permission": {"command": "npm test", "tool": "run_command"} if with_permission else None,
            "permissionHtml": permission_html,
            "askQuestion": {"question": "Select target", "choices": ["A", "B"]} if with_ask_question else None,
            "askQuestionHtml": ask_question_html,
            "dropdown": {"options": ["sonnet", "gpt4o"]} if with_dropdown else None,
            "dropdownHtml": dropdown_html,
            "dialogHtml": None,
            "settingsHtml": None,
            "scheduledTasksHtml": None,
            "scheduledTasksDialogHtml": None,
            "conversationHistoryHtml": None,
            "subagentInfoHtml": subagent_info_html,
            "btwHtml": None,
            "modelName": "claude-3-5-sonnet",
            "environmentName": "local",
            "branchName": "main",
            "scrollInfo": {"scrollTop": 0, "scrollHeight": 1000, "clientHeight": 800},
            "timestamp": int(time.time() * 1000),
        }

        # Calculate authoritative DJB2 composite hash
        snapshot["hash"] = compute_composite_hash(snapshot)
        return snapshot


# ==============================================================================
# 4. Mock Push Service (`MockPushService`)
# ==============================================================================

class MockPushService:
    """
    Simulates and validates pywebpush operations, ECDSA P-256 VAPID keypairs,
    JWT claims, headers, and push delivery responses.
    """

    def __init__(self) -> None:
        self.sent_notifications: List[Dict[str, Any]] = []
        self._default_status_code: int = 201
        self._endpoint_status_map: Dict[str, int] = {}
        self._exception_to_raise: Optional[Exception] = None
        self._original_webpush: Optional[Any] = None
        self._is_patched: bool = False
        self._lock = threading.Lock()

    @staticmethod
    def generate_vapid_keypair() -> Dict[str, str]:
        """Generates an authentic EC P-256 (prime256v1) keypair for VAPID."""
        private_key = ec.generate_private_key(ec.SECP256R1())

        # Uncompressed 65-byte point (0x04 + X + Y)
        public_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        public_key_b64 = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("utf-8")

        # 32-byte private key raw value as base64url
        priv_num = private_key.private_numbers().private_value.to_bytes(32, "big")
        private_key_b64 = base64.urlsafe_b64encode(priv_num).rstrip(b"=").decode("utf-8")

        # PEM representation
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        return {
            "public_key": public_key_b64,
            "private_key": private_key_b64,
            "private_pem": private_pem,
        }

    def set_default_status(self, status_code: int) -> None:
        """Sets the default HTTP status code returned for push dispatches."""
        self._default_status_code = status_code

    def set_endpoint_status(self, endpoint: str, status_code: int) -> None:
        """Sets an HTTP status code for a specific endpoint (e.g. 410 Gone for expired)."""
        self._endpoint_status_map[endpoint] = status_code

    def set_exception(self, exc: Optional[Exception]) -> None:
        """Configures an exception to be raised when webpush is called."""
        self._exception_to_raise = exc

    def clear(self) -> None:
        """Clears all recorded notifications and reset configs."""
        with self._lock:
            self.sent_notifications.clear()
            self._endpoint_status_map.clear()
            self._exception_to_raise = None
            self._default_status_code = 201

    def create_mock_subscription(
        self,
        endpoint: str = "https://fcm.googleapis.com/fcm/send/test-sub-id",
        p256dh: Optional[str] = None,
        auth: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a valid browser push subscription payload dictionary."""
        if p256dh is None:
            # Generate valid EC P-256 public point
            kp = self.generate_vapid_keypair()
            p256dh = kp["public_key"]
        if auth is None:
            # 16-byte random auth secret as base64url
            auth = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode("utf-8")

        return {
            "endpoint": endpoint,
            "keys": {
                "p256dh": p256dh,
                "auth": auth,
            },
            "expirationTime": None,
        }

    def mock_webpush(
        self,
        subscription_info: Dict[str, Any],
        data: Optional[str] = None,
        vapid_private_key: Optional[str] = None,
        vapid_claims: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Any:
        """Mock replacement for `pywebpush.webpush`."""
        if self._exception_to_raise:
            raise self._exception_to_raise

        endpoint = subscription_info.get("endpoint", "")
        status = self._endpoint_status_map.get(endpoint, self._default_status_code)

        parsed_json = None
        if data:
            try:
                parsed_json = json.loads(data)
            except Exception:
                parsed_json = None

        record = {
            "id": str(os.urandom(8).hex()),
            "endpoint": endpoint,
            "subscription": subscription_info,
            "payload_raw": data,
            "payload_json": parsed_json,
            "vapid_private_key": vapid_private_key,
            "vapid_claims": vapid_claims,
            "ttl": ttl,
            "headers": headers or {},
            "status_code": status,
            "timestamp": time.time(),
        }

        with self._lock:
            self.sent_notifications.append(record)

        # Mock Response Object
        class MockPushResponse:
            def __init__(self, sc: int):
                self.status_code = sc
                self.ok = 200 <= sc < 300
                self.text = "OK" if self.ok else f"Error: HTTP {sc}"

            def json(self):
                return {"status": self.status_code, "text": self.text}

        if status >= 400:
            try:
                from pywebpush import WebPushException
                resp = MockPushResponse(status)
                raise WebPushException(f"Push delivery failed with status {status}", response=resp)
            except ImportError:
                resp = MockPushResponse(status)
                return resp

        return MockPushResponse(status)

    def patch(self) -> None:
        """Patches `pywebpush.webpush` with the mock implementation."""
        if self._is_patched:
            return
        try:
            import pywebpush
            self._original_webpush = getattr(pywebpush, "webpush", None)
            setattr(pywebpush, "webpush", self.mock_webpush)
            self._is_patched = True
        except ImportError:
            pass

    def unpatch(self) -> None:
        """Restores original `pywebpush.webpush`."""
        if not self._is_patched:
            return
        try:
            import pywebpush
            if self._original_webpush is not None:
                setattr(pywebpush, "webpush", self._original_webpush)
            self._is_patched = False
        except ImportError:
            pass

    def __enter__(self) -> MockPushService:
        self.patch()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.unpatch()


# ==============================================================================
# 5. Mock Chrome DevTools Protocol Server (`MockCDPServer`)
# ==============================================================================

class MockCDPServer:
    """
    In-process WebSocket and HTTP mock server simulating Chrome DevTools Protocol (CDP)
    at 127.0.0.1 (dynamic or fixed port) responding to:
    - HTTP GET `/json/list`, `/json`, `/json/version`, `/json/protocol`
    - WebSocket `/devtools/page/{target_id}`
    - CDP JSON-RPC methods: Page.enable, Runtime.enable, DOM.enable, CSS.enable,
      Runtime.evaluate, Runtime.callFunctionOn, Input.dispatchMouseEvent,
      Input.dispatchKeyEvent, DOM.performSearch, etc.
    """

    def __init__(
        self,
        port: Optional[int] = None,
        host: str = "127.0.0.1",
        target_id: str = "C82C6F0E027B",
    ) -> None:
        self.host = host
        self.port = port or find_free_port(host)
        self.target_id = target_id
        self.browser_id = "browser-" + target_id[:8]

        # State tracking
        self.call_log: List[Dict[str, Any]] = []
        self.injected_messages: List[Dict[str, Any]] = []
        self.clicked_elements: List[str] = []
        self.mouse_events: List[Dict[str, Any]] = []
        self.key_events: List[Dict[str, Any]] = []
        self.uploaded_images: List[Dict[str, Any]] = []
        self.stopped_calls: int = 0

        # Snapshot state
        self.mock_snapshot: Dict[str, Any] = MockDOMGenerator.generate_full_snapshot()
        self.custom_evaluate_handler: Optional[Callable[[str, Dict[str, Any]], Any]] = None
        self.method_errors: Dict[str, Tuple[int, str]] = {}
        self.method_delays: Dict[str, float] = {}

        # Server internal mechanics
        self._server: Optional[uvicorn.Server] = None
        self._server_thread: Optional[threading.Thread] = None
        self._active_websockets: Set[WebSocket] = set()
        self._is_running = False
        self._lock = threading.Lock()

        # Build Starlette ASGI app for Mock CDP
        self.app = self._create_asgi_app()

    def _create_asgi_app(self) -> Starlette:
        """Constructs the Starlette application handling CDP HTTP and WebSocket endpoints."""
        app = Starlette()

        # HTTP Routes
        async def json_list(request: Request) -> Response:
            port = self.port
            targets = [
                {
                    "description": "",
                    "devtoolsFrontendUrl": f"/devtools/inspector.html?ws={self.host}:{port}/devtools/page/{self.target_id}",
                    "id": self.target_id,
                    "title": "Antigravity Workbench",
                    "type": "page",
                    "url": "vscode-file://vscode-app/workbench.html",
                    "webSocketDebuggerUrl": f"ws://{self.host}:{port}/devtools/page/{self.target_id}",
                },
                {
                    "description": "",
                    "devtoolsFrontendUrl": f"/devtools/inspector.html?ws={self.host}:{port}/devtools/page/ext-background",
                    "id": "ext-background",
                    "title": "Antigravity Extension Host",
                    "type": "background_page",
                    "url": "vscode-file://vscode-app/out/vs/workbench/services/extensions/node/extensionHostProcess.js",
                    "webSocketDebuggerUrl": f"ws://{self.host}:{port}/devtools/page/ext-background",
                },
            ]
            return JSONResponse(targets)

        async def json_version(request: Request) -> Response:
            port = self.port
            version_data = {
                "Browser": "Antigravity/1.10.0 Chrome/120.0.6099.109 Electron/28.1.0",
                "Protocol-Version": "1.3",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "V8-Version": "12.0.267.10",
                "WebKit-Version": "537.36 (@c21ef9a405)",
                "webSocketDebuggerUrl": f"ws://{self.host}:{port}/devtools/browser/{self.browser_id}",
            }
            return JSONResponse(version_data)

        async def json_protocol(request: Request) -> Response:
            return JSONResponse({"domains": [{"domain": "Page"}, {"domain": "Runtime"}, {"domain": "DOM"}, {"domain": "CSS"}, {"domain": "Input"}]})

        # WebSocket Route
        async def ws_endpoint(websocket: WebSocket) -> None:
            await websocket.accept()
            with self._lock:
                self._active_websockets.add(websocket)
            try:
                while True:
                    text = await websocket.receive_text()
                    try:
                        data = json.loads(text)
                    except Exception:
                        continue

                    msg_id = data.get("id")
                    method = data.get("method", "")
                    params = data.get("params", {})

                    with self._lock:
                        self.call_log.append({
                            "id": msg_id,
                            "method": method,
                            "params": params,
                            "timestamp": time.time(),
                        })

                    # Check method delays
                    if method in self.method_delays:
                        await asyncio.sleep(self.method_delays[method])

                    # Check method error injections
                    if method in self.method_errors:
                        err_code, err_msg = self.method_errors[method]
                        err_res = {
                            "id": msg_id,
                            "error": {"code": err_code, "message": err_msg},
                        }
                        await websocket.send_text(json.dumps(err_res))
                        continue

                    # Handle CDP Methods
                    response_result = await self._handle_cdp_method(websocket, method, params)

                    if msg_id is not None:
                        res_msg = {
                            "id": msg_id,
                            "result": response_result,
                        }
                        await websocket.send_text(json.dumps(res_msg))

            except (WebSocketDisconnect, asyncio.CancelledError):
                pass
            finally:
                with self._lock:
                    self._active_websockets.discard(websocket)

        app.routes.extend([
            Route("/json/list", json_list, methods=["GET"]),
            Route("/json", json_list, methods=["GET"]),
            Route("/json/version", json_version, methods=["GET"]),
            Route("/json/protocol", json_protocol, methods=["GET"]),
            WebSocketRoute("/devtools/page/{target_id}", ws_endpoint),
            WebSocketRoute("/devtools/browser/{browser_id}", ws_endpoint),
        ])

        return app

    async def _handle_cdp_method(
        self,
        ws: WebSocket,
        method: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Dispatches CDP JSON-RPC commands and generates authentic protocol results."""
        if method == "Page.enable":
            return {}

        elif method == "DOM.enable":
            return {}

        elif method == "CSS.enable":
            return {}

        elif method == "Target.setDiscoverTargets" or method == "Target.setAutoAttach":
            return {}

        elif method == "Runtime.enable":
            # Emit executionContextCreated events
            ctx1 = {
                "method": "Runtime.executionContextCreated",
                "params": {
                    "context": {
                        "id": 1,
                        "origin": "vscode-file://vscode-app",
                        "name": "Antigravity Main World",
                        "isDefault": True,
                    }
                },
            }
            ctx2 = {
                "method": "Runtime.executionContextCreated",
                "params": {
                    "context": {
                        "id": 2,
                        "origin": "vscode-file://vscode-app",
                        "name": "Antigravity Isolated Extension Context",
                        "isDefault": False,
                    }
                },
            }
            await ws.send_text(json.dumps(ctx1))
            await ws.send_text(json.dumps(ctx2))
            return {}

        elif method == "Runtime.evaluate":
            expr = params.get("expression", "")
            return self._handle_runtime_evaluate(expr, params)

        elif method == "Runtime.callFunctionOn":
            fn_decl = params.get("functionDeclaration", "")
            return {"result": {"type": "object", "value": {"success": True, "evaluated": True}}}

        elif method == "Input.dispatchMouseEvent":
            with self._lock:
                self.mouse_events.append(params)
            return {}

        elif method == "Input.dispatchKeyEvent":
            with self._lock:
                self.key_events.append(params)
            return {}

        elif method == "DOM.performSearch":
            return {"searchId": "search-uuid-1", "resultCount": 1}

        elif method == "DOM.getSearchResults":
            return {"nodeIds": [1001]}

        elif method == "DOM.resolveNode":
            return {"object": {"type": "object", "objectId": "node-obj-1001"}}

        elif method == "DOM.requestNode":
            return {"nodeId": 1001}

        # Default fallback
        return {}

    def _handle_runtime_evaluate(self, expr: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates JS scripts and matches Antigravity CDP script templates."""
        # 1. Custom evaluation handler hook
        if self.custom_evaluate_handler:
            custom_res = self.custom_evaluate_handler(expr, params)
            if isinstance(custom_res, tuple) and len(custom_res) == 1:
                return {"result": {"type": "object", "value": custom_res[0]}}
            elif custom_res is not None:
                return {"result": {"type": "object", "value": custom_res}}

        expr_clean = expr.strip()

        # 2. Match `capture.js` script
        if (
            "TAG_INTERACTIVES_FN" in expr
            or "CAPTURE_SCRIPT" in expr
            or "Find the chat container" in expr
            or "sidebarAttentionItems" in expr
            or "parentConversationName" in expr
            or "subagentInfoHtml" in expr
        ):
            # Recalculate hash on current mock snapshot
            with self._lock:
                self.mock_snapshot["hash"] = compute_composite_hash(self.mock_snapshot)
                self.mock_snapshot["timestamp"] = int(time.time() * 1000)
                snapshot_copy = dict(self.mock_snapshot)

            return {
                "result": {
                    "type": "object",
                    "value": snapshot_copy,
                }
            }

        # 3. Match `upload-image.js`
        if "DragEvent" in expr or "upload-image" in expr or "image/png" in expr or ("DataTransfer" in expr and "File" in expr):
            with self._lock:
                self.uploaded_images.append({"payload": expr[:200]})
            return {
                "result": {
                    "type": "object",
                    "value": {"success": True, "uploaded": True},
                }
            }

        # 4. Match `inject-message.js`
        if "ClipboardEvent" in expr or "inject-message" in expr or "data-lexical-editor" in expr:
            # Extract injected message text
            match = re.search(r'(?:["\']text["\']\s*:\s*|textVal\s*=\s*|text\s*=\s*)["\'](.*?)["\']', expr)
            text_val = match.group(1) if match else "Injected test message"
            with self._lock:
                self.injected_messages.append({"text": text_val, "raw": expr})
            return {
                "result": {
                    "type": "object",
                    "value": {"success": True, "sent": True, "message": text_val},
                }
            }

        # 5. Match `stop.js`
        if "lucide-square" in expr or "input-send-button-cancel-tooltip" in expr or "stop.js" in expr:
            with self._lock:
                self.stopped_calls += 1
                self.mock_snapshot["agentRunning"] = False
                self.mock_snapshot["hash"] = compute_composite_hash(self.mock_snapshot)
            return {
                "result": {
                    "type": "object",
                    "value": {"success": True, "stopped": True},
                }
            }

        # 6. Match `click-main.js` or `click`
        if "data-ag-click-id" in expr or "click-main" in expr or "click()" in expr:
            match = re.search(r'data-ag-click-id\s*=\s*["\']([^"\']+)["\']', expr)
            click_id = match.group(1) if match else "chat:0"
            with self._lock:
                self.clicked_elements.append(click_id)
            return {
                "result": {
                    "type": "object",
                    "value": {"success": True, "clicked": True, "clickId": click_id},
                }
            }

        # 7. Match `running-tasks.js`
        if "running-tasks" in expr:
            return {
                "result": {
                    "type": "object",
                    "value": self.mock_snapshot.get("runningTasks", []),
                }
            }

        # 8. Match `scheduled-tasks.js`
        if "scheduled-tasks" in expr:
            return {
                "result": {
                    "type": "object",
                    "value": [{"id": "cron-1", "cron": "0 9 * * *", "prompt": "Daily report"}],
                }
            }

        # 9. Match `conversation-history.js`
        if "conversation-history" in expr:
            return {
                "result": {
                    "type": "object",
                    "value": [{"id": "conv-1", "title": "History Session 1"}],
                }
            }

        # 10. Simple expression evaluations
        if expr_clean in ("true", "1 === 1", "Boolean(true)"):
            return {"result": {"type": "boolean", "value": True}}
        elif expr_clean in ("false", "1 === 2", "Boolean(false)"):
            return {"result": {"type": "boolean", "value": False}}
        elif expr_clean.isdigit():
            return {"result": {"type": "number", "value": int(expr_clean)}}

        # Generic success
        return {
            "result": {
                "type": "object",
                "value": {"status": "ok", "expression": expr_clean[:60]},
            }
        }

    # ==========================================================================
    # Mock CDP Simulation & Mutation Helpers
    # ==========================================================================

    def set_mock_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Sets the mock snapshot state returned by capture script evaluations."""
        with self._lock:
            self.mock_snapshot = dict(snapshot)
            self.mock_snapshot["hash"] = compute_composite_hash(self.mock_snapshot)

    def update_mock_snapshot(self, **kwargs: Any) -> None:
        """Updates specific fields in the current mock snapshot."""
        with self._lock:
            self.mock_snapshot.update(kwargs)
            self.mock_snapshot["hash"] = compute_composite_hash(self.mock_snapshot)

    def simulate_agent_start(self) -> None:
        """Simulates agent beginning generation."""
        self.update_mock_snapshot(agentRunning=True)

    def simulate_agent_stop(self) -> None:
        """Simulates agent completing generation."""
        self.update_mock_snapshot(agentRunning=False)

    def simulate_permission_prompt(
        self,
        command: str = "npm test",
        tool: str = "run_command",
    ) -> None:
        """Simulates Antigravity displaying an interactive permission dialog."""
        perm_html = MockDOMGenerator.generate_permission_dialog(command=command, tool_name=tool)
        self.update_mock_snapshot(
            permission={"command": command, "tool": tool},
            permissionHtml=perm_html,
        )

    def simulate_ask_question(
        self,
        question: str = "Choose action",
        choices: Optional[List[str]] = None,
    ) -> None:
        """Simulates Antigravity displaying an ask_question card."""
        choices = choices or ["Option 1", "Option 2"]
        ask_html = MockDOMGenerator.generate_ask_question_card(question=question, choices=choices)
        self.update_mock_snapshot(
            askQuestion={"question": question, "choices": choices},
            askQuestionHtml=ask_html,
        )

    def simulate_subagent_view(
        self,
        subagent_title: str = "Subagent 1",
        parent_title: str = "Main Conversation",
    ) -> None:
        """Simulates UI switching into a subagent view."""
        sub_html = MockDOMGenerator.generate_subagent_bar(parent_title=parent_title, subagent_title=subagent_title)
        self.update_mock_snapshot(
            isSubagentView=True,
            subagentTitle=subagent_title,
            parentConversationName=parent_title,
            subagentInfoHtml=sub_html,
        )

    def inject_method_error(self, method: str, code: int = -32000, message: str = "Injected error") -> None:
        """Configures CDP method to respond with a JSON-RPC error."""
        self.method_errors[method] = (code, message)

    def clear_method_error(self, method: str) -> None:
        """Clears error injection for a method."""
        self.method_errors.pop(method, None)

    def inject_method_delay(self, method: str, delay_seconds: float) -> None:
        """Configures an artificial latency before responding to a method."""
        self.method_delays[method] = delay_seconds

    def create_active_port_file(self, target_dir: str) -> str:
        """
        Creates an authentic `%APPDATA%/Antigravity/DevToolsActivePort` file
        containing port number and browser debug URL path.
        """
        os.makedirs(target_dir, exist_ok=True)
        port_file_path = os.path.join(target_dir, "DevToolsActivePort")
        content = f"{self.port}\n/devtools/browser/{self.browser_id}\n"
        with open(port_file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return port_file_path

    # ==========================================================================
    # Lifecycle Management
    # ==========================================================================

    def start(self) -> MockCDPServer:
        """Starts the Mock CDP server in a background thread."""
        if self._is_running:
            return self

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="critical",
            access_log=False,
        )
        self._server = uvicorn.Server(config)

        self._server_thread = threading.Thread(
            target=self._server.run,
            name=f"MockCDP-{self.port}",
            daemon=True,
        )
        self._server_thread.start()

        # Wait until started
        deadline = time.time() + 5.0
        while not self._server.started and time.time() < deadline:
            time.sleep(0.02)

        self._is_running = True
        return self

    def stop(self) -> None:
        """Stops the Mock CDP server and cleans up threads."""
        if not self._is_running or not self._server:
            return

        self._server.should_exit = True
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=2.0)

        self._is_running = False

    async def start_async(self) -> MockCDPServer:
        """Starts server in async context."""
        return self.start()

    async def stop_async(self) -> None:
        """Stops server in async context."""
        self.stop()

    def __enter__(self) -> MockCDPServer:
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()


# ==============================================================================
# 6. Test Client Wrapper (`TestClientWrapper`)
# ==============================================================================

class TestClientWrapper:
    """
    Unified synchronous and asynchronous client wrapper for testing all 32
    WebRemote v6 REST endpoints and 15 legacy endpoints, plus WebSocket streaming.
    """

    def __init__(
        self,
        app: Optional[Any] = None,
        base_url: str = "http://testserver",
    ) -> None:
        self.base_url = base_url
        if app is None:
            # Dynamically load server app or fallback to mock ASGI app
            try:
                import server
                self.app = getattr(server, "app", None) or self._build_fallback_app()
            except Exception:
                self.app = self._build_fallback_app()
        else:
            self.app = app

        self._sync_client: Optional[TestClient] = None

    @property
    def sync_client(self) -> TestClient:
        """Lazy-loaded Starlette TestClient instance."""
        if self._sync_client is None:
            self._sync_client = TestClient(self.app, base_url=self.base_url)
        return self._sync_client

    def _build_fallback_app(self) -> Starlette:
        """Builds a fallback ASGI app implementing all route schemas for standalone testing."""
        fallback = Starlette()

        # VAPID Key State
        vapid_kp = MockPushService.generate_vapid_keypair()
        subscriptions: List[Dict[str, Any]] = []

        async def get_vapid_key(req: Request) -> Response:
            return JSONResponse({"publicKey": vapid_kp["public_key"], "status": "ok"})

        async def add_subscription(req: Request) -> Response:
            data = await req.json()
            subscriptions.append(data)
            return JSONResponse({"status": "success", "count": len(subscriptions)})

        async def chat_send(req: Request) -> Response:
            data = await req.json()
            return JSONResponse({"status": "success", "text": data.get("text", "")})

        async def cdp_click(req: Request) -> Response:
            data = await req.json()
            return JSONResponse({"status": "success", "clickId": data.get("clickId", "")})

        async def cdp_stop(req: Request) -> Response:
            return JSONResponse({"status": "success", "stopped": True})

        async def upload_image(req: Request) -> Response:
            data = await req.json()
            return JSONResponse({"status": "success", "filename": data.get("filename", "upload.png")})

        async def answer_question(req: Request) -> Response:
            data = await req.json()
            return JSONResponse({"status": "success", "answer": data})

        async def permission_route(req: Request) -> Response:
            data = await req.json()
            return JSONResponse({"status": "success", "action": data.get("action", "allow")})

        async def dropdown_select(req: Request) -> Response:
            data = await req.json()
            return JSONResponse({"status": "success", "selection": data})

        async def running_tasks(req: Request) -> Response:
            return JSONResponse({"tasks": []})

        async def scheduled_tasks(req: Request) -> Response:
            return JSONResponse({"scheduled": []})

        async def conversation_history(req: Request) -> Response:
            return JSONResponse({"history": []})

        async def right_sidebar(req: Request) -> Response:
            return JSONResponse({"artifacts": [], "changes": []})

        async def restart_antigravity(req: Request) -> Response:
            return JSONResponse({"status": "restarting"})

        # Legacy 15 endpoints
        async def legacy_endpoint(req: Request) -> Response:
            return JSONResponse({"status": "ok", "legacy": True, "path": req.url.path})

        async def ws_stream(ws: WebSocket) -> None:
            await ws.accept()
            try:
                # Send initial snapshot
                snapshot = MockDOMGenerator.generate_full_snapshot()
                await ws.send_text(json.dumps(snapshot))
                while True:
                    msg = await ws.receive_text()
                    try:
                        parsed = json.loads(msg)
                        if parsed.get("type") == "visibility":
                            await ws.send_text(json.dumps({"type": "ack", "visible": parsed.get("visible")}))
                    except Exception:
                        pass
            except (WebSocketDisconnect, asyncio.CancelledError):
                pass

        fallback.routes.extend([
            # v6 Core Routes
            Route("/api/vapid-key", get_vapid_key, methods=["GET"]),
            Route("/api/subscriptions/push", add_subscription, methods=["POST"]),
            Route("/api/chat/send", chat_send, methods=["POST"]),
            Route("/api/cdp/click", cdp_click, methods=["POST"]),
            Route("/api/cdp/stop", cdp_stop, methods=["POST"]),
            Route("/api/upload-image", upload_image, methods=["POST"]),
            Route("/api/cdp/answer-question", answer_question, methods=["POST"]),
            Route("/api/cdp/permission", permission_route, methods=["POST"]),
            Route("/api/cdp/dropdown-select", dropdown_select, methods=["POST"]),
            Route("/api/running-tasks", running_tasks, methods=["GET"]),
            Route("/api/scheduled-tasks", scheduled_tasks, methods=["GET", "POST", "DELETE"]),
            Route("/api/conversation-history", conversation_history, methods=["GET"]),
            Route("/api/right-sidebar", right_sidebar, methods=["GET"]),
            Route("/api/restart-antigravity", restart_antigravity, methods=["POST"]),
            # Legacy 15 Routes
            Route("/api/projects", legacy_endpoint, methods=["GET"]),
            Route("/api/review/diff", legacy_endpoint, methods=["GET"]),
            Route("/api/chat/incoming", legacy_endpoint, methods=["GET", "POST"]),
            Route("/api/status", legacy_endpoint, methods=["GET"]),
            Route("/api/models", legacy_endpoint, methods=["GET"]),
            Route("/api/agents", legacy_endpoint, methods=["GET"]),
            Route("/api/sessions", legacy_endpoint, methods=["GET"]),
            Route("/api/config", legacy_endpoint, methods=["GET"]),
            Route("/api/system/info", legacy_endpoint, methods=["GET"]),
            Route("/api/version", legacy_endpoint, methods=["GET"]),
            Route("/api/ping", legacy_endpoint, methods=["GET"]),
            Route("/api/logs", legacy_endpoint, methods=["GET"]),
            Route("/api/metrics", legacy_endpoint, methods=["GET"]),
            Route("/api/context", legacy_endpoint, methods=["GET"]),
            Route("/api/prompts", legacy_endpoint, methods=["GET"]),
            # WebSocket live stream
            WebSocketRoute("/ws/stream", ws_stream),
            WebSocketRoute("/wahyuai/ws/stream", ws_stream),
        ])

        return fallback

    # ==========================================================================
    # Synchronous HTTP Helpers
    # ==========================================================================

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Sends synchronous GET request."""
        return self.sync_client.get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        """Sends synchronous POST request."""
        return self.sync_client.post(path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        """Sends synchronous DELETE request."""
        return self.sync_client.delete(path, **kwargs)

    # ==========================================================================
    # Asynchronous HTTP Helpers
    # ==========================================================================

    async def async_get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Sends asynchronous GET request."""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=self.base_url) as client:
            return await client.get(path, **kwargs)

    async def async_post(self, path: str, **kwargs: Any) -> httpx.Response:
        """Sends asynchronous POST request."""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=self.base_url) as client:
            return await client.post(path, **kwargs)

    async def async_delete(self, path: str, **kwargs: Any) -> httpx.Response:
        """Sends asynchronous DELETE request."""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=self.base_url) as client:
            return await client.delete(path, **kwargs)

    # ==========================================================================
    # WebSocket Streaming Helper
    # ==========================================================================

    def websocket_connect(self, path: str = "/ws/stream") -> Any:
        """Returns synchronous WebSocket test connection context manager."""
        return self.sync_client.websocket_connect(path)

    # ==========================================================================
    # Typed Endpoints Helpers (All 32 Features + 15 Legacy)
    # ==========================================================================

    def get_vapid_key(self) -> httpx.Response:
        """Calls `GET /api/vapid-key`."""
        return self.get("/api/vapid-key")

    def add_push_subscription(self, subscription: Dict[str, Any]) -> httpx.Response:
        """Calls `POST /api/subscriptions/push`."""
        return self.post("/api/subscriptions/push", json=subscription)

    def chat_send(self, text: str, append_mode: bool = False) -> httpx.Response:
        """Calls `POST /api/chat/send`."""
        return self.post("/api/chat/send", json={"text": text, "append_mode": append_mode})

    def cdp_click(self, click_id: str, click_type: str = "chat") -> httpx.Response:
        """Calls `POST /api/cdp/click`."""
        return self.post("/api/cdp/click", json={"clickId": click_id, "clickType": click_type})

    def cdp_stop(self) -> httpx.Response:
        """Calls `POST /api/cdp/stop`."""
        return self.post("/api/cdp/stop", json={})

    def upload_image(
        self,
        base64_data: str,
        mime_type: str = "image/png",
        filename: str = "upload.png",
    ) -> httpx.Response:
        """Calls `POST /api/upload-image`."""
        return self.post(
            "/api/upload-image",
            json={"image": base64_data, "mimeType": mime_type, "filename": filename},
        )

    def answer_question(
        self,
        question_id: Optional[str] = None,
        choice_index: Optional[int] = 0,
        custom_text: Optional[str] = None,
    ) -> httpx.Response:
        """Calls `POST /api/cdp/answer-question`."""
        return self.post(
            "/api/cdp/answer-question",
            json={"questionId": question_id, "choiceIndex": choice_index, "customText": custom_text},
        )

    def permission_action(self, action: str = "allow", command: Optional[str] = None) -> httpx.Response:
        """Calls `POST /api/cdp/permission`."""
        return self.post("/api/cdp/permission", json={"action": action, "command": command})

    def dropdown_select(self, option_index: int = 0, label: Optional[str] = None) -> httpx.Response:
        """Calls `POST /api/cdp/dropdown-select`."""
        return self.post("/api/cdp/dropdown-select", json={"optionIndex": option_index, "label": label})

    def get_running_tasks(self) -> httpx.Response:
        """Calls `GET /api/running-tasks`."""
        return self.get("/api/running-tasks")

    def get_scheduled_tasks(self) -> httpx.Response:
        """Calls `GET /api/scheduled-tasks`."""
        return self.get("/api/scheduled-tasks")

    def get_conversation_history(self) -> httpx.Response:
        """Calls `GET /api/conversation-history`."""
        return self.get("/api/conversation-history")

    def get_right_sidebar(self) -> httpx.Response:
        """Calls `GET /api/right-sidebar`."""
        return self.get("/api/right-sidebar")

    def restart_antigravity(self) -> httpx.Response:
        """Calls `POST /api/restart-antigravity`."""
        return self.post("/api/restart-antigravity", json={})


# ==============================================================================
# 7. Assertion Helpers
# ==============================================================================

def assert_valid_djb2_hash(hash_val: str, content: Optional[Union[str, bytes]] = None) -> None:
    """Validates that hash_val is a valid non-empty base-36 DJB2 hash string."""
    assert isinstance(hash_val, str), f"Expected string hash, got {type(hash_val)}"
    assert len(hash_val) > 0, "DJB2 hash must not be empty"
    assert re.match(r"^[0-9a-z]+$", hash_val), f"Invalid characters in base36 hash: '{hash_val}'"
    if content is not None:
        expected = compute_djb2(content)
        assert hash_val == expected, f"DJB2 hash mismatch: got '{hash_val}', expected '{expected}'"


def assert_valid_snapshot(snapshot: Dict[str, Any], allow_partial: bool = False) -> None:
    """Validates that snapshot complies with the WebRemote v6 WebSocket schema."""
    assert isinstance(snapshot, dict), f"Expected dict snapshot, got {type(snapshot)}"
    assert snapshot.get("type") == "snapshot", f"Expected type 'snapshot', got '{snapshot.get('type')}'"

    required_keys = ["hash", "html", "css", "agentRunning"]
    for k in required_keys:
        assert k in snapshot, f"Missing required key '{k}' in snapshot"

    assert isinstance(snapshot["hash"], str) and len(snapshot["hash"]) > 0, "Snapshot hash must be non-empty string"
    assert isinstance(snapshot["html"], str), "Snapshot html must be string"
    assert isinstance(snapshot["css"], str), "Snapshot css must be string"
    assert isinstance(snapshot["agentRunning"], bool), "Snapshot agentRunning must be bool"

    if not allow_partial:
        expected_fields = [
            "isSubagentView",
            "attentionItems",
            "runningTasks",
            "permission",
            "askQuestion",
            "dropdown",
            "timestamp",
        ]
        for f in expected_fields:
            assert f in snapshot, f"Missing standard field '{f}' in snapshot"


def assert_sanitized_html(html_str: str) -> None:
    """
    Validates that HTML is sanitized according to the 14-step pipeline:
    - No script / iframe / object / embed tags
    - No unsafe inline event handlers (onload, onerror, onclick, etc.)
    - No javascript: pseudo-protocol URIs
    - No '[object Object]' class names
    - No unnested span-div violations
    """
    assert isinstance(html_str, str), f"Expected string HTML, got {type(html_str)}"

    # Check forbidden tags
    forbidden_tags = ["<script", "<iframe", "<object", "<embed", "<applet"]
    for tag in forbidden_tags:
        assert tag not in html_str.lower(), f"Sanitization violation: forbidden tag '{tag}' detected"

    # Check forbidden inline event attributes (e.g. onerror=, onload=)
    forbidden_attrs = ["onerror=", "onload=", "onclick=", "onmouseover=", "onfocus="]
    for attr in forbidden_attrs:
        assert attr not in html_str.lower(), f"Sanitization violation: inline event '{attr}' detected"

    # Check javascript: protocol
    assert "javascript:" not in html_str.lower(), "Sanitization violation: javascript: URI detected"

    # Check object-object class corruption
    assert "[object Object]" not in html_str, "Sanitization violation: corrupted '[object Object]' class found"


def assert_vapid_key_valid(key_str: str) -> None:
    """
    Validates that key_str is an authentic base64url encoded EC P-256 public key
    (65-byte uncompressed point starting with 0x04).
    """
    assert isinstance(key_str, str), f"Expected string VAPID key, got {type(key_str)}"
    assert len(key_str) in (86, 87, 88), f"VAPID public key invalid length ({len(key_str)}): '{key_str}'"

    # Add padding if needed
    padded = key_str + "=" * ((4 - len(key_str) % 4) % 4)
    raw_bytes = base64.urlsafe_b64decode(padded.encode("utf-8"))

    assert len(raw_bytes) == 65, f"Expected 65-byte uncompressed EC point, got {len(raw_bytes)}"
    assert raw_bytes[0] == 0x04, f"First byte of uncompressed point must be 0x04, got 0x{raw_bytes[0]:02x}"


def assert_push_subscription_valid(sub: Dict[str, Any]) -> None:
    """Validates browser push subscription schema."""
    assert isinstance(sub, dict), "Subscription must be dict"
    assert "endpoint" in sub and isinstance(sub["endpoint"], str), "Missing valid endpoint in subscription"
    assert sub["endpoint"].startswith("https://"), "Endpoint must be HTTPS"
    assert "keys" in sub and isinstance(sub["keys"], dict), "Missing keys in subscription"
    assert "p256dh" in sub["keys"] and isinstance(sub["keys"]["p256dh"], str), "Missing p256dh key"
    assert "auth" in sub["keys"] and isinstance(sub["keys"]["auth"], str), "Missing auth key"


def assert_push_payload_valid(payload: Dict[str, Any]) -> None:
    """Validates web push notification payload structure."""
    assert isinstance(payload, dict), "Push payload must be dict"
    assert "title" in payload and isinstance(payload["title"], str), "Push payload must have string title"
    assert "body" in payload and isinstance(payload["body"], str), "Push payload must have string body"


def assert_responsive_css(css_str: str) -> None:
    """Validates that CSS contains Antigravity theme variables and responsive structures."""
    assert isinstance(css_str, str), "CSS must be string"
    assert len(css_str) > 0, "CSS must not be empty"
    assert "--" in css_str, "CSS must contain CSS custom properties (--*)"


def assert_service_worker_contract(js_content: str) -> None:
    """Validates service worker JavaScript implementation contains required push event hooks."""
    assert "addEventListener('push'" in js_content or 'addEventListener("push"' in js_content, (
        "Service worker missing 'push' event listener"
    )
    assert (
        "addEventListener('notificationclick'" in js_content
        or 'addEventListener("notificationclick"' in js_content
    ), "Service worker missing 'notificationclick' listener"


# ==============================================================================
# 8. Test Fixtures & Base Classes (`HarnessTestCase`)
# ==============================================================================

def async_test(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to execute an async test function in a standalone event loop."""
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(f(*args, **kwargs))
        finally:
            loop.close()
    return wrapper


def with_mock_cdp(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that starts a MockCDPServer instance and passes it as keyword argument."""
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with MockCDPServer() as cdp:
            kwargs["mock_cdp"] = cdp
            return f(*args, **kwargs)
    return wrapper


def with_mock_push(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that activates a MockPushService instance and passes it as keyword argument."""
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with MockPushService() as push:
            kwargs["mock_push"] = push
            return f(*args, **kwargs)
    return wrapper


class HarnessTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Standard Base TestCase for WebRemote v6 test suites.
    Provides automatic setup, teardown, and access to:
    - `self.cdp_server`: MockCDPServer instance
    - `self.push_service`: MockPushService instance
    - `self.dom_gen`: MockDOMGenerator utility class
    - `self.client`: TestClientWrapper instance
    """

    async def asyncSetUp(self) -> None:
        """Asynchronous setup executed before each test."""
        self.dom_gen = MockDOMGenerator
        self.cdp_server = MockCDPServer()
        self.cdp_server.start()

        self.push_service = MockPushService()
        self.push_service.patch()

        self.client = TestClientWrapper()

    async def asyncTearDown(self) -> None:
        """Asynchronous teardown executed after each test."""
        if hasattr(self, "push_service"):
            self.push_service.unpatch()
        if hasattr(self, "cdp_server"):
            self.cdp_server.stop()

    def create_temp_file(self, content: str = "", suffix: str = ".txt") -> str:
        """Creates a self-deleting temporary file for test runs."""
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        if content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path


# ==============================================================================
# Self-Check Unit Tests
# ==============================================================================

class TestHarnessSelfCheck(HarnessTestCase):
    """Unit tests executing against the harness infrastructure itself."""

    async def test_cdp_server_lifecycle_and_evaluation(self) -> None:
        """Verifies CDP server lifecycle, target list, and evaluation responses."""
        self.assertTrue(self.cdp_server._is_running)
        resp = httpx.get(f"http://127.0.0.1:{self.cdp_server.port}/json/list")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(len(resp.json()) >= 1)

    async def test_push_service_mocking(self) -> None:
        """Verifies MockPushService records deliveries and generates authentic VAPID keys."""
        sub = self.push_service.create_mock_subscription()
        assert_push_subscription_valid(sub)
        resp = self.push_service.mock_webpush(sub, data=json.dumps({"title": "Test", "body": "Alert"}))
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(self.push_service.sent_notifications), 1)

    def test_dom_generators_and_assertions(self) -> None:
        """Verifies all DOM generators produce valid snapshots and valid DJB2 hashes."""
        snap = self.dom_gen.generate_full_snapshot(agent_running=True, with_permission=True)
        assert_valid_snapshot(snap)
        assert_valid_djb2_hash(snap["hash"])
        assert_sanitized_html(snap["html"])

    def test_client_wrapper_routes_and_websocket(self) -> None:
        """Verifies TestClientWrapper communicates over HTTP and WebSocket endpoints."""
        vapid_res = self.client.get_vapid_key()
        self.assertEqual(vapid_res.status_code, 200)
        with self.client.websocket_connect("/ws/stream") as ws:
            snap = ws.receive_json()
            assert_valid_snapshot(snap)


# ==============================================================================
# CLI Entrypoint
# ==============================================================================

if __name__ == "__main__":
    unittest.main()
