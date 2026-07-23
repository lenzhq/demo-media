# IsThisBS?

**The claims desk. Receipts included.**

IsThisBS? is an automated fact-check publication. Every article is a single
claim — with a verdict, a plain-language summary, and the sources to back it
up. It's a static website regenerated on a schedule from the public
[Lenz](https://lenz.io) catalog. **Every verdict on this site is produced by
Lenz**, an independent fact-checking engine; this repo is just the newsroom
that renders them.

- Live site: **https://isthisbs.org** *(pending launch)*
- Powered by the Lenz public API via the [`lenz-io`](https://pypi.org/project/lenz-io/) Python SDK
- Public, MIT-licensed, and secret-free — it doubles as the **reference
  implementation** for building on the Lenz API.

---

## Quickstart

No credentials. No API key. The Lenz catalog is read keyless.

```bash
git clone https://github.com/lenzhq/demo-media.git
cd demo-media   # repo name; the product/package is `isthisbs`
make install     # pip install -e ".[dev,search]"
make smoke       # fast 2-page keyless build into dist/
make serve       # http://localhost:8080
```

`make smoke` builds a couple of pages so you can see the pipeline end-to-end in
seconds. `make build` does the full catalog. That's the whole loop.

---

## How it works

Build-time static generation: fetch once, render to `dist/`, deploy the folder.
No server, no per-visitor API calls.

```
Lenz API ──▶ fetch (incremental cache) ──▶ Check model ──▶ Jinja render ──▶ dist/
                                                    │
                                       SEO assets · OG cards · Pagefind
```

- **Fetch** — [`isthisbs/fetch.py`](isthisbs/fetch.py) walks the public library
  via the SDK and pulls detail + related claims **only for new or changed
  ids**, caching each to `.cache/claims/`. Second builds are nearly free.
- **Model** — [`isthisbs/content.py`](isthisbs/content.py) turns raw API dicts
  into `Check` / `Source` / `Entity` dataclasses: filters `Error` verdicts and
  non-build languages, mints stable slugs, groups by section and entity.
- **Render** — [`isthisbs/render.py`](isthisbs/render.py) +
  [`isthisbs/templates/`](isthisbs/templates/) emit every page (home, 8
  sections, articles, entity hubs, collections, search, about, 404) with the
  design system in [`isthisbs/static/`](isthisbs/static/).
- **SEO/AEO** — [`isthisbs/seo.py`](isthisbs/seo.py) writes ClaimReview +
  NewsArticle JSON-LD, sitemaps (incl. news), Atom feeds, `robots.txt`,
  `llms.txt` / `llms-full.txt`.
- **OG cards** — [`isthisbs/ogimage.py`](isthisbs/ogimage.py) renders
  1200×630 PNG social cards with Pillow, hash-cached.
- **Search** — [Pagefind](https://pagefind.app/) indexes `dist/` after render
  for client-side search; skipped gracefully when unavailable.

The whole thing is a few thousand lines of small, legible Python. That's the point.

---

## The SDK in action

Everything the site knows comes from three read-only SDK calls. The client is
keyless — the base URL defaults to `https://lenz.io/api/v1` and is
overridable with `LENZ_BASE_URL`.

```python
from lenz_io import Lenz

client = Lenz()  # no api_key — public catalog reads are keyless

# 1. Walk the public catalog (20 per page; read `total` to paginate).
page = client.library.list(page=1, sort="recent")
for item in page.items:
    print(item.verdict, "—", item.claim)

# 2. Fetch full detail for one claim — this is where sources[] live.
detail = client.verifications.get(item.verification_id)
print(detail.executive_summary)
for src in detail.sources:
    print(f"  · {src.source_name}: {src.title} ({src.url})")

# 3. Pull related claims to build the "More checks" rail.
related = client.verifications.related(item.verification_id, limit=5)
for r in related.items:
    print("related:", r.claim)
```

> Note: `related` currently requires an API key — the build treats it as
> best-effort and falls back to local entity overlap for "More Fact Checks".


That's the entire data layer. See [`isthisbs/fetch.py`](isthisbs/fetch.py) for
the cached, error-tolerant version.

- SDK on PyPI: <https://pypi.org/project/lenz-io/>
- Lenz API docs: <https://lenz.io/developers>

---

## Configuration

Everything is environment-overridable; sensible defaults ship in
[`isthisbs/config.py`](isthisbs/config.py).

| Setting | Env var | Default | Purpose |
|---|---|---|---|
| Google Analytics | `GA_MEASUREMENT_ID` | *(unset — no analytics)* | GA4 id (e.g. `G-XXXX`); when unset the site ships zero analytics markup |
| Site base URL | `SITE_BASE_URL` | `https://isthisbs.org` | Canonical URLs, sitemaps, OG tags |
| Lenz API base | `LENZ_BASE_URL` | `https://lenz.io/api/v1` | Where the SDK reads the catalog |
| Build languages | `BUILD_LANGS` | `en` | Comma-separated language filter (`en,de`) |

Build flags (`python build.py …`):

| Flag | Effect |
|---|---|
| `--max-pages N` | Cap catalog pages fetched (fast partial builds) |
| `--skip-fetch` | Render from the existing `.cache/` only (offline) |
| `--skip-og` | Skip OG-image generation |
| `--skip-search` | Skip the Pagefind index |
| `--out DIR` | Output directory (default `dist/`) |

---

## Deploy

After any deploy, `make smoke-live` verifies the live site end to end
(redirect matrix, catalog coverage, SEO assets, the `/c/` function).

### Details

Hosting is **Firebase Hosting** in a dedicated GCP project (`isthisbs-prod`).
CI deploys from GitHub Actions via **Workload Identity Federation** — no JSON
key, no long-lived secret. The workflow authenticates with a short-lived OIDC
token exchanged for a service account, then runs `firebase deploy`.

- Scheduled + on-push builds: [`.github/workflows/build-deploy.yml`](.github/workflows/build-deploy.yml)
- One-time GCP + WIF provisioning: [`deploy/provision-gcp.sh`](deploy/provision-gcp.sh)
- Manual local deploy: `make deploy` → [`deploy/deploy.sh`](deploy/deploy.sh)

Full setup lives in [`deploy/`](deploy/).

---

## Contributing

Issues and PRs welcome. This is a public reference implementation — clarity is a
feature. Run `make lint` and `make test` before opening a PR; both run offline.
Licensed under the [MIT License](LICENSE).

---

## Powered by Lenz

Every verdict on this site is produced by **Lenz**, an independent
fact-checking engine that has multiple frontier AI models independently
research and assess each claim against fresh, cited sources. IsThisBS? adds no
editorial layer of its own — it renders what Lenz publishes and links back to
the full analysis for every claim.

- Lenz: <https://lenz.io>
- API docs: <https://lenz.io/developers>
- SDKs: [Python](https://pypi.org/project/lenz-io/) · [Node](https://www.npmjs.com/package/lenz-io)
