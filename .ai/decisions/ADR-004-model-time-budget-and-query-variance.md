# ADR-004 — Anggaran waktu model dan batas varian kueri

- Status: `PROPOSED`
- Tanggal: `2026-09-17`
- Lane: `PROFESSIONAL`
- Mengubah: `src/rag_assistant/config.py` (default `llm_timeout`), `.env.example`, `README.md`, `.ai/knowledge/environment-schema.md` `1.3`
- Pengambil keputusan: `Human` (arah: **A2 + B1**, dipilih `2026-09-17`)
- Terkait: PRD `1.1` (`REQ-005`, `REQ-006`), architecture `1.1` §`20`/§`117`/§`245`, ADR-002, ADR-003

## Konteks

Saat runtime diuji langsung oleh Human, **setiap** jawaban berbunyi sama:

> *"Saya tidak menemukan informasi yang cukup di dokumen resmi untuk menjawab
> pertanyaan ini. Silakan hubungi manajer untuk kepastian."*

Termasuk pertanyaan yang sebelumnya **lulus** di eval sandbox M5. Itu dua sinyal
yang tidak dapat keduanya benar, jadi diukur.

### Temuan 1 — fallback timeout, bukan abstention

Log runtime untuk pertanyaan yang sama:

```
ERROR | op=answer | status=error | duration_ms=3000.0 | error_category=MODEL_TIMEOUT
```

Teks di atas adalah `ABSTENTION_TEXT`, dan `AnswerService` memakainya untuk
**dua** jalur berbeda: abstention yang sah, dan **fallback saat timeout**. Jalur
timeout ditandai `status=error`, tetapi yang sampai ke pengguna adalah teks yang
sama persis, tanpa pembeda yang terlihat.

Akarnya:

- `LLM_TIMEOUT_SECONDS=3`.
- Tidak ada `keep_alive` di mana pun (`grep -rn keep_alive src/ scripts/` →
  kosong). Ollama mengeluarkan model dari memori setelah idle (~5 menit);
  `/api/ps` mengembalikan `expires_at`.
- Permintaan berikutnya membayar cold load **25.654 ms** ≫ 3.000 ms → timeout.

Sebab `M5` tetap lulus: harness sandbox membayar
`model_prewarmed=True prewarm_ms=29175` sebelum jam mulai. Produksi **tidak**
prewarm dan **tidak** menahan model. Kondisi yang diukur harness bukan kondisi
yang dipertahankan runtime.

### Temuan 2 — gate leksikal tidak mengenal varian kata

Diukur dengan `LLM_TIMEOUT_SECONDS=120` (batas benar-benar hilang):

| Pertanyaan | Gate | Hasil |
|---|---|---|
| `Jam berapa toko Makmur Jaya tutup?` | sufficient | `Toko tutup pukul 21.00.` (25.654 ms, cold load) |
| `toko ini tutup jam berapa?` | sufficient | `Toko tutup pada pukul 21.00.` (878 ms) |
| `cuti tahunan berapa hari?` | sufficient | `12 hari per tahun.` (3.572 ms) |
| `kapan tokonya tutup?` | **insufficient** | abstain |
| `berapa jatah cuti setahun?` | **insufficient** | abstain |
| `Siapa pemenang piala dunia 1998?` | insufficient | abstain (benar) |

Parafrase dengan **kosakata sama** berhasil. Yang gagal hanya yang mengganti
kata: `tokonya` (sufiks `-nya`; `toko` bahkan stopword), `jatah`/`setahun`
(sinonim dari `hari`/`tahunan`).

Sebabnya `SupportGate(min_coverage=1.0)` — **setiap** term kueri harus muncul
verbatim di dalam chunk. Itu penetapan M2 yang di-approve dan di-ADR-kan,
bukan kecelakaan.

## Keputusan 1 — A2: `LLM_TIMEOUT_SECONDS` default `3` → `30`

Default aplikasi, `_OPTIONAL_DEFAULTS`, `.env`, dan `.env.example` dinaikkan ke
`30`.

- Anggaran waktu harus mencakup permintaan yang **modelnya belum residen**,
  karena itu keadaan yang berulang di produksi, bukan pengecualian.
- `30` mengabsorpsi cold load terukur (~26 s) dengan margin. Jawaban hangat
  tetap 1–4 s, jadi jalur tunak tidak berubah.
- Ini **plafon, bukan target**: `REQ-006` mengukur latensi tersampaikan terhadap
  ambangnya sendiri (`<5,0` detik). Menaikkan plafon tidak melonggarkan ambang
  itu, dan `M5` tetap mengukurnya.

**Diterima sadar:** timeout yang lebih panjang memperlambat kegagalan saat
endpoint benar-benar rusak. Dinilai sepadan: alternatifnya adalah jawaban salah
secara sistematis pada setiap permintaan dingin.

## Keputusan 2 — B1: batas varian kueri diterima dan didokumentasikan

Batasnya **tidak** diubah. Ia dicatat di `README.md` sebagai keterbatasan yang
diketahui, apa adanya:

- Sistem menjawab dalam kosakata yang ada di korpus; ia tidak memetakan sinonim.
- Ia **tidak** mengoreksi salah ketik dan tidak mengenali imbuhan
  (`tokonya`, `cutinya`).
- Pertanyaan di luar frasa korpus akan meng-abstain meskipun korpus memuat
  jawabannya.

Alasan tidak menambal: `architecture.md:20` dan `:117` mengunci *"Vector
database... tidak diperlukan"* dan *"tidak ada vector database"* — pencarian
semantik berada di luar cakupan yang disetujui. `architecture.md:245` mengunci
kalibrasi ambang dukungan terhadap eval 12+3. Menurunkan `min_coverage` akan
membatalkan seluruh baseline M2 yang disetujui dan invalidasi sepuluh pengukuran
yang dibangun di atasnya. Itu keputusan produk, bukan keputusan Engineer.

**Konsekuensi ke pengguna:** abstention **bukan** bukti korpus tidak memuat
jawabannya. Ia bisa berarti pertanyaannya memakai kata lain. Ini tampak jelas
setelah diukur, dan sebelumnya tidak terdokumentasi di mana pun.

## Tidak diperbaiki — dicatat

**Tidak ada allowlist chat pada runtime bot.** `__main__._run_bot` meneruskan
`update.chat_id` apa adanya ke `send_message`, tanpa penyaringan. Siapa pun yang
menemukan `@Agnes_1_BOT` dapat menanyakan kebijakan internal toko — termasuk
gaji, sanksi, dan cuti — lewat DM atau grup mana pun. Ini **pengungkapan
informasi**, bukan sekadar kebisingan.

Di luar dua keputusan di atas: allowlist adalah kontrol **lingkup akses**, tidak
berhubungan dengan anggaran waktu maupun batas kueri, dan menyentuh
`src/rag_assistant/__main__.py` serta `telegram/`. Direkomendasikan sebagai ADR
terpisah sebelum runtime menyentuh VPS (`M7`). Dicatat di sini supaya tidak
hilang.

## Alternatif yang ditolak

1. **A1 — kirim `keep_alive` per request (Ollama).** Menyerang sebab, bukan
   gejala: model tetap residen sehingga 3 s cukup. Ditolak karena `keep_alive`
   hanya ada di `POST /api/chat` milik Ollama; endpoint OpenAI-compatible tidak
   mengenalnya, sehingga ini menambah ketergantungan provider pada jalur yang
   dirancang provider-agnostik, dan harus punya fallback. Kandidat kuat untuk
   ditinjau ulang bila target deploy pasti Ollama — bahkan mungkin berdampingan
   dengan A2, karena keduanya menjawab hal berbeda: A1 menghindari cold load, A2
   menoleransinya.
2. **A3 — prewarm saat boot + ping berkala.** Tak bergantung `keep_alive`, tetapi
   menambah utas/timer ke runtime dan tetap menyisakan jendela setelah crash.
   Lebih banyak mekanisme daripada masalah yang diselesaikan pada tahap ini.
3. **A4 — pisahkan deteksi cold start dari anggaran waktu.** Kualitas angka
   `REQ-006` paling terjaga, tetapi paling rumit, dan permintaan pertama tetap
   tidak terlayani.
4. **B2 — normalisasi morfologis deterministik** (`-nya`, `-kah`, `-lah`).
   Leksikal murni, tidak melanggar "tanpa vector database", dan akan memulihkan
   `tokonya`. Ditolak untuk sekarang karena menyentuh `normalize_terms` — fungsi
   yang kalibrasi M2 bergantung padanya — dan hanya menutup satu dari beberapa
   kelas varian: `jatah`/`setahun` tetap gagal.
5. **B3 — peta sinonim/alias sebagai konfigurasi.** Deterministik dan terlihat,
   tetapi menambah kosakata retrieval = mengubah kalibrasi yang di-approve, dan
   harus dipelihara tangan. Sama seperti B2: menyentuh gate M2, jadi butuh
   keputusan produk.
6. **B4 — turunkan `min_coverage` 1.0 → 0.8.** Menangkap lebih banyak parafrase
   dengan satu angka. Ditolak: mengubah artefak M2 yang beku dan membatalkan
   seluruh baseline yang disetujui.

## Konsekuensi

- Identik pada konfigurasi default untuk **semua pengukuran M2/M5 yang
  disetujui**: eval memakai model hangat dan `LLM_TIMEOUT_SECONDS` tidak
  mengubah retrieval, gate, rubrik, maupun sumber. `content`/`sources`/
  `abstention` tidak bergerak.
- **Baseline latensi berubah maknanya.** Nilai `REQ-006` kini diukur terhadap
  plafon baru, bukan plafon `3` yang membuat setiap permintaan dingin gagal.
  Pengukuran lama yang menyebut "timeout 3 s" tidak lagi sebanding.
- **Jalur timeout tetap tidak fail-closed.** Ini sengaja dibiarkan dan sekarang
  didokumentasikan: `AnswerService` mengirim teks fallback sebagai respons
  sukses (`supported=False`, tanpa sumber) saat timeout. Mengubahnya menjadi
  respons gagal yang eksplisit adalah kerja terpisah yang menyentuh perilaku
  produksi dan agregasi `REQ-002`; belum diputuskan.
- `.ai/knowledge/environment-schema.md` naik `1.2` → `1.3` (safe example
  `LLM_TIMEOUT_SECONDS`). Menyentuh artefak approved ⇒ butuh persetujuan Human.
- Dijaga test: `tests/unit/test_llm_config.py` mengunci default baru `30` agar
  penurunan diam-diam kembali ke `3` tidak lolos.

## Batas bukti

Diukur pada **satu model lokal** (`gemma4:e2b-it-qat`), satu korpus (26 dokumen),
dan enam pertanyaan. Angka cold load (~26 s) spesifik model dan perangkat ini.
ADR ini tidak mengklaim nilai anggaran waktu yang benar untuk model atau
perangkat lain — hanya bahwa nilai yang dipilih harus mengakomodasi cold load,
dan bahwa `3` tidak.
