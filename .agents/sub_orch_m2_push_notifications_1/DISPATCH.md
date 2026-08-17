# Dispatch — 2026-08-17T01:30:12+07:00

## Milestone M2: Push Notifications Module

### Task Description
Implement `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\push_notifications.py`:
- VAPID keypair generation and persistent storage in `vapid-keys.json` / `config.json`.
- Browser push subscriptions management and persistence in `push-subscriptions.json`.
- Integration with `pywebpush` to send RFC 8292 Web Push notifications.
- Attention state watcher: compare attention item transitions (command approval, question asked, task complete) and dispatch push notification payloads with `{ title, body, icon, data: { conversationId, url } }`.
- Client visibility suppression: track active clients and suppress notifications if any client is actively viewing the web UI.
- Automatic cleanup of 410 Gone / expired subscriptions.
- Update `requirements.txt` to include `pywebpush>=1.14.0`.
- Verify with standalone unit tests.

### References
- `ORIGINAL_REQUEST.md`
- `PROJECT.md`
- Reference codebase: `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\_references_antigravity_mobile\ag2r\`
