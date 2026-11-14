# Blocked Items Requiring Human Action

## 1. Cloud Run Deployment (`gcloud` CLI not installed on this machine)

Per `SPEC.md` section 7 and overnight run rules, `gcloud` is not installed locally and no login/install was attempted. The `Dockerfile` and `scripts/deploy.sh` are built and verified locally with Docker.

When you wake up, run these three commands from a machine with `gcloud` installed and authenticated (or after `brew install --cask google-cloud-sdk && gcloud auth login`):

```bash
gcloud config set project YOUR_GCP_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
GEMINI_API_KEY="$(grep '^GEMINI_API_KEY=' .env | cut -d= -f2-)" bash scripts/deploy.sh
```
