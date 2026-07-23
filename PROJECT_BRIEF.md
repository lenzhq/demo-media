# IsThisBS? — Project Brief & Execution Plan

> Working name **IsThisBS?** (`isthisbs.org` placeholder — configurable). An independent, public, MIT-licensed **editorial fact-check media site** built entirely on the **public Lenz API via the `lenz-io` Python SDK**. Completely standalone: separate repo (`~/Lenz-Media`, GitHub name `isthisbs`), separate domain, own brand and design. The only thing it takes from Lenz is the database of public verified claims. Also the reference implementation of "how to build something real on the Lenz API."

## Context — why this exists

Lenz is a fact-checking API (B2B). IsThisBS is a standalone media website that (1) demonstrates what you can build on the public API + Python SDK, (2) gives developers evaluating Lenz a real thing to look at and a public codebase to read, and (3) captures organic search / answer-engine traffic as a side benefit. **Demo and proof-of-capability first, traffic engine second.**

Deliberately **not** hosted on `lenz.io` or a subdomain — protects the "Lenz = fact-checking API" entity/positioning. The site links back to Lenz as attribution, acting as an external citation for the API.

**Brand synergy note:** `@isthisbs` is already Lenz's live X reply-bot. The name choice is deliberate — the site becomes the bot's home base; bot replies and site cross-pollinate under one consumer-facing brand while Lenz stays the B2B engine behind both.

## What it is

An automated fact-check publication — a small "newsroom" — where **every article is one verified claim** (verdict + reasoning + cited sources) pulled from the public Lenz catalog. Content is screened upstream by Lenz; no additional editorial/moderation layer. Built as a **static site regenerated on a schedule**: fast, near-free to host, near-zero maintenance.

**Editorial selection — show what a reader needs, not the audit trail.** Render: the claim (headline), the verdict (BS Meter), `executive_summary` as the body, cited `sources[]`, publish date, key `warnings[]` as caveats, and a "panel divided" note when `audit.panel_agreement == "split"`. **Omit** `audit.debate_pro`/`debate_con`, per-panelist `assessments[]`, raw scores — those live on lenz.io; the article links there for depth.

## Hard constraints (guardrails)

1. **Separate everything**: own repo, own domain, own brand. Nothing Lenz-branded beyond the disclosure.
2. **Distinct design** — no reuse of Lenz's design system, colors, fonts, or components.
3. **Public repo, MIT license.** Exemplary, readable code — the code is part of the demo.
4. **No secrets at all.** Reads run keyless. CI auth to GCP is Workload Identity Federation (no long-lived key). If an API key is ever added: env var only, never committed.
5. **"Powered by Lenz" disclosure + backlink** to `lenz.io` and the API docs/SDK — sitewide (header chip + footer block) and per article.
6. **Neutral fact-check tone.** Verdicts include False/Mostly False — present like a fact-check desk. Wit lives in interface labels (the frame), never in headlines or verdicts. No endorsement framing.
7. **Read-only.** Never calls verify/assess/ask (paid, write). Catalog reads only.

## Brand & design system (summary — full spec in `DESIGN.md`)

**Concept:** *the claims desk.* The reader asks "is this BS?"; the site answers with receipts. Tabloid energy in the frame, broadsheet rigor in the verdict. Tagline: **"The claims desk. Receipts included."**

- **Logo: the real `@isthisbs` X mark** (dark square, heavy white sans "BS", colored "?") — originals fetched into `static/brand/`. On-site the "?" is recolored to the caution-yellow accent (blue original kept for social parity). Masthead lockup: serif "IsThis" + the mark replicated in pure HTML/CSS (zero image bytes); favicon = SVG replica; apple-touch-icon from the yellow PNG.
- **Type: system font stacks only — zero webfont requests** (PSI guardrail). Display + body = one system serif stack (`ui-serif` / Iowan Old Style / Palatino / Georgia) at two weights; labels/kickers = system mono (`ui-monospace` / SF Mono / Menlo / Consolas). The heavy-serif/mono contrast carries the newsprint character. OG-card TTFs are still fetched into `.cache/fonts/` at build time — baked into PNGs, never loaded by pages.
- **Color — "newsprint + caution tape":** paper `#FAF7F0`, ink `#141310`, hairline `#D8D3C8`, single accent **caution yellow `#FFD23F`** (wordmark block, link underlines, selection, hover). Dark mode via CSS custom properties (`prefers-color-scheme`).
- **The signature element — the BS Meter** (the one place the brand editorializes, PolitiFact-Truth-O-Meter-style). Dual-labeled: playful BS label + canonical verdict, always both, never color-alone:

| API verdict | BS label | Color |
|---|---|---|
| True | NOT BS | `#2E7D32` |
| Mostly True | HARDLY BS | `#558B2F` |
| Mixed | SOME BS | `#B58900` |
| Mostly False | MOSTLY BS | `#C75000` |
| False | TOTAL BS | `#C62828` |

  Article rendering: a 5-stop horizontal track with a marker on the verdict's stop + `TOTAL BS — Verdict: False`. Card rendering: compact mono pill (`■ TOTAL BS`). Pure HTML/CSS, no JS. **`Error` verdicts are excluded from the site entirely** (build filter).
- **Neutrality mechanic:** a claim never appears as a bare assertion. Every headline is visually marked as *a claim under examination* — mono `THE CLAIM` kicker, quoted styling — with the verdict immediately adjacent.
- **Layout:** newspaper conventions — hairline rules, folio line (date · tagline · Powered-by-Lenz chip), dense front page with lead + rail, uppercase mono kickers, article measure ~65ch, max content width 72rem.
- **ClaimReview stays canonical:** JSON-LD `alternateName` carries the API verdict (`False`), not the BS label. BS labels are presentation-layer only.

## Information architecture & navigation

The atom: one verified claim = one article. Four axes: **sections** (primary nav), **entities** (discovery/SEO), **chronology** (news pulse), **verdict** (facet, never top-level nav).

**Masthead (all pages):** folio line (date · tagline · "Powered by Lenz" chip) → wordmark (large on home, compact sticky inner) → nav: 8 sections · Latest · About · search icon.

**Footer (all pages):** section links, collections, About, RSS, GitHub repo, full Lenz disclosure block ("Every verdict on this site is produced by Lenz, an independent fact-checking engine…" + links to lenz.io, API docs, both SDKs), MIT notice.

**Pages:**
- **`/` home** — lead check (latest); "Fresh Checks" rail (recent list); **The BS Files** strip (recent False/Mostly False); per-section blocks (top 4–6 each); **Checks Out** strip (recent True/Mostly True); "Frequently Checked" entity cloud; about-blurb band ("This entire site is a few hundred lines of Python on the Lenz API →").
- **`/[section]/`** ×8 — `health, science, politics, finance, tech, history, legal, general`. Hand-written intro blurb (in `config.py`), feed at 20/page (`/[section]/page/N/`), client-side verdict filter chips (progressive enhancement over `data-verdict`; no-JS = unfiltered list).
- **`/[section]/[slug]/`** — **the article** (core unit). Breadcrumb (Home › Section); mono kicker `SECTION · date`; `THE CLAIM` label + H1 (the claim, quoted styling); BS Meter + `Verified by Lenz · {created_at}`; `THE SHORT VERSION` (executive_summary as body); `CAVEATS` (warnings[]); "panel divided" note when split; `THE RECEIPTS` (sources[] — title, source_name, date, external link); `MORE CHECKS` (related, from cache); attribution box → `https://lenz.io/c/{verification_id}` ("Read the full analysis on Lenz →"); ClaimReview + NewsArticle JSON-LD.
- **`/topic/[entity]/`** — entity hubs (name, claim count, feed). **Only entities with ≥2 claims get pages** (no thin content); below threshold, names render unlinked. `qid` → `sameAs` (Wikidata) in JSON-LD.
- **`/latest/`** — reverse-chron, all sections, paginated.
- **`/bs-files/`**, **`/checks-out/`** — curated collections (~40 each), computed locally from verdicts (no extra API calls).
- **`/search/`** — Pagefind UI (lazy-loaded assets).
- **`/about/`** — what IsThisBS is; methodology (how Lenz verifies: multiple frontier models independently research and assess each claim against fresh sources; disagreements surfaced); the disclosure; the developer pitch (repo, API docs, SDK links); contact = GitHub issues.
- **`404.html`** — "This page is BS — it doesn't exist." (wit allowed in interface).
- **Plumbing:** `robots.txt` (allow all incl. AI crawlers, sitemap pointers), `sitemap.xml` (index → articles/sections/topics children) + Google-News-style sitemap (recent), Atom feeds (site `/feed.xml` latest 50 + per-section latest 30), `llms.txt` (curated site map for AI engines) + `llms-full.txt` (flat claim+verdict+summary index), OG images `/og/{verification_id}.png` (1200×630, claim + BS Meter in brand style, Pillow-generated).

**English-only v1**: build filters `language == "en"` (configurable `BUILD_LANGS`). Mixed-language nav is bad UX; i18n later.

## Data source — the `lenz-io` Python SDK

- `pip install lenz-io` (≥2.3.0, Python ≥3.9). `Lenz(api_key=..., base_url=...)`; base URL default `https://lenz.io/api/v1`, override via `LENZ_BASE_URL`. **All reads keyless.**
- Read surface used:
  - `client.library.list(*, page=1, sort="recent", search="", domain="", entity="") -> LibraryList` — public catalog. Fixed `page_size=20`; read `total` to compute pages. Sorts: `recent`, `popular`, `most_true`, `most_untrue` (+`relevance` w/ search).
  - `client.verifications.get(verification_id) -> Verification` — full detail **including `sources[]`** (list items have no sources → detail fetch per claim, mitigated by cache).
  - `client.verifications.related(verification_id, *, limit=5)` — server caps 10; items include real `url`.
- Fields — list item: `verification_id, claim, domain, entities[{name,qid}], verdict, confidence, lenz_score, executive_summary, created_at, modified_at, language`. Detail adds: `presumed_intent, warnings[], sources[{source_name,title,url,snippet,date}], audit{adjudication_summary, assessments[], debate_pro, debate_con, panel_agreement}`.
- **Not available (design around):** no slug, no country, no verdict/date filter, no sources on list items, no URL on list items. Verdict enum: `True | Mostly True | Mixed | Mostly False | False | Error`; `lenz_score` int 1–10.
- **Keyless reality (verified live 2026-07-23):** `library.list` and `verifications.get` are keyless; **`related` requires an API key** (401 anonymously). The build fetches related best-effort (stores `[]` on failure) and renders "MORE CHECKS" from a local entity-overlap fallback when absent. Candidate Lenz-side extension (broadly useful, keeps keyless): make `related` public-read like detail.
- **`confidence` is coarse (effectively always high) — never feature it.** Real uncertainty signal = `audit.panel_agreement` (`unanimous|majority|split`); surface `split` as the "panel divided" note.
- SDK raises typed exceptions (`LenzRateLimitError.retry_after`, etc.) and auto-retries 5xx/429. Build catches per-claim errors, logs, skips, continues.

## Extending the API / SDK (allowed, with a principle)

**Only additions that are legitimate improvements for all public-API callers — no demo-only crutches.** Candidates in value order: incremental catalog feed (`GET /library?modified_since=<iso>`, unauthenticated — the expected first extension), sources/sources_count on list items, verdict/date filters on `/library`. Any extension ships with tests, keeps SDK models forward-compatible, propagates to BOTH SDKs (`lenz-io-python` + `lenz-io-node`), and stays keyless public-read. Server work lives in the Lenz repo — out of scope for this repo.

## Architecture — build-time static generation

Fetch at build time via the SDK → generate static HTML → deploy `dist/`. No server, no per-visitor API calls.

- **Stack (settled):** Python ≥3.11, `build.py` CLI + `isthisbs/` package, Jinja2 templates, plain CSS (own design system), Pillow for OG cards, Pagefind for client-side search (`pagefind[extended]` pip wheel; graceful skip if unavailable). Minimal deps, maximally legible.
- **Incremental fetch/cache:** `.cache/claims/{verification_id}.json` (detail + related + fetched_at) with `.cache/manifest.json` (id → modified_at). Each build walks the library list (cheap, 20/page), fetches detail+related **only for new/changed ids**, and drops ids no longer present in the walk. OG images cached in `.cache/og/` keyed by id+content-hash, copied to `dist/og/`. CI persists `.cache/` via actions/cache.
- **Clean URLs as directories:** every page is `path/index.html` — works on Firebase, `python -m http.server`, any host.
- **Hosting (settled): Firebase Hosting** on GCP — free tier, global CDN, custom domain + SSL, one-command deploy. In a **separate GCP project (`isthisbs-prod`)** — real independence, clean billing. Alternatives rejected: GCS+LB+CDN (~$18+/mo fixed for a demo), Cloud Run+nginx (container ceremony, no CDN).
- **Scheduled rebuild: GitHub Actions** — daily cron + `workflow_dispatch` + push-to-main. Auth to GCP via **Workload Identity Federation** (repo stays secret-free). `firebase deploy --only hosting` via ADC.
- **Slug minting** (API has no slug): `slugify(claim)[:60] + "-" + verification_id` — stable, unique. Entity slugs: `slugify(name)` (+qid disambiguation on collision).

## Future: interactivity layer (no DB today — deliberate)

v1 has **no database**: content truth lives in the Lenz catalog; `.cache/` is a flat-file build cache. When interactive features land (comments, challenges, votes), the settled growth path is **Firestore + Firebase Auth (+ Cloud Functions if needed) in the same `isthisbs-prod` project**: votes = per-claim counter docs with per-uid dedup, comments = per-claim collection behind moderation, "challenge this verdict" = a submissions collection (candidate future loop: feed challenges back into Lenz re-verification). Pages stay static; interactivity ships as lazy-loaded JS islands talking to Firestore from the browser under security rules — still serverless, still secret-free. Guardrails: Firebase SDK loads on first interaction only (PSI budget), comments imply a moderation policy decision before launch. Escape hatch if outgrown: Cloud Run + Cloud SQL (accepting the ops bill).

## Repo layout & module contracts

```
~/Lenz-Media (repo: isthisbs)
├── PROJECT_BRIEF.md            # this document (mirror)
├── DESIGN.md                   # full design system spec
├── README.md                   # doubles as the lenz-io SDK walkthrough
├── LICENSE                     # MIT
├── pyproject.toml              # deps: lenz-io, jinja2, pillow, python-slugify; [search] pagefind[extended]; [dev] pytest, ruff
├── Makefile                    # install / build / serve / test / lint / deploy / clean
├── build.py                    # thin CLI (argparse): --max-pages --skip-fetch --skip-og --skip-search --out
├── isthisbs/
│   ├── config.py               # SITE (name/base_url/tagline), SECTIONS (8, key→title+blurb), VERDICTS (map above), LANGS
│   ├── content.py              # Check/Source/Entity dataclasses; slug minting; build_checks(raw)→[Check] (filter Error/langs, sort);
│   │                           #   group_by_section / group_by_entity(min_count=2) / collections() / latest()
│   ├── fetch.py                # sync(client, cache_dir, max_pages=None)→SyncStats; load_raw(cache_dir)→[dict]
│   ├── render.py               # render_site(checks, groups, out_dir) — all HTML pages via Jinja
│   ├── seo.py                  # JSON-LD builders (ClaimReview, NewsArticle, Breadcrumb, ItemList, Organization, WebSite);
│   │                           #   write_assets(...): sitemaps (+news), Atom feeds, robots.txt, llms.txt, llms-full.txt
│   ├── ogimage.py              # generate(checks, cache_dir, out_dir) — 1200×630 PNG cards, font auto-fetch, hash-cached
│   ├── templates/              # base, home, section, article, topic, latest, collection, search, about, 404 + partials + xml
│   └── static/                 # css/site.css, js/filter.js, logo.svg, favicon.svg
├── tests/                      # offline pytest suite w/ fake SDK fixtures (see Testing)
├── firebase.json / .firebaserc # hosting config at repo root (firebase-tools resolves from root)
├── deploy/
│   ├── provision-gcp.sh        # one-time: project, Firebase, WIF pool + SA for GH Actions; prints GH vars
│   └── deploy.sh               # manual local deploy (build + firebase deploy)
└── .github/workflows/
    ├── ci.yml                  # PR/push: ruff + pytest (offline)
    └── build-deploy.yml        # cron daily + dispatch + push→main: fetch/build (keyless), pagefind, WIF auth, firebase deploy
```

## Testing

Fully offline pytest suite (fake SDK objects/fixture dicts — never hits the network):
- `test_content.py` — slug stability (incl. unicode/long claims), verdict map completeness, Error exclusion, language filter, entity ≥2 threshold, collections split, sort orders.
- `test_fetch.py` — cache decisions with a fake client: new id fetched, unchanged skipped, changed modified_at refetched, disappeared id dropped, per-claim error skips + continues.
- `test_seo.py` — ClaimReview field mapping (ratingValue=lenz_score, best 10/worst 1, alternateName=canonical verdict), sitemap URL sets, valid Atom XML, llms.txt content.
- `test_render.py` — render home/section/article/topic from fixtures: exactly one `<h1>`, disclosure present, canonical link, BS pill correct for all 5 verdicts, split note renders, debate/panelist internals absent.
- `test_ogimage.py` — emits 1200×630 PNG; deterministic cache key.
CI runs ruff + pytest on every PR/push. Real-fetch smoke (`--max-pages 2`) is a manual/deploy-time check, not PR CI.

## Execution process (step-by-step, with agents)

Orchestrated from a Claude Code session; bulk file production fans out to **opus subagents** with the contract docs (this file + `DESIGN.md` + `config.py`/`content.py`) as their spec. Steps:

1. **Contracts (main session):** update this plan; write `DESIGN.md`; write `isthisbs/config.py` + `content.py` (+ `__init__.py`) by hand — every agent codes against these.
2. **Fan-out (4 parallel opus agents, disjoint files):**
   - **Agent A — data layer:** `fetch.py` + `build.py` (CLI orchestration calling the module contracts).
   - **Agent B — design implementation:** `render.py` + all `templates/` + `static/` per DESIGN.md.
   - **Agent C — SEO/AEO:** `seo.py` + `ogimage.py`.
   - **Agent D — infra:** `pyproject.toml`, `Makefile`, `README.md`, `LICENSE`, `.gitignore`, both workflows, `deploy/` (Firebase + WIF provisioning).
3. **Tests (opus agent E, after A–C):** writes the offline suite against the real code + contracts.
4. **Integration (main session):** install, `ruff check`, `pytest`; fix drift between modules; run a real keyless smoke build (`python build.py --max-pages 2`), inspect `dist/` output; local `make serve` sanity pass.
5. **Commit** scaffold on `main` (no push until asked).
6. **Reviews (in sequence):** `/plan-ceo-review` → `/plan-design-review` → `/codex` review → `/plan-eng-review`; triage findings, apply accepted fixes.
7. **Later (Pavel):** create `isthisbs-prod` GCP project + run `deploy/provision-gcp.sh`, create GitHub repo + push, set WIF vars, first deploy, domain purchase/DNS.

## Decisions (settled — don't re-litigate)

1. **Name:** IsThisBS? — deliberately shared with the `@isthisbs` X bot; consumer brand for both, Lenz stays the B2B engine.
2. **BS Meter dual-labeling** — playful BS scale in the UI, canonical verdict everywhere that's machine-read (ClaimReview `alternateName`) and beside every BS label on-page.
3. **Stack** — Python + Jinja2 static build on `lenz-io`; own CSS; Pagefind; Pillow OG cards. Reference implementation of the Python SDK.
4. **Hosting** — Firebase Hosting, separate `isthisbs-prod` GCP project, GH Actions + WIF, daily rebuild.
5. **Article depth** — media + light context (claim, meter, summary, sources, warnings, split note); omit debates/panelist internals; link to lenz.io for depth.
6. **ClaimReview** — site emits its own (author = Lenz, publisher = IsThisBS); accept cross-domain duplication with lenz.io; AEO priority.
7. **English-only v1**; `Error` verdicts excluded; entity pages need ≥2 claims; keyless forever on reads.
8. **API/SDK extensions** only where broadly useful to all callers; both SDKs at parity; keyless public-read; out of this repo's scope.

## Verification / acceptance criteria

- `python build.py` runs clean from a fresh checkout **with no credentials**, emits `dist/` with home, 8 section hubs, entity pages (≥2 threshold), articles, latest, both collections, search, about, 404, OG images, Atom feeds, `sitemap.xml` + news sitemap, `robots.txt`, `llms.txt`, `llms-full.txt`.
- Incremental cache: second build refetches only changed/new claims; pagination covers the full catalog.
- An article validates in Google's Rich Results Test (ClaimReview) + schema.org validator; exactly one `<h1>` per page; Lighthouse SEO ≥ 95.
- BS Meter renders correctly for all 5 verdicts (label + canonical verdict text, accessible without color); `split` shows the divided note; no debate/panelist internals anywhere.
- Powered-by-Lenz disclosure + backlink sitewide and per article; every article links to `lenz.io/c/{verification_id}`.
- Zero secrets in repo or CI (WIF only); `pytest` green offline; ruff clean; scheduled Action builds and deploys.
- Design is visibly distinct from lenz.io; headlines stay neutral; wit confined to interface labels.
