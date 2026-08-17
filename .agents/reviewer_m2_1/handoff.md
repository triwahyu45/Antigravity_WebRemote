# Milestone M2 Review Report: Push Notifications Module

## 1. Observation

### 1.1 Interface Contract Conformity (`PROJECT.md` vs `push_notifications.py`)
- `PROJECT.md` lines 107-118 define the `PushNotificationManager` interface contract:
  - `__init__(self, config_path: str = "config.json", subscriptions_path: str = "push-subscriptions.json", vapid_path: str = "vapid-keys.json", vapid_email: str = "mailto:wahyuai@local.net")`
  - `get_public_vapid_key(self) -> str`
  - `add_subscription(self, subscription_data: Dict[str, Any]) -> bool`
  - `remove_subscription(self, endpoint: str) -> bool`
  - `set_client_visibility(self, client_id: str, is_visible: bool) -> None`
  - `is_any_client_visible(self, heartbeat_timeout: float = 30.0) -> bool`
  - `check_and_send_attention_notifications(self, attention_items: List[Dict[str, Any]], agent_running: bool, conversation_name: str = "", conversation_id: str = "") -> int`
  - `send_notification(self, title: str, body: str, data: Optional[Dict[str, Any]] = None) -> int`
- In `push_notifications.py` (lines 68-503), every method matches the signature, parameter defaults, and return type contracts exactly.

### 1.2 Cryptographic Correctness (NIST EC P-256 & VAPID RFC 8292)
- Lines 143-159 of `push_notifications.py` use `cryptography.hazmat.primitives.asymmetric.ec.generate_private_key(ec.SECP256R1())` and serialize the public key as X9.62 uncompressed point (`serialization.PublicFormat.UncompressedPoint`), producing a 65-byte point (0x04 || X || Y) encoded as an unpadded Base64url string (87 characters).
- Verified via Python CLI:
  ```
  Key: BP--mCWfvLbpTyPkfrZl_4L8cTzCduFNEPXnVcliGmuxvfi7rBz_aN8bwQP0A0erGl8VWPGm4J7Ip-7K8RwVAjg Len: 87
  Raw len: 65 Prefix: 0x4
  ```
- Supports PKCS#8 PEM private key format and legacy raw 32-byte scalar base64url private keys.

### 1.3 Async WebPush Dispatcher & Error Pruning
- Lines 374-378 of `push_notifications.py` execute synchronous `pywebpush.webpush` calls in worker threads via `asyncio.to_thread` with parallel execution via `asyncio.gather`, preventing event loop starvation.
- Line 323-335 handles `WebPushException`: HTTP 404 and 410 triggers automatic pruning of stale subscriptions; HTTP 429 and 500 retain subscriptions for retry; general network exceptions are caught safely.
- Atomic persistence is implemented in lines 200-211 using `.tmp` files and `os.replace`.

### 1.4 Test Suite Execution Results
Executed: `python -m unittest tests/test_push_notifications.py -v`
```
Ran 37 tests in 0.475s
OK
```
Executed: `python -m unittest discover -s tests -v`
```
Ran 37 tests in 0.626s
OK
```

### 1.5 Adversarial Stress Testing Results
Tested concurrent multi-threaded writes (5 threads, 250 operations), malformed inputs, corrupted files, and HTTP status pruning/retention: All passed without crashes or state corruption.

---

## 2. Logic Chain

1. **Interface Contract Verification**:
   - `PushNotificationManager` implements all required methods with compatible signatures. All types and defaults align with `PROJECT.md` and `SCOPE.md`.
2. **Cryptographic Integrity**:
   - The browser Web Push standard requires `applicationServerKey` to be a 65-byte uncompressed P-256 EC point (`0x04 || X || Y`) in Base64url format.
   - `push_notifications.py` correctly produces 87-character unpadded base64url keys from `ec.SECP256R1()`.
3. **Dispatcher & Concurrency Safety**:
   - Web Push HTTP requests take 100ms-2000ms over network. By dispatching them via `asyncio.to_thread` and `asyncio.gather`, the FastAPI async server remains responsive.
   - Concurrency is protected with `threading.Lock` around `self.subscriptions` and file writes.
4. **Resilience & Fault Tolerance**:
   - Invalidation of expired push tokens (410/404) prevents accumulation of dead subscriptions.
   - Rate limiting (429) does not discard valid subscriptions.
   - File writes are atomic via `os.replace`, preventing corrupted JSON on unexpected process exit.
5. **Absence of Integrity Violations**:
   - Source code contains real cryptographic and networking logic. No dummy mocks, hardcoded outputs, or bypasses.

---

## 3. Caveats

- End-to-end delivery to real mobile devices over FCM/APNs relies on browser push services and internet connectivity; mocked in automated tests via `MockPushService`.
- Integration into the FastAPI server (`server.py`) and WebSocket `/ws/stream` visibility dispatching is scheduled for Milestone M3.

---

## 4. Conclusion

**Verdict: APPROVE**

The implementation of `push_notifications.py`, `requirements.txt`, and `tests/test_push_notifications.py` is cryptographically sound, conforms strictly to the interface contract, implements robust async concurrency and error handling, and passes 100% of unit and adversarial tests.

---

## 5. Verification Method

To independently verify this milestone review:
1. Run the test suite:
   ```powershell
   python -m unittest tests/test_push_notifications.py -v
   ```
2. Verify VAPID EC P-256 key encoding and length:
   ```powershell
   python -c "from push_notifications import PushNotificationManager; m = PushNotificationManager(); pk = m.get_public_vapid_key(); print('Len:', len(pk)); import base64; raw = base64.urlsafe_b64decode(pk + '==='); print('Raw len:', len(raw), 'Prefix:', hex(raw[0]))"
   ```
3. Inspect `requirements.txt` for `pywebpush>=1.14.0` and `cryptography>=41.0.0`.
