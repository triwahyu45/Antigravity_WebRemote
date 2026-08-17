# Push Notifications Module (Milestone M2) — Architecture & Design Report

**Agent**: `explorer_m2_3`  
**Date**: 2026-08-16  
**Milestone**: M2 (Push Notifications Module)  
**Target Module**: `push_notifications.py`  
**Project**: Antigravity WebRemote v6 (Python Port)

---

## Executive Summary
This report provides the complete architectural design, attention state watcher mechanics, multi-client visibility tracking, and testing strategy for `push_notifications.py` in Antigravity WebRemote v6. It strictly adheres to the interface contracts defined in `PROJECT.md` and `SCOPE.md`, matching the feature set and behavioral nuances of the AG2R reference implementation (`_references_antigravity_mobile/ag2r/server.js`), while optimizing for Python 3.12, `asyncio`, and `cryptography` / `pywebpush`.

---

## 1. Complete Class Design for `PushNotificationManager`

### 1.1 Architecture & Concurrency Model
`PushNotificationManager` manages VAPID cryptographic keys, browser push subscriptions, multi-client visibility states, attention state transitions, and background push notification dispatches.

Because `pywebpush.webpush` is a synchronous HTTP network call (wrapping `requests` or `urllib`), calling it directly in FastAPI/asyncio would block the server event loop. To guarantee high throughput and zero UI stuttering, `send_notification` dispatches push requests concurrently via `asyncio.to_thread` or an `asyncio` task pool (`asyncio.gather`).

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PushNotificationManager                         │
├────────────────────────────────────────────────────────────────────────┤
│ - _config_path: Path                                                   │
│ - _subscriptions_path: Path                                            │
│ - _vapid_path: Path                                                    │
│ - _public_key_b64: str (87 chars base64url uncompressed EC point)      │
│ - _private_key_pem: str (PKCS#8 PEM string)                            │
│ - _vapid_claims: Dict[str, str] ({"sub": "mailto:..."})                │
│ - _subscriptions: Dict[str, Dict[str, Any]] (keyed by endpoint)        │
│ - _clients: Dict[str, ClientVisibilityState] (keyed by client_id)      │
│ - _notified_items: Dict[str, float] (dedup map: item_key -> timestamp) │
│ - _previous_agent_running: Optional[bool]                              │
│ - _push_paused: bool                                                   │
├────────────────────────────────────────────────────────────────────────┤
│ + get_public_vapid_key() -> str                                        │
│ + add_subscription(subscription_data: Dict[str, Any]) -> bool         │
│ + remove_subscription(endpoint: str) -> bool                           │
│ + get_subscriptions() -> List[Dict[str, Any]]                          │
│ + set_client_visibility(client_id: str, is_visible: bool) -> None      │
│ + remove_client(client_id: str) -> None                                │
│ + is_any_client_visible(heartbeat_timeout: float = 30.0) -> bool       │
│ + cleanup_stale_clients(timeout_seconds: float = 30.0) -> int          │
│ + check_and_send_attention_notifications(items, agent_running) -> int  │
│ + send_notification(title: str, body: str, data: Optional[Dict]) -> int│
│ + set_push_paused(paused: bool) -> None                                │
│ + is_push_paused() -> bool                                             │
└────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Data Structures & Type Definitions
```python
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import time

@dataclass
class ClientVisibilityState:
    client_id: str
    is_visible: bool
    last_heartbeat: float = 0.0

@dataclass
class PushNotificationPayload:
    title: str
    body: str
    icon: str = "/static/icons/icon-192.png"
    badge: str = "/static/icons/badge-72.png"
    tag: str = "ag2r-attention"
    data: Optional[Dict[str, Any]] = None
    timestamp: int = 0
```

### 1.3 Detailed Method Specifications

#### `__init__(self, config_path: str = "config.json", subscriptions_path: str = "push-subscriptions.json", vapid_path: str = "vapid-keys.json")`
- Initializes paths and in-memory caches.
- Calls `self._init_vapid_keys()` to load or generate EC P-256 keys.
- Calls `self._load_subscriptions()` to load persisted subscriptions from `push-subscriptions.json`.
- Initializes client tracking dict `self._clients = {}`.
- Initializes attention deduplication dict `self._notified_items = {}` and `self._previous_agent_running = None`.

#### `_init_vapid_keys(self) -> None`
- Checks `self._vapid_path` or `config.json` for existing keys.
- If missing or corrupt:
  - Generates EC P-256 private key via `cryptography.hazmat.primitives.asymmetric.ec.generate_private_key(ec.SECP256R1())`.
  - Serializes public key to X9.62 Uncompressed Point (`0x04 || X || Y`, 65 bytes), encoded in base64url without padding (`rstrip(b'=')`).
  - Serializes private key to PKCS#8 PEM string (or base64url raw 32 bytes).
  - Writes `{"publicKey": ..., "privateKey": ...}` to `vapid-keys.json`.
- Configures VAPID claims: `{"sub": "mailto:wahyuai@local.net"}` (or read from `config.json`).

#### `get_public_vapid_key(self) -> str`
- Returns the 87-character unpadded Base64url VAPID public key string.

#### `add_subscription(self, subscription_data: Dict[str, Any]) -> bool`
- Validates payload: requires `endpoint` (str), `keys` (dict), `keys.p256dh` (str), and `keys.auth` (str).
- Stores in `self._subscriptions[endpoint] = subscription_data`.
- Automatically calls `self._save_subscriptions()`.
- Returns `True` on success, `False` on validation error.

#### `remove_subscription(self, endpoint: str) -> bool`
- Removes `endpoint` from `self._subscriptions` if present.
- Calls `self._save_subscriptions()`.
- Returns `True` if removed, `False` if not found.

#### `set_client_visibility(self, client_id: str, is_visible: bool) -> None`
- Updates `self._clients[client_id] = ClientVisibilityState(client_id=client_id, is_visible=is_visible, last_heartbeat=time.time())`.

#### `remove_client(self, client_id: str) -> None`
- Deletes `client_id` from `self._clients` when WebSocket disconnects.

#### `is_any_client_visible(self, heartbeat_timeout: float = 30.0) -> bool`
- First prunes stale clients (`cleanup_stale_clients(heartbeat_timeout)`).
- Returns `True` if any connected client has `is_visible == True`, otherwise `False`.

#### `cleanup_stale_clients(self, timeout_seconds: float = 30.0) -> int`
- Compares `time.time() - client.last_heartbeat > timeout_seconds`.
- Deletes expired clients and returns count of cleaned up clients.

#### `async def send_notification(self, title: str, body: str, data: Optional[Dict[str, Any]] = None) -> int`
- If `self._push_paused` is `True` or `len(self._subscriptions) == 0`: returns 0 immediately.
- Formats payload JSON according to WebPush standard.
- Dispatches push requests across all subscribers concurrently using `asyncio.to_thread(self._sync_send_push, sub, payload_str)`.
- Catches `WebPushException`:
  - If status code is `404` or `410` (Gone): automatically adds endpoint to `stale_endpoints`.
  - If status code is `429` (Rate limit) or `500`: logs warning and retains subscription.
- Removes all `stale_endpoints` and saves updated subscriptions to disk.
- Returns number of successful deliveries.

---

## 2. Attention State Watcher Design

### 2.1 State Transitions & Trigger Conditions
The attention watcher evaluates snapshots and triggers push notifications on three distinct event categories:

| Event Type | CDP/Snapshot Indicator | Notification Title | Notification Body | Target Action / Data |
|---|---|---|---|---|
| **Command Approval** | `item.type == 'command'` in `attentionItems` | `WahyuAI Remote` | `Command approval \| <name>` | `{"type": "command", "conversationId": id}` |
| **User Question** | `item.type == 'question'` in `attentionItems` | `WahyuAI Remote` | `Asking question \| <name>` | `{"type": "question", "conversationId": id}` |
| **Task Completed** | `agent_running` transitions `True -> False` or `item.type == 'completed'` | `WahyuAI Remote` | `Agent task completed` | `{"type": "completed", "conversationId": id}` |

### 2.2 Deduplication & Cooldown Algorithm
1. **Composite Key Tracking**:
   Each attention item is tracked using composite key `f"{item.get('id', '')}:{item.get('type', '')}"`. This differentiates between a command approval and a subsequent question asked within the same conversation session.
2. **Attendance / Pruning Cycle**:
   At each poll tick:
   ```python
   current_keys = {
       f"{it.get('id', '')}:{it.get('type', '')}"
       for it in attention_items
       if it.get('type') != 'completed'
   }
   # Prune resolved items from notified memory
   for key in list(self._notified_items.keys()):
       if key not in current_keys:
           del self._notified_items[key]
   ```
   *Rationale*: When the user acts on a prompt (e.g. clicking Allow in the mobile UI or desktop), the item leaves the DOM. Pruning it from `_notified_items` ensures that if a new prompt appears in the same conversation later, it will be detected as a fresh notification.
3. **Foreground Dedup Registration**:
   If `is_any_client_visible()` is `True`, the new item is **added to `_notified_items`** but network push is skipped.
   *Rationale*: The user is already actively looking at the screen. If they switch tabs 2 seconds later, they must not receive a delayed push for something they already saw in the UI.

### 2.3 `agent_running` Transition Logic
```python
# Startup guard: If _previous_agent_running is None, initialize without firing false completion alert
if self._previous_agent_running is None:
    self._previous_agent_running = agent_running
    return 0

if self._previous_agent_running is True and agent_running is False:
    # Task just completed
    if not self.is_any_client_visible():
        await self.send_notification(
            title="WahyuAI Remote",
            body="Agent task completed",
            data={"type": "completed", "url": "/"}
        )
self._previous_agent_running = agent_running
```

---

## 3. Multi-Client Visibility Tracking Design

### 3.1 Client State Model
Clients communicate their visibility state via WebSocket `/ws/stream` messages:
`{"type": "visibility", "clientId": "uuid-v4", "visible": true}`.

The manager stores client state in a dictionary:
```python
self._clients[client_id] = ClientVisibilityState(
    client_id=client_id,
    is_visible=is_visible,
    last_heartbeat=time.time()
)
```

### 3.2 Heartbeat & Stale Client Cleanup
Clients periodically send pings or visibility updates every 10–15 seconds. If a client unexpectedly drops network connectivity without sending a WebSocket close frame, it remains in memory until cleaned up.

The cleanup algorithm:
```python
def cleanup_stale_clients(self, timeout_seconds: float = 30.0) -> int:
    now = time.time()
    stale_ids = [
        cid for cid, state in self._clients.items()
        if (now - state.last_heartbeat) > timeout_seconds
    ]
    for cid in stale_ids:
        del self._clients[cid]
    return len(stale_ids)
```

### 3.3 Visibility Suppression Truth Table
`is_any_client_visible()` determines whether any push notification should be suppressed:

| Connected Clients | Client 1 State | Client 2 State | Stale (> 30s) | `is_any_client_visible()` | Push Action |
|---|---|---|---|---|---|
| **0 clients** | — | — | — | `False` | **Dispatch Push** |
| **1 client** | `visible=False` (background) | — | No | `False` | **Dispatch Push** |
| **1 client** | `visible=True` (foreground) | — | No | `True` | **Suppress Push** |
| **2 clients** | `visible=False` | `visible=False` | No | `False` | **Dispatch Push** |
| **2 clients** | `visible=True` | `visible=False` | No | `True` | **Suppress Push** |
| **1 client** | `visible=True` (dead tab) | — | Yes (> 30s) | `False` (cleaned up) | **Dispatch Push** |

---

## 4. Test Strategy for `push_notifications.py`

### 4.1 Test Suite Organization (`tests/test_push_notifications.py`)
The unit test suite will use standard Python `unittest` or `pytest` with `unittest.mock` and `tempfile.TemporaryDirectory`.

```
tests/test_push_notifications.py
├── TestVapidKeyManagement (3 tests)
├── TestSubscriptionStorage (5 tests)
├── TestVisibilityTracking (5 tests)
├── TestAttentionWatcher (6 tests)
└── TestWebPushDispatcher (5 tests)
```

### 4.2 Detailed Test Cases & Mocking Patterns

#### Test Group 1: VAPID Key Management
- `test_vapid_key_generation_when_missing`:
  - Verify new key file is created in temp directory.
  - Verify `get_public_vapid_key()` returns an 87-character base64url string.
  - Verify public key starts with uncompressed point prefix (`BN...` / standard EC point).
- `test_vapid_key_persistence_load`:
  - Initialize manager, obtain public key.
  - Create second manager instance pointing to same file; verify public key matches exactly.
- `test_vapid_key_corrupted_file_recovery`:
  - Write invalid JSON to `vapid-keys.json`; verify manager regenerates valid keys without crashing.

#### Test Group 2: Subscription Persistence
- `test_add_valid_subscription`:
  - Add subscription with valid `endpoint`, `keys.p256dh`, `keys.auth`.
  - Verify returns `True`, stored in JSON, and present in `get_subscriptions()`.
- `test_add_invalid_subscription_rejected`:
  - Pass dict missing `endpoint` or `keys`; verify returns `False` and not stored.
- `test_subscription_deduplication_and_update`:
  - Add subscription with endpoint `E1` and auth key `A1`.
  - Add subscription with same endpoint `E1` and new auth key `A2`.
  - Verify total subscription count remains 1 and auth key is updated to `A2`.
- `test_remove_subscription`:
  - Remove existing endpoint -> returns `True`, file updated.
  - Remove non-existent endpoint -> returns `False`.

#### Test Group 3: Visibility Tracking & Suppression
- `test_visibility_state_changes`:
  - Set `client_1` visible -> `is_any_client_visible()` returns `True`.
  - Set `client_1` hidden -> `is_any_client_visible()` returns `False`.
- `test_multi_client_visibility_aggregation`:
  - Set `client_1` hidden, `client_2` visible -> returns `True`.
  - Set `client_2` hidden -> returns `False`.
- `test_client_disconnect_removal`:
  - Set `client_1` visible -> returns `True`.
  - Call `remove_client("client_1")` -> returns `False`.
- `test_heartbeat_timeout_pruning`:
  - Set `client_1` visible with timestamp `t = now - 35s`.
  - Call `is_any_client_visible(heartbeat_timeout=30.0)` -> returns `False` and cleans up `client_1`.

#### Test Group 4: Attention Watcher & Transitions
- `test_agent_running_completion_trigger`:
  - Mock `send_notification`.
  - Call `check_and_send_attention_notifications([], agent_running=True)`.
  - Call `check_and_send_attention_notifications([], agent_running=False)`.
  - Verify `send_notification` called with `"Agent task completed"`.
- `test_attention_command_trigger`:
  - Call with `[{"id": "conv-1", "name": "Run Build", "type": "command"}]`.
  - Verify notification sent with `"Command approval | Run Build"`.
- `test_attention_question_trigger`:
  - Call with `[{"id": "conv-2", "name": "Select Option", "type": "question"}]`.
  - Verify notification sent with `"Asking question | Select Option"`.
- `test_attention_deduplication`:
  - Call with same attention item twice in a row; verify only 1 notification is dispatched.
- `test_attention_pruning_and_reactivation`:
  - Call with item `conv-1` (notified).
  - Call with empty list `[]` (user attended / resolved).
  - Call with item `conv-1` again (new attention item); verify notification is dispatched again.
- `test_visibility_suppression_prevents_network_push`:
  - Set `client_1` visible.
  - Call with new attention item -> verify `send_notification` is NOT dispatched.
  - Set `client_1` hidden.
  - Next tick with same attention item -> verify still NOT dispatched (already recorded as seen).

#### Test Group 5: WebPush Dispatcher (`pywebpush` Mocking)
- `test_successful_webpush_dispatch`:
  - Mock `pywebpush.webpush` to return HTTP 201 Created.
  - Call `send_notification(title="Test", body="Hello")`.
  - Verify payload formatted properly with title, body, icon, badge, tag.
- `test_auto_prune_on_410_gone`:
  - Mock `pywebpush.webpush` raising `WebPushException` with response status 410.
  - Call `send_notification()`.
  - Verify that the subscription is automatically deleted from in-memory dict and disk.
- `test_auto_prune_on_404_not_found`:
  - Mock `WebPushException` status 404 -> verify subscription deleted.
- `test_transient_error_retention`:
  - Mock `WebPushException` status 429 / 500 or `requests.exceptions.ConnectionError`.
  - Call `send_notification()`.
  - Verify subscription is NOT deleted from disk.

---

## 5. Implementation Blueprint

### 5.1 Proposed Code Structure for `push_notifications.py`
```python
"""
Antigravity WebRemote v6 - Push Notifications Manager
Handles VAPID keys, Web Push subscriptions, visibility tracking, and attention alerts.
"""

import os
import json
import time
import base64
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Set

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None
    class WebPushException(Exception):
        pass

logger = logging.getLogger("PushNotifications")

@dataclass
class ClientVisibilityState:
    client_id: str
    is_visible: bool
    last_heartbeat: float

class PushNotificationManager:
    def __init__(
        self,
        config_path: str = "config.json",
        subscriptions_path: str = "push-subscriptions.json",
        vapid_path: str = "vapid-keys.json",
    ):
        self.config_path = Path(config_path)
        self.subscriptions_path = Path(subscriptions_path)
        self.vapid_path = Path(vapid_path)
        
        self._public_key_b64: str = ""
        self._private_key_pem: str = ""
        self._vapid_claims: Dict[str, str] = {"sub": "mailto:wahyuai@local.net"}
        
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._clients: Dict[str, ClientVisibilityState] = {}
        self._notified_items: Dict[str, float] = {}
        self._previous_agent_running: Optional[bool] = None
        self._push_paused: bool = False
        
        self._init_vapid_keys()
        self._load_subscriptions()

    def _init_vapid_keys(self) -> None:
        if self.vapid_path.exists():
            try:
                with open(self.vapid_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._public_key_b64 = data.get("publicKey", "")
                    self._private_key_pem = data.get("privateKey", "")
                if self._public_key_b64 and self._private_key_pem:
                    return
            except Exception as e:
                logger.warning(f"Failed to read VAPID keys: {e}, generating new keys.")

        # Generate EC P-256 Keypair
        priv_key = ec.generate_private_key(ec.SECP256R1())
        pub_key = priv_key.public_key()
        
        # Raw uncompressed point: 0x04 || X || Y (65 bytes) -> urlsafe b64
        raw_pub = pub_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        self._public_key_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode("utf-8")
        
        self._private_key_pem = priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode("utf-8")

        # Persist
        try:
            self.vapid_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.vapid_path, "w", encoding="utf-8") as f:
                json.dump({"publicKey": self._public_key_b64, "privateKey": self._private_key_pem}, f, indent=2)
            logger.info("Generated and saved new VAPID keys.")
        except Exception as e:
            logger.error(f"Failed to save VAPID keys: {e}")

    def _load_subscriptions(self) -> None:
        if not self.subscriptions_path.exists():
            return
        try:
            with open(self.subscriptions_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, list):
                    # List of [endpoint, sub_dict] or list of sub_dict
                    for item in raw:
                        if isinstance(item, list) and len(item) == 2:
                            self._subscriptions[item[0]] = item[1]
                        elif isinstance(item, dict) and "endpoint" in item:
                            self._subscriptions[item["endpoint"]] = item
                elif isinstance(raw, dict):
                    self._subscriptions = raw
            logger.info(f"Loaded {len(self._subscriptions)} push subscriptions.")
        except Exception as e:
            logger.warning(f"Could not load push subscriptions: {e}")

    def _save_subscriptions(self) -> None:
        try:
            self.subscriptions_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.subscriptions_path, "w", encoding="utf-8") as f:
                json.dump(self._subscriptions, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save push subscriptions: {e}")

    def get_public_vapid_key(self) -> str:
        return self._public_key_b64

    def add_subscription(self, subscription_data: Dict[str, Any]) -> bool:
        endpoint = subscription_data.get("endpoint")
        keys = subscription_data.get("keys", {})
        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            return False
        self._subscriptions[endpoint] = subscription_data
        self._save_subscriptions()
        return True

    def remove_subscription(self, endpoint: str) -> bool:
        if endpoint in self._subscriptions:
            del self._subscriptions[endpoint]
            self._save_subscriptions()
            return True
        return False

    def get_subscriptions(self) -> List[Dict[str, Any]]:
        return list(self._subscriptions.values())

    def set_client_visibility(self, client_id: str, is_visible: bool) -> None:
        self._clients[client_id] = ClientVisibilityState(
            client_id=client_id,
            is_visible=is_visible,
            last_heartbeat=time.time()
        )

    def remove_client(self, client_id: str) -> None:
        if client_id in self._clients:
            del self._clients[client_id]

    def cleanup_stale_clients(self, timeout_seconds: float = 30.0) -> int:
        now = time.time()
        stale_ids = [
            cid for cid, s in self._clients.items()
            if (now - s.last_heartbeat) > timeout_seconds
        ]
        for cid in stale_ids:
            del self._clients[cid]
        return len(stale_ids)

    def is_any_client_visible(self, heartbeat_timeout: float = 30.0) -> bool:
        self.cleanup_stale_clients(heartbeat_timeout)
        return any(s.is_visible for s in self._clients.values())

    def set_push_paused(self, paused: bool) -> None:
        self._push_paused = bool(paused)

    def is_push_paused(self) -> bool:
        return self._push_paused

    async def check_and_send_attention_notifications(
        self, attention_items: List[Dict[str, Any]], agent_running: bool
    ) -> int:
        if self._push_paused:
            return 0

        notifications_sent = 0
        active_items = [it for it in attention_items if it.get("type") != "completed"]
        current_keys = {f"{it.get('id', '')}:{it.get('type', '')}" for it in active_items}

        # Clear items no longer active (user attended to them)
        for key in list(self._notified_items.keys()):
            if key not in current_keys:
                del self._notified_items[key]

        # Check new attention items
        for item in active_items:
            item_id = item.get("id", "")
            item_type = item.get("type", "command")
            key = f"{item_id}:{item_type}"
            if key in self._notified_items:
                continue

            self._notified_items[key] = time.time()
            if self.is_any_client_visible():
                continue  # Recorded as notified, suppressed from push

            name = (item.get("name") or "").strip()
            if item_type == "question":
                body = f"Asking question | {name}" if name else "Asking question"
            else:
                body = f"Command approval | {name}" if name else "Command approval"

            data = {"conversationId": item_id, "type": item_type, "url": f"/?conversationId={item_id}"}
            notifications_sent += await self.send_notification(
                title="WahyuAI Remote", body=body, data=data
            )

        # Check agent_running transition
        if self._previous_agent_running is True and agent_running is False:
            if not self.is_any_client_visible():
                notifications_sent += await self.send_notification(
                    title="WahyuAI Remote",
                    body="Agent task completed",
                    data={"type": "completed", "url": "/"}
                )
        self._previous_agent_running = agent_running

        return notifications_sent

    def _sync_send_single_push(self, sub: Dict[str, Any], payload_str: str) -> Optional[str]:
        if webpush is None:
            logger.warning("pywebpush not installed, skipping push dispatch.")
            return None
        try:
            webpush(
                subscription_info=sub,
                data=payload_str,
                vapid_private_key=self._private_key_pem,
                vapid_claims=self._vapid_claims,
                timeout=10,
            )
            return None
        except WebPushException as ex:
            status = getattr(ex.response, "status_code", None) if hasattr(ex, "response") and ex.response else None
            if status in (404, 410):
                logger.info(f"Subscription {sub.get('endpoint', '')[:50]} gone ({status}), marking stale.")
                return sub.get("endpoint")
            logger.warning(f"WebPushException {status}: {ex}")
            return None
        except Exception as ex:
            logger.warning(f"Push send error: {ex}")
            return None

    async def send_notification(
        self, title: str, body: str, data: Optional[Dict[str, Any]] = None
    ) -> int:
        if self._push_paused or not self._subscriptions:
            return 0

        payload = {
            "title": title,
            "body": body,
            "icon": data.get("icon", "/static/icons/icon-192.png") if data else "/static/icons/icon-192.png",
            "badge": data.get("badge", "/static/icons/badge-72.png") if data else "/static/icons/badge-72.png",
            "tag": data.get("tag", "ag2r-attention") if data else "ag2r-attention",
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        payload_str = json.dumps(payload)

        stale_endpoints: Set[str] = set()
        delivered = 0

        tasks = [
            asyncio.to_thread(self._sync_send_single_push, sub, payload_str)
            for sub in list(self._subscriptions.values())
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for stale_ep in results:
            if stale_ep:
                stale_endpoints.add(stale_ep)
            else:
                delivered += 1

        if stale_endpoints:
            for ep in stale_endpoints:
                self._subscriptions.pop(ep, None)
            self._save_subscriptions()

        return delivered
```

---

## 6. Conclusion
The designed `PushNotificationManager` satisfies all contractual and operational requirements for Milestone M2. Concurrency is safely decoupled from the FastAPI asyncio loop, attention transitions and `agent_running` state are robustly tracked without duplicate notification spam, multi-client visibility suppresses alerts when tabs are active, and dead clients or expired push endpoints (410/404) are automatically purged.
