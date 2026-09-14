# ADR-001 — Full Code dan Telegram Long Polling

- Status: `APPROVED`
- Tanggal: `2026-09-14`
- Scope: PRD `1.1`, architecture `1.1`
- Pengambil keputusan: `Human`, disetujui bersama architecture `1.1` pada `2026-09-14`

## Keputusan

Implementasi menggunakan aplikasi Python penuh tanpa n8n atau platform orkestrasi workflow sejenis. Aplikasi memiliki entry point untuk rebuild knowledge base dan entry point untuk runtime bot Telegram. Telegram menggunakan long polling untuk runtime lokal dan VPS awal. Isi percakapan tidak disimpan; hanya state teknis minimum untuk polling, deduplication, timing, dan status operasi yang diperbolehkan.

## Alasan

Scope hanya mencakup satu bot internal, satu corpus lokal berisi 26 Markdown, dan dua alur yang dapat dinyatakan langsung sebagai kode. Long polling menghindari endpoint publik, domain, HTTPS termination, dan komponen ingress tambahan pada fase lokal maupun VPS. State teknis kecil tetap diperlukan untuk menjaga recovery, tetapi penyimpanan transcript akan memperbesar risiko data tanpa kebutuhan bisnis yang disetujui.

## Alternatif yang dipertimbangkan

1. **n8n atau platform orkestrasi:** tidak dipilih karena bertentangan dengan keputusan full-code dan menambah deployment/runtime surface yang tidak dibutuhkan.
2. **Webhook Telegram sejak awal:** tidak dipilih karena membutuhkan ingress publik dan TLS sebelum ada kebutuhan skala; dapat diajukan lagi sebagai perubahan struktur runtime.
3. **Database eksternal/vector database:** tidak dipilih karena 26 dokumen dapat diindeks lokal dengan SQLite FTS5 dan tidak ada kebutuhan multi-instance atau multi-tenant.
4. **Penyimpanan transcript:** tidak dipilih karena PRD tidak memerlukan histori percakapan dan data operasional dapat tetap diproses sementara di memori.

## Konsekuensi

- Satu instance polling aktif harus dijaga pada satu host.
- Tidak ada jaminan exactly-once universal ketika Telegram kehilangan koneksi setelah side effect pengiriman; kondisi tidak pasti harus terlihat sebagai `UNKNOWN`.
- Long polling cukup untuk scope awal tetapi bukan keputusan scaling tanpa batas.
- Migrasi ke webhook, multi-instance, atau penyimpanan histori memerlukan ADR dan review ulang data/acceptance.
