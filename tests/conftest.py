"""Shared test fixtures for rag_assistant.

Fixtures are synthetic and never use production data, credentials, or real corpus content.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def synthetic_docs(tmp_path: Path) -> Path:
    """Create a minimal synthetic corpus with 5 files (00-04) for fast unit tests."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    files = {
        "00_Profil_Perusahaan.md": """# Profil Perusahaan Toko Makmur Jaya

## Informasi Dasar
Toko Makmur Jaya adalah toko retail kebutuhan sehari-hari yang berdiri sejak 2015.
Lokasi: Jalan Raya Kecamatan No. 45.

## Jam Operasional
Toko buka setiap hari dari pukul 07.00 hingga 21.00.
""",
        "01_SOP_Buka_Toko.md": """# SOP Buka Toko

## Tujuan
Memastikan toko siap melayani pelanggan dengan standar keamanan dan kebersihan.

## Prosedur
1. Pengecekan keamanan area luar (06.30-06.40)
2. Pengecekan keamanan dalam (06.40-06.50)
3. Setup area kasir (06.50-07.00)
4. Setup area penjualan (07.00)
""",
        "02_FAQ_Pembayaran.md": """# FAQ Metode Pembayaran

## Pertanyaan Umum
### Apa saja metode pembayaran yang diterima?
Toko Makmur Jaya menerima pembayaran tunai, kartu debit, kartu kredit, dan QRIS.

### Apakah bisa cicilan?
Untuk pembelian elektronik di atas Rp 1.000.000, tersedia cicilan 0% selama 3 bulan.
""",
        "03_Panduan_Komplain.md": """# Panduan Komplain Barang Rusak

## Prosedur
1. Karyawan menerima keluhan dari pelanggan
2. Verifikasi kondisi barang (fisik dan bukti pembelian)
3. Tawarkan penggantian barang atau refund sesuai kebijakan garansi
4. Catat komplain di formulir komplain
""",
        "04_Kebijakan_Cuti.md": """# Kebijakan Cuti dan Izin Karyawan

## Hak Cuti
Setiap karyawan berhak mendapatkan cuti tahunan sebanyak 12 hari per tahun.

## Prosedur Pengajuan
1. Ajukan minimal 3 hari sebelum cuti
2. Isi form cuti dan serahkan ke manajer
3. Persetujuan dari manajer diperlukan
""",
    }

    for name, content in files.items():
        (docs_dir / name).write_text(content, encoding="utf-8")

    return docs_dir


@pytest.fixture
def config_local(tmp_path: Path, synthetic_docs: Path):
    """Create AppConfig for local test profile pointing to synthetic docs."""
    from rag_assistant.config import AppConfig

    return AppConfig(
        app_env="test",
        docs_path=synthetic_docs,
        index_path=tmp_path / ".runtime" / "index.sqlite3",
        expected_file_count=5,
        project_root=tmp_path,
    )


@pytest.fixture
def empty_docs(tmp_path: Path) -> Path:
    """Create an empty docs directory."""
    docs_dir = tmp_path / "docs_empty"
    docs_dir.mkdir()
    return docs_dir


@pytest.fixture
def invalid_docs(tmp_path: Path) -> Path:
    """Create a docs directory with invalid filenames (outside 00-25 range)."""
    docs_dir = tmp_path / "docs_invalid"
    docs_dir.mkdir()
    (docs_dir / "26_Extra_File.md").write_text("# Extra\nContent", encoding="utf-8")
    (docs_dir / "99_Bad_File.md").write_text("# Bad\nContent", encoding="utf-8")
    return docs_dir