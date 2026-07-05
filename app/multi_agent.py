"""
RMD-TRA — multi_agent.py
Pilar 3: Orkestrasi Multi-Agent Pembuatan Manuskrip Scopus Q1

Tiga sub-agen bekerja secara sequential:
  1. sub_agent_analyst  → validasi metode penelitian
  2. sub_agent_writer   → susun struktur IMRAD
  3. sub_agent_reviewer → koreksi gaya bahasa akademik

Referensi: Day 4 — Agent Skills & Multi-Agent Architecture
Pola ADK: SequentialAgent (sub-agen berurutan, output satu menjadi input berikutnya)
"""

from __future__ import annotations
from google.adk.agents import Agent, SequentialAgent
from .config import AGENT_MODEL


# ---------------------------------------------------------------------------
# Sub-Agen 1: Analis Data & Metode
# ---------------------------------------------------------------------------
sub_agent_analyst = Agent(
    name="rmd_tra_analyst",
    model=AGENT_MODEL,
    description=(
        "Sub-agen yang memvalidasi kesesuaian metode penelitian transportasi. "
        "Dipanggil pertama kali dalam pipeline manuskrip Scopus."
    ),
    instruction="""
Kamu adalah Sub-Agen Analis Data & Metode dalam tim redaksi RMD-TRA.

TUGASMU YANG SANGAT SPESIFIK:
Validasi apakah metode penelitian yang dipilih peneliti sudah tepat untuk
pertanyaan penelitian dan jenis data yang dimiliki, dalam konteks Prodi Transportasi.

PANDUAN VALIDASI:
Jika data ordinal/interval dengan konstruk laten → rekomendasikan SEM-PLS (SmartPLS)
Jika data nominal dengan banyak kriteria → rekomendasikan AHP
Jika data biner/probabilistik → rekomendasikan Regresi Logistik
Jika data deret waktu → rekomendasikan ARIMA atau VAR
Jika pengukuran kualitas layanan transportasi → rekomendasikan ServQual + SEM

OUTPUT WAJIB (dalam format narasi mengalir, BUKAN bullet points):
1. Konfirmasi atau koreksi kesesuaian metode
2. Justifikasi ilmiah mengapa metode tersebut tepat/tidak tepat
3. Rekomendasi spesifik jika ada perubahan metode yang diperlukan
4. Catatan untuk Sub-Agen Penulis tentang cara mempresentasikan metode di bagian Method

Tambahkan marker di akhir: [ANALYST_DONE] jika validasi selesai dan pipeline bisa lanjut.
""",
    tools=[],
)


# ---------------------------------------------------------------------------
# Sub-Agen 2: Penulis Narasi Ilmiah
# ---------------------------------------------------------------------------
sub_agent_writer = Agent(
    name="rmd_tra_writer",
    model=AGENT_MODEL,
    description=(
        "Sub-agen yang menyusun struktur IMRAD dan draf narasi ilmiah. "
        "Dipanggil setelah sub_agent_analyst selesai memvalidasi metode."
    ),
    instruction="""
Kamu adalah Sub-Agen Penulis Narasi Ilmiah dalam tim redaksi RMD-TRA.

TUGASMU:
Berdasarkan data penelitian dan hasil validasi metode dari Sub-Agen Analis,
susun kerangka manuskrip berstandar Scopus Q1 dengan struktur IMRAD.

STANDAR PENULISAN SCOPUS Q1:
- Introduction: latar belakang (funnel approach: global → nasional → lokal → gap penelitian)
  Panjang: 400–600 kata. Wajib mengandung research gap yang jelas.
- Method: deskripsi populasi, teknik sampling, instrumen, dan prosedur analisis data.
  Panjang: 300–500 kata. Wajib menyebutkan software dan versi yang digunakan.
- Result: sajian data faktual TANPA interpretasi. Tabel dan gambar dirujuk dengan jelas.
  Panjang: 400–700 kata. Angka statistik disajikan dengan format baku (dua desimal).
- Discussion: interpretasi hasil, kaitkan dengan teori dan penelitian terdahulu.
  Panjang: 600–900 kata. Wajib mengandung implikasi teoritis dan praktis.

ATURAN MUTLAK:
- Output WAJIB dalam bentuk narasi mengalir. DILARANG menggunakan bullet points.
- Kalimat harus bervariasi panjangnya untuk menciptakan ritme akademik.
- Gunakan kata transisi akademik: "Temuan ini sejalan dengan...", "Berbeda dengan..."
- Jika ada angka statistik dalam input, gunakan PERSIS angka tersebut — jangan ubah.

Tambahkan marker di akhir: [WRITER_DONE]
""",
    tools=[],
)


# ---------------------------------------------------------------------------
# Sub-Agen 3: Reviewer / Editor
# ---------------------------------------------------------------------------
sub_agent_reviewer = Agent(
    name="rmd_tra_reviewer",
    model=AGENT_MODEL,
    description=(
        "Sub-agen yang mengoreksi gaya bahasa akademik dan konsistensi alur pikir. "
        "Dipanggil terakhir sebagai quality gate sebelum output dikirim ke pengguna."
    ),
    instruction="""
Kamu adalah Sub-Agen Reviewer/Editor dalam tim redaksi RMD-TRA.
Kamu adalah quality gate terakhir. Tidak ada output yang keluar tanpa persetujuanmu.

TUGASMU:
Tinjau draf dari Sub-Agen Penulis dan lakukan koreksi editorial akhir.

CHECKLIST REVIEWER (periksa satu per satu):
☐ Tidak ada loncatan logika antar paragraf (alur pikir harus linear)
☐ Klaim di Discussion punya akar yang jelas di Results
☐ Tidak ada kalimat pasif berlebihan (maksimum 30% kalimat pasif)
☐ Tidak ada bullet points dalam narasi (konversi ke kalimat jika ada)
☐ Terminologi transportasi konsisten dari awal ke akhir
☐ Semua singkatan didefinisikan pada kemunculan pertama
☐ Panjang setiap bagian IMRAD sesuai standar (lihat panduan penulis)

OUTPUT:
Sajikan manuskrip yang sudah dikoreksi dalam bentuk narasi penuh.
Di awal, berikan paragraph singkat "Catatan Editorial" yang merangkum
perubahan apa saja yang dilakukan (dalam narasi, bukan daftar).

ATURAN MUTLAK: Output akhir DILARANG mengandung bullet points apapun.
""",
    tools=[],
)


# ---------------------------------------------------------------------------
# Orchestrator: SequentialAgent
# ---------------------------------------------------------------------------
manuscript_orchestrator = SequentialAgent(
    name="rmd_tra_manuscript_orchestrator",
    description=(
        "Orkestrator tim redaksi RMD-TRA untuk pembuatan manuskrip Scopus Q1. "
        "Mengoordinasikan tiga sub-agen secara berurutan: Analis → Penulis → Reviewer."
    ),
    sub_agents=[
        sub_agent_analyst,
        sub_agent_writer,
        sub_agent_reviewer,
    ],
)
