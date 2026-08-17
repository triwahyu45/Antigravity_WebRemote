# Investigation Report: AG2R Push Notification Architecture & Milestone M2 Design

**Explorer Agent**: `explorer_m2_1`  
**Milestone**: M2 — Push Notifications Module (`push_notifications.py`)  
**Target Project**: Local AI Mobile Agent (Antigravity WebRemote v6)  
**Date**: 2026-08-17  

---

## 1. Executive Summary

This report documents the end-to-end investigation of the Web Push notification system from the reference AG2R implementation (`_references_antigravity_mobile/ag2r`) and maps its exact specifications to the Python implementation required for Milestone M2 (`push_notifications.py`).

Key findings include:
1. **VAPID Key Handling**: AG2R uses NIST P-256 (secp256r1) EC keys. The public key is an uncompressed 65-byte point (`0x04 || X || Y`) base64url-encoded without padding (87 chars). The private key is a 32-byte scalar base64url-encoded (43 chars). `pywebpush` and Python's `cryptography` library natively interoperate with this exact format.
2. **Payload Specification**: The Service Worker (`sw.js`) expects a JSON payload containing `title`, `body`, `tag`, `icon`, `badge`, and `data: { url, conversationId }`. On click, `sw.js` focuses an existing open window and dispatches a `postMessage` (`navigate-conversation` or `open-sidebar`), or opens a new window with `?sidebar=open&conversationId=<id>`.
3. **Client Visibility & Suppression**: Active tabs report visibility (`document.visibilityState === 'visible'`) over WebSocket `/ws/stream`. When `visibleClients > 0`, notifications are suppressed from delivery, but new attention items are still tracked in `notifiedConversations` so backgrounding the tab does not trigger duplicate spam for already-seen items.
4. **Attention Triggers**: Sidebar attention items (`question` and `command`) and agent completion triggers (`agentRunning: false` / `completed`) generate distinct notification titles and bodies. Deduping tracks conversation IDs until resolved.

---

## 2. 5-Component Investigation Analysis

### Component 1: Observation

#### Observation 1.1: VAPID Key Generation, Format, and Storage in AG2R
- **Source**: `_references_antigravity_mobile/ag2r/server.js:105-131`
- **Verbatim Code**:
  ```javascript
  const VAPID_KEYS_PATH = getConfigPath('vapid-keys.json');
  const LEGACY_VAPID_KEYS_PATH = path.join(__dirname, 'vapid-keys.json');
  const PUSH_SUBS_PATH = getConfigPath('push-subscriptions.json');
  const pushSubscriptions = new Map(); // endpoint → { ...PushSubscription, origin }

  function initVapid() {
    ensureConfigDir();
    let keys;
    try {
      keys = JSON.parse(fs.readFileSync(VAPID_KEYS_PATH, 'utf-8'));
    } catch {
      try {
        keys = JSON.parse(fs.readFileSync(LEGACY_VAPID_KEYS_PATH, 'utf-8'));
        fs.writeFileSync(VAPID_KEYS_PATH, JSON.stringify(keys, null, 2));
      } catch {
        keys = webpush.generateVAPIDKeys();
        fs.writeFileSync(VAPID_KEYS_PATH, JSON.stringify(keys, null, 2));
      }
    }
    const email = process.env.VAPID_EMAIL || 'mailto:ag2r@omercanyy.com';
    webpush.setVapidDetails(email, keys.publicKey, keys.privateKey);
    return keys;
  }
  ```
- **Endpoints**:
  - `server.js:1756-1758`:
    ```javascript
    app.get('/push/vapid-public-key', (req, res) => {
      res.json({ publicKey: vapidKeys.publicKey });
    });
    ```

#### Observation 1.2: Client Subscription & Public Key Conversion in `app.js`
- **Source**: `_references_antigravity_mobile/ag2r/public/js/app.js:3070-3097`
- **Verbatim Code**:
  ```javascript
  async function subscribePush(registration) {
    const res = await fetchAPI('/push/vapid-public-key');
    const { publicKey } = await res.json();

    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });

    await sendSubscription(subscription);
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(base64);
    const arr = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
    return arr;
  }
  ```

#### Observation 1.3: Subscription Storage and Origin Tracking in `server.js`
- **Source**: `_references_antigravity_mobile/ag2r/server.js:1760-1783`
- **Verbatim Code**:
  ```javascript
  app.post('/push/subscribe', (req, res) => {
    const subscription = req.body;
    if (!subscription?.endpoint) {
      return res.status(400).json({ error: 'Invalid subscription' });
    }
    const origin = (req.get('origin') || req.get('referer') || '').replace(/\/$/, '');
    pushSubscriptions.set(subscription.endpoint, { ...subscription, origin });
    saveSubscriptions();
    track('push_registered', { subscriberCount: pushSubscriptions.size });
    res.json({ ok: true });
  });

  app.post('/push/unsubscribe', (req, res) => {
    const { endpoint } = req.body;
    if (endpoint) {
      pushSubscriptions.delete(endpoint);
      saveSubscriptions();
    }
    track('push_unregistered', { subscriberCount: pushSubscriptions.size });
    res.json({ ok: true });
  });
  ```

#### Observation 1.4: Push Notification Delivery & Error Handling in `server.js`
- **Source**: `_references_antigravity_mobile/ag2r/server.js:186-220`
- **Verbatim Code**:
  ```javascript
  async function sendPushToAll(payload) {
    if (pushSubscriptions.size === 0) {
      log('Push', 'No subscribers — skipping send');
      return;
    }
    log('Push', `Sending to ${pushSubscriptions.size} subscriber(s): ${payload.body}`);
    const stale = [];
    let sent = 0;
    for (const [endpoint, sub] of pushSubscriptions) {
      const base = sub.origin || TUNNEL_URL || `https://localhost:${PORT}`;
      const params = new URLSearchParams({ sidebar: 'open' });
      if (payload.conversationId) params.set('conversationId', payload.conversationId);
      const url = base + (base.includes('?') ? '&' : '?') + params.toString();
      const body = JSON.stringify({ ...payload, url, icon: appIconPath });
      try {
        await webpush.sendNotification(sub, body);
        sent++;
      } catch (err) {
        if (err.statusCode === 410) {
          stale.push(endpoint);
        }
      }
    }
    stale.forEach(ep => pushSubscriptions.delete(ep));
    if (stale.length > 0) saveSubscriptions();
  }
  ```

#### Observation 1.5: Service Worker (`sw.js`) Push and Click Handlers
- **Source**: `_references_antigravity_mobile/ag2r/public/sw.js:14-68`
- **Verbatim Code**:
  ```javascript
  self.addEventListener('push', (event) => {
    let data = {};
    try {
      data = event.data.json();
    } catch (e) {}

    const title = data.title || 'AG2R';
    const tag = data.tag || 'ag2r-attention';
    const options = {
      body: data.body || 'Session needs your attention',
      icon: data.icon || '/ag2r-icon.png',
      badge: '/ag2r-badge.png',
      tag,
      data: { url: data.url, conversationId: data.conversationId },
      requireInteraction: true,
    };

    event.waitUntil(
      self.registration.showNotification(title, options)
    );
  });

  self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    const url = event.notification.data?.url;
    const conversationId = event.notification.data?.conversationId;

    trackEvent('push_clicked', { conversationId });

    event.waitUntil(
      clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
        if (windowClients.length > 0) {
          const target = windowClients[0];
          target.postMessage({
            type: conversationId ? 'navigate-conversation' : 'open-sidebar',
            conversationId,
          });
          return target.focus();
        }
        if (url) return clients.openWindow(url);
      })
    );
  });
  ```

#### Observation 1.6: Visibility Tracking & Notification Suppression
- **Source**:
  - Client sender (`app.js:365-371`):
    ```javascript
    function sendVisibility() {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'visibility', visible: document.visibilityState === 'visible' }));
      }
    }
    document.addEventListener('visibilitychange', sendVisibility);
    ```
  - Server receiver (`server.js:1959-1980`):
    ```javascript
    ws.on('message', (raw) => {
      try {
        const msg = JSON.parse(raw);
        if (msg.type === 'visibility') {
          const wasVisible = ws._visible;
          ws._visible = !!msg.visible;
          if (ws._visible && !wasVisible) visibleClients++;
          if (!ws._visible && wasVisible) visibleClients--;
        }
      } catch {}
    });

    ws.on('close', () => {
      if (ws._visible) visibleClients--;
      wsClients.delete(ws);
    });
    ```
  - Attention Check & Suppression (`server.js:234-279`):
    ```javascript
    const notifiedConversations = new Set();

    function checkAttentionState(snapshot) {
      if (pushPaused) return;

      const attentionItems = (snapshot.sidebarAttentionItems || [])
        .filter(item => item.type !== 'completed');

      // Clear notified IDs that are no longer in attention list (attended to)
      for (const id of notifiedConversations) {
        if (!attentionItems.some(item => item.id === id)) {
          notifiedConversations.delete(id);
        }
      }

      if (attentionItems.length === 0) return;

      const newItems = attentionItems.filter(item => !notifiedConversations.has(item.id));
      if (newItems.length === 0) return;

      for (const item of newItems) {
        notifiedConversations.add(item.id);

        if (visibleClients > 0) continue; // Track but don't send while looking

        const name = truncName(item.name);
        let body;
        if (item.type === 'question') {
          body = name ? `Asking question | ${name}` : 'Asking question';
        } else {
          body = name ? `Command approval | ${name}` : 'Command approval';
        }

        sendPushToAll({
          title: appName,
          body,
          tag: `ag2r-${item.id}`,
          conversationId: item.id,
        });
      }
    }
    ```

#### Observation 1.7: Verification of Python `pywebpush` & `cryptography`
- **Tool Command**: `python -c "import pywebpush; ..."`
- **Result**:
  - Python `cryptography` generates NIST P-256 EC keys.
  - `public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)` yields 65 bytes (`0x04 || X || Y`), which base64url-encodes to 87 characters.
  - `private_key.private_numbers().private_value.to_bytes(32, 'big')` yields 32 bytes scalar, which base64url-encodes to 43 characters.
  - `pywebpush.Vapid.from_string(raw_b64_scalar)` successfully instantiates `Vapid` and signs RFC 8292 claims.
  - `pywebpush.webpush(subscription_info, data, vapid_private_key=raw_b64_scalar, vapid_claims={"sub": email})` executes full RFC 8291 AES-128-GCM encryption and network dispatch.

---

### Component 2: Logic Chain

1. **VAPID Key Compatibility (Obs 1.1, 1.2, 1.7)**:
   - The browser's `PushManager.subscribe({ applicationServerKey })` requires an `ArrayBuffer` containing the raw 65-byte uncompressed elliptic curve point on curve P-256 (SEC-1 standard).
   - In `app.js`, `urlBase64ToUint8Array` decodes the string from `GET /push/vapid-public-key` into this 65-byte `Uint8Array`.
   - In Python, `cryptography.hazmat.primitives.asymmetric.ec.generate_private_key(ec.SECP256R1())` provides the exact NIST P-256 curve.
   - By exporting the public key using `Encoding.X962` and `PublicFormat.UncompressedPoint`, the output is 65 bytes starting with byte `0x04`.
   - The private key is a 32-byte integer, which base64url-encodes to 43 characters.
   - `pywebpush.Vapid.from_string` directly accepts this 32-byte scalar base64url string.
   - Therefore, Python can persist `{ "publicKey": "...", "privateKey": "..." }` in `vapid-keys.json`, identical to AG2R.

2. **Push Notification Payload & Service Worker Lifecycle (Obs 1.4, 1.5)**:
   - When an event triggers push, the server constructs a JSON string containing:
     - `title`: Application name (e.g. `Tri Wahyu Local AI Mobile Agent` / `AG2R`).
     - `body`: Notification text (e.g. `Asking question | <task>`, `Command approval | <task>`, `Task completed | <task>`).
     - `tag`: `ag2r-<conversationId>` (ensures notifications from the same task replace each other rather than flooding).
     - `icon`: Application icon URL.
     - `badge`: Application badge icon URL.
     - `data`: `{ "url": "<origin>?sidebar=open&conversationId=<id>", "conversationId": "<id>" }`.
   - `sw.js` parses this JSON payload in its `push` event handler and passes it to `registration.showNotification(title, options)`.
   - When clicked, `notificationclick` closes the notification, checks for open window clients:
     - If client window is open: sends postMessage `{ type: 'navigate-conversation', conversationId }` and focuses the window.
     - If no client window is open: opens the URL via `clients.openWindow(url)`.

3. **Visibility Tracking & Suppression Semantics (Obs 1.6)**:
   - WebSocket `/ws/stream` receives `{ type: "visibility", visible: boolean }` from connected clients.
   - If `visibleClients > 0`, the user is actively viewing the UI; push notifications must be suppressed to avoid noisy alerts on the same device.
   - However, new attention items MUST still be added to `notifiedConversations` (dedup set) while visible.
   - This ensures that if the user views the question/command on screen and then closes/backgrounds the tab without answering, they will NOT receive a stale alert for something they already saw.
   - Once the attention item is resolved (disappears from `attentionItems`), it is cleared from `notifiedConversations`.

4. **Attention Triggers & Agent Execution State (Obs 1.6, PROJECT.md, SCOPE.md)**:
   - Trigger 1: `sidebarAttentionItems` with `type === 'question'` -> `"Asking question | <name>"`.
   - Trigger 2: `sidebarAttentionItems` with `type === 'command'` -> `"Command approval | <name>"`.
   - Trigger 3: `agentRunning` transitions from `True` to `False` -> `"Task completed | <name>"`.
   - Trigger 4: Attention item with `type === 'completed'` -> `"Task completed | <name>"`.
   - Subscriptions failing with HTTP 410 (Gone) or 404 (Not Found) must be automatically pruned.

---

### Component 3: Caveats

1. **Push Delivery Requires HTTPS or Localhost**:
   - Web Push Notifications and Service Workers are only permitted in secure contexts (`https://` or `localhost`).
   - When accessed over LAN / Tailscale (`100.89.122.63:8888`), either HTTPS (self-signed cert) or Chrome's `--unsafely-treat-insecure-origin-as-secure` is required by the browser.
2. **Apple iOS Safari Web Push Requirement**:
   - On iOS (Safari 16.4+), Web Push is only supported if the user has added the web app to their Home Screen ("Add to Home Screen" / PWA standalone mode).
3. **Rate Limiting & Push Service Quotas**:
   - FCM / Mozilla push services can return 429 Too Many Requests if flooded. Asynchronous dispatch with `asyncio.to_thread` and retry backoff is recommended.
4. **No caveats on cryptographic format**:
   - Verified directly: NIST P-256 base64url uncompressed format matches across browser `PushManager`, Node.js `web-push`, Python `cryptography`, and `pywebpush`.

---

### Component 4: Conclusion & Architecture Recommendation

Milestone M2 (`push_notifications.py`) must implement `PushNotificationManager` with the following architectural components:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PushNotificationManager                         │
│                                                                        │
│  ┌──────────────────────┐  ┌─────────────────────┐  ┌───────────────┐  │
│  │ VAPID Key Management │  │ Subscription Store  │  │ Visibility    │  │
│  │ - P-256 EC Keypair   │  │ - push-subs.json    │  │ - Active set  │  │
│  │ - vapid-keys.json    │  │ - Thread-safe lock  │  │ - Suppression │  │
│  │ - get_public_key()   │  │ - 410 auto-prune    │  │ - Dedup set   │  │
│  └──────────┬───────────┘  └──────────┬──────────┘  └───────┬───────┘  │
│             │                         │                     │          │
│             └────────────────┬────────┴─────────────────────┘          │
│                              │                                         │
│             ┌────────────────▼───────────────────────┐                 │
│             │  check_and_send_attention_notifications│                 │
│             │  - Question & Command approvals        │                 │
│             │  - Agent running -> complete transition│                 │
│             │  - pywebpush async dispatcher (thread) │                 │
│             └────────────────────────────────────────┘                 │
└────────────────────────────────────────────────────────────────────────┘
```

#### Exact Class Design for `push_notifications.py`

```python
class PushNotificationManager:
    def __init__(
        self,
        config_path: str = "config.json",
        subscriptions_path: str = "push-subscriptions.json",
        vapid_path: str = "vapid-keys.json",
    ): ...

    def get_public_vapid_key(self) -> str:
        """Returns base64url-encoded 65-byte uncompressed P-256 public key (87 chars)."""
        ...

    def add_subscription(self, subscription_data: Dict[str, Any], origin: str = "") -> bool:
        """Stores subscription keyed by endpoint in push-subscriptions.json."""
        ...

    def remove_subscription(self, endpoint: str) -> bool:
        """Removes subscription by endpoint."""
        ...

    def set_client_visibility(self, client_id: str, is_visible: bool) -> None:
        """Tracks per-client visibility."""
        ...

    def remove_client(self, client_id: str) -> None:
        """Cleans up disconnected client."""
        ...

    def is_any_client_visible(self) -> bool:
        """Returns True if at least one client tab is visible/foreground."""
        ...

    def set_paused(self, paused: bool) -> None:
        """Pause/resume notification dispatch."""
        ...

    def is_paused(self) -> bool: ...

    async def check_and_send_attention_notifications(
        self,
        attention_items: List[Dict[str, Any]],
        agent_running: bool,
        conversation_name: str = "",
        conversation_id: str = "",
    ) -> int:
        """Evaluates attention items and agent status transitions, applies suppression and dedup, dispatches push."""
        ...

    async def send_notification(
        self,
        title: str,
        body: str,
        tag: Optional[str] = None,
        conversation_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Dispatches push notification payload to all active subscribers via pywebpush."""
        ...
```

---

### Component 5: Verification Method

1. **Unit Test Verification**:
   - Test VAPID key generation, loading from existing `vapid-keys.json`, and public key format (must be 87 chars base64url starting with valid base64 character).
   - Test subscription persistence: adding, removing, deduping, and file write/reload.
   - Test visibility tracking: adding client, setting visible true/false, verifying `is_any_client_visible()`.
   - Test attention state machine: transitions from idle -> running -> complete, question/command triggers, and suppression behavior when client is visible vs background.
2. **Mock Push Dispatch Verification**:
   - Mock `pywebpush.webpush` to capture outgoing payload and verify fields: `title`, `body`, `tag`, `icon`, `data.url`, `data.conversationId`.
   - Verify HTTP 410 / 404 response triggers automatic removal of the stale subscription from storage.
3. **Execution Command**:
   ```bash
   python -m unittest tests/test_push_notifications.py
   ```

---
*Report prepared by `explorer_m2_1` for Sub-Orchestrator M2 (`sub_orch_m2_push_notifications_1`).*
