#!/bin/bash
# =============================================================================
# deploy.sh — Script deployment RMD-TRA ke Google Cloud Run
# Jalankan: chmod +x deploy.sh && ./deploy.sh
# =============================================================================

set -e  # Hentikan jika ada error

# ── Konfigurasi (sesuaikan jika perlu) ──────────────────────────────────────
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-gen-lang-client-0269895826}"
REGION="${GOOGLE_CLOUD_REGION:-us-east1}"
SERVICE_NAME="rmd-tra"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║         RMD-TRA Deployment ke Google Cloud Run          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Project  : ${PROJECT_ID}"
echo "Region   : ${REGION}"
echo "Service  : ${SERVICE_NAME}"
echo "Image    : ${IMAGE_NAME}"
echo ""

# ── 1. Pastikan gcloud sudah login ──────────────────────────────────────────
echo "▶ [1/5] Memverifikasi autentikasi Google Cloud..."
gcloud auth print-identity-token > /dev/null 2>&1 || {
    echo "⚠  Belum login. Menjalankan: gcloud auth login"
    gcloud auth login
}
gcloud config set project "${PROJECT_ID}"
echo "✓ Autentikasi OK"

# ── 2. Aktifkan API yang dibutuhkan ─────────────────────────────────────────
echo ""
echo "▶ [2/5] Mengaktifkan Google Cloud APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    aiplatform.googleapis.com \
    --project="${PROJECT_ID}" --quiet
echo "✓ APIs aktif"

# ── 3. Build dan push Docker image ──────────────────────────────────────────
echo ""
echo "▶ [3/5] Build dan push Docker image ke GCR..."
gcloud builds submit \
    --tag "${IMAGE_NAME}" \
    --project="${PROJECT_ID}" \
    --timeout=600s
echo "✓ Image berhasil di-push: ${IMAGE_NAME}"

# ── 4. Deploy ke Cloud Run ───────────────────────────────────────────────────
echo ""
echo "▶ [4/5] Men-deploy ke Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_NAME}" \
    --region="${REGION}" \
    --platform=managed \
    --allow-unauthenticated \
    --port=8080 \
    --memory=1Gi \
    --cpu=1 \
    --min-instances=0 \
    --max-instances=5 \
    --concurrency=10 \
    --timeout=1200 \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=true" \
    --project="${PROJECT_ID}" \
    --quiet
echo "✓ Deployment selesai"

# ── 5. Tampilkan URL layanan ─────────────────────────────────────────────────
echo ""
echo "▶ [5/5] Mengambil URL layanan..."
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format="value(status.url)")

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║              ✅ DEPLOYMENT BERHASIL!                    ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  URL Aplikasi : ${SERVICE_URL}"
echo "║  Health Check : ${SERVICE_URL}/health"
echo "║  API Info     : ${SERVICE_URL}/info"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Buka browser dan kunjungi: ${SERVICE_URL}"
