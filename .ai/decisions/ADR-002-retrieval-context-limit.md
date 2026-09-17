# ADR-002 — Retrieval Context Limit sebagai Konfigurasi, Bukan Hardcode

- Status: `APPROVED`
- Tanggal: `2026-09-17`
- Scope: ADR-001 (runtime), environment-schema `1.1`, gate M2
- Pengambil keputusan: `Human` (keputusan arah: *"default saja + adr"*; disetujui
  `2026-09-17` — *"ya approve, lanjutkan"*)

## Keputusan

`RetrievalPolicy.context_limit` tetap **default `5`** dan **tidak** diubah menjadi
`2`. Nilainya diangkat menjadi konfigurasi `RAG_CONTEXT_LIMIT` (default `5`) agar
dapat disetel tanpa mengubah kode, dan jalur produksi
(`python -m rag_assistant bot`) kini membacanya lewat
`build_retrieval_policy(cfg.rag_context_limit)`.

Seluruh parameter retrieval lain — `candidate_limit`, `min_matched_terms`,
`min_coverage`, `min_single_term_length` — **tetap beku di kode**. Hanya
`context_limit` yang diekspos.

Persetujuan yang diminta — **keduanya sudah dipenuhi** (`2026-09-17`):

1. ADR ini → `APPROVED`.
2. Baris `RAG_CONTEXT_LIMIT` pada environment-schema `1.1` → ditambahkan ke
   `.ai/knowledge/environment-schema.md` (versi `1.2`) setelah ADR ini disetujui.

Perubahan environment-schema yang menyertai ADR ini: versi `1.1` → `1.2`, satu
baris baru `RAG_CONTEXT_LIMIT`. Tidak ada baris lama yang diubah atau dihapus.

## Konteks

Audit rubrik eval (`2026-09-17`) memperbaiki false negative pada `cand-04` dan
menghasilkan baseline yang sah pada `context_limit=5`: content **12/15**, sources
11/12, abstention 3/3, latency 15/15. Pengukuran ulang dengan rubrik yang sudah
diperbaiki (`scripts/probe_context_limit.py --limits 5 5 2 2`, reproducible dua
kali per nilai):

| `context_limit` | content | sources | abstention | latency ≤5s | baris gagal |
|---|---|---|---|---|---|
| **2** | **13/15** | **12/12** | 3/3 | 15/15 | cand-05, cand-06 |
| **5** (default) | 12/15 | 11/12 | 3/3 | 15/15 | cand-05, cand-06, cand-13 |

Satu-satunya baris yang berbeda adalah `cand-13` (*"Bagaimana penanganan barang
kadaluarsa?"*). Pada limit 5 model menghasilkan boilerplate panjang (469 karakter)
tanpa `diskon`/`expired`; pada limit 2 jawabannya terfokus. `scripts/diagnose_context_assembly.py`
menunjukkan chunk yang benar sudah berada di `gate_rank=0`/`ctx_rank=0` pada semua
limit, jadi ini **dilusi konteks pada lapisan model**, bukan kegagalan retrieval
atau gate.

Data itu sempat terlihat seperti alasan kuat untuk menetapkan `2`. ADR ini
mencatat mengapa tidak.

## Alasan

1. **`context_limit` bukan properti sistem, melainkan properti pasangan
   sistem–model.** Ia mengatur berapa banyak konteks yang diserahkan ke model
   untuk dirangkai. Model kecil (gemma4 2B) mudah teralihkan chunk di luar topik,
   sehingga konteks sempit menolongnya. Model yang lebih besar biasanya menyaring
   lebih baik tetapi justru membutuhkan cakupan lebih luas untuk pertanyaan
   multi-hop, sehingga konteks sempit **merugikan**. Nilai optimal karena itu
   berpindah ketika model berpindah.

2. **Menetapkan `2` akan mengunci kompensasi untuk satu model ke dalam kode.**
   Siapa pun yang mengganti model di kemudian hari akan mewarisi angka yang
   dioptimalkan untuk model yang sudah tidak dipakai, tanpa ada yang mengingatkan.
   Ini persis jenis keputusan yang ADR ini ada untuk mencegahnya.

3. **Baseline yang di-approve diambil pada `5`.** Gate M2 (`min_coverage=1.0`,
   `min_matched_terms=2`) beserta seluruh bukti M2/M5 dikalibrasi dan diverifikasi
   pada `context_limit=5`. Mengubah default berarti mengubah artifact yang sudah
   di-approve; mempertahankan default berarti tidak ada satu pun klaim sebelumnya
   yang perlu ditinjau ulang. Default `5` karena itu juga satu-satunya nilai yang
   aman untuk lingkungan yang belum diukur.

4. **Mengekspos knob tidak mengubah perilaku.** Selama `RAG_CONTEXT_LIMIT` tidak
   diset, `_OPTIONAL_DEFAULTS` memberi `5` dan runtime berperilaku identik dengan
   sebelum ADR ini. Yang bertambah hanya kemampuan menyetel, bukan nilai.

5. **Knob ini menutup celah yang sudah terukur, tanpa menciptakan celah baru.**
   Sebelumnya satu-satunya cara mengubah `context_limit` adalah mengedit `src/`,
   yaitu perubahan kode untuk sesuatu yang sepenuhnya konfigurasi. Sejak ADR ini,
   mengganti model menjadi perubahan `.env` — dan `scripts/probe_context_limit.py`
   tetap menjadi alat pembanding sebelum/sesudah.

## Alternatif yang dipertimbangkan

1. **Tetapkan `context_limit=2` sebagai default (skor tertinggi terukur):**
   tidak dipilih. Menaikkan content 12/15 → 13/15 pada model saat ini, tetapi
   mengunci kompensasi untuk satu model ke dalam kode, mengubah artifact yang
   di-approve, dan merugikan model berikutnya secara diam-diam.

2. **Biarkan `context_limit` beku di kode, tanpa knob:** tidak dipilih. Lebih
   konservatif, tetapi memaksa edit `src/` untuk sesuatu yang bersifat
   konfigurasi tiap kali model berganti — persis titik gesek yang seharusnya
   dihapus, dan risiko perubahan kode yang tidak perlu pada jalur yang sudah
   tervalidasi.

3. **Ekspos seluruh `RetrievalPolicy` (termasuk gate) sebagai env:** tidak
   dipilih. Field gate menentukan **apakah** sebuah pertanyaan boleh dijawab sama
   sekali. `min_coverage=1.0` adalah artifact approved; satu nilai `.env` yang
   salah dapat membuat sistem menjawab pertanyaan yang seharusnya diabstain, dan
   itu kegagalan yang senyap. Field gate tetap beku; `candidate_limit` juga,
   karena ia mengubah kumpulan kandidat yang dinilai gate.

4. **Naikkan timeout agar model dingin tetap menjawab (mis. `LLM_TIMEOUT_SECONDS=30`):**
   tidak dipilih untuk ADR ini. Timeout adalah tuas tersendiri terhadap budget
   REQ-006 `<5,0 detik` dan perlu pengukurannya sendiri; mencampurnya ke sini akan
   mengaburkan sebab kenaikan skor. Dicatat sebagai kandidat ADR terpisah.

5. **Auto-tune `context_limit` saat startup:** tidak dipilih. Menambah panggilan
   model pada jalur startup, mempersulit reproduksi baseline, dan memindahkan
   keputusan kalibrasi dari manusia ke heuristik tanpa bukti.

## Konsekuensi

- **Default tidak berubah.** `context_limit=5`; seluruh klaim M2/M5 yang
  di-approve tetap sah tanpa peninjauan ulang. Nol perubahan perilaku selama
  `RAG_CONTEXT_LIMIT` tidak diset.
- `RAG_CONTEXT_LIMIT` menjadi satu-satunya knob retrieval. Penyalahgunaan yang
  membahayakan (gate) tidak dapat dijangkau dari env — dijamin 8 test kontrak.
- **Setiap penggantian model wajib diikuti pengukuran ulang** dengan
  `scripts/probe_context_limit.py --limits 5 2` dan pencatatan hasilnya. Tanpa
  langkah ini, angka pada tabel di atas tidak berlaku untuk model baru.
- Selama `RAG_CONTEXT_LIMIT` diset ke nilai selain `5`, hasil eval **tidak
  setara** dengan baseline approved dan tidak boleh disajikan sebagai
  reproduksi M2/M5.
- **Batas bukti.** Seluruh angka berasal dari 15 baris eval pada satu model
  (gemma4 2B) dan satu korpus (26 dokumen). Selisih satu baris (`cand-13`) tidak
  cukup untuk menyatakan salah satu nilai lebih baik secara umum; yang dapat
  dinyatakan hanya bahwa pada model ini, pengukuran ini, limit 2 menghasilkan
  13/15 dan limit 5 menghasilkan 12/15. Klaim yang lebih kuat menuntut dataset
  lebih besar.
- **`cand-05` dan `cand-06` tidak dapat diperbaiki oleh knob ini** pada nilai apa
  pun yang diukur (1–5) — keduanya kegagalan model (jawaban bagian salah, daftar
  tidak lengkap) dan hanya berubah bila model diganti.
- Melampaui ADR ini (default selain 5, knob baru pada policy, atau mengubah gate
  M2) memerlukan ADR baru. Mengubah `min_coverage` juga menuntut peninjauan ulang
  data/acceptance, sesuai ADR-001.
- `run_candidate_eval.py` dan `run_local_csv_eval.py` **ikut** membaca knob dan
  mencetak `context_limit=<nilai>` di buktinya. Sebelum penyesuaian ini kedua
  skrip itu selalu memakai `5` sambil mengabaikan `RAG_CONTEXT_LIMIT`, sehingga
  laporan yang dijalankan pada limit lain akan menyajikan angka yang berbeda
  tanpa menyebutkannya. Nilai yang tercetak itulah yang membuat sebuah hasil
  dapat dibandingkan atau tidak dengan baseline approved.
