"""
RMD-TRA — stats_tools.py
Pilar 2: Validasi Komputasi & Interpretasi Data

Function Tools untuk parsing output SPSS, SmartPLS, dan validasi ServQual.
PRINSIP: Agen TIDAK boleh menebak angka statistik. Semua angka diambil
dari teks yang disediakan pengguna melalui parser deterministik.

Referensi: Day 2 — Agent Tools & Interoperability (Function Calling)
"""

from __future__ import annotations
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Tool 1 — Parser Output SPSS
# ---------------------------------------------------------------------------
def parse_spss_output(spss_text: str) -> dict:
    """
    Membaca teks output SPSS yang di-paste pengguna dan mengekstrak
    koefisien jalur, nilai-t, p-value, dan R-squared secara deterministik.
    Agen TIDAK menebak angka — semua diambil dari teks input.

    Args:
        spss_text: Teks hasil output SPSS (copy-paste dari software).

    Returns:
        dict berisi angka-angka statistik yang berhasil diekstrak
        beserta interpretasi naratif untuk bab Pembahasan.
    """
    results = {
        "source": "SPSS",
        "coefficients": [],
        "r_squared": None,
        "f_statistic": None,
        "model_significant": None,
        "narrative": "",
        "warnings": []
    }

    # Ekstrak koefisien Beta (standardized)
    beta_pattern = re.compile(
        r'(?P<var>[\w\s]+?)\s+'
        r'(?:Beta|β)\s*[=:]?\s*(?P<beta>-?\d+\.\d+)'
        r'(?:.*?[tp]\s*[=<>]?\s*(?P<sig>-?\d+\.\d+))?',
        re.IGNORECASE
    )
    for m in beta_pattern.finditer(spss_text):
        beta = float(m.group("beta"))
        p_raw = m.group("sig")
        p_val = float(p_raw) if p_raw else None

        results["coefficients"].append({
            "variable": m.group("var").strip(),
            "beta": beta,
            "p_value": p_val,
            "significant": (p_val < 0.05) if p_val is not None else None,
            "effect_size": (
                "besar" if abs(beta) >= 0.5
                else "sedang" if abs(beta) >= 0.3
                else "kecil"
            )
        })

    # Ekstrak R-squared
    r2 = re.search(r'R[²2]\s*[=:]\s*(\d+\.\d+)', spss_text, re.IGNORECASE)
    if r2:
        results["r_squared"] = float(r2.group(1))

    # Ekstrak F-statistic
    f_stat = re.search(r'F\s*[=(:]\s*(\d+\.\d+)', spss_text, re.IGNORECASE)
    if f_stat:
        results["f_statistic"] = float(f_stat.group(1))

    # Cek signifikansi model
    sig_match = re.search(r'Sig\.\s*[=<]\s*(\d+\.\d+)', spss_text, re.IGNORECASE)
    if sig_match:
        results["model_significant"] = float(sig_match.group(1)) < 0.05

    # Peringatan jika tidak ada angka terdeteksi
    if not results["coefficients"]:
        results["warnings"].append(
            "Tidak ada koefisien Beta yang terdeteksi. "
            "Pastikan format output SPSS mengandung kolom 'Beta' atau 'β'."
        )

    # Hasilkan narasi pembahasan
    results["narrative"] = _build_spss_narrative(results)
    return results


def _build_spss_narrative(r: dict) -> str:
    if not r["coefficients"]:
        return (
            "Tidak dapat menghasilkan narasi karena tidak ada koefisien "
            "yang berhasil diekstrak. Periksa format teks SPSS yang Anda berikan."
        )
    parts = []
    for c in r["coefficients"]:
        sig_txt = (
            "secara statistik signifikan (p < 0,05)"
            if c["significant"]
            else "tidak signifikan secara statistik (p ≥ 0,05)"
            if c["significant"] is False
            else "signifikansinya belum dapat ditentukan"
        )
        parts.append(
            f"Variabel {c['variable']} memiliki koefisien Beta sebesar "
            f"{c['beta']:.3f} dengan efek yang tergolong {c['effect_size']}, "
            f"dan {sig_txt}."
        )
    narasi = " ".join(parts)
    if r["r_squared"] is not None:
        narasi += (
            f" Secara keseluruhan, model ini mampu menjelaskan "
            f"{r['r_squared']*100:.1f}% variansi variabel dependen "
            f"(R² = {r['r_squared']:.3f})."
        )
    return narasi


# ---------------------------------------------------------------------------
# Tool 2 — Parser Output SmartPLS (SEM/PLS)
# ---------------------------------------------------------------------------
def parse_smartpls_report(smartpls_text: str) -> dict:
    """
    Membaca teks laporan SmartPLS dan mengekstrak path coefficients,
    T-statistics, P-values, dan AVE/CR untuk outer model.

    Args:
        smartpls_text: Teks hasil SmartPLS (copy-paste dari report).

    Returns:
        dict berisi hasil path analysis dan interpretasi SEM.
    """
    results = {
        "source": "SmartPLS",
        "path_coefficients": [],
        "outer_model": [],
        "model_fit": {},
        "narrative": "",
        "warnings": []
    }

    # Pola path coefficient: X -> Y, coef, T, P
    path_pattern = re.compile(
        r'(?P<from>[\w\s]+?)\s*[-→>]+\s*(?P<to>[\w\s]+?)\s+'
        r'(?P<coef>-?\d+\.\d+)\s+'
        r'(?P<t_stat>\d+\.\d+)\s+'
        r'(?P<p_val>\d+\.\d+)',
        re.IGNORECASE
    )
    for m in path_pattern.finditer(smartpls_text):
        p = float(m.group("p_val"))
        coef = float(m.group("coef"))
        results["path_coefficients"].append({
            "from": m.group("from").strip(),
            "to": m.group("to").strip(),
            "coefficient": coef,
            "t_statistic": float(m.group("t_stat")),
            "p_value": p,
            "supported": p < 0.05,
            "direction": "positif" if coef > 0 else "negatif"
        })

    # AVE dan CR untuk validitas konvergen
    ave = re.findall(r'AVE\s*[=:]\s*(\d+\.\d+)', smartpls_text, re.IGNORECASE)
    cr  = re.findall(r'(?:CR|Composite Reliability)\s*[=:]\s*(\d+\.\d+)', smartpls_text, re.IGNORECASE)
    if ave:
        results["outer_model"].append({"metric": "AVE", "values": [float(v) for v in ave]})
    if cr:
        results["outer_model"].append({"metric": "CR", "values": [float(v) for v in cr]})

    if not results["path_coefficients"]:
        results["warnings"].append(
            "Tidak ada path coefficient yang terdeteksi. "
            "Format yang diharapkan: 'VariabelA -> VariabelB  0.456  5.123  0.001'"
        )

    results["narrative"] = _build_sem_narrative(results)
    return results


def _build_sem_narrative(r: dict) -> str:
    if not r["path_coefficients"]:
        return "Narasi tidak dapat dibuat karena tidak ada path coefficient yang terdeteksi."
    parts = []
    for p in r["path_coefficients"]:
        status = "didukung (supported)" if p["supported"] else "tidak didukung (not supported)"
        parts.append(
            f"Jalur dari {p['from']} ke {p['to']} memiliki koefisien jalur "
            f"sebesar {p['coefficient']:.3f} dengan arah {p['direction']} "
            f"(T-statistik = {p['t_statistic']:.3f}, p = {p['p_value']:.3f}), "
            f"sehingga hipotesis ini {status}."
        )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Tool 3 — Validator ServQual Transportasi Publik
# ---------------------------------------------------------------------------
def validate_servqual_dimensions(
    dimensions_text: str,
    context: Optional[str] = "transportasi publik"
) -> dict:
    """
    Memverifikasi konsistensi penggunaan kelima dimensi ServQual dalam
    konteks transportasi publik: Tangibles, Reliability, Responsiveness,
    Assurance, dan Empathy.

    Args:
        dimensions_text: Teks yang menyebutkan dimensi ServQual.
        context: Konteks layanan (default: "transportasi publik").

    Returns:
        dict berisi status validasi setiap dimensi dan rekomendasi.
    """
    canonical = {
        "Tangibles": [
            "tangible", "bukti fisik", "fasilitas fisik",
            "penampilan", "kondisi armada", "kebersihan kendaraan"
        ],
        "Reliability": [
            "reliability", "keandalan", "ketepatan waktu",
            "jadwal", "konsistensi layanan", "ketepatan jadwal"
        ],
        "Responsiveness": [
            "responsiveness", "daya tanggap", "ketanggapan",
            "kecepatan pelayanan", "respons petugas"
        ],
        "Assurance": [
            "assurance", "jaminan", "keamanan", "kepercayaan",
            "kompetensi petugas", "rasa aman"
        ],
        "Empathy": [
            "empathy", "empati", "perhatian individual",
            "kepedulian petugas", "layanan personal"
        ]
    }

    text_lower = dimensions_text.lower()
    found, missing = {}, []

    for dim, keywords in canonical.items():
        hits = [kw for kw in keywords if kw in text_lower]
        if hits:
            found[dim] = hits
        else:
            missing.append(dim)

    transport_context = {
        "Tangibles": "kondisi fisik armada (bus/kereta), kebersihan, dan fasilitas halte/stasiun",
        "Reliability": "ketepatan waktu kedatangan dan keberangkatan sesuai jadwal",
        "Responsiveness": "kecepatan petugas dalam menangani keluhan penumpang",
        "Assurance": "keamanan dan keselamatan selama perjalanan",
        "Empathy": "perhatian individual kepada penumpang berkebutuhan khusus"
    }

    return {
        "context": context,
        "total_dimensions": 5,
        "found": list(found.keys()),
        "missing": missing,
        "completeness": f"{len(found)}/5 dimensi terdeteksi",
        "status": "[Lengkap]" if not missing else f"[Perhatian] {len(missing)} dimensi belum muncul",
        "transport_interpretations": {
            dim: transport_context[dim] for dim in found
        },
        "recommendation": (
            "Semua dimensi ServQual sudah tercakup dalam instrumen Anda."
            if not missing else
            f"Dimensi berikut belum terdeteksi dan perlu ditambahkan: "
            f"{', '.join(missing)}. Dalam konteks {context}, "
            + " dan ".join([transport_context[m] for m in missing])
            + " merupakan aspek yang krusial untuk diukur."
        )
    }
