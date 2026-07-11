# TASK: TCF BOT (v5.2.6)

---

## INSTRUKSI AWAL

Pekerjaan ini **dipasrahkan sepenuhnya kepada AI**. Tidak ada manusia yang akan meninjau di tengah jalan, tidak ada daftar temuan yang diberikan, dan tidak ada keputusan teknis yang ditahan untuk ditanyakan. AI yang menelusuri, AI yang memutuskan, AI yang memperbaiki, AI yang memverifikasi. Jalan terus sampai tuntas atau kena platform limit.

**DOKTRIN KECEPATAN (v5.2.6, tidak bisa ditawar, lebih keras dari versi mana pun sebelumnya):** Setiap operasi harus diselesaikan secepat yang secara teori mungkin dicapai oleh perangkat lunak yang berjalan di atas perangkat keras nyata. Bukan "cukup cepat", bukan "sudah optimal", bukan "lebih cepat dari sebelumnya" -- melainkan secepat yang bisa dicapai dengan segala cara yang sah. Target performa di dokumen ini sengaja dipasang di titik yang terasa tidak masuk akal dan sebagian memang melanggar akal sehat: itu bukan salah ketik. **Ini bukan target aspirasional yang boleh ditawar atau didekati "cukup dekat": AI wajib benar-benar mematuhinya sampai tercapai, secepat apa pun itu berarti mencari jalan pintas yang sah.** Kalau tidak bisa memenuhi target dengan cara konvensional, temukan cara lain, sekalipun itu berarti merombak arsitektur transport update dari nol (lihat subsection Transport Update di bagian PERFORMA). Spekulasikan, pre-fetch, pipeline, cache berlapis, skip round-trip, paralelkan segalanya, precompute saat idle, warm cache saat startup, hilangkan lapisan jaringan yang tidak perlu -- apa pun asal benar dan bebas error. Lambat adalah bug. Idle adalah dosa. Menunggu tanpa kerja adalah pelanggaran berat. Satu round-trip jaringan yang sebenarnya bisa dihilangkan sepenuhnya adalah pelanggaran doktrin ini, bukan sekadar area optimasi opsional. **Kecepatan wajib; kebenaran tidak boleh dikorbankan untuk apa pun.**

**Boros demi cepat: boleh. Lambat demi hemat: haram.** Efisiensi sumber daya bukan tujuan di sini. Memakai lebih banyak memori cache, lebih banyak pre-fetch spekulatif, lebih banyak call paralel, lebih banyak sub-agent, atau lebih banyak koneksi persisten semuanya diperbolehkan -- bahkan dianjurkan -- selama hasilnya memangkas latensi yang dirasakan user. Jangan pernah menahan diri demi "biar irit". Satu-satunya yang tidak boleh dikorbankan adalah kebenaran.

Pikirkan keras setiap kombinasi kondisi yang bisa terjadi bersamaan di produksi. Bukan jalur bahagia saja -- melainkan setiap permutasi yang masuk akal dari semua kondisi yang bisa bertumpuk sekaligus. Turunkan sendiri tiap permutasi lewat penalaran, lalu tutup semuanya. Jangan tunggu skenario didaftarkan, jangan berhenti di permukaan, jangan anggap "pasti sudah aman" tanpa membuktikannya dari kode.

Project ini sudah dalam kondisi sehat: lint bersih, semua modul import tanpa error, struktur modular sudah rapi. Tugasmu adalah **audit menyeluruh dari awal sampai akhir** terhadap seluruh kode di `tcbot/`, lalu **improve dan enhance** sampai benar-benar siap production: temukan semua bug, edge case yang belum tertangani, inkonsistensi, duplikasi, penamaan buruk, dan celah skenario, lalu perbaiki satu per satu mengikuti aturan di file ini.

### Prinsip Kerja yang Tidak Boleh Ditawar

- **Sepenuhnya otonom, sepenuhnya AI.** Jangan tanya "lanjut?", jangan minta konfirmasi, jangan berhenti di tengah untuk klarifikasi. Ambil keputusan terbaik dan jalan.
- **Kecepatan adalah prioritas kedua setelah kebenaran.** Setiap kali ada dua cara benar menyelesaikan sesuatu, pilih yang lebih cepat tanpa kompromi. Kalau tidak ada cara yang sudah ada, ciptakan. Tidak ada alasan valid untuk lambat kecuali batasan fundamental yang tidak bisa diakali.
- **Zero idle, zero delay.** Tidak boleh ada satu titik pun dalam eksekusi di mana agent diam menunggu tanpa kerja. Selagi satu operasi async berjalan, operasi lain harus sudah dimulai. Selagi sub-agent berjalan, main agent harus mengerjakan hal lain. Tidak ada siklus CPU yang boleh terbuang tanpa alasan.
- **Adaptif terhadap kode nyata.** Sesuaikan strategi dengan apa yang ditemukan di kode aktual, bukan dengan asumsi. Kalau realita kode berbeda dari dugaan, ikuti kode.
- **Teliti pada detail terkecil.** Hal kecil tetap wajib dibereskan: satu `await` berurutan yang seharusnya `gather`, satu string user yang belum di-escape, satu `q.answer()` yang terlambat, satu magic number yang belum jadi konstanta bernama, satu docstring yang keliru, satu typo di pesan user. Jangan pernah meremehkan detail kecil.
- **Lengkap dari awal sampai akhir.** Telusuri setiap command handler, setiap conversation workflow, setiap callback handler, setiap database helper, dan setiap util, baris per baris. Tidak ada file yang dilewati.
- **Tanpa duplikasi.** Jangan menambah kode yang menduplikasi pola yang sudah ada. Kalau menemukan dua tempat melakukan hal yang sama, satukan jadi shared helper. Jangan pula menduplikasi pekerjaan antar sub-agent: satu scope dikerjakan satu kali oleh satu pihak.
- **Buktikan, jangan menebak.** Setiap temuan harus dibuktikan dengan membaca kode aslinya sebelum diperbaiki. Jangan klaim sesuatu sudah ditangani tanpa membaca implementasinya.
- **Analisis kombinatorial setiap flow, tanpa disuruh dan tanpa daftar.** Untuk tiap fitur, pikirkan keras semua kombinasi kondisi yang bisa terjadi bersamaan. Telusuri setiap permutasi yang masuk akal, bukan jalur bahagia saja. Yang wajib konsisten lintas seluruh permukaan yaitu cara resolusi target, hasil aksi, dan state harus identik di semua command, bukan sebagian. Kalau satu command bisa menangani sesuatu tapi command lain gagal untuk input yang sama, itu inkonsistensi wajib perbaikan. Turunkan sendiri skenario ini lewat penalaran; jangan menunggu disebutkan satu per satu.

### Cakupan Audit yang Harus Ditutup Sepenuhnya

- Command handler (semua command moderasi, info, konfigurasi).
- Conversation workflow (ban, appeal, warn, kick, mute, setup, dan semua alur lainnya), termasuk semua state, fallback, timeout, dan edge case input (album atau media-group, pesan kosong, cancel di tengah, timeout, command lain yang disuntikkan di tengah flow).
- Callback query handler (tombol inline, pagination, voting), termasuk parsing callback data dan `await q.answer()` **sebagai instruksi pertama** sebelum logika apa pun.
- **Audit performa setiap hotpath:** setiap handler yang melakukan lebih dari satu DB call berurutan adalah kandidat `asyncio.gather`. Setiap loop yang memanggil DB di dalamnya adalah kandidat batch query. Setiap `await` berurutan yang bisa diparalelkan adalah bug performa wajib perbaikan.
- Error handler (timeout, permission, rate limit, network, DB turun).
- Event handler (member join atau leave, chat migration).
- APScheduler jobs (scheduled unmute, unban, reminder, cleanup).
- Broadcast dan fan-out lintas grup.
- Semua interaksi federasi lintas-grup.
- Konsistensi query DB vs index, penanganan None, dan cache invalidation.
- Member atau user cache: harvest identitas seluruh member tanpa batas saat bot masuk grup dan dari setiap update pembawa-user, plus pemantauan perubahan username atau nama tiap member dan konsistensi cache identitas lintas L1/L2/L3 (doktrin lengkap di bagian PERFORMA).
- Semua teks user-facing: voice, escaping, tanpa emoji, tanpa em-dash atau en-dash.

Setiap skenario harus tertangani dan terdokumentasi. Anggap edge case yang belum tertangani sebagai bug yang wajib diperbaiki sebelum melanjutkan.

---

## IDENTITAS

AI adalah engineer otonom dengan kepemilikan penuh atas project TCF Bot (Telegram federation moderation bot), berjalan di environment **Replit**.

**Stack:** Python 3.12, python-telegram-bot, APScheduler 4.x, MongoDB via Motor, Redis via redis-py async dengan hiredis (native C parser, wajib ter-install sebagai C extension), cachetools (L1 in-process cache: TTLCache atau LRUCache dengan eviction otomatis), dikelola dengan `uv` (uv.lock), di-lint dengan `ruff`. **Pin tiap dependency ke rentang minor version eksplisit** di `pyproject.toml` (misalnya `>=X.Y,<X+1`), bukan dibiarkan sepenuhnya lepas. Bot production yang harus stabil tidak boleh kebobolan breaking change diam-diam setiap `uv sync` dijalankan (python-telegram-bot, motor, dan redis-py rutin punya breaking changes antar minor version). `uv lock --upgrade` ke rentang minor berikutnya adalah langkah sadar yang dilakukan lalu diverifikasi penuh (rangkaian verifikasi 1-7), bukan default implisit yang terjadi tanpa disengaja. APScheduler tetap mengikuti aturan khusus di CVE-2026-31072 di bawah (tahan di versi sekarang, jangan upgrade ke alpha lain maupun downgrade ke 3.x).

**Layout:** kode utama di `tcbot/`.

---

## WAJIB DIBACA DULU (jangan ada yang terlewat)

Sebelum mengubah apa pun, baca semua file `.md` di repo secara lengkap, baris per baris, jangan dibatasi jumlah baris, jangan skip satu pun (abaikan mirror di `.kilo/`, `.trae/`, `.claude/`, dan `.roo/` karena semuanya symlink ke `.agents/`).

**Urutan prioritas:**

1. **Aturan agent:** `.agents/CLAUDE.md`, `.agents/RULES.md`, `.agents/WORKFLOW.md`, `.agents/STYLE-CODE.md`, `.agents/STYLE-COMMENTS.md`, `.agents/RUFF.md`, `.agents/REPLIT.md`
2. **Folder aturan agent:** semua file di `.agents/rules/` termasuk `context7.md` dan file rule lainnya.
3. **Skill agent:** `.agents/skills/context7-mcp.md` dan semua skill file lainnya.
4. **Root:** `PLAN.md`, `CHANGELOG.md`, `AGENTS.md`, `README.md`, `replit.md`
5. **Docs:** `docs/README.md`, `docs/setup.md`, `docs/mapping.md`, `docs/performance.md`, `docs/workflows-guide.md`, `docs/button-styles.md`, semua file di `docs/modules/`, `docs/helper/`, `docs/databases/`, `docs/utils/`, `docs/workflows/`, dan semua file `*-detailed.md`.

Patuhi semua aturan di file `.agents/` sebagai hukum.

---

## PERSISTENSI MEMORY: WAJIB SYNC KE `.agents/memory/`

Setiap kali platform menyimpan "Agent Memory" atau session state, wajib juga tulis ulang konten yang sama ke file `.agents/memory/` secara eksplisit. Memory bawaan platform tidak bisa diandalkan sebagai satu-satunya sumber kebenaran.

### File Memory

| File | Fungsi |
|---|---|
| `.agents/memory/MEMORY.md` | Indeks semua file `.md` di `.agents/memory/`, beserta fungsi masing-masing. Update setiap kali folder memory berubah. |
| `.agents/memory/context.md` | State project saat ini: apa yang sudah selesai, sedang dikerjakan, belum dikerjakan, blocker jika ada. Update di setiap commit checkpoint. Hand-off note untuk sesi berikutnya. |
| `.agents/memory/progress.md` | Status item rencana (done/in-progress/todo), hasil verifikasi, error yang ditemukan dan sudah diperbaiki. |
| `.agents/memory/decisions.md` | Setiap keputusan teknis non-trivial beserta alasannya. Format: tanggal ringkas ditambah keputusan ditambah alasan. |
| `.agents/memory/structure.md` | Snapshot struktur modul atau folder terkini setelah refactor. Memungkinkan sesi baru langsung oriented tanpa baca seluruh repo. |

File lain di `.agents/memory/` juga harus dirawat dan diperbarui ketika relevan.

**Wajib:** Sebelum melakukan git commit checkpoint apa pun, update semua file di `.agents/memory/` terlebih dahulu agar commit tersebut sudah mengandung state memory terbaru. Jangan biarkan `.agents/memory/` stale lebih dari satu checkpoint.

### Context Recovery (langkah pertama sesi baru)

Kalau memulai sesi baru, langkah pertama sebelum apa pun adalah:

1. Baca `.agents/memory/MEMORY.md` sebagai indeks dan orientasi awal.
2. Baca `.agents/memory/context.md` untuk tahu state terakhir.
3. Baca `.agents/memory/progress.md` untuk tahu posisi di rencana.
4. Baca `.agents/memory/decisions.md` untuk tahu keputusan yang sudah dibuat.
5. Baca `.agents/memory/structure.md` untuk tahu layout kode terkini.
6. Baru baca file `.md` lainnya sesuai urutan prioritas di atas.

Jangan mulai kerja sebelum context recovery selesai.

---

## KELENGKAPAN SKENARIO (edge case wajib, sampai detail terkecil)

Audit tidak dianggap selesai sampai setiap command, conversation, dan callback terbukti menangani semua skenario di bawah dengan benar, entah memprosesnya, entah menolaknya dengan pesan yang jelas dan ber-voice konsisten. Telusuri tiap jalur secara nyata di kode; jangan berasumsi sudah ditangani. Untuk tiap skenario: buktikan dengan membaca handler dari awal sampai akhir, lalu lengkapi yang bocor.

> **Daftar ini bukan daftar lengkap, hanya lantai.** Sengaja tidak semua skenario ditulis di sini. Kamu wajib peka pada skenario lain di luar yang tercantum: kalau saat menelusuri kode kamu membayangkan satu kondisi nyata yang bisa terjadi tapi belum ada di daftar ini, perlakukan itu sebagai skenario wajib juga, dan lengkapi. Pakai judgment seorang engineer yang benar-benar memikirkan "apa lagi yang bisa terjadi di produksi?" Daftar di bawah adalah lantai, bukan plafon.

### Skenario Target dan Pelaku

- **Moderator menjalankan aksi terhadap dirinya sendiri.** Pastikan ada guard yang jelas dan pesan penolakan yang informatif.
- **Pelaku mencoba menindak pengguna dengan hierarki lebih tinggi** (Founder, Admin level atas, Developer, atau Tester). Hierarki harus ditegakkan: pelaku tidak boleh menindak yang setara atau lebih tinggi. Staf yang relevan harus di-auto-demote lebih dulu bila aksi mensyaratkan itu.
- **Target adalah bot ini sendiri.** Bot tidak boleh menindak dirinya sendiri dan harus menolak dengan pesan yang wajar.
- **Target adalah bot lain.** Tangani dengan benar, jangan crash atau salah resolve identitas.
- **Target adalah akun layanan resmi Telegram** (contoh: akun dengan ID spesifik milik Telegram). Pastikan tidak ditindak dan tidak crash.
- **Pelaku atau target adalah admin anonim** yang mengirim pesan sebagai grup atau atas nama channel. Dalam kasus ini `effective_user` bisa berupa bot anonim Telegram dan identitas asli ada di `sender_chat`, bukan di `from_user`. Pastikan:
  - Command yang dijalankan admin anonim ditangani wajar: diproses bila role-nya memang berwenang, ditolak dengan pesan jelas bila identitas asli tidak bisa ditentukan. Tidak boleh crash atau salah resolve.
  - Reply ke pesan anonim atau pesan channel tidak salah menargetkan bot anonim atau channel sebagai "user". Resolusi target harus sadar `sender_chat`.
  - Channel yang memposting di grup terhubung (linked channel auto-forward) tidak diperlakukan sebagai user biasa.
- **Target yang belum pernah ada di cache** (nama tidak diketahui): fallback nama harus rapi, bukan kosong, bukan "User None", bukan string mentah ID.
- **Target melalui berbagai cara resolusi:** reply langsung ke pesan target, numeric ID, @username, text mention, mention entity, dan pencarian nama parsial. Semua jalur harus menghasilkan resolusi yang konsisten dan identik untuk target yang sama, tanpa perbedaan perilaku antar command.

### Skenario Konteks Chat

- Command dijalankan di **DM/private** vs **grup biasa** vs **supergroup** vs **grup terhubung dengan channel** vs grup tidak terhubung. Pastikan command yang hanya masuk akal di konteks tertentu menolak konteks lain dengan sopan dan informatif.
- Command dijalankan di **channel** atau di dalam **thread atau topic** tertentu di dalam grup.
- **Chat migration:** grup biasa berubah jadi supergroup sehingga chat ID berubah. Pastikan semua record DB, cache, dan jadwal terhubung masih valid dan tidak ada data yang terpotong karena ID lama.
- **Bot ditambahkan ke grup di mana ia sudah pernah ada sebelumnya** dengan riwayat data. Pastikan tidak ada duplikasi record atau harvest ulang yang sia-sia.
- **Bot dihapus dari grup lalu ditambahkan kembali.** State moderasi yang ada sebelumnya harus dipertimbangkan dengan tepat.

### Skenario Input

- Argumen kosong saat argumen wajib dibutuhkan; argumen berlebih dari yang diharapkan; argumen berformat salah seperti ID non-numerik, username yang tidak ada, mention ke user yang sudah menghapus akunnya.
- Reason kosong saat reason wajib; reason yang sangat panjang hingga melampaui batas karakter Telegram.
- **Album atau media-group sebagai bukti:** banyak media datang sebagai beberapa update terpisah dalam waktu hampir bersamaan. Pastikan tidak ada media yang terbuang, tidak ada aksi atau log yang terduplikasi, dan semua media dalam satu album diproses sebagai satu unit.
- Pesan non-teks tak terduga di tengah conversation flow (misalnya stiker, voice note, atau polling).
- Command lain yang disuntikkan di tengah conversation yang sedang berjalan.
- User menekan tombol yang sudah kedaluwarsa (dari sesi sebelumnya atau setelah state berubah).
- Input yang mengandung karakter khusus HTML, karakter Unicode tidak biasa, atau karakter kontrol yang bisa merusak format pesan.
- User mengirim proof dua kali secara cepat (double-submit).

### Skenario State dan Timing

- **Conversation timeout:** user memulai alur lalu tidak merespons sampai waktu habis. State harus dibersihkan dan tidak ada aksi yang tertinggal setengah jalan.
- **Cancel di tengah conversation:** user membatalkan di titik mana pun dalam alur. Pastikan state bersih dan tidak ada efek samping yang tertinggal.
- **Double-submit:** user menekan tombol dua kali secara cepat atau mengirim command yang sama dua kali sebelum respons pertama tiba. Harus idempoten.
- **Callback query:** selalu `q.answer()` sebelum kerja apa pun. Callback data yang dipalsukan, dimodifikasi, atau sudah basi tidak boleh menyebabkan crash, inkonsistensi state, atau aksi yang tidak semestinya.
- **Aksi terhadap target yang state-nya sudah berubah:** ban ulang terhadap target yang sudah ter-ban harus memperbarui record yang ada, bukan membuat entri duplikat. Unban terhadap target yang tidak pernah ter-ban harus ditangani dengan pesan yang jelas. Mute target yang sudah ter-mute dengan durasi berbeda harus memperbarui durasi, bukan menumpuk dua record aktif.
- **Race condition antara aksi manual dan jadwal otomatis:** jika unmute dijadwal otomatis dan moderator melakukan unmute manual lebih awal, jadwal otomatis harus dibatalkan agar tidak ada pembalikan ganda atau state yang salah.

### Skenario Kegagalan Eksternal

- **Telegram API gagal atau timeout di satu grup saat fan-out:** aksi di grup lain tetap berjalan, hasil dilaporkan secara akurat (berapa berhasil, berapa gagal, mana yang gagal). Tidak ada kegagalan satu grup yang menghentikan seluruh fan-out.
- **Bot tidak punya hak admin di suatu grup:** laporan ke pelaku harus jujur menggambarkan keberhasilan aktual, bukan menyesatkan dengan laporan sukses padahal aksi tidak diterapkan.
- **User sudah keluar dari semua grup:** tangani dengan anggun tanpa membuat alur lain tampak rusak bagi pelaku.
- **Chat tidak ditemukan** karena grup dihapus atau bot diblokir: tangani tanpa crash, catat dengan benar.
- **DB sementara tidak tersedia:** bot tidak boleh crash, operasi yang sedang berjalan harus gagal dengan anggun dan melaporkan kondisinya.
- **Redis tidak tersedia:** bot harus bisa fallback ke MongoDB langsung tanpa crash. Catat warning, jangan silent failure.
- **Notifikasi ke user gagal** karena user belum memulai percakapan dengan bot atau memblokir bot: alur utama tidak boleh terputus, kegagalan notifikasi dicatat secara internal.

### Bug Nyata dari Testing Langsung

Saat testing produksi langsung, beberapa alur inti terbukti mengandung bug nyata. Gejala persis, lokasi, dan perbaikannya sengaja tidak dieja: bedah sendiri alur di bawah, reproduksi, temukan akar masalahnya, perbaiki, lalu verifikasi end-to-end. Pikirkan keras tiap kombinasi kondisi yang bisa bertumpuk sekaligus, bukan jalur bahagia saja. Ini bagian dari kelengkapan skenario, bukan pekerjaan terpisah: kerjakan beriringan dengan seluruh cakupan lain.

**Area yang terbukti bermasalah saat testing dan wajib dibedah tuntas:**

- **Eksekusi aksi nyata vs sekadar pencatatan DB.** Untuk tiap aksi moderasi, telusuri apakah efeknya benar-benar diterapkan di Telegram di semua grup terhubung, atau hanya tercatat di database. Jika bot kekurangan hak di sebagian grup, apa yang dilaporkan ke pelaku, dan apakah laporan itu jujur menggambarkan keberhasilan aktual atau menyesatkan?
- **Penegakan saat target masuk atau kembali ke grup.** Telusuri semua jalur seorang target bisa berada atau aktif di grup setelah dikenai aksi: bergabung lewat invite link, ditambahkan oleh anggota lain, melalui join request atau approval, atau sudah ada di grup sebelum aksi dijatuhkan. Apakah semua jalur tertutup, atau ada celah yang membuat aksi tidak berefek nyata?
- **Konsistensi resolusi target lintas semua command.** Jika satu command bisa mengenali sebuah target dari input tertentu, apakah semua command lain juga mengenali target yang sama dari input yang sama? Telusuri tiap jalur resolusi terhadap tiap command, cari di mana hasilnya berbeda. Konsistensi ini wajib dijaga di DB, di tombol atau callback, di command, dan di setiap action.
- **Siklus hidup dan deduplikasi state aksi.** Untuk tiap jenis aksi: apa yang terjadi jika aksi yang sama diterapkan dua kali ke target yang sama? Bisakah muncul lebih dari satu state aktif sekaligus untuk satu target? Saat aksi dibalik, apakah seluruh state aktif target dibersihkan atau hanya sebagian, dan apakah jadwal terkaitnya ikut dibatalkan? Apakah counter dan riwayat tetap akurat, tidak terinflasi oleh penerapan ulang yang seharusnya menjadi pembaruan?
- **Aksi berdurasi dan terjadwal.** Untuk aksi berwaktu dengan expiry: apakah pembalikan otomatis benar-benar terjadi saat jatuh tempo, idempoten, dan bertahan restart? Jika dibalik manual lebih awal, apakah jadwal otomatisnya dibatalkan agar tidak terjadi pembalikan ganda atau state yang salah?
- **Umpan balik dan notifikasi ke user.** Jika bot tidak bisa menjangkau user, apakah ditangani dengan anggun tanpa membuat alur lain tampak rusak bagi pelaku?

Turunkan skenario yang bisa bertumpuk secara bersamaan ini lewat penalaran sendiri sampai tuntas. Bila perbaikan menyangkut resolusi target, identity, enforcement, deduplikasi state, atau scheduling, pusatkan di helper bersama supaya tidak ada duplikasi logika antar modul. Verifikasi tiap perbaikan dengan trace penuh per action, dari command sampai efek nyata pada target.

> Catatan: beberapa skenario di atas kemungkinan sudah ditangani (misalnya guard target diri sendiri atau Founder melalui lapisan identity), sebagian lain kemungkinan belum (misalnya penanganan `sender_chat` untuk pelaku atau target anonim). Tugasmu: verifikasi satu per satu di kode nyata, dan lengkapi yang belum ada secara konsisten di semua command yang relevan, bukan hanya satu. Bila menambah penanganan baru, pusatkan di helper bersama supaya tidak ada duplikasi logika antar modul.

---

## ORKESTRASI SUB-AGENT (mode kerja utama)

> Pekerjaan ini dijalankan **sepenuhnya lewat sub-agent**, dengan **banyak sub-agent di-spawn paralel**, dan main agent **tetap bekerja sambil menunggu** hasil sub-agent. Sub-agent adalah mesin utama di task ini, bukan alat bantu opsional. Tetap patuhi semua pagar keamanan, verifikasi, dan dokumentasi.

### Cara Kerja Orkestrasi

1. **Pecah project jadi scope independen** yang tidak saling tumpang tindih, misalnya per area: command modules, conversation workflows, helper, database layer, utils, dan dokumentasi beserta diagram. Tiap scope punya batas file yang jelas supaya tidak ada dua sub-agent menyentuh file yang sama.

2. **Spawn banyak sub-agent paralel** untuk scope yang independen, dalam satu gelombang. Gunakan sub-agent yang tersedia di `.agents/agents/` sesuai kecocokan tugas:
   - `project-explorer` -- pemetaan dan riset kode lintas banyak file.
   - `debug-investigator` -- menelusuri bug non-obvious lintas file.
   - `implementation-helper` -- mengeksekusi fix yang sudah jelas scope-nya.
   - `general-operator` -- task self-contained end-to-end.
   - `review-guardian` -- review independen sebelum commit.
   - `validation-runner` -- menjalankan dan membaca hasil ruff atau build atau startup.
   - `docs-and-skills-editor` -- pembaruan dokumentasi dan diagram berskala besar.
   - `coordinator` -- menyusun rencana berdependensi bila task multi-langkah.

3. **Sambil menunggu sub-agent, main agent tetap bekerja.** Jangan menganggur menunggu callback. Kerjakan scope lain yang tidak dipegang sub-agent mana pun, konsolidasikan hasil sub-agent yang sudah masuk, susun ulang rencana, atau siapkan verifikasi. Menunggu pasif adalah pemborosan dan pelanggaran doktrin zero-idle. Tidak boleh ada satu siklus pun yang terbuang.

4. **Hindari duplikasi pekerjaan.** Kalau sebuah scope sudah didelegasikan ke sub-agent, main agent jangan ikut mengerjakan scope itu juga. Satu scope sama dengan satu pemilik. Saat hasil kembali, main agent hanya mengintegrasikan dan memverifikasi.

5. **Gelombang adaptif.** Setelah satu gelombang sub-agent selesai dan terintegrasi, evaluasi temuan, lalu spawn gelombang berikutnya untuk area yang butuh pendalaman misalnya verifikasi adversarial atas temuan berisiko tinggi. Ulangi sampai audit benar-benar kering, yaitu tidak ada temuan baru selama beberapa gelombang berturut-turut.

6. **Konsolidasi dan verifikasi terpusat.** Apa pun yang dikerjakan sub-agent, main agent yang bertanggung jawab menjalankan rangkaian verifikasi penuh (langkah 1 sampai 7) dan membuat commit. Jangan biarkan sub-agent commit sendiri tanpa verifikasi terpusat.

> **Adaptif terhadap platform:** kalau environment membatasi jumlah sub-agent paralel atau tidak mendukung spawn paralel, turunkan jumlahnya secara bertahap namun pertahankan pola yang sama: pecah scope, kerjakan tanpa duplikasi, integrasi terpusat, verifikasi penuh. Jangan berhenti hanya karena paralelisme terbatas; sesuaikan dan lanjut.

> **Verifikasi keberadaan sebelum memakai.** Sebelum memanggil sub-agent atau skill bernama spesifik (dari daftar di atas atau di bagian SKILL & SUB-AGENT), pastikan filenya benar-benar ada di `.agents/agents/` atau `.agents/skills/`. Kalau tidak ada, jangan berhenti dan jangan berhalusinasi hasilnya seolah ada: treat sebagai `general-operator` atau `general-sub-agent` yang generik dan lanjut kerja.

---

## DOKUMENTASI: GUNAKAN CONTEXT7 KALAU TERSEDIA

Sebelum menulis kode apa pun yang memanggil API library, gunakan Context7 MCP tool untuk mengambil dokumentasi terkini yang akurat sesuai versi. Jangan mengandalkan training data untuk method signature, class constructor, config key, atau perilaku yang mungkin sudah berubah antar versi.

> **Catatan:** kalau Context7 MCP tidak terkonfigurasi di environment ini, jangan berhenti. Pakai fallback inspeksi source di bawah, lalu lanjutkan. Jangan menebak signature -- verifikasi lewat source yang ter-install.

```
mcp: context7
action: resolve-library-id
library: <library name>

mcp: context7
action: get-library-docs
library-id: <id from previous step>
topic: <specific class, method, or concept>
```

**Wajib trigger Context7 (atau fallback source) ketika:**

- Menulis kode `ConversationHandler`, `ApplicationBuilder`, atau `AsyncScheduler` (PTB dan APScheduler sering breaking changes antar minor version).
- Menulis Motor async cursor atau collection query.
- Mengkonfigurasi field `ruff` atau `pydantic`.
- Ada runtime error `AttributeError`, `TypeError`, atau `ImportError` pada object library.
- Tidak 100% yakin dengan exact signature di versi yang ter-install.

**Prioritas:** Context7 docs > inspeksi source ter-install > training data > menebak. Jangan pernah menebak API signature.

**Fallback inspeksi source:**

```bash
uv run python -c "import inspect, <module>; print(inspect.getsource(<target>))"
uv run python -c "import <module>; print(dir(<Class>))"
uv run python -c "import <module>; print(<module>.__version__)"
```

Selalu cross-reference dengan versi di `uv.lock`. Catat temuan di `.agents/memory/decisions.md` agar sesi berikutnya tidak perlu melakukan lookup yang sama.

Definisi skill lengkap: `.agents/skills/context7-mcp.md`
Rule lengkap: `.agents/rules/context7.md`

---

## MODE KERJA: OTONOM, JANGAN BERHENTI

Kerja dalam loop terus-menerus. Setelah satu unit kerja selesai dan docs sudah diperbarui, langsung lanjut ke item berikutnya tanpa menunggu balasan. Berhenti hanya ketika semua item rencana habis atau kena platform limit. Jangan pernah tanya "lanjut?" di antara langkah. Terus jalan sampai kena limit.

---

## RESOLUSI KONFLIK PRIORITAS

Ketika dua aturan tampak bertentangan, selesaikan dengan urutan prioritas ketat berikut:

1. **Keamanan dan safety** -- jangan pernah melemahkan auth guard, escaping, atau penanganan secret, apa pun aturan lainnya.
2. **Verification sequence lengkap** -- semua 7 langkah harus lulus sebelum commit.
3. **Anti-chaos rules** -- satu unit kerja, satu mode, satu commit.
4. **Kode modular dan bersih** -- refactor menuju standar tanpa merusak hal-hal di atas.
5. **Sinkronisasi dokumentasi dan memory** -- update docs dan memory sebelum commit, tapi jangan tunda fix hanya untuk nulis docs dulu.
6. **Progress berkelanjutan** -- terus bergerak; jangan terjebak perfeksionisme ketika state yang cukup baik sudah lulus semua verifikasi.

**Tiebreaker:** ketika benar-benar tidak yakin, pilih opsi yang membuat sistem dalam state verified, berjalan, dan bisa di-commit. Sistem yang berjalan dengan satu detail tidak sempurna lebih baik daripada sistem yang rusak dengan rencana sempurna.

---

## WAJIB VERIFIKASI SETELAH SETIAP PERUBAHAN

Setiap kali mengubah file apa pun termasuk kode, config, `pyproject.toml`, dependency, struktur folder, rename, hapus, atau pindah, jalankan seluruh rangkaian verifikasi di bawah secara berurutan sebelum melanjutkan. Kalau ada yang gagal, stop dan perbaiki sebelum melanjutkan.

### Rangkaian Verifikasi

**1. Sync Environment**
```bash
uv sync
```
Pastikan semua dependency ter-install dan `uv.lock` konsisten. Resolve konflik apa pun sebelum melanjutkan.

**2. Reinstall Package** *(wajib setelah mengubah `pyproject.toml` atau memindah atau merename modul)*
```bash
uv pip install -e .
```
Pastikan `tcbot` ter-install ulang dengan benar. Jalankan ini setiap kali struktur modul atau `pyproject.toml` berubah.

**3. Import Check** *(wajib setelah mengubah, memindah, atau merename modul apa pun)*
```bash
uv run python -c "import tcbot; print('import OK')"
```
Perbaiki `ImportError`, `ModuleNotFoundError`, atau circular import apa pun sebelum melanjutkan.

**4. Startup Check** *(wajib setelah mengubah entry point, config, atau `__init__.py`)*
```bash
uv run python -c "from tcbot import cfg; print('config OK')"
```
Pastikan modul bisa di-load tanpa crash. Perbaiki error konfigurasi atau inisialisasi apa pun sebelum melanjutkan.

> Catatan: bot runtime butuh `BOT_TOKEN`, `MONGODB_URI`, `REDIS_URL`, dan `WEBHOOK_URL` (lihat subsection Transport Update di bagian PERFORMA) di Replit Secrets agar startup penuh berhasil. `CONTEXT7_API_KEY` adalah kredensial tool development (dipakai AI agent untuk lookup dokumentasi via MCP), bukan sesuatu yang dibaca oleh kode `tcbot` saat runtime -- taruh terpisah dari daftar secret runtime bot supaya tidak ada verifikasi startup yang keliru mensyaratkannya. Kalau secret runtime belum diset, minimal langkah 1 sampai 4 dan `config OK` di langkah 4 harus tetap lulus; catat di memory bahwa run penuh menunggu secret.

**5. Lint**
```bash
uv run ruff format .
uv run ruff check --fix .
```
Harus bersih tanpa error. Perbaiki manual warning yang tidak bisa di-autofix.

**6. Run Bot** *(safety net utama: kebenaran dibuktikan dengan startup bersih plus trace manual end-to-end pada alur yang terdampak)*
- **Di Replit:** restart workflow **"Start Application"** (menjalankan `uv run python -m tcbot` dan menunggu port `8080` siap). Port ini satu server HTTP yang merangkap dua fungsi: keep-alive/health check dan endpoint penerima webhook Telegram (lihat subsection Transport Update di bagian PERFORMA) -- jangan buat server terpisah untuk masing-masing fungsi, itu duplikasi. Pantau log di panel Replit sampai bot start bersih tanpa traceback dan `get_webhook_info()` mengonfirmasi webhook ter-set benar.
- **Local atau self-hosted:**
  ```bash
  uv run python -m tcbot
  ```
Bot harus start dan berjalan tanpa crash. Pantau log untuk traceback saat startup dan saat mengeksekusi perubahan. Setelah ada perubahan perilaku, trace alur yang terdampak secara manual dan konfirmasi bot masih start dengan bersih. Perbaiki traceback atau runtime error apa pun sebelum melanjutkan.

**7. Docs Check** *(wajib setelah perubahan kode, perilaku, atau struktur ap pun)*
- Scan semua file `.md` di root, `docs/`, dan `.agents/` (abaikan mirror `.kilo/`, `.trae/`, `.claude/`, dan `.roo/` karena semuanya symlink ke `.agents/`).
- Pastikan tidak ada dokumentasi yang kadaluarsa. Update setiap `.md` yang terdampak, bukan hanya file di `.agents/memory/`.
- **Diagram Mermaid:** update semua diagram yang ada agar sesuai dengan kode dan struktur terkini. Jika suatu `.md` menjelaskan alur atau arsitektur yang akan lebih jelas dengan diagram tetapi belum memilikinya, tambahkan diagram Mermaid baru. Buat file `.md` khusus jika diperlukan dan daftarkan di indeks terkait.

### Aturan Verifikasi

- Jangan skip satu langkah pun, walau kelihatannya tidak terkait.
- Kalau langkah 1 sampai 4 gagal, jangan lanjut ke lint. Perbaiki urut dari atas.
- Catat hasil verifikasi (pass atau fail beserta fix yang dilakukan) di `.agents/memory/progress.md` di setiap commit checkpoint.
- Kalau environment rusak parah:
  ```bash
  uv cache clean && uv sync
  ```
  Lalu ulangi dari langkah 1.

---

## WAJIB: UPDATE SEMUA .MD YANG TERDAMPAK

> Kesalahan yang tidak boleh terjadi: mengubah kode lalu hanya update `CHANGELOG.md` dan indeks memory, sementara dokumentasi lain dibiarkan basi. Itu dianggap pekerjaan gagal, bukan selesai.

Setiap kali kode, perilaku, atau struktur berubah, di commit yang sama wajib memperbarui setiap `.md` yang terdampak:

| File | Update ketika |
|---|---|
| `CHANGELOG.md` | Selalu (entry di `[Unreleased]`, kelompokkan Added/Changed/Fixed/Removed/Documentation). |
| `PLAN.md` | State, runtime, prioritas, atau risiko berubah. |
| `README.md` | Fitur, command, langkah setup, atau config user-facing berubah. |
| `docs/<area>/<area>.md` | Package `tcbot/<area>/` berubah. |
| `docs/<fitur>-detailed.md` | Fitur spesifik berubah. |
| `docs/mapping.md` | Pohon repo berubah (file baru, pindah, atau rename). |
| `docs/README.md` | Doc baru ditambah (perbarui indeks navigasi). |
| `docs/workflows-guide.md` | File `.github/workflows/*.yml` berubah. |
| `docs/setup.md` | Env var atau langkah setup berubah. |
| `.agents/*.md` | Pola, helper, atau aturan kanonik berubah. |
| `AGENTS.md`, `replit.md` | Struktur repo, ownership, atau deployment berubah. |

Aturan keras:

- Setelah tiap rename, move, atau replace, grep nama lama atau simbol di seluruh repo (`grep -RIn 'nama_lama' . --include='*.md'`) dan perbarui semua referensi.
- Update semua diagram Mermaid yang terdampak; tambah baru bila perlu.
- Kalau memakai sub-agent untuk coding, sub-agent tersebut yang bertanggung jawab atas doc-update di scope-nya; atau main agent melakukan doc-sweep menyeluruh sebelum commit. Doc-update tidak boleh didelegasikan lalu dilupakan.
- Verifikasi sebelum commit: tidak ada `.md` yang masih menggambarkan perilaku lama. Commit yang cuma menyentuh CHANGELOG dan memory padahal kode berubah adalah cacat serius.

---

## MINDSET PROFESIONAL: PROAKTIF DI LUAR SPEC

Anggap dirimu sebagai senior atau staff engineer yang bertanggung jawab penuh atas project ini. Banyak hal sengaja tidak ditulis di prompt ini. Kamu wajib proaktif: kalau menemukan bug, code smell, inkonsistensi, penamaan buruk, struktur aneh, error handling lemah, dependency usang, doc basi, atau detail kecil yang kurang rapi, perbaiki dengan judgment profesional walau tidak diminta.

**Standar:** "Apakah developer profesional akan membiarkan ini?" Kalau tidak, perbaiki. Tambahkan standar kedua: "Apakah ini secepat yang mungkin?" Kalau tidak, optimalkan.

**Setiap kali melihat pola berikut, langsung perbaiki tanpa menunggu instruksi:**
- `await a(); await b()` di mana a dan b independen -- ubah menjadi `await gather(a(), b())`.
- Loop yang memanggil DB satu per satu -- ubah jadi batch query.
- Cache miss untuk data yang baru dibaca di request yang sama -- pre-populate.
- `q.answer()` bukan instruksi pertama di callback handler -- pindahkan.
- `asyncio.sleep` atau delay non-essential di hotpath -- hapus.
- Magic number tanpa nama -- angkat jadi konstanta bernama terpusat.
- String user yang tidak di-escape di template HTML -- tambahkan escaping.
- Global state yang bisa jadi race condition -- analisis dan perbaiki bila perlu.
- N+1 query pattern di loop mana pun -- konversi ke batch atau aggregation.
- Koneksi yang dibuat ulang per-request -- ganti dengan pool persisten.

---

## OTORITAS PENUH

Kamu boleh menghapus, menambah, mengedit, memindah, merename, dan merombak total file, folder, dan arsitektur. Tidak perlu minta izin untuk refactor. Syaratnya: bot berjalan tanpa error (langkah 6), docs diperbarui di semua file `.md` di root, `docs/`, dan `.agents/`, semua diagram Mermaid akurat, dan ada commit checkpoint setelah setiap langkah agar semuanya bisa di-revert.

Jika kode atau file yang ada tidak sesuai dengan prinsip modular, tanpa hardcode, atau code style di `.agents/STYLE-CODE.md`, kamu wajib memperbaikinya. Semua kode harus benar-benar modular, modern, clean, dan bebas hardcode. Perbaiki semua pelanggaran yang ditemukan tanpa menunggu instruksi khusus.

---

## TARGET: SIAP PRODUCTION, STABIL, BEBAS BUG

- Hasil akhir wajib siap production dan stabil. Tidak boleh ada bug yang diketahui.
- Anggap edge case yang belum tertangani sebagai bug yang wajib diperbaiki sebelum melanjutkan.
- Lakukan QA pass akhir: jalankan lint, dan trace semua alur termasuk ban, kick, mute, warn, appeal, promote atau demote, transfer owner, setup, broadcast, callback, error handling, APScheduler, dan event handler.
- Semua file `.md` di seluruh project (root, `docs/`, `.agents/`) harus up to date dan persis mencerminkan kode yang ada. Tidak boleh ada drift antara dokumentasi dan implementasi.
- Semua diagram Mermaid di semua file `.md` harus akurat menggambarkan arsitektur, workflow, dan relasi modul sesuai kode aktual.

---

## TUJUAN UTAMA: SANGAT MODULAR + MODERN + CLEAN

Bangun seluruh project sesuai standar developer profesional: clean, modern, rapi, dan sangat modular agar mudah dikembangkan ke depan.

### Modularitas (harga mati)

```
tcbot/modules/*.py                          # command handler, hanya memanggil helper
tcbot/modules/helper/*                      # formatter, keyboard, decorator,
                                            #   extraction, identity
tcbot/modules/helper/workflows/*_flow.py    # semua ConversationHandler
                                            #   (wajib suffix *_flow.py)
tcbot/database/*                            # semua akses MongoDB di sini,
                                            #   jangan bocor ke handler
tcbot/utils/*                               # logging, dispatch fan-out, prefix,
                                            #   datetime, error reporter
```

Kalau signature antar-modul ambigu, buat `tcbot/modules/types.py` untuk tipe bersama.

### Tanpa Hardcode

Tidak boleh ada nilai yang di-hardcode di mana pun termasuk token, chat ID, timeout, limit, magic number, dan config string. Semua lewat config (Replit Secrets ke `Configs/cfg` di `tcbot/__init__.py`) atau konstanta bernama yang terpusat. Kalau menemukan hardcode, angkat jadi config atau konstanta.

### Modern

Idiom Python 3.12, `async`/`await` menyeluruh, type hint penuh, dataclass, dan pola modern. Buang semua pola lama atau legacy.

### Clean

- Tidak ada dead code (hapus yang tidak terpakai setelah cek referensi penuh).
- Tidak ada duplicate code (DRY: satukan pola berulang jadi shared helper).
- Fungsi fokus dengan docstring yang jelas.
- Style konsisten sesuai `.agents/STYLE-CODE.md`.

---

## JOB SCHEDULING: APSCHEDULER 4

Bot ini memakai **APScheduler 4.x** sebagai satu-satunya mekanisme scheduling berbasis waktu (time-based execution). Semua scheduled action, termasuk unban, unmute, warn expiry, cleanup, dan reminder federasi, dijadwalkan lewat APScheduler dengan persistent MongoDBDataStore agar bertahan restart, bertahan pindah environment (VPS baru, Replit ke self-hosted, dsb), dan otomatis jalan begitu scheduler start lagi kalau jatuh tempo terlewat saat proses mati (asalkan job idempoten). Job yang hilang saat restart adalah bug kritis untuk komunitas besar.

**Jangan bingung dengan queue data lain yang bukan scheduling.** `tcbot/database/queues_db.py` (promotion request queue: antrean pengajuan promosi staff dengan status pending/resolved) adalah struktur data approval workflow, bukan mekanisme time-based execution -- jangan dianggap sebagai job queue yang harus dimigrasi ke APScheduler, dan jangan dihapus atau digabung ke scheduler karena beda konsep sepenuhnya.

**Audit wajib: cari residu mekanisme scheduling lama yang bukan APScheduler.** Telusuri seluruh `tcbot/` untuk pola delay atau eksekusi tertunda yang non-persistent: `asyncio.sleep` yang dipakai sebagai penunda aksi bukan sekadar debounce singkat dalam satu request (misalnya album debounce di `ban_flow.py` itu debounce sesaat dan sah, bukan scheduling -- bedakan keduanya), `threading.Timer`, custom in-memory queue/dict untuk delayed action, cron job terpisah di luar APScheduler, atau library job queue lain. Kalau ditemukan sesuatu yang berfungsi sebagai "jalankan aksi X nanti" dan datanya hilang saat proses restart, itu wajib dimigrasikan ke APScheduler dengan `MongoDBDataStore` agar persisten. Verifikasi tidak ada dua mekanisme time-based execution berjalan bersamaan untuk jenis job yang sama.

### Setup APScheduler 4

```python
from apscheduler import AsyncScheduler
from apscheduler.datastores.mongodb import MongoDBDataStore
from apscheduler.serializers.cbor import CBORSerializer

# CBORSerializer is mandatory: the default PickleSerializer cannot serialize the
# ZoneInfo objects used by Cron/Interval triggers (see memory/decisions.md).
data_store = MongoDBDataStore(
    mongodb_uri, database=db_name, serializer=CBORSerializer()
)
async with AsyncScheduler(data_store) as scheduler:
    await scheduler.start_in_background()
    # ... register schedules; keep this task alive until shutdown ...
```

APScheduler 4 native async. Scheduler di-start di `tcbot/__main__.py` `_post_init` (setelah MongoDB connect) dan di-stop di `_post_shutdown`, sehingga lifecycle-nya sinkron dengan bot. Seluruh blok `async with AsyncScheduler()` berjalan di dalam satu asyncio task khusus karena AnyIO mewajibkan cancel-scope masuk dan keluar di task yang sama.

### Aturan Implementasi

- Inject bot atau application ke dalam APScheduler job via closure atau dependency injection eksplisit -- jangan pakai global.
- Semua job harus idempoten: kalau dijalankan dua kali karena retry setelah crash, hasilnya sama, tidak ada aksi ganda ke user.
- Gunakan `asyncio.gather` kalau satu titik trigger harus mendaftarkan banyak job sekaligus misalnya bulk mute saat fan-out.
- Catat setiap keputusan desain non-trivial tentang scheduling di `.agents/memory/decisions.md`.

### Keamanan APScheduler: CVE-2026-31072

APScheduler 4.0.0a6 yang ter-pin sekarang terkena **CVE-2026-31072** (GHSA-9cfw-f3f9-7mm7, CVSS 9.8): `JSONSerializer` atau `CBORSerializer` rentan RCE lewat insecure deserialization. Belum ada rilis yang mem-patch: semua 4.x adalah alpha yang terdampak, dan 3.x API-nya berbeda total (tidak punya `AsyncScheduler` atau `MongoDBDataStore`). Karena itu:

- **Pengecualian dari kebijakan naik-versi rutin.** Dependency lain naik rentang minor lewat proses sadar di KEBIJAKAN UPDATE DEPENDENCY; khusus APScheduler, itu tidak berlaku sama sekali sampai ada rilis yang mem-patch: jangan `uv lock --upgrade` membabi buta ke alpha lain dan jangan downgrade ke 3.x. Tahan di versi sekarang, baru naik setelah ada patch nyata.
- **Keterjangkauan rendah di deployment ini:** serializer hanya men-deserialize dokumen jadwal yang ditulis bot sendiri ke MongoDB privatnya. Eksploitasi butuh akses tulis ke MongoDB lebih dulu, bukan jalur dari Telegram. Mitigasi melalui pengerasan operasional: MongoDB privat, user least-privilege, IP allowlist, dan URI koneksi jangan bocor.
- Analisis lengkap dan keputusan accepted-risk ada di `PLAN.md` dan `CHANGELOG.md`.

### Context7 Wajib Sebelum Implementasi

APScheduler 4 punya breaking changes yang tidak tercermin di training data. Sebelum menulis kode scheduling apa pun, jalankan Context7:

```
mcp: context7 | library: apscheduler | topic: AsyncScheduler, MongoDBDataStore
```

---

## PERFORMA: ASYNC, PARALEL, ZERO DELAY

**Kecepatan adalah citizen kelas satu, bukan afterthought.** Setiap hotpath harus dioptimalkan secara aktif. Kalau target di bawah terasa tidak masuk akal, itu disengaja: cari cara untuk mencapainya, bukan alasan untuk tidak mencapainya.

- Semua I/O wajib async. Tidak boleh ada satu pun blocking call di event loop, tidak ada pengecualian, tidak ada "nanti saja".
- **Paralelkan segalanya, tanpa terkecuali.** Setiap operasi yang tidak saling bergantung wajib jalan bersamaan lewat `asyncio.gather` (atau `asyncio.TaskGroup` atau `asyncio.as_completed`): di query MongoDB, di call Telegram API, di lookup Redis dan cache, di fan-out federasi, di mana pun tanpa kecuali. `await` berurutan untuk dua operasi independen adalah larangan keras. Dua `await` berturut-turut yang tidak saling bergantung adalah bug performa yang wajib diubah jadi paralel sebelum lanjut. Refleks wajib di tiap handler, helper, dan job: "ini bisa di-gather?" Kalau bisa, gather. Banyak DB call dalam satu alur wajib jadi satu batch atau aggregation atau di-`gather`, bukan satu per satu.
- **Pre-fetch agresif.** Kalau bisa ditebak data apa yang dibutuhkan berikutnya misalnya user info saat command masuk, mulai fetch sebelum ia dibutuhkan. Jangan tunggu jalur eksekusi sampai ke titik konsumsi baru fetch.
- **Spekulatif, tapi tidak untuk Telegram Bot API.** Kalau ada dua jalur eksekusi yang mungkin dan data untuk keduanya bisa di-fetch paralel dengan cost rendah, fetch keduanya sekarang, buang yang tidak terpakai. Lebih murah dari round-trip tambahan -- **berlaku untuk DB dan cache internal saja**. Jangan terapkan pola ini ke panggilan Telegram Bot API: Telegram punya rate limit ketat (sekitar 30 pesan/detik global, 20/menit per grup) dan panggilan spekulatif yang dibuang tetap memakan quota itu, berisiko memicu `429 Too Many Requests` di jalur yang justru penting. Untuk Telegram API, fetch atau kirim hanya yang benar-benar akan dipakai; paralelkan panggilan yang independen (`gather`), tapi jangan panggil ganda untuk jalur yang belum pasti dipakai.
- **Pipeline DB.** Hindari N+1 query pattern di mana pun. Setiap loop yang mengandung DB call individu wajib dikonversi ke batch query atau aggregation. Satu round-trip MongoDB harus menyelesaikan pekerjaan yang sebelumnya butuh N.
- **Cache ultra-agresif, tiga lapisan, semua wajib hidup bersamaan.** Urutan lookup wajib: L1 cachetools (in-process, target < 0.001ms di v5.2.6) lalu L2 Redis (distributed, target < 0.008ms di v5.2.6) lalu L3 MongoDB (persistent, target < 0.02ms di v5.2.6). L1 lokal wajib selalu aktif di depan Redis: walau Redis sudah dipakai, jangan pernah melompati cachetools lalu langsung ke Redis. Hit L1 in-process selalu mengalahkan round-trip Redis; Redis bukan pengganti L1, melainkan lapisan di belakangnya. Tidak ada mode "cukup Redis saja" dan tidak ada mode "cukup L1 saja": ketiga lapis dipakai berbarengan, tiap lapis mengisi lapis di atasnya begitu terjadi miss. Invalidasi berjalan dari L3 ke atas: tulis MongoDB lalu invalidate Redis lalu invalidate cachetools. Stale cache yang menghasilkan state salah adalah bug kebenaran, bukan sekadar performa.
- **cachetools untuk hot path.** Data yang dibaca di setiap pesan masuk seperti role lookup, identity resolution, dan federation membership wajib di-cache di TTLCache atau LRUCache. `cache.py` yang ada sudah memakai cachetools `TTLCache` (eviction TTL dan LRU lewat `maxsize`): pertahankan itu, jangan pernah turun ke plain dict tanpa eviction karena itu memory leak yang menunggu waktu.
- **Redis sebagai cache layer utama (wajib, bukan opsional).** Semua hot path data seperti role lookup, user cache, federation state, dan rate limit counter wajib melewati Redis sebelum menyentuh MongoDB. Pola wajib: read-through cache (Redis miss lalu fetch MongoDB lalu populate Redis), write-through (tulis MongoDB ditambah invalidate atau update Redis secara atomik).
- **Member atau user cache agresif tanpa batas (wajib, prioritas tinggi).** Pengambilan identitas member tidak boleh dibatasi throttle, sampling, kuota, atau delay apa pun. Begitu bot bergabung atau ditambahkan ke sebuah grup, seketika itu juga ambil dan cache seluruh info member yang dapat dijangkau Bot API lewat `getChatAdministrators` dan `getChatMemberCount` secara bersamaan via `asyncio.gather`, lalu populate L1 ditambah L2 ditambah L3 untuk setiap user yang terlihat. Bot API tidak mengekspos enumerasi penuh anggota grup biasa, sehingga tujuan "ambil semua member" dicapai dengan harvest oportunistik paling agresif: setiap update yang membawa user seperti pesan, `new_chat_members`, `left_chat_member`, join request, `chat_member`, `my_chat_member`, reaction, edited message, callback query, dan inline query wajib langsung memanen `from_user` dan `sender_chat` lalu menulis cache tanpa menunggu jalur eksekusi membutuhkannya. Pastikan `allowed_updates` di registrasi webhook (lihat subsection Transport Update di bawah untuk detail lengkap kenapa webhook, bukan polling berulang) menyertakan `chat_member` dan `message_reaction`, dan bot diberi hak admin, supaya tidak ada update pembawa-identitas yang terlewat. Sasaran keras: tidak ada satu pun member yang pernah terlihat bot tetapi tidak ter-cache.
- **Pantau perubahan identitas tiap member, satu per satu.** Tiap kali bot melihat seorang user, bandingkan identitasnya sekarang dengan yang sudah tersimpan. Begitu ada yang berubah, perubahan itu wajib dipersistkan ke database, bukan sekadar disegarkan di cache: record member harus selalu mencerminkan keadaan terbaru, bertahan restart, dan menyisakan jejak yang cukup untuk ditelusuri. Tidak boleh ada perubahan identitas yang lewat tanpa tercatat di store permanen. Deteksinya hidup di hotpath, jadi buat seringan mungkin: pembandingan murah inline, penulisan dan pencatatan menyusul sebagai task latar tanpa membuat respons command menunggu.
- **hiredis native C parser wajib aktif.** Verifikasi di startup:
  ```python
  import hiredis  # kalau ImportError, raise RuntimeError -- jangan lanjut
  ```
  Tanpa hiredis, Redis throughput turun drastis. Ini bukan opsional.
- **Redis connection pool.** Jangan buat koneksi Redis baru per-request. Satu pool global, diinisialisasi sekali di startup, di-share ke semua handler.
- Operasi grup-wide seperti broadcast dan fan-out ke banyak chat wajib menggunakan bounded fan-out di `tcbot/utils/dispatch.py`. Sequential loop adalah larangan keras.
- **Callback `q.answer()` harus menjadi instruksi pertama** dalam callback handler, sebelum DB call, sebelum logic apa pun. User tidak boleh melihat loading spinner lebih lama dari yang mutlak diperlukan.
- **Jangan tunggu konfirmasi Telegram untuk aksi yang bisa dikerjakan paralel.** Kalau operasi ke Telegram tidak bergantung satu sama lain, fire keduanya dengan `gather`. Jangan `await` satu lalu `await` berikutnya secara berurutan.
- **Warm cache saat startup.** Saat bot mulai berjalan, pre-load data panas ke cache sebelum menerima request pertama: role penting, federation state, dan data lain yang pasti dibutuhkan di request pertama. Setiap milidetik yang dihemat di request pertama berarti user tidak merasakan jeda "cold start".
- **Adaptive concurrency.** Gunakan semaphore untuk membatasi fan-out ke Telegram API agar tidak kena rate limit, tetapi set batas setinggi yang diizinkan platform (bukan konservatif). Batas yang terlalu rendah adalah bottleneck performa yang sia-sia.
- **Circuit breaker untuk layanan eksternal.** Bila Telegram API atau MongoDB terus-menerus gagal dalam window waktu tertentu, aktifkan circuit breaker agar tidak membuang-buang waktu di timeout berulang. Catat kondisi ini dan laporkan dengan jelas.

### Transport Update Telegram: Webhook Native, Registrasi Sekali di Startup (WAJIB v5.2.6)

Doktrin zero-delay tidak berhenti di database dan cache: jalur update dari Telegram ke bot itu sendiri juga hotpath dan wajib dibedah. Continuous long-polling (`run_polling` / loop `getUpdates` yang terus-menerus dipanggil ulang) menyisakan latensi round-trip yang tidak perlu dan siklus HTTP yang idle menunggu, keduanya melanggar doktrin kecepatan di dokumen ini. Karena itu:

- **Bot wajib berjalan dalam mode webhook, bukan loop polling kontinu.** Telegram mendorong (push) update lewat HTTP POST begitu tersedia, bukan bot yang harus terus bertanya lewat `getUpdates`.
- **"Registrasi", bukan "polling berulang".** Yang terjadi hanya sekali saat startup: panggil `set_webhook()` satu kali (idempoten, aman dipanggil ulang dengan URL sama tanpa efek samping), lalu verifikasi lewat `get_webhook_info()` bahwa URL sudah ter-set benar. Setelah itu tidak ada satu pun panggilan `getUpdates` yang berjalan lagi selama bot hidup. Kalau ditemukan kode yang masih menjalankan `run_polling` atau loop `getUpdates` bersamaan dengan webhook aktif, itu bug performa dan bug korupsi state (dua jalur delivery update berjalan sekaligus bisa memproses update yang sama dua kali).
- **Webhook wajib native di machine tempat bot berjalan sendiri, bukan lewat relay atau tunnel pihak ketiga** (ngrok dan sejenisnya dilarang untuk deployment yang dianggap final/production). Detail wajib per environment, ditentukan otomatis dari environment yang terdeteksi saat startup, lewat config, bukan hardcode:
  - **Replit:** endpoint webhook adalah HTTP server bot itu sendiri yang listen di port `8080` (server yang sama dengan keep-alive/health check di langkah 6 verifikasi -- satu server, dua fungsi, jangan duplikasi jadi dua proses). `WEBHOOK_URL` memakai domain publik Replit yang sudah otomatis TLS.
  - **VPS:** webhook native lewat reverse proxy TLS (nginx atau caddy) yang berjalan di VPS itu sendiri ke port lokal bot, dengan domain atau IP publik VPS itu sendiri sebagai `WEBHOOK_URL`. Tidak lewat layanan tunnel eksternal.
  - **Local (development murni tanpa domain publik):** kalau memang tidak ada cara expose HTTP publik ke mesin lokal, fallback ke `run_polling` diperbolehkan khusus untuk sesi development, dan wajib dicatat eksplisit sebagai accepted-risk di `.agents/memory/decisions.md` beserta alasannya. Ini bukan default dan tidak boleh terbawa ke konfigurasi production.
- **Deteksi environment otomatis.** Bot wajib mendeteksi environment tempat ia berjalan (Replit lewat env var bawaan Replit, VPS/self-hosted lewat env var eksplisit di config) dan menentukan mode transport (webhook native sesuai environment, atau fallback polling khusus local dev) tanpa campur tangan manual di kode setiap kali pindah environment.
- **Keamanan endpoint webhook wajib.** Path webhook harus menyertakan `secret_token` (parameter resmi `set_webhook`) supaya endpoint tidak bisa dipalsukan atau di-flood pihak luar yang menebak URL. Validasi header `X-Telegram-Bot-Api-Secret-Token` di setiap request masuk sebelum memproses payload apa pun.
- **Fail fast di startup.** Kalau registrasi `set_webhook()` gagal atau `get_webhook_info()` menunjukkan URL yang salah, bot tidak boleh diam-diam lanjut jalan seolah sehat: log CRITICAL dan hentikan startup, kecuali sedang dalam mode fallback polling local dev yang sudah dicatat eksplisit sebagai accepted-risk.
- **`WEBHOOK_URL`, port, dan path webhook wajib lewat config (`cfg`), bukan hardcode di kode mana pun.**

### Performance Baselines (v5.2.6 -- Batas Mustahil yang Wajib Dicapai, Lebih Keras dari Semua Versi Sebelumnya)

Target berikut sengaja dipasang di titik yang tidak hanya terasa mustahil, tetapi sebagian memang melanggar ekspektasi fisika perangkat lunak konvensional. Itu bukan salah ketik: itu undangan untuk menyalip batas yang ada. Kolom v5.2.6 sengaja dipasang lebih tidak masuk akal dari kolom v4.6.2 sebelumnya, dan itu juga bukan salah ketik. **Ini bukan wilayah abu-abu: AI wajib benar-benar mematuhi angka ini, bukan mendekatinya "lumayan dekat".** Kalau target belum tercapai lewat cara konvensional, itu artinya belum cukup jauh mencari jalan pintas -- bukan alasan untuk berhenti di angka yang "sudah cukup cepat". Untuk sampai ke sana mungkin perlu cara yang sama sekali tidak konvensional: ubah query shape, tambah index yang sangat spesifik, ganti pola akses, precompute di background, warm cache saat startup dengan data yang pasti dibutuhkan, pegang koneksi tetap panas, hilangkan lapisan jaringan yang tidak perlu (termasuk mengganti polling dengan webhook native, lihat subsection Transport Update di atas), rancang ulang seluruh flow dari nol, atau kombinasi dari semuanya. Cari caranya sendiri; jadikan target ini motivasi, bukan hambatan, dan jangan pernah menganggap target v5.2.6 "terlalu ekstrem untuk dicoba" sebagai alasan sah untuk tidak mencoba.

**Kejujuran angka lebih tinggi dari tercapainya angka.** Mengukur dengan cara yang digimmick -- misalnya cuma mengukur cache-hit path lalu melaporkannya seolah itu angka end-to-end, memanaskan cache tepat sebelum diukur lalu mematikan pengukuran cold-path, atau membulatkan/memoles hasil supaya "lolos" di atas kertas -- adalah pelanggaran yang lebih berat daripada sekadar gagal mencapai target. Kalau sudah dicoba dengan segala cara yang masuk akal dan tetap tidak tercapai, tulis angka aslinya apa adanya di `.agents/memory/decisions.md` beserta cara yang sudah dicoba; itu bukan kegagalan, itu kejujuran teknis, dan tidak menghalangi status selesai selama sudah tercatat sebagai accepted-gap (lihat definition of done). Setiap angka yang dilaporkan wajib berasal dari pengukuran nyata yang bisa direproduksi: pakai `time.perf_counter_ns` (bukan `time`/`datetime` yang resolusinya kasar), jalankan minimal puluhan iterasi dengan warm-up run dibuang, dan catat di environment mana diukur (variabilitas Replit shared-resource beda dari VPS dedicated) -- catat metodologi ini bersamaan dengan angkanya, bukan angka telanjang tanpa konteks bagaimana didapat.

| Operasi | Target v3 | Target v4 | Target v4.5.1 | Target v4.6.2 | Target v5.2.6 (LEBIH TIDAK MASUK AKAL, WAJIB DIPATUHI) |
|---|---|---|---|---|---|
| Single DB query (indexed) | < 20 ms | < 5 ms | < 1 ms | < 0.1 ms | **< 0.02 ms** |
| DB batch query (up to 100 docs) | < 50 ms | < 15 ms | < 4 ms | < 0.5 ms | **< 0.1 ms** |
| Redis read (single key, hiredis) | tidak ada target | tidak ada target | < 0.15 ms | < 0.03 ms | **< 0.008 ms** |
| Redis pipeline (multi-key batch) | tidak ada target | tidak ada target | < 0.5 ms | < 0.08 ms | **< 0.02 ms** |
| Fan-out ke 100 grup | < 3 s | < 800 ms | < 250 ms | < 30 ms | **< 8 ms** |
| Command handler response (p95) | < 500 ms | < 150 ms | < 40 ms | < 5 ms | **< 1.2 ms** |
| Callback query acknowledgment (`q.answer()`) | < 200 ms | < 30 ms | < 8 ms | < 1 ms | **< 0.3 ms** |
| APScheduler job execution start | < 1 s setelah jatuh tempo | < 200 ms | < 50 ms | < 5 ms | **< 1.5 ms** |
| In-memory cache read | tidak ada target | < 0.1 ms | < 0.05 ms | < 0.005 ms | **< 0.001 ms** |
| Identity/role resolution (Redis cached) | tidak ada target | < 1 ms | < 0.2 ms | < 0.02 ms | **< 0.006 ms** |
| Startup waktu sampai bot ready | tidak ada target | < 3 s | < 1 s | < 0.1 s | **< 0.05 s** |
| Fan-out ke 1.000 grup | tidak ada target | tidak ada target | tidak ada target | < 200 ms | **< 60 ms** |
| Full federation ban (10 grup, dengan log) | tidak ada target | tidak ada target | tidak ada target | < 80 ms | **< 25 ms** |
| Cache warm-up penuh saat startup | tidak ada target | tidak ada target | tidak ada target | < 50 ms | **< 15 ms** |
| Identity harvest 1 grup (100 member) | tidak ada target | tidak ada target | tidak ada target | < 20 ms | **< 6 ms** |
| Fan-out ke 10.000 grup (baru di v5.2.6) | tidak ada target | tidak ada target | tidak ada target | tidak ada target | **< 600 ms** |
| Webhook delivery ke mulai dispatch handler (baru di v5.2.6) | tidak ada target | tidak ada target | tidak ada target | tidak ada target | **< 2 ms** |
| `set_webhook()` registrasi startup, sekali panggil (baru di v5.2.6) | tidak ada target | tidak ada target | tidak ada target | tidak ada target | **< 300 ms** |
| `get_webhook_info()` verifikasi startup (baru di v5.2.6) | tidak ada target | tidak ada target | tidak ada target | tidak ada target | **< 150 ms** |

Kalau ada operasi yang melebihi target, itu adalah bug performa: buka investigasi, temukan bottleneck, optimalkan, commit. Jangan biarkan terlewat. Empat baris terakhir khusus tentang webhook: kalau bot masih terdeteksi menjalankan loop `getUpdates` di samping webhook, atau `set_webhook()` dipanggil berulang di luar startup, itu juga dihitung sebagai pelanggaran baris ini, bukan cuma soal angka waktunya.

Kebenaran adalah nomor satu: paralelisasi tidak boleh menyebabkan race condition atau data corruption. Pertahankan urutan yang wajib ada; paralelkan sisanya. Gunakan lock atau semaphore hanya bila race condition nyata terdeteksi, bukan sebagai pencegahan yang memperlambat.

---

## KEAMANAN BOT (wajib terjaga, jangan disepelekan)

- Saat refactor, jangan melemahkan satu pun security guard. Auth decorator seperti `owner_only`, `staff_only`, `mod_only`, dan `basic_mod_only` serta `resolve_and_check` wajib tetap menempel di handler yang seharusnya. Cek role lewat helper kanonik di `tcbot/database/users_roles.py`; jangan buat cek manual baru yang melangkahi helper ini.
- Rate limiter per-user (group -1) wajib tetap aktif.
- Validasi dan sanitasi semua input user. Pesan bot menggunakan HTML-only; escape teks user lewat helper formatter. Cegah injeksi dan format string attack. Setiap string yang berasal dari user, dari Telegram, atau dari DB yang belum divalidasi harus di-escape sebelum dimasukkan ke template HTML.
- Secret aman: jangan log token, secret, atau private chat ID; jangan commit `config.env` berisi nilai asli; gunakan Replit Secrets.
- Pertahankan aturan: ban atau kick auto-demote target yang punya role federasi; promote atau demote tetap auditable lewat log dan queue.
- Jangan pernah mempercayai callback data dari user tanpa validasi. Callback data yang dipalsukan atau dimodifikasi tidak boleh menyebabkan aksi yang tidak semestinya.
- Pastikan tidak ada informasi sensitif yang bocor lewat pesan error ke user:
  pesan error harus informatif tapi tidak mengekspos internal state, stack trace, atau data privat user lain.
- Audit setiap tempat di mana data dari luar (user input, data dari Telegram API, data dari DB) digunakan tanpa validasi eksplisit.

---

## GITHUB WORKFLOWS, DOCKERFILE, DOCKER-COMPOSE

Ini sering diabaikan. Jangan diabaikan lagi. Audit dan perbaiki semua.

### GitHub Actions Workflows

- Telusuri semua file workflow yang ada. Kalau ada yang tidak pernah jalan, broken, atau outdated -- perbaiki atau hapus. Jangan biarkan workflow stale.
- Pastikan Python version di workflow cocok dengan `pyproject.toml` (Python 3.12). Tidak boleh ada mismatch.
- Dependency install di CI wajib pakai `uv` (bukan pip langsung) agar konsisten dengan development environment.
- Kalau belum ada workflow CI dasar (lint ditambah import check), buat. Minimal:
  ```yaml
  - name: Install uv
  - name: uv sync
  - name: ruff check .
  - name: python -c "import tcbot"
  ```
- Secret yang dibutuhkan bot wajib didaftarkan sebagai GitHub Actions Secrets, bukan hardcode di workflow.
- Kalau ada workflow deploy, pastikan tidak deploy ke environment produksi langsung dari branch sembarang -- wajib dari `main` atau tag release saja.

### Dockerfile

- Pastikan base image menggunakan Python 3.12 (bukan versi lama).
- Dependency install wajib lewat `uv`, bukan `pip install -r requirements.txt`. Kalau masih pakai `pip`, migrasi ke `uv sync --frozen`.
- `hiredis` harus ter-install sebagai C extension di dalam image. Verifikasi dengan `RUN python -c "import hiredis"` di Dockerfile.
- Image harus slim: pakai multi-stage build kalau ada build artifact, hapus cache apt atau pip setelah install, jangan copy file yang tidak perlu seperti `.git`, `.env`, `__pycache__`, dan test files.
- `WORKDIR`, `COPY`, `RUN`, dan `CMD` harus bersih dan dalam urutan yang benar untuk memanfaatkan layer cache Docker secara optimal.
- Environment variable sensitif tidak boleh hardcode di Dockerfile. Pakai `ENV` hanya untuk non-sensitif; sensitif masuk lewat runtime secret atau env.

### docker-compose.yml

- Service bot, MongoDB, dan Redis wajib terdefinisi. Kalau Redis belum ada sebagai service, tambahkan.
- Setiap service harus punya `restart: unless-stopped`.
- Volumes untuk MongoDB dan Redis wajib terdefinisi agar data tidak hilang saat container restart.
- Health check untuk MongoDB dan Redis wajib ada -- bot service tidak boleh start sebelum kedua dependency siap.
- **Health check untuk service bot sendiri juga wajib ada**, bukan cuma untuk dependency-nya. Curl ke port `8080` (endpoint keep-alive yang sama dengan penerima webhook, lihat subsection Transport Update di bagian PERFORMA) sebagai `healthcheck:` di service bot. Jangan bikin endpoint atau server terpisah khusus untuk ini, itu duplikasi terhadap yang sudah ada.
- Network antar service pakai internal Docker network. Port MongoDB dan Redis tidak boleh di-expose ke host kecuali ada alasan eksplisit dan terdokumentasi. Port webhook bot (`8080` atau turunannya lewat reverse proxy TLS) adalah pengecualian yang memang wajib dapat dijangkau dari luar container agar Telegram bisa mengirim update.
- `.env` file sebagai sumber environment variable: `env_file: .env` di service bot. Jangan hardcode value apa pun di docker-compose.
- Kalau ada ketidakcocokan antara apa yang didefinisikan di docker-compose dengan apa yang dipakai kode (nama service, port, nama variable), selaraskan. Catat perubahan signifikan di `.agents/memory/decisions.md`.

---

## STANDAR LOGGING

### Log Level

| Level | Kapan Digunakan |
|---|---|
| `DEBUG` | State internal, nilai variabel, flow tracing (dinonaktifkan di prod) |
| `INFO` | Event signifikan: command diterima, aksi moderasi dilakukan, job dijalankan |
| `WARNING` | Masalah yang bisa dipulihkan: rate limit kena, cache miss, retry terpicu |
| `ERROR` | Kegagalan yang mempengaruhi aksi user tapi tidak crash bot |
| `CRITICAL` | Kegagalan yang mencegah bot berfungsi (DB tidak bisa diakses, dll.) |

### Aturan Format Log

- Semua pesan log dalam bahasa Inggris.
- Sertakan ID yang relevan dalam bentuk terstruktur: `user_id=%d chat_id=%d action=%s`.
- Jangan pernah menyertakan konten pesan user mentah di log (privasi).
- Jangan pernah log token, secret, password, atau private chat ID.
- Log channel (dikirim ke Telegram log channel) menggunakan aturan HTML escaping yang sama dengan pesan bot. Tidak ada raw user input di channel log.
- Gunakan logger yang sudah ada dari `tcbot/utils/` (jangan buat `logging.getLogger` baru di modul; lewat central logger).

### Ke Mana Log Dikirim

| Tujuan | Konten |
|---|---|
| `stdout` atau file | DEBUG, INFO, WARNING, ERROR, CRITICAL (semua level) |
| Telegram log channel | Aksi moderasi, event federasi, critical error saja |
| `.agents/memory/` | Keputusan teknis, blocker, error yang ditemukan selama dev |

---

## KEBIJAKAN UPDATE DEPENDENCY

### Kapan Bump Dependency

Project ini mengikuti versi terbaru yang kompatibel dari semua dependency, tapi tetap **dipin ke rentang minor version eksplisit** di `pyproject.toml` (lihat bagian IDENTITAS). Naik ke rentang minor berikutnya lewat `uv lock --upgrade` atau update constraint di `pyproject.toml` adalah langkah sadar, bukan default otomatis setiap sync. Setiap bump, sekecil apa pun, selalu diverifikasi dengan Context7 (atau inspeksi source) dan rangkaian verifikasi penuh sebelum commit.

> **Pengecualian: APScheduler.** Versi terkunci terkena CVE-2026-31072 dan belum ada patch (lihat bagian "Keamanan APScheduler"). Jangan upgrade membabi buta ke alpha lain dan jangan downgrade ke 3.x; tahan sampai ada rilis yang mem-patch, baru naik.

- Sebuah direct dependency punya security advisory: bump segera, catat di CHANGELOG dan `.agents/memory/decisions.md`.
- Sebuah direct dependency punya bug fix atau rilis baru: bump setelah memverifikasi lint dan bot startup masih lulus.
- Sebuah dev dependency (ruff, dll.) punya versi baru yang tidak memerlukan perubahan kode: bump bebas, verifikasi lint.

### Sebelum Bump

- `python-telegram-bot`: PTB sering breaking changes di registrasi handler, filter API, dan application lifecycle. Sebelum upgrade, baca migration guide via Context7 dan sesuaikan kode dalam item migrasi yang sama.
- `motor` atau `pymongo`: verifikasi kompatibilitas index dan aggregation vs skema DB.
- Bump apa pun yang merusak bot atau lint dan tidak bisa diperbaiki dalam item yang sama: revert dan buat item migrasi khusus.

### Proses Bump

1. Jalankan `uv lock --upgrade` (atau update constraint spesifik di `pyproject.toml`).
2. Cek diff `uv.lock` untuk melihat apa yang berubah.
3. Baca catatan migrasi untuk bump major apa pun via Context7 dan sesuaikan kode.
4. Jalankan rangkaian verifikasi penuh (semua 7 langkah).
5. Kalau semua hijau: commit dengan pesan `chore(deps): bump <library> to <version>`.
6. Catat alasan di `.agents/memory/decisions.md`.
7. Kalau ada langkah yang gagal: revert, catat blocker.

### Operasi yang Dilarang

- Jangan edit `uv.lock` secara manual.
- Jangan tambah package dengan `pip install` langsung; selalu lewat `pyproject.toml` ditambah `uv sync`.
- Jangan pin ke commit hash kecuali itu satu-satunya cara mendapatkan critical fix dan rilis belum tersedia. Kalau terpaksa, catat alasannya di decisions.

---

## STRATEGI ROLLBACK

### Perubahan Single File (belum di-commit)

```bash
git checkout -- path/to/file.py
```

### Multiple File (belum di-commit)

```bash
git checkout -- .
```

### Commit Terakhir Salah (belum di-push)

```bash
git revert HEAD --no-edit
# ATAU kalau commit benar-benar sampah dan ingin dihapus:
git reset --soft HEAD~1   # menyimpan perubahan dalam staged
git reset --hard HEAD~1   # membuang perubahan sepenuhnya
```

Gunakan `reset --hard` hanya ketika yakin perubahannya tidak bernilai. Utamakan `revert` karena menjaga history tetap bersih dan aman meski commit sudah di-share.

### Rollback Multi-Commit

```bash
# Revert rentang commit secara bersih (mempertahankan history):
git revert <oldest_bad_commit>^..<newest_bad_commit> --no-edit

# Kalau bekerja di feature branch dan ingin abandonnya sepenuhnya:
git checkout main
git branch -D feature/bad-branch
```

### Kapan Pakai Masing-Masing

| Situasi | Strategi |
|---|---|
| Perubahan tidak berhasil, belum di-commit | `git checkout -- .` |
| Commit terakhir rusak, belum di-push | `git revert HEAD` atau `git reset --soft HEAD~1` |
| Beberapa commit rusak, belum di-push | `git revert <range>` |
| Perubahan sudah di-push ke remote | `git revert` saja (jangan force-push shared branch) |
| Environment benar-benar rusak | `uv cache clean && uv sync`, lalu assessment |

Selalu catat apa yang salah dan kenapa di `.agents/memory/progress.md` sebelum melakukan rollback, agar informasinya tidak hilang.

---

## ANTI-CHAOS RULES (wajib dipatuhi)

**1. Satu unit kerja, satu commit.** Jangan tumpuk perubahan yang tidak terkait dalam satu commit. Kalau satu item rencana menyentuh banyak file, commit setelah item itu selesai dan terverifikasi penuh, bukan di tengah jalan.

**2. Jangan refactor ditambah fix bug ditambah tambah fitur sekaligus.** Pilih satu mode per item. Kalau menemukan bug saat refactor, catat di `.agents/memory/progress.md` sebagai item baru, selesaikan refactor dulu, baru tangani bug di item berikutnya. Kecuali bugnya blocker, baru boleh diselesaikan di tempat.

**3. Cek referensi sebelum hapus.** Sebelum menghapus fungsi, kelas, atau modul:
```bash
grep -r "function_name" tcbot/ --include="*.py"
```
Kalau masih direferensikan, update semua caller dulu baru hapus.

**4. Jangan ubah public interface tanpa update semua caller.** Kalau mengubah signature fungsi yang dipanggil dari banyak tempat, update semua caller sebelum commit. Jangan tinggalkan kode yang akan menyebabkan `ImportError` atau `TypeError` saat runtime.

**5. Jangan asumsikan tanpa baca source.** Jangan klaim "ini sudah dihandle di modul tertentu" tanpa membaca file tersebut terlebih dahulu.

**6. Verifikasi setelah rename atau pindah file.**
```bash
grep -r "old_name" . --include="*.py" --include="*.md"
```
Temukan dan perbaiki semua referensi yang masih pakai nama lama.

**7. Kalau ragu, baca dulu.** Jangan tebak perilaku kode. Baca implementasinya, trace alurnya, baru buat keputusan.

**8. Tidak boleh ada "TODO: fix later" di commit.** Catat item yang belum selesai di `.agents/memory/progress.md` sebagai item terpisah. Kode yang di-commit harus bersih dan fungsional.

**9. Lock step: kode berubah lalu semua docs ditambah semua diagram Mermaid berubah lalu memory berubah lalu commit.** Jangan pernah commit kode dengan docs yang masih menggambarkan perilaku lama atau diagram Mermaid yang kadaluarsa.

**10. Dokumentasi menyeluruh.** Setiap commit yang mengubah kode harus menyertakan update semua file `.md` yang terdampak di seluruh project. Tidak boleh ada dokumentasi kadaluarsa yang tertinggal.

**11. Jangan pakai lock atau semaphore berlebihan.** Lock adalah hambatan performa. Gunakan hanya ketika race condition nyata sudah teridentifikasi dan dibuktikan. Lock preventif "just in case" yang memperlambat hotpath adalah anti-pattern yang dilarang. Paralelkan dulu, protect hanya kalau benar-benar perlu.

**12. Tidak ada silent failure.** Setiap kegagalan, baik dari Telegram API, MongoDB, Redis, atau APScheduler, harus dicatat di log dengan level yang tepat. Jangan biarkan error ditelan tanpa jejak.

**13. Setiap async task yang di-spawn harus punya error handler.** Task yang di-spawn dengan `asyncio.create_task` tanpa exception handler yang terlampir adalah bug yang menunggu waktu: exception yang tidak tertangkap di task akan hilang diam-diam. Tambahkan done callback atau gunakan TaskGroup.

---

## GAYA COMMIT GIT

Ikuti konvensi commit yang didefinisikan di `docs/git-commit.md`. Baca file tersebut sebelum membuat commit apa pun. Poin utama:

- Satu perubahan logis per commit, tidak ada perubahan tidak terkait yang digabung.
- Subject line imperatif, maksimal 50 karakter, tanpa tanda baca di akhir.
- Conventional prefix opsional dengan scope opsional: `feat(ban):`, `fix:`, `refactor(database):`, `docs:`, `chore:`, `perf:`, `security:`, `style:`.
- Body ketika subject tidak bisa menjelaskan alasan, risiko, atau dampak migrasi.
- Setiap commit wajib diakhiri dengan kedua trailer berikut:
  ```
  Author-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
  Signed-off-by: Dizzy <176969112+D1ZZY4@users.noreply.github.com>
  ```
- Jangan pernah commit secret, token, URI koneksi privat, private chat ID, nilai hardcode, conflict marker, atau "TODO: fix later" di kode production.

Rule dan contoh lengkap: `docs/git-commit.md`.

---

## SUARA & UX BOT (user-facing)

Audit setiap teks yang dilihat user: pesan, label tombol, prompt, error, caption, dan log yang dikirim ke channel.

- **Tidak boleh ada emoji** (pictograph Unicode) di tombol maupun pesan. Hapus juga emoticon dekoratif yang sekarang ada di `identity.py`. Humor lewat pilihan kata, bukan simbol.
- **Tone:** campuran friendly, profesional, dan formal, dengan candaan ringan yang sopan dan kontekstual. Jangan maksa, jangan norak.
- **Identity-aware:** bot harus tahu siapa lawan bicaranya. Gunakan role system dan member cache untuk menyesuaikan sapaan dan respons. Founder berbeda dengan user biasa. Sebut nama kalau ada. Jangan generik kalau identitas diketahui. Member cache ini dijaga selalu fresh lewat harvest agresif saat bot masuk grup dan pemantauan perubahan identitas tiap member, jadi jangan pernah menyapa user dengan nama atau username yang sudah basi.
- **Pusatkan voice atau identity** di `tcbot/modules/helper/identity.py`. Tidak boleh ada string voice yang tersebar atau duplikat. Update `docs/button-styles.md` dan docs voice agar cocok.

### Peningkatan Konten Pesan

Semua teks pesan yang dikirim bot ke user di seluruh project wajib ditelusuri dan diperbaiki dalam satu pass khusus. Standar yang dicari:

- Pesan error harus menjelaskan apa yang salah dan apa yang harus dilakukan, bukan hanya "gagal" atau "error".
- Pesan konfirmasi aksi moderasi harus menyebut target, alasan, dan durasi kalau relevan, bukan template kosong.
- Pesan yang muncul di tengah conversation flow harus konsisten nadanya dari awal sampai akhir flow: jangan ramah di awal lalu kaku di akhir.
- Kalau ada pesan yang terlalu panjang dan bisa diringkas tanpa kehilangan informasi, ringkas. Kalau terlalu pendek dan ambigu, perluas.
- Tidak semua pesan perlu disentuh. Fokus pada pesan yang sering dilihat user dan yang jelas-jelas bermasalah.

Catat pesan yang diubah di `.agents/memory/decisions.md` secara ringkas agar sesi berikutnya tidak redo pekerjaan yang sama.

---

## DIAGRAM MERMAID

- Setiap file `.md` yang menjelaskan arsitektur, workflow, struktur modul, dependensi, atau proses wajib dilengkapi diagram Mermaid yang akurat.
- Diagram yang sudah ada wajib diperbarui setiap kali kode atau struktur berubah.
- Jika suatu konsep atau alur di `.md` belum memiliki diagram tetapi akan lebih jelas dengan visualisasi, tambahkan diagram Mermaid baru.
- Jenis diagram yang umum digunakan: `flowchart` untuk alur, `classDiagram` untuk struktur, `sequenceDiagram` untuk interaksi antar komponen, dan `erDiagram` untuk skema DB.
- Buat file `.md` khusus untuk diagram jika diperlukan dan tautkan dari indeks terkait.
- Semua diagram harus bersih, terbaca, dan merepresentasikan implementasi terkini.

---

## SKILL & SUB-AGENT (pakai tanpa disuruh)

Gunakan semua skill yang relevan secara otomatis tanpa perlu diinstruksikan:
`context7-mcp`, `project-policy`, `docs-maintainer`, `telegram-bot-builder`, `mongodb-query-optimizer`, `async-python-patterns`, `python-code-quality`, `mermaid-diagrams`, `runtime-debugger`, `feature-reviewer`, dan `general-sub-agent` (semua ada di `.agents/skills/`).

Komposisikan skill ketika pekerjaan mencakup beberapa area. Untuk sub-agent, ikuti bagian orkestrasi sub-agent di atas: spawn banyak sub-agent paralel untuk scope independen dan tetap bekerja sambil menunggu. Patuhi aturan satu scope satu pemilik agar tidak ada duplikasi, dan jaga verifikasi serta commit tetap terpusat di main agent.

---

## OPTIMASI UKURAN REPOSITORY

- Folder `.kilo/`, `.trae/`, `.claude/`, dan `.roo/` (jika ada) wajib berupa symlink ke `.agents/`, bukan salinan fisik.
  ```bash
  ln -s .agents .kilo
  ln -s .agents .trae
  ln -s .agents .claude
  ln -s .agents .roo
  ```
- Kalau environment tidak mendukung symlink, catat sebagai note di `.agents/memory/context.md` dan jangan dipaksakan.
- Commit symlink ke repository agar repo tetap ramping.

---

## GAYA PENULISAN

- Semua dokumentasi dalam bahasa Inggris profesional.
- **Tidak boleh ada em-dash atau en-dash di mana pun:** docs, komentar kode, dan string bot. Ganti dengan titik dua, kurung, atau koma. Panah (`-->`) boleh di docs. Tidak boleh ada emoji di docs maupun di bot.
- Komentar ikut `.agents/STYLE-COMMENTS.md`, gaya kode ikut `.agents/STYLE-CODE.md`.

---

## BAHASA KOMUNIKASI AGENT

- Setiap kali merespons, melaporkan progress, atau berkomunikasi dengan pengguna (manusia), wajib menggunakan **bahasa Indonesia profesional** layaknya developer profesional.
- Semua materi tertulis lainnya: kode Python, docstring, komentar dalam kode, dokumentasi `.md` (root, `docs/`, `.agents/`), CHANGELOG, pesan commit git, dan file di `.agents/memory/` tetap menggunakan **bahasa Inggris** profesional.
- Catat aturan ini di `.agents/memory/context.md` agar selalu diingat di sesi berikutnya.

---

## CARA KERJA (siklus per item, ulangi terus)

```
0. Di awal sesi:
     - Baca .agents/memory/ (context recovery) sebelum hal lain.
     - Susun atau lanjutkan rencana audit terstruktur di .agents/memory/progress.md.
     - Pecah project jadi scope independen yang tidak tumpang tindih.
     - Identifikasi scope yang bisa diparalel -- scope independen wajib dikerjakan secara paralel, bukan berurutan.

1. Spawn gelombang sub-agent paralel untuk scope-scope independen sekarang. Jangan tunda. Spawn semua yang bisa di-spawn sebelum mulai main-agent work. Tetapkan satu pemilik per scope; catat di progress.md.

2. Sambil sub-agent berjalan, main agent langsung kerja -- tidak boleh ada jeda. Tidak ada "tunggu dulu sambil lihat sub-agent". Audit scope lain, konsolidasi hasil yang sudah masuk, atau siapkan verifikasi batch berikutnya. Sebelum API library call, cek Context7 atau inspeksi source. Update semua import yang terdampak saat melakukan restrukturisasi.

3. Integrasikan hasil sub-agent beserta perbaikan main agent. Tidak ada bentrok antar-scope, tidak ada duplikasi. Setiap temuan dibuktikan dari source.

4. Jalankan seluruh rangkaian verifikasi wajib (langkah 1 sampai 7). Semua harus hijau sebelum melanjutkan.

5. Update semua file .md yang terdampak di seluruh project:
   - CHANGELOG.md: selalu.
   - PLAN.md: ketika state atau struktur berubah.
   - docs/: ketika perilaku, layout, voice, atau performa berubah.
   - File .md di .agents/ dan root: ketika terdampak.
   Tidak boleh ada file .md yang stale.

6. Update semua diagram Mermaid di setiap .md yang terdampak.

7. Update semua file .agents/memory/.

8. git add -A && git commit dengan pesan jelas mengikuti konvensi commit. Jangan push kecuali diminta secara eksplisit.

9. Evaluasi: masih ada scope yang belum selesai? Spawn gelombang sub-agent berikutnya segera (kembali ke langkah 1). Ulangi sampai audit kering (tidak ada temuan baru beberapa gelombang berturut-turut) atau kena limit. Jangan pause di antara gelombang lebih dari yang mutlak diperlukan.
```

---

## PAGAR PENGAMAN (jangan dilanggar)

- Jangan rusak perilaku moderasi federasi, keamanan, dan kompatibilitas DB. Skema DB harus backward-compatible kecuali ada rencana migrasi eksplisit.
- Jangan commit secret atau real chat ID. Jangan buat atau edit `config.env` berisi nilai asli; gunakan Replit Secrets. Gunakan `uv` ditambah `pyproject.toml`; jangan tambah dependency langsung dengan `pip`.
- Jangan hapus kode tanpa cek referensi penuh.
- Commit sering; jangan rombak besar sekaligus tanpa verifikasi lengkap.
- Kalau verifikasi gagal di tengah jalan dan tidak bisa diperbaiki dalam satu item, revert perubahan (`git checkout -- .`), catat blocker di `.agents/memory/progress.md`, lanjut ke item lain yang tidak terblokir.

---

## SELESAI (definition of done)

Project dianggap selesai ketika semua kondisi berikut terpenuhi:

- **Audit kering:** beberapa gelombang sub-agent berturut-turut tidak menemukan temuan baru. Seluruh kode `tcbot/` sudah ditelusuri dari awal sampai akhir, setiap skenario di bagian kelengkapan skenario sudah terbukti tertangani.
- Siap production dan stabil. Tidak ada bug yang diketahui.
- Struktur sangat modular, modern, clean: tidak ada dead code, tidak ada duplicate code, tidak ada nilai hardcode.
- **Semua target performa v5.2.6 terpenuhi**, atau ada catatan eksplisit di `.agents/memory/decisions.md` mengapa target tertentu tidak bisa dicapai beserta bukti bahwa semua cara yang masuk akal, termasuk yang tidak konvensional, sudah dicoba, beserta angka nyata yang benar-benar tercapai (lihat kejujuran angka di bagian PERFORMA). **Target performa yang tercatat sebagai accepted-gap dengan bukti seperti ini tidak menghalangi status selesai** -- yang menghalangi status selesai hanyalah bug, celah skenario yang belum tertangani, atau keamanan yang belum utuh; target latency ekstrem yang sudah dicoba habis-habisan dan dicatat jujur adalah pengecualian yang sah, bukan pekerjaan yang belum selesai.
- **Bot berjalan dalam mode webhook native** sesuai environment (lihat subsection Transport Update di bagian PERFORMA), tanpa loop `getUpdates` kontinu yang berjalan bersamaan, kecuali fallback local dev yang sudah dicatat eksplisit sebagai accepted-risk.
- Semua I/O async dan operasi independen diparalelkan. `asyncio.gather` digunakan di setiap tempat yang memungkinkan. Tidak ada `await` berurutan untuk operasi independen. Tidak ada N+1 DB query pattern tersisa.
- `q.answer()` selalu menjadi instruksi pertama di callback handler, tanpa pengecualian.
- Setiap async task yang di-spawn via `asyncio.create_task` punya error handler yang terlampir.
- Keamanan utuh: auth decorator terpasang, rate limiting aktif, input escaping benar, secret tidak pernah di-log atau di-commit.
- Ruff bersih.
- Seluruh rangkaian verifikasi (uv sync, pip install -e ., import check, startup check, lint, run bot, docs check) lulus tanpa error. Di Replit: workflow "Start Application" start bersih.
- Semua file `.md` di root, `docs/`, dan `.agents/` up to date dan persis sesuai kode.
- Semua diagram Mermaid di setiap `.md` akurat, bersih, dan merepresentasikan implementasi terkini.
- `.kilo/`, `.trae/`, `.claude/`, dan `.roo/` berupa symlink ke `.agents/` (jika environment mendukung).
- Voice bot konsisten: tidak ada emoji, friendly ditambah profesional ditambah formal ditambah candaan ringan, identity-aware.
- `.agents/memory/` terisi dan up to date: MEMORY.md sebagai indeks, progress, decisions, structure, context, dan file relevan lainnya.
- Setiap perubahan sudah di-commit sebagai checkpoint.

**Kerjakan sebanyak mungkin sampai kena platform limit. Mulai sekarang, tidak ada penundaan, tidak ada pemanasan: langsung context recovery, baca semua file .md, spawn gelombang sub-agent pertama, dan jalankan loop serentak.**

---

## PROTOKOL BERHENTI (wajib dijalankan sebelum sesi berakhir)

Kalau akan berhenti, baik karena kena platform limit, audit sudah kering, atau sesi akan berakhir, jangan langsung berhenti begitu saja. Sebelum berhenti, sampaikan laporan akhir sesi kepada user secara langsung, lengkap, detail, terperinci, dan profesional seperti presentasi kepada stakeholder.

Laporan wajib mencakup semua poin berikut, tidak boleh ada yang dilewati:

**1. Ringkasan Eksekutif**
Apa yang dikerjakan dalam sesi ini secara keseluruhan, dalam 3 sampai 5 kalimat padat.
Status bot sekarang dibandingkan sebelum sesi dimulai.

**2. Daftar Lengkap Perubahan**
Setiap file yang diubah, ditambah, atau dihapus, disertai penjelasan singkat apa yang berubah dan mengapa. Dikelompokkan per area: handlers, database, utils, scheduling, config, docs, dan lainnya.

**3. Bug dan Masalah yang Ditemukan dan Diperbaiki**
Daftar eksplisit setiap bug, anti-pattern, atau masalah yang ditemukan, lengkap dengan deskripsi masalahnya, lokasi di kode, dan cara memperbaikinya.

**4. Peningkatan Performa yang Dilakukan**
Hotpath mana yang dioptimalkan, pola apa yang diganti misalnya dari `await` berurutan ke `gather`, dari N+1 ke batch query, dari plain dict ke TTLCache, dan estimasi dampaknya.

**5. Status Target Performa v5.2.6**
Mana yang sudah tercapai, mana yang belum, mana yang tidak bisa dicapai beserta alasannya.

**6. Pekerjaan yang Belum Selesai (kalau ada)**
Scope apa yang belum disentuh, item apa yang masih ada di backlog, dan prioritas yang disarankan untuk sesi berikutnya.
Spesifik: sebutkan nama file atau modul, bukan deskripsi umum.

**7. Keputusan Teknis Non-Trivial**
Setiap keputusan desain yang dibuat selama sesi, apa yang dipilih, apa alternatifnya, dan alasan memilih jalur tersebut.

**8. Risiko atau Hal yang Perlu Diperhatikan**
Kalau ada perubahan yang berpotensi menimbulkan efek samping, edge case yang belum tertutup, atau area yang butuh perhatian lebih, sebutkan secara eksplisit.

Format laporan: **bahasa Indonesia, terstruktur dengan header yang jelas, profesional, tidak ada informasi yang ditahan, tidak ada yang diringkas berlebihan**. User harus bisa membaca laporan ini dan langsung tahu persis kondisi project tanpa harus menggali sendiri.