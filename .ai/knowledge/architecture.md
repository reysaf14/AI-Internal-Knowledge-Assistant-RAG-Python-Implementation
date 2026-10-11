# Architecture — Internal Knowledge Assistant

- Architecture version: `1.2`
- Date: `2026-10-11`
- Status: `APPROVED`
- PRD: `.ai/knowledge/prd.md` version `1.2` (`APPROVED`)
- Lane: `PROFESSIONAL`

## 1. Primary Approach and Rationale

Build one Python application with two operational entry points:

1. rebuild the knowledge base from `docs/`; and
2. run the Telegram Q&A bot through long polling.

The application is packaged as one OCI image that contains the Python runtime,
locked application dependencies, application source, and the approved
26-document corpus. Build the image once for a release and promote the same
image artifact by immutable digest between compatible Docker hosts. Supply
environment-specific configuration and secrets at runtime. The image does
not contain the model service or credentials. This milestone covers image
packaging and portable container execution; it does not prepare or deploy to a
specific VPS, registry, or production target.

No n8n or workflow-orchestration platform is used. Telegram long polling avoids
a public ingress endpoint, domain, TLS termination, and reverse proxy for this
single internal bot. Webhooks remain outside this release scope. The model is
an external runtime dependency behind the generic adapter; changing its
reachable endpoint and model identifier does not change ingest, retrieval,
validation, or Telegram logic.

Retrieval uses a local SQLite FTS5 index with source metadata attached to each
document chunk. A vector database, cloud database, or external search service
is not required for 26 documents. The model receives only the question and
chunks selected by the active index. Application guards restrict citations to
the active corpus and abstain when evidence is insufficient.

Primary design boundaries:

- the active corpus contains only approved Markdown files `docs/00` through `docs/25`;
- Telegram input is limited to general policy questions, not individual records or transaction data;
- this version has no per-employee authentication or personalization;
- the application does not store conversation content;
- only one polling instance may use a runtime volume at a time;
- the same image artifact runs on compatible Docker hosts, with environment-specific runtime configuration;
- no writes are made to POS, inventory, HR, payment, or customer systems;
- the image includes Confidential corpus data and may be distributed only through a Human-approved private route.

## 2. Aliran Data

### 2.1 Ingest dan pembentukan corpus

| Sumber | Transformasi | Tujuan | Operator / trust boundary |
|---|---|---|---|
| Approved `docs/*.md` | Validate names/count, parse Markdown, preserve headings, split by heading structure, normalize whitespace, assign chunk IDs and source names | One active SQLite FTS5 corpus index | Owner/manager approves the corpus; the image packages the approved files |
| File content and metadata | Hash content and inventory, compute `corpus_version`, write a new index atomically | Identifiable corpus version | Container performs local indexing; corpus is not sent to a remote service during ingest |
| New index | Validate file/chunk/source counts and version; activate only when valid | Index used by the bot | SQLite index lives in the persistent named volume; a failed build preserves the previous active index |

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

### 2.4 Trust Boundaries and Main Failures

- **Operator → aplikasi:** operator dapat mengganti corpus dan menjalankan rebuild; aplikasi memvalidasi path dan tidak menerima path yang mengarah ke data produksi di luar scope.
- **Telegram → aplikasi:** update adalah input eksternal yang tidak tepercaya; validasi tipe/ukuran, deduplication, dan pembatasan pesan berlaku sebelum retrieval.
- **Aplikasi → model:** model adalah boundary provider/runtime terpisah; timeout, error HTTP, respons tidak valid, dan respons tanpa dukungan diperlakukan sebagai kegagalan terkontrol.
- **Aplikasi → Telegram:** pengiriman adalah side effect eksternal; hasil tidak dikenal tidak boleh dilaporkan sebagai sukses dan retry tidak boleh menjanjikan exactly-once universal.
- **Aplikasi → file system:** index corpus bersifat Confidential; akses direktori dan permission runtime dibatasi oleh operator/host.
- **Aplikasi → log/state:** hanya metadata teknis minimum yang boleh keluar; payload dan credential diredaksi sebelum logging.
- **Image build → runtime:** `.dockerignore` excludes `.env*`, `.runtime/`, local caches, and Git metadata. Credentials are injected at runtime and never placed in build arguments, image layers, or image defaults.
- **Container → host:** the root filesystem is read-only; the process runs as UID/GID `10001`, drops Linux capabilities, and writes only to the named `.runtime` volume and a bounded temporary filesystem. No inbound port is published.
- **Container → model endpoint:** the configured endpoint must be reachable from the container network. The model service is not bundled into the application image.

## 3. Struktur Folder

The runtime packaging layout is:

```text
project-root/
├─ Dockerfile                    # locked multi-stage image build
├─ .dockerignore                 # secret/state/build-context boundary
├─ compose.yaml                  # run the selected image; no build step
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
└─ .env.example                  # canonical safe configuration template
```

`data/`, `runtime/`, atau nama direktori setara untuk index dan state harus dikecualikan dari Git bila berisi corpus turunan atau konfigurasi lokal. Engineer tidak boleh menaruh credential di folder tersebut. Folder report dibuat hanya ketika evidence memang dihasilkan.

## 4. Dependency & Environment Variables

### Dependency Plan

- Python `3.12` as the image runtime; the Docker host does not need a Python installation.
- `python-telegram-bot` untuk lifecycle long polling, parsing update, dan pengiriman pesan.
- `httpx` for the generic model adapter.
- SQLite FTS5 melalui runtime SQLite yang tersedia; tidak ada database eksternal atau vector database.
- Parser Markdown ringan atau parser yang dipilih Engineer bila diperlukan untuk mempertahankan struktur heading tanpa menyalin format yang tidak perlu.
- `pytest` dan satu linter/formatter sebagai dependency pengembangan; tidak dipakai sebagai bukti QA independen.

Runtime dependencies are resolved from the committed `uv.lock` during the image
build. The final runtime image does not include the package manager or
development/test dependencies.

Schema konfigurasi canonical berada di [.ai/knowledge/environment-schema.md](environment-schema.md). Engineer membuat `.env.example` di root berdasarkan schema yang sama; tidak boleh membuat template tandingan di `src/`, `config/`, atau `deploy/`.

## 5. Database jika ada, atau alasan stateless

SQLite is used for two small, controlled state sets:

1. index chunk corpus dengan metadata sumber dan versi corpus; dan
2. state teknis polling/idempotency agar restart tidak langsung memproses ulang update yang sudah selesai.

Tidak ada tabel atau file untuk isi percakapan. State runtime hanya boleh memuat versi index aktif, offset/update identifier, status teknis pengiriman, timestamp, durasi, dan kategori hasil. Tidak menyimpan nama pengguna, username, chat ID, teks pertanyaan, teks jawaban, atau payload Telegram.

The SQLite index, polling state, and lock file live under `/app/.runtime`, a
named Docker volume shared by the one-shot ingest command and the bot
container. Index rebuild writes a new temporary SQLite database and validates
it before activation. Activation is atomic and preserves the previous index
when a rebuild fails. Only one bot instance may use a given runtime volume at
a time; two polling instances are unsupported.

Corpus dan index turunan tetap `Confidential` dan harus memiliki permission file yang sesuai. State polling tidak menjadi arsip percakapan. Retensi state teknis dibatasi pada kebutuhan deduplication/recovery dan dibersihkan oleh runtime/operasi sesuai profile; durasi retention yang spesifik harus dikunci Engineer sebelum implementasi.

## 6. Catatan Keamanan & Robustness

### Authentication, Authorization, and Data Boundaries

- Token bot adalah credential `Restricted`, disediakan Human melalui runtime/credential store yang disetujui, dan tidak boleh masuk repository, prompt, fixture, screenshot, log, atau report.
- Tidak ada autentikasi per karyawan sesuai PRD. Operator wajib menjaga distribusi bot sebagai kanal internal; akses publik atau penggunaan pelanggan langsung berada di luar scope.
- Input Telegram harus menolak atau mengarahkan pengguna dari record individual, data transaksi, data pembayaran, data HR, credential, dan payload produksi. Aplikasi tidak boleh meneruskan data tersebut ke model.
- Corpus is processed only after the owner/manager approves the documents and verifies direct identities, credentials, signatures, personal contacts, and individual records have been removed.
- The image contains the approved Confidential corpus. Image tags, archives, and registry copies inherit that classification and require a Human-approved private distribution route.
- Docker build secrets are not used. The bot and model credentials are supplied only to the running container; the sandbox echo-bot token is not passed to it.

### Grounding, Sources, and Prompt Boundary

- Model hanya menerima konteks yang berasal dari index corpus aktif dan instruksi aplikasi yang tetap.
- Jawaban tidak boleh mengandalkan pengetahuan di luar konteks. Jika retrieval tidak cukup, model gagal, atau validator meragukan sumber, aplikasi mengirim respons tidak tahu.
- Nama sumber ditambahkan/divalidasi dari metadata index, bukan dipercaya dari teks bebas model.
- Respons tidak boleh menyertakan sumber yang tidak ada di chunk retrieved atau sumber yang tidak relevan.
- Perintah atau instruksi yang muncul di pertanyaan maupun corpus tidak boleh mengubah aturan aplikasi, akses file, atau credential boundary.

### Retry, Timeouts, and Partial Failure

- Polling melakukan reconnect/backoff terbatas ketika Telegram tidak tersedia; kegagalan polling tidak menghasilkan jawaban palsu.
- Panggilan model memiliki timeout terpisah dari polling. Jika melewati budget, aplikasi memilih abstention atau status error yang aman dan tidak mengklaim jawaban supported.
- Pengiriman Telegram memiliki timeout dan status `UNKNOWN` untuk hasil yang tidak dapat dipastikan. Retry otomatis tidak boleh menjanjikan exactly-once; kasus tidak pasti dicatat untuk operator tanpa menyimpan payload.
- Update diproses melalui identity Telegram dan state atomic. Duplicate/retry yang terdeteksi tidak memicu jawaban kedua.
- Rebuild index gagal secara fail-closed: index aktif lama tetap dipakai, dan corpus baru tidak disebut aktif.

### Shell, Files, and Observability

- Runtime tidak memanggil shell untuk memproses input eksternal. Bila launcher shell diperlukan, argumen harus dipisahkan sebagai argument array/parameter aman; input Telegram atau nama file eksternal tidak boleh diinterpolasikan ke command string.
- Path corpus harus di-resolve terhadap root project dan dicek agar tidak keluar dari boundary `docs/`.
- Log hanya berisi operation, timestamp, durasi, status, sanitized error category, corpus version, dan hasil supported/abstention/error. Redaction dilakukan sebelum logger menerima nilai.
- Dependency, file konfigurasi, dan runtime profile harus diaudit oleh Security pada tahap berikutnya. Architecture PASS bukan Security PASS.
- Compose must not publish container ports. The Telegram and model calls are outbound connections; no inbound webhook is part of this design.

## 7. Acceptance & Failure Scenarios

This acceptance matrix is version `1.1`, aligned with PRD `1.2`. Each
required row must map to implementation, test, fixture, command, and evidence.
Execution status is recorded in `.ai/project-state.md` and current reports;
this design table does not itself claim a runtime PASS.

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
| `AC-037 / REQ-007` | Valid Docker artifact | Build one tagged image from the approved source and corpus; load/promote that artifact to another compatible Docker host | The deployed image ID/digest matches the built artifact; Compose references the image and does not rebuild it | Docker build + image-load integration; required |
| `AC-038 / REQ-007` | Invalid build/runtime secret boundary | Use a synthetic marker in an ignored `.env` and inspect build context/image configuration without exposing real credentials | `.env*` and `.runtime/` are excluded from build context; no secret is baked into image layers/default environment; sandbox-only bot token is not passed to the service | Static build-context/image inspection; required |
| `AC-039 / REQ-007` | Duplicate/retry and persistence | Run ingest, replace the disposable bot container while reusing the named runtime volume | The active corpus version and technical polling state remain available after recreation; no transcript is stored; only one poller can hold the volume lock | Docker integration; required |
| `AC-040 / REQ-007` | Runtime isolation | Inspect and start the Compose service with a valid synthetic configuration | Process runs as UID/GID `10001`; root filesystem is read-only; Linux capabilities are dropped; no inbound ports are published; only `/app/.runtime` and bounded `/tmp` are writable | Compose static check + container inspection; required |
| `AC-041 / REQ-001, REQ-007` | Approved corpus update | Build a new image after an approved document change; stop the old service and run ingest against the existing named volume | The new image carries the new approved corpus; successful ingest atomically activates its version; failed ingest leaves the prior active index intact; operator instructions identify the sequence | Docker integration + operator handoff; required |

Target minimum yang berasal dari PRD tetap: isi `≥12/15`, sumber `12/12` supported, abstention `3/3`, dan waktu `<5,0 detik` untuk `15/15`. Matrix ini tidak mengklaim bahwa target tersebut telah tercapai. Engineer wajib membuat mapping `AC → implementation → test → fixture → command`; QA kemudian mengeksekusi secara independen.

## 8. Catatan Khusus: asumsi/risiko/batas yang belum terselesaikan

### 8.1 Milestone Delivery Plan

Pengerjaan dibagi menjadi milestone berurutan. Setiap milestone memiliki artefak, acceptance yang dituju, dan exit gate. Engineer tidak melompati gate yang gagal; skenario yang belum terbukti tetap `NOT_VERIFIED`. Tidak ada target waktu yang ditetapkan di tahap desain.

| Milestone | Fokus dan hasil utama | Acceptance / quality gate | Exit condition dan owner berikutnya |
|---|---|---|---|
| `M0` — Baseline & Gate | Human menyetujui PRD `1.2`, architecture `1.2`, ADR-001/ADR-005, schema environment, corpus manifest `00–25`, serta kandidat eval final 12+3 | PRD `1.2` approved; matrix `1.1` menjadi kontrak; data representation dan owner provisioning tercatat | Semua keputusan desain tidak ambigu; Human membuka Engineer |
| `M1` — Corpus Ingestion | Inventory, validasi, parsing Markdown, chunking heading-aware, hash versi corpus, rebuild index SQLite, dan atomic activation | `AC-001–005`, termasuk rebuild identik, invalid corpus, dan perlindungan index aktif lama | Baseline 26 file terindeks deterministik; Engineer melakukan self-test dan handoff |
| `M2` — Retrieval & Source Grounding | Search FTS5, metadata sumber, support gate, ranking, dan penolakan sumber di luar context | `AC-011–013`, `AC-017–018`, `AC-022–023` pada fixture sintetis dan mock model | Query supported menemukan sumber benar; query unsupported dapat diarahkan ke abstention; Engineer mengunci parameter retrieval sebelum eval |
| `M3` — Answering & Failure Control | Adapter model generik, format output, validator, abstention, timeout, provider failure, dan sanitized observability | `AC-015–016`, `AC-020–021`, `AC-025–026`; tidak ada isi pertanyaan/jawaban di log | Local model/mock melewati unit dan integration checks; kegagalan tidak menghasilkan success claim |
| `M4` — Telegram Polling | Polling loop, validasi update, state offset/idempotency, single-instance guard, dan send result handling | `AC-006–010`, `AC-014`, `AC-019`, `AC-024`; mock boundary dahulu, sandbox sesudah token disediakan | Satu update valid menghasilkan satu respons; duplicate dan Telegram failure terobservasi; Engineer/DevOps handoff |
| `M5` — Local End-to-End Eval | Runtime lokal menjalankan eval 12+3 melalui polling atau boundary sandbox yang disetujui; ukur sumber, abstention, isi, dan latency | `AC-027–031`; target PRD: isi `≥12/15`, sumber `12/12`, abstention `3/3`, waktu `<5,0 detik` `15/15` | Evidence per pertanyaan tersedia dan tersanitasi; hasil tidak langsung dianggap QA independent |
| `M6` — Operator Packaging | `.env.example`, panduan setup lokal, panduan rebuild/penggantian dokumen, command reproducible, dan demo tersanitasi | `AC-032–036`; required config fail-fast; rebuild dan runtime dapat diulang operator | Engineer self-test lengkap dengan mapping AC; Human menentukan handoff ke DevOps/QA |
| `M7` — Docker Packaging & Portable Runtime | Multi-stage Dockerfile from `uv.lock`; image includes application and approved corpus; Compose runs a selected prebuilt image, injects an explicit environment allowlist, and mounts persistent SQLite state; non-root/read-only/no-published-port runtime | `AC-037–041`; build artifact is identified by tag/digest; no credentials or generated state in build context/image; local container can rebuild the corpus and retain runtime state across recreation | Engineer/DevOps hands off the built image, digest, Compose runtime, operator update/transfer guide, and implementer evidence. No registry publication, VPS readiness, or deployment is included |
| `M8` — Independent Quality & Release | QA menjalankan seluruh required scenario; Security mengaudit source, dependency, config, dan boundary; DoD/release packet disusun | QA dan Security menghasilkan verdict independen; gap tetap `NOT_VERIFIED` dan tidak ditutup oleh self-test | Human memutuskan quality lalu release/deploy secara terpisah |

Aturan kualitas lintas milestone:

- setiap milestone menyimpan evidence di path yang ditentukan state dan menyebut versi artifact/candidate;
- fixture tetap sintetis dan tidak boleh memakai token, payload Telegram, record HR/pelanggan, atau data produksi;
- perubahan yang memengaruhi requirement atau matrix mengembalikan pekerjaan ke gate PRD/architecture yang terdampak;
- M1–M3 dapat dikerjakan tanpa credential Telegram; credential diperlukan mulai M4 sandbox dan hanya diprovision Human;
- M5 tidak boleh mengganti E2E Telegram dengan mock lalu menyatakan target waktu Telegram terbukti;
- M7 packages the Docker runtime and does not authorize image publication or deployment; Human separately approves the distribution route and any release action;
- jika milestone gagal, perbaiki scope milestone tersebut dan jalankan regression AC yang terdampak sebelum lanjut.

- **Approval gate:** Human approved PRD `1.2`, Architecture `1.2`, and the Docker packaging decision on `2026-10-11`; `.ai/project-state.md` records the exact scope.
- **Model dan provider:** sengaja tidak dikunci di PRD atau arsitektur. Adapter, format request/response, serta local test double harus dipilih Engineer tanpa mengubah kontrak grounding dan abstention.
- **Retrieval calibration:** SQLite FTS5 dipilih sebagai mekanisme sederhana. Ambang dukungan retrieval harus dikalibrasi terhadap eval 12+3 dan dicatat sebelum pengujian; tidak boleh menyembunyikan threshold di dalam kode tanpa dokumentasi.
- **Latency:** model lokal mungkin tidak memenuhi `<5,0 detik`. Ini risiko teknis yang harus dibuktikan melalui E2E; tidak boleh diganti dengan mock sebagai bukti waktu Telegram.
- **Telegram exactly-once:** API eksternal dapat membuat hasil pengiriman tidak pasti ketika koneksi putus setelah side effect. Desain mencatat `UNKNOWN` dan tidak menjanjikan exactly-once universal; mitigasi deduplication berlaku pada update yang identity-nya diketahui.
- **Shared bot without authentication:** anyone who obtains bot access can ask questions. Bot distribution controls are operational and do not provide technical authentication. The known open chat-scope issue remains before any externally accessible production use.
- **Retention:** the application stores no conversation content. The named runtime volume contains the index and minimal polling state only; backup, retention, and cleanup remain operator responsibilities and must not include transcripts.
- **Corpus approval:** dokumen baru/pengganti tidak aktif hanya karena file muncul di `docs/`; owner/manajer harus mengesahkannya dan rebuild harus menghasilkan versi yang dapat diidentifikasi.
- **No public ingress:** polling is used in the container. A future webhook requires an ADR and a renewed security/acceptance review.
- **Dataset approval:** CSV sumber sudah diperiksa secara struktural dan dikonfirmasi sintetis, tetapi salinan final 12+3 beserta kunci jawaban/sumber masih harus disahkan sebelum menjadi eval set approved.

## 9. Riwayat Perubahan

| Versi | Tanggal | Perubahan | ADR terkait |
|---|---|---|---|
| `1.0` | `2026-09-14` | Desain awal full-code tanpa n8n, Telegram long polling, model generik, index lokal, tanpa penyimpanan isi percakapan, dan matrix acceptance PRD 1.1 | `ADR-001-full-code-polling.md` |
| `1.1` | `2026-09-14` | Menambahkan milestone berurutan M0–M8, exit criteria, quality gate, dan aturan regresi sebelum handoff Engineer/DevOps/QA | `ADR-001-full-code-polling.md` |
| `1.2` | `2026-10-11` | Replaces host-specific VPS readiness with a Docker build-once/promote-by-digest milestone; adds image, secret-boundary, volume-persistence, and container-isolation acceptance scenarios; aligns the runtime profile and operator deliverables | `ADR-005-docker-image-runtime.md` |
