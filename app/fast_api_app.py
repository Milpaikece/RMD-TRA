"""
FastAPI application — RMD-TRA
Endpoint HTTP yang membungkus agen ADK untuk dijalankan di Cloud Run.
Stack: Google ADK 2.0 · Vertex AI · Gemini 2.0 Flash (sesuai materi kursus Day 1-5)
"""

from __future__ import annotations

# ── MUAT .env SEBELUM IMPORT GOOGLE ────────────────────────────────────────
import os
from pathlib import Path

def _load_env_file():
    """Muat .env ke os.environ sebelum google.adk diimport."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val

_load_env_file()

_PROJECT  = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-east4")
_VERTEXAI = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "false").lower()

print(f"[RMD-TRA] GOOGLE_CLOUD_PROJECT        = {_PROJECT or '(KOSONG!)'}")
print(f"[RMD-TRA] GOOGLE_CLOUD_LOCATION       = {_LOCATION}")
print(f"[RMD-TRA] GOOGLE_GENAI_USE_VERTEXAI   = {_VERTEXAI}")

if not _PROJECT:
    raise RuntimeError(
        "\n\nGOOGLE_CLOUD_PROJECT belum diisi di file .env\n"
        "Pastikan .env berisi:\n"
        "  GOOGLE_GENAI_USE_VERTEXAI=true\n"
        "  GOOGLE_CLOUD_PROJECT=gen-lang-client-0269895826\n"
        "  GOOGLE_CLOUD_LOCATION=us-east4\n"
    )

if _VERTEXAI != "true":
    raise RuntimeError(
        "\n\nGOOGLE_GENAI_USE_VERTEXAI harus bernilai 'true'\n"
        "Ubah di file .env:\n"
        "  GOOGLE_GENAI_USE_VERTEXAI=true\n"
    )

print(f"[RMD-TRA] Konfigurasi Vertex AI OK. Memuat agen...")
# ── SELESAI KONFIGURASI ─────────────────────────────────────────────────────

import io
import re
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from .agent import root_agent

# ---------------------------------------------------------------------------
# Session service — InMemory untuk Cloud Run (stateless per request)
# ---------------------------------------------------------------------------
session_service = InMemorySessionService()
APP_NAME = "rmd-tra"

# ---------------------------------------------------------------------------
# Runner ADK
# ---------------------------------------------------------------------------
runner: Runner | None = None
_p5_runner_early: Runner | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global runner, _p5_runner_early
    # Runner Pilar 1-4
    runner = Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )
    print("[OK] RMD-TRA Agent Runner (Pilar 1-4) siap.")
    # Runner Pilar 5 — diinisialisasi saat startup agar tidak None saat dipanggil
    try:
        from .pillar5 import thesis_analyzer_orchestrator as _tao
        _p5_runner_early = Runner(
            agent=_tao,
            app_name="rmd-tra-p5",
            session_service=session_service,
        )
        print("[OK] RMD-TRA Agent Runner (Pilar 5) siap.")
    except Exception as e:
        print(f"[WARN] Pilar 5 runner gagal diinisialisasi: {e}")
    yield
    print("[OK] RMD-TRA Agent Runner dihentikan.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="RMD-TRA API",
    description="Research Management & Development — Transportation Research Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sajikan frontend statis
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str | None = None


class AnalyzeRequest(BaseModel):
    thesis_title: str
    student_name: str | None = "Mahasiswa"
    thesis_text: str
    session_id: str | None = None
    user_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    user_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    """Redirect ke UI."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


@app.get("/health")
async def health():
    """Health check untuk Cloud Run."""
    return {"status": "ok", "agent": "rmd-tra", "version": "1.0.0"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Endpoint utama: kirim pesan ke RMD-TRA dan terima respons narasi.
    """
    if runner is None:
        raise HTTPException(status_code=503, detail="Agent belum siap.")

    user_id = request.user_id or f"user-{uuid.uuid4().hex[:8]}"
    session_id = request.session_id or f"session-{uuid.uuid4().hex[:8]}"

    try:
        # Pastikan sesi ada
        existing = await session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if existing is None:
            await session_service.create_session(
                app_name=APP_NAME, user_id=user_id, session_id=session_id
            )

        # Jalankan agen
        user_message = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=request.message)]
        )

        final_text = ""
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        final_text += part.text

        if not final_text:
            raise HTTPException(status_code=500, detail="Agen tidak menghasilkan respons.")

        return ChatResponse(
            response=final_text,
            session_id=session_id,
            user_id=user_id,
        )

    except HTTPException:
        raise  # Teruskan HTTPException yang sudah jelas

    except Exception as e:
        err_msg = str(e)
        # Deteksi jenis error spesifik untuk pesan yang lebih berguna
        if "credentials" in err_msg.lower() or "authentication" in err_msg.lower() \
                or "api key" in err_msg.lower() or "UNAUTHENTICATED" in err_msg:
            detail = (
                "❌ Error Autentikasi Google Cloud.\n\n"
                "Jalankan perintah ini di terminal baru:\n"
                "  gcloud auth application-default login\n\n"
                "Pastikan juga file .env berisi:\n"
                "  GOOGLE_GENAI_USE_VERTEXAI=true\n"
                "  GOOGLE_CLOUD_PROJECT=gen-lang-client-0269895826\n"
                "  GOOGLE_CLOUD_LOCATION=us-east1"
            )
            raise HTTPException(status_code=401, detail=detail)

        elif "quota" in err_msg.lower() or "RESOURCE_EXHAUSTED" in err_msg:
            detail = (
                "❌ Kuota API Google Cloud habis.\n\n"
                "Cek kuota di: https://console.cloud.google.com/iam-admin/quotas\n"
                "Atau tunggu beberapa menit dan coba lagi."
            )
            raise HTTPException(status_code=429, detail=detail)

        elif "billing" in err_msg.lower() or "BILLING" in err_msg:
            detail = (
                "❌ Billing Google Cloud belum aktif atau akun diblokir.\n\n"
                "Aktifkan billing di: https://console.cloud.google.com/billing"
            )
            raise HTTPException(status_code=402, detail=detail)

        elif "model" in err_msg.lower() and ("not found" in err_msg.lower() or "404" in err_msg):
            detail = (
                "❌ Model Gemini tidak ditemukan di project/region ini.\n\n"
                "Lakukan langkah berikut di terminal:\n\n"
                "1. Aktifkan Vertex AI API:\n"
                "   gcloud services enable aiplatform.googleapis.com\n\n"
                "2. Aktifkan akses model Gemini:\n"
                "   Buka: https://console.cloud.google.com/vertex-ai/model-garden\n"
                "   Cari 'Gemini 2.0 Flash' → klik Enable\n\n"
                "3. Pastikan billing aktif:\n"
                "   https://console.cloud.google.com/billing\n\n"
                "4. Ganti region di .env ke: GOOGLE_CLOUD_LOCATION=us-east4"
            )
            raise HTTPException(status_code=404, detail=detail)

        else:
            # Tampilkan error asli agar mudah di-debug
            print(f"[RMD-TRA ERROR] /chat endpoint: {err_msg}")
            raise HTTPException(
                status_code=500,
                detail=f"Error internal agen: {err_msg[:500]}"
            )


@app.get("/info")
async def info():
    """Informasi tentang kemampuan RMD-TRA."""
    return {
        "name": "RMD-TRA",
        "full_name": "Research Management & Development — Transportation Research Assistant",
        "version": "1.0.0",
        "pillars_active": ["Pilar 1: RAG + Chronological Filter + Citation Corrector"],
        "pillars_coming": [
            "Pilar 2: Validasi Komputasi Statistik (SPSS/SmartPLS)",
            "Pilar 3: Multi-Agent Manuskrip Scopus Q1",
            "Pilar 4: Tata Kelola Spec-Driven (MCP + Policy Server)",
        ],
        "filter_window": "2021–2026",
        "citation_styles": ["APA 7th Edition", "IEEE 2024"],
        "domain": "Transportasi",
    }


# ---------------------------------------------------------------------------
# Helpers ekstraksi dokumen
# ---------------------------------------------------------------------------
def _extract_references(text: str) -> list[str]:
    """
    Mencari bagian Daftar Pustaka / References dalam teks dokumen
    dan mengekstrak setiap entri referensi sebagai list.
    """
    markers = [
        r'daftar\s+pustaka', r'daftar\s+referensi',
        r'references', r'bibliography', r'daftar\s+acuan',
    ]
    pattern = '|'.join(markers)
    match = re.search(pattern, text, re.IGNORECASE)

    ref_section = text[match.start():] if match else text[-8000:]

    lines = ref_section.splitlines()
    refs = []
    current = ""
    for line in lines:
        line = line.strip()
        if not line:
            if current and re.search(r'\b(19|20)\d{2}\b', current):
                refs.append(current.strip())
            current = ""
        else:
            current += " " + line

    if current and re.search(r'\b(19|20)\d{2}\b', current):
        refs.append(current.strip())

    refs = [r for r in refs if len(r) > 20][:80]
    return refs


def _detect_title(text: str) -> str:
    """Ambil judul dari baris pertama yang substantif."""
    for line in text.splitlines()[:30]:
        line = line.strip()
        if 10 < len(line) < 200 and not line.lower().startswith(('abstract', 'abstrak', 'kata kunci')):
            return line
    return "Judul tidak terdeteksi"


def _extract_chapters(text: str) -> dict:
    """
    Deteksi dan ekstrak setiap bab skripsi secara terpisah.
    Mengembalikan dict: {'bab1': '...', 'bab2': '...', 'bab3': '...', 'bab4': '...', 'bab5': '...', 'dapus': '...'}

    Banyak skripsi punya bagian "Sistematika Penulisan" di akhir Bab I yang menyebut
    ulang "BAB I".."BAB V" dalam ringkasan singkat, saling berdekatan. Kalau dianggap
    sebagai bab sungguhan, sub-agen akan menerima potongan teks kosong/salah untuk
    Bab II-V. Untuk menghindarinya: kumpulkan SEMUA kemunculan penanda bab, lalu buang
    kemunculan yang jaraknya ke penanda berikutnya terlalu dekat (ciri khas daftar
    isi/sistematika, bukan bab sungguhan yang isinya panjang).
    """
    MIN_GAP = 800  # karakter minimum antar penanda agar dianggap bab sungguhan (bukan daftar isi)

    markers = [
        ('bab1', r'\bBAB\s+(?:I|1|SATU)\b'),
        ('bab2', r'\bBAB\s+(?:II|2|DUA)\b'),
        ('bab3', r'\bBAB\s+(?:III|3|TIGA)\b'),
        ('bab4', r'\bBAB\s+(?:IV|4|EMPAT)\b'),
        ('bab5', r'\bBAB\s+(?:V|5|LIMA)\b'),
        ('dapus', r'(?:DAFTAR PUSTAKA|DAFTAR REFERENSI|REFERENCES|BIBLIOGRAPHY|DAFTAR ACUAN)'),
    ]

    hits_by_key: dict[str, list[int]] = {key: [] for key, _ in markers}
    for key, pattern in markers:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            hits_by_key[key].append(m.start())

    all_hits = sorted(
        (pos, key) for key, positions in hits_by_key.items() for pos in positions
    )

    def _gap_to_next(pos: int) -> int:
        idx = next(i for i, (p, _) in enumerate(all_hits) if p == pos)
        return (all_hits[idx + 1][0] - pos) if idx + 1 < len(all_hits) else len(text) - pos

    # Filter jarak HANYA relevan kalau suatu bab disebut lebih dari sekali (berarti
    # ada kandidat "asli" vs "cuma disebut di ringkasan/sistematika" yang perlu
    # dipilih). Kalau cuma sekali muncul, tidak ada yang perlu dibandingkan — bab
    # pendek yang sah (mis. Daftar Pustaka singkat) tidak boleh ikut terbuang.
    first_valid: dict[str, int] = {}
    decoy_positions: list[int] = []
    for key, positions in hits_by_key.items():
        if not positions:
            continue
        if len(positions) == 1:
            first_valid[key] = positions[0]
            continue
        candidates = [p for p in positions if _gap_to_next(p) >= MIN_GAP]
        chosen = candidates[0] if candidates else positions[-1]
        first_valid[key] = chosen
        # Cuma posisi yang GAGAL cek jarak yang dianggap decoy (ciri sistematika
        # penulisan). Posisi lain yang lolos cek jarak tapi bukan kandidat pertama
        # (mis. referensi silang "...dijelaskan di Bab IV..." di tengah kalimat)
        # tetap konten sungguhan — tidak boleh ikut dibuang.
        decoy_positions.extend(p for p in positions if p not in candidates and p != chosen)

    # Kumpulkan kemunculan yang TERBUANG (ciri sistematika penulisan/ringkasan bab)
    # jadi rentang karakter yang harus dipotong keluar dari isi bab — bukan cuma
    # dihindari saat menentukan titik mulai, tapi benar-benar tidak ikut dikirim.
    strip_ranges: list[tuple[int, int]] = []
    if decoy_positions:
        decoy_positions.sort()
        all_positions_sorted = sorted(p for p, _ in all_hits)
        cluster_start = decoy_positions[0]
        prev = decoy_positions[0]
        for p in decoy_positions[1:] + [None]:
            if p is None or p - prev > 3000:
                after = [q for q in all_positions_sorted if q > prev]
                cluster_end = min(after) if after else len(text)
                strip_ranges.append((cluster_start, cluster_end))
                if p is not None:
                    cluster_start = p
            if p is not None:
                prev = p

    def _slice_without_decoys(start_pos: int, end_pos: int) -> str:
        pieces = []
        cursor = start_pos
        for r_start, r_end in strip_ranges:
            if r_start >= end_pos or r_end <= start_pos:
                continue
            clip_start = max(r_start, start_pos)
            clip_end = min(r_end, end_pos)
            pieces.append(text[cursor:clip_start])
            cursor = clip_end
        pieces.append(text[cursor:end_pos])
        return "".join(pieces)

    keys = ['bab1', 'bab2', 'bab3', 'bab4', 'bab5', 'dapus']
    chapters = {}
    for key in keys:
        if key not in first_valid:
            chapters[key] = ""
            continue
        start_pos = first_valid[key]
        later_starts = [p for k, p in first_valid.items() if p > start_pos]
        end_pos = min(later_starts) if later_starts else len(text)
        # Isi bab tidak dipotong batas karakter apa pun — cuma bagian sistematika
        # penulisan/ringkasan bab (kalau terdeteksi) yang dibuang dari hasil akhir.
        chapters[key] = _slice_without_decoys(start_pos, end_pos)

    return chapters


# label ramah-manusia untuk tiap kunci bab (dipakai di pesan diagnostik)
_CHAPTER_LABELS = {
    'bab1': 'Bab I (Pendahuluan)',
    'bab2': 'Bab II (Tinjauan Pustaka)',
    'bab3': 'Bab III (Metodologi)',
    'bab4': 'Bab IV (Hasil & Pembahasan)',
    'bab5': 'Bab V (Kesimpulan & Saran)',
    'dapus': 'Daftar Pustaka',
}


def _diagnose_chapter_extraction(chapters: dict, total_len: int) -> list[str]:
    """
    Periksa hasil pembagian bab dan kembalikan daftar peringatan bila pembagian
    terlihat mencurigakan. Tujuannya mengubah kegagalan DIAM-DIAM (ekstraksi
    salah tapi laporan tetap keluar meyakinkan) menjadi kegagalan BERSUARA:
    kalau pembagian bab janggal, auditor manusia harus tahu sebelum mempercayai
    isi laporan.

    Anomali yang dideteksi:
      - Bab inti (I–V) kosong padahal seharusnya ada.
      - Satu bab menelan porsi dokumen yang tidak wajar (indikasi bab lain gagal
        terpisah dan ikut tertelan di dalamnya).
      - Bab inti sangat pendek dibanding dokumen (indikasi isi bab gagal terambil).
      - Urutan posisi bab tidak menaik (I→II→…→V) — indikasi penanda salah pilih.

    Ambang sengaja longgar: guardrail ini hanya berteriak saat ada yang benar-benar
    janggal, supaya tidak memunculkan peringatan palsu pada skripsi yang normal.
    """
    warnings: list[str] = []
    if total_len <= 0:
        return ["Dokumen kosong atau gagal diekstrak — tidak ada teks untuk diaudit."]

    core = ['bab1', 'bab2', 'bab3', 'bab4', 'bab5']
    lengths = {k: len(chapters.get(k, '')) for k in core}
    detected = [k for k in core if lengths[k] > 0]

    # (a) Terlalu sedikit bab inti terdeteksi -> kemungkinan pola penomoran beda
    #     (mis. "BAB DUA" bukan "BAB II/2") sehingga regex tidak menangkap.
    if len(detected) < 3:
        hilang = [_CHAPTER_LABELS[k] for k in core if lengths[k] == 0]
        warnings.append(
            f"Hanya {len(detected)} dari 5 bab inti yang terdeteksi. Bab yang tidak "
            f"terbaca: {', '.join(hilang)}. Kemungkinan penomoran bab memakai format "
            "tak dikenal (mis. 'BAB SATU' ejaan penuh) — audit bab-bab itu tidak andal."
        )

    # (b) Bab inti kosong satuan (padahal mayoritas bab lain ada)
    if len(detected) >= 3:
        for k in core:
            if lengths[k] == 0:
                warnings.append(
                    f"{_CHAPTER_LABELS[k]} terdeteksi KOSONG padahal bab lain ada. "
                    "Penanda babnya mungkin tidak tertangkap atau tertimpa bab sebelumnya."
                )

    # (c) Satu bab menelan porsi tak wajar -> bab lain kemungkinan gagal terpisah
    for k in core:
        frac = lengths[k] / total_len
        if frac > 0.72:
            warnings.append(
                f"{_CHAPTER_LABELS[k]} menempati {frac*100:.0f}% seluruh dokumen. "
                "Sangat mungkin satu/lebih bab berikutnya gagal terpisah dan ikut "
                "tertelan di sini — periksa apakah batas antar-bab benar."
            )

    # (d) Bab inti yang ada tapi teramat pendek (< 1% & < 400 char) -> isi hilang
    for k in detected:
        if lengths[k] < 400 and (lengths[k] / total_len) < 0.01:
            warnings.append(
                f"{_CHAPTER_LABELS[k]} hanya {lengths[k]} karakter — nyaris kosong. "
                "Isi bab kemungkinan gagal terambil (penanda bab berikutnya terlalu dekat)."
            )

    return warnings


def _build_finance_verification_block(text: str) -> str:
    """
    Jalankan verifikasi angka finansial deterministik (Python, bukan LLM)
    SEBELUM teks dikirim ke agen, lalu format hasilnya jadi blok teks yang
    disuntikkan ke prompt. Ini memastikan agen membaca hasil yang sudah
    pasti benar secara matematis, bukan menghitung ulang sendiri.
    """
    from .pillar5.finance_tools import extract_labeled_figures, recompute_bca_from_tables

    table_blocks = re.findall(r'\[TABEL\](.*?)\[/TABEL\]', text, re.DOTALL)

    figures = extract_labeled_figures(text)
    bca = recompute_bca_from_tables(text, table_blocks)

    # GERBANG RELEVANSI: kalau skripsi ini TIDAK punya materi finansial sama sekali
    # (mis. skripsi survei/kualitas layanan), jangan tampilkan blok ini — bahkan
    # untuk mengatakan "tidak ada tabel arus kas". Materi seperti BCA/NPV/IRR milik
    # skripsi finansial; membahasnya di skripsi non-finansial adalah kebocoran
    # konteks. Blok hanya muncul kalau ada sinyal finansial nyata di dokumen.
    has_finance_signal = bool(re.search(
        r'\b(NPV|IRR|BCR|BCA|benefit[\s-]*cost|analisis\s+manfaat\s+biaya|'
        r'arus\s+kas|cash\s*flow|payback|periode\s+pengembalian|'
        r'kelayakan\s+(?:finansial|investasi|ekonomi)|discount\s+rate|'
        r'nilai\s+sekarang\s+bersih)\b',
        text, re.IGNORECASE))
    if not has_finance_signal and not bca.get("recomputed"):
        return ""

    def _fmt(v: float) -> str:
        # angka besar (nilai rupiah) -> format ribuan tanpa desimal;
        # angka kecil (persen/rasio/tahun) -> pertahankan desimal.
        if abs(v) >= 1000:
            return f"{v:,.0f}".replace(",", ".")
        return f"{v:g}"

    lines = ["=" * 60, "VERIFIKASI ANGKA OTOMATIS (dihitung sistem, BUKAN oleh kamu)", "=" * 60]
    lines.append(f"Status konsistensi angka: {figures['status']}")
    for inc in figures["inconsistencies"]:
        lines.append(f"- GALAT KRITIS: {inc['warning']}")
        for occ in inc["occurrences"]:
            lines.append(f"    * nilai {_fmt(occ['value'])} — teks asli: \"{occ['raw_text']}\"")

    lines.append("")
    lines.append(f"Status hitung ulang BCA dari tabel: {bca['status']}")
    reliable = [r for r in bca["recomputed"] if r.get("reliable")]
    unreliable = [r for r in bca["recomputed"] if not r.get("reliable")]
    for r in reliable:
        irr_txt = f"{r['irr_recomputed']}%" if r['irr_recomputed'] is not None else "tidak terdefinisi"
        bcr_txt = f"{r['bcr_recomputed']}" if r['bcr_recomputed'] is not None else "tidak terdefinisi"
        lines.append(
            f"- [ANDAL] Tabel {r['subject']} (discount rate {r['discount_rate_used']*100:.0f}%, "
            f"{r['periods_found']} periode): NPV = {_fmt(r['npv_recomputed'])}, "
            f"IRR = {irr_txt}, BCR = {bcr_txt}"
        )
    if unreliable:
        subj_list = ", ".join(f"{r['subject']} ({r['periods_found']} periode)" for r in unreliable)
        lines.append(
            f"- [TIDAK DIHITUNG] {len(unreliable)} tabel hanya punya satu kolom arus kas "
            f"tanpa pemisahan manfaat & biaya ({subj_list}). NPV/IRR sengaja TIDAK dihitung "
            "ulang untuk menghindari angka menyesatkan — ini justru sinyal metodologi NPV/IRR "
            "pada tabel-tabel itu perlu diperiksa Sub-Agen Statistical Auditor."
        )

    lines.append("")
    lines.append(
        "PENTING: Angka-angka di atas dihitung/diekstrak otomatis oleh Python, bukan tebakanmu — "
        "kutip sebagai bukti kalau memang valid. NAMUN deteksi inkonsistensi ini berbasis kedekatan "
        "teks (bukan pemahaman makna penuh), jadi SEBELUM melaporkan sebagai galat Kritis, cek ulang "
        "ke teks aslinya di ISI SKRIPSI di bawah: pastikan kedua nilai yang ditandai memang tentang "
        "subjek yang PERSIS SAMA (mis. dua alternatif/moda yang dibandingkan) dan indikator yang "
        "PERSIS SAMA — bukan salah atribusi karena dua baris/kolom tabel yang berdekatan letaknya. "
        "Kalau setelah dicek ternyata bukan inkonsistensi sungguhan (mis. satu nilai untuk alternatif A "
        "dan satu untuk alternatif B), JANGAN laporkan sebagai galat."
    )
    return "\n".join(lines)


def _build_survey_verification_block(text: str) -> str:
    """
    Verifikasi deterministik untuk skripsi berbasis SURVEI/kualitas layanan
    (Slovin, konsistensi ukuran sampel, jumlah persen, klaim rasio). Menutup
    celah gagal-diam: untuk skripsi survei, verifikator finansial mati total,
    jadi lapisan pengaman ini yang menyediakan angka yang sudah pasti benar.

    Kembalikan string kosong kalau skripsi ini jelas BUKAN survei (tidak ada
    sinyal), supaya laporan finansial tidak diganggu blok yang tak relevan.
    """
    from .pillar5.survey_tools import build_survey_verification

    v = build_survey_verification(text)
    tipe = v["type"]
    # GERBANG RELEVANSI (simetris dgn blok finansial): hanya tampil kalau ada
    # SINYAL SURVEI NYATA — bukan sekadar kata "validitas/reliabilitas" yang juga
    # dipakai skripsi non-survei. Mencegah materi survei (Slovin/CSI/IPA/SPM)
    # bocor ke laporan skripsi finansial. Butuh penanda metodologi survei yang
    # spesifik, ATAU rumus Slovin memang dipakai.
    # Penanda METODOLOGI survei yang spesifik (bukan "SPM"/"service quality" yang
    # bisa muncul sebagai SITASI di skripsi finansial). Butuh minimal DUA kemunculan
    # total agar sebutan sekilas (mis. satu kutipan) tidak memicu seluruh blok.
    survey_hits = len(re.findall(
        r'\b(kuesioner|kuisioner|angket|skala\s+likert|slovin|responden|'
        r'customer\s+satisfaction\s+index|\bCSI\b|importance\s+performance|'
        r'\bIPA\b|servqual|tingkat\s+kepuasan\s+(?:penumpang|pengguna|pelanggan))\b',
        text, re.IGNORECASE))
    if survey_hits < 2 and not v["slovin"].get("applicable"):
        return ""

    lines = [
        "=" * 60,
        "VERIFIKASI SURVEI OTOMATIS (dihitung sistem, BUKAN oleh kamu)",
        "=" * 60,
        f"Tipe skripsi terdeteksi: {tipe['label']} "
        f"(skor finansial={tipe['scores'].get('finansial',0)}, survei={tipe['scores'].get('survei',0)}).",
        "",
    ]

    sl = v["slovin"]
    if sl.get("applicable"):
        lines.append(f"[SLOVIN] {sl['status']}")
        if sl.get("population") is not None:
            lines.append(f"- Populasi (N) terbaca: {sl['population']:,}")
        if sl.get("margins_mentioned"):
            lines.append(
                "- Margin error disebut: "
                + ", ".join(f"{e*100:g}%" for e in sl["margins_mentioned"])
            )
        if sl.get("recomputed"):
            lines.append(
                "- Hitung ulang Slovin: "
                + "; ".join(f"e={e*100:g}% → n={n}" for e, n in sl["recomputed"])
            )
        if sl.get("sample_stated") is not None:
            lines.append(f"- Sampel yang diklaim skripsi: {sl['sample_stated']}")
        for iss in sl.get("issues", []):
            lines.append(f"  ⚠ {iss}")
        lines.append("")

    ss = v["sample_size"]
    lines.append(f"[UKURAN SAMPEL] {ss['status']}")
    lines.append("")

    pc = v["percentages"]
    lines.append(f"[KOLOM PERSENTASE] {pc['status']}")
    for p in pc.get("problems", []):
        lines.append(f"  ⚠ {p['table']}: {p['note']}")
    lines.append("")

    ra = v["ratios"]
    lines.append(f"[KLAIM RASIO] {ra['status']}")
    for p in ra.get("problems", []):
        lines.append(
            f"  ⚠ {p['x']:g} dari {p['y']:g} = {p['computed_pct']}% "
            f"(skripsi menulis {p['claimed_pct']:g}%) — “{p['context']}”"
        )
    lines.append("")

    lines.append(
        "PENTING: Angka di atas dihitung ulang oleh Python (mis. Slovin n=N/(1+N·e²)), "
        "bukan tebakanmu. Kalau ada ⚠, itu bukti kuat — tapi tetap cek ke teks asli untuk "
        "memastikan konteksnya, lalu laporkan sebagai galat dengan solusi revisi konkret "
        "(mis. seragamkan margin error, atau perbaiki ukuran sampel)."
    )
    return "\n".join(lines)


def _build_structured_thesis_prompt(text: str, thesis_title: str, student_name: str) -> str:
    """
    Buat prompt terstruktur per bab sehingga setiap sub-agen
    mendapatkan konteks yang relevan, bukan hanya bagian awal.
    """
    chapters = _extract_chapters(text)
    finance_verification = _build_finance_verification_block(text)
    survey_verification = _build_survey_verification_block(text)

    # Hitung berapa bab yang berhasil dideteksi
    detected = [k for k, v in chapters.items() if v]

    if len(detected) >= 3:
        # Deteksi bab berhasil — kirim per bab
        sections = []
        labels = {
            'bab1': 'BAB 1 — PENDAHULUAN (Rumusan Masalah, Tujuan, Hipotesis)',
            'bab2': 'BAB 2 — TINJAUAN PUSTAKA (Teori, Kerangka Konseptual)',
            'bab3': 'BAB 3 — METODOLOGI (Metode, Populasi, Sampling, Instrumen)',
            'bab4': 'BAB 4 — HASIL DAN PEMBAHASAN',
            'bab5': 'BAB 5 — KESIMPULAN DAN SARAN',
            'dapus': 'DAFTAR PUSTAKA',
        }
        for key, label in labels.items():
            content = chapters.get(key, '')
            if content:
                sections.append(f"\n{'='*60}\n{label}\n{'='*60}\n{content}")
        structured_text = '\n'.join(sections)
    else:
        # Deteksi bab gagal — kirim seluruh teks apa adanya, tidak dipotong
        structured_text = text

    # Blok verifikasi hanya disisipkan kalau relevan (string tak kosong) — supaya
    # skripsi survei tidak kebocoran materi finansial, dan sebaliknya.
    finance_block = f"{finance_verification}\n\n" if finance_verification else ""
    survey_block = f"{survey_verification}\n\n" if survey_verification else ""

    return (
        f"Analisis skripsi berikut secara menyeluruh menggunakan semua kemampuanmu:\n\n"
        f"JUDUL: {thesis_title}\n"
        f"PENULIS: {student_name}\n"
        f"BAB TERDETEKSI: {', '.join(detected) if detected else 'tidak terdeteksi (teks dikirim penuh)'}\n\n"
        f"{finance_block}"
        f"{survey_block}"
        f"ISI SKRIPSI:\n{structured_text}\n\n"
        f"Jalankan semua 7 analisis dan hasilkan laporan lengkap dengan "
        f"solusi revisi siap tempel untuk setiap temuan."
    )


async def _extract_from_pdf(content: bytes) -> dict:
    """
    Ekstrak teks dari PDF menggunakan pdfplumber (ambil teks + tabel).
    pypdf hanya baca teks polos dan sering melewatkan/mengacak isi tabel;
    pdfplumber mengekstrak tabel secara terstruktur per baris/kolom.
    """
    try:
        import pdfplumber

        text_parts = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
                for table in page.extract_tables():
                    rows = [
                        # newline internal sel dikolapskan jadi spasi supaya tiap
                        # baris tabel tetap satu baris (penting untuk parsing angka)
                        " | ".join((cell or "").strip().replace("\n", " ") for cell in row)
                        for row in table
                    ]
                    text_parts.append("[TABEL]\n" + "\n".join(rows) + "\n[/TABEL]")

        text = "\n".join(text_parts)
        return {"text": text, "pages": pages}
    except ImportError:
        raise HTTPException(
            status_code=422,
            detail="Library pdfplumber belum terinstall. Jalankan: uv add pdfplumber"
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Gagal membaca PDF: {str(e)}")


async def _extract_from_docx(content: bytes) -> dict:
    """Ekstrak teks dari DOCX menggunakan python-docx."""
    try:
        import docx
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        doc = docx.Document(io.BytesIO(content))

        def _table_to_text(table: "Table") -> str:
            # newline internal sel dikolapskan jadi spasi supaya tiap baris tabel
            # tetap satu baris utuh (kalau tidak, sel keterangan multi-paragraf
            # memecah satu baris logis jadi banyak baris & merusak parsing angka)
            rows = [
                " | ".join(cell.text.strip().replace("\n", " ") for cell in row.cells)
                for row in table.rows
            ]
            return "[TABEL]\n" + "\n".join(rows) + "\n[/TABEL]"

        # Iterasi body dokumen sesuai urutan asli (paragraf & tabel berselang-seling),
        # supaya tabel (mis. tabel perhitungan NPV/IRR) ikut terbaca dan masuk ke bab
        # yang benar — doc.paragraphs saja melewati seluruh isi tabel.
        parts = []
        for child in doc.element.body.iterchildren():
            if child.tag == qn("w:p"):
                parts.append(Paragraph(child, doc).text)
            elif child.tag == qn("w:tbl"):
                parts.append(_table_to_text(Table(child, doc)))

        text = "\n".join(parts)
        pages = max(1, len(text) // 2500)  # estimasi halaman
        return {"text": text, "pages": pages}
    except ImportError:
        raise HTTPException(
            status_code=422,
            detail="Library python-docx belum terinstall. Jalankan: uv add python-docx"
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Gagal membaca DOCX: {str(e)}")


# ---------------------------------------------------------------------------
# Endpoint upload dokumen
# ---------------------------------------------------------------------------
@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Menerima file PDF atau Word, mengekstrak teksnya, mendeteksi judul
    dan daftar pustaka, lalu mengembalikan data terstruktur yang siap
    dikirim ke endpoint /chat.
    """
    filename = file.filename or "dokumen"
    content = await file.read()

    if len(content) > 20 * 1024 * 1024:  # 20 MB limit
        raise HTTPException(status_code=413, detail="File terlalu besar. Maksimum 20 MB.")

    # Ekstrak berdasarkan tipe file
    if filename.lower().endswith(".pdf"):
        extracted = await _extract_from_pdf(content)
    elif filename.lower().endswith((".docx", ".doc")):
        extracted = await _extract_from_docx(content)
    else:
        raise HTTPException(
            status_code=415,
            detail="Format tidak didukung. Gunakan PDF, DOC, atau DOCX."
        )

    text = extracted["text"]
    pages = extracted["pages"]
    word_count = len(text.split())
    title = _detect_title(text)
    references = _extract_references(text)

    chapters = _extract_chapters(text)
    chapters_detected = [k for k, v in chapters.items() if v]

    return {
        "filename": filename,
        "pages": pages,
        "word_count": word_count,
        "title": title,
        "references": references,
        "ref_count": len(references),
        "extracted_text": text,  # Seluruh teks dikirim apa adanya, tidak dipotong
        "chapters_detected": chapters_detected,
        "chapter_count": len(chapters_detected),
        "status": "ok",
    }



# ---------------------------------------------------------------------------
# Endpoint Pilar 5 — Analisis Skripsi Lengkap
# ---------------------------------------------------------------------------
from .pillar5 import thesis_analyzer_orchestrator, generate_audit_report

_p5_runner: Runner | None = None


@app.post("/analyze")
async def analyze_thesis(request: AnalyzeRequest):
    """
    Endpoint Pilar 5: analisis skripsi lengkap dengan 7 sub-agen paralel.
    """
    global _p5_runner, _p5_runner_early

    # Gunakan runner yang sudah diinisialisasi saat startup
    active_runner = _p5_runner_early or _p5_runner

    # Fallback: inisialisasi on-demand jika belum ada
    if active_runner is None:
        try:
            active_runner = Runner(
                agent=thesis_analyzer_orchestrator,
                app_name="rmd-tra-p5",
                session_service=session_service,
            )
            _p5_runner = active_runner
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Pilar 5 belum siap: {str(e)[:300]}"
            )

    user_id   = request.user_id   or f"user-{uuid.uuid4().hex[:8]}"
    session_id = request.session_id or f"p5-{uuid.uuid4().hex[:8]}"

    await session_service.create_session(
        app_name="rmd-tra-p5", user_id=user_id, session_id=session_id
    )

    # Prompt terstruktur per bab — jauh lebih efektif daripada terpotong di awal
    prompt = _build_structured_thesis_prompt(
        text=request.thesis_text,
        thesis_title=request.thesis_title,
        student_name=request.student_name or "Mahasiswa",
    )

    user_message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=prompt)]
    )

    try:
        final_text = ""
        async for event in active_runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        final_text += part.text

        if not final_text:
            raise HTTPException(status_code=500, detail="Analisis tidak menghasilkan output.")

        # Generate file Word — sertakan hasil verifikasi angka otomatis (Python)
        # sebagai bagian tersendiri, bukan cuma tersembunyi di dalam prompt.
        finance_verification = _build_finance_verification_block(request.thesis_text)
        survey_verification = _build_survey_verification_block(request.thesis_text)
        # Guardrail: deteksi pembagian bab yang mencurigakan supaya kegagalan
        # ekstraksi tampil BERSUARA di laporan, bukan diam-diam.
        _chapters = _extract_chapters(request.thesis_text)
        extraction_warnings = _diagnose_chapter_extraction(
            _chapters, len(request.thesis_text)
        )
        docx_bytes = generate_audit_report(
            audit_text=final_text,
            thesis_title=request.thesis_title,
            student_name=request.student_name or "Mahasiswa",
            finance_verification=finance_verification,
            extraction_warnings=extraction_warnings,
            survey_verification=survey_verification,
        )

        # Encode ke base64 untuk dikirim via JSON
        import base64
        docx_b64 = base64.b64encode(docx_bytes).decode("utf-8")

        return {
            "status": "ok",
            "session_id": session_id,
            "audit_text": final_text,
            "docx_base64": docx_b64,
            "docx_filename": f"Laporan_Audit_RMD-TRA_{session_id[:8]}.docx",
        }

    except Exception as e:
        import traceback

        # ExceptionGroup (dari ParallelAgent/TaskGroup) menyembunyikan error
        # aslinya di .exceptions — bongkar supaya penyebab nyata terlihat di
        # log DAN di pesan error yang sampai ke pengguna, bukan cuma
        # "unhandled errors in a TaskGroup (N sub-exceptions)".
        causes = []
        stack = [e]
        while stack:
            err = stack.pop()
            subs = getattr(err, "exceptions", None)
            if subs:
                stack.extend(subs)
            else:
                causes.append(err)

        print(f"[RMD-TRA P5 ERROR] /analyze: {e}")
        for i, c in enumerate(causes):
            print(f"[RMD-TRA P5 ERROR]   penyebab #{i + 1}: {type(c).__name__}: {c}")
            traceback.print_exception(type(c), c, c.__traceback__)

        cause_txt = "; ".join(f"{type(c).__name__}: {c}" for c in causes[:3])
        raise HTTPException(
            status_code=500,
            detail=f"Error analisis: {cause_txt[:500] or str(e)[:500]}",
        )
