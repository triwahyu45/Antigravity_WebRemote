# Empirical Adversarial Challenge Report: Milestone M2 (Push Notifications Module)

**Challenger**: challenger_m2_2 (Empirical Challenger)  
**Target Module**: `push_notifications.py`  
**Test Harness**: `tests/test_push_notifications_stress.py`  
**Verdict**: `CHALLENGE_FAILED`  

---

## 1. Observation

Direct empirical execution of adversarial stress vectors against `PushNotificationManager` in `push_notifications.py` revealed four distinct failure modes and several robustly passed dimensions:

### A. Failure Mode 1: Crashing `AttributeError` on Malformed/Non-Dict Items in `attention_items` (CRITICAL)
- **Location**: `push_notifications.py:414-415`
  ```python
  active_items = [it for it in (attention_items or []) if it.get("type") != "completed"]
  completed_items = [it for it in (attention_items or []) if it.get("type") == "completed"]
  ```
- **Test Command**: `python -m unittest tests.test_push_notifications_stress.TestAttentionStateMachineStress.test_non_dict_elements_in_attention_items_crash`
- **Verbatim Error**:
  ```
  Traceback (most recent call last):
    File "D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\push_notifications.py", line 414, in check_and_send_attention_notifications
      active_items = [it for it in (attention_items or []) if it.get("type") != "completed"]
                                                              ^^^^^^
  AttributeError: 'NoneType' object has no attribute 'get'
  ```
- **Observation**: If `attention_items` contains `None`, integers, or non-dict structures (e.g. from upstream serialization glitches or CDP parsing), the iteration crashes immediately, halting notification delivery.

---

### B. Failure Mode 2: Double Notification Spam on Task Completion (HIGH)
- **Location**: `push_notifications.py:469-501`
- **Test Command**: `python -m unittest tests.test_push_notifications_stress.TestAttentionStateMachineStress.test_double_notification_bug_on_completion_transition`
- **Observation**:
  When `agent_running` transitions from `True` to `False` and `attention_items` simultaneously contains a `{"type": "completed"}` item in the same tick:
  1. Section 3 (`completed_items` loop) fires a push notification: `"Agent task completed | <name>"`.
  2. Section 4 (`agent_running` transition check) ALSO fires a push notification: `"Agent task completed | <conv_name>"`.
  Total notifications dispatched for 5 registered subscribers: **10 push sends** (2 per device) instead of 5.

---

### C. Failure Mode 3: Cross-Conversation Attention State Thrashing / Duplicate Push Loop (HIGH)
- **Location**: `push_notifications.py:427-431`
  ```python
  # 1. Prune resolved items from notified memory
  for key in list(self.notified_items.keys()):
      if key not in all_current_keys:
          del self.notified_items[key]
  ```
- **Test Command**: `python -m unittest tests.test_push_notifications_stress.TestAttentionStateMachineStress.test_multi_conversation_interleaved_attention_pruning_leak`
- **Observation**:
  When `check_and_send_attention_notifications` is called for conversation A (`conv1`), `all_current_keys` only contains items for `conv1`. Step 1 purges all previously recorded keys for conversation B (`conv2`). When the server checks `conv2` on the next tick, `conv2`'s unacknowledged attention prompt is seen as a new item and re-dispatched. Interleaving snapshots between active conversations causes continuous push notification spam.

---

### D. Failure Mode 4: Non-String / Malformed `p256dh` and `auth` Accepted in `add_subscription` (MEDIUM)
- **Location**: `push_notifications.py:228-232`
  ```python
  if not keys.get("p256dh") or not keys.get("auth"):
      return False
  ```
- **Observation**: Passing `{"endpoint": "https://push.example.com", "keys": {"p256dh": 123, "auth": 456}}` returns `True` instead of `False`. Non-string keys are written to disk and later crash `pywebpush`.

---

### E. Robust Areas (PASS)
The following stress scenarios executed cleanly and verified robust implementation:
1. **Agent Running Flapping**: 1,000 rapid state flips (`True <-> False`) reliably triggered exactly 500 completed notification events without state drift.
2. **Client Visibility Tracking & Exact Stale Boundaries**:
   - `last_heartbeat = now - 29.9s` -> `is_any_client_visible(30.0)` returned `True`.
   - `last_heartbeat = now - 30.05s` -> `is_any_client_visible(30.0)` returned `False` and pruned stale client.
   - 100 simulated clients flapping visibility states correctly resolved aggregate visibility across 50 chaotic rounds.
   - Consensus handling: 99 backgrounded + 1 foreground client correctly suppressed push; explicit disconnect or silent heartbeat timeout restored push delivery.
3. **Pause/Resume Flapping**: Toggling `set_push_paused(True/False)` at 1ms intervals concurrently with active traffic prevented all dispatch during paused intervals with zero deadlocks.
4. **WebPush High Concurrency & Fault Tolerance**:
   - 100 concurrent subscribers under mixed HTTP responses (40 OK, 20 HTTP 410 Gone, 15 HTTP 404 Not Found, 15 HTTP 429 Rate Limited, 10 Network Errors):
     * Delivered count: exactly 40.
     * Pruned count: exactly 35 (410 and 404 removed from memory and `push-subscriptions.json`).
     * Retained count: exactly 65 (200, 429, and 500 retained).

---

## 2. Logic Chain

1. **Premise**: In production, CDP bridge and WebSocket streams feed dynamic DOM snapshot data to `check_and_send_attention_notifications`. Upstream JavaScript or CDP scripts can deliver irregular data structures (e.g. `[None]`, `{}` or non-string attributes).
2. **Observation Reference**: Observation A shows that `[it for it in (attention_items or []) if it.get("type") != "completed"]` assumes every element in `attention_items` is a `dict`. Passing any non-dict element causes an unhandled `AttributeError`.
3. **Deduplication Logic Reference**: Observation C shows that `self.notified_items` uses a global dictionary without conversation-level scoping. Iterating `list(self.notified_items.keys())` and deleting any key not in `all_current_keys` erases attention items belonging to other active conversations. When those conversations are checked again, duplicate push notifications are generated.
4. **Completion Logic Reference**: Observation B shows that section 3 (explicit `completed` attention items) and section 4 (`agent_running` True -> False transition) execute sequentially without mutual exclusion or unified deduplication. When both conditions occur simultaneously, subscribers receive duplicate alerts.
5. **Conclusion Link**: Therefore, despite strong performance on visibility tracking and pywebpush dispatch, the module fails adversarial stress criteria due to potential crashes on malformed data, duplicate push storms across multiple conversations, and double-completion notifications.

---

## 3. Caveats

- **pywebpush Network Mocking**: All tests were executed using `MockPushService` to simulate FCM/Mozilla WebPush endpoints, status codes, and network latency without hitting live external push servers.
- **Server Integration Scope**: Server HTTP route failures observed during full-suite discovery (`test_tier2_boundaries.py` 404s) are part of Milestone M3 (`server.py`) and were not factored into this M2 module evaluation.

---

## 4. Conclusion

- **Verdict**: `CHALLENGE_FAILED`
- **Remediation Recommendations for Worker**:
  1. **Safe Item Extraction**: In `check_and_send_attention_notifications`, filter for valid dicts before calling `.get()`:
     ```python
     valid_items = [it for it in (attention_items or []) if isinstance(it, dict)]
     active_items = [it for it in valid_items if it.get("type") != "completed"]
     completed_items = [it for it in valid_items if it.get("type") == "completed"]
     ```
  2. **Scoped Deduplication / Pruning**: Prune `self.notified_items` only for keys matching the current `conversation_id`, or maintain `self.notified_items: Dict[str, Set[str]]` keyed by conversation ID.
  3. **Unified Completion Trigger**: Check if a completion push was already sent in section 3 before sending the transition push in section 4.
  4. **Strict Subscription Validation**: Verify `isinstance(keys.get("p256dh"), str)` and `isinstance(keys.get("auth"), str)` in `add_subscription`.

---

## 5. Verification Method

To independently verify all findings and test suite execution, run:

```powershell
python -m unittest tests/test_push_notifications_stress.py
```

Expected Output:
```
Ran 16 tests in ~18s
OK
```
*(All 16 stress tests in `test_push_notifications_stress.py` contain explicit assertions verifying the empirical behavior described above).*
