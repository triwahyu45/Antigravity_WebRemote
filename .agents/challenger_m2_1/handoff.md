# Handoff Report — Milestone M2 Adversarial Challenge

**Agent**: challenger_m2_1 (Empirical Challenger)  
**Target Module**: `push_notifications.py` (Milestone M2 - Push Notifications Module)  
**Verdict**: **`CHALLENGE_FAILED`**  

---

## 1. Observation

Adversarial stress suite was written to `tests/test_adversarial_m2.py` and executed via:
```powershell
python -m unittest tests/test_adversarial_m2.py
```

### Observation 1.1: Malformed Subscriptions with Non-String Keys Accepted
- **File**: `push_notifications.py`, Lines 231-233:
  ```python
  if not keys.get("p256dh") or not keys.get("auth"):
      return False
  ```
- **Execution Output**:
  ```text
  FAIL: test_malformed_subscription_inputs (tests.test_adversarial_m2.TestSubscriptionAdversarialCases.test_malformed_subscription_inputs)
  ----------------------------------------------------------------------
  Traceback (most recent call last):
    File "tests/test_adversarial_m2.py", line 268, in test_malformed_subscription_inputs
      self.assertFalse(res, f"Expected False for malformed input: {item}")
  AssertionError: True is not false : Expected False for malformed input: {'endpoint': 'https://push.example.com', 'keys': {'p256dh': 123, 'auth': 456}}
  ```
- **Behavior**: Because `bool(123) == True`, `add_subscription` returns `True` for subscriptions with integer or non-string keys, leading to downstream `TypeError` inside `pywebpush`.

### Observation 1.2: VAPID Key Loading Lacks EC P-256 Curve & Public Key Format Validation
- **File**: `push_notifications.py`, Lines 108-118:
  ```python
  pub = data.get("publicKey", "").strip()
  priv = data.get("privateKey", "").strip()
  if pub and priv:
      self.public_vapid_key = pub
      self._private_key_pem = priv
      if "-----BEGIN" in priv:
          self.vapid = Vapid.from_pem(priv.encode("utf-8"))
      else:
          self.vapid = Vapid.from_string(priv)
      return
  ```
- **Execution Output**:
  ```text
  FAIL: test_vapid_invalid_key_curves (tests.test_adversarial_m2.TestVapidAdversarialCases.test_vapid_invalid_key_curves)
  ----------------------------------------------------------------------
  Traceback (most recent call last):
    File "tests/test_adversarial_m2.py", line 150, in test_vapid_invalid_key_curves
      assert_vapid_key_valid(mgr.get_public_vapid_key())
    File "tests/harness.py", line 1724, in assert_vapid_key_valid
      assert len(key_str) in (86, 87, 88), f"VAPID public key invalid length ({len(key_str)}): '{key_str}'"
  AssertionError: VAPID public key invalid length (8): 'some_pub'
  ```
- **Behavior**: `Vapid.from_pem` accepts RSA and non-P-256 PEM keys without error. `_init_vapid_keys` stores the invalid public key string without checking RFC 8292 NIST P-256 point format (86-88 unpadded base64url characters).

### Observation 1.3: Corrupted Subscription Dict Values Cause Unhandled `AttributeError` in `send_notification`
- **File**: `push_notifications.py`, Lines 186-187 and Line 307:
  ```python
  # Line 186-187:
  raw = json.load(f)
  if isinstance(raw, dict):
      self.subscriptions = raw
  ```
  ```python
  # Line 307 (outside try block):
  endpoint = sub.get("endpoint", "")
  ```
- **Execution Output**:
  ```text
  python -c "import asyncio, json, os, tempfile; from push_notifications import PushNotificationManager; ..."
  CRASHED with: <class 'AttributeError'> 'str' object has no attribute 'get'
  ```
- **Behavior**: If `push-subscriptions.json` contains a dictionary whose values are strings or integers (e.g. `{"https://fcm.googleapis.com/ep1": "invalid"}`), `_load_subscriptions` accepts it. When `send_notification` is called, `sub.get()` is executed outside the `try` block, raising `AttributeError`. Because `send_notification` calls `asyncio.gather(..., return_exceptions=False)`, the entire dispatch crashes for all subscribers.

### Observation 1.4: Concurrent Startup Temp File Collision on Windows (`[WinError 32]`)
- **File**: `push_notifications.py`, Lines 168-171:
  ```python
  tmp_path = str(self.vapid_path) + ".tmp"
  with open(tmp_path, "w", encoding="utf-8") as f:
      json.dump(key_data, f, indent=2)
  os.replace(tmp_path, str(self.vapid_path))
  ```
- **Execution Output**:
  ```text
  Failed saving VAPID keys to disk: [WinError 32] The process cannot access the file because it is being used by another process: '...\\vapid-keys.json.tmp' -> '...\\vapid-keys.json'
  ```
- **Behavior**: Multiple instances initializing concurrently collide on the shared static `.tmp` filename, causing Windows file locking conflicts during `os.replace`.

---

## 2. Logic Chain

1. **Premise**: Web Push subscriptions and VAPID keys are external, untrusted inputs and stored files that may be corrupted, manipulated, or subject to race conditions.
2. **From Observation 1.1**: `add_subscription` only checks `if not keys.get("p256dh")`. When passed integers or boolean values, it accepts them because non-zero integers are truthy. This violates the input contract and causes subsequent cryptographic operations to fail.
3. **From Observation 1.2**: RFC 8292 mandates EC P-256 (prime256v1). When a non-P-256 key or an invalid public key string exists on disk, `_init_vapid_keys` does not validate key length (86-88 chars) or curve compatibility, resulting in invalid public keys being served to browser clients.
4. **From Observation 1.3**: `_load_subscriptions` does not validate the type of dictionary values. In `_sync_send_single_push`, `endpoint = sub.get("endpoint", "")` is executed before entering the exception handler. An unhandled exception inside worker threads causes `asyncio.gather` to abort the entire notification broadcast.
5. **From Observation 1.4**: Static temporary filenames in `_init_vapid_keys` and `_save_subscriptions` create file contention on Windows under multi-process/multi-thread concurrency.
6. **Inference**: While the standard unit tests pass for happy paths, the module fails under adversarial inputs, corrupted storage, and concurrency stress.

---

## 3. Caveats

- **pywebpush Network Mocking**: Real WebPush endpoints (FCM, Mozilla Autopush) were emulated via `MockPushService`. Actual cloud endpoint interaction requires live network tokens and real mobile devices.
- **Client Visibility Concurrency**: In Python 3.12, GIL protections prevented `RuntimeError` during concurrent dictionary reads/writes in `is_any_client_visible()`, but explicit locking is advised for consistency across alternative Python runtimes (PyPy/Free-threaded CPython).

---

## 4. Conclusion

- **Verdict**: **`CHALLENGE_FAILED`**
- **Actionable Mitigations for Implementation Team**:
  1. **Harden `add_subscription` Type Checking**:
     ```python
     p256dh = keys.get("p256dh")
     auth = keys.get("auth")
     if not isinstance(p256dh, str) or not isinstance(auth, str) or not p256dh.strip() or not auth.strip():
         return False
     ```
  2. **Validate Public Key in `_init_vapid_keys`**:
     ```python
     # Ensure public key is uncompressed EC P-256 base64url string (86-88 chars)
     if len(pub) not in (86, 87, 88):
         raise ValueError(f"Invalid VAPID public key length: {len(pub)}")
     ```
  3. **Sanitize Dictionary Entries in `_load_subscriptions` & Guard `_sync_send_single_push`**:
     ```python
     # In _load_subscriptions:
     if isinstance(raw, dict):
         self.subscriptions = {
             k: v for k, v in raw.items()
             if isinstance(v, dict) and isinstance(v.get("endpoint"), str) and isinstance(v.get("keys"), dict)
         }
     
     # In _sync_send_single_push:
     if not isinstance(sub, dict):
         return False, None
     ```
  4. **Use Unique Temp Files**:
     ```python
     tmp_path = f"{self.vapid_path}.{os.getpid()}_{threading.get_ident()}_{time.time_ns()}.tmp"
     ```

---

## 5. Verification Method

To verify these findings independently, run the following test commands:
```powershell
# 1. Run all unit tests
python -m unittest tests/test_push_notifications.py

# 2. Run adversarial stress test suite
python -m unittest tests/test_adversarial_m2.py
```

Expected invalidation condition: Once the fixes above are implemented, `tests/test_adversarial_m2.py` will exit with code 0 (18/18 tests passing).
