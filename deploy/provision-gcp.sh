#!/usr/bin/env bash
#
# provision-gcp.sh — one-time, idempotent setup of the isthisbs-prod GCP
# project for keyless CI deploys to Firebase Hosting.
#
# What it creates:
#   - the GCP project (+ billing link)
#   - the required APIs
#   - Firebase on the project + a default Hosting site
#   - a deploy service account (no keys)
#   - a Workload Identity Federation pool + GitHub OIDC provider, scoped to
#     this repo, bound to the service account (so GitHub Actions authenticates
#     with a short-lived token — never a JSON key)
#
# Every step is check-then-create or `|| true` with a clear echo, so re-running
# is safe. Run once, locally, with an account that can create projects and
# manage IAM. It prints the three GitHub Actions *variables* to set at the end.
#
# DANGER: never re-run against a project whose credentials you rely on
# expecting new resources — this script only *adds*; it does not rotate.

set -euo pipefail

# Prefer an installed firebase CLI; fall back to npx (which needs npm network).
fb() {
  if command -v firebase >/dev/null 2>&1; then firebase "$@"; else fb "$@"; fi
}

# --------------------------------------------------------------------------- #
# Parameters (override via env; sensible defaults for this project)
# --------------------------------------------------------------------------- #
GCP_PROJECT="${GCP_PROJECT:-isthisbs-prod}"       # target GCP/Firebase project id
GH_REPO="${GH_REPO:-lenzhq/demo-media}"             # owner/repo allowed to deploy
BILLING_ACCOUNT="${BILLING_ACCOUNT:-}"            # REQUIRED: e.g. 0123AB-4567CD-89EF01
REGION="${REGION:-us-central1}"                   # optional; Hosting is global, kept for consistency

POOL_ID="github"                                  # WIF pool id
PROVIDER_ID="github-oidc"                         # WIF OIDC provider id
SA_ID="github-deployer"                           # deploy service account id
SA_EMAIL="${SA_ID}@${GCP_PROJECT}.iam.gserviceaccount.com"

if [[ -z "${BILLING_ACCOUNT}" ]]; then
  echo "ERROR: BILLING_ACCOUNT is required (e.g. BILLING_ACCOUNT=0123AB-4567CD-89EF01)." >&2
  echo "       Find it with: gcloud billing accounts list" >&2
  exit 1
fi

echo "==> Provisioning project '${GCP_PROJECT}' for repo '${GH_REPO}'"

# --------------------------------------------------------------------------- #
# 1. Project + billing
# --------------------------------------------------------------------------- #
if gcloud projects describe "${GCP_PROJECT}" >/dev/null 2>&1; then
  echo "[1/8] Project ${GCP_PROJECT} already exists — skipping create."
else
  echo "[1/8] Creating project ${GCP_PROJECT}..."
  gcloud projects create "${GCP_PROJECT}" --name="IsThisBS"
fi

echo "[1/8] Linking billing account ${BILLING_ACCOUNT}..."
gcloud billing projects link "${GCP_PROJECT}" \
  --billing-account="${BILLING_ACCOUNT}" || true

# Everything below targets this project by default.
gcloud config set project "${GCP_PROJECT}" >/dev/null

# --------------------------------------------------------------------------- #
# 2. Enable APIs (idempotent — enabling an enabled API is a no-op)
# --------------------------------------------------------------------------- #
echo "[2/8] Enabling required APIs..."
gcloud services enable \
  firebase.googleapis.com \
  firebasehosting.googleapis.com cloudfunctions.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com run.googleapis.com eventarc.googleapis.com \
  iamcredentials.googleapis.com \
  iam.googleapis.com \
  cloudresourcemanager.googleapis.com \
  serviceusage.googleapis.com \
  --project "${GCP_PROJECT}"

# --------------------------------------------------------------------------- #
# 3. Add Firebase + a default Hosting site
#    firebase-tools is the most reliable path for both. addfirebase is a no-op
#    if Firebase is already enabled; site create is guarded by a list check.
# --------------------------------------------------------------------------- #
echo "[3/8] Adding Firebase to the project..."
fb projects:addfirebase "${GCP_PROJECT}" || true

echo "[3/8] Ensuring a default Hosting site exists..."
if fb hosting:sites:list --project "${GCP_PROJECT}" 2>/dev/null \
    | grep -q "${GCP_PROJECT}"; then
  echo "       Hosting site already present — skipping."
else
  fb hosting:sites:create "${GCP_PROJECT}" \
    --project "${GCP_PROJECT}" || true
fi

# --------------------------------------------------------------------------- #
# 4. Deploy service account (no keys are ever created for it)
# --------------------------------------------------------------------------- #
echo "[4/8] Creating deploy service account ${SA_EMAIL}..."
if gcloud iam service-accounts describe "${SA_EMAIL}" \
    --project "${GCP_PROJECT}" >/dev/null 2>&1; then
  echo "       Service account already exists — skipping."
else
  gcloud iam service-accounts create "${SA_ID}" \
    --project "${GCP_PROJECT}" \
    --display-name="GitHub Actions Firebase deployer"
fi

# --------------------------------------------------------------------------- #
# 5. Grant the SA just what it needs to deploy Hosting
# --------------------------------------------------------------------------- #
echo "[5/8] Granting deploy roles to the service account..."
# Publish to Firebase Hosting + deploy the claimlive function (Cloud
# Functions gen2 rides Cloud Run + Cloud Build + Artifact Registry).
for _role in \
    roles/firebasehosting.admin \
    roles/cloudfunctions.admin \
    roles/run.admin \
    roles/cloudbuild.builds.editor \
    roles/artifactregistry.writer \
    roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "${GCP_PROJECT}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${_role}" \
    --condition=None >/dev/null
done
# Allow the SA to consume services (required by firebase-tools API calls).
gcloud projects add-iam-policy-binding "${GCP_PROJECT}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/serviceusage.serviceUsageConsumer" \
  --condition=None >/dev/null

# --------------------------------------------------------------------------- #
# 6. Workload Identity Federation pool
# --------------------------------------------------------------------------- #
echo "[6/8] Creating Workload Identity pool '${POOL_ID}'..."
if gcloud iam workload-identity-pools describe "${POOL_ID}" \
    --project "${GCP_PROJECT}" --location="global" >/dev/null 2>&1; then
  echo "       Pool already exists — skipping."
else
  gcloud iam workload-identity-pools create "${POOL_ID}" \
    --project "${GCP_PROJECT}" \
    --location="global" \
    --display-name="GitHub Actions"
fi

# --------------------------------------------------------------------------- #
# 7. GitHub OIDC provider, restricted to this repo
# --------------------------------------------------------------------------- #
echo "[7/8] Creating GitHub OIDC provider '${PROVIDER_ID}' (repo-scoped)..."
if gcloud iam workload-identity-pools providers describe "${PROVIDER_ID}" \
    --project "${GCP_PROJECT}" --location="global" \
    --workload-identity-pool="${POOL_ID}" >/dev/null 2>&1; then
  echo "       Provider already exists — skipping."
else
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
    --project "${GCP_PROJECT}" \
    --location="global" \
    --workload-identity-pool="${POOL_ID}" \
    --display-name="GitHub Actions OIDC" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
    --attribute-condition="assertion.repository == '${GH_REPO}'"
fi

# --------------------------------------------------------------------------- #
# 8. Let workflows from this repo impersonate the deploy SA
# --------------------------------------------------------------------------- #
PROJECT_NUMBER="$(gcloud projects describe "${GCP_PROJECT}" \
  --format='value(projectNumber)')"
POOL_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}"
PROVIDER_RESOURCE="${POOL_RESOURCE}/providers/${PROVIDER_ID}"
PRINCIPAL_SET="principalSet://iam.googleapis.com/${POOL_RESOURCE}/attribute.repository/${GH_REPO}"

echo "[8/8] Binding workloadIdentityUser for ${GH_REPO} on ${SA_EMAIL}..."
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --project "${GCP_PROJECT}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="${PRINCIPAL_SET}" >/dev/null

# --------------------------------------------------------------------------- #
# Done — print the exact GitHub Actions variables to set
# --------------------------------------------------------------------------- #
cat <<EOF

============================================================================
 Provisioning complete. Set these GitHub Actions *variables* (not secrets):
============================================================================

  gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER \\
    --repo ${GH_REPO} \\
    --body "${PROVIDER_RESOURCE}"

  gh variable set GCP_SERVICE_ACCOUNT \\
    --repo ${GH_REPO} \\
    --body "${SA_EMAIL}"

  gh variable set GCP_PROJECT \\
    --repo ${GH_REPO} \\
    --body "${GCP_PROJECT}"

Once GCP_PROJECT is set, the Build & Deploy workflow's deploy steps activate
automatically (they are guarded on \`vars.GCP_PROJECT != ''\`).
============================================================================
EOF
