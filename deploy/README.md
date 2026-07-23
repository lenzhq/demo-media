# Deploying IsThisBS

Everything deploys from GitHub Actions (`.github/workflows/build-deploy.yml`)
— daily cron + every push to `main` — using keyless Workload Identity
Federation. No JSON keys, no secrets in the repo.

## One-time provisioning

```bash
BILLING_ACCOUNT=<your-billing-account-id> bash deploy/provision-gcp.sh
```

Creates the GCP project, links billing (this is also the Firebase Blaze
prerequisite for the `claimlive` function), enables APIs, adds Firebase +
a Hosting site, creates the deploy service account, and configures a WIF
pool scoped to exactly this repo. It ends by printing the three
`gh variable set` commands to run.

Prerequisites: `gcloud` (authenticated with project-create rights) and
either a `firebase` CLI on PATH or working `npx`.

## Manual deploy (rarely needed)

```bash
bash deploy/deploy.sh   # build + firebase deploy --only hosting,functions
```

Note: `functions/` is deployed self-contained — the script syncs the
`isthisbs/` package into it and builds `functions/venv` (the firebase CLI
discovers Python functions through that venv).

## Post-deploy verification

```bash
make smoke-live         # redirect matrix, catalog coverage, SEO assets, /c/ function
```

CI runs the same script automatically after every deploy.
