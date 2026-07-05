# diagnose.ps1 — Periksa semua kemungkinan penyebab error sebelum menjalankan RMD-TRA
# Jalankan dari folder rmd-tra: powershell -ExecutionPolicy Bypass -File diagnose.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = $ScriptDir
if (-not (Test-Path "$ProjectDir\pyproject.toml")) {
    $Parent = Split-Path -Parent $ScriptDir
    if (Test-Path "$Parent\pyproject.toml") { $ProjectDir = $Parent }
}
Set-Location $ProjectDir

$OK   = "[OK]  "
$FAIL = "[FAIL]"
$WARN = "[WARN]"
$errors = 0

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   RMD-TRA — Diagnosis Error HTTP 500" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Cek file .env ada ────────────────────────────────────────────────────
Write-Host "[ 1 ] Memeriksa file .env ..." -ForegroundColor Yellow
if (Test-Path ".env") {
    $envContent = Get-Content ".env" -Raw
    Write-Host "$OK  File .env ditemukan." -ForegroundColor Green

    # Cek isi .env
    if ($envContent -match "GOOGLE_CLOUD_PROJECT=(.+)") {
        $proj = $Matches[1].Trim()
        if ($proj -eq "" -or $proj -match "^#") {
            Write-Host "$FAIL GOOGLE_CLOUD_PROJECT kosong di .env!" -ForegroundColor Red
            $errors++
        } else {
            Write-Host "$OK  GOOGLE_CLOUD_PROJECT = $proj" -ForegroundColor Green
        }
    } else {
        Write-Host "$FAIL GOOGLE_CLOUD_PROJECT tidak ada di .env!" -ForegroundColor Red
        Write-Host "      Tambahkan baris: GOOGLE_CLOUD_PROJECT=gen-lang-client-0269895826" -ForegroundColor Yellow
        $errors++
    }

    if ($envContent -match "GOOGLE_GENAI_USE_VERTEXAI=true") {
        Write-Host "$OK  GOOGLE_GENAI_USE_VERTEXAI=true" -ForegroundColor Green
    } else {
        Write-Host "$FAIL GOOGLE_GENAI_USE_VERTEXAI tidak diset ke 'true'!" -ForegroundColor Red
        Write-Host "      Tambahkan baris: GOOGLE_GENAI_USE_VERTEXAI=true" -ForegroundColor Yellow
        $errors++
    }
} else {
    Write-Host "$FAIL File .env tidak ditemukan!" -ForegroundColor Red
    Write-Host "      Salin dari template: copy .env.example .env" -ForegroundColor Yellow
    $errors++
}

# ── 2. Cek gcloud tersedia ──────────────────────────────────────────────────
Write-Host ""
Write-Host "[ 2 ] Memeriksa Google Cloud SDK ..." -ForegroundColor Yellow
$gcloud = Get-Command gcloud -ErrorAction SilentlyContinue
if ($gcloud) {
    $ver = gcloud --version 2>&1 | Select-Object -First 1
    Write-Host "$OK  gcloud ditemukan: $ver" -ForegroundColor Green
} else {
    Write-Host "$FAIL gcloud tidak ditemukan!" -ForegroundColor Red
    Write-Host "      Download: https://cloud.google.com/sdk/docs/install" -ForegroundColor Yellow
    $errors++
}

# ── 3. Cek status login gcloud ──────────────────────────────────────────────
Write-Host ""
Write-Host "[ 3 ] Memeriksa status login Google Cloud ..." -ForegroundColor Yellow
$authList = gcloud auth list 2>&1
if ($authList -match "ACTIVE") {
    $activeAccount = ($authList | Select-String "ACTIVE") -replace "\*", "" -replace "ACTIVE", "" 
    Write-Host "$OK  Akun aktif ditemukan." -ForegroundColor Green
} else {
    Write-Host "$FAIL Tidak ada akun Google aktif!" -ForegroundColor Red
    Write-Host "      Jalankan: gcloud auth login" -ForegroundColor Yellow
    $errors++
}

# ── 4. Cek Application Default Credentials ─────────────────────────────────
Write-Host ""
Write-Host "[ 4 ] Memeriksa Application Default Credentials (ADC) ..." -ForegroundColor Yellow
$adcPath = "$env:APPDATA\gcloud\application_default_credentials.json"
$adcPath2 = "$env:USERPROFILE\.config\gcloud\application_default_credentials.json"

if ((Test-Path $adcPath) -or (Test-Path $adcPath2)) {
    Write-Host "$OK  Application Default Credentials ditemukan." -ForegroundColor Green
} else {
    Write-Host "$FAIL Application Default Credentials TIDAK ditemukan!" -ForegroundColor Red
    Write-Host "      INI KEMUNGKINAN PENYEBAB HTTP 500 ANDA." -ForegroundColor Red
    Write-Host "      Jalankan perintah ini sekarang:" -ForegroundColor Yellow
    Write-Host "      gcloud auth application-default login" -ForegroundColor Cyan
    $errors++
}

# ── 5. Cek project ID di gcloud ─────────────────────────────────────────────
Write-Host ""
Write-Host "[ 5 ] Memeriksa project aktif di gcloud ..." -ForegroundColor Yellow
$currentProject = gcloud config get-value project 2>&1
if ($currentProject -and $currentProject -notmatch "unset") {
    Write-Host "$OK  Project aktif: $currentProject" -ForegroundColor Green
    if ($currentProject -ne "gen-lang-client-0269895826") {
        Write-Host "$WARN Project berbeda dari yang ada di .env!" -ForegroundColor Yellow
        Write-Host "      Jalankan: gcloud config set project gen-lang-client-0269895826"
    }
} else {
    Write-Host "$FAIL Tidak ada project aktif di gcloud!" -ForegroundColor Red
    Write-Host "      Jalankan: gcloud config set project gen-lang-client-0269895826" -ForegroundColor Yellow
    $errors++
}

# ── 6. Cek Vertex AI API aktif ──────────────────────────────────────────────
Write-Host ""
Write-Host "[ 6 ] Memeriksa Vertex AI API ..." -ForegroundColor Yellow
$apiStatus = gcloud services list --enabled --filter="name:aiplatform.googleapis.com" 2>&1
if ($apiStatus -match "aiplatform") {
    Write-Host "$OK  Vertex AI API sudah aktif." -ForegroundColor Green
} else {
    Write-Host "$WARN Vertex AI API mungkin belum aktif." -ForegroundColor Yellow
    Write-Host "      Aktifkan dengan: gcloud services enable aiplatform.googleapis.com" -ForegroundColor Yellow
}

# ── 7. Cek dependensi Python ────────────────────────────────────────────────
Write-Host ""
Write-Host "[ 7 ] Memeriksa dependensi Python ..." -ForegroundColor Yellow
$uvExists = Get-Command uv -ErrorAction SilentlyContinue
if ($uvExists) {
    $checkDeps = uv run python -c "import google.adk; import fastapi; import pypdf; import docx; print('OK')" 2>&1
    if ($checkDeps -match "OK") {
        Write-Host "$OK  Semua dependensi Python tersedia." -ForegroundColor Green
    } else {
        Write-Host "$FAIL Dependensi Python tidak lengkap: $checkDeps" -ForegroundColor Red
        Write-Host "      Jalankan: uv sync" -ForegroundColor Yellow
        $errors++
    }
} else {
    Write-Host "$WARN uv tidak ditemukan, tidak bisa cek dependensi." -ForegroundColor Yellow
}

# ── Ringkasan ────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
if ($errors -eq 0) {
    Write-Host "  Semua pemeriksaan LULUS. Coba jalankan server lagi:" -ForegroundColor Green
    Write-Host "  uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8080 --reload" -ForegroundColor Cyan
} else {
    Write-Host "  Ditemukan $errors masalah yang perlu diperbaiki dulu." -ForegroundColor Red
    Write-Host ""
    Write-Host "  LANGKAH PALING PENTING — jalankan ini:" -ForegroundColor Yellow
    Write-Host "  gcloud auth application-default login" -ForegroundColor Cyan
    Write-Host "  (akan membuka browser, login dengan akun Google Cloud Anda)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Setelah itu jalankan diagnose.ps1 lagi untuk verifikasi." -ForegroundColor Yellow
}
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
pause
