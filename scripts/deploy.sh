#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${VOUCH_SERVICE_NAME:-vouch}"
REGION="${VOUCH_REGION:-us-central1}"

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  if [[ -f ".env" ]]; then
    GEMINI_API_KEY="$(grep -E '^GEMINI_API_KEY=' .env | head -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
  fi
fi

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "ERROR: GEMINI_API_KEY must be set in the environment or .env" >&2
  exit 1
fi

PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: No active GCP project. Run: gcloud config set project YOUR_GCP_PROJECT_ID" >&2
  exit 1
fi

echo "Deploying ${SERVICE_NAME} to Cloud Run (project=${PROJECT_ID}, region=${REGION})..."

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com

gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --min-instances=1 \
  --max-instances=1 \
  --timeout=3600 \
  --session-affinity \
  --no-cpu-throttling \
  --cpu=1 \
  --memory=512Mi \
  --set-env-vars="GEMINI_API_KEY=${GEMINI_API_KEY},VOUCH_MOCK=0"

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --region "${REGION}" --format='value(status.url)')"
echo ""
echo "Deployed successfully!"
echo "Public URL: ${SERVICE_URL}"
echo "Demo view:  ${SERVICE_URL}/demo"
