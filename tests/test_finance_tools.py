"""
RMD-TRA — tests/test_finance_tools.py
Test untuk verifikasi angka finansial otomatis (Pilar 5, Poin A):
1. Parsing angka gaya Indonesia vs Barat dalam satu dokumen.
2. Deteksi inkonsistensi NPV/IRR/BCR/PBP lintas dokumen (Abstrak vs Bab IV).
3. Hitung ulang NPV/BCR dari tabel arus kas, termasuk baris investasi awal (t=0).

Jalankan: uv run pytest tests/test_finance_tools.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.pillar5.finance_tools import (  # noqa: E402
    _parse_id_number,
    extract_labeled_figures,
    recompute_bca_from_tables,
)


def test_parse_id_number_indonesian_style():
    assert _parse_id_number("5.290.190.887") == 5290190887.0
    assert _parse_id_number("35,8") == 35.8
    assert _parse_id_number("0,64") == 0.64
    assert _parse_id_number("5.290.190,50") == 5290190.5


def test_parse_id_number_western_style():
    assert _parse_id_number("1,970,154,295") == 1970154295.0
    assert _parse_id_number("1,970,154.295") == 1970154.295
    assert _parse_id_number("0.9091") == 0.9091


def test_extract_labeled_figures_detects_real_inconsistency():
    text = (
        "ABSTRAK\nHasil analisis menunjukkan nilai NPV bus listrik sebesar Rp 5.290.190.887 "
        "dan IRR sebesar 35,8% sehingga investasi dinyatakan layak.\n\n"
        "BAB IV HASIL DAN PEMBAHASAN\n"
        "Hasil analisis kelayakan menunjukkan nilai NPV bus listrik sebesar Rp 4.596.212.966 "
        "dan IRR sebesar 30,8% sehingga investasi dinyatakan layak secara finansial.\n"
    )
    result = extract_labeled_figures(text)
    assert result["inconsistencies_found"] >= 1
    npv_inc = next((i for i in result["inconsistencies"] if i["indicator"] == "NPV"), None)
    assert npv_inc is not None
    assert npv_inc["subject"] == "bus listrik"


def test_extract_labeled_figures_no_false_positive_for_different_subjects():
    """
    NPV bus listrik dan NPV bus diesel BOLEH beda nilai — itu wajar, bukan galat.
    """
    text = (
        "Nilai NPV bus diesel sebesar Rp 10.329.812.880, sedangkan "
        "NPV bus listrik sebesar Rp 4.596.212.966.\n"
        "Nilai NPV bus listrik sebesar Rp 4.596.212.966 juga dikonfirmasi pada bagian lain.\n"
    )
    result = extract_labeled_figures(text)
    # NPV bus listrik disebut 2x dengan nilai SAMA -> konsisten, bukan galat
    npv_listrik = [
        i for i in result["inconsistencies"]
        if i["indicator"] == "NPV" and i["subject"] == "bus listrik"
    ]
    assert npv_listrik == []


def test_extract_labeled_figures_ignores_unrelated_numbers():
    """
    Angka yang tidak terkait (mis. periode analisis, tingkat diskonto) yang
    kebetulan dekat nama indikator TIDAK boleh ikut tertangkap sebagai nilainya.
    """
    text = (
        "Metode analisis yang digunakan meliputi Net Present Value (NPV), "
        "Internal Rate of Return (IRR), Payback Period (PBP), dan Benefit-Cost "
        "Ratio (BCR) dengan periode analisis selama 10 tahun.\n"
        "Perhitungan Net Present Value (NPV) dilakukan dengan menggunakan "
        "tingkat diskonto sebesar 10% dan periode analisis 10 tahun.\n"
    )
    result = extract_labeled_figures(text)
    assert result["total_mentions_found"] == 0


def test_recompute_bca_includes_initial_investment_row():
    """
    Baris investasi awal (kolom Tahun kosong, konvensi t=0) wajib ikut dihitung
    — kalau terlewat, NPV hasil hitung ulang akan jauh lebih besar dari yang benar.
    Tabel harus punya kolom Manfaat & Biaya terpisah (mode "net") supaya NPV
    benar-benar dihitung — kolom "Arus kas" tunggal sengaja TIDAK dihitung
    (lihat test_recompute_single_column_not_forced) karena ambigu.
    """
    table = (
        "[TABEL]\n"
        "Tahun | Manfaat | Biaya\n"
        " | 0 | 1,800,000,000\n"
        "1 | 1,970,154,295 | 0\n"
        "2 | 1,975,834,295 | 0\n"
        "[/TABEL]"
    )
    document_text = "tingkat diskonto sebesar 10%\n" + table
    result = recompute_bca_from_tables(document_text)
    assert result["recomputed"], "Tabel arus kas seharusnya berhasil dikenali"
    entry = result["recomputed"][0]
    assert entry["reliable"], "Tabel dengan kolom Manfaat & Biaya harus dihitung andal"
    npv = entry["npv_recomputed"]
    # Tanpa baris investasi awal, NPV akan jauh di atas 3 miliar (cuma benefit tanpa
    # dikurangi investasi). Dengan baris awal diikutsertakan, NPV harus lebih rendah.
    assert npv < 2_000_000_000


def test_recompute_bca_returns_none_status_for_unrecognized_table():
    table = "Kolom A | Kolom B\nBaris 1 | Baris 2\n"
    result = recompute_bca_from_tables("", [table])
    assert result["recomputed"] == []
    assert "tidak dapat dilakukan" in result["status"].lower()
