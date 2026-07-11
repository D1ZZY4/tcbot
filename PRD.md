# PRD — TCBot AI Federation Moderation System
> **Status**: Draft v1.0 | **Tanggal**: 11 Juli 2026  
> **Scope**: Integrasi AI moderasi otomatis berbasis rules federasi ke dalam TCBot yang sudah ada  
> **Target**: 60 grup, ~600.000 member, Telegram bot berbasis python-telegram-bot + MongoDB

---

## DAFTAR ISI

1. [Latar Belakang & Tujuan](#1-latar-belakang--tujuan)
2. [Batasan & Asumsi](#2-batasan--asumsi)
3. [Arsitektur Sistem Keseluruhan](#3-arsitektur-sistem-keseluruhan)
4. [Federation Rules — Struktur & Storage](#4-federation-rules--struktur--storage)
5. [Sistem Severity](#5-sistem-severity)
6. [Sistem Actions](#6-sistem-actions)
7. [Proof dalam Konteks AI](#7-proof-dalam-konteks-ai)
8. [Flow Lengkap: Pesan Masuk → Keputusan AI → Eksekusi](#8-flow-lengkap-pesan-masuk--keputusan-ai--eksekusi)
9. [Format JSON ke AI](#9-format-json-ke-ai)
10. [Format JSON Output dari AI](#10-format-json-output-dari-ai)
11. [Action Flows Detail](#11-action-flows-detail)
12. [Sistem Terjemahan Otomatis (EN → ID)](#12-sistem-terjemahan-otomatis-en--id)
13. [Seeding Rules ke Database](#13-seeding-rules-ke-database)
14. [Cooldown & Rate Limiting AI](#14-cooldown--rate-limiting-ai)
15. [Log Channel & Notifikasi Admin](#15-log-channel--notifikasi-admin)
16. [Integrasi dengan Kode yang Sudah Ada](#16-integrasi-dengan-kode-yang-sudah-ada)
17. [Rules yang Tidak Bisa Di-enforce AI](#17-rules-yang-tidak-bisa-di-enforce-ai)
18. [Edge Cases & Penanganan Error](#18-edge-cases--penanganan-error)
19. [Konfigurasi Bot](#19-konfigurasi-bot)
20. [Out of Scope](#20-out-of-scope)

---

## 1. LATAR BELAKANG & TUJUAN

### Situasi Saat Ini

TCBot sudah memiliki sistem moderasi manual yang lengkap:
- `/ban` dengan bukti wajib → fan-out ke semua grup (fban)
- `/mute` dengan durasi opsional
- `/kick` single-group
- `/warn` dengan auto-escalate ke ban saat batas tercapai

Namun semua aksi ini **100% manual** — admin harus melihat pelanggaran, memutuskan, lalu menjalankan command. Di federasi dengan 60 grup dan ratusan ribu member, ini tidak skala.

### Tujuan

Tambahkan lapisan **AI pre-screening** yang:
1. Memantau setiap pesan masuk di semua grup yang terhubung
2. Mengevaluasi pesan terhadap 27 federation rules
3. Mengeksekusi action ringan-sedang **secara otomatis** (low confidence → eskalasi ke admin)
4. Memberikan **rekomendasi** ke mod channel untuk action berat
5. Tidak menggantikan admin — melengkapi dan meringankan beban moderasi

### Yang Tidak Berubah

Semua flow manual yang sudah ada (`/ban`, `/mute`, `/kick`, `/warn`, `/fban`) **tidak disentuh**. AI adalah lapisan tambahan di atas sistem yang sudah ada, bukan pengganti.

---

## 2. BATASAN & ASUMSI

### Batasan Teknis

| Item | Keputusan |
|---|---|
| AI dapat melihat media (foto, video, stiker) | ❌ Tidak — AI hanya menerima teks pesan |
| AI dapat memberikan bukti screenshot | ❌ Tidak — bukti hanya berupa teks pesan itu sendiri |
| Action `fban` (federation ban terpisah) | ❌ Dihapus dari sistem baru — diganti `ban` |
| Rules disimpan dalam dua bahasa di DB | ❌ Tidak — hanya EN, terjemahan dilakukan on-demand |
| Field `last_updated` per rule di DB | ❌ Tidak diperlukan |
| AI memutuskan sendiri untuk action `ban` | ⚠️ Dengan syarat — lihat Bagian 7 |

### Asumsi

- Model AI yang digunakan sudah mampu memahami konteks percakapan Bahasa Indonesia dan Bahasa Inggris (bilingual)
- Bot sudah terhubung ke semua 60 grup sebagai admin dengan izin delete message
- `cfg.logs` channel sudah ada dan berfungsi untuk log moderasi
- MongoDB dan Redis sudah running

---

## 3. ARSITEKTUR SISTEM KESELURUHAN

```
┌─────────────────────────────────────────────────────────────────┐
│                         TELEGRAM GROUPS                          │
│              (60 grup, semua pesan masuk di-process)            │
└────────────────────────────┬────────────────────────────────────┘
                             │ setiap pesan (MessageHandler)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PRE-FILTER LAYER                              │
│  • Skip jika pengirim adalah admin/bot                           │
│  • Skip jika pesan tidak punya teks (hanya stiker/foto kosong)  │
│  • Skip jika grup belum mengaktifkan AI moderation              │
│  • Rate limit: satu evaluasi per 30 detik per grup               │
└────────────────────────────┬────────────────────────────────────┘
                             │ lolos filter
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   CONTEXT BUILDER                                │
│  • Ambil 10 pesan terakhir di grup (sliding window)             │
│  • Format menjadi conversation array                             │
│  • Load rules dari cache (Redis L1 → MongoDB L2)                │
│  • Bangun JSON payload untuk AI                                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AI EVALUATION ENGINE                          │
│  • Kirim JSON ke LLM via API                                     │
│  • Parse JSON response                                           │
│  • Validasi output (verdict, rule_id, confidence, action)       │
└────────────────────────────┬────────────────────────────────────┘
                             │
            ┌────────────────┴────────────────┐
            │ clean                           │ violation
            ▼                                ▼
     [Log → discard]            ┌────────────────────────┐
                                │   DECISION ROUTER       │
                                │  berdasarkan:            │
                                │  - confidence level      │
                                │  - severity rule         │
                                │  - selected_action       │
                                └────────────────────────┘
                                         │
                   ┌─────────────────────┼───────────────────────┐
                   │                     │                         │
                   ▼                     ▼                         ▼
         confidence < 0.75     0.75 ≤ conf < 0.90         confidence ≥ 0.90
              │                         │                         │
         Log saja               Flag ke mod channel       Auto-execute action
         (tidak ada action)     (admin putuskan)          + notify log channel
```

---

## 4. FEDERATION RULES — STRUKTUR & STORAGE

### Format File (fed-rules/*.md)

Setiap file rule memiliki YAML frontmatter di bagian atas, diikuti konten teks EN untuk ditampilkan ke user.

**Contoh file `05-cheat.md` setelah ditambah frontmatter:**

```markdown
---
rule_id: cheat
display_name: "Cheat & Hack"
severity: xhigh
auto_actions:
  - warning
  - kick
  - ban
ai_enforceable: true
ai_description: >
  Prohibited: using or sharing any cheat, hack, maphack, wallhack, damage++,
  auto-targeting, aimbot, or any software/modification that gives unfair advantage
  in games. Sharing screenshots, videos, or download links of cheats is also
  prohibited. Discussing or promoting cheat tools of any kind is banned.
  IMPORTANT EXCEPTION: iPad View (screen mirroring) in PUBG Mobile and Mobile
  Legends is explicitly ALLOWED as it gives no unfair advantage.
  Violations result in immediate action without prior warning.
---

**CHEAT**
─────────
**EN**

**Rules**: Using or sharing cheating scripts (cheats) in games or applications
is strictly prohibited. Let's maintain sportsmanship within the community.

...dst (konten EN lengkap)
```

### Apa yang Disimpan di MongoDB (collection: `fed_rules`)

Hanya data yang diperlukan bot secara operasional:

```
FedRuleDoc:
  rule_id         : str           # unique key, e.g. "cheat"
  display_name    : str           # untuk tampilan di bot, e.g. "Cheat & Hack"
  severity        : str           # "low" | "medium" | "high" | "xhigh" | "max"
  auto_actions    : list[str]     # ["warning", "kick", "ban"] terurut ringan→berat
  ai_enforceable  : bool          # False → skip AI untuk rule ini
  ai_description  : str           # dioptimalkan untuk AI, bukan untuk human
  content_en      : str           # teks lengkap EN untuk ditampilkan ke user
  is_active       : bool          # bisa di-disable tanpa hapus
```

> **Catatan**: Tidak ada `content_id`, tidak ada `last_updated`. Terjemahan ID dilakukan secara on-demand (lihat Bagian 12). `last_updated` hanya relevan sebagai info di file `.md` asli, tidak perlu masuk DB.

### 27 Rules yang Ada Saat Ini

| # | rule_id | display_name | Severity | ai_enforceable |
|---|---|---|---|---|
| 01 | `18-plus` | 18+ Content | xhigh | ✅ (teks deskriptif) |
| 02 | `fed-admin` | Federation Admin Conduct | high | ❌ (butuh human judgment) |
| 03 | `admin-power` | Admin Power Abuse | high | ❌ (butuh human judgment) |
| 04 | `group-admin` | Group Admin Conduct | medium | ❌ (butuh human judgment) |
| 05 | `cheat` | Cheat & Hack | xhigh | ✅ |
| 06 | `crypto` | Cryptocurrency | high | ✅ |
| 07 | `doxing` | Doxing & Privacy | high | ✅ |
| 08 | `drugs` | Narcotics & Drugs | max | ✅ |
| 09 | `fundraising` | Fundraising Abuse | high | ✅ (partial) |
| 10 | `group-ownership` | Group Ownership | high | ❌ |
| 11 | `gambling` | Gambling | high | ✅ |
| 12 | `harmful-modules` | Harmful Modules | high | ✅ |
| 13 | `keybox` | Keybox & VVIP Sales | max | ✅ |
| 14 | `hate-speech` | Hate Speech | xhigh | ✅ |
| 15 | `license-claiming` | License & Ownership | high | ✅ |
| 16 | `nickname-pfp` | Nickname & Profile Picture | medium | ❌ (butuh visual) |
| 17 | `hoax-monopoly` | Hoax & Monopoly | high | ✅ |
| 18 | `root-module` | Root Module Rules | high | ✅ |
| 19 | `phishing` | Phishing | max | ✅ |
| 20 | `piracy` | Piracy | high | ✅ |
| 21 | `promotion` | Unauthorized Promotion | low | ✅ |
| 22 | `provocation` | Provocation | medium | ✅ |
| 23 | `racism-sara` | Racism & SARA | xhigh | ✅ |
| 24 | `politics` | Political Content | high | ✅ |
| 25 | `scam-ripper` | Scam & Ripper | max | ✅ |
| 26 | `spam-flooding` | Spam & Flooding | low | ✅ |
| 27 | `unethical-marketing` | Unethical Marketing | high | ✅ |

**AI-enforceable: 20 rules.** Non-enforceable by AI: 7 rules (02, 03, 04, 10, 16 = butuh human; 09 = partial).

---

## 5. SISTEM SEVERITY

Severity mendefinisikan **seberapa serius** pelanggaran tersebut dan menentukan batas minimum action yang bisa AI rekomendasikan.

### Level Severity

| Level | Arti | Contoh Rules | Default Behavior |
|---|---|---|---|
| `low` | Gangguan kecil, tidak berbahaya | spam, flooding, promotion | AI auto-execute ringan saja |
| `medium` | Mengganggu suasana grup | provocation, nickname-pfp | AI auto-execute dengan notif |
| `high` | Pelanggaran serius, berdampak luas | politics, piracy, hate-speech | AI rekomendasikan, admin approve |
| `xhigh` | Sangat serius, multi-korban potensial | cheat, 18+, racism-sara | AI auto-ban dengan notif wajib |
| `max` | Kriminal / zero-tolerance | phishing, scam, drugs, keybox | AI auto-ban langsung, no appeal otomatis |

### Mapping Severity → Action yang Diizinkan AI

```
low   → AI boleh: warning, mute, mute_time
        AI tidak boleh: kick, ban
        
medium → AI boleh: warning, mute, mute_time, kick
         AI tidak boleh: ban (kecuali repeat offender dalam window)

high   → AI boleh: warning, kick, mute_time
         ban: hanya jika confidence ≥ 0.90 DAN auto_execute diaktifkan admin
         
xhigh  → AI boleh semua kecuali ban langsung tanpa confidence ≥ 0.90
         ban: confidence ≥ 0.87 sudah cukup
         
max    → AI langsung ban jika confidence ≥ 0.85
         tidak ada warning/mute terlebih dahulu
```

---

## 6. SISTEM ACTIONS

### 5 Actions yang Tersedia

Tidak ada lagi `fban` sebagai action terpisah. Actions yang valid:

#### 6.1 `warning`
Tambah peringatan ke user di grup tersebut. Jika mencapai batas warn (`cfg.warn_limit`), auto-escalate ke `ban`.

- Tersimpan di collection `warns`
- User bisa lihat warn count via `/warns @user`
- Tidak ada efek langsung ke kemampuan chat user
- Bot kirim pesan notifikasi ke grup bahwa user mendapat warn

#### 6.2 `mute`
Mute permanen. User tidak bisa kirim pesan sampai admin un-mute manual.

- `restrict_chat_member(permissions=ChatPermissions(can_send_messages=False), until_date=None)`
- Tersimpan di `mutes` (audit) dan `active_mutes` (state)
- Scope: satu grup saja (bukan federation-wide)
- Bisa di-unmute via `/unmute`

#### 6.3 `mute_time`
Mute sementara dengan durasi tertentu. AI menentukan durasi berdasarkan severity.

- `restrict_chat_member(..., until_date=<datetime>)`
- Durasi default yang bisa AI rekomendasikan:
  - Pelanggaran ringan pertama: `1h`
  - Pelanggaran sedang: `6h` atau `12h`
  - Pelanggaran berat pertama: `24h` atau `3d`
  - Maximum AI bisa rekomendasikan: `7d`
- Tersimpan di `active_mutes` dengan `until_date`
- Telegram handle expiry secara otomatis (tidak perlu background job)

#### 6.4 `kick`
Hapus user dari grup. User bisa join kembali via invite link.

- `ban_chat_member` lalu `unban_chat_member(only_if_banned=True)` — persis seperti kode yang ada sekarang
- Tidak ada record permanen di DB (atau bisa log minimal di collection `kicks`)
- Scope: satu grup saja
- Tidak memerlukan bukti formal
- Bot kirim notifikasi ke grup

#### 6.5 `ban`
Ban permanen dari seluruh federasi (fan-out ke semua 60 grup). Ini yang paling berat.

- **Memerlukan**: `reason` (string) + `proof` (lihat Bagian 7)
- Menggunakan `_execute_ban` yang sudah ada di `ban_flow.py`
- Fan-out via `fan_out()` ke semua `active_groups()`
- Tersimpan di collection `bans` sebagai `BanDoc`
- Appeal tetap tersedia lewat sistem yang sudah ada
- Bot kirim notifikasi ke `cfg.logs` channel dengan tombol appeal

### Tabel Ringkasan Actions

| Action | Durasi | Scope | Butuh Proof | Bisa AI Otomatis |
|---|---|---|---|---|
| `warning` | Permanent (counter) | Per-grup | ❌ | ✅ |
| `mute` | Permanent | Per-grup | ❌ | ✅ |
| `mute_time` | Sementara (1h–7d) | Per-grup | ❌ | ✅ |
| `kick` | Permanent (tapi bisa re-join) | Per-grup | ❌ | ✅ |
| `ban` | Permanent (bisa di-unban) | Federation-wide | ✅ (teks) | ✅ (confidence ≥ threshold) |

---

## 7. PROOF DALAM KONTEKS AI

### Masalah

Sistem ban yang ada di `ban_flow.py` memerlukan bukti (`proof_message_id`). Untuk ban manual, admin attach screenshot atau forward pesan. AI **tidak bisa** menghasilkan screenshot atau gambar.

### Solusi

Untuk ban yang diinisiasi AI, "bukti" adalah **pesan itu sendiri**. Flow-nya:

```
AI deteksi pesan ID: 6001 dari user 801 sebagai violation
        │
        ▼
Bot forward pesan ID 6001 ke cfg.proofs channel
        │
        ▼
Dapatkan message_id hasil forward di proofs channel = proof_message_id
        │
        ▼
Buat BanDoc dengan:
  - reason = teks reasoning dari AI (e.g. "Menjual keybox dengan label VVIP...")
  - proof_message_id = ID pesan yang di-forward ke proofs channel
  - admin_user_id = BOT_USER_ID (bot yang eksekusi, bukan admin manusia)
        │
        ▼
Kirim ke cfg.logs channel dengan format standar + tag "[AI Moderation]"
```

### Implikasi

- Field `proof_message_id` di `BanDoc` tetap terisi (link ke pesan asli yang di-forward)
- `reason` diisi oleh AI reasoning — bukan "tidak ada alasan"
- Log channel menandai jelas bahwa ini "AI ban" bukan "manual ban"
- Admin tetap bisa undo jika AI salah, via tombol `[Undo Ban]` di log channel

### Batas AI untuk Ban

AI **tidak boleh** ban atas dasar:
- Media saja (foto/video) tanpa teks pendamping yang melanggar
- Stiker tanpa konteks teks
- Link tanpa domain yang jelas berbahaya/dikenal
- Pesan yang sangat ambigu (confidence < threshold)

Untuk kasus-kasus ini, AI hanya boleh: flag ke admin, atau pilih action lebih ringan.

---

## 8. FLOW LENGKAP: PESAN MASUK → KEPUTUSAN AI → EKSEKUSI

### Diagram Detail

```
TELEGRAM MESSAGE HANDLER (setiap pesan di semua grup)
│
├─ PRE-FILTER (sinkron, cepat)
│   ├─ from_user is None? → skip (anonymous admin)
│   ├─ from_user.id in admin_ids? → skip
│   ├─ from_user.is_bot? → skip
│   ├─ message.text is None AND message.caption is None? → skip
│   ├─ group ai_enabled = False? → skip
│   └─ Redis check: cooldown active for this chat_id? → skip
│       (set cooldown 30 detik setelah setiap evaluasi)
│
├─ CONTEXT BUILDER (async)
│   ├─ Ambil 10 pesan sebelumnya dari chat (Telegram getMessages atau cache)
│   ├─ Sanitasi: hapus field tidak perlu (entities, keyboards, dll)
│   ├─ Load fed_rules dari Redis (TTL 10 menit) → fallback ke MongoDB
│   ├─ Filter: hanya rules dengan ai_enforceable = True
│   └─ Build JSON payload (lihat Bagian 9)
│
├─ AI CALL (async, timeout 15 detik)
│   ├─ POST ke LLM API
│   ├─ Timeout → log error, tidak ada action, reset cooldown
│   ├─ Parse JSON response
│   └─ Validasi: verdict harus "violation" atau "clean"
│
├─ DECISION ROUTER
│   │
│   ├─ verdict = "clean" → log debug, selesai
│   │
│   └─ verdict = "violation":
│       │
│       ├─ confidence < 0.75
│       │   └─ Hanya log ke internal debug. Tidak ada action.
│       │
│       ├─ 0.75 ≤ confidence < 0.90
│       │   └─ Flag ke mod channel dengan tombol:
│       │       [Approve Action] [Ignore] [Lihat Pesan]
│       │       Admin yang memutuskan. Bot tidak eksekusi otomatis.
│       │
│       └─ confidence ≥ 0.90
│           ├─ selected_action = "warning"  → execute_warn()
│           ├─ selected_action = "mute"     → execute_mute(permanent=True)
│           ├─ selected_action = "mute_time" → execute_mute(duration=ai_duration)
│           ├─ selected_action = "kick"     → execute_kick()
│           └─ selected_action = "ban"
│               ├─ Cek severity rule: max/xhigh → langsung eksekusi
│               ├─ Severity high ke bawah → flag dulu ke mod channel
│               └─ Forward offending message ke proofs channel
│                   → create BanDoc → fan_out ban → notify logs
│
└─ NOTIFIKASI
    ├─ Kirim pesan ke grup (lihat format di Bagian 15)
    └─ Kirim log ke cfg.logs channel (lihat format di Bagian 15)
```

### Threshold Decision Matrix

| Confidence | Severity Action | Hasil |
|---|---|---|
| < 0.75 | apapun | Log saja, tidak ada action |
| 0.75–0.89 | apapun | Flag ke mod channel, tunggu admin |
| ≥ 0.90 | warning/mute/mute_time/kick | Auto-execute |
| ≥ 0.90 | ban + severity max/xhigh | Auto-execute ban |
| ≥ 0.90 | ban + severity high ke bawah | Flag ke mod channel |
| ≥ 0.87 | ban + severity xhigh | Auto-execute ban |
| ≥ 0.85 | ban + severity max | Auto-execute ban |

---

## 9. FORMAT JSON KE AI

Ini adalah JSON yang dikirim sebagai `user` message ke LLM. **Harus tepat format ini, tidak boleh berbeda.**

### System Prompt (dikirim sekali sebagai `system` role)

```
You are a strict AI moderator for TCF (Transsion Community Federation), a Telegram 
tech & gaming community with 60 groups and 600,000 members. You enforce federation 
rules and output ONLY valid JSON.

CRITICAL INSTRUCTIONS:
1. Output ONLY a single valid JSON object. No text before {, no text after }.
2. Evaluate the ENTIRE conversation, not just the last message.
3. If multiple violations exist, pick the SINGLE most severe one.
4. "selected_action" MUST be one of the values in that rule's "auto_actions" array.
5. For "mute_time" action, you MUST include "mute_duration" field (e.g. "1h", "6h", "24h", "3d", "7d").
6. "reason" must be factual, concise (max 2 sentences), and in the same language as the offending message.
7. Confidence reflects your certainty that this IS a violation (0.0 = not sure, 1.0 = certain).

SELECTION LOGIC for "selected_action":
- Choose from the rule's auto_actions array (ordered lightest to heaviest).
- For first-time violations: prefer lighter actions unless severity is xhigh or max.
- For users who continued after being warned in the conversation: escalate one level.
- For severity "max": always pick the heaviest action in the array.

OUTPUT FORMAT if violation detected:
{
  "verdict": "violation",
  "rule_violated": "<rule_id>",
  "offending_msg_id": <integer>,
  "offending_user_id": <integer>,
  "confidence": <float 0.0-1.0>,
  "severity": "<low|medium|high|xhigh|max>",
  "selected_action": "<warning|mute|mute_time|kick|ban>",
  "mute_duration": "<string or null>",
  "reason": "<factual explanation max 2 sentences>"
}

OUTPUT FORMAT if no violation:
{
  "verdict": "clean",
  "confidence": <float 0.0-1.0>,
  "reason": "<1 sentence>"
}
```

### User Message (JSON Payload per Evaluasi)

```json
{
  "group": {
    "chat_id": -100123456789,
    "title": "TCF Gaming Indonesia"
  },
  "conversation": [
    {
      "msg_id": 5997,
      "user_id": 799,
      "name": "Budi",
      "username": "budi_gamer",
      "text": "ada yang tau cara upgrade kernel ga?",
      "reply_to": null,
      "timestamp": "2026-07-11T13:00:00Z",
      "has_media": false
    },
    {
      "msg_id": 5998,
      "user_id": 800,
      "name": "Siska",
      "username": null,
      "text": "cek channel kernel dev bro",
      "reply_to": 5997,
      "timestamp": "2026-07-11T13:00:15Z",
      "has_media": false
    },
    {
      "msg_id": 5999,
      "user_id": 801,
      "name": "KeyMaster",
      "username": "keymaster_vip",
      "text": "OPEN KEYBOX VVIP!! Keybox exclusive premium kami sudah teruji di 500+ device. Garansi aktif PlayIntegrity & strong. Harga mulai 15rb/bulan. Daftar sekarang!",
      "reply_to": null,
      "timestamp": "2026-07-11T13:00:45Z",
      "has_media": false
    }
  ],
  "rules": [
    {
      "rule_id": "keybox",
      "severity": "max",
      "auto_actions": ["kick", "ban"],
      "description": "Keyboxes are FREE and open-source credentials. Strictly prohibited: selling/reselling keyboxes, promoting paid keybox services, labeling modules as VVIP/PREMIUM/EXCLUSIVE to charge money. Any commercialization of keyboxes = immediate ban. Community guidance: keyboxes are public and free, never pay for them."
    },
    {
      "rule_id": "promotion",
      "severity": "low",
      "auto_actions": ["warning", "mute", "kick"],
      "description": "Members are not allowed to promote products, services, or other groups without prior admin approval."
    },
    {
      "rule_id": "scam-ripper",
      "severity": "max",
      "auto_actions": ["kick", "ban"],
      "description": "Fraudulent activities (scam) or avoiding transaction responsibilities (ripper). Any form of financial fraud or deceptive transactions results in permanent removal."
    }
    // ... semua rules ai_enforceable = True (20 rules)
  ]
}
```

### Catatan Penting untuk Payload

1. **`conversation`**: Maksimal 10 pesan terakhir. Tidak perlu lebih — AI butuh konteks, bukan seluruh riwayat.
2. **`has_media`**: `true` jika pesan punya foto/video/stiker — untuk info AI bahwa ada media yang tidak bisa dilihatnya. Jika `has_media: true` dan `text: null`, AI seharusnya tidak bisa evaluate (hasilnya `clean` dengan catatan).
3. **`rules`**: Kirim HANYA rules dengan `ai_enforceable: true` — tidak semua 27, hanya 20 yang bisa di-evaluate dari teks.
4. **Order conversation**: Dari yang terlama ke yang terbaru (ascending timestamp).
5. **Field yang tidak perlu**: Jangan kirim field DB internal (ObjectId, timestamps DB, dll). Hanya yang relevan untuk konteks.

---

## 10. FORMAT JSON OUTPUT DARI AI

### Kasus: Violation Ditemukan

```json
{
  "verdict": "violation",
  "rule_violated": "keybox",
  "offending_msg_id": 5999,
  "offending_user_id": 801,
  "confidence": 0.96,
  "severity": "max",
  "selected_action": "ban",
  "mute_duration": null,
  "reason": "User KeyMaster explicitly sells keyboxes with VVIP/PREMIUM labeling and subscription pricing (15rb/month), violating the rule that keyboxes must be free and open-source."
}
```

### Kasus: Mute Time

```json
{
  "verdict": "violation",
  "rule_violated": "spam-flooding",
  "offending_msg_id": 6012,
  "offending_user_id": 820,
  "confidence": 0.91,
  "severity": "low",
  "selected_action": "mute_time",
  "mute_duration": "1h",
  "reason": "User sent 8 identical promotional messages within 2 minutes, disrupting the discussion flow."
}
```

### Kasus: Clean

```json
{
  "verdict": "clean",
  "confidence": 0.97,
  "reason": "All messages are on-topic tech discussion with no rule violations detected."
}
```

### Validasi Output (Bot Harus Cek)

Sebelum bot eksekusi apapun, validasi JSON output AI:

```python
# Validasi wajib — jika gagal, treat as "clean" dan log error
assert output["verdict"] in ("violation", "clean")

if output["verdict"] == "violation":
    assert isinstance(output["rule_violated"], str)
    assert isinstance(output["offending_msg_id"], int)
    assert isinstance(output["offending_user_id"], int)
    assert 0.0 <= output["confidence"] <= 1.0
    assert output["severity"] in ("low", "medium", "high", "xhigh", "max")
    assert output["selected_action"] in ("warning", "mute", "mute_time", "kick", "ban")
    assert isinstance(output["reason"], str) and len(output["reason"]) > 0
    
    if output["selected_action"] == "mute_time":
        assert output["mute_duration"] is not None
        # Validasi format durasi: angka + unit (1h, 6h, 24h, 3d, 7d)
        assert re.match(r"^\d+[hd]$", output["mute_duration"])
    
    # Pastikan selected_action ada di auto_actions rule yang dimaksud
    rule = get_rule_by_id(output["rule_violated"])
    assert output["selected_action"] in rule["auto_actions"]
```

### Penanganan JSON Tidak Valid dari AI

AI terkadang mengirim JSON dengan karakter ekstra (```json, teks tambahan). Parsing harus robust:

```python
def parse_ai_response(raw: str) -> dict:
    # Strip code fences
    raw = re.sub(r"```(?:json)?\n?", "", raw).strip()
    # Extract JSON object saja
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in AI response")
    return json.loads(match.group())
```

---

## 11. ACTION FLOWS DETAIL

### 11.1 Flow `warning`

```
AI putuskan → warning
│
├─ Panggil: tcbot.modules.helper.workflows.warning_flow._execute_warn()
│           (fungsi yang sudah ada, tambah parameter: is_ai_triggered=True)
│
├─ DB: add_warn(user_id, chat_id, reason=ai_reason, admin_id=BOT_USER_ID)
│
├─ DB: increment warn_count → cek apakah == cfg.warn_limit
│   └─ Jika == limit: auto-escalate ke ban (flow ban existing berjalan)
│
├─ Pesan ke GRUP:
│   "⚠️ Moderasi Otomatis
│   @username mendapat peringatan.
│   Alasan: [ai_reason]
│   Rule: [display_name] | Peringatan ke-[N] dari [limit]"
│
└─ Log ke cfg.logs: minimal log, bukan alert penuh
```

### 11.2 Flow `mute` (Permanent)

```
AI putuskan → mute
│
├─ Telegram API: restrict_chat_member(
│     user_id=offending_user_id,
│     chat_id=chat_id,
│     permissions=ChatPermissions(can_send_messages=False),
│     until_date=None
│   )
│
├─ DB: log_mute(user_id, chat_id, reason, admin_id=BOT_USER_ID, duration_secs=None)
├─ DB: set_active_mute(user_id, until_date=None)
│
├─ Pesan ke GRUP:
│   "🔇 Moderasi Otomatis
│   @username telah di-mute secara permanen.
│   Alasan: [ai_reason]
│   Rule: [display_name]"
│
└─ Log ke cfg.logs: info log
```

### 11.3 Flow `mute_time` (Sementara)

```
AI putuskan → mute_time, duration = "6h"
│
├─ Parse duration: "6h" → timedelta(hours=6)
│   until_dt = datetime.utcnow() + timedelta(hours=6)
│
├─ Telegram API: restrict_chat_member(
│     user_id=offending_user_id,
│     chat_id=chat_id,
│     permissions=ChatPermissions(can_send_messages=False),
│     until_date=until_dt
│   )
│
├─ DB: log_mute(user_id, chat_id, reason, admin_id=BOT_USER_ID, duration_secs=21600)
├─ DB: set_active_mute(user_id, until_date=until_dt)
│
├─ Pesan ke GRUP:
│   "🔇 Moderasi Otomatis
│   @username di-mute selama 6 jam.
│   Alasan: [ai_reason]
│   Rule: [display_name]
│   Mute berakhir: 11 Jul 2026, 19:00 WIB"
│
└─ Log ke cfg.logs: info log
```

**Durasi yang Valid untuk AI (strict whitelist):**
`1h`, `3h`, `6h`, `12h`, `24h`, `2d`, `3d`, `7d`

Jika AI kirim durasi lain (e.g. `"forever"`, `"30m"`), bot fallback ke `1h` dan log warning.

### 11.4 Flow `kick`

```
AI putuskan → kick
│
├─ Telegram API: ban_chat_member(user_id, chat_id)
├─ Telegram API: unban_chat_member(user_id, chat_id, only_if_banned=True)
│   (user bisa join kembali — persis seperti kicking_flow.py yang ada)
│
├─ Opsional DB: log ke collection "kicks" (bisa minimal — user_id, chat_id, reason, timestamp)
│
├─ Pesan ke GRUP:
│   "👢 Moderasi Otomatis
│   @username telah di-kick dari grup.
│   Alasan: [ai_reason]
│   Rule: [display_name]"
│
└─ Log ke cfg.logs: info log
```

### 11.5 Flow `ban` (Federation-Wide)

```
AI putuskan → ban, confidence ≥ threshold
│
├─ Forward offending message ke cfg.proofs channel
│   proof_message_id = message_id hasil forward
│
├─ Panggil: _execute_ban() dari ban_flow.py (yang sudah ada)
│   Parameter baru perlu ditambahkan:
│     - is_ai_ban: bool = True
│     - ai_reason: str = output["reason"]
│     - proof_msg_id: int = proof_message_id
│     - trigger_user_id: int = BOT_USER_ID
│
├─ Di dalam _execute_ban():
│   ├─ Buat BanDoc:
│   │   - reason = ai_reason
│   │   - proof_message_id = proof_msg_id
│   │   - admin_user_id = BOT_USER_ID (bot, bukan manusia)
│   │   - is_active = True
│   │
│   ├─ Fan-out: ban user di semua active_groups()
│   │   (menggunakan fan_out() yang sudah ada — semaphore-bounded)
│   │
│   └─ Kirim ke cfg.logs channel:
│       Format khusus AI ban (lihat Bagian 15)
│       Dengan tombol: [Undo Ban] [Lihat Pesan Asli] [Lihat Bukti]
│
└─ Pesan ke GRUP tempat pelanggaran terjadi:
    "🚫 Moderasi Otomatis
    @username telah di-ban dari federasi TCF.
    Alasan: [ai_reason]
    Rule: [display_name]
    Untuk appeal: [link appeal]"
```

---

## 12. SISTEM TERJEMAHAN OTOMATIS (EN → ID)

### Masalah

Rules hanya disimpan dalam Bahasa Inggris di DB. Ketika user minta lihat rules via `/rules`, komunitas ini mayoritas berbahasa Indonesia, sehingga perlu terjemahan.

### Solusi: MyMemory API (Free, Tanpa API Key)

**MyMemory** dipilih karena:
- Gratis sepenuhnya hingga 1.000 permintaan/hari (tanpa API key)
- Dengan email parameter: 10.000 karakter/hari
- Tidak perlu autentikasi untuk penggunaan basic
- Mendukung EN → ID dengan baik

**Endpoint:**
```
GET https://api.mymemory.translated.net/get?q={text}&langpair=en|id
```

**Response:**
```json
{
  "responseStatus": 200,
  "responseData": {
    "translatedText": "teks terjemahan"
  }
}
```

### Flow Terjemahan

```
User ketik /rules di grup
│
├─ Bot cek Redis: "rule_translated:{rule_id}:id" ada?
│   ├─ Ada → langsung pakai dari cache (TTL 7 hari)
│   └─ Tidak ada:
│       │
│       ├─ Ambil content_en dari DB
│       ├─ Kirim ke MyMemory API
│       ├─ Simpan hasil ke Redis dengan key "rule_translated:{rule_id}:id"
│       └─ Tampilkan ke user
```

**Penting:** Terjemahan hanya terjadi untuk perintah `/rules` — bukan real-time. Rules sudah ada EN-nya, terjemahan adalah tambahan kenyamanan. Jika MyMemory gagal (timeout, rate limit), bot fallback ke EN tanpa error ke user.

### Batasan Terjemahan

- Terjemahan otomatis tidak sempurna untuk istilah teknis (FBAN, keybox, rootmodule)
- Istilah teknis dibiarkan dalam EN (tidak diterjemahkan)
- Terjemahan hanya untuk tampilan user — **tidak mempengaruhi ai_description** yang selalu EN

### Alternatif Jika MyMemory Tidak Cukup

| Library | Tipe | Limit | Kekurangan |
|---|---|---|---|
| MyMemory | Online API | 1.000 req/hari | Tergantung internet |
| argostranslate | Offline Python | Unlimited | Model ~100MB perlu download |
| GoogleTrans (unofficial) | Online | Unlimited (unstable) | Sering di-block |
| LibreTranslate (self-hosted) | Online/Offline | Unlimited | Perlu hosting sendiri |

**Rekomendasi**: MyMemory untuk sekarang. Jika volume naik, switch ke argostranslate (offline, tidak ada rate limit, tidak perlu API key).

---

## 13. SEEDING RULES KE DATABASE

### Kapan Seeding Terjadi

Satu kali saat bot pertama kali dijalankan — atau ketika collection `fed_rules` kosong. Setelah itu, rules dikelola via DB dan tidak pernah baca file `.md` lagi dalam operasional normal.

### Prasyarat

Setiap file `fed-rules/*.md` harus punya YAML frontmatter (perlu ditulis manual sekali untuk semua 27 file):

```yaml
---
rule_id: "cheat"
display_name: "Cheat & Hack"
severity: "xhigh"
auto_actions:
  - "warning"
  - "kick"
  - "ban"
ai_enforceable: true
ai_description: >
  Prohibited: maphack, wallhack, damage++, auto-targeting, aimbot, any unfair
  modification, sharing/discussing/promoting cheat tools. EXCEPTION: iPad View
  in PUBG/ML is allowed (no unfair advantage). Violations = immediate action.
---

**CHEAT**
... (konten EN asli)
```

### Proses Seeding

```python
async def seed_fed_rules(db: AsyncIOMotorDatabase) -> None:
    collection = db["fed_rules"]
    
    # Cek apakah sudah ada data
    if await collection.count_documents({}) > 0:
        logger.info("fed_rules already seeded, skipping")
        return
    
    rules_dir = Path("fed-rules")
    docs = []
    
    for md_file in sorted(rules_dir.glob("*.md")):
        # Parse frontmatter
        with open(md_file) as f:
            content = f.read()
        
        # Split frontmatter dan body
        parts = content.split("---", 2)
        if len(parts) < 3:
            logger.warning(f"No frontmatter in {md_file}, skipping")
            continue
        
        meta = yaml.safe_load(parts[1])  # parse YAML
        body_en = parts[2].strip()       # konten EN
        
        doc = {
            "rule_id":        meta["rule_id"],
            "display_name":   meta["display_name"],
            "severity":       meta["severity"],
            "auto_actions":   meta["auto_actions"],
            "ai_enforceable": meta["ai_enforceable"],
            "ai_description": meta["ai_description"],
            "content_en":     body_en,
            "is_active":      True,
        }
        docs.append(doc)
    
    if docs:
        await collection.insert_many(docs)
        # Buat index
        await collection.create_index("rule_id", unique=True)
        await collection.create_index("ai_enforceable")
        logger.info(f"Seeded {len(docs)} federation rules")
```

### Re-seeding / Update Rules

Untuk update rule setelah awal seeding (misalnya rule baru atau perubahan ai_description):

- Gunakan command admin di bot: `/admin_update_rule <rule_id>` — update field tertentu di DB
- Atau script CLI `python -m tcbot.scripts.update_rules` yang baca frontmatter terbaru dari file
- Setelah update DB, bot otomatis invalidate cache Redis untuk rule tersebut

---

## 14. COOLDOWN & RATE LIMITING AI

### Mengapa Cooldown Diperlukan

Tanpa cooldown, grup yang ramai bisa trigger AI call ratusan kali per menit, menyebabkan:
- Cost API tinggi
- Rate limit dari LLM provider
- Latency tinggi yang memblokir bot

### Implementasi Cooldown

**Per-grup cooldown: 30 detik**

```python
COOLDOWN_KEY = "ai_moderation:cooldown:{chat_id}"
COOLDOWN_TTL = 30  # detik

async def is_cooldown_active(chat_id: int) -> bool:
    return await redis.exists(COOLDOWN_KEY.format(chat_id=chat_id))

async def set_cooldown(chat_id: int) -> None:
    await redis.setex(COOLDOWN_KEY.format(chat_id=chat_id), COOLDOWN_TTL, 1)
```

### Sliding Window Context

Walaupun ada cooldown 30 detik, bot tetap **menyimpan context pesan** yang masuk selama cooldown. Ketika cooldown berakhir dan evaluasi berikutnya terjadi, context window mencakup semua pesan yang masuk sejak evaluasi terakhir (max 10 pesan).

Ini artinya tidak ada "celah" — user yang melanggar saat cooldown tetap akan tertangkap di evaluasi berikutnya.

### Rate Limiting Tambahan

- **Max AI calls per jam per bot instance**: 500 (safetynet)
- **Timeout per AI call**: 15 detik — jika timeout, tidak ada action
- **Max retry**: 0 — tidak ada retry. Gagal = skip, coba di evaluasi berikutnya

---

## 15. LOG CHANNEL & NOTIFIKASI ADMIN

### Format Pesan ke Grup (Setelah Action Dieksekusi)

```
🤖 Moderasi Otomatis

Pengguna @username [ID: 801] mendapat warning.

📋 Rule: Cheat & Hack
⚡ Alasan: User membagikan link download cheat maphack.
📊 Peringatan ke-2 dari 3

─────────────────
Tidak setuju? Hubungi admin grup.
```

```
🚫 Moderasi Otomatis

Pengguna @keymaster_vip [ID: 801] telah di-ban dari federasi TCF.

📋 Rule: Keybox & VVIP Sales  
⚡ Alasan: Menjual keybox dengan label VVIP dan harga berlangganan.
🔗 Appeal: [Ajukan Banding]
```

### Format Log ke cfg.logs Channel

**Untuk semua actions (info log):**
```
[AI MOD] ✅ Action Executed

Group  : TCF Gaming ID (-100123456789)
User   : KeyMaster (@keymaster_vip) [ID: 801]
Rule   : keybox (max severity)
Action : BAN (federation-wide)
Conf.  : 96%
Reason : Menjual keybox dengan label VVIP dan harga berlangganan.

[Lihat Pesan Asli] [Lihat Bukti] [Undo Ban]
```

**Untuk flag ke admin (confidence 0.75–0.89):**
```
[AI MOD] ⚠️ Review Required

Group  : TCF Gaming ID
User   : SomeMember (@some_user) [ID: 905]
Rule   : piracy (high severity)
Suggest: kick
Conf.  : 81%
Reason : User membahas download FKM illegal dengan link channel Telegram.

Preview Pesan:
"nah mending download FKM yang versi gratis aja, ada di t.me/..."

[✅ Approve Kick] [⬆️ Escalate to Ban] [❌ Ignore] [👁 Lihat Konteks]
```

**Untuk AI ban dengan bukti:**
```
[AI MOD] 🚫 Auto-Ban Executed

Group  : TCF Gaming ID
User   : KeyMaster (@keymaster_vip) [ID: 801]
Rule   : keybox (MAXIMUM severity)
Conf.  : 96%
Reason : Menjual keybox dengan label VVIP dan harga berlangganan (15rb/bulan).

⚠️  Ini adalah ban otomatis oleh AI. Verifikasi jika perlu.

[🔍 Lihat Bukti di #proofs] [↩️ Undo Ban] [📋 Lihat Appeal]
```

---

## 16. INTEGRASI DENGAN KODE YANG SUDAH ADA

### Prinsip Utama

**Tidak ada kode yang sudah ada yang dihapus atau diubah besar.** AI moderation adalah **lapisan baru** (`tcbot/modules/ai_moderation/`) yang memanggil fungsi-fungsi existing.

### File Baru yang Perlu Dibuat

```
tcbot/
├── modules/
│   ├── ai_moderation/              ← BARU: package AI moderation
│   │   ├── __init__.py
│   │   ├── handler.py              ← MessageHandler entry point
│   │   ├── context_builder.py      ← Build JSON payload
│   │   ├── ai_client.py            ← Panggil LLM API + parse response
│   │   ├── decision_router.py      ← Logic routing berdasarkan confidence
│   │   ├── action_executor.py      ← Wrapper panggil existing flows
│   │   └── seeder.py               ← Seed fed_rules ke MongoDB
│   └── ...
├── database/
│   └── fed_rules_db.py             ← BARU: CRUD untuk collection fed_rules
└── utils/
    └── translator.py               ← BARU: MyMemory API wrapper
```

### Fungsi Existing yang Dipanggil (Tidak Diubah)

| Fungsi Existing | Dipanggil Oleh AI Moderation Untuk |
|---|---|
| `ban_flow._execute_ban()` | Action `ban` |
| `muting_flow._execute_mute()` | Action `mute` dan `mute_time` |
| `kicking_flow.execute_kick()` | Action `kick` |
| `warning_flow._execute_warn()` | Action `warning` |
| `bans_db.create_ban()` | Buat BanDoc untuk AI ban |
| `mutes_db.log_mute()` + `set_active_mute()` | Record AI mute |
| `warns_db.add_warn()` + `warn_count()` | Record AI warning |
| `groups_db.active_groups()` | Fan-out ban ke semua grup |

### Modifikasi Minor yang Diperlukan pada Kode Existing

`ban_flow._execute_ban()` perlu parameter opsional baru:
```python
async def _execute_ban(
    ...,                              # semua parameter yang sudah ada
    is_ai_ban: bool = False,          # BARU
    ai_proof_msg_id: int | None = None,  # BARU
) -> ...:
    # Jika is_ai_ban = True, skip langkah BuildProof (sudah ada proof_msg_id)
    # Langsung gunakan ai_proof_msg_id sebagai proof_message_id di BanDoc
    ...
```

Tidak ada perubahan lain ke kode existing.

### Handler Registration

Di `tcbot/__main__.py`, tambah handler AI moderation dengan priority rendah (group tinggi = diproses terakhir):

```python
from tcbot.modules.ai_moderation.handler import ai_moderation_handler

app.add_handler(ai_moderation_handler, group=50)
# group 50 = setelah semua handler normal (group -1, 10, dll)
```

---

## 17. RULES YANG TIDAK BISA DI-ENFORCE AI

7 rules dengan `ai_enforceable: false` — ini tetap ada di DB untuk keperluan:
- Tampilan ke user via `/rules`
- Referensi manual admin
- Dokumentasi

| Rule | Kenapa Tidak Bisa AI | Penanganan |
|---|---|---|
| `fed-admin` | Ini aturan UNTUK admin, bukan member biasa | Human only |
| `admin-power` | Abuse of power butuh konteks organisasi | Human only |
| `group-admin` | Tentang perilaku admin internal | Human only |
| `group-ownership` | Tentang kepemilikan grup, tidak terdeteksi via chat | Human only |
| `nickname-pfp` | Butuh inspeksi visual profil | Human only |
| `fundraising` | Partial — AI bisa flag tapi tidak bisa verify transparansi | Flag to admin saja |

---

## 18. EDGE CASES & PENANGANAN ERROR

### 18.1 Pesan Hanya Media (Foto/Video Tanpa Teks)

```python
if not (message.text or message.caption):
    # Skip — AI tidak bisa evaluate
    return
```

### 18.2 Pesan dari Anonymous Admin (GroupAnonymousBot)

```python
ANONYMOUS_BOT_ID = 1087968824
if from_user.id == ANONYMOUS_BOT_ID:
    return  # Skip — sudah ada guard di extraction.py
```

### 18.3 AI Return JSON Invalid

```python
try:
    result = parse_ai_response(raw_output)
    validate_ai_output(result)
except (json.JSONDecodeError, AssertionError, KeyError) as e:
    logger.error(f"AI output invalid: {e} | raw: {raw_output[:200]}")
    return  # Tidak ada action, tidak crash bot
```

### 18.4 AI Timeout (> 15 Detik)

```python
try:
    result = await asyncio.wait_for(call_ai(payload), timeout=15.0)
except asyncio.TimeoutError:
    logger.warning(f"AI timeout for chat {chat_id}")
    return  # Skip, coba lagi di evaluasi berikutnya
```

### 18.5 User Sudah Kena Ban Aktif

```python
existing_ban = await bans_db.get_active_ban(user_id)
if existing_ban:
    return  # User sudah di-ban, skip evaluasi
```

### 18.6 AI Rekomendasikan Action yang Bukan di auto_actions Rule

Validasi wajib — jika `selected_action` tidak ada di `auto_actions` rule yang dimaksud, tolak dan tidak eksekusi:

```python
rule = await fed_rules_db.get_rule(output["rule_violated"])
if output["selected_action"] not in rule["auto_actions"]:
    logger.error(f"AI picked invalid action {output['selected_action']} for rule {rule['rule_id']}")
    return
```

### 18.7 Pesan Sudah Dihapus Sebelum AI Selesai

```python
try:
    await bot.forward_message(cfg.proofs, chat_id, offending_msg_id)
except MessageIdInvalid:
    # Pesan sudah dihapus, gunakan teks dari context sebagai fallback
    await bot.send_message(cfg.proofs, f"[Pesan dihapus]\nKonten: {offending_text}")
```

### 18.8 Grup Tidak Mengaktifkan AI Moderation

AI moderation bersifat opt-in per grup. GroupDoc di MongoDB perlu field tambahan:

```python
# Di GroupDoc (modifikasi minor)
"ai_moderation_enabled": bool  # default: False
```

Owner grup bisa aktifkan via command admin: `/admin_set_ai on/off`

---

## 19. KONFIGURASI BOT

Field baru yang perlu ditambah ke `cfg` (konfigurasi bot):

```python
# Di tcbot/config.py atau environment:

AI_API_URL: str          # URL LLM API endpoint
AI_API_KEY: str          # API key (dari secrets)
AI_MODEL: str            # e.g. "nvidia/nemotron-3-ultra-550b-a55b:free"
AI_TIMEOUT: int = 15     # Detik
AI_COOLDOWN: int = 30    # Detik per grup

# Confidence thresholds
AI_CONF_EXECUTE: float = 0.90   # Auto-execute action
AI_CONF_FLAG: float = 0.75      # Flag ke admin
AI_CONF_BAN_XHIGH: float = 0.87 # Auto-ban untuk severity xhigh
AI_CONF_BAN_MAX: float = 0.85   # Auto-ban untuk severity max

# Translation
MYMEMORY_EMAIL: str | None = None  # Opsional, tingkatkan limit ke 10k chars/hari
```

---

## 20. OUT OF SCOPE

Item-item berikut **tidak termasuk dalam PRD ini** dan tidak akan dibangun:

- Dashboard web untuk melihat AI moderation history
- Training / fine-tuning model AI sendiri
- Deteksi media (foto, video, stiker) — AI hanya teks
- Real-time terjemahan pesan member (bukan rules)
- Integrasi dengan platform eksternal (Discord, WhatsApp, dll)
- Auto-appeal system (appeal tetap manual via bot yang sudah ada)
- Statistik moderasi (berapa % AI vs manual, accuracy, dll) — mungkin fase berikutnya
- Perubahan pada sistem warn, ban, mute manual yang sudah ada

---

## RINGKASAN EKSEKUTIF

| Aspek | Keputusan |
|---|---|
| Actions yang tersedia | `warning`, `mute`, `mute_time`, `kick`, `ban` |
| Action yang dihapus | `fban` (digabung ke `ban` yang sudah federation-wide) |
| Severity levels | `low`, `medium`, `high`, `xhigh`, `max` |
| Rules storage | EN only di MongoDB, terjemahan ID on-demand |
| Terjemahan | MyMemory API (free, 1000 req/hari), cached di Redis 7 hari |
| Proof untuk AI ban | Forward pesan pelanggaran ke cfg.proofs channel |
| Confidence threshold | Auto-execute ≥ 0.90 | Flag ke admin 0.75–0.89 | Log saja < 0.75 |
| Cooldown per grup | 30 detik |
| Context window | 10 pesan terakhir per grup |
| Rules di-enforce AI | 20 dari 27 (7 butuh human judgment) |
| Integrasi kode existing | Zero breaking changes — AI adalah lapisan tambahan |
| Opt-in per grup | Ya — `ai_moderation_enabled` field di GroupDoc |

---

*PRD ini adalah dokumen hidup. Diskusikan schema DB final dengan Claude terpisah sebelum implementasi dimulai.*
