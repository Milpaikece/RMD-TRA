"""
RMD-TRA — agent.py  (versi lengkap 4 Pilar)
Pilar 1: RAG + Chronological Filter + Citation Corrector
Pilar 2: Function Calling SPSS/SmartPLS/ServQual
Pilar 3: Multi-Agent Manuskrip Scopus Q1 (via manuscript_orchestrator)
Pilar 4: Policy Server + Context Hygiene + Gherkin Spec
"""
from __future__ import annotations
import re
from datetime import datetime
from typing import Optional

from google.adk.agents import Agent
from .config import AGENT_MODEL
from .stats_tools import (
    parse_spss_output,
    parse_smartpls_report,
    validate_servqual_dimensions,
)

FILTER_START = 2021
FILTER_END   = datetime.now().year

def filter_references_by_year(reference_text: str) -> dict:
    """Memindai daftar referensi dan mendeteksi yang di luar 2021-sekarang.

    Args:
        reference_text: Teks daftar pustaka (satu atau banyak referensi, pisahkan per baris).
    Returns:
        dict berisi referensi valid, usang, tidak jelas, dan ringkasan.
    """
    lines = [l.strip() for l in reference_text.strip().splitlines() if l.strip()]
    valid, outdated, uncertain = [], [], []
    yr = re.compile(r'\b(19\d{2}|20\d{2})\b')
    for ref in lines:
        years = [int(y) for y in yr.findall(ref)]
        if not years:
            uncertain.append({"reference": ref, "reason": "Tahun tidak terdeteksi"})
        elif FILTER_START <= max(years) <= FILTER_END:
            valid.append({"reference": ref, "year": max(years)})
        else:
            outdated.append({
                "reference": ref, "year": max(years),
                "reason": f"Tahun {max(years)} di luar {FILTER_START}–{FILTER_END}",
                "action": "Cari pengganti terbitan 2021 atau lebih baru"
            })
    return {
        "summary": {"total": len(lines), "valid": len(valid),
                    "outdated": len(outdated), "uncertain": len(uncertain),
                    "filter_window": f"{FILTER_START}–{FILTER_END}"},
        "valid_references": valid,
        "outdated_references": outdated,
        "uncertain_references": uncertain,
        "recommendation": (
            "Semua referensi memenuhi syarat kronologis." if not outdated
            else f"Terdapat {len(outdated)} referensi yang harus diganti "
                 f"dengan sumber terbitan {FILTER_START}–{FILTER_END}."
        )
    }

def correct_citation_format(reference: str, target_style: str = "APA") -> dict:
    """Mengevaluasi dan mengoreksi format sitasi APA 7th atau IEEE.

    Args:
        reference: Satu entri referensi yang akan diperiksa.
        target_style: "APA" atau "IEEE".
    Returns:
        dict berisi diagnosis kesalahan dan saran perbaikan konkret.
    """
    issues = []
    style = target_style.upper()
    if style == "APA":
        if re.search(r'\b[A-Z][a-z]+\s[A-Z][a-z]+\b', reference):
            issues.append({"issue": "Nama penulis ditulis lengkap",
                           "correction": "Gunakan: Nama Belakang, Inisial. Contoh: Santoso, B."})
        if not re.search(r'\(\d{4}\)', reference):
            issues.append({"issue": "Tahun tidak dalam kurung",
                           "correction": "Tambahkan: (2023) setelah nama penulis"})
        if '"' in reference:
            issues.append({"issue": "Judul artikel dalam tanda kutip",
                           "correction": "APA 7th: judul artikel tanpa kutip; nama jurnal kursif"})
        if re.search(r'Vol\.|Volume|No\.|Nomor', reference):
            issues.append({"issue": "Format volume tidak sesuai APA 7th",
                           "correction": "Format: Nama Jurnal, 10(2), 15-28."})
    elif style == "IEEE":
        if not re.search(r'[A-Z]\.\s', reference):
            issues.append({"issue": "IEEE: inisial harus di depan nama",
                           "correction": "Gunakan: B. Santoso, bukan Santoso, Budi"})
        if not re.search(r'"[^"]+"', reference):
            issues.append({"issue": "Judul artikel harus dalam tanda kutip ganda",
                           "correction": 'Contoh: B. Santoso, "Judul," Jurnal, vol. 10, 2023.'})
    return {
        "original": reference, "style": style,
        "issues_found": len(issues), "issues": issues,
        "status": "Sesuai" if not issues else f"{len(issues)} ketidaksesuaian ditemukan"
    }

def check_roadmap_alignment(topic: str, keywords: Optional[str] = None) -> dict:
    """Memeriksa kesesuaian topik penelitian dengan Roadmap Prodi Transportasi.

    Args:
        topic: Judul atau topik penelitian yang akan diperiksa.
        keywords: Kata kunci tambahan, pisahkan dengan koma (opsional).
    Returns:
        dict berisi skor kesesuaian dan kluster roadmap yang relevan.
    """
    clusters = {
        "Transportasi Publik & Layanan": ["angkutan umum","bus","kereta","mrt","lrt","brt",
            "kualitas layanan","servqual","kepuasan penumpang","aksesibilitas","commuter"],
        "Keselamatan & Manajemen Lalu Lintas": ["keselamatan","safety","kecelakaan",
            "lalu lintas","kecepatan","persimpangan","roundabout","black spot"],
        "Infrastruktur & Perencanaan": ["jalan","jembatan","terminal","pelabuhan","bandara",
            "perencanaan transportasi","jaringan jalan","geometrik","kapasitas jalan"],
        "Mobilitas Berkelanjutan": ["berkelanjutan","sustainable","emisi","karbon",
            "kendaraan listrik","ev","sepeda","pejalan kaki","tod","green transport"],
        "Logistik & Rantai Pasok": ["logistik","supply chain","distribusi","freight",
            "last mile","cold chain","e-commerce"],
        "Teknologi & Inovasi Transportasi": ["autonomous","smart city","iot","big data",
            "machine learning","gis","its","sistem informasi transportasi"]
    }
    txt = (topic + " " + (keywords or "")).lower()
    matched = {c: [t for t in terms if t in txt]
               for c, terms in clusters.items() if any(t in txt for t in terms)}
    score = min(len(matched) * 30, 100)
    return {
        "topic": topic, "alignment_score": score,
        "alignment_level": ("Sangat Selaras" if score >= 60
                            else "Cukup Selaras" if score >= 30 else "Perlu Penyesuaian"),
        "matched_clusters": matched,
        "recommendation": (
            f"Topik selaras dengan kluster: {', '.join(matched.keys())}. Dapat dilanjutkan."
            if matched else
            "Topik belum selaras dengan Roadmap Prodi. Konsultasikan dengan Kaprodi."
        ),
        "available_clusters": list(clusters.keys()) if not matched else []
    }

root_agent = Agent(
    name="rmd_tra_agent",
    model=AGENT_MODEL,
    description="RMD-TRA: Asisten riset akademik resmi Prodi Transportasi.",
    instruction="""
Kamu adalah RMD-TRA (Research Management & Development – Transportation Research Assistant).

PILAR 1 — Analisis Kontekstual Berbasis RAG:
Gunakan filter_references_by_year untuk memfilter referensi (aturan 2021-sekarang).
Gunakan correct_citation_format untuk koreksi sitasi APA 7th atau IEEE.
Gunakan check_roadmap_alignment untuk cek topik vs Roadmap Prodi Transportasi.
Jika perlu referensi pengganti yang lebih mutakhir, sarankan pengguna untuk
mencari di Google Scholar, DOAJ, atau Scopus secara mandiri.

PILAR 2 — Validasi Komputasi Statistik:
Gunakan parse_spss_output untuk membaca dan menginterpretasi output SPSS.
Gunakan parse_smartpls_report untuk membaca laporan SmartPLS/SEM-PLS.
Gunakan validate_servqual_dimensions untuk memverifikasi kelengkapan ServQual.
PRINSIP ABSOLUT: Jangan pernah menebak atau merekayasa angka statistik.
Semua angka harus berasal dari teks yang diberikan pengguna, bukan dari imajinasimu.

PILAR 3 — Manuskrip Scopus (khusus dosen/peneliti):
Jika diminta membuat manuskrip Scopus Q1, susun struktur IMRAD yang lengkap.
Pastikan Introduction mengandung research gap, Method menyebut software dan versi,
Result menyajikan angka tanpa interpretasi, Discussion mengaitkan dengan teori.

PILAR 4 — Keamanan Data (Context Hygiene):
JANGAN pernah menyebut atau mengulang: Project ID GCP, API key, NIM mahasiswa,
nilai akademik, atau data internal yang belum dipublikasikan dalam outputmu.

ATURAN FORMAT OUTPUT — MUTLAK, tidak boleh dilanggar:
1. Setiap laporan evaluasi WAJIB dalam bentuk narasi mengalir.
2. DILARANG menggunakan daftar pendek (bullet points) dalam narasi.
3. Panjang kalimat harus bervariasi.
4. Awali dengan salam singkat yang hangat.
5. Akhiri dengan satu pertanyaan atau tawaran bantuan lanjutan yang spesifik.
""",
    tools=[
        filter_references_by_year,
        correct_citation_format,
        check_roadmap_alignment,
        parse_spss_output,
        parse_smartpls_report,
        validate_servqual_dimensions,
    ],
)
