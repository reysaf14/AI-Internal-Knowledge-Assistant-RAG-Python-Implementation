# PRD — Asisten Pengetahuan Internal Toko Makmur Jaya

- Delivery lane: `PROFESSIONAL`
- Scope version: `0.3`
- PRD version: `1.0`
- Tanggal: `2026-09-13`
- Status: `APPROVED`
- Approved by: `Human`
- Approval date: `2026-09-13`

## Latar Belakang

SOP operasional, kebijakan pelanggan, panduan komplain, dan kebijakan internal Toko Makmur Jaya telah didokumentasikan, tetapi tersebar dan jarang dirujuk setelah pelatihan awal. Akibatnya, karyawan sering meminta jawaban kepada manajer dan dapat memberikan informasi yang tidak konsisten.

Project ini menyediakan asisten tanya-jawab internal bagi kasir, pramuniaga, dan staf gudang. Asisten harus menjawab berdasarkan dokumen resmi, menyebutkan sumber yang benar, dan menyatakan tidak tahu ketika corpus tidak mendukung jawaban. Karyawan tetap menjadi human-in-the-loop sebelum informasi diteruskan kepada pelanggan.

Tujuan bisnis:

- mengurangi interupsi repetitif kepada manajer;
- meningkatkan konsistensi jawaban karyawan;
- mempermudah pemakaian dan pembaruan pengetahuan resmi;
- mencegah jawaban kebijakan yang tidak didukung dokumen.

## Data & Operational Boundary

| Area | Kategori data | Representasi yang diizinkan | Sumber / tujuan dan owner |
|---|---|---|---|
| Corpus kebijakan | `Confidential` | `minimized-and-masked`; hanya materi yang telah dibersihkan dari identitas langsung, credential, tanda tangan, kontak pribadi, dan record individual | Sumber resmi adalah seluruh dokumen yang disahkan di `/docs`; baseline 26 file Markdown `00`–`25`. Pemilik/manajer mengesahkan perubahan corpus |
| Pertanyaan dan jawaban pengembangan/evaluasi | `Internal` bila sintetis; selain itu mengikuti kelas data aktual | `synthetic` sebagai default | Fixture dan laporan dimiliki tim delivery; kunci jawaban serta sumber disahkan pemilik/manajer sebelum evaluasi |
| Kandidat `QA_Dataset_15_Pasangan.csv` | `Internal` karena seluruh isi dikonfirmasi sintetis oleh Human pada `2026-09-13` | `synthetic`; boleh diproses menjadi salinan kerja yang sesuai rubric | Belum menjadi eval set approved sampai komposisi 12+3 dan kunci jawaban disesuaikan serta disahkan |
| Pertanyaan operasional karyawan | Berpotensi `Confidential` atau `Restricted` tergantung isi | Dibatasi pada pertanyaan kebijakan umum; pengguna tidak boleh memasukkan record individual, data transaksi, atau identitas pelanggan/karyawan | Masuk melalui kanal internal Telegram bersama dan menghasilkan jawaban kepada karyawan |
| Credential dan konfigurasi rahasia | `Restricted` | `blocked` dari prompt, repository, fixture, screenshot, laporan, dan project state | Human/klien melakukan provisioning melalui penyimpanan credential/runtime yang disetujui pada tahap teknis |
| Record HR/pelanggan, data pembayaran, dan payload produksi | `Restricted` | `blocked` | Di luar scope; kebutuhan baru atas data ini kembali ke Human untuk klasifikasi dan perubahan scope |

Pemilik/manajer menjadi pengesah corpus dan owner operasi awal sampai Human menetapkan pihak lain. Operator hanya memuat dokumen yang sudah disahkan. Dokumen yang ditambah atau diganti harus tercatat sebagai bagian corpus berlaku sebelum pemuatan ulang.

Tidak ada autentikasi per karyawan pada scope ini. Satu bot dipakai bersama oleh karyawan internal. Retensi percakapan dan mekanisme provisioning akan ditetapkan pada desain, tanpa memperluas izin penggunaan data.

## User Stories

- Sebagai karyawan toko, saya ingin bertanya dengan bahasa sehari-hari agar dapat menemukan kebijakan yang relevan tanpa selalu menghubungi manajer.
- Sebagai karyawan toko, saya ingin melihat nama dokumen sumber agar dapat memeriksa dasar jawaban sebelum menyampaikannya kepada pelanggan.
- Sebagai karyawan toko, saya ingin asisten mengakui ketika informasi tidak ditemukan agar saya tidak mengikuti jawaban yang dibuat-buat.
- Sebagai pemilik/manajer, saya ingin memperbarui corpus resmi agar jawaban mengikuti SOP dan kebijakan yang berlaku.
- Sebagai pemilik/manajer, saya ingin melihat hasil evaluasi dan kegagalan per pertanyaan agar kelayakan penggunaan dapat dinilai secara transparan.

## Fitur Wajib

| ID | Kebutuhan bisnis | Prioritas | Hasil yang disepakati |
|---|---|---|---|
| `REQ-001` | Knowledge base menggunakan seluruh dokumen resmi yang berlaku dan dapat dimuat ulang setelah pembaruan | Wajib | Baseline mencakup 26 dokumen Markdown `00`–`25`; operator dapat menjalankan pemuatan ulang dan mengidentifikasi corpus yang berlaku |
| `REQ-002` | Karyawan internal dapat mengirim pertanyaan dan menerima jawaban melalui bot Telegram bersama | Wajib | Setiap pertanyaan valid menghasilkan satu respons yang dapat dibaca karyawan; autentikasi/personalization per karyawan tidak disediakan |
| `REQ-003` | Isi jawaban hanya didasarkan pada corpus resmi | Wajib | Akurasi isi mencapai sedikitnya `12/15` pada eval set approved berdasarkan rubric biner yang tidak menuntut kecocokan kata-per-kata |
| `REQ-004` | Jawaban supported menyebut sumber yang benar | Wajib | Seluruh 12 pertanyaan supported mencantumkan setidaknya satu nama dokumen yang mendukung; setiap sumber tambahan juga relevan |
| `REQ-005` | Asisten tidak mengarang ketika corpus tidak mendukung jawaban | Wajib | Seluruh 3 pertanyaan unsupported menghasilkan pernyataan tidak tahu, tanpa klaim kebijakan atau sumber palsu |
| `REQ-006` | Respons tersedia dalam waktu yang layak untuk penggunaan operasional | Wajib | Masing-masing dari 15 pertanyaan eval menerima respons dalam `<5,0 detik`, diukur sejak workflow menerima pertanyaan sampai pengiriman jawaban ke Telegram dinyatakan berhasil |
| `REQ-007` | Hasil dapat disiapkan, dievaluasi, dan dipelihara oleh operator yang ditunjuk | Wajib | Tersedia dua workflow yang dapat diekspor, panduan setup/penggantian dokumen, hasil evaluasi per pertanyaan beserta catatan kegagalan, dan demo percakapan yang telah disanitasi |

## Fitur Tambahan

Tidak ada fitur tambahan pada version ini. Integrasi POS/stok real-time, autentikasi per karyawan, personalisasi, akses pelanggan langsung, dan jawaban di luar corpus tetap di luar scope.

## Kriteria Sukses

Eval set approved terdiri dari 15 pertanyaan sintetis:

- 12 pertanyaan supported: 3 SOP operasional, 3 FAQ pelanggan, 2 panduan komplain, 3 kebijakan internal, dan 1 profil perusahaan;
- 3 pertanyaan unsupported yang jawabannya sengaja tidak tersedia di corpus;
- kunci jawaban dan dokumen sumber ditetapkan sebelum pengujian serta disahkan pemilik/manajer.

Rubric isi menggunakan nilai biner `LULUS` atau `GAGAL`. Jawaban supported lulus bila seluruh fakta wajib tersampaikan, tidak bertentangan dengan corpus, dan tidak menambahkan klaim kebijakan yang tidak didukung. Jawaban unsupported lulus hanya bila menyatakan informasi tidak ditemukan/tidak diketahui, tidak menebak, dan tidak mencantumkan sumber palsu.

| Requirement | Kriteria keberhasilan | Dasar pengukuran aman |
|---|---|---|
| `REQ-001` | Seluruh 26 dokumen baseline tercatat sebagai corpus berlaku dan pemuatan ulang dapat menghasilkan corpus versi terbaru yang dapat diidentifikasi | Inventaris nama file dan metadata proses yang disanitasi; tanpa credential atau isi mentah dalam laporan |
| `REQ-002` | 15 pertanyaan eval masing-masing menghasilkan satu respons Telegram yang dapat dibaca | Fixture sintetis dan evidence eksekusi yang disanitasi |
| `REQ-003` | Minimal 12 dari 15 jawaban lulus rubric isi (`≥80%`) | Penilaian per pertanyaan terhadap kunci jawaban approved; wording tidak harus identik |
| `REQ-004` | Ketepatan sumber `12/12` untuk pertanyaan supported | Perbandingan nama dokumen yang disebut dengan sumber approved; setiap sumber tambahan harus relevan |
| `REQ-005` | Abstention `3/3` untuk pertanyaan unsupported | Pemeriksaan bahwa jawaban menyatakan tidak tahu, tidak membuat klaim kebijakan, dan tidak mengarang sumber |
| `REQ-006` | Waktu respons `<5,0 detik` pada `15/15` pertanyaan | Selisih timestamp penerimaan pertanyaan oleh workflow dan keberhasilan pengiriman respons; laporkan setiap durasi |
| `REQ-007` | Seluruh deliverable wajib tersedia dan dapat ditinjau oleh pemilik/manajer | Daftar artefak, panduan penggunaan, laporan evaluasi, dan demo tersanitasi; tidak ada credential atau payload mentah |

Kegagalan pada hard gate sumber, abstention, atau waktu respons tidak dapat ditutupi oleh skor akurasi agregat. Hasil evaluasi harus tetap menampilkan status setiap pertanyaan dan catatan kegagalan.

Kandidat eval set yang diberikan Human memerlukan penyesuaian agar sesuai dengan komposisi approved. Tiga baris di luar corpus akan menjadi unsupported dan satu baris di luar corpus akan diganti dengan pertanyaan supported dari dokumen `00`. Human telah mengonfirmasi seluruh isi kandidat sintetis, sehingga salinan kerja boleh disiapkan pada tahap berikutnya. File sumber tidak diubah pada tahap PM.

## Riwayat Revisi

| Versi | Tanggal | Perubahan | Diminta oleh |
|---|---|---|---|
| `1.0` | `2026-09-13` | PRD awal berdasarkan Scope Card `0.3` yang approved; menetapkan corpus 26 dokumen dan rubric 12 supported + 3 unsupported | Human |
