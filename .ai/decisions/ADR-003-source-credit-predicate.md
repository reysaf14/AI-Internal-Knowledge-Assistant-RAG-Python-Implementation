# ADR-003 — Predikat kredit sumber pada evaluasi (`REQ-004`)

- Status: `APPROVED`
- Tanggal: `2026-09-17`
- Lane: `PROFESSIONAL`
- Mengubah: `src/rag_assistant/evaluation/runner.py`, `src/rag_assistant/evaluation/models.py`
- Pengambil keputusan: `Human`, disetujui `2026-09-17` — *"approve adr 003"*
- Terkait: Architecture `1.1` §7 (`AC-017`, `REQ-004`), PRD `1.1` (`REQ-003`, `REQ-004`), ADR-002

## Konteks

`REQ-004` menetapkan: *"Jawaban supported menyebut sumber yang benar"*, dengan
kriteria verifikasi *"Ketepatan sumber `12/12` untuk pertanyaan supported;
**setiap sumber tambahan harus relevan**"*.

`AC-017` menyatakan hal yang sama dalam bentuk yang bisa diuji:

> *"Setiap jawaban menyebut minimal satu sumber yang benar; sumber tambahan
> harus berasal dari context dan relevan"*

Implementasi `source_pass` pada `runner.py` menguji **predikat yang lebih ketat**
daripada kontrak itu:

```python
source_pass = (
    bool(sources)
    and bool(set(sources).intersection(case.expected_sources))
    and all(source in case.expected_sources for source in sources)   # subset persis
)
```

Syarat ketiga menuntut himpunan sumber yang dikutip menjadi **subset persis**
dari kunci approved. Akibatnya jawaban yang mengutip sumber **kedua yang sah**
dinilai gagal, meskipun kontrak hanya menuntut sumber tambahan itu *relevan*.

Sementara itu, relevansi **sudah** dijamin dan bersifat fail-closed di jalur
produksi: setiap jawaban melewati
`answering/validator.py::validate_model_answer`, yang meng-abstain seluruh
respons bila model menyebut sumber di luar konteks yang ter-retrieve. Jadi
syarat ketiga itu **menduplikasi jaminan yang tidak mungkin gagal di runtime** —
dan yang duplikatnya menolak jawaban benar.

## Bukti

Diukur pada rantai menjawab nyata, `RAG_CONTEXT_LIMIT=5`, eval 12+3 approved:

- **Sebelum perbaikan:** `sources=11/12`. Satu-satunya kegagalan sumber adalah
  `cand-14`.
- `cand-14` — *"Sakit tanpa surat dokter gaji bagaimana?"* — mengutip kunci
  approved `20_Kebijakan_Cuti_dan_Izin_Karyawan.md` **dan**
  `23_Kebijakan_Sanksi_Pelanggaran.md`.
- Dokumen 23 memuat bagian **"Sakit > 2 Hari Tanpa Surat Dokter"** →
  *"Gaji 0 untuk periode sakit"*.
- Dokumen 20 (kunci) memuat *"... tanpa surat (> 2 hari): akan dikurangi cuti
  tahunan **atau gaji**"*.
- Kunci jawaban approved: *"Gaji tidak dibayar untuk hari sakit (Rp 0) **dan**
  dikurangi dari cuti tahunan"*.

Kedua dokumen **saling melengkapi**, bukan bertentangan. Mengutip keduanya
adalah jawaban **paling akurat yang mungkin**, dan predikat lama menilainya
gagal. Ini keluarga cacat yang sama dengan `cand-04`: **alat ukurnya yang salah,
bukan sistemnya**.

**Setelah perbaikan:** `sources=12/12`, terukur dua kali — lewat runner lokal
(`run_candidate_eval.py`, `context_limit=5`, `acceptance_verdict` tidak lagi
`FAIL`) dan lewat eval sandbox Telegram penuh 15 pertanyaan (15/15 dijawab,
`duplicates=0`, `daily=0`).

### Koreksi klaim sebelumnya

Diagnosis awal cacat ini — dicatat di
`.ai/reports/build/gap-closure-status-2026-09-17.md` §5 — menyatakan bahwa
`cand-13` **juga** gagal karena ekstensi `.md`. **Itu keliru.** Kesalahan itu
muncul dari skrip diagnostik sekali-pakai yang menurunkan nama berkas tanpa
ekstensi, sehingga menciptakan ketidakcocokan palsu. Diukur ulang dengan
pembangun kasus produksi (`run_candidate_eval._cases`, yang menyertakan `.md`
seperti yang dinormalisasi evaluasi): **`cand-13` selalu lolos sumber** dan
gagal hanya pada `content`. Satu-satunya kegagalan sumber adalah `cand-14`, dan
begitu juga setelah perbaikan `cand-13` tetap `failures=content` saja. Klaim di
laporan itu dikoreksi, bukan dibiarkan berdiri.

## Keputusan

**Disetujui Human `2026-09-17`** (*"approve adr 003"*), setelah bukti di §Bukti
dan ketiga alternatif di §Alternatif ditolak.

`source_pass` diubah agar menguji predikat yang **secara harfiah diminta
kontrak**, diekstrak ke fungsi bernama yang dapat diuji:

```python
def source_credit_pass(cited, expected) -> bool:
    cited_set = set(cited)
    return bool(cited_set) and bool(cited_set & set(expected))
```

Dua syarat dipertahankan — persis yang dinyatakan kontrak: **harus ada sumber
yang dikutip**, dan **sumber yang diharapkan harus termasuk di dalamnya**.
Syarat "subset persis" dibuang; relevansi ditegakkan di validator, bukan di
evaluator.

Relevansi tetap terjaga meski syarat itu dibuang: nilai `sources` yang sampai ke
evaluator berasal dari `extract_claimed_sources` atas jawaban yang **sudah**
lolos `validate_model_answer`. Sumber di luar konteks meng-abstain di hulu, jauh
sebelum penilaian. Yang berubah hanyalah evaluator tidak lagi menghukum
**kelengkapan**.

## Alternatif yang ditolak

1. **Memperbaiki baris `cand-14` saja** (tambahkan dokumen 23 ke kunci approved).
   Lebih kecil, tetapi tidak menyelesaikan prinsipnya: sumber sah mana pun di
   luar daftar masih akan dianggap gagal, dan cacat akan muncul lagi pada
   pertanyaan berikutnya yang jawabannya melintasi dua dokumen.
2. **Membiarkan `11/12` sebagai `FAIL`.** Menjaga baseline apa adanya, tetapi
   melaporkan gagal pada baris yang buktinya menunjukkan jawaban benar — dan
   `REQ-004` adalah *hard gate*: melaporkan `FAIL` palsu menghalangi rilis
   dengan alasan yang salah.
3. **Melonggarkan penuh** (cukup ada sumber apa pun). Menghapus syarat "sumber
   yang diharapkan harus ada", sehingga jawaban yang menyebut dokumen keliru
   namun tetap di dalam konteks akan lolos. Ditolak: kontrak menyebut "minimal
   satu sumber yang benar", bukan "sumber apa saja".

## Konsekuensi

- `sources` naik `11/12` → **`12/12`** pada `RAG_CONTEXT_LIMIT=5` (default).
  Empat threshold PRD kini terpenuhi pada konfigurasi default.
- **Baseline approved berubah** pada metrik sumber. Setiap perbandingan terhadap
  angka `11/12` pra-ADR-003 harus menyebutkan ADR ini, karena angkanya berasal
  dari alat ukur yang berbeda.
- `metrics_match` dan `EvaluationSummary.metric_targets_match` juga diperbaiki:
  keduanya membandingkan `supported_content_passed` (metrik 12 baris) terhadap
  `12` sementara yang dilaporkan adalah `content` (metrik 15 baris). Dua
  predikat yang saling bertentangan itu membuat run dengan `content=12/15` dan
  seluruh target lain terpenuhi dicap `FAIL`. Kini gate memakai metrik 15 baris
  yang dilaporkan, sesuai `REQ-003` (*"sedikitnya `12/15`"*).
- **Tidak ada perubahan perilaku runtime.** `src/rag_assistant/answering/` tidak
  disentuh; jalur abstention, grounding, dan sumber palsu tidak berubah.
- `cand-05`, `cand-06`, `cand-13` tetap **gagal `content`** dan tetap ketat
  (`STRICT_ROWS`). Perbaikan ini tidak menyembunyikan kegagalan model; ia hanya
  berhenti menambah kegagalan yang bukan kegagalan.
- Dijaga 7 test: `tests/integration/test_m5_local_eval.py` (predikat + verdict) dan
  `tests/unit/test_eval_aggregation.py` (agregasi per-keluarga).

## Batas bukti

Bukti berasal dari **15 baris sintetis dan satu model lokal** (`gemma4:e2b-it-qat`,
`context_limit=5`). Ia menunjukkan bahwa satu baris dinilai salah oleh predikat
lama, dan bahwa perbaikan menaikkan metrik tanpa menurunkan yang lain pada set
itu. Ia **tidak** mengklaim keakuratan sumber secara umum di luar set approved.
`REQ-004` tetap *hard gate*: pengukuran ini tidak mengubah ambangnya.
