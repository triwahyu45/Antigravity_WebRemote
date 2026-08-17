"""
push_notifications.py - Web Push Notifications Module for Antigravity WebRemote v6
===================================================================================

Handles VAPID EC P-256 keypair management, persistent browser push subscriptions,
client visibility tracking, attention state transition monitoring, and asynchronous
non-blocking Web Push notification delivery via pywebpush.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid, b64urlencode

try:
    import pywebpush
    from pywebpush import WebPushException
except ImportError:
    pywebpush = None  # type: ignore

    class WebPushException(Exception):  # type: ignore
        """Fallback WebPushException if pywebpush is unavailable."""
        def __init__(self, message: str, response: Optional[Any] = None) -> None:
            super().__init__(message)
            self.response = response
            self.status_code = getattr(response, "status_code", None) if response else None


logger = logging.getLogger("PushNotifications")


@dataclass
class ClientVisibilityState:
    """Represents the foreground/background visibility state of a connected client."""
    client_id: str
    is_visible: bool
    last_heartbeat: float = 0.0


def _extract_status_code(ex: Exception) -> Optional[int]:
    """Safely extracts HTTP status code from WebPushException or generic response."""
    if hasattr(ex, "response") and ex.response is not None:
        if isinstance(ex.response, int):
            return ex.response
        if hasattr(ex.response, "status_code"):
            return getattr(ex.response, "status_code")
        if hasattr(ex.response, "statusCode"):
            return getattr(ex.response, "statusCode")
    if hasattr(ex, "status_code") and isinstance(getattr(ex, "status_code"), int):
        return getattr(ex, "status_code")
    if hasattr(ex, "statusCode") and isinstance(getattr(ex, "statusCode"), int):
        return getattr(ex, "statusCode")
    return None


class PushNotificationManager:
    """
    Manages VAPID keys, browser push subscriptions, client visibility tracking,
    and asynchronous Web Push delivery via pywebpush.
    """

    def __init__(
        self,
        config_path: str = "config.json",
        subscriptions_path: str = "push-subscriptions.json",
        vapid_path: str = "vapid-keys.json",
        vapid_email: str = "mailto:wahyuai@local.net",
    ) -> None:
        self.config_path = Path(config_path)
        self.subscriptions_path = Path(subscriptions_path)
        self.vapid_path = Path(vapid_path)
        self.vapid_email = vapid_email

        self._lock = threading.Lock()
        self.subscriptions: Dict[str, Dict[str, Any]] = {}
        self.clients: Dict[str, ClientVisibilityState] = {}
        self.notified_items: Dict[str, float] = {}
        self.previous_agent_running: Optional[bool] = None
        self.push_paused: bool = False

        self.vapid: Optional[Vapid] = None
        self.public_vapid_key: str = ""
        self._private_key_pem: str = ""
        self._vapid_claims: Dict[str, str] = {"sub": self.vapid_email}

        self._init_vapid_keys()
        self._load_subscriptions()

    def _validate_and_create_vapid(self, pub: Any, priv: Any) -> Optional[Tuple[str, str, Vapid]]:
        """Validates public/private key format and curve. Returns (pub, priv, vapid_obj) or None."""
        if not isinstance(pub, str) or not isinstance(priv, str):
            return None
        pub = pub.strip()
        priv = priv.strip()
        # VAPID public key must be 86, 87, or 88 chars (uncompressed P-256 base64url)
        if len(pub) not in (86, 87, 88):
            return None

        # Validate private key and curve
        try:
            if "-----BEGIN" in priv:
                key_obj = serialization.load_pem_private_key(priv.encode("utf-8"), password=None)
                if not isinstance(key_obj, ec.EllipticCurvePrivateKey):
                    return None
                if not isinstance(key_obj.curve, ec.SECP256R1):
                    return None
                v = Vapid.from_pem(priv.encode("utf-8"))
            else:
                v = Vapid.from_string(priv)
                if not hasattr(v, "private_key") or not isinstance(v.private_key, ec.EllipticCurvePrivateKey):
                    return None
                if not isinstance(v.private_key.curve, ec.SECP256R1):
                    return None
            return pub, priv, v
        except Exception:
            return None

    def _init_vapid_keys(self) -> None:
        """Loads existing VAPID keypair or generates a new NIST P-256 keypair."""
        # 1. Try loading from vapid_path
        if self.vapid_path.exists():
            try:
                with open(self.vapid_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        res = self._validate_and_create_vapid(data.get("publicKey"), data.get("privateKey"))
                        if res is not None:
                            self.public_vapid_key, self._private_key_pem, self.vapid = res
                            logger.info("Loaded existing VAPID keys from %s", self.vapid_path)
                            return
            except Exception as e:
                logger.warning("Failed reading %s, regenerating keys: %s", self.vapid_path, e)

        # 2. Try loading from config_path
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if isinstance(cfg, dict):
                        v_cfg = cfg.get("vapid", {})
                        if isinstance(v_cfg, dict):
                            res = self._validate_and_create_vapid(v_cfg.get("publicKey"), v_cfg.get("privateKey"))
                            if res is not None:
                                self.public_vapid_key, self._private_key_pem, self.vapid = res
                                logger.info("Loaded existing VAPID keys from %s", self.config_path)
                                return
            except Exception as e:
                logger.warning("Failed reading VAPID from %s: %s", self.config_path, e)

        # 3. Generate fresh EC P-256 (secp256r1) keypair
        priv_key = ec.generate_private_key(ec.SECP256R1())
        pub_key = priv_key.public_key()

        # 65-byte uncompressed point (0x04 || X || Y) base64url encoded without padding (87 chars)
        raw_pub = pub_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        self.public_vapid_key = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode("ascii")

        # PKCS#8 PEM private key
        self._private_key_pem = priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        key_data = {
            "publicKey": self.public_vapid_key,
            "privateKey": self._private_key_pem,
        }

        # Persist to vapid_path using unique temporary file to prevent Windows file locking collisions
        unique_id = f"{os.getpid()}_{uuid.uuid4().hex[:8]}_{time.time_ns()}"
        tmp_path = f"{self.vapid_path}.{unique_id}.tmp"
        try:
            self.vapid_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(key_data, f, indent=2)
            os.replace(tmp_path, str(self.vapid_path))
            self.vapid = Vapid.from_pem(self._private_key_pem.encode("utf-8"))
            logger.info("Generated and saved new VAPID keys to %s", self.vapid_path)
        except Exception as e:
            logger.error("Failed saving VAPID keys to disk: %s", e)
            self.vapid = Vapid(priv_key)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    @staticmethod
    def _is_valid_sub_entry(sub: Any) -> bool:
        """Validates that a subscription entry contains an endpoint string and valid keys."""
        if not isinstance(sub, dict):
            return False
        ep = sub.get("endpoint")
        if not ep or not isinstance(ep, str) or not ep.startswith("http"):
            return False
        keys = sub.get("keys")
        if not keys or not isinstance(keys, dict):
            return False
        p256dh = keys.get("p256dh")
        auth = keys.get("auth")
        if not isinstance(p256dh, str) or not isinstance(auth, str) or not p256dh.strip() or not auth.strip():
            return False
        return True

    def _load_subscriptions(self) -> None:
        """Loads push subscriptions from disk, gracefully filtering corrupted entries."""
        if not self.subscriptions_path.exists():
            self.subscriptions = {}
            return
        try:
            with open(self.subscriptions_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                cleaned: Dict[str, Dict[str, Any]] = {}
                if isinstance(raw, dict):
                    for ep, val in raw.items():
                        if self._is_valid_sub_entry(val):
                            cleaned[val["endpoint"]] = val
                elif isinstance(raw, list):
                    for item in raw:
                        if self._is_valid_sub_entry(item):
                            cleaned[item["endpoint"]] = item
                        elif isinstance(item, list) and len(item) == 2 and self._is_valid_sub_entry(item[1]):
                            cleaned[item[1]["endpoint"]] = item[1]
                self.subscriptions = cleaned
            logger.info("Loaded %d push subscription(s) from disk", len(self.subscriptions))
        except Exception as e:
            logger.warning("Failed loading subscriptions from %s: %s", self.subscriptions_path, e)
            self.subscriptions = {}

    def _save_subscriptions(self) -> None:
        """Atomically persists subscriptions to disk using unique tmp file."""
        with self._lock:
            unique_id = f"{os.getpid()}_{uuid.uuid4().hex[:8]}_{time.time_ns()}"
            tmp_path = f"{self.subscriptions_path}.{unique_id}.tmp"
            try:
                self.subscriptions_path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self.subscriptions, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, str(self.subscriptions_path))
            except Exception as e:
                logger.error("Failed saving subscriptions to %s: %s", self.subscriptions_path, e)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

    def get_public_vapid_key(self) -> str:
        """Returns the 87-character unpadded Base64url VAPID public key string."""
        return self.public_vapid_key

    def add_subscription(self, subscription_data: Dict[str, Any]) -> bool:
        """
        Registers or updates a browser push subscription.
        Validates structure and atomically saves to disk.
        """
        if not isinstance(subscription_data, dict):
            return False

        endpoint = subscription_data.get("endpoint")
        keys = subscription_data.get("keys")

        if not endpoint or not isinstance(endpoint, str) or not endpoint.startswith("http"):
            return False
        if not keys or not isinstance(keys, dict):
            return False
        p256dh = keys.get("p256dh")
        auth = keys.get("auth")
        if not isinstance(p256dh, str) or not isinstance(auth, str) or not p256dh.strip() or not auth.strip():
            return False

        with self._lock:
            self.subscriptions[endpoint] = {
                **subscription_data,
                "updatedAt": time.time(),
            }
        self._save_subscriptions()
        logger.info("Registered push subscriber (%d total)", len(self.subscriptions))
        return True

    def remove_subscription(self, endpoint: str) -> bool:
        """Removes a push subscription by endpoint URL."""
        if not endpoint:
            return False
        with self._lock:
            if endpoint in self.subscriptions:
                del self.subscriptions[endpoint]
            else:
                return False
        self._save_subscriptions()
        logger.info("Removed push subscriber (%d remaining)", len(self.subscriptions))
        return True

    def get_subscriptions(self) -> List[Dict[str, Any]]:
        """Returns all currently active push subscriptions."""
        with self._lock:
            return list(self.subscriptions.values())

    def set_client_visibility(self, client_id: str, is_visible: bool) -> None:
        """Records or updates client visibility status with current heartbeat timestamp."""
        if not client_id:
            return
        self.clients[client_id] = ClientVisibilityState(
            client_id=client_id,
            is_visible=bool(is_visible),
            last_heartbeat=time.time(),
        )

    def remove_client(self, client_id: str) -> None:
        """Removes client entry on disconnect."""
        self.clients.pop(client_id, None)

    def cleanup_stale_clients(self, timeout_seconds: float = 30.0) -> int:
        """Prunes client entries whose heartbeat is older than timeout_seconds."""
        now = time.time()
        stale_ids = [
            cid for cid, state in list(self.clients.items())
            if (now - state.last_heartbeat) > timeout_seconds
        ]
        for cid in stale_ids:
            self.clients.pop(cid, None)
        return len(stale_ids)

    def is_any_client_visible(self, heartbeat_timeout: float = 30.0) -> bool:
        """
        Returns True if any connected client currently has an active, visible tab
        within the heartbeat timeout window.
        """
        self.cleanup_stale_clients(heartbeat_timeout)
        return any(client.is_visible for client in self.clients.values())

    def set_push_paused(self, paused: bool) -> None:
        """Pauses or resumes push notification delivery."""
        self.push_paused = bool(paused)

    def is_push_paused(self) -> bool:
        """Returns True if push delivery is paused."""
        return self.push_paused

    def _sync_send_single_push(self, sub: Dict[str, Any], payload_str: str) -> Tuple[bool, Optional[str]]:
        """
        Synchronously delivers a push notification to a single subscriber.
        Executed in a background thread to prevent blocking the event loop.
        """
        if not isinstance(sub, dict):
            return False, None

        endpoint = sub.get("endpoint", "")
        if not endpoint or not isinstance(endpoint, str):
            return False, None

        if pywebpush is None or not hasattr(pywebpush, "webpush"):
            logger.warning("pywebpush not installed, skipping network push delivery.")
            return True, None

        try:
            pywebpush.webpush(
                subscription_info=sub,
                data=payload_str,
                vapid_private_key=self.vapid or self._private_key_pem,
                vapid_claims=self._vapid_claims,
                ttl=86400,
                timeout=5.0,
            )
            return True, None
        except WebPushException as ex:
            status = _extract_status_code(ex)
            if status in (404, 410):
                logger.info("Subscription expired or gone (HTTP %s), pruning: %s", status, endpoint[:40])
                return False, endpoint
            elif status == 429:
                logger.warning("WebPush rate limited (HTTP 429) for %s: %s", endpoint[:40], ex)
                return False, None
            else:
                logger.warning("WebPushException (HTTP %s) for %s: %s", status, endpoint[:40], ex)
                return False, None
        except Exception as ex:
            logger.error("Failed sending push to %s: %s", endpoint[:40], ex)
            return False, None

    async def send_notification(
        self,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Dispatches push notification payload to all active subscribers in parallel
        using worker threads. Prunes expired endpoints automatically.
        """
        if self.push_paused:
            logger.debug("Push notifications are paused, skipping send.")
            return 0

        with self._lock:
            subs = list(self.subscriptions.values())

        if not subs:
            return 0

        payload = {
            "title": title,
            "body": body,
            "icon": (data and data.get("icon")) or "/static/icons/icon-192.png",
            "badge": (data and data.get("badge")) or "/static/icons/badge-72.png",
            "tag": (data and data.get("tag")) or f"ag2r-{data.get('conversationId', 'alert') if data else 'alert'}",
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        if data:
            if "conversationId" in data and "conversationId" not in payload:
                payload["conversationId"] = data["conversationId"]
            if "url" in data and "url" not in payload:
                payload["url"] = data["url"]

        payload_str = json.dumps(payload, ensure_ascii=False)

        tasks = [
            asyncio.to_thread(self._sync_send_single_push, sub, payload_str)
            for sub in subs
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        delivered = 0
        stale_endpoints: Set[str] = set()

        for success, stale_ep in results:
            if success:
                delivered += 1
            if stale_ep:
                stale_endpoints.add(stale_ep)

        if stale_endpoints:
            with self._lock:
                for ep in stale_endpoints:
                    self.subscriptions.pop(ep, None)
            self._save_subscriptions()
            logger.info("Pruned %d stale subscription(s)", len(stale_endpoints))

        logger.info("WebPush delivered to %d / %d subscriber(s)", delivered, len(subs))
        return delivered

    async def check_and_send_attention_notifications(
        self,
        attention_items: List[Dict[str, Any]],
        agent_running: bool,
        conversation_name: str = "",
        conversation_id: str = "",
    ) -> int:
        """
        Evaluates attention items and agent execution status transitions,
        applies suppression and deduplication, and triggers push alerts.
        """
        if self.push_paused:
            return 0

        total_sent = 0
        conv_id = conversation_id.strip() if conversation_id else ""

        # 0. Safely filter for dict instances
        valid_items = [it for it in (attention_items or []) if isinstance(it, dict)]
        active_items = [it for it in valid_items if it.get("type") != "completed"]
        completed_items = [it for it in valid_items if it.get("type") == "completed"]

        # Form deduplication keys
        current_active_keys = {
            f"{conv_id}:{str(it.get('id') or conv_id)}:{str(it.get('type') or 'command')}"
            if conv_id else f"{str(it.get('id') or '')}:{str(it.get('type') or 'command')}"
            for it in active_items
        }
        current_completed_keys = {
            f"{conv_id}:{str(it.get('id') or conv_id)}:completed"
            if conv_id else f"{str(it.get('id') or '')}:completed"
            for it in completed_items
        }
        all_current_keys = current_active_keys | current_completed_keys

        # 1. Prune resolved items from notified memory with conversation scoping
        if conv_id:
            conv_prefix = f"{conv_id}:"
            for key in list(self.notified_items.keys()):
                if key.startswith(conv_prefix) and key not in all_current_keys:
                    del self.notified_items[key]
        else:
            for key in list(self.notified_items.keys()):
                if key not in all_current_keys:
                    del self.notified_items[key]

        # 2. Check active attention items (questions & command approvals)
        for item in active_items:
            item_id = str(item.get("id") or conv_id or "")
            item_type = str(item.get("type") or "command")
            item_name = str(item.get("name") or conversation_name or "").strip()
            item_text = str(item.get("text") or "").strip()

            key = f"{conv_id}:{item_id}:{item_type}" if conv_id else f"{item_id}:{item_type}"
            if key in self.notified_items:
                continue

            self.notified_items[key] = time.time()

            # If any client is actively viewing the UI, suppress delivery
            if self.is_any_client_visible():
                logger.debug("Suppressed push alert for %s (client tab visible)", key)
                continue

            display_title = item_name or item_text
            if item_type == "question":
                body = f"Asking question | {display_title}" if display_title else "Agent is asking a question"
            else:
                body = f"Command approval | {display_title}" if display_title else "Command approval requested"

            data = {
                "conversationId": item_id or conv_id,
                "type": item_type,
                "url": f"/?sidebar=open&conversationId={item_id or conv_id}" if (item_id or conv_id) else "/?sidebar=open",
            }
            sent = await self.send_notification(
                title="WahyuAI Remote",
                body=body,
                data=data,
            )
            total_sent += sent

        completed_notification_fired = False

        # 3. Check explicit completed items in attention list
        for comp_item in completed_items:
            comp_id = str(comp_item.get("id") or conv_id or "")
            comp_key = f"{conv_id}:{comp_id}:completed" if conv_id else f"{comp_id}:completed"
            if comp_key not in self.notified_items:
                self.notified_items[comp_key] = time.time()
                completed_notification_fired = True
                if not self.is_any_client_visible():
                    comp_name = str(comp_item.get("name") or comp_item.get("text") or conversation_name or "").strip()
                    body = f"Agent task completed | {comp_name}" if comp_name else "Agent task completed"
                    sent = await self.send_notification(
                        title="WahyuAI Remote",
                        body=body,
                        data={"type": "completed", "conversationId": comp_id or conv_id, "url": "/"},
                    )
                    total_sent += sent

        # 4. Check agent_running state transition (True -> False)
        if self.previous_agent_running is None:
            # Startup guard: initialize previous state without false alarms
            self.previous_agent_running = agent_running
        else:
            if self.previous_agent_running is True and agent_running is False:
                # Agent just finished running
                # Avoid double notification if a completion notification was already fired in Section 3
                if not completed_notification_fired and not self.is_any_client_visible():
                    body = f"Agent task completed | {conversation_name}" if conversation_name else "Agent task completed"
                    sent = await self.send_notification(
                        title="WahyuAI Remote",
                        body=body,
                        data={"type": "completed", "conversationId": conv_id, "url": "/"},
                    )
                    total_sent += sent
            self.previous_agent_running = agent_running

        return total_sent
