# Environment Schema — Asisten Pengetahuan Internal Toko Makmur Jaya

- Schema version: `1.2`
- Tanggal: `2026-09-17` (versi `1.1`: `2026-09-14`)
- Status: `APPROVED`. Versi `1.2` menambahkan satu baris `RAG_CONTEXT_LIMIT`
  berdasarkan ADR-002, disetujui Human `2026-09-17`. Tidak ada baris `1.1` yang
  diubah atau dihapus.
- Canonical template yang akan dibuat Engineer: `.env.example` di root project
- Nilai credential nyata tidak dicatat di sini.

| Name | Purpose / type | Required / optional / condition | Environment | Safe example | Owner / source | Secret? | Consumer / validation |
|---|---|---|---|---|---|---|---|
| `APP_ENV` | Profile enum aplikasi | Required | `local`, `test`, `vps` | `local` | Engineer / selected runtime profile | No | Entrypoint; hanya menerima profile yang didukung |
| `DOCS_PATH` | Root corpus resmi relatif terhadap project root | Required untuk ingest; tidak diperlukan bot setelah index tersedia | `local`, `test`, `vps` bila rebuild di host | `docs` | Human/manajer menentukan corpus; Engineer memvalidasi | No | Ingest; resolve path harus tetap di bawah `docs/` dan tidak keluar boundary |
| `INDEX_PATH` | Lokasi SQLite index dan state runtime | Required | `local`, `test`, `vps` | `.runtime/index.sqlite3` | Engineer / runtime profile | No | Ingest dan bot; parent directory dibuat aman, bukan path produksi pada test |
| `TELEGRAM_BOT_TOKEN` | Credential bot Telegram | Required untuk bot live; tidak diperlukan ingest; test memakai dummy/mocked boundary atau sandbox token yang diprovision Human | `local`, `test-sandbox`, `vps` | kosong: `TELEGRAM_BOT_TOKEN=` | Human/client melalui credential store/runtime injection | Yes | Polling/send client; validasi presence sebelum network, tidak pernah log nilainya |
| `TELEGRAM_POLL_TIMEOUT_SECONDS` | Durasi long polling request | Optional; default aplikasi tercatat oleh Engineer | `local`, `test`, `vps` | `30` | Engineer / Telegram runtime profile | No | Polling loop; positive numeric value, tidak menentukan SLA REQ-006 |
| `TELEGRAM_REQUEST_TIMEOUT_SECONDS` | Timeout request Telegram selain long polling | Required untuk bot runtime | `local`, `test`, `vps` | `4` | Architect/Engineer; dikalibrasi terhadap REQ-006 | No | Telegram client; positive numeric value dan tercatat dalam evidence |
| `LLM_BASE_URL` | Endpoint model generik OpenAI-compatible | Required untuk bot runtime; test dapat menunjuk mock lokal | `local`, `test`, `vps` | `http://127.0.0.1:8080/v1` | Human/Engineer berdasarkan runtime model yang dipilih | No | Model adapter; URL tervalidasi terhadap profile/allowlist target |
| `LLM_API_KEY` | Credential endpoint model bila diperlukan | Optional; kosong untuk Qwen lokal tanpa auth | `local`, `test`, `vps` | kosong: `LLM_API_KEY=` | Human melalui runtime injection bila endpoint memerlukan auth | Yes | Model adapter; tidak pernah dilog |
| `LLM_MODEL` | Identifier model generik | Required untuk bot runtime | `local`, `test`, `vps` | `local-default` | Human/Engineer melalui runtime profile | No | Model adapter; tidak boleh kosong atau placeholder saat runtime aktif |
| `LLM_TIMEOUT_SECONDS` | Batas waktu pembangkitan jawaban | Required untuk bot runtime | `local`, `test`, `vps` | `3` | Architect/Engineer; harus menyisakan headroom dari `<5,0 detik` | No | Model adapter; positive numeric value, timeout menghasilkan fallback aman |
| `RAG_CONTEXT_LIMIT` | Jumlah chunk konteks retrieval yang diserahkan ke model jawaban | Optional; default aplikasi `5`, yaitu nilai seluruh pengukuran M2/M5 yang di-approve | `local`, `test`, `vps` | `5` | Engineer/Architect; nilai optimal bergantung model jawaban (lihat ADR-002) | No | `build_retrieval_policy`; positive integer; **hanya** mengekspos `context_limit` — field support gate (`min_coverage`, `min_matched_terms`) tetap beku di kode |
| `MAX_QUESTION_CHARS` | Batas ukuran pertanyaan teks | Optional; default aplikasi harus didokumentasikan | `local`, `test`, `vps` | `2000` | Architect/Engineer | No | Update validator; positive integer, input di atas batas ditolak sebelum model |
| `LOG_LEVEL` | Level logging | Optional; default `info` | `local`, `test`, `vps` | `info` | Engineer / application default | No | Logger; enum tervalidasi dan tidak menonaktifkan redaction |

## Runtime profiles dan source precedence

Semua path relatif terhadap root project. Precedence yang dikunci: process environment atau injected runtime secret menang atas file profile; CLI aplikasi secara eksplisit memuat `.env` **hanya untuk profile `local`**; profile `test` dan `vps` menerima konfigurasi dari launcher/process environment; default aplikasi hanya berlaku untuk variabel optional. Nama sumber yang sama tidak boleh diam-diam mengambil nilai dari profile lain.

| Profile | Working directory / launcher | Sumber konfigurasi | Target dan boundary | Missing-value behavior |
|---|---|---|---|---|
| `local` | Root project; entry point Python ingest atau bot | Process environment mengalahkan `.env` lokal yang dimuat eksplisit oleh CLI | Folder `docs/`, SQLite lokal, model yang berjalan di endpoint lokal, dan bot yang diprovision Human | Required kosong/hilang/placeholder menghentikan startup sebelum network/write |
| `test` | Root project; command test terisolasi | Process environment dan `.env.test` yang dipilih eksplisit; tidak fallback ke `.env` | Fixture sintetis, SQLite test terpisah, mock/model lokal, Telegram mock atau sandbox yang disetujui | Required test value memakai dummy yang benar-benar valid untuk target test; target live ditolak |
| `vps` | Directory deployment yang ditetapkan DevOps; launcher service | Injected process environment/credential store; tidak mengandalkan file `.env` yang tidak diaudit | Satu service polling, corpus/index pada disk host yang dibatasi, model endpoint sesuai profile | Service tidak start dan tidak polling bila required config hilang/placeholder |

Engineer wajib membuat template root `.env.example` dengan nilai aman saja. Human mengisi credential melalui jalur runtime yang disetujui. `.env`, `.env.test`, backup, export credential, dan file key tidak boleh masuk Git atau log. Test profile tidak boleh membaca credential atau corpus production untuk menutup gap. Loader local hanya mendukung assignment sederhana `KEY=VALUE`, tidak melakukan interpolasi atau command execution, dan tidak menimpa process environment.

## Credential references

Tidak ada credential store n8n. Referensi credential yang direncanakan adalah `TELEGRAM_BOT_TOKEN` dan, bila endpoint model tidak lokal, `LLM_API_KEY` melalui runtime injection/credential store yang disetujui Human. Nilai credential tidak diperlukan untuk desain, implementasi sintetik, atau report. Jika target VPS menyediakan secret store khusus, DevOps mencatat nama referensi aman dan source precedence tanpa menyalin nilainya.

## Validasi dan verifikasi yang direncanakan

- Validasi konfigurasi harus menyebut nama variabel yang bermasalah, bukan nilainya, dan berhenti sebelum efek jaringan/tulis.
- Engineer menyediakan command validasi tanpa mencetak environment; exact command dan hasil aktual dicatat pada handoff.
- DevOps memverifikasi source precedence, isolasi test, dan target host; validasi konfigurasi bukan bukti bot berhasil.
- QA memverifikasi bahwa test tidak fallback ke `.env`, target VPS, corpus produksi, atau credential live.
