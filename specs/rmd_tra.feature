# =============================================================================
# RMD-TRA — specs/rmd_tra.feature
# BDD Specification menggunakan Gherkin (Day 5 pattern)
# Format: Scenario / Given / When / Then
# Referensi: Spec-Driven Production Grade Development, May 2026, hal. 9
# =============================================================================

Feature: RMD-TRA — Research Management & Development Transportation Research Assistant

  Background:
    Given sistem RMD-TRA berjalan di Google Cloud Run
    And agen terhubung ke Vertex AI dengan model "gemini-2.0-flash"
    And Policy Server aktif dengan role default "mahasiswa"

  # ── PILAR 1: RAG + Chronological Filter ────────────────────────────────────

  Scenario: Filter referensi usang dari daftar pustaka skripsi
    Given mahasiswa mengunggah daftar pustaka yang berisi 4 referensi
    And 2 referensi berada di tahun 2015 dan 2019
    And 2 referensi berada di tahun 2022 dan 2024
    When sistem menjalankan tool "filter_references_by_year"
    Then output harus mengandung narasi yang menyebut 2 referensi usang
    And output harus menyebutkan rentang filter "2021-2026"
    And output TIDAK boleh berbentuk bullet points
    And output harus mengandung saran referensi pengganti yang spesifik

  Scenario: Koreksi sitasi APA yang format nama penulisnya salah
    Given dosen mengirim referensi "Budi Santoso, 2023, Analisis Kualitas Layanan"
    When sistem menjalankan tool "correct_citation_format" dengan style "APA"
    Then output harus mendeteksi kesalahan format nama penulis
    And output harus memberikan contoh perbaikan konkret
    And output TIDAK boleh mengklaim referensi sudah benar jika masih ada kesalahan

  Scenario: Deteksi topik penelitian di luar Roadmap Prodi
    Given mahasiswa mengirim topik "Analisis Inflasi dan Nilai Tukar Rupiah"
    When sistem menjalankan tool "check_roadmap_alignment"
    Then alignment_score harus kurang dari 30
    And output harus menyarankan kluster Roadmap yang lebih sesuai
    And agen TIDAK boleh merekomendasikan topik tersebut dilanjutkan tanpa konsultasi

  Scenario: Upload file PDF skripsi dan analisis otomatis
    Given mahasiswa mengupload file PDF skripsi berukuran kurang dari 20 MB
    When endpoint "/upload" menerima file
    Then sistem harus mengekstrak teks dari PDF
    And sistem harus mendeteksi bagian "Daftar Pustaka"
    And response harus mengandung field "references", "title", "pages", "word_count"
    And referensi yang diekstrak harus dikirim ke agen untuk dianalisis

  # ── PILAR 2: Validasi Komputasi Statistik ──────────────────────────────────

  Scenario: Parsing output SPSS koefisien jalur
    Given pengguna menempelkan output SPSS yang mengandung nilai koefisien jalur
    And output mengandung pola "Beta = 0.456, p = 0.023"
    When sistem menjalankan tool "parse_spss_output"
    Then output harus mengekstrak nilai Beta dan p-value secara akurat
    And agen TIDAK boleh menebak atau merekayasa angka statistik
    And narasi pembahasan harus menyatakan signifikansi berdasarkan p < 0.05

  Scenario: Validasi dimensi ServQual transportasi publik
    Given peneliti mengirim data 5 dimensi ServQual
    When sistem menjalankan tool "validate_servqual_dimensions"
    Then output harus memverifikasi 5 dimensi: Tangibles, Reliability, Responsiveness, Assurance, Empathy
    And output harus mendeteksi jika ada dimensi yang hilang atau salah nama

  # ── PILAR 3: Multi-Agent Manuskrip Scopus ──────────────────────────────────

  Scenario: Orkestrasi pembuatan manuskrip IMRAD
    Given dosen mengirim data penelitian dan hasil statistik
    When orchestrator_agent mendelegasikan ke sub_agent_analyst
    Then sub_agent_analyst harus memvalidasi kesesuaian metode penelitian
    When sub_agent_analyst selesai dan hasilnya valid
    Then orchestrator_agent mendelegasikan ke sub_agent_writer
    And sub_agent_writer harus menghasilkan struktur IMRAD
    When sub_agent_writer selesai
    Then orchestrator_agent mendelegasikan ke sub_agent_reviewer
    And sub_agent_reviewer harus mengoreksi gaya bahasa akademik
    And output akhir TIDAK boleh mengandung bullet points dalam narasi

  Scenario: Blokir akses mahasiswa ke fitur Scopus
    Given pengguna dengan role "mahasiswa" mencoba mengakses "generate_scopus_manuscript"
    When Policy Server menjalankan structural check
    Then hasil validasi harus False
    And pesan error harus menyebut "Role 'mahasiswa' tidak memiliki akses"

  # ── PILAR 4: Keamanan & Context Hygiene ────────────────────────────────────

  Scenario: ContextHygiene memblokir kebocoran Project ID
    Given output agen mengandung string "gen-lang-client-0269895826"
    When ContextHygiene.sanitize() dipanggil
    Then output harus mengganti string tersebut dengan "[GOOGLE_CLOUD_PROJECT_ID]"
    And violations list harus mengandung "Google Cloud Project ID"

  Scenario: ContextHygiene memblokir kebocoran email
    Given output agen mengandung alamat email "rudymax@example.com"
    When ContextHygiene.sanitize() dipanggil
    Then output harus mengganti email dengan "[ALAMAT_EMAIL]"

  Scenario: Tolak file melebihi batas ukuran
    Given pengguna mengupload file berukuran 25 MB
    When endpoint "/upload" menerima file
    Then response harus mengembalikan HTTP 413
    And pesan error harus menyebut "terlalu besar" dan batas 20 MB
