# Scope Card — Asisten Pengetahuan Internal Toko Makmur Jaya

- Delivery lane: `PROFESSIONAL` (disetujui Human pada `2026-09-13`)
- Scope version: `0.3`
- Tanggal: `2026-09-13`
- Status: `APPROVED`
- Sumber intake: brief Human `project-brief-rag-n8n.md`

## Tujuan dan pengguna

Toko Makmur Jaya membutuhkan asisten tanya-jawab internal agar kasir, pramuniaga, dan staf gudang dapat memperoleh jawaban yang konsisten dari SOP dan kebijakan resmi tanpa selalu menginterupsi manajer. Asisten hanya membantu karyawan; karyawan tetap menjadi pihak yang menyampaikan informasi kepada pelanggan.

Hasil bisnis yang dituju:

- menurunkan pertanyaan repetitif kepada manajer;
- meningkatkan konsistensi jawaban karyawan;
- membatasi jawaban pada pengetahuan resmi dan menyatakan tidak tahu bila dukungan dokumen tidak cukup.

## Scope

### In scope

- Menyiapkan ulang knowledge base dari seluruh dokumen resmi yang ada di folder `/docs`. Baseline scope version `0.2` adalah 26 file Markdown bernomor `00`–`25`: satu profil perusahaan, 8 SOP operasional, 7 FAQ pelanggan, 4 panduan komplain, dan 6 kebijakan internal.
- Menerima pertanyaan karyawan melalui satu bot Telegram bersama.
- Memberikan jawaban singkat yang didukung isi dokumen resmi.
- Menyertakan nama dokumen sumber pada jawaban yang didukung dokumen.
- Memberikan respons tidak tahu ketika jawaban tidak didukung knowledge base.
- Menjalankan ulang proses pemuatan dokumen ketika kebijakan atau SOP berubah.
- Menyerahkan dua workflow yang dapat diekspor (pemuatan dokumen dan tanya-jawab), panduan setup/penggantian dokumen, hasil evaluasi, serta bukti demo percakapan yang telah disanitasi.

### Out of scope

- Bot yang berinteraksi langsung dengan pelanggan.
- Integrasi dengan POS/kasir atau stok real-time.
- Autentikasi dan personalisasi per karyawan.
- Jawaban di luar isi dokumen resmi.
- Pemrosesan record individual karyawan atau pelanggan, credential, data pembayaran, dan data Restricted lainnya.

## Data & operational boundary

| Area | Klasifikasi awal | Representasi yang diizinkan | Batas / owner |
|---|---|---|---|
| SOP, FAQ, panduan komplain, dan kebijakan umum | `Confidential` karena merupakan materi internal klien | `minimized-and-masked`; gunakan corpus kebijakan yang sudah dibersihkan dari identitas langsung, credential, tanda tangan, kontak pribadi, dan record individual | Human/klien menyediakan dan menyatakan corpus resmi yang boleh diproses |
| Pertanyaan dan jawaban untuk pengembangan/evaluasi | `Internal` bila sepenuhnya sintetis; dapat menjadi `Confidential` atau `Restricted` bila berisi data nyata | `synthetic` sebagai default; contoh nyata hanya setelah minimisasi dan masking yang disetujui | PM/Engineer/QA hanya memakai fixture sintetis dalam artefak dan laporan |
| Kandidat eval set `QA_Dataset_15_Pasangan.csv` | `Internal` karena seluruh isi dikonfirmasi sintetis oleh Human pada `2026-09-13` | `synthetic`; boleh dipakai setelah disesuaikan dengan struktur 12 supported + 3 unsupported | Tim delivery menyiapkan salinan kerja; file sumber tidak diubah pada tahap PM |
| Credential bot, akses penyimpanan, dan layanan terkait | `Restricted` | `blocked` dari prompt, repository, fixture, screenshot, laporan, dan state | Human/klien melakukan provisioning melalui credential store/runtime yang disetujui pada tahap teknis |
| Record HR/pelanggan, transaksi, dan payload produksi | `Restricted` | `blocked` | Bukan bagian scope; bila ternyata diperlukan, pekerjaan berhenti untuk keputusan Human |

Keputusan Human `2026-09-13`: corpus resmi adalah seluruh isi folder `/docs`, termasuk `00_Company_Profile_Toko_Makmur_Jaya.md`. Baseline yang telah diamati berisi 26 file Markdown. Dokumen baru atau pengganti harus disahkan sebagai dokumen resmi sebelum proses pemuatan ulang.

Asumsi operasional awal: pemilik/manajer mengesahkan perubahan corpus dan menjadi owner operasi sampai Human menetapkan pihak lain. Sumber pemuatan resmi, mekanisme penambahan dokumen, dan batas retensi percakapan akan diperinci pada tahap desain tanpa mengubah keputusan bahwa `/docs` adalah corpus proyek.

## Kebutuhan bisnis dan hasil teramati

| ID | Kebutuhan bisnis | Prioritas | Hasil yang disepakati / masih perlu dikunci |
|---|---|---|---|
| `REQ-001` | Knowledge base memakai seluruh dokumen resmi yang berlaku di `/docs` dan dapat dimuat ulang ketika ada pembaruan | Wajib | Baseline memuat 26 file Markdown `00`–`25`; operator dapat menjalankan pemuatan ulang dan versi corpus yang berlaku dapat diidentifikasi |
| `REQ-002` | Karyawan internal dapat mengirim pertanyaan dan menerima respons melalui bot Telegram bersama | Wajib | Pertanyaan menerima satu respons yang dapat dibaca karyawan; tidak ada autentikasi per karyawan |
| `REQ-003` | Jawaban didasarkan pada isi dokumen resmi | Wajib | Pada eval set approved, minimal 12 dari 15 jawaban lulus rubric isi biner |
| `REQ-004` | Jawaban yang didukung knowledge base menyebut dokumen sumber yang benar | Wajib | Ketepatan sumber wajib 12/12 untuk pertanyaan supported; pertanyaan unsupported tidak boleh mengarang sumber |
| `REQ-005` | Sistem tidak mengarang jawaban ketika dukungan dokumen tidak memadai | Wajib | Pertanyaan unsupported pada eval set menghasilkan pernyataan tidak tahu dan tidak menyajikan klaim kebijakan yang tidak didukung |
| `REQ-006` | Respons cukup cepat untuk pemakaian operasional | Wajib | Waktu respons wajib `<5,0 detik` pada 15/15 pertanyaan, dari penerimaan oleh workflow hingga pengiriman ke Telegram berhasil |
| `REQ-007` | Hasil dapat disiapkan dan dipelihara oleh operator yang ditunjuk | Wajib | Tersedia workflow ekspor, panduan setup/penggantian dokumen, hasil evaluasi beserta catatan kegagalan, dan demo yang telah disanitasi |

## Rubric evaluasi yang disetujui

Eval set berjumlah 15 pertanyaan dan menggunakan wording sintetis. Kunci jawaban serta dokumen sumber disiapkan sebelum pengujian dan disahkan oleh pemilik/manajer. Komposisi final:

- 12 pertanyaan yang jawabannya tersedia di corpus: 3 SOP operasional, 3 FAQ pelanggan, 2 panduan komplain, 3 kebijakan internal, dan 1 profil perusahaan;
- 3 pertanyaan yang sengaja tidak memiliki jawaban di corpus untuk menguji perilaku tidak tahu.

Penilaian dilakukan per pertanyaan dengan nilai biner `LULUS` atau `GAGAL`:

1. Untuk pertanyaan supported, isi dinilai `LULUS` bila semua fakta wajib pada kunci jawaban tersampaikan, tidak bertentangan dengan dokumen, dan tidak menambahkan klaim kebijakan yang tidak didukung. Kalimat tidak harus sama persis dengan kunci.
2. Untuk pertanyaan unsupported, isi dinilai `LULUS` hanya bila bot dengan jelas menyatakan informasi tidak ditemukan/tidak diketahui, tidak menebak, dan tidak mencantumkan sumber palsu.
3. Sumber dinilai terpisah. Seluruh 12 pertanyaan supported wajib mencantumkan setidaknya satu nama file yang benar-benar mendukung jawaban; setiap sumber tambahan juga harus relevan. Untuk pertanyaan unsupported, keluaran yang benar adalah tanpa sumber atau penanda bahwa tidak ada sumber ditemukan.
4. Waktu respons diukur untuk setiap pertanyaan sejak pertanyaan diterima oleh workflow sampai pengiriman jawaban ke Telegram dinyatakan berhasil. Batas tegas adalah `<5,0 detik` untuk masing-masing dari 15 pertanyaan, bukan hanya nilai rata-rata.

Keputusan kelulusan keseluruhan:

- akurasi isi minimal `12/15` (`80%`);
- seluruh pertanyaan unsupported wajib lulus (`3/3`) agar kegagalan abstention tidak tertutup oleh skor total;
- ketepatan sumber wajib `12/12` untuk pertanyaan supported;
- waktu respons wajib `<5,0 detik` pada `15/15` pertanyaan;
- hasil tetap melaporkan nilai per pertanyaan dan catatan setiap kegagalan, bukan hanya skor agregat.

### Status kandidat eval set yang diberikan Human

Pemeriksaan struktur aman terhadap `D:\QA_Dataset_15_Pasangan.csv` menemukan:

- 15 baris dengan kolom `Pertanyaan`, `Jawaban_Benar`, dan `Dokumen_Sumber`;
- tidak ada sel kosong pada ketiga kolom dan seluruh pertanyaan unik;
- 11 baris merujuk dokumen yang ada dalam baseline `/docs`;
- 4 baris data (`3`, `7`, `8`, dan `15`) merujuk dokumen `26`, `27`, atau `29`, yang tidak ada dalam corpus resmi `00`–`25`;
- tidak ada baris yang secara eksplisit didefinisikan sebagai unsupported karena seluruh baris memiliki jawaban benar dan nama sumber.

Human memutuskan mempertahankan komposisi 12 supported + 3 unsupported dan mengonfirmasi seluruh isi dataset sintetis pada `2026-09-13`. Tiga dari empat baris di luar corpus akan menjadi skenario abstention dengan expected output “tidak tahu” dan tanpa sumber. Satu baris lainnya akan diganti dengan pertanyaan supported dari dokumen `00` agar cakupan profil perusahaan terwakili. Dataset menjadi kandidat yang boleh diproses, tetapi belum menjadi eval set approved sebelum penyesuaian dan pengesahan kunci jawaban selesai. Memasukkan dokumen `26`, `27`, atau `29` tetap merupakan perubahan scope corpus.

## Asumsi

- Pengguna adalah delapan karyawan internal dan satu bot dipakai bersama.
- Karyawan tetap melakukan pemeriksaan kewajaran sebelum menyampaikan jawaban kepada pelanggan.
- Knowledge base baseline berisi 26 dokumen Markdown `00`–`25` di `/docs` dan hanya memuat materi perusahaan/kebijakan umum, bukan kasus individual atau record transaksi/HR.
- Pemilik/manajer menjadi pengesah corpus dan owner operasi sementara sampai ada keputusan Human lain.
- Eval set 15 pertanyaan akan memakai data sintetis atau isi yang sudah diminimalkan dan dimasking.
- Persetujuan scope ini tidak memberikan izin untuk memakai credential, data produksi, atau record Restricted.

## Risiko dan rekomendasi lane

PM merekomendasikan `PROFESSIONAL` karena sistem memproses kebijakan internal termasuk kebijakan ketenagakerjaan, menggunakan kanal pesan pihak ketiga, dan menghasilkan jawaban probabilistik yang dapat memengaruhi tindakan operasional. Human menyetujui lane ini pada `2026-09-13`. Jalur ini memerlukan PRD dan arsitektur yang disetujui Human sebelum implementasi, lalu QA dan Security independen sebelum keputusan kualitas/rilis.

## Keputusan data

Human mengonfirmasi pada `2026-09-13` bahwa seluruh isi `QA_Dataset_15_Pasangan.csv` sepenuhnya sintetis. Dataset boleh diproses sebagai `Internal / synthetic`. File sumber tetap tidak diubah pada tahap PM; salinan kerja harus disesuaikan dan disahkan sebelum menjadi eval set approved.

## Riwayat revisi

| Versi | Tanggal | Perubahan | Diminta oleh |
|---|---|---|---|
| `0.1` | `2026-09-13` | Scope Card intake awal dan rekomendasi Professional Lane | Human / PM |
| `0.2` | `2026-09-13` | Professional Lane dicatat disetujui; corpus ditetapkan sebagai seluruh isi `/docs` dengan baseline 26 file Markdown; keputusan metrik dipersempit | Human |
| `0.3` | `2026-09-13` | Rubric 12 supported + 3 unsupported disetujui; rencana penyesuaian kandidat eval set dicatat; Scope & Lane ditutup sebagai approved | Human |
