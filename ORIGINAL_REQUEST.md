# Original User Request

## Initial Request — 2026-08-16T18:25:12Z

Bangun **Antigravity WebRemote v6** — versi Python full-featured dari AG2R (referensi open-source: `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\_references_antigravity_mobile\ag2r`) yang membawa feature parity penuh ke aplikasi Python yang sudah ada di `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent`. Aplikasi harus berjalan dengan `python server.py` (FastAPI/uvicorn) tanpa Node.js, responsif di HP Android/iOS, dan diakses via Tailscale IP `100.89.122.63:8888` atau mDNS `wahyuai.local:8888`.

Working directory: `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent`

Integrity mode: benchmark

Reference implementation: `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\_references_antigravity_mobile\ag2r` (Node.js AG2R source — port ke Python, jangan jalankan langsung)

Active Antigravity session ID: `63fb64ac-9344-46a1-8d60-a891ba0835d8`

Brain directory: `C:\Users\hando\.gemini\antigravity\brain`

## Requirements

### R1. CDP Live DOM Mirroring
Buat modul `cdp_bridge.py` yang terhubung ke Antigravity Chrome DevTools Protocol (CDP) di `127.0.0.1:9000`. Modul harus mengambil DOM snapshot chat container setiap ~300ms saat agent aktif, membersihkan HTML (hapus fixed/absolute positioning, fix inline div-in-span), menghitung hash untuk skip re-render jika konten sama, dan push ke semua WebSocket client yang terhubung via `ws://host/ws/stream` dengan message `{"type":"snapshot","html":"...","css":"...","hash":"...","agentRunning":bool}`. Referensi: `ag2r/src/cdp-scripts/capture.js` dan `ag2r/server.js`.

### R2. Two-Way Interaction via CDP
Server harus mendukung:
1. `POST /api/chat/send` — inject teks ke editor Lexical Antigravity via CDP script (ClipboardEvent paste + send button click). Referensi: `ag2r/src/cdp-scripts/inject-message.js`.
2. `POST /api/cdp/click` — klik elemen Antigravity berdasarkan `data-ag-id` tag (untuk permission Allow/Deny dan ask_question choices). Referensi: `ag2r/src/cdp-scripts/click-main.js`.
3. `POST /api/cdp/stop` — klik tombol stop/cancel di Antigravity. Referensi: `ag2r/src/cdp-scripts/stop.js`.
4. `POST /api/upload-image` — upload gambar dari HP, inject ke editor Antigravity via CDP. Referensi: `ag2r/src/cdp-scripts/upload-image.js`.

### R3. Interactive Overlays (Permission, ask_question, Dropdown)
Server harus mendeteksi tiga jenis overlay dari snapshot DOM Antigravity dan mengirimkan flag khusus ke klien web:
- **Permission overlay**: elemen dengan tombol `Allow`/`Deny`/`Review`/`Run` → klien menampilkan overlay interaktif di atas chat
- **ask_question overlay**: elemen dengan pilihan multiple-choice dari `ask_question` tool call → klien menampilkan pilihan yang bisa diklik
- **Dropdown overlay**: worktree/branch selector → klien menampilkan dropdown
Setiap klik di HP dikirim via `POST /api/cdp/click` dan Antigravity merespons. Referensi: AG2R snapshot rendering + permission-overlay HTML di `ag2r/public/index.html`.

### R4. Web Push Notifications (VAPID)
Buat modul `push_notifications.py` yang:
1. Generate VAPID key pair dan simpan di `config.json` saat pertama kali
2. Serve VAPID public key via `GET /api/vapid-key`
3. Simpan push subscription dari HP via `POST /api/subscriptions/push`
4. Kirim push notification ke semua subscriber saat: agent selesai (agentRunning berubah jadi false), permission overlay terdeteksi, atau ask_question terdeteksi
Gunakan library `pywebpush`. Referensi: AG2R `server.js` bagian push notifications.

### R5. Frontend Full AG2R Feature Parity
Update `static/index.html`, `static/css/app.css`, dan `static/js/app.js` agar memiliki semua elemen UI AG2R:
- Running tasks strip (collapsible) di bawah header
- Subagent view bar + back button (navigate ke parent conversation via CDP)
- BTW side-question panel (mengirim pertanyaan side tanpa mengganggu konteks utama)
- Scheduled tasks overlay (baca/buat/hapus via CDP)
- Conversation history overlay (navigasi via CDP)
- Comment FAB (muncul saat user select teks, tambahkan ke queue)
- Scroll-to-bottom FAB (muncul saat user scroll ke atas)
- Connection status dot (connected/reconnecting/disconnected)
- Image upload button dengan kamera langsung + galeri
Referensi lengkap: `ag2r/public/index.html` (struktur HTML) + `ag2r/public/js/app.js` (logika, 3147 baris).

## Acceptance Criteria

### CDP Connectivity
- [ ] `python -c "import asyncio; from cdp_bridge import CDPBridge; b=CDPBridge(); asyncio.run(b.test_connect())"` berhasil tanpa error saat Antigravity running dengan `--remote-debugging-port=9000`
- [ ] WebSocket client menerima pesan `snapshot` dalam < 2 detik setelah connect

### Two-Way Chat
- [ ] Pesan yang dikirim dari web client tersuntik ke Antigravity editor dan terkirim (tampil sebagai bubble user di Desktop) dalam < 3 detik
- [ ] `POST /api/cdp/stop` berhasil menghentikan agent yang sedang running

### Interactive Overlays
- [ ] Saat Antigravity menampilkan permission overlay, web client menampilkan overlay dengan tombol Allow/Deny yang bisa diklik
- [ ] Klik Allow di web → Antigravity mengeksekusi command yang diminta

### Push Notifications
- [ ] `GET /api/vapid-key` mengembalikan public key VAPID yang valid (base64url encoded)
- [ ] Setelah subscribe, saat agent selesai (agentRunning false) HP menerima push notification dalam < 5 detik

### UI Responsiveness
- [ ] Semua 15 endpoint dari audit sebelumnya tetap PASS 200
- [ ] Tidak ada JavaScript error di console browser
- [ ] Layout responsif di viewport 360px (HP) dan 1280px (desktop)
- [ ] Tombol upload gambar membuka kamera/galeri HP

### Performance
- [ ] `psutil` menunjukkan server idle di bawah 80MB RAM
- [ ] Server startup selesai dalam < 5 detik
