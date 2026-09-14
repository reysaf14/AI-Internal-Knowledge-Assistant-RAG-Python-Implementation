# Architecture — Asisten Pengetahuan Internal Toko Makmur Jaya

- Architecture version: `1.1`
- Tanggal: `2026-09-14`
- Status: `APPROVED`
- PRD: `.ai/knowledge/prd.md` versi `1.1` (`APPROVED`)
- Lane: `PROFESSIONAL`

## 1. Pendekatan Utama dan alasan

Bangun satu aplikasi Python dengan dua entry point operasional:

1. pemuatan ulang knowledge base dari folder `docs/`; dan
2. runtime bot tanya-jawab Telegram menggunakan long polling.

Tidak ada n8n atau platform orkestrasi workflow sejenis. Pendekatan ini paling sesuai dengan PRD karena corpus hanya 26 dokumen Markdown, bot dipakai bersama oleh karyawan internal, dan runtime harus bisa berpindah dari mesin lokal ke VPS tanpa memindahkan desain bisnis ke platform lain. Long polling dipilih sebagai jalur Telegram awal karena tidak memerlukan endpoint publik, domain, sertifikat, atau reverse proxy; biaya pemeliharaan dan permukaan serangannya lebih kecil untuk satu bot internal. Webhook dicatat sebagai opsi masa depan, bukan bagian scope versi ini.

Komponen model diperlakukan sebagai dependency generik melalui adapter. Percobaan lokal dapat menggunakan model yang tersedia di mesin lokal; pemindahan ke VPS cukup mengganti konfigurasi endpoint/model yang disetujui tanpa mengubah alur ingest, retrieval, validasi, atau Telegram.

Retrieval menggunakan index lokal SQLite FTS5 dengan metadata sumber yang melekat pada setiap potongan dokumen. Vector database, database cloud, dan service pencarian eksternal tidak diperlukan untuk 26 dokumen. Model hanya menerima pertanyaan dan potongan yang ditemukan oleh index; application guard memastikan sumber yang dikirim berasal dari corpus aktif dan menyediakan jalur abstention bila dukungan tidak cukup.

Batas desain utama:

- corpus aktif hanya file Markdown resmi `docs/00` sampai `docs/25` yang telah disahkan;
- input Telegram dibatasi pada pertanyaan kebijakan umum, bukan record individual atau data transaksi;
- tidak ada autentikasi atau personalisasi per karyawan pada versi ini;
- isi percakapan tidak disimpan oleh aplikasi;
- satu instance polling aktif pada satu waktu;
- deployment awal lokal, lalu VPS dengan konfigurasi dan artefak aplikasi yang sama secara konseptual;
- tidak ada aksi tulis ke POS, stok, HR, pembayaran, atau sistem pelanggan.

## 2. Aliran Data

### 2.1 Ingest dan pembentukan corpus

| Sumber | Transformasi | Tujuan | Operator / trust boundary |
|---|---|---|---|
| `docs/*.md` resmi | Validasi rentang/nama file, baca Markdown, pertahankan heading, pecah berdasarkan struktur heading, normalisasi whitespace, beri identitas chunk dan nama sumber | Index corpus lokal dengan satu versi aktif | Operator/manajer mengesahkan corpus; boundary file system lokal ke aplikasi |
| Isi dan metadata file | Hash isi serta daftar file, hitung `corpus_version`, tulis index secara atomic ke artefak baru | Corpus version yang dapat diidentifikasi | Aplikasi lokal; tidak mengirim corpus ke layanan eksternal pada tahap ingest |
| Index baru | Validasi jumlah file, chunk, sumber dan versi; aktifkan hanya jika valid | Index yang digunakan runtime bot | Aplikasi mengganti pointer/metadata aktif; index lama dipertahankan sampai penggantian berhasil |

Baseline yang dipetakan adalah 26 file Markdown: `00` profil perusahaan, `01–08` SOP operasional, `09–15` FAQ pelanggan, `16–19` panduan komplain, dan `20–25` kebijakan internal. Artefak desain hanya menyimpan kategori dan nama file; tidak menyalin isi kebijakan.

Pemuatan ulang bersifat rebuild, bukan mutasi sebagian. Jika satu file hilang, berada di luar rentang baseline, gagal dibaca, atau menghasilkan index tidak valid, proses berhenti sebelum index baru menjadi aktif. Index aktif sebelumnya tetap digunakan oleh bot.

### 2.2 Tanya-jawab Telegram

1. Runtime mengambil update Telegram melalui long polling.
2. Aplikasi menerima update dan memvalidasi bahwa pesan berisi teks pertanyaan kebijakan umum dalam batas ukuran yang ditetapkan.
3. Update yang tidak valid ditolak tanpa memanggil model.
4. Pertanyaan dinormalisasi untuk pencarian tanpa mengubah teks yang diproses secara sementara.
5. Index aktif mencari potongan relevan dan mengembalikan teks, nama file, bagian heading, serta `corpus_version`.
6. Guard dukungan menentukan apakah konteks cukup. Jika tidak cukup, hasil diarahkan ke respons abstention.
7. Jika cukup, adapter model menerima pertanyaan, konteks terpilih, aturan jawaban singkat, dan aturan sumber.
8. Validator memeriksa bentuk jawaban, status dukungan, dan sumber. Sumber yang boleh disebut hanya metadata dari chunk yang dikembalikan index; sumber tambahan yang tidak didukung ditolak.
9. Aplikasi mengirim tepat satu respons normal untuk update yang selesai. Respons supported mencantumkan nama dokumen yang mendukung; respons abstention tidak mencantumkan sumber palsu.
10. Aplikasi mencatat status teknis minimum dan memperbarui state polling secara atomic. Isi pertanyaan, jawaban, identitas pengguna, username, dan chat ID tidak masuk log atau database aplikasi.

### 2.3 Evaluasi

CSV yang diberikan Human diperlakukan sebagai kandidat data sintetis. Pemeriksaan aman menemukan 15 baris unik, tiga kolom wajib, dan tidak ada sel kosong. Baris 3, 7, 8, dan 15 merujuk dokumen di luar corpus resmi. Tiga baris pertama menjadi unsupported; baris 15 diganti dengan pertanyaan supported dari dokumen `00`. Engineer menyiapkan salinan kerja sintetis dan Human/manajer mengesahkan kunci jawaban serta sumber sebelum eksekusi evaluasi.

Evaluasi mengukur setiap pertanyaan secara terpisah: isi, sumber, abstention, waktu dari penerimaan aplikasi sampai Telegram menyatakan pengiriman berhasil, dan catatan kegagalan. CSV sumber tidak menjadi runtime corpus dan tidak diubah oleh aplikasi.

### 2.4 Trust boundary dan kegagalan utama

- **Operator → aplikasi:** operator dapat mengganti corpus dan menjalankan rebuild; aplikasi memvalidasi path dan tidak menerima path yang mengarah ke data produksi di luar scope.
- **Telegram → aplikasi:** update adalah input eksternal yang tidak tepercaya; validasi tipe/ukuran, deduplication, dan pembatasan pesan berlaku sebelum retrieval.
- **Aplikasi → model:** model adalah boundary provider/runtime terpisah; timeout, error HTTP, respons tidak valid, dan respons tanpa dukungan diperlakukan sebagai kegagalan terkontrol.
- **Aplikasi → Telegram:** pengiriman adalah side effect eksternal; hasil tidak dikenal tidak boleh dilaporkan sebagai sukses dan retry tidak boleh menjanjikan exactly-once universal.
- **Aplikasi → file system:** index corpus bersifat Confidential; akses direktori dan permission runtime dibatasi oleh operator/host.
- **Aplikasi → log/state:** hanya metadata teknis minimum yang boleh keluar; payload dan credential diredaksi sebelum logging.

## 3. Struktur Folder

Struktur berikut adalah target implementasi untuk Engineer; file kode, fixture, dan command aktual belum dibuat pada tahap Architect.

```text
project-root/
├─ docs/                         # corpus resmi 00–25, dikelola Human/manajer
├─ src/
│  └─ rag_assistant/
│     ├─ __main__.py             # dispatch entry point ingest/bot
│     ├─ config.py               # konfigurasi dan validasi profile
│     ├─ domain/                 # tipe hasil, status, dan aturan bisnis
│     ├─ ingestion/              # inventory, parsing, chunking, versioning
│     ├─ retrieval/              # SQLite FTS5 dan support gate
│     ├─ answering/              # adapter model, prompt boundary, validator
│     ├─ telegram/               # polling, update validation, send result
│     ├─ storage/                 # index aktif dan runtime state atomic
│     └─ observability/          # log tersanitasi dan timing
├─ tests/
│  ├─ unit/                      # synthetic fixtures dan fault injection
│  ├─ integration/               # local model/mock Telegram boundary
│  └─ e2e/                       # sandbox Telegram bila provisioning tersedia
├─ eval/                         # salinan eval sintetis yang telah disahkan
├─ scripts/                      # launcher/validasi non-interaktif bila diperlukan
├─ .ai/
│  ├─ knowledge/
│  │  ├─ architecture.md
│  │  ├─ environment-schema.md
│  │  └─ prd.md
│  ├─ decisions/
│  └─ reports/
└─ .env.example                 # dibuat Engineer berdasarkan schema
```

`data/`, `runtime/`, atau nama direktori setara untuk index dan state harus dikecualikan dari Git bila berisi corpus turunan atau konfigurasi lokal. Engineer tidak boleh menaruh credential di folder tersebut. Folder report dibuat hanya ketika evidence memang dihasilkan.

## 4. Dependency & Environment Variables

### Dependency plan

- Python `3.12` sebagai runtime tunggal untuk lokal dan VPS.
- `python-telegram-bot` untuk lifecycle long polling, parsing update, dan pengiriman pesan.
- `httpx` atau client HTTP setara untuk adapter model generik; pilihan final dan lockfile menjadi tanggung jawab Engineer.
- SQLite FTS5 melalui runtime SQLite yang tersedia; tidak ada database eksternal atau vector database.
- Parser Markdown ringan atau parser yang dipilih Engineer bila diperlukan untuk mempertahankan struktur heading tanpa menyalin format yang tidak perlu.
- `pytest` dan satu linter/formatter sebagai dependency pengembangan; tidak dipakai sebagai bukti QA independen.

Dependency harus dikunci pada manifest/lockfile oleh Engineer. Tidak boleh ada dependency provider yang tidak dipakai oleh alur yang disetujui.

Schema konfigurasi canonical berada di [.ai/knowledge/environment-schema.md](environment-schema.md). Engineer membuat `.env.example` di root berdasarkan schema yang sama; tidak boleh membuat template tandingan di `src/`, `config/`, atau `deploy/`.

## 5. Database jika ada, atau alasan stateless

SQLite lokal digunakan karena sistem membutuhkan dua jenis state yang kecil dan terkontrol:

1. index chunk corpus dengan metadata sumber dan versi corpus; dan
2. state teknis polling/idempotency agar restart tidak langsung memproses ulang update yang sudah selesai.

Tidak ada tabel atau file untuk isi percakapan. State runtime hanya boleh memuat versi index aktif, offset/update identifier, status teknis pengiriman, timestamp, durasi, dan kategori hasil. Tidak menyimpan nama pengguna, username, chat ID, teks pertanyaan, teks jawaban, atau payload Telegram.

Index rebuild ditulis ke SQLite baru/temporary lalu divalidasi sebelum diaktifkan. Penggantian aktif harus atomic dan mempertahankan index sebelumnya ketika rebuild gagal. Satu instance bot memakai file lock atau mekanisme host setara; dua instance polling bersamaan tidak didukung.

Corpus dan index turunan tetap `Confidential` dan harus memiliki permission file yang sesuai. State polling tidak menjadi arsip percakapan. Retensi state teknis dibatasi pada kebutuhan deduplication/recovery dan dibersihkan oleh runtime/operasi sesuai profile; durasi retention yang spesifik harus dikunci Engineer sebelum implementasi.

## 6. Catatan Keamanan & Robustness

### Auth, authorization, dan data boundary

- Token bot adalah credential `Restricted`, disediakan Human melalui runtime/credential store yang disetujui, dan tidak boleh masuk repository, prompt, fixture, screenshot, log, atau report.
- Tidak ada autentikasi per karyawan sesuai PRD. Operator wajib menjaga distribusi bot sebagai kanal internal; akses publik atau penggunaan pelanggan langsung berada di luar scope.
- Input Telegram harus menolak atau mengarahkan pengguna dari record individual, data transaksi, data pembayaran, data HR, credential, dan payload produksi. Aplikasi tidak boleh meneruskan data tersebut ke model.
- Corpus diproses hanya setelah Human/manajer mengesahkan dokumen dan memastikan identitas langsung, credential, tanda tangan, kontak pribadi, serta record individual telah dibersihkan.

### Grounding, sumber, dan prompt boundary

- Model hanya menerima konteks yang berasal dari index corpus aktif dan instruksi aplikasi yang tetap.
- Jawaban tidak boleh mengandalkan pengetahuan di luar konteks. Jika retrieval tidak cukup, model gagal, atau validator meragukan sumber, aplikasi mengirim respons tidak tahu.
- Nama sumber ditambahkan/divalidasi dari metadata index, bukan dipercaya dari teks bebas model.
- Respons tidak boleh menyertakan sumber yang tidak ada di chunk retrieved atau sumber yang tidak relevan.
- Perintah atau instruksi yang muncul di pertanyaan maupun corpus tidak boleh mengubah aturan aplikasi, akses file, atau credential boundary.

### Retry, timeout, dan partial failure

- Polling melakukan reconnect/backoff terbatas ketika Telegram tidak tersedia; kegagalan polling tidak menghasilkan jawaban palsu.
- Panggilan model memiliki timeout terpisah dari polling. Jika melewati budget, aplikasi memilih abstention atau status error yang aman dan tidak mengklaim jawaban supported.
- Pengiriman Telegram memiliki timeout dan status `UNKNOWN` untuk hasil yang tidak dapat dipastikan. Retry otomatis tidak boleh menjanjikan exactly-once; kasus tidak pasti dicatat untuk operator tanpa menyimpan payload.
- Update diproses melalui identity Telegram dan state atomic. Duplicate/retry yang terdeteksi tidak memicu jawaban kedua.
- Rebuild index gagal secara fail-closed: index aktif lama tetap dipakai, dan corpus baru tidak disebut aktif.

### Shell, file, dan observability

- Runtime tidak memanggil shell untuk memproses input eksternal. Bila launcher shell diperlukan, argumen harus dipisahkan sebagai argument array/parameter aman; input Telegram atau nama file eksternal tidak boleh diinterpolasikan ke command string.
- Path corpus harus di-resolve terhadap root project dan dicek agar tidak keluar dari boundary `docs/`.
- Log hanya berisi operation, timestamp, durasi, status, sanitized error category, corpus version, dan hasil supported/abstention/error. Redaction dilakukan sebelum logger menerima nilai.
- Dependency, file konfigurasi, dan runtime profile harus diaudit oleh Security pada tahap berikutnya. Architecture PASS bukan Security PASS.

## 7. Acceptance & Failure Scenarios

Matrix ini adalah versi `1.0`, rancangan untuk PRD `1.1`. Semua baris `required` adalah skenario wajib yang harus dipetakan Engineer ke implementation, test, fixture, command, dan evidence. Belum ada test yang dijalankan pada tahap Architect; status runtime/evidence adalah `NOT_RUN` setelah implementasi belum tersedia, bukan `PASS`.

| AC / REQ | Family | Precondition + stimulus sintetis/injected fault | Expected observable result; forbidden side effects | Level / target; priority |
|---|---|---|---|---|
| `AC-001 / REQ-001` | Valid | Root project berisi tepat 26 Markdown resmi `00–25`; jalankan rebuild | Index baru memuat seluruh file, versi corpus dapat diidentifikasi, dan menjadi aktif atomically; tidak ada credential/payload di report | Unit + local integration; required |
| `AC-002 / REQ-001` | Invalid | Satu file wajib hilang, nama di luar pola, atau file tidak dapat dibaca | Rebuild gagal dengan kategori error; index aktif sebelumnya tetap; tidak ada partial index aktif | Unit + local integration; required |
| `AC-003 / REQ-001` | Duplicate/retry | Rebuild corpus identik dua kali atau dua request rebuild berurutan | Satu versi aktif yang sama, tidak ada duplicate chunk, dan tidak ada korupsi index | Local integration; required |
| `AC-004 / REQ-001` | Timeout | `NOT_APPLICABLE`: ingest adalah operasi lokal offline dan PRD tidak menetapkan SLA waktu rebuild; interruption tetap harus mempertahankan index aktif lama | Alasan N/A ditinjau; cancellation/failure tidak mengaktifkan partial index | Design N/A + local integration interruption check; required |
| `AC-005 / REQ-001` | Provider failure | `NOT_APPLICABLE`: ingest tidak memakai provider eksternal; filesystem/index failure tercakup AC-002 | Alasan N/A ditinjau | Design N/A; required |
| `AC-006 / REQ-002` | Valid | Update Telegram sintetis berisi satu pertanyaan teks kebijakan umum | Satu respons dapat dibaca dikirim untuk update tersebut; tidak ada personalization/auth per karyawan | Mock integration + Telegram sandbox E2E; required |
| `AC-007 / REQ-002` | Invalid | Update kosong, non-text, command tidak dikenal, atau teks melebihi batas konfigurasi | Ditolak secara terkontrol tanpa pemanggilan model, tanpa retrieval sensitif, dan maksimal satu pesan penjelasan yang aman bila desain memilih memberi feedback | Unit + mock integration; required |
| `AC-008 / REQ-002` | Duplicate/retry | Update ID sama diterima ulang atau proses diulang setelah status sukses | Tidak ada jawaban kedua untuk identity yang sama; state polling/idempotency tetap konsisten | Local integration + sandbox integration; required |
| `AC-009 / REQ-002` | Timeout | Polling request atau koneksi Telegram diberi delay/timeout terkendali sebelum update diterima | Runtime reconnect/backoff dan tetap hidup; tidak ada jawaban atau status sukses palsu | Mock integration; required |
| `AC-010 / REQ-002` | Provider failure | Telegram menolak request, rate-limit, atau send result tidak diketahui | Aplikasi tidak menyatakan sukses; retry dibatasi/ditandai `UNKNOWN`; tidak memasukkan payload ke log | Sandbox integration bila tersedia; required |
| `AC-011 / REQ-003` | Valid supported | Pertanyaan sintetis dari 12 item approved menghasilkan chunk pendukung | Jawaban hanya menyampaikan fakta yang didukung context dan dapat dinilai terhadap rubric biner | Local model integration + approved eval; required |
| `AC-012 / REQ-003` | Valid unsupported | Tiga pertanyaan sintetis yang sengaja tidak ada di corpus | Respons jelas menyatakan tidak tahu/tidak ditemukan tanpa klaim kebijakan baru | Local model integration + approved eval; required |
| `AC-013 / REQ-003` | Invalid context/output | Context kosong, konflik, atau model mengembalikan bentuk/status di luar kontrak | Validator memilih abstention/error aman; tidak ada jawaban supported palsu | Unit + mock model integration; required |
| `AC-014 / REQ-003` | Duplicate/retry | Pertanyaan sama diproses melalui duplicate update yang sama | Deduplikasi dilakukan pada boundary Telegram; answer service tidak membuat side effect kedua | Covered by AC-008; required |
| `AC-015 / REQ-003` | Timeout | Model diberi delay terkontrol sampai melewati timeout aplikasi | Fallback abstention/error aman; tidak ada klaim jawaban lengkap atau sumber palsu | Mock model integration; required |
| `AC-016 / REQ-003` | Provider failure | Model tidak tersedia, mengembalikan server error, atau respons tidak dapat diparse | Aplikasi berhenti pada respons tidak tahu/error aman dan tidak melaporkan supported success | Mock model integration + local runtime; required |
| `AC-017 / REQ-004` | Valid | Dua belas pertanyaan supported memiliki chunk dengan filename sumber yang disahkan | Setiap jawaban menyebut minimal satu sumber yang benar; sumber tambahan harus berasal dari context dan relevan | Unit + approved eval; required |
| `AC-018 / REQ-004` | Invalid source | Model mengeluarkan filename di luar index atau sumber tambahan yang tidak ada di context | Validator menghapus/menolak keluaran dan mengarah ke respons aman; sumber palsu tidak dikirim | Unit + mock model integration; required |
| `AC-019 / REQ-004` | Duplicate/retry | Sumber sama diproses ulang akibat update duplicate | Tidak ada pesan kedua; aturan sumber tidak berubah | Covered by AC-008; required |
| `AC-020 / REQ-004` | Timeout | `NOT_APPLICABLE` sebagai family sumber: metadata sumber lokal; timeout end-to-end diuji pada AC-025 | Alasan N/A ditinjau; timeout runtime tidak boleh menghasilkan sumber palsu | Design N/A; required |
| `AC-021 / REQ-004` | Provider failure | `NOT_APPLICABLE` untuk derivasi sumber: sumber berasal dari index; kegagalan model diuji pada AC-016 | Alasan N/A ditinjau; fallback tidak menyatakan sumber | Design N/A; required |
| `AC-022 / REQ-005` | Valid unsupported | Pertanyaan eval tidak memiliki chunk yang mendukung jawabannya | Respons abstention eksplisit, tanpa tebakan, klaim kebijakan, atau sumber palsu | Unit + approved eval; required |
| `AC-023 / REQ-005` | Invalid abstention | Model mencoba menjawab unsupported atau menyertakan sumber palsu | Guard/validator mengubahnya menjadi abstention aman; tidak ada klaim model yang lolos | Unit + mock model integration; required |
| `AC-024 / REQ-005` | Duplicate/retry | Unsupported update ID sama diterima ulang | Satu abstention maksimum untuk identity tersebut | Covered by AC-008; required |
| `AC-025 / REQ-005` | Timeout | Model timeout saat pertanyaan unsupported | Fallback tetap abstention; tidak mengisi jawaban dari tebakan | Mock model integration; required |
| `AC-026 / REQ-005` | Provider failure | Model unavailable/invalid response pada pertanyaan unsupported | Respons aman tidak tahu/error; tidak ada sumber palsu dan tidak ada success claim | Mock model integration; required |
| `AC-027 / REQ-006` | Valid | Jalankan 15 pertanyaan approved pada profile evaluasi dan ukur sejak aplikasi menerima sampai Telegram send berhasil | Setiap durasi `<5,0 detik`; semua 15 hasil memiliki timestamp start/end dan status per pertanyaan | Sandbox Telegram E2E; required |
| `AC-028 / REQ-006` | Invalid | Input tidak valid dari AC-007 | Tidak dihitung sebagai pass/fail eval; ditolak sebelum model dan tidak menimbulkan side effect tambahan | Unit + mock integration; required |
| `AC-029 / REQ-006` | Duplicate/retry | Satu pertanyaan eval dikirim ulang dengan update ID sama | Tidak ada pengukuran ganda sebagai respons baru dan tidak ada pesan kedua | Covered by AC-008; required |
| `AC-030 / REQ-006` | Timeout | Delay model atau Telegram send melewati budget `<5,0 detik` | Runtime tidak melaporkan evaluasi sebagai sukses; timeout/fallback terukur; candidate gagal pada item yang melewati batas | Mock + sandbox integration; required |
| `AC-031 / REQ-006` | Provider failure | Model/Telegram mengembalikan error atau status send tidak diketahui | Status item bukan successful response; error tersanitasi; tidak mengubah verdict menjadi lulus | Sandbox integration; required |
| `AC-032 / REQ-007` | Valid | Operator menjalankan entry point rebuild lalu bot pada profile lokal dengan panduan | Knowledge base dapat diidentifikasi, bot dapat dijalankan, panduan dan evaluasi dapat ditinjau | Local setup/integration; required |
| `AC-033 / REQ-007` | Invalid configuration | Required env hilang/kosong/placeholder atau path corpus invalid | Aplikasi berhenti sebelum network/write dan menyebut nama konfigurasi/path yang bermasalah tanpa nilainya | Static + local startup check; required |
| `AC-034 / REQ-007` | Duplicate/retry | Operator menjalankan rebuild ulang dan mengikuti panduan penggantian dokumen berulang | Hasil deterministik, corpus version berubah hanya bila isi/daftar file berubah, dan tidak ada duplicate state | Local integration; required |
| `AC-035 / REQ-007` | Timeout | `NOT_APPLICABLE`: deliverable/panduan tidak memiliki provider timeout; timeout runtime ditutup oleh AC-009/015/030 | Alasan N/A ditinjau | Design N/A; required |
| `AC-036 / REQ-007` | Provider failure | `NOT_APPLICABLE`: requirement ini menilai artefak operator; provider failure ditutup oleh REQ-002/003/006 | Alasan N/A ditinjau | Design N/A; required |

Target minimum yang berasal dari PRD tetap: isi `≥12/15`, sumber `12/12` supported, abstention `3/3`, dan waktu `<5,0 detik` untuk `15/15`. Matrix ini tidak mengklaim bahwa target tersebut telah tercapai. Engineer wajib membuat mapping `AC → implementation → test → fixture → command`; QA kemudian mengeksekusi secara independen.

## 8. Catatan Khusus: asumsi/risiko/batas yang belum terselesaikan

### 8.1 Milestone Delivery Plan

Pengerjaan dibagi menjadi milestone berurutan. Setiap milestone memiliki artefak, acceptance yang dituju, dan exit gate. Engineer tidak melompati gate yang gagal; skenario yang belum terbukti tetap `NOT_VERIFIED`. Tidak ada target waktu yang ditetapkan di tahap desain.

| Milestone | Fokus dan hasil utama | Acceptance / quality gate | Exit condition dan owner berikutnya |
|---|---|---|---|
| `M0` — Baseline & Gate | Human menyetujui architecture `1.1`, ADR-001, schema environment, corpus manifest `00–25`, serta kandidat eval final 12+3 | PRD `1.1` approved; matrix `1.0` tetap menjadi kontrak; data representation dan owner provisioning tercatat | Semua keputusan desain tidak ambigu; Human membuka Engineer |
| `M1` — Corpus Ingestion | Inventory, validasi, parsing Markdown, chunking heading-aware, hash versi corpus, rebuild index SQLite, dan atomic activation | `AC-001–005`, termasuk rebuild identik, invalid corpus, dan perlindungan index aktif lama | Baseline 26 file terindeks deterministik; Engineer melakukan self-test dan handoff |
| `M2` — Retrieval & Source Grounding | Search FTS5, metadata sumber, support gate, ranking, dan penolakan sumber di luar context | `AC-011–013`, `AC-017–018`, `AC-022–023` pada fixture sintetis dan mock model | Query supported menemukan sumber benar; query unsupported dapat diarahkan ke abstention; Engineer mengunci parameter retrieval sebelum eval |
| `M3` — Answering & Failure Control | Adapter model generik, format output, validator, abstention, timeout, provider failure, dan sanitized observability | `AC-015–016`, `AC-020–021`, `AC-025–026`; tidak ada isi pertanyaan/jawaban di log | Local model/mock melewati unit dan integration checks; kegagalan tidak menghasilkan success claim |
| `M4` — Telegram Polling | Polling loop, validasi update, state offset/idempotency, single-instance guard, dan send result handling | `AC-006–010`, `AC-014`, `AC-019`, `AC-024`; mock boundary dahulu, sandbox sesudah token disediakan | Satu update valid menghasilkan satu respons; duplicate dan Telegram failure terobservasi; Engineer/DevOps handoff |
| `M5` — Local End-to-End Eval | Runtime lokal menjalankan eval 12+3 melalui polling atau boundary sandbox yang disetujui; ukur sumber, abstention, isi, dan latency | `AC-027–031`; target PRD: isi `≥12/15`, sumber `12/12`, abstention `3/3`, waktu `<5,0 detik` `15/15` | Evidence per pertanyaan tersedia dan tersanitasi; hasil tidak langsung dianggap QA independent |
| `M6` — Operator Packaging | `.env.example`, panduan setup lokal, panduan rebuild/penggantian dokumen, command reproducible, dan demo tersanitasi | `AC-032–036`; required config fail-fast; rebuild dan runtime dapat diulang operator | Engineer self-test lengkap dengan mapping AC; Human menentukan handoff ke DevOps/QA |
| `M7` — VPS Readiness | Profile VPS, process/service launcher, secret injection, permission folder, backup/rollback index, dan satu-instance polling | Environment schema tervalidasi; target VPS sandbox/host benar; tidak memakai credential atau corpus production tanpa approval | DevOps menyerahkan runtime static/readiness evidence; tidak melakukan deploy tanpa gate Human |
| `M8` — Independent Quality & Release | QA menjalankan seluruh required scenario; Security mengaudit source, dependency, config, dan boundary; DoD/release packet disusun | QA dan Security menghasilkan verdict independen; gap tetap `NOT_VERIFIED` dan tidak ditutup oleh self-test | Human memutuskan quality lalu release/deploy secara terpisah |

Aturan kualitas lintas milestone:

- setiap milestone menyimpan evidence di path yang ditentukan state dan menyebut versi artifact/candidate;
- fixture tetap sintetis dan tidak boleh memakai token, payload Telegram, record HR/pelanggan, atau data produksi;
- perubahan yang memengaruhi requirement atau matrix mengembalikan pekerjaan ke gate PRD/architecture yang terdampak;
- M1–M3 dapat dikerjakan tanpa credential Telegram; credential diperlukan mulai M4 sandbox dan hanya diprovision Human;
- M5 tidak boleh mengganti E2E Telegram dengan mock lalu menyatakan target waktu Telegram terbukti;
- M7 menyiapkan runtime VPS tetapi tidak mengotorisasi deploy; approval release tetap milik Human;
- jika milestone gagal, perbaiki scope milestone tersebut dan jalankan regression AC yang terdampak sebelum lanjut.

- **Approval gate:** arsitektur ini menunggu Human approval sebelum Engineer membangun. `.ai/project-state.md` mencatat gate tersebut.
- **Model dan provider:** sengaja tidak dikunci di PRD atau arsitektur. Adapter, format request/response, serta local test double harus dipilih Engineer tanpa mengubah kontrak grounding dan abstention.
- **Retrieval calibration:** SQLite FTS5 dipilih sebagai mekanisme sederhana. Ambang dukungan retrieval harus dikalibrasi terhadap eval 12+3 dan dicatat sebelum pengujian; tidak boleh menyembunyikan threshold di dalam kode tanpa dokumentasi.
- **Latency:** model lokal mungkin tidak memenuhi `<5,0 detik`. Ini risiko teknis yang harus dibuktikan melalui E2E; tidak boleh diganti dengan mock sebagai bukti waktu Telegram.
- **Telegram exactly-once:** API eksternal dapat membuat hasil pengiriman tidak pasti ketika koneksi putus setelah side effect. Desain mencatat `UNKNOWN` dan tidak menjanjikan exactly-once universal; mitigasi deduplication berlaku pada update yang identity-nya diketahui.
- **Shared bot tanpa auth:** siapa pun yang memperoleh akses bot dapat mengirim pertanyaan. Pembatasan distribusi bot dan instruksi penggunaan internal adalah kontrol operasional, bukan autentikasi teknis.
- **Retention:** isi percakapan tidak disimpan aplikasi. Batas retention metadata teknis, lokasi backup index, dan cleanup state harus ditetapkan Engineer/DevOps berdasarkan target host tanpa menyimpan transcript.
- **Corpus approval:** dokumen baru/pengganti tidak aktif hanya karena file muncul di `docs/`; owner/manajer harus mengesahkannya dan rebuild harus menghasilkan versi yang dapat diidentifikasi.
- **No public ingress:** polling dipilih untuk lokal dan VPS. Jika kelak diperlukan webhook, itu perubahan struktur runtime yang memerlukan ADR/review ulang.
- **Dataset approval:** CSV sumber sudah diperiksa secara struktural dan dikonfirmasi sintetis, tetapi salinan final 12+3 beserta kunci jawaban/sumber masih harus disahkan sebelum menjadi eval set approved.

## 9. Riwayat Perubahan

| Versi | Tanggal | Perubahan | ADR terkait |
|---|---|---|---|
| `1.0` | `2026-09-14` | Desain awal full-code tanpa n8n, Telegram long polling, model generik, index lokal, tanpa penyimpanan isi percakapan, dan matrix acceptance PRD 1.1 | `ADR-001-full-code-polling.md` |
| `1.1` | `2026-09-14` | Menambahkan milestone berurutan M0–M8, exit criteria, quality gate, dan aturan regresi sebelum handoff Engineer/DevOps/QA | `ADR-001-full-code-polling.md` |
