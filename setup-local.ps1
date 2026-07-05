# setup-local.ps1 - RMD-TRA Local Setup (Windows · Vertex AI)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = $ScriptDir
if (-not (Test-Path "$ProjectDir\pyproject.toml")) {
    $Parent = Split-Path -Parent $ScriptDir
    if (Test-Path "$Parent\pyproject.toml") { $ProjectDir = $Parent }
    else {
        Write-Host "ERROR: jalankan dari folder rmd-tra yang berisi pyproject.toml" -ForegroundColor Red
        pause; exit 1
    }
}
Set-Location $ProjectDir
Write-Host ""
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "   RMD-TRA - Setup Lokal Windows (Vertex AI)" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Buat .env jika belum ada
Write-Host "[1/5] Memeriksa file .env..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "      .env dibuat dari .env.example" -ForegroundColor Green
    } else {
        @"
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=gen-lang-client-0269895826
GOOGLE_CLOUD_LOCATION=us-east4
PORT=8080
"@ | Out-File ".env" -Encoding utf8
        Write-Host "      .env dibuat dengan nilai default" -ForegroundColor Green
    }
} else {
    Write-Host "      .env sudah ada" -ForegroundColor Gray
}

# Step 2: Muat .env ke environment sesi
Write-Host ""
Write-Host "[2/5] Memuat .env ke sesi PowerShell..." -ForegroundColor Yellow
Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line -match "=") {
        $parts = $line -split "=", 2
        $key = $parts[0].Trim()
        $val = $parts[1].Trim().Trim('"').Trim("'")
        if ($key) {
            [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
            Write-Host "      SET $key" -ForegroundColor DarkGray
        }
    }
}

$project  = [System.Environment]::GetEnvironmentVariable("GOOGLE_CLOUD_PROJECT","Process")
$location = [System.Environment]::GetEnvironmentVariable("GOOGLE_CLOUD_LOCATION","Process")
$vertex   = [System.Environment]::GetEnvironmentVariable("GOOGLE_GENAI_USE_VERTEXAI","Process")

if (-not $project) {
    Write-Host "      GAGAL: GOOGLE_CLOUD_PROJECT kosong di .env!" -ForegroundColor Red
    pause; exit 1
}
if ($vertex -ne "true") {
    Write-Host "      GAGAL: GOOGLE_GENAI_USE_VERTEXAI harus 'true' di .env!" -ForegroundColor Red
    pause; exit 1
}
Write-Host "      Project:  $project" -ForegroundColor Green
Write-Host "      Location: $location" -ForegroundColor Green

# Step 3: Cek Application Default Credentials
Write-Host ""
Write-Host "[3/5] Memeriksa Application Default Credentials..." -ForegroundColor Yellow
$adcPaths = @(
    "$env:APPDATA\gcloud\application_default_credentials.json",
    "$env:USERPROFILE\.config\gcloud\application_default_credentials.json"
)
$adcFound = $false
foreach ($p in $adcPaths) { if (Test-Path $p) { $adcFound = $true; break } }

if ($adcFound) {
    Write-Host "      ADC ditemukan." -ForegroundColor Green
} else {
    Write-Host "      ADC belum ada. Membuka browser untuk login..." -ForegroundColor Yellow
    gcloud auth application-default login
    if ($LASTEXITCODE -ne 0) {
        Write-Host "      Login gagal. Coba manual: gcloud auth application-default login" -ForegroundColor Red
        pause; exit 1
    }
}
gcloud config set project $project --quiet

# Step 4: Aktifkan Vertex AI API
Write-Host ""
Write-Host "[4/5] Memastikan Vertex AI API aktif..." -ForegroundColor Yellow
$apiEnabled = gcloud services list --enabled --filter="name:aiplatform.googleapis.com" 2>&1
if ($apiEnabled -match "aiplatform") {
    Write-Host "      Vertex AI API sudah aktif." -ForegroundColor Green
} else {
    Write-Host "      Mengaktifkan Vertex AI API (1-2 menit)..." -ForegroundColor Yellow
    gcloud services enable aiplatform.googleapis.com --project=$project
    gcloud services enable generativelanguage.googleapis.com --project=$project
    Write-Host "      API aktif." -ForegroundColor Green
}

# Step 5: Install dependensi dan jalankan
Write-Host ""
Write-Host "[5/5] Install dependensi dan jalankan server..." -ForegroundColor Yellow
$uvExists = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvExists) {
    Write-Host "      Menginstall uv..." -ForegroundColor Yellow
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    Write-Host "      Tutup PowerShell ini, buka baru, jalankan lagi." -ForegroundColor Red
    pause; exit
}
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: uv sync gagal." -ForegroundColor Red
    pause; exit 1
}

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "  Server berjalan di http://localhost:8080" -ForegroundColor Cyan
Write-Host "  Tekan Ctrl+C untuk menghentikan" -ForegroundColor Gray
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host ""

Start-Job -ScriptBlock { Start-Sleep 3; Start-Process "http://localhost:8080" } | Out-Null
uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8080 --reload
