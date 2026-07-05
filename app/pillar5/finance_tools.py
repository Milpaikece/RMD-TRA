"""
RMD-TRA — pillar5/finance_tools.py
Verifikasi Angka Finansial Otomatis (deterministik, bukan tebakan LLM)

PRINSIP (sama seperti stats_tools.py Pilar 2): agen TIDAK boleh menebak atau
menghitung ulang angka finansial di kepalanya sendiri. Dua fungsi di sini
dijalankan di Python SEBELUM teks dikirim ke sub-agen, hasilnya disuntikkan
langsung ke prompt sebagai data yang sudah pasti benar. Sub-agen tinggal
membaca dan menarasikan, bukan menghitung.

1. extract_labeled_figures  — kumpulkan SEMUA penyebutan NPV/IRR/BCR/PBP/
   jumlah armada/kapasitas baterai di seluruh dokumen, tandai subjeknya
   (bus listrik vs bus diesel), lalu deteksi kalau ada nilai yang berbeda
   untuk subjek & indikator yang sama (mis. NPV bus listrik disebut beda
   di Abstrak vs Bab IV).

2. recompute_bca_from_tables — cari tabel arus kas (dari [TABEL]...[/TABEL]
   hasil ekstraksi dokumen), hitung ulang NPV/IRR/BCR/PBP dari angka
   mentahnya, bandingkan dengan nilai yang diklaim di teks.
"""
from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Helper — parsing angka format Indonesia MAUPUN Barat
# ---------------------------------------------------------------------------
def _parse_id_number(raw: str) -> Optional[float]:
    """
    Ubah string angka jadi float, mendukung dua gaya penulisan yang sama-sama
    muncul di dokumen skripsi: gaya Indonesia ('5.290.190,50' — titik ribuan,
    koma desimal) dan gaya Barat ('1,970,154.295' atau '1,970,154,295' —
    koma ribuan, titik/tanpa desimal). Tabel numerik dan teks naratif dalam
    dokumen yang sama sering memakai gaya berbeda.
    """
    s = raw.strip()
    if not s:
        return None
    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        # pemisah desimal = yang muncul PALING BELAKANG
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")  # gaya ID: "5.290.190,50"
        else:
            s = s.replace(",", "")  # gaya Barat: "1,970,154.295"
    elif has_comma:
        groups = s.split(",")
        if len(groups) > 1 and all(len(g) == 3 for g in groups[1:]):
            s = s.replace(",", "")  # ribuan gaya Barat: "1,970,154,295"
        else:
            s = s.replace(",", ".")  # desimal gaya ID: "35,8" / "0,64"
    elif has_dot:
        groups = s.split(".")
        if len(groups) > 1 and all(len(g) == 3 for g in groups[1:]):
            s = s.replace(".", "")  # ribuan gaya ID: "5.290.190"
        # else: titik desimal biasa, biarkan apa adanya ("35.8")
    try:
        return float(s)
    except ValueError:
        return None


_SUBJECT_PATTERNS = {
    "bus listrik": r'\b(?:bus\s+listrik|electric\s+bus|kendaraan\s+listrik|EV\b|VKTR|BYD)\b',
    "bus diesel": r'\b(?:bus\s+diesel|bus\s+konvensional|diesel|konvensional|ICE\b|Mercedes[- ]Benz|internal\s+combustion)\b',
}

# Cuma nama indikatornya — nilainya dicari lewat kata penghubung setelah
# kata kunci ini, karena di kalimat nyata sering ada sisipan kata antara
# nama indikator dan angkanya (mis. "NPV bus listrik sebesar Rp X").
_INDICATOR_KEYWORDS = {
    "NPV": r'\bNPV\b',
    "IRR": r'\bIRR\b',
    "BCR": r'\bBCR\b',
    "PBP (tahun)": r'\b(?:PBP|Payback\s+Period)\b',
}

# Kata penghubung WAJIB ada antara nama indikator dan angkanya — mencegah
# angka tak terkait (mis. "10 tahun" pada kalimat "...PBP, dan BCR dengan
# periode analisis selama 10 tahun") ikut tertangkap sebagai nilai indikator.
# "=" polos SENGAJA tidak dimasukkan — terlalu longgar, sering menangkap
# variabel rumus lain (mis. "r = 10%", "i = 10%") yang bukan nilai indikator.
_CONNECTOR = re.compile(r'(?:sebesar|adalah|senilai|diperoleh|\|)', re.IGNORECASE)
_VALUE_AFTER_CONNECTOR = re.compile(r'(?:Rp\.?\s*)?(-?[\d]+(?:[.,]\d+)*)\s*(?:%|tahun)?', re.IGNORECASE)
# Kalau teks antara nama indikator dan angkanya menyebut variabel lain
# (tingkat diskonto, discount rate), nilainya bukan milik indikator ini.
_UNRELATED_VALUE_HINT = re.compile(r'diskonto|discount\s+rate', re.IGNORECASE)

_KEYWORD_TO_CONNECTOR_GAP = 80  # jarak maks cari kata penghubung setelah nama indikator
_CONNECTOR_TO_VALUE_GAP = 20    # jarak maks cari angka setelah kata penghubung
_SUBJECT_SEARCH_BEFORE = 90     # jarak maks cari subjek sebelum nama indikator


# Sel dianggap "nilai murni" hanya kalau SELURUH isinya angka (opsional Rp/%),
# bukan sekadar mengandung angka — supaya angka yang nyelip di teks keterangan
# (mis. "...di atas diskonto (10%)") tidak ikut terambil.
_CELL_IS_NUMBER = re.compile(r'(?:Rp\.?\s*)?-?\d[\d.,]*\s*%?$', re.IGNORECASE)


def _extract_figures_from_tables(document_text: str) -> list[dict]:
    """
    Ekstraksi indikator dari tabel secara COLUMN-AWARE: baca header untuk tahu
    kolom mana milik bus listrik vs bus diesel, lalu atribusikan tiap nilai ke
    subjek kolomnya yang benar. Ini menggantikan pendekatan lama (mengecualikan
    tabel) — sekarang inkonsistensi nyata di tabel bisa tertangkap TANPA salah
    atribusi, karena subjek ditentukan posisi kolom, bukan kedekatan teks.
    """
    mentions: list[dict] = []
    for mt in re.finditer(r'\[TABEL\](.*?)\[/TABEL\]', document_text, re.DOTALL):
        base_pos = mt.start()
        rows = [
            [c.strip() for c in ln.strip().strip("|").split("|")]
            for ln in mt.group(1).splitlines() if ln.strip()
        ]
        if len(rows) < 2:
            continue

        # Peta kolom -> subjek, dari baris header PERTAMA yang menyebut subjek.
        col_subject: dict[int, str] = {}
        for row in rows:
            tentative: dict[int, str] = {}
            for j, cell in enumerate(row):
                for subj_name, subj_pat in _SUBJECT_PATTERNS.items():
                    if re.search(subj_pat, cell, re.IGNORECASE):
                        tentative[j] = subj_name
                        break
            if tentative:
                col_subject = tentative
                break
        if not col_subject:
            continue  # tabel tanpa penanda subjek per kolom -> tak bisa diatribusi

        # Baris data: sel pertama = nama indikator, sel berikutnya = nilai per kolom.
        for row in rows:
            if not row:
                continue
            indicator = next(
                (ind for ind, kw in _INDICATOR_KEYWORDS.items()
                 if re.search(kw, row[0], re.IGNORECASE)),
                None,
            )
            if not indicator:
                continue
            for j, cell in enumerate(row):
                if j == 0 or j not in col_subject:
                    continue
                if not _CELL_IS_NUMBER.fullmatch(cell.strip()):
                    continue
                value = _parse_id_number(re.sub(r'[Rp%\s]', '', cell))
                if value is None:
                    continue
                mentions.append({
                    "indicator": indicator,
                    "subject": col_subject[j],
                    "value": value,
                    "raw_text": f"[Tabel] {row[0]} = {cell.strip()} (kolom {col_subject[j]})",
                    "position": base_pos,
                })
    return mentions


def extract_labeled_figures(document_text: str) -> dict:
    """
    Kumpulkan SEMUA penyebutan indikator finansial (NPV, IRR, BCR, PBP) di
    seluruh dokumen, tandai subjeknya (bus listrik/bus diesel/tidak
    diketahui), lalu deteksi inkonsistensi: indikator + subjek yang sama
    tapi nilainya berbeda di lokasi berbeda (mis. Abstrak vs Bab IV, atau
    narasi vs tabel).

    Args:
        document_text: Seluruh teks dokumen (bukan potongan per-bab).

    Returns:
        dict berisi semua kemunculan yang terdeteksi, dikelompokkan per
        (indikator, subjek), dan daftar inkonsistensi yang ditemukan.
    """
    # Rentang [TABEL]...[/TABEL] harus DIKECUALIKAN dari deteksi inkonsistensi:
    # di tabel perbandingan (header "Diesel|Diesel|Diesel|Listrik|Listrik|Listrik"),
    # subjek sebuah nilai ditentukan oleh POSISI KOLOM, bukan kedekatan teks — jadi
    # pemindaian mundur akan salah melabeli nilai diesel sebagai bus listrik dan
    # menghasilkan "inkonsistensi" palsu. Nilai di tabel ditangani terpisah oleh
    # recompute_bca_from_tables yang memang column-aware. Deteksi inkonsistensi di
    # sini hanya dari kalimat NARATIF (format jelas "NPV bus listrik sebesar X").
    table_spans = [
        (mt.start(), mt.end())
        for mt in re.finditer(r'\[TABEL\].*?\[/TABEL\]', document_text, re.DOTALL)
    ]

    def _inside_table(pos: int) -> bool:
        return any(start <= pos < end for start, end in table_spans)

    mentions = []
    for indicator, kw_pattern in _INDICATOR_KEYWORDS.items():
        for m in re.finditer(kw_pattern, document_text, re.IGNORECASE):
            if _inside_table(m.start()):
                continue
            after = document_text[m.end():m.end() + _KEYWORD_TO_CONNECTOR_GAP]
            conn_m = _CONNECTOR.search(after)
            if not conn_m:
                continue
            if _UNRELATED_VALUE_HINT.search(after[:conn_m.start()]):
                continue  # "sebesar" di sini milik variabel lain (mis. tingkat diskonto), bukan indikator ini
            value_zone = after[conn_m.end():conn_m.end() + _CONNECTOR_TO_VALUE_GAP]
            val_m = _VALUE_AFTER_CONNECTOR.search(value_zone)
            if not val_m or not val_m.group(1):
                continue
            value = _parse_id_number(val_m.group(1))
            if value is None:
                continue

            # Subjek: cari kata kunci TERDEKAT di antara [sebelum nama indikator]
            # sampai [setelah kata penghubung] — bukan sekadar "ada di jendela",
            # supaya kalimat perbandingan ("...listrik X, sedangkan diesel Y...")
            # tidak salah atribusi ke subjek yang jauh.
            search_start = max(0, m.start() - _SUBJECT_SEARCH_BEFORE)
            search_end = m.end() + conn_m.end()
            search_zone = document_text[search_start:search_end]
            subject = "tidak diketahui"
            best_dist = None
            for subj_name, subj_pattern in _SUBJECT_PATTERNS.items():
                for sm in re.finditer(subj_pattern, search_zone, re.IGNORECASE):
                    abs_pos = search_start + sm.start()
                    dist = abs(abs_pos - m.start())
                    if best_dist is None or dist < best_dist:
                        best_dist, subject = dist, subj_name

            display_start = max(0, m.start() - 60)
            display_end = min(len(document_text), m.end() + conn_m.end() + _CONNECTOR_TO_VALUE_GAP)
            mentions.append({
                "indicator": indicator,
                "subject": subject,
                "value": value,
                "raw_text": document_text[display_start:display_end].strip().replace("\n", " "),
                "position": m.start(),
            })

    # Tambahkan nilai dari TABEL secara column-aware (subjek dari posisi kolom).
    mentions.extend(_extract_figures_from_tables(document_text))

    groups: dict[tuple[str, str], list[dict]] = {}
    for men in mentions:
        if men["subject"] == "tidak diketahui":
            continue  # tidak bisa dibandingkan tanpa tahu subjeknya
        key = (men["indicator"], men["subject"])
        groups.setdefault(key, []).append(men)

    inconsistencies = []
    for (indicator, subject), items in groups.items():
        distinct_values = {round(i["value"], 2) for i in items}
        if len(distinct_values) > 1:
            inconsistencies.append({
                "indicator": indicator,
                "subject": subject,
                "occurrences": [
                    {"value": i["value"], "raw_text": i["raw_text"], "position": i["position"]}
                    for i in items
                ],
                "warning": (
                    f"{indicator} untuk {subject} disebut dengan nilai berbeda "
                    f"di {len(items)} lokasi berbeda: "
                    + ", ".join(
                        (f"{i['value']:,.0f}".replace(",", ".") if abs(i['value']) >= 1000 else f"{i['value']:g}")
                        for i in items
                    )
                ),
            })

    return {
        "total_mentions_found": len(mentions),
        "inconsistencies_found": len(inconsistencies),
        "inconsistencies": inconsistencies,
        "status": (
            "KONSISTEN — tidak ditemukan angka yang bertentangan"
            if not inconsistencies
            else f"TERDETEKSI {len(inconsistencies)} INKONSISTENSI ANGKA — wajib dilaporkan sebagai galat Kritis"
        ),
    }


# ---------------------------------------------------------------------------
# Hitung ulang BCA dari tabel arus kas
# ---------------------------------------------------------------------------
def _find_discount_rate(document_text: str) -> float:
    m = re.search(r'(?:tingkat\s+diskonto|discount\s+rate)[^\d]{0,20}(\d+(?:[.,]\d+)?)\s*%', document_text, re.IGNORECASE)
    if m:
        val = _parse_id_number(m.group(1))
        if val is not None:
            return val / 100
    return 0.10  # default 10% kalau tidak disebutkan eksplisit


def _detect_table_subject(block: str) -> str:
    """Tebak subjek tabel (bus listrik / bus diesel / keduanya) dari isinya."""
    found = {
        name for name, pat in _SUBJECT_PATTERNS.items()
        if re.search(pat, block, re.IGNORECASE)
    }
    if len(found) == 1:
        return next(iter(found))
    if len(found) > 1:
        return "diesel & listrik"
    return "tidak diketahui"


def _parse_cashflow_table(table_block: str):
    """
    Parse satu blok tabel jadi arus kas. Mengembalikan salah satu:
      ("net",    [(tahun, benefit, cost), ...])  -> ada kolom manfaat DAN biaya
      ("single", [(tahun, nilai), ...], nama_kolom) -> hanya satu kolom (ambigu)
      None -> bukan tabel arus kas yang dikenali.

    Perbedaan mode ini penting: NPV/IRR hanya sahih dihitung dari arus kas BERSIH
    (manfaat − biaya). Kalau tabel cuma punya satu kolom (mis. "Net Cash" yang
    ternyata biaya operasional saja), memaksa hitung NPV menghasilkan angka
    menyesatkan — jadi ditandai "single" agar tidak dihitung sebagai NPV.
    """
    rows = [r.strip() for r in table_block.splitlines() if r.strip() and "|" in r]
    if len(rows) < 2:
        return None

    header = [c.strip().lower() for c in rows[0].split("|")]
    year_idx = next((i for i, c in enumerate(header) if "tahun" in c or "year" in c or "periode" in c), None)
    benefit_idx = next((i for i, c in enumerate(header) if "manfaat" in c or "benefit" in c or "pendapatan" in c or "revenue" in c), None)
    cost_idx = next((i for i, c in enumerate(header) if "biaya" in c or "cost" in c), None)
    cashflow_idx = next((i for i, c in enumerate(header) if "arus kas" in c or "cash flow" in c or "net cash" in c), None)

    if year_idx is None:
        return None

    def _cell_num(cells, idx):
        if idx is None or idx >= len(cells):
            return None
        return _parse_id_number(re.sub(r'[^\d.,\-]', '', cells[idx]))

    def _year_of(cells):
        raw = re.sub(r'[^\d.,\-]', '', cells[year_idx]) if year_idx < len(cells) else ""
        if raw == "":
            return 0  # sel Tahun kosong = investasi awal (t=0)
        v = _parse_id_number(raw)
        return int(v) if v is not None else None

    # MODE NET — ada kolom manfaat DAN biaya terpisah (arus kas bersih sungguhan)
    if benefit_idx is not None and cost_idx is not None:
        flows = []
        for row in rows[1:]:
            cells = [c.strip() for c in row.split("|")]
            year = _year_of(cells)
            if year is None:
                continue
            b, c = _cell_num(cells, benefit_idx), _cell_num(cells, cost_idx)
            if b is None and c is None:
                continue
            flows.append((year, b or 0.0, c or 0.0))
        return ("net", flows) if len(flows) >= 2 else None

    # MODE SINGLE — hanya satu kolom arus kas (tak bisa dipastikan manfaat/biaya)
    if cashflow_idx is not None:
        flows = []
        for row in rows[1:]:
            cells = [c.strip() for c in row.split("|")]
            year = _year_of(cells)
            if year is None:
                continue
            v = _cell_num(cells, cashflow_idx)
            if v is None:
                continue
            flows.append((year, v))
        return ("single", flows, header[cashflow_idx].strip()) if len(flows) >= 2 else None

    return None


def _compute_npv(cashflows: list[tuple[int, float, float]], rate: float) -> float:
    return sum((b - c) / ((1 + rate) ** t) for t, b, c in cashflows)


def _compute_irr(cashflows: list[tuple[int, float, float]]) -> Optional[float]:
    """Cari IRR lewat pencarian biner sederhana (bukan Newton) — cukup untuk verifikasi kasar."""
    def npv_at(rate):
        return sum((b - c) / ((1 + rate) ** t) for t, b, c in cashflows)

    lo, hi = -0.99, 10.0
    npv_lo, npv_hi = npv_at(lo), npv_at(hi)
    if npv_lo * npv_hi > 0:
        return None  # tidak ada akar di rentang ini
    for _ in range(200):
        mid = (lo + hi) / 2
        npv_mid = npv_at(mid)
        if abs(npv_mid) < 1e-6:
            return mid
        if npv_lo * npv_mid < 0:
            hi = mid
        else:
            lo, npv_lo = mid, npv_mid
    return (lo + hi) / 2


def recompute_bca_from_tables(document_text: str, table_blocks: Optional[list[str]] = None) -> dict:
    """
    Hitung ulang NPV/IRR/BCR dari tabel arus kas yang terdeteksi di dokumen,
    lalu bandingkan dengan nilai yang diklaim lewat extract_labeled_figures.

    Args:
        document_text: Seluruh teks dokumen (untuk cari discount rate, caption
            tabel, & angka klaim). Tabel dideteksi langsung dari sini agar
            caption (judul di atas tabel) bisa dipakai menebak subjek.
        table_blocks: diabaikan (dipertahankan demi kompatibilitas pemanggil lama).

    Returns:
        dict berisi hasil hitung ulang per tabel yang berhasil dikenali,
        atau status "tidak ada tabel arus kas yang dikenali" kalau gagal.
    """
    rate = _find_discount_rate(document_text)
    recomputed = []
    n_reliable = 0

    for mt in re.finditer(r'\[TABEL\](.*?)\[/TABEL\]', document_text, re.DOTALL):
        block = mt.group(1)
        parsed = _parse_cashflow_table(block)
        if not parsed:
            continue
        # subjek: cari di isi tabel; kalau tak ketemu, lihat ~160 char caption di atasnya
        subject = _detect_table_subject(block)
        if subject == "tidak diketahui":
            caption = document_text[max(0, mt.start() - 160):mt.start()]
            subject = _detect_table_subject(caption)

        if parsed[0] == "net":
            flows = parsed[1]
            npv = _compute_npv(flows, rate)
            irr = _compute_irr(flows)
            pv_benefit = sum(b / ((1 + rate) ** t) for t, b, c in flows if b)
            pv_cost = sum(c / ((1 + rate) ** t) for t, b, c in flows if c)
            bcr = (pv_benefit / pv_cost) if pv_cost else None
            n_reliable += 1
            recomputed.append({
                "reliable": True,
                "subject": subject,
                "discount_rate_used": rate,
                "periods_found": len(flows),
                "npv_recomputed": round(npv, 2),
                "irr_recomputed": round(irr * 100, 2) if irr is not None else None,
                "bcr_recomputed": round(bcr, 3) if bcr is not None else None,
            })
        else:  # "single" — satu kolom ambigu, jangan paksa hitung NPV
            flows, col_name = parsed[1], parsed[2]
            recomputed.append({
                "reliable": False,
                "subject": subject,
                "periods_found": len(flows),
                "note": (
                    f"Tabel ini hanya memiliki satu kolom arus kas ('{col_name}') "
                    "tanpa kolom manfaat & biaya yang terpisah. Sistem TIDAK menghitung "
                    "ulang NPV/IRR di sini karena tidak dapat memastikan apakah kolom itu "
                    "manfaat atau biaya — memaksakan perhitungan akan menghasilkan angka "
                    "menyesatkan. Justru ini sinyal bahwa metodologi NPV/IRR pada tabel "
                    "tersebut perlu diperiksa Sub-Agen Statistical Auditor."
                ),
            })

    if not recomputed:
        return {
            "status": "Tidak ada tabel arus kas dalam format yang dikenali sistem — hitung ulang otomatis tidak dapat dilakukan. Jangan klaim ada verifikasi ulang untuk bagian ini.",
            "recomputed": [],
        }

    return {
        "status": (
            f"{n_reliable} tabel dihitung ulang dengan andal (punya kolom manfaat & biaya), "
            f"{len(recomputed) - n_reliable} tabel ditandai tidak-dapat-diandalkan "
            f"(satu kolom ambigu). Discount rate diasumsikan {rate*100:.0f}% kecuali disebut lain."
        ),
        "recomputed": recomputed,
    }
