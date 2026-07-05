@echo off
REM =============================================================================
REM deploy.bat — Script deployment RMD-TRA ke Google Cloud Run (Windows)
REM Cara pakai: Klik dua kali file ini, atau jalankan di Command Prompt
REM =============================================================================

setlocal enabledelayedexpansion

REM ── Konfigurasi ──────────────────────────────────────────────────────────────
set PROJECT_ID=gen-lang-client-0269895826
set REGION=us-east1
set SERVICE_NAME=rmd-tra
set IMAGE_NAME=gcr.io/%PROJECT_ID%/%SERVICE_NAME%:latest

echo ============================================================
echo         RMD-TRA Deployment ke Google Cloud Run
echo ============================================================
echo.
echo Project  : %PROJECT_ID%
echo Region   : %REGION%
echo Service  : %SERVICE_NAME%
echo Image    : %IMAGE_NAME%
echo.

REM ── 1. Buat file .env dari template ─────────────────────────────────────────
echo [1/5] Menyiapkan file konfigurasi .env ...
if not exist .env (
    copy .env.example .env
    echo       File .env berhasil dibuat dari .env.example
) else (
    echo       File .env sudah ada, dilewati.
)

REM ── 2. Verifikasi gcloud login ───────────────────────────────────────────────
echo.
echo [2/5] Memverifikasi autentikasi Google Cloud...
gcloud auth print-identity-token >nul 2>&1
if %errorlevel% neq 0 (
    echo       Belum login. Membuka browser untuk login...
    gcloud auth login
)
gcloud config set project %PROJECT_ID%
echo       Autentikasi OK

REM ── 3. Aktifkan API ──────────────────────────────────────────────────────────
echo.
echo [3/5] Mengaktifkan Google Cloud APIs...
gcloud services enable ^
    run.googleapis.com ^
    cloudbuild.googleapis.com ^
    artifactregistry.googleapis.com ^
    aiplatform.googleapis.com ^
    --project=%PROJECT_ID% --quiet
echo       APIs aktif

REM ── 4. Build dan push image ──────────────────────────────────────────────────
echo.
echo [4/5] Build Docker image via Cloud Build (bisa memakan 3-5 menit)...
gcloud builds submit ^
    --tag %IMAGE_NAME% ^
    --project=%PROJECT_ID% ^
    --timeout=600s
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build gagal. Periksa pesan error di atas.
    pause
    exit /b 1
)
echo       Image berhasil di-push

REM ── 5. Deploy ke Cloud Run ───────────────────────────────────────────────────
echo.
echo [5/5] Men-deploy ke Cloud Run...
gcloud run deploy %SERVICE_NAME% ^
    --image=%IMAGE_NAME% ^
    --region=%REGION% ^
    --platform=managed ^
    --allow-unauthenticated ^
    --port=8080 ^
    --memory=1Gi ^
    --cpu=1 ^
    --min-instances=0 ^
    --max-instances=5 ^
    --concurrency=10 ^
    --timeout=300 ^
    --set-env-vars="GOOGLE_CLOUD_PROJECT=%PROJECT_ID%,GOOGLE_CLOUD_LOCATION=%REGION%,GOOGLE_GENAI_USE_VERTEXAI=true" ^
    --project=%PROJECT_ID% ^
    --quiet
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Deployment gagal. Periksa pesan error di atas.
    pause
    exit /b 1
)

REM ── Tampilkan URL ─────────────────────────────────────────────────────────────
echo.
for /f "tokens=*" %%u in ('gcloud run services describe %SERVICE_NAME% --region=%REGION% --project=%PROJECT_ID% --format="value(status.url)"') do set SERVICE_URL=%%u

echo ============================================================
echo              DEPLOYMENT BERHASIL!
echo ============================================================
echo   URL Aplikasi : %SERVICE_URL%
echo   Health Check : %SERVICE_URL%/health
echo   API Info     : %SERVICE_URL%/info
echo ============================================================
echo.
echo Membuka browser...
start %SERVICE_URL%

pause
