"""
Chrome DevTools Protocol (CDP) Bridge for Antigravity WebRemote v6.
Pure Python async implementation supporting:
- Dynamic DevTools port discovery (%APPDATA%\\Antigravity\\DevToolsActivePort and socket probe)
- Multi-context V8 execution tracking (Main World & Isolated Contexts)
- 31 browser-side CDP automation scripts
- Live chat DOM capture, 14-step sanitization, CSS extraction, and DJB2 state hashing
- Two-way user interaction (inject message, clicks, stop, upload image, type text)
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field, asdict

import aiohttp
import websockets
import websockets.exceptions

logger = logging.getLogger("cdp_bridge")


# ============================================================================
# 1. Data Models & Dataclasses
# ============================================================================

@dataclass
class CDPTarget:
    """Represents a Chrome DevTools Protocol target from /json/list."""
    id: str
    title: str
    type: str
    url: str
    webSocketDebuggerUrl: str
    devtoolsFrontendUrl: Optional[str] = None
    description: Optional[str] = ""


@dataclass
class ExecutionContext:
    """Represents a V8 execution context in the Electron renderer."""
    id: int
    origin: str
    name: str
    aux_data: Dict[str, Any] = field(default_factory=dict)
    is_default_flag: bool = False

    @property
    def is_default(self) -> bool:
        """Returns True if this is the Main World default context."""
        return self.is_default_flag or bool(self.aux_data.get("isDefault", False))


@dataclass
class AttentionItem:
    """Represents a sidebar conversation item needing user attention."""
    id: str               # Conversation UUID
    type: str             # "question" | "command" | "completed"
    name: str             # Conversation title / label


@dataclass
class ScrollInfo:
    """Scroll metrics of the chat DOM container."""
    scrollTop: int = 0
    scrollHeight: int = 0
    clientHeight: int = 0


@dataclass
class DOMSnapshot:
    """Captured DOM and UI state snapshot of the Antigravity desktop window."""
    html: str = ""
    css: str = ""
    agentRunning: bool = False
    hash: str = ""
    timestamp: str = ""
    scrollInfo: Optional[Dict[str, Any]] = None
    leftSidebarHtml: Optional[str] = None
    sidebarAttentionItems: List[Dict[str, Any]] = field(default_factory=list)
    sidebarSignature: Optional[str] = None
    isSidebarOpen: bool = False
    isNewSessionPage: bool = False
    isInputBoxHidden: bool = False
    isSubagentView: bool = False
    parentConversationName: str = ""
    subagentInfoHtml: Optional[str] = None
    dropdownHtml: Optional[str] = None
    dialogHtml: Optional[str] = None
    settingsHtml: Optional[str] = None
    activeArtifactUri: Optional[str] = None
    activeFileUri: Optional[str] = None
    askQuestionHtml: Optional[str] = None
    permissionHtml: Optional[str] = None
    runningTasksHtml: Optional[str] = None
    scheduledTasksHtml: Optional[str] = None
    scheduledTasksDialogHtml: Optional[str] = None
    conversationHistoryHtml: Optional[str] = None
    btwHtml: Optional[str] = None
    environmentName: Optional[str] = None
    branchName: Optional[str] = None
    modelName: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ActionResult:
    """Standardized action response returned by CDP interactions."""
    ok: bool
    reason: Optional[str] = None
    method: Optional[str] = None
    label: Optional[str] = None
    source: Optional[str] = None
    error: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {"ok": self.ok}
        if self.reason is not None:
            res["reason"] = self.reason
        if self.method is not None:
            res["method"] = self.method
        if self.label is not None:
            res["label"] = self.label
        if self.source is not None:
            res["source"] = self.source
        if self.error is not None:
            res["error"] = self.error
        if self.data is not None:
            res.update(self.data)
        return res


# ============================================================================
# 2. DJB2 State Hashing
# ============================================================================

def compute_djb2_hash(s: str) -> str:
    """
    Computes a 32-bit DJB2 hash encoded as a base-36 string.
    Fully bitwise and encoding compatible with Node.js AG2R hashString(str).
    """
    if not s:
        return "45h"

    # Encode as UTF-16LE to match JS String.prototype.charCodeAt (UTF-16 code units)
    utf16_bytes = s.encode("utf-16le")
    code_units = [
        int.from_bytes(utf16_bytes[i : i + 2], "little")
        for i in range(0, len(utf16_bytes), 2)
    ]

    hash_val = 5381
    for code in code_units:
        signed_hash = ((hash_val & 0xFFFFFFFF) ^ 0x80000000) - 0x80000000
        shifted = (signed_hash << 5) & 0xFFFFFFFF
        shifted_signed = ((shifted ^ 0x80000000) - 0x80000000)
        hash_val = shifted_signed + hash_val + code

    uint32_val = int(hash_val) % (2**32)

    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if uint32_val == 0:
        return "0"

    res = []
    n = uint32_val
    while n > 0:
        res.append(chars[n % 36])
        n //= 36
    return "".join(reversed(res))


def compute_composite_hash(snapshot: Union[DOMSnapshot, Dict[str, Any]]) -> str:
    """
    Constructs the 18-token composite string and computes the DJB2 base-36 hash.
    Matches exact property ordering from ag2r/server.js:
      0: html
      1: leftSidebarHtml
      2: sidebarSignature
      3: isSidebarOpen ("1" or "0")
      4: dropdownHtml
      5: dialogHtml
      6: settingsHtml
      7: askQuestionHtml
      8: permissionHtml
      9: runningTasksHtml
      10: scheduledTasksHtml
      11: scheduledTasksDialogHtml
      12: conversationHistoryHtml
      13: subagentInfoHtml
      14: btwHtml
      15: modelName
      16: environmentName
      17: branchName
    """
    def _s(val: Any) -> str:
        return val if isinstance(val, str) else ""

    if isinstance(snapshot, dict):
        html = _s(snapshot.get("html"))
        left_sidebar = _s(snapshot.get("leftSidebarHtml"))
        sidebar_sig = _s(snapshot.get("sidebarSignature"))
        is_sidebar_open = "1" if snapshot.get("isSidebarOpen") else "0"
        dropdown = _s(snapshot.get("dropdownHtml"))
        dialog = _s(snapshot.get("dialogHtml"))
        settings = _s(snapshot.get("settingsHtml"))
        ask_question = _s(snapshot.get("askQuestionHtml"))
        permission = _s(snapshot.get("permissionHtml"))
        running_tasks = _s(snapshot.get("runningTasksHtml"))
        scheduled_tasks = _s(snapshot.get("scheduledTasksHtml"))
        scheduled_dialog = _s(snapshot.get("scheduledTasksDialogHtml"))
        conversation_history = _s(snapshot.get("conversationHistoryHtml"))
        subagent_info = _s(snapshot.get("subagentInfoHtml"))
        btw = _s(snapshot.get("btwHtml"))
        model_name = _s(snapshot.get("modelName"))
        env_name = _s(snapshot.get("environmentName"))
        branch_name = _s(snapshot.get("branchName"))
    else:
        html = _s(snapshot.html)
        left_sidebar = _s(snapshot.leftSidebarHtml)
        sidebar_sig = _s(snapshot.sidebarSignature)
        is_sidebar_open = "1" if snapshot.isSidebarOpen else "0"
        dropdown = _s(snapshot.dropdownHtml)
        dialog = _s(snapshot.dialogHtml)
        settings = _s(snapshot.settingsHtml)
        ask_question = _s(snapshot.askQuestionHtml)
        permission = _s(snapshot.permissionHtml)
        running_tasks = _s(snapshot.runningTasksHtml)
        scheduled_tasks = _s(snapshot.scheduledTasksHtml)
        scheduled_dialog = _s(snapshot.scheduledTasksDialogHtml)
        conversation_history = _s(snapshot.conversationHistoryHtml)
        subagent_info = _s(snapshot.subagentInfoHtml)
        btw = _s(snapshot.btwHtml)
        model_name = _s(snapshot.modelName)
        env_name = _s(snapshot.environmentName)
        branch_name = _s(snapshot.branchName)

    composite_str = (
        html
        + left_sidebar
        + sidebar_sig
        + is_sidebar_open
        + dropdown
        + dialog
        + settings
        + ask_question
        + permission
        + running_tasks
        + scheduled_tasks
        + scheduled_dialog
        + conversation_history
        + subagent_info
        + btw
        + model_name
        + env_name
        + branch_name
    )
    return compute_djb2_hash(composite_str)


# ============================================================================
# 3. Dynamic Port Discovery
# ============================================================================

def get_devtools_active_port_path(app_data_dir: Optional[str] = None) -> Path:
    """Returns platform-specific path to DevToolsActivePort."""
    if app_data_dir:
        return Path(app_data_dir) / "Antigravity" / "DevToolsActivePort"

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Antigravity" / "DevToolsActivePort"
        return Path.home() / "AppData" / "Roaming" / "Antigravity" / "DevToolsActivePort"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Antigravity" / "DevToolsActivePort"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        return base / "Antigravity" / "DevToolsActivePort"


def read_devtools_port(app_data_dir: Optional[str] = None) -> Optional[int]:
    """Reads port from DevToolsActivePort if file exists and is valid."""
    dtp_path = get_devtools_active_port_path(app_data_dir)
    try:
        if dtp_path.is_file():
            content = dtp_path.read_text(encoding="utf-8").strip()
            lines = content.splitlines()
            if lines:
                port = int(lines[0].strip())
                if 0 < port < 65536:
                    return port
    except Exception as e:
        logger.debug(f"[PortDiscovery] Error reading DevToolsActivePort: {e}")
    return None


async def try_port_for_target(
    host: str, port: int, session: aiohttp.ClientSession, timeout: float = 0.5
) -> Optional[Tuple[int, CDPTarget]]:
    """Probes http://{host}:{port}/json/list and selects highest priority target."""
    url = f"http://{host}:{port}/json/list"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if not data or not isinstance(data, list):
                    return None

                targets = [
                    CDPTarget(
                        id=t.get("id", ""),
                        title=t.get("title", ""),
                        type=t.get("type", ""),
                        url=t.get("url", ""),
                        webSocketDebuggerUrl=t.get("webSocketDebuggerUrl", ""),
                        devtoolsFrontendUrl=t.get("devtoolsFrontendUrl"),
                        description=t.get("description", ""),
                    )
                    for t in data
                    if isinstance(t, dict) and t.get("webSocketDebuggerUrl")
                ]
                if not targets:
                    return None

                # Priority 1: Workbench target
                for t in targets:
                    if "workbench.html" in (t.url or "") or "workbench" in (t.title or "").lower():
                        return port, t

                # Priority 2: Jetski / Launchpad target
                for t in targets:
                    if "jetski" in (t.url or "") or t.title == "Launchpad":
                        return port, t

                # Priority 3: Any page target (Antigravity 2.x main window)
                for t in targets:
                    if t.type == "page":
                        return port, t

                # Fallback: return first target
                return port, targets[0]
    except Exception:
        pass
    return None


def _normalize_action_result(res: Any) -> Dict[str, Any]:
    """Ensures action response dictionaries have a boolean 'ok' field."""
    if isinstance(res, dict):
        if "ok" not in res:
            res["ok"] = bool(
                res.get("success")
                or res.get("status") == "ok"
                or res.get("clicked")
                or res.get("sent")
                or res.get("stopped")
                or res.get("uploaded")
            )
        return res
    if res is True or res == "ok":
        return {"ok": True}
    if res is None:
        return {"ok": False, "reason": "null_result"}
    return {"ok": bool(res), "value": res}


async def discover_target(
    host: str = "127.0.0.1",
    port: Optional[int] = None,
    app_data_dir: Optional[str] = None,
    timeout: float = 0.5,
) -> Optional[Tuple[int, CDPTarget]]:
    """
    Probes candidate ports and returns (port, CDPTarget).
    If port is explicitly provided, ONLY probes that port.
    Otherwise checks DevToolsActivePort, then fallback candidate range 9000..9003.
    """
    if port is not None:
        candidate_ports = [port]
    else:
        candidate_ports = []
        dtp_port = read_devtools_port(app_data_dir)
        if dtp_port:
            candidate_ports.append(dtp_port)

        base_port = 9000
        for p in [base_port, base_port + 1, base_port + 2, base_port + 3]:
            if p not in candidate_ports:
                candidate_ports.append(p)

    async with aiohttp.ClientSession() as session:
        for p in candidate_ports:
            result = await try_port_for_target(host, p, session, timeout=timeout)
            if result:
                return result
    return None


# ============================================================================
# 4. Embedded 31 CDP Automation Scripts & Builders
# ============================================================================

TAG_INTERACTIVES_FN = """
  // -- Helper: tag interactive elements for click proxying --
  function tagInteractives(root, prefix, skipVisibilityCheck, includeCursorPointer, maxTextLength) {
    let idx = 0;
    const tagged = [];
    // Semantic interactive elements — always tag, no text-length filter
    root.querySelectorAll('button, a, [role="button"], [role="option"], [role="menuitem"], [role="menuitemradio"]').forEach(el => {
      if (skipVisibilityCheck || el.offsetParent !== null) {
        const text = (el.textContent || '').trim();
        el.setAttribute('data-ag-click-id', prefix + ':' + idx);
        el.setAttribute('data-ag-click-label', text.substring(0, 50));
        idx++;
        tagged.push(el);
      }
    });
    // cursor-pointer elements are ambiguous — could be content containers.
    if (includeCursorPointer) {
      root.querySelectorAll('[class*="cursor-pointer"]').forEach(el => {
        if ((skipVisibilityCheck || el.offsetParent !== null) && !el.hasAttribute('data-ag-click-id')) {
          const text = (el.textContent || '').trim();
          const hasHandler = typeof el.onclick === 'function';
          if (maxTextLength && text.length > maxTextLength && !hasHandler) return;
          el.setAttribute('data-ag-click-id', prefix + ':' + idx);
          el.setAttribute('data-ag-click-label', text.substring(0, 50));
          idx++;
          tagged.push(el);
        }
      });
    }
    return tagged;
  }

  function untagAll(tagged) {
    tagged.forEach(el => {
      el.removeAttribute('data-ag-click-id');
      el.removeAttribute('data-ag-click-label');
    });
  }
"""

CAPTURE_SCRIPT = f"""
(async () => {{
  {TAG_INTERACTIVES_FN}

  // -- 1. Find the chat container --
  let container =
    document.querySelector('.scrollbar-hide[class*="overflow-y-auto"]') ||
    document.querySelector('[data-testid="conversation-view"]') ||
    document.getElementById('conversation') ||
    document.getElementById('chat') ||
    document.getElementById('cascade');

  let isNewSessionPage = false;
  if (!container || container.clientHeight === 0) {{
    const inputBox = document.getElementById('antigravity.agentSidePanelInputBox');
    if (inputBox) {{
      let newSessionRoot = inputBox;
      for (let i = 0; i < 10; i++) {{
        if (!newSessionRoot.parentElement) break;
        newSessionRoot = newSessionRoot.parentElement;
        const cls = newSessionRoot.className?.toString() || '';
        if (cls.includes('animate-fade-in')) break;
      }}
      container = newSessionRoot;
      isNewSessionPage = true;
    }}
  }}

  if (!container) return null;

  // -- 2. Detect if agent is generating --
  const stopBtn =
    document.querySelector('[data-tooltip-id="input-send-button-cancel-tooltip"]') ||
    document.querySelector('button svg.lucide-square')?.closest('button');
  const agentRunning = !!(stopBtn && stopBtn.offsetParent !== null);

  // -- 3. Scroll info --
  const scrollInfo = {{
    scrollTop: container.scrollTop,
    scrollHeight: container.scrollHeight,
    clientHeight: container.clientHeight,
  }};

  // -- 4. Mark positioned elements + tag chat interactives --
  const marked = [];
  container.querySelectorAll('*').forEach(el => {{
    try {{
      const cs = getComputedStyle(el);
      if (cs.position === 'fixed' || cs.position === 'absolute') {{
        el.setAttribute('data-ag-remove', '1');
        marked.push(el);
      }}
      if (cs.position === 'sticky') {{
        el.setAttribute('data-ag-sticky', '1');
        marked.push(el);
      }}
    }} catch {{}}
  }});
  const chatTagged = tagInteractives(container, 'chat', false, true, 80);

  // -- 5. Clone chat container --
  const clone = container.cloneNode(true);

  // -- 6. Unmark originals --
  marked.forEach(el => {{
    el.removeAttribute('data-ag-remove');
    el.removeAttribute('data-ag-sticky');
  }});
  untagAll(chatTagged);

  // -- 7. Clean clone: remove editor/input --
  if (!isNewSessionPage) {{
    ['[contenteditable="true"]', '[data-lexical-editor]', '[role="textbox"]', 'form'].forEach(sel => {{
      clone.querySelectorAll(sel).forEach(el => {{
        let target = el;
        while (target.parentElement && target.parentElement !== clone) {{
          const btn = target.parentElement.querySelector('button, [role="button"]');
          if (/^(Allow|Deny|Review|Run|Confirm|Accept|Reject)/i.test(btn?.textContent?.trim() || '')) break;
          target = target.parentElement;
        }}
        if (target.parentElement === clone) target.remove();
        else el.remove();
      }});
    }});
  }}

  // -- 8. Remove fixed/absolute overlays (protect action bars) --
  clone.querySelectorAll('[data-ag-remove]').forEach(el => {{
    let isActionBar = false;
    el.querySelectorAll('button, [role="button"]').forEach(b => {{
      const label = b.textContent?.trim() || b.getAttribute('aria-label') || '';
      if (/^(Allow|Deny|Review|Run|Confirm|Undo)/i.test(label)) isActionBar = true;
    }});
    if (!isActionBar) el.remove();
    else el.removeAttribute('data-ag-remove');
  }});

  // -- 9. Force sticky backgrounds --
  clone.querySelectorAll('[data-ag-sticky]').forEach(el => {{
    el.style.backgroundColor = '#101010';
  }});

  // -- 10. Fix inline div-inside-span/p --
  clone.querySelectorAll('span > div, p > div').forEach(div => {{
    const span = document.createElement('span');
    span.innerHTML = div.innerHTML;
    span.style.display = 'inline-flex';
    span.style.alignItems = 'center';
    for (const attr of div.attributes) {{
      if (attr.name !== 'style') span.setAttribute(attr.name, attr.value);
    }}
    div.replaceWith(span);
  }});

  // -- 11. Force paragraph display block --
  clone.querySelectorAll('p').forEach(p => {{ p.style.display = 'block'; }});

  // -- 12. Get chat HTML + strip [object Object] --
  let html = clone.innerHTML;
  html = html.replace(/class="([^"]*)"/g, (match, classes) => {{
    if (!classes.includes('[object Object]')) return match;
    const cleaned = classes.replace(/\\[object Object\\]/g, '').replace(/\\s+/g, ' ').trim();
    return 'class="' + cleaned + '"';
  }});

  // -- 13. Collect CSS --
  let css = '';
  for (const sheet of document.styleSheets) {{
    try {{
      for (const rule of sheet.cssRules) {{ css += rule.cssText + '\\n'; }}
    }} catch {{}}
  }}

  const rootStyle = getComputedStyle(document.documentElement);
  const bodyStyle = document.body ? getComputedStyle(document.body) : null;
  const themeRules = [];
  const seen = new Set();
  for (const source of [rootStyle, bodyStyle]) {{
    if (!source) continue;
    for (const name of source) {{
      if (name.startsWith('--') && !seen.has(name)) {{
        const val = source.getPropertyValue(name).trim();
        if (val) {{
          themeRules.push(name + ':' + val);
          seen.add(name);
        }}
      }}
    }}
  }}
  if (themeRules.length > 0) {{
    css = ':root{{' + themeRules.join(';') + '}}\\n' + css;
  }}

  // -- 14. Capture LEFT sidebar --
  let leftSidebarHtml = null;
  let sidebarAttentionItems = [];
  try {{
    const leftRoot = document.querySelector('.bg-sidebar');
    if (leftRoot && leftRoot.offsetParent !== null) {{
      const leftTagged = tagInteractives(leftRoot, 'left', true, true);
      const leftClone = leftRoot.cloneNode(true);
      untagAll(leftTagged);
      leftSidebarHtml = leftClone.outerHTML;

      const seenIds = new Set();
      leftRoot.querySelectorAll('.animate-unread-ping').forEach(ping => {{
        let el = ping;
        for (let i = 0; i < 10 && el; i++) {{
          const pill = el.querySelector('[data-testid^="convo-pill-"]');
          if (pill) {{
            const id = pill.getAttribute('data-testid').replace('convo-pill-', '');
            if (id && !seenIds.has(id)) {{
              seenIds.add(id);
              let statusContainer = ping;
              for (let j = 0; j < 5 && statusContainer; j++) {{
                if ((statusContainer.getAttribute('class') || '').includes('group-hover:invisible')) break;
                statusContainer = statusContainer.parentElement;
              }}
              const svgEl = statusContainer ? statusContainer.querySelector('svg') : null;
              let type = 'completed';
              if (svgEl) {{
                const pathD = (svgEl.querySelector('path')?.getAttribute('d') || '');
                const QUESTION_ICON_PATH = 'M477.92-295.77q17.15,0 28.96-11.81t11.81-28.96T506.88-365.5t-28.96-11.81T448.96-365.5t-11.81,28.96t11.81,28.96t28.96,11.81ZM449.62-439h56.31q0.38-15.08 2.08-25.92T514.69-486t12.69-19.73t20.54-22.35q31.92-31.92 45.65-54.27t13.73-50.81q0-49.92-34.08-80.5t-87.77-30.58q-48.85,0-83.5,24.88t-49.27,64.81l51.38,20.61q8.54-25.46 28.38-41.58t49.77-16.12q32.39,0 50.58,17.58T551-631.31q0,18.54-11,36.38t-33.92,38.54q-15.85,14-26.35,27.12t-17.5,26.96t-9.81,28.81T449.62-439ZM480-68.46L368.46-180H212.31Q182-180 161-201t-21-51.31V-787.69Q140-818 161-839t51.31-21H747.69Q778-860 799-839t21,51.31v535.38Q820-222 799-201t-51.31,21H591.54L480-68.46ZM212.31-240H392.77L480-152.77L567.23-240H747.69q5.39,0 8.85-3.46t3.46-8.85V-787.69q0-5.39-3.46-8.85T747.69-800H212.31q-5.39,0-8.85,3.46T200-787.69v535.38q0,5.39 3.46,8.85t8.85,3.46ZM480-520Z';
                type = (pathD === QUESTION_ICON_PATH) ? 'question' : 'command';
              }}
              let name = '';
              let nameEl = ping;
              for (let k = 0; k < 10 && nameEl; k++) {{
                if (nameEl.getAttribute('role') === 'button') {{
                  name = (nameEl.textContent || '').trim();
                  break;
                }}
                nameEl = nameEl.parentElement;
              }}
              sidebarAttentionItems.push({{ id, type, name }});
            }}
            break;
          }}
          el = el.parentElement;
        }}
      }});
    }}
  }} catch (e) {{}}

  // -- 15. Sidebar signature --
  let sidebarSignature = null;
  try {{
    const tabBtns = document.querySelectorAll('[data-tab-id]');
    if (tabBtns.length > 0) {{
      const tabs = [];
      for (const b of tabBtns) {{
        const id = b.getAttribute('data-tab-id');
        const active = (b.className || '').includes('bg-secondary') ? '*' : '';
        tabs.push(id + active);
      }}
      sidebarSignature = tabs.join(',');
    }}
  }} catch (e) {{}}

  const firstTab = document.querySelector('[data-tab-id]');
  let isSidebarOpen = false;
  if (firstTab) {{
    let el = firstTab;
    let foundCollapse = false;
    for (let i = 0; i < 20 && el; i++) {{
      el = el.parentElement;
      if (!el) break;
      const s = getComputedStyle(el);
      if (s.overflow === 'hidden' || s.overflowX === 'hidden') {{
        const r = el.getBoundingClientRect();
        if (r.height > 100) {{
          const inlineWidth = el.style.width;
          isSidebarOpen = inlineWidth !== '0%' && inlineWidth !== '0px' && inlineWidth !== '';
          foundCollapse = true;
          break;
        }}
      }}
    }}
    if (!foundCollapse) {{
      isSidebarOpen = true;
    }}
  }}

  // -- 8. Capture portal elements --
  let dropdownHtml = null;
  let dialogHtml = null;
  try {{
    for (const child of document.body.children) {{
      if (child.tagName === 'SCRIPT' || child.tagName === 'STYLE') continue;
      const text = child.textContent.trim();
      if (!text) continue;

      const targets = child.id
        ? Array.from(child.querySelectorAll('[role="dialog"], [role="listbox"]'))
        : [child];

      for (const target of targets) {{
        if (!dropdownHtml && target.getAttribute('role') === 'listbox') {{
          const tagged = tagInteractives(target, 'dropdown', true, false);
          const clone = target.cloneNode(true);
          untagAll(tagged);
          dropdownHtml = clone.outerHTML;
        }}

        const cls = (target.className || '').toString();
        if (!dialogHtml && cls.includes('fixed') && cls.includes('inset-0')) {{
          const tagged = tagInteractives(target, 'dialog', true, false);
          const clone = target.cloneNode(true);
          untagAll(tagged);
          clone.querySelectorAll('style').forEach(s => s.remove());
          dialogHtml = clone.outerHTML;
        }}

        if (!dialogHtml && target.getAttribute('role') === 'dialog') {{
          const tagged = tagInteractives(target, 'dialog', true, false);
          const clone = target.cloneNode(true);
          untagAll(tagged);
          clone.querySelectorAll('style').forEach(s => s.remove());
          dialogHtml = clone.outerHTML;
        }}
      }}
    }}
  }} catch (e) {{}}

  // -- 8b. Capture Settings modal --
  let settingsHtml = null;
  try {{
    const settingsOverlay = document.querySelector('#root .fixed.inset-0[class*="z-[5000]"]');
    if (settingsOverlay && settingsOverlay.getBoundingClientRect().width > 0) {{
      const settingsCard = settingsOverlay.querySelector('[class*="max-w-5xl"]') ||
                           settingsOverlay.querySelector('[class*="rounded-2xl"]');
      if (settingsCard) {{
        const tagged = tagInteractives(settingsCard, 'settings', true, false);
        const clone = settingsCard.cloneNode(true);
        untagAll(tagged);
        clone.querySelectorAll('style').forEach(s => s.remove());
        settingsHtml = clone.outerHTML;
      }}
    }}
  }} catch (e) {{}}

  // -- 9. Detect active tab URI --
  let activeArtifactUri = null;
  let activeFileUri = null;
  try {{
    const activeTab = document.querySelector('[data-tab-id].bg-secondary');
    if (activeTab) {{
      const tabId = activeTab.getAttribute('data-tab-id');
      if (tabId !== 'overview' && tabId !== 'review') {{
        if (tabId.startsWith('artifact__')) {{
          activeArtifactUri = tabId.replace('artifact__', '');
        }} else {{
          activeFileUri = tabId;
        }}
      }}
    }}
  }} catch (e) {{}}

  // -- 10. Detect ask_question modal --
  let askQuestionHtml = null;
  let askQuestionContainer = null;
  try {{
    const allBtns = Array.from(document.querySelectorAll('button'));
    const skipBtn = allBtns.find(b => b.textContent.trim() === 'Skip');
    const submitBtn = allBtns.find(b => /^Submit/.test(b.textContent.trim()));
    if (skipBtn && submitBtn) {{
      let container = skipBtn;
      for (let i = 0; i < 20 && container.parentElement; i++) {{
        container = container.parentElement;
        if (container.contains(submitBtn)) break;
      }}
      let cardRoot = container;
      for (let i = 0; i < 5 && cardRoot.parentElement; i++) {{
        const cls = (cardRoot.className || '').toString();
        if (cls.includes('bg-card-border')) break;
        cardRoot = cardRoot.parentElement;
      }}
      askQuestionContainer = cardRoot;
      let askIdx = 0;
      const askTagged = [];
      cardRoot.querySelectorAll('[role="radiogroup"] label, [role="group"] label').forEach(el => {{
        el.setAttribute('data-ag-click-id', 'ask:' + askIdx);
        el.setAttribute('data-ag-click-label', (el.textContent || '').trim().substring(0, 50));
        askIdx++;
        askTagged.push(el);
      }});
      cardRoot.querySelectorAll('button').forEach(el => {{
        el.setAttribute('data-ag-click-id', 'ask:' + askIdx);
        el.setAttribute('data-ag-click-label', (el.textContent || '').trim().substring(0, 50));
        askIdx++;
        askTagged.push(el);
      }});
      const askClone = cardRoot.cloneNode(true);
      askTagged.forEach(el => {{
        el.removeAttribute('data-ag-click-id');
        el.removeAttribute('data-ag-click-label');
      }});
      askClone.querySelectorAll('style').forEach(s => s.remove());
      askQuestionHtml = askClone.outerHTML;
    }}
  }} catch (e) {{}}

  // -- 11. Detect permission banner --
  let permissionHtml = null;
  try {{
    const radioGroup = document.querySelector('[role="radiogroup"]');
    if (radioGroup && !(askQuestionContainer && askQuestionContainer.contains(radioGroup))) {{
      let banner = radioGroup;
      for (let i = 0; i < 10; i++) {{
        if (!banner.parentElement || banner.parentElement === document.body) break;
        banner = banner.parentElement;
        if (/allow|permission/i.test(banner.textContent) && banner.querySelectorAll('button').length >= 1) break;
      }}
      let permIdx = 0;
      const permTagged = [];
      banner.querySelectorAll('[role="radiogroup"] label').forEach(el => {{
        el.setAttribute('data-ag-click-id', 'perm:' + permIdx);
        el.setAttribute('data-ag-click-label', (el.textContent || '').trim().substring(0, 50));
        permIdx++;
        permTagged.push(el);
      }});
      banner.querySelectorAll('button').forEach(el => {{
        el.setAttribute('data-ag-click-id', 'perm:' + permIdx);
        el.setAttribute('data-ag-click-label', (el.textContent || '').trim().substring(0, 50));
        permIdx++;
        permTagged.push(el);
      }});
      const permClone = banner.cloneNode(true);
      permTagged.forEach(el => {{
        el.removeAttribute('data-ag-click-id');
        el.removeAttribute('data-ag-click-label');
      }});
      permissionHtml = permClone.outerHTML;
    }}
  }} catch (e) {{}}

  // -- 12. Environment and branch names --
  let environmentName = null;
  let branchName = null;
  try {{
    const envBtn = document.querySelector('[aria-label="Select Environment"]');
    if (envBtn) {{
      const span = envBtn.querySelector('span');
      environmentName = span ? span.textContent.trim() : (envBtn.textContent || '').trim();
    }}
    const branchBtn = document.querySelector('[aria-label="Select Default Branch"]');
    if (branchBtn) {{
      const span = branchBtn.querySelector('span');
      branchName = span ? span.textContent.trim() : (branchBtn.textContent || '').trim();
    }}
  }} catch (e) {{}}

  // -- 13. Model name --
  let modelName = null;
  try {{
    const modelBtn = document.querySelector('[aria-label*="Select model"]');
    if (modelBtn) {{
      const span = modelBtn.querySelector('span');
      modelName = span ? span.textContent.trim() : (modelBtn.textContent || '').trim();
    }}
  }} catch (e) {{}}

  // -- 14. Subagent view detection --
  let isInputBoxHidden = false;
  let isSubagentView = false;
  let parentConversationName = '';
  try {{
    const inputBox = document.getElementById('antigravity.agentSidePanelInputBox');
    if (!inputBox) {{
      isInputBoxHidden = !isNewSessionPage && !!container;
    }} else {{
      isInputBoxHidden = inputBox.offsetParent === null || inputBox.getBoundingClientRect().height === 0;
    }}

    if (isInputBoxHidden) {{
      const candidates = document.querySelectorAll('div, span, p');
      for (const el of candidates) {{
        if (container && container.contains(el)) continue;
        const txt = (el.textContent || '').trim();
        if (txt.length > 5 && txt.length < 100 &&
            (txt.toLowerCase().includes('cannot send') || txt.toLowerCase().includes('cannot prompt'))) {{
          isSubagentView = true;
          break;
        }}
      }}
    }}

    if (isSubagentView && container) {{
      const cvParent = container.parentElement;
      if (cvParent) {{
        for (const child of cvParent.children) {{
          if (child === container) break;
          const rect = child.getBoundingClientRect();
          if (rect.height > 8 && rect.height < 80) {{
            const text = child.textContent.trim();
            if (text.length > 0 && text.length < 300) {{
              const parts = text.split(/[/›>]/).map(s => s.trim()).filter(Boolean);
              if (parts.length >= 2) {{
                parentConversationName = parts[parts.length - 2];
              }} else {{
                parentConversationName = parts[0] || text;
              }}
              break;
            }}
          }}
        }}
      }}
    }}
  }} catch (e) {{}}

  let subagentInfoHtml = null;
  if (isSubagentView) {{
    try {{
      const allDivs = document.querySelectorAll('div');
      let infoPanel = null;
      for (const div of allDivs) {{
        const txt = div.textContent.trim().toLowerCase();
        if ((txt.includes('cannot') && txt.includes('prompt')) || 
            (txt.includes('open') && txt.includes('overview'))) {{
          if (!infoPanel || (infoPanel.contains(div) && div !== infoPanel)) {{
            infoPanel = div;
          }}
        }}
      }}
      if (infoPanel) {{
        let subIdx = 0;
        const subTagged = [];
        infoPanel.querySelectorAll('button, a, [role="button"]').forEach(el => {{
          el.setAttribute('data-ag-click-id', 'subinfo:' + subIdx);
          el.setAttribute('data-ag-click-label', (el.textContent || '').trim().substring(0, 80));
          subIdx++;
          subTagged.push(el);
        }});
        const subClone = infoPanel.cloneNode(true);
        subTagged.forEach(el => {{
          el.removeAttribute('data-ag-click-id');
          el.removeAttribute('data-ag-click-label');
        }});
        subagentInfoHtml = subClone.outerHTML;
      }}
    }} catch (e) {{}}
  }}

  // -- 12/btw. Detect and capture /btw side question box --
  let btwHtml = null;
  try {{
    const span = Array.from(document.querySelectorAll('span')).find(s => s.textContent.trim().startsWith('Side Question'));
    if (span) {{
      let container = span;
      for (let i = 0; i < 5 && container; i++) {{
        const cls = (container.className || '').toString();
        if (cls.includes('border-border') && cls.includes('rounded-md')) {{
          break;
        }}
        container = container.parentElement;
      }}
      if (container) {{
        let btwIdx = 0;
        const btwTagged = [];
        container.querySelectorAll('button, a, [role="button"]').forEach(el => {{
          if (el.closest('#antigravity\\\\.agentSidePanelInputBox') || el.closest('[class*="bg-card-border"]')) return;
          el.setAttribute('data-ag-click-id', 'btw:' + btwIdx);
          el.setAttribute('data-ag-click-label', (el.textContent || '').trim().substring(0, 50));
          btwIdx++;
          btwTagged.push(el);
        }});
        const btwClone = container.cloneNode(true);
        const inputWrapper = btwClone.querySelector('#antigravity\\\\.agentSidePanelInputBox') || btwClone.querySelector('[class*="bg-card-border"]');
        if (inputWrapper) {{
          inputWrapper.remove();
        }}
        btwTagged.forEach(el => {{
          el.removeAttribute('data-ag-click-id');
          el.removeAttribute('data-ag-click-label');
        }});
        btwClone.querySelectorAll('style').forEach(s => s.remove());
        btwHtml = btwClone.outerHTML;
      }}
    }}
  }} catch (e) {{}}

  return {{ html, css, agentRunning, scrollInfo, leftSidebarHtml, sidebarAttentionItems, sidebarSignature, isSidebarOpen, isNewSessionPage, isInputBoxHidden, isSubagentView, parentConversationName, subagentInfoHtml, dropdownHtml, dialogHtml, settingsHtml, activeArtifactUri, activeFileUri, askQuestionHtml, permissionHtml, environmentName, branchName, modelName, btwHtml }};
}})()
"""

RIGHT_SIDEBAR_SCRIPT = f"""
(() => {{
  {TAG_INTERACTIVES_FN}

  let sidebarRoot = null;
  const tabBtn = document.querySelector('[data-tab-id="overview"], [data-tab-id="review"]');
  if (tabBtn) {{
    let el = tabBtn;
    for (let i = 0; i < 10 && el; i++) {{
      el = el.parentElement;
      const cls = el?.className?.toString?.() || '';
      if (cls.includes('flex') && cls.includes('flex-col') && el.children.length >= 2) {{
        const rect = el.getBoundingClientRect();
        if (rect.width > 100 && rect.height > 200) {{
          sidebarRoot = el;
          break;
        }}
      }}
    }}
  }}

  if (!sidebarRoot) {{
    const closeBtn = document.querySelector('[data-testid="toggle-aux-sidebar"]');
    if (closeBtn) {{
      let el = closeBtn;
      for (let i = 0; i < 10 && el; i++) {{
        el = el.parentElement;
        const cls = el?.className?.toString?.() || '';
        if (cls.includes('flex') && cls.includes('flex-col') && el.children.length >= 2) {{
          sidebarRoot = el;
          break;
        }}
      }}
    }}
  }}

  if (!sidebarRoot) return null;

  const rightTagged = tagInteractives(sidebarRoot, 'right', true, true, 0);
  const rightClone = sidebarRoot.cloneNode(true);
  untagAll(rightTagged);
  return rightClone.outerHTML;
}})()
"""

RUNNING_TASKS_SCRIPT = """
(() => {
  const inputBox = document.getElementById('antigravity.agentSidePanelInputBox');
  if (!inputBox) return null;
  const taskSection = inputBox.querySelector('.rounded-t-2xl');
  if (!taskSection || taskSection.getBoundingClientRect().height <= 0) return null;
  const allBtns = taskSection.querySelectorAll('button');
  if (allBtns.length < 2) return null;
  let taskIdx = 0;
  const taskTagged = [];
  taskSection.querySelectorAll('button').forEach(btn => {
    btn.setAttribute('data-ag-click-id', 'task:' + taskIdx);
    btn.setAttribute('data-ag-click-label', (btn.textContent || '').trim().substring(0, 80));
    taskIdx++;
    taskTagged.push(btn);
  });
  const taskClone = taskSection.cloneNode(true);
  taskTagged.forEach(el => {
    el.removeAttribute('data-ag-click-id');
    el.removeAttribute('data-ag-click-label');
  });
  return taskClone.outerHTML;
})()
"""

SCHEDULED_TASKS_SCRIPT = """
(() => {
  let anchor = document.querySelector('[aria-label="Add scheduled task"]');
  if (!anchor) {
    anchor = document.querySelector('[aria-label="Edit task title"]');
  }
  if (!anchor) {
    anchor = document.querySelector('textarea[placeholder*="Prompt to execute"]');
  }
  if (!anchor) return null;

  let container = anchor;
  for (let i = 0; i < 15; i++) {
    if (!container.parentElement) break;
    const p = container.parentElement;
    if (p.getBoundingClientRect().x < 10) break;
    container = p;
  }

  const inner = container.querySelector('.flex-1.flex.flex-col.min-w-0.h-full') || container;
  let idx = 0;
  const tagged = [];
  inner.querySelectorAll('button, a, [role="button"], input, select, textarea').forEach(el => {
    el.setAttribute('data-ag-click-id', 'sched:' + idx);
    el.setAttribute('data-ag-click-label', (el.textContent || el.getAttribute('placeholder') || '').trim().substring(0, 50));
    idx++;
    tagged.push(el);
  });
  inner.querySelectorAll('[class*="cursor-pointer"]').forEach(el => {
    if (el.hasAttribute('data-ag-click-id')) return;
    const text = (el.textContent || '').trim();
    if (text.length > 200) return;
    el.setAttribute('data-ag-click-id', 'sched:' + idx);
    el.setAttribute('data-ag-click-label', text.substring(0, 50));
    idx++;
    tagged.push(el);
  });
  const valuedEls = [];
  inner.querySelectorAll('input, textarea').forEach(el => {
    valuedEls.push(el);
    el.setAttribute('data-ag-value', el.value || '');
  });
  const pageClone = inner.cloneNode(true);
  tagged.forEach(el => {
    el.removeAttribute('data-ag-click-id');
    el.removeAttribute('data-ag-click-label');
  });
  valuedEls.forEach(el => el.removeAttribute('data-ag-value'));
  pageClone.querySelectorAll('style').forEach(s => s.remove());
  return pageClone.outerHTML;
})()
"""

SCHEDULED_TASKS_DIALOG_SCRIPT = """
(() => {
  const overlay = document.querySelector('.fixed.inset-0[class*="z-[2550]"]');
  if (!overlay || overlay.getBoundingClientRect().width <= 0) return null;
  const text = overlay.textContent || '';
  if (!text.includes('Scheduled Task') && !text.includes('task name') && !/delete/i.test(text)) return null;

  let idx = 0;
  const tagged = [];
  overlay.querySelectorAll('button, a, [role="button"], input, select, textarea, [role="combobox"], [role="switch"]').forEach(el => {
    el.setAttribute('data-ag-click-id', 'scheddlg:' + idx);
    el.setAttribute('data-ag-click-label', (el.textContent || el.getAttribute('placeholder') || '').trim().substring(0, 50));
    idx++;
    tagged.push(el);
  });
  overlay.querySelectorAll('div.cursor-pointer[aria-expanded]').forEach(el => {
    if (el.getAttribute('data-ag-click-id')) return;
    el.setAttribute('data-ag-click-id', 'scheddlg:' + idx);
    el.setAttribute('data-ag-click-label', (el.textContent || '').trim().substring(0, 50));
    idx++;
    tagged.push(el);
  });
  const valuedEls = [];
  overlay.querySelectorAll('input, textarea').forEach(el => {
    const liveVal = el.value || '';
    el.setAttribute('data-ag-value', liveVal);
    valuedEls.push(el);
  });
  const card = overlay.querySelector('[class*="shadow-xl"]') || overlay.firstElementChild || overlay;
  const clone = card.cloneNode(true);
  tagged.forEach(el => {
    el.removeAttribute('data-ag-click-id');
    el.removeAttribute('data-ag-click-label');
  });
  valuedEls.forEach(el => el.removeAttribute('data-ag-value'));
  clone.querySelectorAll('style').forEach(s => s.remove());
  return clone.outerHTML;
})()
"""

CONVERSATION_HISTORY_SCRIPT = """
(() => {
  const container = Array.from(
    document.querySelectorAll('.h-full.w-full.overflow-y-auto')
  ).find(el => {
    const r = el.getBoundingClientRect();
    return r.x > 200 && r.height > 300;
  });

  if (!container) return null;
  const heading = container.querySelector('.text-lg.font-medium');
  if (!heading || heading.textContent.trim() !== 'Conversation History') return null;

  const inner = container.querySelector('.w-full.max-w-2xl') || container;
  let idx = 0;
  const tagged = [];
  inner.querySelectorAll('button, a, [role="button"], input').forEach(el => {
    el.setAttribute('data-ag-click-id', 'history:' + idx);
    el.setAttribute('data-ag-click-label', (el.textContent || el.getAttribute('placeholder') || '').trim().substring(0, 50));
    idx++;
    tagged.push(el);
  });
  inner.querySelectorAll('[class*="cursor-pointer"]').forEach(el => {
    if (el.hasAttribute('data-ag-click-id')) return;
    const text = (el.textContent || '').trim();
    if (text.length > 200) return;
    el.setAttribute('data-ag-click-id', 'history:' + idx);
    el.setAttribute('data-ag-click-label', text.substring(0, 50));
    idx++;
    tagged.push(el);
  });
  const valuedEls = [];
  inner.querySelectorAll('input').forEach(el => {
    valuedEls.push(el);
    el.setAttribute('data-ag-value', el.value || '');
  });
  const clone = inner.cloneNode(true);
  tagged.forEach(el => {
    el.removeAttribute('data-ag-click-id');
    el.removeAttribute('data-ag-click-label');
  });
  valuedEls.forEach(el => el.removeAttribute('data-ag-value'));
  clone.querySelectorAll('style').forEach(s => s.remove());
  return clone.outerHTML;
})()
"""

STOP_SCRIPT = """
(async () => {
  const cancelBtn = document.querySelector('[data-tooltip-id="input-send-button-cancel-tooltip"]');
  if (cancelBtn && cancelBtn.offsetParent !== null) {
    cancelBtn.click();
    return { ok: true, method: 'cancel-tooltip' };
  }
  const squareIcon = document.querySelector('button svg.lucide-square');
  if (squareIcon) {
    const btn = squareIcon.closest('button');
    if (btn && btn.offsetParent !== null) {
      btn.click();
      return { ok: true, method: 'square-icon' };
    }
  }
  return { ok: false, reason: 'no_stop_button' };
})()
"""

DISCOVER_SCRIPT = """
(async () => {
  const results = {
    textMatches: [],
    asides: [],
    panels: [],
    tabs: [],
    rightEdgeElements: [],
    chatContainer: null,
    topLevel: [],
  };

  const textTargets = ['Overview', 'Review', 'Review Changes', 'No changes to review'];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const text = walker.currentNode.textContent.trim();
    for (const target of textTargets) {
      if (text === target || text.includes(target)) {
        const el = walker.currentNode.parentElement;
        if (el) {
          results.textMatches.push({
            text: target,
            tag: el.tagName,
            id: el.id || null,
            className: el.className?.toString?.()?.substring(0, 200) || null,
            role: el.getAttribute('role'),
            parentTag: el.parentElement?.tagName,
            parentId: el.parentElement?.id || null,
            parentClass: el.parentElement?.className?.toString?.()?.substring(0, 200) || null,
          });
        }
      }
    }
  }
  return results;
})()
"""

CHECK_EDITOR_IMAGE_SCRIPT = """
(() => {
  const editor = document.querySelector(
    '[data-lexical-editor="true"], [contenteditable="true"][role="textbox"], [contenteditable="true"]'
  );
  if (!editor || editor.offsetParent === null) return false;
  const hasImg = !!editor.querySelector('img');
  const hasDecorator = !!editor.querySelector('[data-lexical-decorator="true"]');
  const text = (editor.textContent || '').trim();
  const hasContent = text.length > 0 && !text.includes('Ask anything');
  return hasImg || hasDecorator || hasContent;
})()
"""

CLICK_SEND_BUTTON_SCRIPT = """
(() => {
  const selectors = [
    'button[data-testid="send-button"]',
    'button[aria-label*="send" i]',
    'button[aria-label*="submit" i]',
  ];
  let btn = null;
  for (const sel of selectors) {
    btn = document.querySelector(sel);
    if (btn && btn.offsetParent !== null) break;
    btn = null;
  }
  if (!btn) {
    const arrow = document.querySelector('svg.lucide-arrow-right, svg.lucide-arrow-up');
    if (arrow) btn = arrow.closest('button');
  }
  if (btn) {
    btn.click();
    return { ok: true, method: 'button' };
  }
  return { ok: false, reason: 'no_send_button' };
})()
"""

EXPAND_LEFT_SIDEBAR_SCRIPT = """
(async () => {
  const leftRoot = document.querySelector('.bg-sidebar');
  const isCollapsed = !leftRoot || leftRoot.offsetParent === null;
  if (!isCollapsed) return { ok: true, wasCollapsed: false };
  const toggleBtn = document.querySelector('[data-testid="sidebar-toggle"]');
  if (!toggleBtn) return { ok: false, error: 'Toggle button not found' };
  toggleBtn.click();
  return { ok: true, wasCollapsed: true };
})()
"""

DISMISS_SCHEDULED_TASKS_SCRIPT = """
(() => {
  const editBtn = document.querySelector('[aria-label="Edit task title"]');
  const promptTA = document.querySelector('textarea[placeholder*="Prompt to execute"]');
  if (editBtn || promptTA) {
    const links = document.querySelectorAll('a');
    for (const a of links) {
      if ((a.textContent || '').trim() === 'Scheduled') {
        a.click();
        return { ok: true, method: 'detail-back' };
      }
    }
    const goBack = document.querySelector('[aria-label="Go Back"]');
    if (goBack) {
      goBack.click();
      return { ok: true, method: 'detail-back' };
    }
  }

  const sidebar = document.querySelector('.bg-sidebar');
  if (sidebar) {
    const row = sidebar.querySelector('[class*="min-h-[32px]"]');
    if (row) {
      row.click();
      return { ok: true, method: 'sidebar-row' };
    }
  }
  window.history.back();
  return { ok: true, method: 'history-back' };
})()
"""

DISMISS_SETTINGS_SCRIPT = """
(async () => {
  const overlay = document.querySelector('.fixed.inset-0[class*="z-[5000]"]');
  if (overlay) {
    overlay.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 5, clientY: 5 }));
    return { ok: true, method: 'backdrop' };
  }
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  return { ok: true, method: 'escape' };
})()
"""

CLOSE_RIGHT_SIDEBAR_SCRIPT = """
(() => {
  const closeBtn = document.querySelector('[data-testid="toggle-aux-sidebar"]');
  if (closeBtn) {
    closeBtn.click();
    return 'closed';
  }
  return null;
})()
"""

SELECT_OVERVIEW_TAB_SCRIPT = """
(() => {
  const tabs = document.querySelectorAll('[data-tab-id]');
  const anyActive = [...tabs].some(t => (t.className || '').includes('bg-secondary'));
  if (!anyActive) {
    const overview = document.querySelector('[data-tab-id="overview"]');
    if (overview) overview.click();
  }
})()
"""

HAS_VISIBLE_EDITOR_SCRIPT = """
(() => {
  const candidates = document.querySelectorAll(
    '[data-lexical-editor="true"], [contenteditable="true"][role="textbox"], [contenteditable="true"]'
  );
  const hasLexicalNode = !!document.querySelector('[data-lexical-editor="true"]');
  for (const el of candidates) {
    if (el.offsetParent !== null) {
      if (hasLexicalNode && !el.__lexicalEditor) continue;
      return true;
    }
  }
  return false;
})()
"""

OPEN_RIGHT_SIDEBAR_SCRIPT = """
(() => {
  const candidates = [
    ...document.querySelectorAll('[aria-label*="Review" i]'),
    ...document.querySelectorAll('[aria-label*="Auxiliary" i]'),
    ...document.querySelectorAll('[aria-label*="Secondary Side Bar" i]'),
    ...document.querySelectorAll('[data-tooltip-id*="review" i]'),
  ];
  for (const btn of candidates) {
    if (btn.tagName === 'BUTTON' || btn.getAttribute('role') === 'button' || btn.closest('button')) {
      (btn.closest('button') || btn).click();
      return 'button';
    }
  }
  return null;
})()
"""


# --- Dynamic Script Builders ---

def build_capture_listbox_script() -> str:
    return """
(() => {
  for (const child of document.body.children) {
    if (child.getAttribute('role') === 'listbox' && child.getBoundingClientRect().width > 0) {
      let idx = 0;
      const tagged = [];
      child.querySelectorAll('[role="option"], button, a').forEach(el => {
        el.setAttribute('data-ag-click-id', 'scheddlg:' + (100 + idx));
        el.setAttribute('data-ag-click-label', el.textContent.trim().substring(0, 50));
        idx++;
        tagged.push(el);
      });
      const clone = child.cloneNode(true);
      tagged.forEach(el => {
        el.removeAttribute('data-ag-click-id');
        el.removeAttribute('data-ag-click-label');
      });
      return clone.outerHTML;
    }
  }
  return null;
})()
"""

def build_capture_kebab_menu_script() -> str:
    return """
(() => {
  for (const child of document.body.children) {
    if (child.id || child.tagName === 'SCRIPT' || child.tagName === 'STYLE') continue;
    const text = child.textContent.trim();
    if (!text || text.length > 500) continue;
    const role = child.getAttribute('role');
    const hasSide = child.hasAttribute('data-side') || child.querySelector('[data-side]');
    const isPopover = role === 'dialog' || role === 'menu' || role === 'listbox' || hasSide;
    const hasButtons = child.querySelectorAll('button, [role="menuitem"], [role="option"]').length > 0;
    if (!isPopover && !hasButtons) continue;
    if (child.getBoundingClientRect().width <= 0) continue;

    let idx = 0;
    const tagged = [];
    child.querySelectorAll('button, [role="menuitem"], [role="option"], a').forEach(el => {
      el.setAttribute('data-ag-click-id', 'scheddlg:' + (100 + idx));
      el.setAttribute('data-ag-click-label', el.textContent.trim().substring(0, 50));
      idx++;
      tagged.push(el);
    });
    if (idx === 0) continue;
    const clone = child.cloneNode(true);
    tagged.forEach(el => {
      el.removeAttribute('data-ag-click-id');
      el.removeAttribute('data-ag-click-label');
    });
    return clone.outerHTML;
  }
  return null;
})()
"""

def build_inject_script(safe_text: str, append_mode: bool = False) -> str:
    append_js = "true" if append_mode else "false"
    return f"""
(async () => {{
  const editorCandidates = document.querySelectorAll(
    '[data-lexical-editor="true"], [contenteditable="true"][role="textbox"], [contenteditable="true"]'
  );
  let editor = null;
  for (const el of editorCandidates) {{
    if (el.offsetParent !== null) editor = el;
  }}
  if (!editor) return {{ ok: false, reason: 'no_editor' }};

  editor.focus();
  if ({append_js}) {{
    const sel = window.getSelection();
    sel.selectAllChildren(editor);
    sel.collapseToEnd();
  }} else {{
    const sel = window.getSelection();
    sel.selectAllChildren(editor);
    document.execCommand('delete', false, null);
  }}

  const text = {safe_text};
  const textVal = text;
  const dt = new DataTransfer();
  dt.setData('text/plain', textVal);
  const pasteEvent = new ClipboardEvent('paste', {{
    clipboardData: dt, bubbles: true, cancelable: true,
  }});
  const notHandled = editor.dispatchEvent(pasteEvent);
  if (notHandled) {{
    document.execCommand('insertText', false, textVal);
  }}

  await new Promise(r => setTimeout(r, 100));

  const submitSelectors = [
    'button[data-testid="send-button"]',
    'button[aria-label*="send" i]',
    'button[aria-label*="submit" i]',
  ];
  let submitBtn = null;
  for (const sel of submitSelectors) {{
    submitBtn = document.querySelector(sel);
    if (submitBtn && submitBtn.offsetParent !== null) break;
    submitBtn = null;
  }}
  if (!submitBtn) {{
    const arrow = document.querySelector('svg.lucide-arrow-right, svg.lucide-arrow-up');
    if (arrow) submitBtn = arrow.closest('button');
  }}
  if (!submitBtn) {{
    const form = editor.closest('form');
    if (form) submitBtn = form.querySelector('button[type="submit"], button:last-of-type');
  }}
  if (!submitBtn) {{
    const parent = editor.parentElement;
    if (parent) submitBtn = parent.querySelector('button');
  }}

  if (submitBtn) {{
    submitBtn.click();
    return {{ ok: true, method: 'button' }};
  }}

  const enterEvent = new KeyboardEvent('keydown', {{
    key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true,
  }});
  editor.dispatchEvent(enterEvent);
  return {{ ok: true, method: 'enter' }};
}})()
"""

def build_task_click_script(task_idx: int) -> str:
    return f"""
(() => {{
  const inputBox = document.getElementById('antigravity.agentSidePanelInputBox');
  if (!inputBox) return {{ ok: false, reason: 'no_input_box' }};
  const taskSection = inputBox.querySelector('.rounded-t-2xl');
  if (!taskSection) return {{ ok: false, reason: 'no_task_section' }};
  const btns = taskSection.querySelectorAll('button');
  const idx = {task_idx};
  if (idx < 0 || idx >= btns.length) return {{ ok: false, reason: 'task_index_out_of_range', total: btns.length }};
  const target = btns[idx];
  const actualLabel = (target.textContent || '').trim().substring(0, 80);
  target.click();
  return {{ ok: true, label: actualLabel, source: 'task' }};
}})()
"""

def build_sched_click_script(sched_idx: int) -> str:
    return f"""
(() => {{
  let anchor = document.querySelector('[aria-label="Add scheduled task"]');
  if (!anchor) {{
    anchor = document.querySelector('[aria-label="Edit task title"]');
  }}
  if (!anchor) {{
    anchor = document.querySelector('textarea[placeholder*="Prompt to execute"]');
  }}
  if (!anchor) return {{ ok: false, reason: 'no_scheduled_tasks_page' }};

  let container = anchor;
  for (let i = 0; i < 15; i++) {{
    if (!container.parentElement) break;
    const p = container.parentElement;
    if (p.getBoundingClientRect().x < 10) break;
    container = p;
  }}
  const inner = container.querySelector('.flex-1.flex.flex-col.min-w-0.h-full') || container;
  const elements = [];
  inner.querySelectorAll('button, a, [role="button"], input, select, textarea').forEach(el => elements.push(el));
  inner.querySelectorAll('[class*="cursor-pointer"]').forEach(el => {{
    if (elements.includes(el)) return;
    const text = (el.textContent || '').trim();
    if (text.length > 200) return;
    elements.push(el);
  }});
  const idx = {sched_idx};
  if (idx < 0 || idx >= elements.length) return {{ ok: false, reason: 'sched_index_out_of_range', total: elements.length }};
  const target = elements[idx];
  const actualLabel = (target.textContent || target.getAttribute('placeholder') || '').trim().substring(0, 80);
  if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {{
    target.focus();
  }} else {{
    target.click();
  }}
  return {{ ok: true, label: actualLabel, source: 'sched' }};
}})()
"""

def build_sched_portal_click_script(opt_idx: int) -> str:
    return f"""
(() => {{
  for (const child of document.body.children) {{
    if (child.id || child.tagName === 'SCRIPT' || child.tagName === 'STYLE') continue;
    if (child.getBoundingClientRect().width <= 0) continue;
    const role = child.getAttribute('role');
    const hasSide = child.hasAttribute('data-side') || child.querySelector('[data-side]');
    const isPortal = role === 'listbox' || role === 'dialog' || role === 'menu' || hasSide;
    const hasButtons = child.querySelectorAll('button, [role="menuitem"], [role="option"]').length > 0;
    if (!isPortal && !hasButtons) continue;

    const options = child.querySelectorAll('[role="option"], [role="menuitem"], button, a');
    const idx = {opt_idx};
    if (idx < 0 || idx >= options.length) return {{ ok: false, reason: 'option_index_out_of_range', total: options.length }};
    const target = options[idx];
    const rect = target.getBoundingClientRect();
    const x = rect.left + 5;
    const y = rect.top + rect.height / 2;
    const hit = document.elementFromPoint(x, y) || target;

    const clickOpts = {{
      bubbles: true,
      cancelable: true,
      clientX: x,
      clientY: y
    }};
    hit.dispatchEvent(new PointerEvent('pointerdown', clickOpts));
    hit.dispatchEvent(new MouseEvent('mousedown', clickOpts));
    hit.dispatchEvent(new PointerEvent('pointerup', clickOpts));
    hit.dispatchEvent(new MouseEvent('mouseup', clickOpts));
    
    let clickTarget = hit;
    while (clickTarget && typeof clickTarget.click !== 'function') {{
      clickTarget = clickTarget.parentElement;
    }}
    if (clickTarget) {{
      clickTarget.click();
    }}
    return {{ ok: true, label: target.textContent.trim().substring(0, 50), source: 'scheddlg_portal' }};
  }}
  return null;
}})()
"""

def build_sched_dialog_click_script(dlg_idx: int, safe_label: str = '""') -> str:
    return f"""
(() => {{
  const overlay = document.querySelector('.fixed.inset-0[class*="z-[2550]"]');
  if (!overlay || overlay.getBoundingClientRect().width <= 0) return {{ ok: false, reason: 'no_dialog' }};
  const elements = [];
  overlay.querySelectorAll('button, a, [role="button"], input, select, textarea, [role="combobox"], [role="switch"]').forEach(el => elements.push(el));
  overlay.querySelectorAll('div.cursor-pointer[aria-expanded]').forEach(el => {{
    if (!elements.includes(el)) elements.push(el);
  }});

  const idx = {dlg_idx};
  const expectedLabel = {safe_label};
  let target = (idx >= 0 && idx < elements.length) ? elements[idx] : null;

  if (target && expectedLabel) {{
    const actualLabel = (target.textContent || target.getAttribute('placeholder') || '').trim().substring(0, 50);
    if (actualLabel !== expectedLabel) {{
      target = null;
      for (const el of elements) {{
        const elLabel = (el.textContent || el.getAttribute('placeholder') || '').trim().substring(0, 50);
        if (elLabel === expectedLabel) {{ target = el; break; }}
      }}
    }}
  }}

  if (!target) return {{ ok: false, reason: 'element_not_found', idx: idx, label: expectedLabel, total: elements.length }};
  const actualLabel = (target.textContent || target.getAttribute('placeholder') || '').trim().substring(0, 80);
  if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {{
    target.focus();
  }} else {{
    target.click();
  }}
  return {{ ok: true, label: actualLabel, source: 'scheddlg' }};
}})()
"""

def build_main_click_script(safe_click_id: str, safe_label: str = '""') -> str:
    return f"""
(async () => {{
  const clickId = {safe_click_id};
  const expectedLabel = {safe_label};

  const colonIdx = clickId.indexOf(':');
  if (colonIdx === -1) return {{ ok: false, reason: 'invalid_click_id' }};
  const source = clickId.substring(0, colonIdx);
  const idx = parseInt(clickId.substring(colonIdx + 1), 10);

  let root = null;
  if (source === 'chat') {{
    root =
      document.querySelector('.scrollbar-hide[class*="overflow-y-auto"]') ||
      document.querySelector('[data-testid="conversation-view"]') ||
      document.getElementById('conversation') ||
      document.getElementById('chat') ||
      document.getElementById('cascade');

    if (!root || root.clientHeight === 0) {{
      const inputBox = document.getElementById('antigravity.agentSidePanelInputBox');
      if (inputBox) {{
        let newRoot = inputBox;
        for (let i = 0; i < 10; i++) {{
          if (!newRoot.parentElement) break;
          newRoot = newRoot.parentElement;
          const cls = newRoot.className?.toString() || '';
          if (cls.includes('animate-fade-in')) break;
        }}
        root = newRoot;
      }}
    }}
  }} else if (source === 'left') {{
    root = document.querySelector('.bg-sidebar');
  }} else if (source === 'right') {{
    const tabBtn = document.querySelector('[data-tab-id="overview"], [data-tab-id="review"]');
    const anchor = tabBtn || document.querySelector('[data-testid="toggle-aux-sidebar"]');
    if (anchor) {{
      let el = anchor;
      for (let i = 0; i < 10 && el; i++) {{
        el = el.parentElement;
        const cls = el?.className?.toString?.() || '';
        if (cls.includes('flex') && cls.includes('flex-col') && el.children.length >= 2) {{
          root = el;
          break;
        }}
      }}
    }}
  }} else if (source === 'dropdown') {{
    for (const child of document.body.children) {{
      if (child.getAttribute('role') === 'listbox' && child.textContent.trim()) {{
        root = child;
        break;
      }}
      if (child.id) {{
        const nested = child.querySelector('[role="listbox"]');
        if (nested && nested.textContent.trim()) {{
          root = nested;
          break;
        }}
      }}
    }}
  }} else if (source === 'dialog') {{
    for (const child of document.body.children) {{
      const cls = child.className || '';
      if (cls.includes('fixed') && cls.includes('inset-0')) {{
        root = child;
        break;
      }}
      if (!root && child.getAttribute('role') === 'dialog') {{
        root = child;
      }}
      if (!root && child.id) {{
        const nested = child.querySelector('[role="dialog"]');
        if (nested && nested.getBoundingClientRect().width > 0) {{
          root = nested;
        }}
      }}
    }}
  }} else if (source === 'settings') {{
    const settingsOverlay = document.querySelector('#root .fixed.inset-0[class*="z-[5000]"]');
    if (settingsOverlay) {{
      root = settingsOverlay.querySelector('[class*="max-w-5xl"]') ||
             settingsOverlay.querySelector('[class*="rounded-2xl"]') ||
             settingsOverlay;
    }}
  }} else if (source === 'ask') {{
    const allBtns = Array.from(document.querySelectorAll('button'));
    const skipBtn = allBtns.find(b => b.textContent.trim() === 'Skip');
    const submitBtn = allBtns.find(b => /^Submit/.test(b.textContent.trim()));
    if (skipBtn && submitBtn) {{
      let container = skipBtn;
      for (let i = 0; i < 20 && container.parentElement; i++) {{
        container = container.parentElement;
        if (container.contains(submitBtn)) break;
      }}
      let cardRoot = container;
      for (let i = 0; i < 5 && cardRoot.parentElement; i++) {{
        const cls = (cardRoot.className || '').toString();
        if (cls.includes('bg-card-border')) break;
        cardRoot = cardRoot.parentElement;
      }}
      const askEls = [];
      cardRoot.querySelectorAll('[role="radiogroup"] label, [role="group"] label').forEach(el => askEls.push(el));
      cardRoot.querySelectorAll('button').forEach(el => askEls.push(el));
      if (idx >= 0 && idx < askEls.length) {{
        const target = askEls[idx];
        const actualLabel = (target.textContent || '').trim().substring(0, 50);
        target.click();
        return {{ ok: true, label: actualLabel, source: 'ask' }};
      }}
      return {{ ok: false, reason: 'ask_index_out_of_range', total: askEls.length }};
    }}
    return {{ ok: false, reason: 'no_ask_question_modal' }};
  }} else if (source === 'perm') {{
    const radioGroup = document.querySelector('[role="radiogroup"]');
    if (radioGroup) {{
      let banner = radioGroup;
      for (let i = 0; i < 10; i++) {{
        if (!banner.parentElement || banner.parentElement === document.body) break;
        banner = banner.parentElement;
        if (/allow|permission/i.test(banner.textContent) && banner.querySelectorAll('button').length >= 1) break;
      }}
      const permEls = [];
      banner.querySelectorAll('[role="radiogroup"] label').forEach(el => permEls.push(el));
      banner.querySelectorAll('button').forEach(el => permEls.push(el));
      if (idx >= 0 && idx < permEls.length) {{
        const target = permEls[idx];
        const actualLabel = (target.textContent || '').trim().substring(0, 50);
        target.click();
        return {{ ok: true, label: actualLabel, source: 'perm' }};
      }}
      return {{ ok: false, reason: 'perm_index_out_of_range', total: permEls.length }};
    }}
    return {{ ok: false, reason: 'no_permission_banner' }};
  }} else if (source === 'subinfo') {{
    const allDivs = document.querySelectorAll('div');
    let infoPanel = null;
    for (const div of allDivs) {{
      const txt = div.textContent.trim().toLowerCase();
      if ((txt.includes('cannot') && txt.includes('prompt')) || (txt.includes('open') && txt.includes('overview'))) {{
        if (!infoPanel || (infoPanel.contains(div) && div !== infoPanel)) {{
          infoPanel = div;
        }}
      }}
    }}
    if (infoPanel) root = infoPanel;
  }} else if (source === 'btw') {{
    const span = Array.from(document.querySelectorAll('span')).find(s => s.textContent.trim().startsWith('Side Question'));
    if (span) {{
      let container = span;
      for (let i = 0; i < 5 && container; i++) {{
        const cls = (container.className || '').toString();
        if (cls.includes('border-border') && cls.includes('rounded-md')) break;
        container = container.parentElement;
      }}
      if (container) root = container;
    }}
  }} else if (source === 'model') {{
    root = document.querySelector('[aria-label*="Select model"]');
    if (root) {{
      root.click();
      return {{ ok: true, label: root.textContent.trim().substring(0, 50), source: 'model' }};
    }}
  }} else if (source === 'project') {{
    root = document.querySelector('[aria-label="Select Environment"]') || document.querySelector('[aria-label="Select Default Branch"]');
    if (root) {{
      root.click();
      return {{ ok: true, label: root.textContent.trim().substring(0, 50), source: 'project' }};
    }}
  }}

  if (!root) return {{ ok: false, reason: 'no_root_for_source', source }};

  const elements = [];
  const maxLen = (source === 'chat') ? 80 : 0;
  root.querySelectorAll('button, a, [role="button"], [role="option"], [role="menuitem"]').forEach(el => {{
    if (source === 'dropdown' || source === 'dialog' || source === 'settings' || el.offsetParent !== null) {{
      elements.push(el);
    }}
  }});
  root.querySelectorAll('[class*="cursor-pointer"]').forEach(el => {{
    if (!elements.includes(el) && (source === 'dropdown' || source === 'dialog' || source === 'settings' || el.offsetParent !== null)) {{
      const hasHandler = typeof el.onclick === 'function';
      if (maxLen && (el.textContent || '').trim().length > maxLen && !hasHandler) return;
      elements.push(el);
    }}
  }});

  if (idx < 0 || idx >= elements.length) {{
    return {{ ok: false, reason: 'index_out_of_range', idx, total: elements.length, source }};
  }}

  const target = elements[idx];
  const actualLabel = (target.textContent || target.getAttribute('aria-label') || '').trim().substring(0, 50);

  if (expectedLabel && actualLabel && actualLabel !== expectedLabel) {{
    let matched = null;
    for (const el of elements) {{
      const l = (el.textContent || el.getAttribute('aria-label') || '').trim().substring(0, 50);
      if (l === expectedLabel) {{ matched = el; break; }}
    }}
    if (matched) {{
      matched.click();
      return {{ ok: true, label: expectedLabel, source, recovered: true }};
    }}
  }}

  target.click();
  return {{ ok: true, label: actualLabel, source }};
}})()
"""

def build_type_text_script(safe_placeholder: str = '""', safe_click_id: str = '""', safe_text: str = '""') -> str:
    return f"""
(() => {{
  let el = null;
  const placeholder = {safe_placeholder};
  if (placeholder) {{
    const overlay = document.querySelector('.fixed.inset-0[class*="z-[2550]"]');
    const mainContent = document.querySelector('.flex-1.flex.flex-col.min-w-0.h-full');
    const scope = overlay || mainContent || document;
    el = scope.querySelector('input[placeholder=' + JSON.stringify(placeholder) + '], textarea[placeholder=' + JSON.stringify(placeholder) + ']');
  }}

  if (!el) {{
    const clickId = {safe_click_id};
    if (clickId) {{
      const parts = clickId.split(':');
      const prefix = parts[0];
      const idx = parseInt(parts[1], 10);

      if (prefix === 'sched') {{
        let anchor = document.querySelector('[aria-label="Add scheduled task"]') ||
                     document.querySelector('[aria-label="Edit task title"]') ||
                     document.querySelector('textarea[placeholder*="Prompt to execute"]');
        if (anchor) {{
          let container = anchor;
          for (let i = 0; i < 15; i++) {{
            if (!container.parentElement) break;
            const p = container.parentElement;
            if (p.getBoundingClientRect().x < 10) break;
            container = p;
          }}
          const inner = container.querySelector('.flex-1.flex.flex-col.min-w-0.h-full') || container;
          const elements = inner.querySelectorAll('button, a, [role="button"], input, select, textarea');
          if (idx < elements.length) el = elements[idx];
        }}
      }} else if (prefix === 'scheddlg') {{
        const overlay = document.querySelector('.fixed.inset-0[class*="z-[2550]"]');
        if (overlay) {{
          const elements = overlay.querySelectorAll('button, a, [role="button"], input, select, textarea');
          if (idx < elements.length) el = elements[idx];
        }}
      }}
    }}
  }}

  if (!el) return {{ ok: false, reason: 'element_not_found', placeholder: {safe_placeholder}, clickId: {safe_click_id} }};
  if (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA') {{
    return {{ ok: false, reason: 'not_input', tag: el.tagName }};
  }}

  el.focus();
  const nativeSetter = el.tagName === 'TEXTAREA'
    ? Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
    : Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;

  nativeSetter.call(el, {safe_text});
  el.dispatchEvent(new Event('input', {{ bubbles: true }}));
  el.dispatchEvent(new Event('change', {{ bubbles: true }}));

  return {{ ok: true, tag: el.tagName, placeholder: {safe_placeholder}, valueLength: el.value.length }};
}})()
"""

def build_upload_image_script(safe_base64: str, safe_mimetype: str, safe_file_name: str) -> str:
    return f"""
(async () => {{
  const base64 = {safe_base64};
  const mimetype = {safe_mimetype};
  const fileName = {safe_file_name};

  const binaryStr = atob(base64);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {{
    bytes[i] = binaryStr.charCodeAt(i);
  }}

  const file = new File([bytes], fileName, {{ type: mimetype }});
  const editorCandidates = document.querySelectorAll(
    '[data-lexical-editor="true"], [contenteditable="true"][role="textbox"], [contenteditable="true"]'
  );
  let editor = null;
  for (const el of editorCandidates) {{
    if (el.offsetParent !== null) editor = el;
  }}
  if (!editor) return {{ ok: false, reason: 'no_editor' }};

  const dt = new DataTransfer();
  dt.items.add(file);

  editor.dispatchEvent(new DragEvent('dragenter', {{ dataTransfer: dt, bubbles: true }}));
  editor.dispatchEvent(new DragEvent('dragover', {{ dataTransfer: dt, bubbles: true, cancelable: true }}));
  editor.dispatchEvent(new DragEvent('drop', {{ dataTransfer: dt, bubbles: true, cancelable: true }}));

  return {{ ok: true, method: 'drop', fileName, size: bytes.length }};
}})()
"""

def build_click_conversation_script(safe_conversation_id: str) -> str:
    return f"""
(async () => {{
  const conversationId = {safe_conversation_id};
  const leftRoot = document.querySelector('.bg-sidebar');
  if (!leftRoot || leftRoot.offsetParent === null) {{
    const toggleBtn = document.querySelector('[data-testid="sidebar-toggle"]');
    if (toggleBtn) toggleBtn.click();
    await new Promise(r => setTimeout(r, 300));
  }}

  const pill = document.querySelector('[data-testid="convo-pill-' + conversationId + '"]');
  if (!pill) return {{ ok: false, reason: 'pill_not_found', conversationId }};

  let target = pill;
  for (let i = 0; i < 10 && target; i++) {{
    if (target.getAttribute('role') === 'button') {{
      target.click();
      const name = (target.textContent || '').trim().substring(0, 80);
      return {{ ok: true, conversationId, name }};
    }}
    target = target.parentElement;
  }}

  const fallback = pill.closest('[role="button"], button, a');
  if (fallback) {{
    fallback.click();
    return {{ ok: true, conversationId, fallback: true }};
  }}

  return {{ ok: false, reason: 'no_clickable_ancestor', conversationId }};
}})()
"""

def build_history_click_script(hist_idx: int) -> str:
    return f"""
(() => {{
  const container = Array.from(
    document.querySelectorAll('.h-full.w-full.overflow-y-auto')
  ).find(el => {{
    const r = el.getBoundingClientRect();
    return r.x > 200 && r.height > 300;
  }});
  if (!container) return {{ ok: false, reason: 'no_history_page' }};

  const heading = container.querySelector('.text-lg.font-medium');
  if (!heading || heading.textContent.trim() !== 'Conversation History') {{
    return {{ ok: false, reason: 'not_history_page' }};
  }}

  const inner = container.querySelector('.w-full.max-w-2xl') || container;
  const elements = [];
  inner.querySelectorAll('button, a, [role="button"], input').forEach(el => elements.push(el));
  inner.querySelectorAll('[class*="cursor-pointer"]').forEach(el => {{
    if (elements.includes(el)) return;
    const text = (el.textContent || '').trim();
    if (text.length > 200) return;
    elements.push(el);
  }});

  const idx = {hist_idx};
  if (idx < 0 || idx >= elements.length) {{
    return {{ ok: false, reason: 'history_index_out_of_range', total: elements.length }};
  }}

  const target = elements[idx];
  const actualLabel = (target.textContent || target.getAttribute('placeholder') || '').trim().substring(0, 80);
  if (target.tagName === 'INPUT') {{
    target.focus();
  }} else {{
    target.click();
  }}
  return {{ ok: true, label: actualLabel, source: 'history' }};
}})()
"""

def build_copy_response_script(safe_click_id: str) -> str:
    return f"""
(async () => {{
  const clickId = {safe_click_id};
  const colonIdx = clickId.indexOf(':');
  if (colonIdx === -1) return {{ ok: false, reason: 'invalid_click_id' }};
  const source = clickId.substring(0, colonIdx);
  const idx = parseInt(clickId.substring(colonIdx + 1), 10);

  let root = null;
  if (source === 'chat') {{
    root =
      document.querySelector('.scrollbar-hide[class*="overflow-y-auto"]') ||
      document.querySelector('[data-testid="conversation-view"]') ||
      document.getElementById('conversation') ||
      document.getElementById('chat') ||
      document.getElementById('cascade');
  }}
  if (!root) return {{ ok: false, reason: 'no_root' }};

  const maxLen = (source === 'chat') ? 80 : 0;
  const visible = [];
  root.querySelectorAll('button, a, [role="button"]').forEach(el => {{
    if (el.offsetParent !== null) visible.push(el);
  }});
  root.querySelectorAll('[class*="cursor-pointer"]').forEach(el => {{
    if (el.offsetParent !== null && !visible.includes(el)) {{
      const hasHandler = typeof el.onclick === 'function';
      if (maxLen && (el.textContent || '').trim().length > maxLen && !hasHandler) return;
      visible.push(el);
    }}
  }});

  const target = visible[idx];
  if (!target) return {{ ok: false, reason: 'element_not_found', idx, total: visible.length }};

  let captured = null;
  const orig = navigator.clipboard.writeText.bind(navigator.clipboard);
  navigator.clipboard.writeText = (text) => {{
    captured = text;
    return orig(text);
  }};
  try {{
    target.click();
    await new Promise(r => setTimeout(r, 300));
  }} finally {{
    navigator.clipboard.writeText = orig;
  }}
  return {{ ok: true, text: captured || '' }};
}})()
"""

def build_proxy_image_script(safe_src: str) -> str:
    return f"""
(() => {{
  const targetSrc = {safe_src};
  const imgs = document.querySelectorAll('img');
  for (const img of imgs) {{
    if (img.src !== targetSrc && img.getAttribute('src') !== targetSrc) continue;
    if (!img.complete || img.naturalWidth === 0) continue;

    try {{
      const MAX_WIDTH = 800;
      let w = img.naturalWidth;
      let h = img.naturalHeight;
      if (w > MAX_WIDTH) {{
        h = Math.round(h * (MAX_WIDTH / w));
        w = MAX_WIDTH;
      }}
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, w, h);
      return canvas.toDataURL('image/png');
    }} catch (e) {{
      return null;
    }}
  }}
  return null;
}})()
"""


# ============================================================================
# 5. CDPBridge Implementation
# ============================================================================

class CDPBridge:
    """
    Asynchronous Chrome DevTools Protocol (CDP) Bridge for Antigravity Desktop.
    Connects to Antigravity Electron process, manages multi-context execution,
    evaluates CDP scripts, captures live DOM snapshots, and proxies user interactions.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        poll_interval: float = 0.5,
        app_data_dir: Optional[str] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.poll_interval = poll_interval
        self.app_data_dir = app_data_dir

        self._ws: Any = None
        self._read_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._is_connected: bool = False
        self._connection_state: str = "disconnected"  # "connected", "connecting", "disconnected"

        self._req_id: int = 0
        self._pending_commands: Dict[int, asyncio.Future] = {}
        self._contexts: Dict[int, ExecutionContext] = {}
        self._preferred_context_id: Optional[int] = None

        self.cached_snapshot: Optional[DOMSnapshot] = None
        self.last_snapshot_hash: Optional[str] = None
        self._active_target: Optional[CDPTarget] = None
        self._active_port: Optional[int] = None
        self._status_listeners: List[Callable[[Dict[str, Any]], None]] = []

    @property
    def is_connected(self) -> bool:
        """Returns True if CDP WebSocket client is connected and active."""
        if not self._is_connected or self._ws is None:
            return False
        if hasattr(self._ws, "close_code"):
            return self._ws.close_code is None
        return not getattr(self._ws, "closed", False)

    @property
    def connection_state(self) -> str:
        """Returns 'connected', 'connecting', or 'disconnected'."""
        return self._connection_state

    @property
    def contexts(self) -> List[ExecutionContext]:
        """Returns list of currently active execution contexts."""
        return list(self._contexts.values())

    @property
    def preferred_context_id(self) -> Optional[int]:
        """Returns the currently locked preferred context ID."""
        return self._preferred_context_id

    def add_status_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Registers a status listener for connection and snapshot events."""
        self._status_listeners.append(callback)

    def _broadcast_status(self, data: Dict[str, Any]) -> None:
        for cb in self._status_listeners:
            try:
                cb(data)
            except Exception as e:
                logger.debug(f"[CDP] Status listener error: {e}")

    # --- Connection Lifecycle ---

    async def connect(self, retry_on_failure: bool = False) -> bool:
        """
        Discovers target, opens WebSocket connection, enables Runtime domain,
        subscribes to execution context events, and enables focus emulation.
        """
        if self.is_connected:
            return True

        self._connection_state = "connecting"
        try:
            discovery = await discover_target(
                host=self.host,
                port=self.port,
                app_data_dir=self.app_data_dir,
            )
            if not discovery:
                self._connection_state = "disconnected"
                if retry_on_failure:
                    self._schedule_reconnect()
                return False

            port, target = discovery
            self._active_port = port
            self._active_target = target

            logger.info(f"[CDP] Connecting to '{target.title}' on {target.webSocketDebuggerUrl}")
            ws = await websockets.connect(
                target.webSocketDebuggerUrl,
                max_size=100 * 1024 * 1024,
            )
            self._ws = ws
            self._is_connected = True
            self._connection_state = "connected"

            # Start background frame reader loop
            self._read_task = asyncio.create_task(self._read_loop())

            # Enable Runtime domain
            await self._send_command("Runtime.enable")

            # Enable Emulation focus emulation
            try:
                await self._send_command(
                    "Emulation.setFocusEmulationEnabled", {"enabled": True}, timeout=2.0
                )
            except Exception:
                pass

            # Wait briefly for context events
            await asyncio.sleep(0.1)

            logger.info(f"[CDP] Connected. {len(self._contexts)} context(s) available.")
            self._broadcast_status({"type": "connection", "cdpConnected": True})
            return True
        except Exception as e:
            logger.debug(f"[CDP] Connection failed: {e}")
            self._is_connected = False
            self._connection_state = "disconnected"
            if retry_on_failure:
                self._schedule_reconnect()
            return False

    async def disconnect(self) -> None:
        """Gracefully closes WebSocket connection and cleans up pending tasks."""
        self._is_connected = False
        self._connection_state = "disconnected"

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            self._read_task = None

        # Clean up pending futures
        for fut in list(self._pending_commands.values()):
            if not fut.done():
                fut.set_exception(RuntimeError("CDP connection closed"))
        self._pending_commands.clear()
        self._contexts.clear()
        self._preferred_context_id = None

        self._broadcast_status({"type": "connection", "cdpConnected": False})

    async def test_connect(self) -> bool:
        """
        Lightweight probe checking if Antigravity CDP is reachable.
        Connects and leaves connected if reachable, or returns False if offline.
        """
        if self.is_connected:
            return True
        return await self.connect(retry_on_failure=False)

    def _schedule_reconnect(self, delay: float = 3.0) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            return

        async def _reconnect_job():
            try:
                await asyncio.sleep(delay)
                logger.info("[CDP] Attempting reconnection...")
                success = await self.connect(retry_on_failure=False)
                if not success:
                    self._schedule_reconnect(delay)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"[CDP] Reconnect error: {e}")
                self._schedule_reconnect(delay)

        self._reconnect_task = asyncio.create_task(_reconnect_job())

    def _handle_disconnect(self) -> None:
        was_connected = self._is_connected
        self._is_connected = False
        self._connection_state = "disconnected"
        self._ws = None

        for fut in list(self._pending_commands.values()):
            if not fut.done():
                fut.set_exception(RuntimeError("CDP disconnected"))
        self._pending_commands.clear()
        self._contexts.clear()
        self._preferred_context_id = None

        if was_connected:
            logger.info("[CDP] Disconnected from server")
            self._broadcast_status({"type": "connection", "cdpConnected": False})

    async def _read_loop(self) -> None:
        """Background WebSocket frame receiver and event router."""
        try:
            while self._ws and self.is_connected:
                raw_message = await self._ws.recv()
                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode("utf-8")

                try:
                    data = json.loads(raw_message)
                except Exception:
                    continue

                msg_id = data.get("id")
                if msg_id is not None and msg_id in self._pending_commands:
                    fut = self._pending_commands.pop(msg_id)
                    if not fut.done():
                        if "error" in data:
                            fut.set_exception(RuntimeError(f"CDP error: {data['error']}"))
                        else:
                            fut.set_result(data.get("result", {}))
                elif "method" in data:
                    method = data["method"]
                    params = data.get("params", {})
                    self._handle_cdp_event(method, params)
        except (asyncio.CancelledError, websockets.exceptions.ConnectionClosed):
            pass
        except Exception as e:
            logger.debug(f"[CDP] Read loop error: {e}")
        finally:
            self._handle_disconnect()

    def _handle_cdp_event(self, method: str, params: Dict[str, Any]) -> None:
        """Handles asynchronous notifications from Chrome DevTools Protocol."""
        if method == "Runtime.executionContextCreated":
            ctx_data = params.get("context", {})
            ctx_id = ctx_data.get("id")
            if ctx_id is not None:
                is_def = bool(ctx_data.get("isDefault", False)) or bool(
                    ctx_data.get("auxData", {}).get("isDefault", False)
                )
                ctx = ExecutionContext(
                    id=ctx_id,
                    origin=ctx_data.get("origin", ""),
                    name=ctx_data.get("name", ""),
                    aux_data=ctx_data.get("auxData", {}),
                    is_default_flag=is_def,
                )
                self._contexts[ctx_id] = ctx
                logger.debug(f"[CDP] Context created: id={ctx.id} name='{ctx.name}' default={ctx.is_default}")
        elif method == "Runtime.executionContextDestroyed":
            ctx_id = params.get("executionContextId")
            if ctx_id is not None:
                self._contexts.pop(ctx_id, None)
                if self._preferred_context_id == ctx_id:
                    self._preferred_context_id = None
                logger.debug(f"[CDP] Context destroyed: id={ctx_id}")
        elif method == "Runtime.executionContextsCleared":
            self._contexts.clear()
            self._preferred_context_id = None
            logger.debug("[CDP] Contexts cleared")

    async def _send_command(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0
    ) -> Dict[str, Any]:
        """Sends a JSON-RPC 2.0 command over CDP WebSocket and awaits response."""
        if not self._ws or not self.is_connected:
            raise RuntimeError("CDP not connected")

        self._req_id += 1
        req_id = self._req_id
        payload = {"id": req_id, "method": method, "params": params or {}}

        fut = asyncio.get_running_loop().create_future()
        self._pending_commands[req_id] = fut

        try:
            await self._ws.send(json.dumps(payload))
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_commands.pop(req_id, None)
            raise TimeoutError(f"CDP command '{method}' timed out after {timeout}s")
        except Exception:
            self._pending_commands.pop(req_id, None)
            raise

    # --- Multi-Context Evaluation Engine ---

    async def evaluate_in_browser(
        self,
        expression: str,
        await_promise: bool = True,
        return_by_value: bool = True,
        timeout: float = 5.0,
    ) -> Any:
        """
        Evaluates JS in browser trying contexts in priority order:
        1. Preferred context (locked from previous success)
        2. Default contexts (isDefault == True)
        3. Other contexts (isolated extension worlds)
        Locks to the first successfully evaluating context.
        """
        if not self.is_connected:
            raise RuntimeError("CDP not connected")

        sorted_contexts = sorted(
            self._contexts.values(),
            key=lambda c: (
                0 if c.id == self._preferred_context_id else 1,
                0 if c.is_default else 1,
                c.id,
            ),
        )

        if not sorted_contexts:
            # Fallback for mock environments without pre-registered contexts
            sorted_contexts = [ExecutionContext(id=1, origin="", name="default", is_default_flag=True)]

        for ctx in sorted_contexts:
            try:
                res = await self._send_command(
                    "Runtime.evaluate",
                    {
                        "expression": expression,
                        "contextId": ctx.id,
                        "awaitPromise": await_promise,
                        "returnByValue": return_by_value,
                    },
                    timeout=timeout,
                )
                if "exceptionDetails" in res:
                    continue

                self._preferred_context_id = ctx.id
                result_obj = res.get("result", {})
                if "result" in result_obj and isinstance(result_obj["result"], dict) and "value" in result_obj["result"]:
                    return result_obj["result"]["value"]
                return result_obj.get("value")
            except Exception as e:
                logger.debug(f"[CDP] evaluate_in_browser error in ctx {ctx.id}: {e}")
                continue

        raise RuntimeError("No valid execution context")

    async def evaluate_across_contexts(
        self,
        expression: str,
        await_promise: bool = True,
        return_by_value: bool = True,
        timeout: float = 5.0,
    ) -> Any:
        """
        Evaluates expression across all registered contexts and returns the FIRST NON-NULL result.
        Does not lock preferred context.
        """
        if not self.is_connected:
            raise RuntimeError("CDP not connected")

        ctx_list = list(self._contexts.values())
        if not ctx_list:
            ctx_list = [ExecutionContext(id=1, origin="", name="default", is_default_flag=True)]

        for ctx in ctx_list:
            try:
                res = await self._send_command(
                    "Runtime.evaluate",
                    {
                        "expression": expression,
                        "contextId": ctx.id,
                        "awaitPromise": await_promise,
                        "returnByValue": return_by_value,
                    },
                    timeout=timeout,
                )
                if "exceptionDetails" in res:
                    continue

                result_obj = res.get("result", {})
                val = result_obj.get("value")
                if val is None and "result" in result_obj and isinstance(result_obj["result"], dict):
                    val = result_obj["result"].get("value")

                if val is not None:
                    return val
            except Exception:
                continue
        return None

    async def evaluate_in_context(
        self,
        context_id: int,
        expression: str,
        await_promise: bool = True,
        return_by_value: bool = True,
        timeout: float = 5.0,
    ) -> Any:
        """Evaluates expression in a specific context without fallthrough."""
        if not self.is_connected:
            raise RuntimeError("CDP not connected")

        res = await self._send_command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "contextId": context_id,
                "awaitPromise": await_promise,
                "returnByValue": return_by_value,
            },
            timeout=timeout,
        )
        if "exceptionDetails" in res:
            text = res["exceptionDetails"].get("text", "CDP eval exception")
            raise RuntimeError(f"CDP eval exception in ctx {context_id}: {text}")

        result_obj = res.get("result", {})
        if "result" in result_obj and isinstance(result_obj["result"], dict) and "value" in result_obj["result"]:
            return result_obj["result"]["value"]
        return result_obj.get("value")

    async def find_editor_context(self) -> Optional[int]:
        """
        Runs synchronous HAS_VISIBLE_EDITOR_SCRIPT across contexts to locate
        the exact context containing an active Lexical editor.
        """
        if not self.is_connected:
            return None

        sorted_contexts = sorted(
            self._contexts.values(),
            key=lambda c: (
                0 if c.id == self._preferred_context_id else 1,
                0 if c.is_default else 1,
                c.id,
            ),
        )
        if not sorted_contexts:
            sorted_contexts = [ExecutionContext(id=1, origin="", name="default", is_default_flag=True)]

        for ctx in sorted_contexts:
            try:
                res = await self._send_command(
                    "Runtime.evaluate",
                    {
                        "expression": HAS_VISIBLE_EDITOR_SCRIPT,
                        "contextId": ctx.id,
                        "returnByValue": True,
                    },
                    timeout=1.0,
                )
                if "exceptionDetails" not in res:
                    val = res.get("result", {}).get("value")
                    if val is None and "result" in res.get("result", {}) and isinstance(res["result"]["result"], dict):
                        val = res["result"]["result"].get("value")

                    if val is True or (isinstance(val, dict) and (val.get("success") or val.get("hasEditor"))):
                        return ctx.id
            except Exception:
                continue

        # Fallback to default or preferred context if available
        if self._preferred_context_id is not None:
            return self._preferred_context_id
        for ctx in self._contexts.values():
            if ctx.is_default:
                return ctx.id
        return 1 if self._contexts else None

    # --- Snapshot Capture & State Management ---

    async def capture_snapshot(self) -> Optional[DOMSnapshot]:
        """
        Captures full DOM snapshot, harvests CSS and state variables, runs cross-context
        captures for scheduled/running tasks, and computes the DJB2 composite hash.
        """
        try:
            raw_result = await self.evaluate_in_browser(CAPTURE_SCRIPT)
            if not raw_result or not isinstance(raw_result, dict):
                raw_result = {"html": "", "css": "", "agentRunning": False, "scrollInfo": None}

            # Running tasks
            try:
                raw_result["runningTasksHtml"] = await self.evaluate_across_contexts(RUNNING_TASKS_SCRIPT)
            except Exception as e:
                logger.debug(f"[Snapshot] Running tasks eval failed: {e}")

            # Scheduled tasks
            try:
                raw_result["scheduledTasksHtml"] = await self.evaluate_across_contexts(SCHEDULED_TASKS_SCRIPT)
            except Exception as e:
                logger.debug(f"[Snapshot] Scheduled tasks eval failed: {e}")

            # Conversation history
            try:
                raw_result["conversationHistoryHtml"] = await self.evaluate_across_contexts(CONVERSATION_HISTORY_SCRIPT)
            except Exception as e:
                logger.debug(f"[Snapshot] Conversation history eval failed: {e}")

            # Scheduled tasks dialog & portals
            if raw_result.get("scheduledTasksHtml"):
                try:
                    raw_result["scheduledTasksDialogHtml"] = await self.evaluate_across_contexts(SCHEDULED_TASKS_DIALOG_SCRIPT)
                except Exception as e:
                    logger.debug(f"[Snapshot] Scheduled tasks dialog eval failed: {e}")

                if not raw_result.get("dropdownHtml"):
                    try:
                        raw_result["dropdownHtml"] = await self.evaluate_in_browser(build_capture_listbox_script())
                    except Exception as e:
                        logger.debug(f"[Snapshot] Listbox dropdown eval failed: {e}")

                if not raw_result.get("dropdownHtml"):
                    try:
                        raw_result["dropdownHtml"] = await self.evaluate_across_contexts(build_capture_kebab_menu_script())
                    except Exception as e:
                        logger.debug(f"[Snapshot] Kebab context menu eval failed: {e}")

            snapshot = DOMSnapshot(
                html=raw_result.get("html", ""),
                css=raw_result.get("css", ""),
                agentRunning=bool(raw_result.get("agentRunning", False)),
                scrollInfo=raw_result.get("scrollInfo"),
                leftSidebarHtml=raw_result.get("leftSidebarHtml"),
                sidebarAttentionItems=raw_result.get("sidebarAttentionItems") or [],
                sidebarSignature=raw_result.get("sidebarSignature"),
                isSidebarOpen=bool(raw_result.get("isSidebarOpen", False)),
                isNewSessionPage=bool(raw_result.get("isNewSessionPage", False)),
                isInputBoxHidden=bool(raw_result.get("isInputBoxHidden", False)),
                isSubagentView=bool(raw_result.get("isSubagentView", False)),
                parentConversationName=raw_result.get("parentConversationName", ""),
                subagentInfoHtml=raw_result.get("subagentInfoHtml"),
                dropdownHtml=raw_result.get("dropdownHtml"),
                dialogHtml=raw_result.get("dialogHtml"),
                settingsHtml=raw_result.get("settingsHtml"),
                activeArtifactUri=raw_result.get("activeArtifactUri"),
                activeFileUri=raw_result.get("activeFileUri"),
                askQuestionHtml=raw_result.get("askQuestionHtml"),
                permissionHtml=raw_result.get("permissionHtml"),
                runningTasksHtml=raw_result.get("runningTasksHtml"),
                scheduledTasksHtml=raw_result.get("scheduledTasksHtml"),
                scheduledTasksDialogHtml=raw_result.get("scheduledTasksDialogHtml"),
                conversationHistoryHtml=raw_result.get("conversationHistoryHtml"),
                btwHtml=raw_result.get("btwHtml"),
                environmentName=raw_result.get("environmentName"),
                branchName=raw_result.get("branchName"),
                modelName=raw_result.get("modelName"),
            )

            # Compute DJB2 composite state hash
            state_hash = compute_composite_hash(snapshot)
            snapshot.hash = state_hash
            snapshot.timestamp = datetime.now(timezone.utc).isoformat()

            self.cached_snapshot = snapshot
            self.last_snapshot_hash = state_hash
            return snapshot
        except Exception as e:
            logger.debug(f"[Snapshot] Capture snapshot failed: {e}")
            return None

    def fire_burst_captures(self, delays: Optional[List[float]] = None) -> None:
        """Fires rapid background recaptures to catch instant DOM changes after actions."""
        delays_to_use = delays if delays is not None else [0.15, 0.4, 0.7]

        for d in delays_to_use:
            async def _burst_step(delay_sec: float):
                try:
                    await asyncio.sleep(delay_sec)
                    snapshot = await self.capture_snapshot()
                    if snapshot:
                        self._broadcast_status({
                            "type": "snapshot",
                            "hash": snapshot.hash,
                            "agentRunning": snapshot.agentRunning,
                            "timestamp": snapshot.timestamp,
                        })
                except Exception as e:
                    logger.debug(f"[BurstCapture] Error: {e}")

            asyncio.create_task(_burst_step(d))

    # --- Interaction Proxies ---

    async def inject_message(self, text: str, append_mode: bool = False) -> Dict[str, Any]:
        """
        Injects text into Lexical editor via synthetic ClipboardEvent paste and triggers send.
        Uses detect-then-execute pattern to prevent double-sends.
        """
        ctx_id = await self.find_editor_context() or 1
        safe_text = json.dumps(text)
        script = build_inject_script(safe_text, append_mode=append_mode)
        res = await self.evaluate_in_context(ctx_id, script)
        return _normalize_action_result(res)

    async def wait_for_editor_image(self, max_wait_ms: int = 3000) -> bool:
        """Polls editor until image or decorator nodes appear."""
        interval = 0.1
        attempts = int(max_wait_ms / (interval * 1000))
        for _ in range(attempts):
            try:
                has_image = await self.evaluate_in_browser(CHECK_EDITOR_IMAGE_SCRIPT)
                if has_image:
                    return True
            except Exception:
                pass
            await asyncio.sleep(interval)
        return False

    async def click_send_button(self) -> Dict[str, Any]:
        """Finds and clicks active send/submit button for image attachments."""
        ctx_id = await self.find_editor_context()
        if not ctx_id:
            res = await self.evaluate_in_browser(CLICK_SEND_BUTTON_SCRIPT)
        else:
            res = await self.evaluate_in_context(ctx_id, CLICK_SEND_BUTTON_SCRIPT)
        return _normalize_action_result(res)

    async def click_element(
        self,
        click_id: str,
        label: Optional[str] = None,
        click_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dispatches click to element tagged with data-ag-click-id across 12 prefix sources."""
        cid = str(click_id or "")
        lbl = str(label or "")

        # Task click
        if cid.startswith("task:"):
            try:
                task_idx = int(cid.split(":")[1])
                script = build_task_click_script(task_idx)
                res = await self.evaluate_across_contexts(script)
                return _normalize_action_result(res)
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # Subagent info click
        if cid.startswith("subinfo:"):
            try:
                script = build_main_click_script(json.dumps(cid), json.dumps(lbl))
                res = await self.evaluate_across_contexts(script)
                return _normalize_action_result(res)
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # Scheduled tasks list click
        if cid.startswith("sched:"):
            try:
                sched_idx = int(cid.split(":")[1])
                script = build_sched_click_script(sched_idx)
                res = await self.evaluate_across_contexts(script)
                if isinstance(res, dict) and (res.get("ok") or res.get("success")):
                    self.fire_burst_captures([0.15, 0.4, 0.7])
                return _normalize_action_result(res)
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # Conversation history click
        if cid.startswith("history:"):
            try:
                hist_idx = int(cid.split(":")[1])
                script = build_history_click_script(hist_idx)
                res = await self.evaluate_across_contexts(script)
                self.fire_burst_captures([0.2, 0.5])
                return _normalize_action_result(res)
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # Scheduled tasks dialog / portal click
        if cid.startswith("scheddlg:"):
            try:
                dlg_idx = int(cid.split(":")[1])
                if dlg_idx >= 100:
                    opt_idx = dlg_idx - 100
                    portal_script = build_sched_portal_click_script(opt_idx)
                    res = await self.evaluate_in_browser(portal_script)
                    if not res:
                        res = await self.evaluate_across_contexts(portal_script)
                    if isinstance(res, dict) and (res.get("ok") or res.get("success")):
                        self.fire_burst_captures([0.15, 0.4, 0.8])
                    return _normalize_action_result(res)

                dlg_script = build_sched_dialog_click_script(dlg_idx, json.dumps(lbl))
                res = await self.evaluate_across_contexts(dlg_script)
                if isinstance(res, dict) and (res.get("ok") or res.get("success")):
                    self.fire_burst_captures([0.15, 0.4, 0.8])
                return _normalize_action_result(res)
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # General click dispatcher (chat, left, right, dropdown, dialog, settings, ask, perm, btw, model, project)
        try:
            click_script = build_main_click_script(json.dumps(cid), json.dumps(lbl))
            res = await self.evaluate_in_browser(click_script)
            if isinstance(res, dict) and (res.get("ok") or res.get("success")):
                source = res.get("source", "")
                if source in ["chat", "dropdown", "dialog", "left", "model", "project", "btw"]:
                    self.fire_burst_captures([0.15, 0.4, 0.7])
            return _normalize_action_result(res)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def stop_generation(self) -> Dict[str, Any]:
        """Halts active agent generation via cancel tooltip button or lucide-square icon."""
        ctx_id = await self.find_editor_context()
        if ctx_id:
            try:
                res = await self.evaluate_in_context(ctx_id, STOP_SCRIPT)
                return _normalize_action_result(res)
            except Exception:
                pass
        res = await self.evaluate_in_browser(STOP_SCRIPT)
        return _normalize_action_result(res)

    async def upload_image(
        self,
        base64_data: str,
        mime_type: str = "image/png",
        filename: str = "photo.png",
    ) -> Dict[str, Any]:
        """Synthesizes File and DataTransfer drop events to inject image into Lexical editor."""
        script = build_upload_image_script(
            json.dumps(base64_data),
            json.dumps(mime_type),
            json.dumps(filename),
        )
        res = await self.evaluate_in_browser(script)
        return _normalize_action_result(res)

    async def type_text(
        self,
        placeholder: Optional[str] = None,
        click_id: Optional[str] = None,
        text: str = "",
    ) -> Dict[str, Any]:
        """Types text into input/textarea element using native value setter bypass."""
        script = build_type_text_script(
            safe_placeholder=json.dumps(placeholder or ""),
            safe_click_id=json.dumps(click_id or ""),
            safe_text=json.dumps(text),
        )
        res = await self.evaluate_across_contexts(script)
        return _normalize_action_result(res)

    async def clear_editor(self) -> Dict[str, Any]:
        """Clears Lexical editor content via lexicalEditor root clear."""
        ctx_id = await self.find_editor_context() or 1
        script = """
        (() => {
          const el = document.querySelector('[data-lexical-editor="true"]');
          if (!el) return { ok: false, reason: 'no_editor' };
          const lex = el.__lexicalEditor;
          if (!lex) return { ok: false, reason: 'no_lexical' };
          lex.update(() => {
            const root = lex.getEditorState()._nodeMap.get('root');
            if (root) root.clear();
          });
          return { ok: true };
        })()
        """
        res = await self.evaluate_in_context(ctx_id, script)
        return _normalize_action_result(res)

    async def type_slash(self) -> Dict[str, Any]:
        """Clears editor and pastes '/' via clipboard event to open command typeahead."""
        ctx_id = await self.find_editor_context() or 1
        script = """
        (async () => {
          const el = document.querySelector('[data-lexical-editor="true"]');
          if (!el) return { ok: false, reason: 'no_editor' };
          const lex = el.__lexicalEditor;
          if (!lex) return { ok: false, reason: 'no_lexical' };
          lex.update(() => {
            const root = lex.getEditorState()._nodeMap.get('root');
            if (root) root.clear();
          });
          el.focus();
          await new Promise(r => setTimeout(r, 80));
          const dt = new DataTransfer();
          dt.setData('text/plain', '/');
          el.dispatchEvent(new ClipboardEvent('paste', {
            clipboardData: dt, bubbles: true, cancelable: true,
          }));
          return { ok: true };
        })()
        """
        res = await self.evaluate_in_context(ctx_id, script)
        return _normalize_action_result(res)

    async def copy_response(self, click_id: str) -> Dict[str, Any]:
        """Intercepts clipboard.writeText while clicking copy button to capture markdown."""
        script = build_copy_response_script(json.dumps(str(click_id)))
        res = await self.evaluate_in_browser(script)
        return _normalize_action_result(res)

    async def navigate_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """Navigates to conversation by UUID from left sidebar."""
        script = build_click_conversation_script(json.dumps(conversation_id))
        res = await self.evaluate_in_browser(script)
        if isinstance(res, dict) and (res.get("ok") or res.get("success")):
            self.fire_burst_captures([0.3, 0.6, 1.2])
        return _normalize_action_result(res)

    async def dismiss_portal(self) -> Dict[str, Any]:
        """Closes dropdowns/dialogs via synthetic Escape keydown."""
        script = "document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }))"
        await self.evaluate_in_browser(script)
        return {"ok": True}

    async def dismiss_scheduled_tasks(self) -> Dict[str, Any]:
        """Navigates back from task detail or list view."""
        res = await self.evaluate_across_contexts(DISMISS_SCHEDULED_TASKS_SCRIPT)
        return _normalize_action_result(res)

    async def dismiss_settings(self) -> Dict[str, Any]:
        """Closes Settings modal overlay."""
        res = await self.evaluate_in_browser(DISMISS_SETTINGS_SCRIPT)
        return _normalize_action_result(res)

    async def history_back(self) -> Dict[str, Any]:
        """Navigates back one entry in Page navigation history."""
        try:
            history = await self._send_command("Page.getNavigationHistory")
            curr_idx = history.get("currentIndex", 0)
            entries = history.get("entries", [])
            if curr_idx > 0:
                prev_entry = entries[curr_idx - 1]
                await self._send_command("Page.navigateToHistoryEntry", {"entryId": prev_entry.get("id")})
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def expand_left_sidebar(self) -> Dict[str, Any]:
        """Expands collapsed left sidebar."""
        res = await self.evaluate_in_browser(EXPAND_LEFT_SIDEBAR_SCRIPT)
        return _normalize_action_result(res)

    async def close_right_sidebar(self) -> Dict[str, Any]:
        """Closes right auxiliary sidebar."""
        res = await self.evaluate_in_browser(CLOSE_RIGHT_SIDEBAR_SCRIPT)
        return _normalize_action_result(res)

    async def toggle_sidebar(self) -> Dict[str, Any]:
        """Toggles right auxiliary sidebar."""
        script = """
        (() => {
          const btn = document.querySelector('[data-testid="toggle-aux-sidebar"]');
          if (btn) btn.click();
        })()
        """
        await self.evaluate_in_browser(script)
        return {"ok": True}

    async def get_right_sidebar(self) -> Dict[str, Any]:
        """Captures right sidebar content on-demand."""
        try:
            html = await self.evaluate_in_browser(RIGHT_SIDEBAR_SCRIPT)
            return {"html": html}
        except Exception as e:
            return {"html": None, "error": str(e)}

    async def proxy_image(self, src: str) -> Dict[str, Any]:
        """Draws image element to HTML5 Canvas and exports base64 data URL."""
        script = build_proxy_image_script(json.dumps(src))
        data_url = await self.evaluate_in_browser(script)
        return {"dataUrl": data_url}

    async def submit_dialog(
        self,
        text: Optional[str] = None,
        click_id: Optional[str] = None,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically injects write-in text into textarea and clicks Submit."""
        if not click_id and click_id != "0":
            return {"ok": False, "error": "click_id is required"}

        if text and text.strip():
            safe_text = json.dumps(text)
            inject_script = f"""
            (() => {{
              const rg = document.querySelector('[role="radiogroup"]') || document.querySelector('[role="group"]');
              if (!rg) return {{ ok: false, reason: 'no_radiogroup' }};
              const ta = rg.querySelector('textarea');
              if (!ta) return {{ ok: false, reason: 'no_textarea' }};
              ta.focus();
              const ns = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
              ns.call(ta, {safe_text});
              ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
              ta.dispatchEvent(new Event('change', {{ bubbles: true }}));
              return {{ ok: true, text: ta.value }};
            }})()
            """
            await self.evaluate_in_browser(inject_script)
            await asyncio.sleep(0.15)

        return await self.click_element(str(click_id), label=label)

    async def execute_script(
        self, script_name: str, args: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Executes any named script from the 31 CDP script catalog."""
        args = args or {}
        name = script_name.lower().replace("-", "_").replace(".js", "")

        # Static scripts
        static_map = {
            "capture": CAPTURE_SCRIPT,
            "right_sidebar": RIGHT_SIDEBAR_SCRIPT,
            "running_tasks": RUNNING_TASKS_SCRIPT,
            "scheduled_tasks": SCHEDULED_TASKS_SCRIPT,
            "scheduled_tasks_dialog": SCHEDULED_TASKS_DIALOG_SCRIPT,
            "conversation_history": CONVERSATION_HISTORY_SCRIPT,
            "stop": STOP_SCRIPT,
            "discover": DISCOVER_SCRIPT,
            "check_editor_image": CHECK_EDITOR_IMAGE_SCRIPT,
            "click_send_button": CLICK_SEND_BUTTON_SCRIPT,
            "expand_left_sidebar": EXPAND_LEFT_SIDEBAR_SCRIPT,
            "dismiss_scheduled_tasks": DISMISS_SCHEDULED_TASKS_SCRIPT,
            "dismiss_settings": DISMISS_SETTINGS_SCRIPT,
            "close_right_sidebar": CLOSE_RIGHT_SIDEBAR_SCRIPT,
            "select_overview_tab": SELECT_OVERVIEW_TAB_SCRIPT,
            "has_visible_editor": HAS_VISIBLE_EDITOR_SCRIPT,
            "open_right_sidebar": OPEN_RIGHT_SIDEBAR_SCRIPT,
        }

        if name in static_map:
            res = await self.evaluate_in_browser(static_map[name])
            if isinstance(res, dict):
                return _normalize_action_result(res)
            return res

        # Dynamic builders
        if name == "inject_message":
            return await self.inject_message(args.get("text", ""), args.get("append_mode", False))
        elif name == "click_task":
            return await self.click_element(f"task:{args.get('task_idx', 0)}")
        elif name == "click_sched":
            return await self.click_element(f"sched:{args.get('sched_idx', 0)}")
        elif name == "click_sched_portal":
            return await self.click_element(f"scheddlg:{100 + args.get('opt_idx', 0)}")
        elif name == "click_sched_dialog":
            return await self.click_element(f"scheddlg:{args.get('dlg_idx', 0)}", label=args.get("label"))
        elif name == "click_main":
            return await self.click_element(args.get("click_id", "chat:0"), label=args.get("label"))
        elif name == "type_text":
            return await self.type_text(args.get("placeholder"), args.get("click_id"), args.get("text", ""))
        elif name == "upload_image":
            return await self.upload_image(args.get("base64_data", ""), args.get("mime_type", "image/png"), args.get("filename", "photo.png"))
        elif name == "click_conversation":
            return await self.navigate_conversation(args.get("conversation_id", ""))
        elif name == "click_history":
            return await self.click_element(f"history:{args.get('hist_idx', 0)}")
        elif name == "copy_response":
            return await self.copy_response(args.get("click_id", "chat:0"))
        elif name == "proxy_image":
            return await self.proxy_image(args.get("src", ""))
        elif name == "capture_listbox":
            return await self.evaluate_in_browser(build_capture_listbox_script())
        elif name == "capture_kebab_menu":
            return await self.evaluate_across_contexts(build_capture_kebab_menu_script())

        raise ValueError(f"Unknown script name: {script_name}")
