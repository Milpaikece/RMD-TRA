"""
RMD-TRA — pillar5/survey_tools.py
Verifikasi Angka Survei / Kualitas-Layanan Otomatis (deterministik, bukan LLM)

Melengkapi finance_tools.py. Skripsi transportasi ITL terbagi dua keluarga:
  (A) studi kelayakan finansial  -> NPV/IRR/BCR  (ditangani finance_tools.py)
  (B) survei kualitas layanan     -> CSI/IPA/SERVQUAL/SPM, kuesioner, responden

Untuk keluarga (B), finance_tools diam total. Modul ini menutup celah itu dengan
tiga pemeriksaan deterministik — dijalankan di Python SEBELUM teks dikirim ke
agen, jadi tidak bisa berhalusinasi:

  1. verify_sample_size_consistency — semua deklarasi jumlah responden / n
     dikumpulkan; kalau berbeda-beda (mis. narasi "100 responden" tapi caption
     tabel "n=394"), ditandai sebagai inkonsistensi.

  2. verify_percentage_columns — tabel distribusi yang punya kolom persen
     dikelompokkan per kategori; tiap grup persennya harus ~100%. Grup yang
     jumlahnya melenceng ditandai. Kalibrasi-diri: hanya tabel yang TERBUKTI
     distribusi (minimal satu grup ~100%) yang diperiksa, agar kolom persen
     non-distribusi (mis. % pertumbuhan) tidak ditandai palsu.

  3. verify_ratio_claims — klaim rasio "X dari Y ... Z%" dihitung ulang
     (X/Y*100) dan dibandingkan dengan Z yang tertulis.

PRINSIP ANTI-FALSE-POSITIVE: ambang toleransi dibuat sehingga hanya
penyimpangan yang jelas nyata yang ditandai; ragu = tidak menuduh.
"""
from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Parsing angka (gaya Indonesia & Barat) — cerminan finance_tools._parse_id_number
# ---------------------------------------------------------------------------
def _parse_num(raw: str) -> Optional[float]:
    s = raw.strip()
    if not s:
        return None
    has_comma, has_dot = "," in s, "." in s
    if has_comma and has_dot:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        groups = s.split(",")
        if len(groups) > 1 and all(len(g) == 3 for g in groups[1:]):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif has_dot:
        groups = s.split(".")
        if len(groups) > 1 and all(len(g) == 3 for g in groups[1:]):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _table_blocks(text: str) -> list[str]:
    return re.findall(r"\[TABEL\](.*?)\[/TABEL\]", text, re.DOTALL)


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.split("|")]


# ===========================================================================
# Deteksi tipe skripsi
# ===========================================================================
_TYPE_SIGNALS = {
    "finansial": [
        r"\bNPV\b", r"\bIRR\b", r"\bBCR\b", r"\bBEP\b", r"payback",
        r"arus\s+kas", r"kelayakan\s+(?:finansial|investasi|ekonomi)",
        r"biaya\s+modal", r"discount\s+rate", r"nilai\s+sekarang\s+bersih",
    ],
    "survei": [
        r"\bresponden\b", r"kuesioner", r"skala\s+likert", r"\bCSI\b",
        r"customer\s+satisfaction", r"importance\s+performance", r"\bIPA\b",
        r"servqual", r"service\s+quality", r"\bSPM\b",
        r"standar\s+pelayanan\s+minimum", r"tingkat\s+kepuasan",
        r"validitas", r"reliabilitas",
    ],
}


def detect_thesis_type(text: str) -> dict:
    """
    Tebak keluarga skripsi dari sinyal kata kunci. Mengembalikan skor mentah
    supaya keputusan transparan (bukan kotak hitam). Ambang: sebuah keluarga
    dianggap 'aktif' bila skornya >= 3 (beberapa sinyal berbeda muncul).
    """
    scores = {}
    for fam, patterns in _TYPE_SIGNALS.items():
        scores[fam] = sum(
            1 for p in patterns if re.search(p, text, re.IGNORECASE)
        )
    fin, sur = scores["finansial"], scores["survei"]
    if fin >= 3 and sur >= 3:
        label = "campuran (finansial + survei)"
    elif fin >= 3:
        label = "finansial (studi kelayakan)"
    elif sur >= 3:
        label = "survei (kualitas layanan)"
    else:
        label = "umum / tidak tergolong jelas"
    return {"label": label, "scores": scores}


# ===========================================================================
# 1. Konsistensi jumlah responden / n
# ===========================================================================
# Sumber deklarasi ukuran sampel TOTAL. Tiap pola menangkap satu angka di grup 1.
_N_PATTERNS = [
    (r"\(\s*n\s*=\s*(\d[\d.,]*)\s*\)", "caption tabel (n=…)"),
    (r"\bn\s*=\s*(\d[\d.,]*)", "notasi n=…"),
    (r"melibatkan\s+(\d[\d.,]*)\s+responden", "narasi 'melibatkan … responden'"),
    (r"total\s+(?:sebanyak\s+)?(\d[\d.,]*)\s+responden", "narasi 'total … responden'"),
    (r"sebanyak\s+(\d[\d.,]*)\s+(?:orang\s+)?responden", "narasi 'sebanyak … responden'"),
    (r"terhadap\s+(\d[\d.,]*)\s+responden", "narasi 'terhadap … responden'"),
    (r"(\d[\d.,]*)\s+responden\s+(?:yang|merupakan)", "narasi '… responden yang/merupakan'"),
    (r"jumlah\s+(?:sampel|responden)[^0-9]{0,30}?(\d[\d.,]*)", "narasi 'jumlah sampel/responden …'"),
    (r"ukuran\s+sampel[^0-9]{0,30}?(\d[\d.,]*)", "narasi 'ukuran sampel …'"),
]

# Angka yang langsung diikuti "(xx%)" adalah hitungan SUBGRUP (mis. "sebanyak 34
# responden (34%)"), bukan total sampel — harus dikecualikan agar tidak jadi
# inkonsistensi palsu.
_SUBGROUP_LOOKAHEAD = re.compile(r"^\s*\(?\s*[\d.,]+\s*%")
# Konteks uji-coba/validitas memakai sampel kecil terpisah (mis. 30 untuk uji
# validitas) yang memang beda dari sampel utama — bukan inkonsistensi.
_PILOT_CTX = re.compile(
    r"uji\s*coba|pra[-\s]?survei|pra[-\s]?uji|pretest|pre[-\s]?test|"
    r"uji\s+validitas|uji\s+reliabilitas",
    re.IGNORECASE,
)


def verify_sample_size_consistency(text: str) -> dict:
    """
    Kumpulkan deklarasi ukuran sampel TOTAL (n / jumlah responden) dari narasi
    maupun caption tabel. Kalau muncul lebih dari satu NILAI berbeda, itu sinyal
    kuat inkonsistensi (mis. salah ketik caption 'n=394' padahal narasi '100
    responden').

    Anti-false-positive: (a) hanya nilai wajar 5..100000; (b) angka yang diikuti
    '(xx%)' dibuang karena itu hitungan subgrup, bukan total; (c) angka di
    konteks uji-coba/validitas dibuang karena sampel pilot memang berbeda.
    """
    found: dict[int, list[dict]] = {}
    for pattern, source in _N_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            val = _parse_num(m.group(1))
            if val is None:
                continue
            n = int(round(val))
            if not (5 <= n <= 100000):
                continue
            # (b) buang hitungan subgrup: "… responden (34%)"
            tail = text[m.end():m.end() + 10]
            if _SUBGROUP_LOOKAHEAD.match(tail):
                continue
            # (c) buang sampel pilot/uji-coba
            window = text[max(0, m.start() - 60):m.end() + 10]
            if _PILOT_CTX.search(window):
                continue
            ctx_start = max(0, m.start() - 45)
            ctx = text[ctx_start:m.end() + 15].replace("\n", " ").strip()
            found.setdefault(n, []).append({"source": source, "context": ctx})

    distinct = sorted(found.keys())
    if len(distinct) <= 1:
        status = (
            "KONSISTEN — ukuran sampel disebut seragam"
            if distinct else
            "TIDAK ADA deklarasi ukuran sampel yang terdeteksi"
        )
        return {"status": status, "values": distinct, "inconsistent": False,
                "occurrences": found}

    # >1 nilai berbeda -> inkonsistensi. Sajikan tiap nilai + satu contoh konteks.
    return {
        "status": f"INKONSISTEN — ukuran sampel disebut dengan {len(distinct)} nilai berbeda: "
                  + ", ".join(str(d) for d in distinct),
        "values": distinct,
        "inconsistent": True,
        "occurrences": found,
    }


# ===========================================================================
# 2. Jumlah kolom persentase per grup harus ~100%
# ===========================================================================
def _find_percent_col(header_cells: list[str]) -> Optional[int]:
    for j, h in enumerate(header_cells):
        if "%" in h or re.search(r"persen", h, re.IGNORECASE):
            return j
    return None


def verify_percentage_columns(text: str, tol: float = 1.5) -> dict:
    """
    Untuk tiap tabel dengan kolom persen, kelompokkan baris berdasarkan kolom
    pertama (kategori, mis. 'Usia', 'Jenis Kelamin') dan jumlahkan persennya.
    Grup distribusi yang benar harus ~100%.

    Kalibrasi-diri terhadap false positive: sebuah tabel HANYA diperiksa kalau
    minimal satu grup di dalamnya berjumlah ~100% (bukti tabel itu memang tabel
    distribusi). Dengan begitu kolom persen non-distribusi (mis. '% pertumbuhan',
    '% kesesuaian per indikator') tidak ikut diperiksa dan tidak ditandai palsu.
    """
    problems: list[dict] = []
    checked_tables = 0

    for block in _table_blocks(text):
        rows = [_split_row(ln) for ln in block.splitlines() if ln.strip()]
        if len(rows) < 3:
            continue
        header = rows[0]
        pcol = _find_percent_col(header)
        if pcol is None or len(header) < 2:
            continue

        # kelompokkan baris data per kategori (kolom 0). Baris tanpa label
        # kategori digabung ke grup terakhir yang punya label (tabel sering
        # mengulang label hanya di baris pertama tiap grup).
        groups: dict[str, float] = {}
        order: list[str] = []
        current = None
        for r in rows[1:]:
            if len(r) <= pcol:
                continue
            label = r[0].strip()
            pv = _parse_num(re.sub(r"[^\d.,]", "", r[pcol]))
            if pv is None:
                continue
            if label:
                current = label
                if current not in groups:
                    groups[current] = 0.0
                    order.append(current)
            if current is None:
                current = "(tanpa kategori)"
                groups.setdefault(current, 0.0)
                if current not in order:
                    order.append(current)
            groups[current] += pv

        if not groups:
            continue
        # Bukti tabel distribusi: ada grup yang ~100%.
        looks_distribution = any(abs(s - 100.0) <= tol for s in groups.values()) \
            or (len(groups) == 1 and abs(next(iter(groups.values())) - 100.0) <= 10)
        if not looks_distribution:
            continue
        checked_tables += 1

        for g in order:
            s = groups[g]
            if abs(s - 100.0) > tol:
                caption = _nearest_caption(text, block)
                problems.append({
                    "table": caption,
                    "group": g,
                    "sum": round(s, 2),
                    "note": f"grup '{g}' berjumlah {s:.2f}% (seharusnya ~100%)",
                })

    if not problems:
        status = (
            f"KONSISTEN — {checked_tables} tabel distribusi diperiksa, semua grup ~100%"
            if checked_tables else
            "TIDAK ADA tabel distribusi persen yang bisa diverifikasi"
        )
        return {"status": status, "problems": [], "tables_checked": checked_tables}
    return {
        "status": f"DITEMUKAN {len(problems)} grup persen yang tidak berjumlah 100%",
        "problems": problems,
        "tables_checked": checked_tables,
    }


def _nearest_caption(text: str, block: str) -> str:
    """Ambil caption 'Tabel X.Y …' yang paling dekat sebelum blok tabel."""
    idx = text.find(block)
    if idx == -1:
        return "(tabel)"
    pre = text[max(0, idx - 200):idx]
    caps = re.findall(r"(Tabel\s+\d+[.\d]*[^\n]{0,80})", pre, re.IGNORECASE)
    return caps[-1].strip() if caps else "(tabel tanpa caption dekat)"


# ===========================================================================
# 3. Klaim rasio "X dari Y ... Z%" dihitung ulang
# ===========================================================================
# Tangkap: "21 dari 31 indikator ... 67,74%" dan variasinya.
# Grup selalu (x, y, z) dengan x=bagian, y=total, z=persen klaim.
_RATIO_PATTERNS = [
    # "21 dari 31 indikator ... 67,74%"
    (r"(\d[\d.,]*)\s+dari\s+(\d[\d.,]*)\s+[^.\n]{0,60}?\(?\s*(\d[\d.,]*)\s*%", (1, 2, 3)),
    # "21/31 ... 67,74%"
    (r"(\d[\d.,]*)\s*/\s*(\d[\d.,]*)\s+[^.\n]{0,40}?\(?\s*(\d[\d.,]*)\s*%", (1, 2, 3)),
    # urutan terbalik: "mencapai 67,74%. Dari total 31 indikator ... terdapat 21 indikator"
    # (z dulu, lalu y=total, lalu x=bagian). Jangkar 'dari total N indikator' +
    # 'terdapat N' cukup spesifik, jadi boleh melintasi satu titik kalimat
    # (izinkan '.' tapi tidak newline, panjang dibatasi).
    (r"(\d[\d.,]*)\s*%[^\n]{0,70}?dari\s+total\s+(\d[\d.,]*)\s+(?:indikator|atribut|aspek|item|responden)"
     r"[^\n]{0,80}?terdapat\s+(\d[\d.,]*)", (3, 2, 1)),
]


def verify_ratio_claims(text: str, tol: float = 0.6) -> dict:
    """
    Cari klaim proporsi eksplisit 'X dari Y … Z%', hitung ulang X/Y*100, dan
    bandingkan dengan Z. Ditandai hanya kalau selisih > tol (poin persen),
    supaya pembulatan wajar tidak dituduh salah.
    """
    checks: list[dict] = []
    problems: list[dict] = []
    seen: set[tuple] = set()
    for pattern, (xi, yi, zi) in _RATIO_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            x, y, z = _parse_num(m.group(xi)), _parse_num(m.group(yi)), _parse_num(m.group(zi))
            if x is None or y is None or z is None or y == 0:
                continue
            if x > y:                      # 'X dari Y' harus X<=Y; kalau tidak, bukan rasio
                continue
            key = (round(x, 3), round(y, 3), round(z, 3))
            if key in seen:
                continue
            seen.add(key)
            computed = x / y * 100.0
            ok = abs(computed - z) <= tol
            ctx = text[max(0, m.start() - 20):m.end() + 10].replace("\n", " ").strip()
            rec = {"x": x, "y": y, "claimed_pct": z,
                   "computed_pct": round(computed, 2), "ok": ok, "context": ctx}
            checks.append(rec)
            if not ok:
                problems.append(rec)

    if not checks:
        return {"status": "TIDAK ADA klaim rasio 'X dari Y = Z%' yang terdeteksi",
                "problems": [], "checks": []}
    if not problems:
        return {"status": f"KONSISTEN — {len(checks)} klaim rasio dihitung ulang, semua cocok",
                "problems": [], "checks": checks}
    return {"status": f"DITEMUKAN {len(problems)} klaim rasio yang tidak cocok dengan hitung ulang",
            "problems": problems, "checks": checks}


# ===========================================================================
# 4. Rumus Slovin — hitung ulang ukuran sampel n = N / (1 + N·e²)
# ===========================================================================
import math as _math


def _slovin_n(N: float, e: float) -> int:
    """Ukuran sampel Slovin, dibulatkan ke atas (konvensi kebutuhan minimal)."""
    return _math.ceil(N / (1 + N * e * e))


def _margin_fraction(raw: str) -> Optional[float]:
    """'5%'→0.05 ; '0,05'→0.05 ; '10'→0.10. Kembalikan fraksi 0<e<1."""
    v = _parse_num(raw.replace("%", ""))
    if v is None or v <= 0:
        return None
    if v >= 1:            # ditulis sebagai persen bulat (5, 10)
        v = v / 100.0
    return v if 0 < v < 1 else None


def verify_slovin(text: str) -> dict:
    """
    Cari populasi N, semua margin error yang disebut, dan ukuran sampel n yang
    diklaim; lalu hitung ulang Slovin. Dua sinyal galat yang dikejar:

      (1) lebih dari satu margin berbeda disebut (mis. '5%' di satu kalimat,
          '10%' di kalimat berikutnya) — kontradiksi internal metodologi;
      (2) sampel yang diklaim sebenarnya cocok dengan margin LAIN, bukan margin
          yang dinyatakan (mis. n=100 sesuai e=10%, padahal teks bilang 5%).

    Anti-false-positive: kalau 'slovin' tidak disebut sama sekali, kembalikan
    status netral tanpa temuan (jangan mengarang). Toleransi pencocokan sampel
    dibuat longgar agar pembulatan wajar (394↔400) tidak dituduh salah.
    """
    if not re.search(r"slovin", text, re.IGNORECASE):
        return {"status": "TIDAK memakai rumus Slovin — tidak diperiksa",
                "applicable": False, "issues": []}

    # Populasi N
    N = None
    for pat in (
        r"rata[\s-]*rata\s+([\d.,]{3,})\s*penumpang",
        r"populasi[^.\n]{0,90}?([\d.,]{3,})",
        r"\bN\s*=\s*([\d.,]{3,})",
        r"jumlah\s+populasi[^.\n]{0,40}?([\d.,]{3,})",
    ):
        for m in re.finditer(pat, text, re.IGNORECASE):
            cand = _parse_num(m.group(1))
            if cand and cand >= 30:
                N = int(round(cand))
                break
        if N:
            break

    # Semua margin yang disebut (nilai berbeda saja)
    margins: list[float] = []
    for pat in (
        r"(?:toleransi\s+kesalahan|error\s*margin|margin\s+of\s+error|batas\s+toleransi|"
        r"taraf\s+kesalahan|tingkat\s+(?:toleransi\s+)?kesalahan)[^%\d\n]{0,45}?(\d{1,2}(?:[.,]\d+)?)\s*%",
        r"\be\s*=\s*(\d{1,2}(?:[.,]\d+)?)\s*%",
        r"\be\s*=\s*(0[.,]\d+)\b",
    ):
        for m in re.finditer(pat, text, re.IGNORECASE):
            f = _margin_fraction(m.group(1))
            if f and all(abs(f - g) > 1e-9 for g in margins):
                margins.append(f)
    margins.sort()

    # Ukuran sampel yang diklaim
    n_stated = None
    for pat in (
        r"(?:responden\s+minimal|jumlah\s+responden|jumlah\s+sampel|ukuran\s+sampel|"
        r"sampel\s+sebanyak|diperoleh)[^.\n]{0,60}?([\d.,]{2,5})\s*(?:responden|sampel|orang)",
        r"\bn\s*=\s*([\d.,]{2,5})\b",
    ):
        for m in re.finditer(pat, text, re.IGNORECASE):
            cand = _parse_num(m.group(1))
            if cand and 20 <= cand <= 100000:
                n_stated = int(round(cand))
                break
        if n_stated:
            break

    res = {
        "applicable": True,
        "population": N,
        "margins_mentioned": [round(e, 4) for e in margins],
        "sample_stated": n_stated,
        "recomputed": [(round(e, 4), _slovin_n(N, e)) for e in margins] if N else [],
        "issues": [],
    }

    if len(margins) > 1:
        res["issues"].append(
            "Margin error yang disebut TIDAK konsisten: "
            + ", ".join(f"{e*100:g}%" for e in margins)
            + ". Rumus Slovin hanya memakai satu margin — seluruh metodologi harus "
            "menyebut angka yang sama."
        )

    if N and n_stated:
        tol = max(3, round(n_stated * 0.03))
        matched = None
        for e in margins + [0.01, 0.05, 0.10]:
            if abs(_slovin_n(N, e) - n_stated) <= tol:
                matched = e
                break
        res["sample_matches_margin"] = round(matched, 4) if matched else None
        if matched is not None and margins and all(abs(matched - g) > 1e-9 for g in margins):
            e0 = margins[0]
            res["issues"].append(
                f"Sampel {n_stated} responden sesuai margin {matched*100:g}% "
                f"(Slovin N={N:,} → {_slovin_n(N, matched)}), BUKAN margin {e0*100:g}% "
                f"yang dinyatakan (seharusnya {_slovin_n(N, e0)} responden)."
            )
        elif matched is None and margins:
            e0 = margins[0]
            res["issues"].append(
                f"Sampel {n_stated} responden tidak cocok dengan margin {e0*100:g}% "
                f"(Slovin N={N:,} → {_slovin_n(N, e0)}) maupun margin standar 1/5/10%. "
                "Periksa ulang perhitungan Slovin-nya."
            )

    status = ("KONSISTEN — Slovin cocok" if not res["issues"]
              else f"DITEMUKAN {len(res['issues'])} masalah pada perhitungan Slovin")
    res["status"] = status
    return res


# ===========================================================================
# Orkestrator
# ===========================================================================
def build_survey_verification(text: str) -> dict:
    """Jalankan seluruh pemeriksaan survei dan rangkum."""
    return {
        "type": detect_thesis_type(text),
        "slovin": verify_slovin(text),
        "sample_size": verify_sample_size_consistency(text),
        "percentages": verify_percentage_columns(text),
        "ratios": verify_ratio_claims(text),
    }
