#!/usr/bin/env bash
#
# deploy.sh — manual local deploy to Firebase Hosting.
#
# Builds the site, then publishes dist/ with firebase-tools using your local
# Application Default Credentials. CI uses Workload Identity Federation instead
# (see .github/workflows/build-deploy.yml); this is the human escape hatch.
#
# Usage:  bash deploy/deploy.sh
#         GCP_PROJECT=my-project bash deploy/deploy.sh

set -euo pipefail

# Prefer an installed firebase CLI; fall back to npx (which needs npm network).
fb() {
  if command -v firebase >/dev/null 2>&1; then firebase "$@"; else fb "$@"; fi
}

GCP_PROJECT="${GCP_PROJECT:-isthisbs-prod}"

echo "==> Preflight checks"

# Required tooling.
for cmd in python3 npx; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: '${cmd}' not found on PATH." >&2
    exit 1
  fi
done

# Verify local Application Default Credentials are usable.
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  echo "ERROR: no working Application Default Credentials." >&2
  echo "       Run: gcloud auth application-default login" >&2
  exit 1
fi

echo "==> Building site (keyless)"
make build

echo "==> Deploying to Firebase Hosting (project: ${GCP_PROJECT})"
# The functions bundle must be self-contained: sync the package in.
rm -rf functions/isthisbs
cp -R isthisbs functions/isthisbs
find functions/isthisbs -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
fb deploy \
  --only hosting \
  --project "${GCP_PROJECT}" \
  --non-interactive

echo "==> Deploy complete."
