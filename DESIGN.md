# IsThisBS? — Design System

The complete visual spec. `isthisbs/static/css/site.css` implements these tokens; templates implement the components. Nothing here is inherited from lenz.io — this is an independent editorial brand.

## 1. Brand

- **Name:** IsThisBS? (wordmark includes the `?`). Short form `IsThisBS` for meta/social.
- **Concept:** *the claims desk.* Tabloid energy in the frame, broadsheet rigor in the verdict.
- **Tagline:** "The claims desk. Receipts included."
- **The mark (from the real `@isthisbs` X account** — originals in `static/brand/`): a near-black rounded square, heavy white geometric-sans `BS`, colored `?`. On X the `?` is blue; **on-site the `?` is caution yellow** (`avatar-yellow.png` — same geometry, accent-matched; the blue original stays for social parity).
- **Wordmark lockup:** `IsThis` in the display serif (weight 800, ink) + **the mark replicated in pure HTML/CSS** inline — dark square chip (`#171717`, both themes), `BS` white + `?` yellow in a heavy system sans (`-apple-system, 'Helvetica Neue', 'Segoe UI', Arial`). Reads "IsThis[BS?]" — zero image bytes, crisp at any size. The sans mark / serif voice contrast is intentional (mark matches X; the publication speaks serif).
- **Favicon** (`static/favicon.svg`): SVG replica of the mark (dark rounded square, white BS, yellow ?). `apple-touch-icon.png` (180px) linked in head.
- **Voice rules:** headlines are the **key findings** — the one-sentence fact each check established, asserted plainly (truth-first, never the myth). The checked claim renders as a quoted exhibit beside its verdict, never as a bare assertion. Wit is confined to interface labels (BS Files, Receipts, the 404). Verdict language is always dual: BS label + canonical verdict.
- **The two headline invariants** (every surface, every medium):
  1. *The verdict never appears without the claim adjacent to it.* The verdict rates the claim; next to a finding it would read as rating the finding. Adjacent = same DOM container with the claim preceding the verdict in source order (HTML), same line or the line above (plain text), same node (JSON-LD — `claimReviewed` sits beside `reviewBody`).
  2. *The executive summary never appears without the claim above it* ("the claim…" needs its antecedent). Only the key finding stands alone. Checks without a `key_finding` **never publish** (build gate) — the only fallback surface is the live `/c/` page, which quotes the claim under a `THE CLAIM` kicker.

## 2. Typography — system fonts only

**Zero webfonts, zero font requests** (PSI/LCP: fonts are the classic regression; system faces render instantly with no CLS). Two stacks, defined once as tokens:

```
--font-serif: ui-serif, 'Iowan Old Style', 'Palatino Linotype', Palatino,
              Georgia, 'Times New Roman', serif;
--font-mono:  ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas,
              'DejaVu Sans Mono', monospace;
```

| Role | Stack | Treatment |
|---|---|---|
| Display | `--font-serif` | weight 800, letter-spacing -0.015em — wordmark, H1s, card headlines |
| Body | `--font-serif` | weight 400 (600/700 for emphasis) — article body, standfirsts, blurbs |
| Label | `--font-mono` | kickers, verdict labels, metadata, dates, breadcrumbs, buttons, folio |

One serif family at two weights + a mono for labels: the heavy-serif/mono contrast carries the newsprint character on its own.

**Scale** (rem; fluid where noted):
- `--fs-hero`: clamp(2.25rem, 5.5vw, 3.5rem) — article H1, home lead headline. Serif 800, lh 1.08.
- `--fs-h2`: 1.5rem — block headings. Serif 700.
- `--fs-card`: clamp(1.125rem, 2vw, 1.375rem) — card headlines. Serif 700, lh 1.25.
- `--fs-body`: 1.0625rem / lh 1.7 — serif 400.
- `--fs-standfirst`: 1.25rem / lh 1.5, serif 600.
- `--fs-meta`: 0.8125rem — mono metadata.
- `--fs-label`: 0.6875rem, UPPERCASE, letter-spacing 0.08em — mono kickers/labels.

Mono labels are always uppercase with tracked spacing — this is the strongest recurring texture of the brand.

## 3. Color tokens

Light ("newsprint"):
```
--paper:    #FAF7F0   /* page background */
--ink:      #141310   /* text */
--ink-60:   #5C574C   /* secondary text */
--hairline: #D8D3C8   /* rules, borders */
--accent:   #FFD23F   /* caution yellow — the only brand accent */
--card:     #FFFFFF   /* optional raised surfaces (use sparingly) */
```
**Light-only by design.** Like a printed newspaper (and like nytimes.com,
theguardian.com, ft.com), the site renders on paper white regardless of the
OS theme — `color-scheme: light` pins UA form controls to match. No dark
palette, no theme switcher: one surface to design, QA, and keep honest.

**Verdict tokens** — two variants each: `fill` (vivid; meter marker, pill square, OG blocks — graphic use) and `text` (AA ≥4.5:1 on paper for label text).

| Verdict | class | fill | text |
|---|---|---|---|
| True / NOT BS | `v-not-bs` | `#2E7D32` | `#1E6B24` |
| Mostly True / HARDLY BS | `v-hardly-bs` | `#558B2F` | `#41701F` |
| Mixed / SOME BS | `v-some-bs` | `#B58900` | `#7A5D00` |
| Mostly False / MOSTLY BS | `v-mostly-bs` | `#C75000` | `#9C3F00` |
| False / TOTAL BS | `v-total-bs` | `#C62828` | `#B3261E` |

Color is never the sole carrier — the label text is always present.

**Links:** ink text, 2px yellow underline (`text-decoration-color: var(--accent)`, offset 3px); hover: yellow background, ink text. `::selection`: yellow bg / ink. Focus: `:focus-visible` 2px solid yellow outline, 2px offset.

## 4. The BS Meter (signature component)

**Article size** (`.meter`): a horizontal track of 5 square stops (10px, hairline-bordered, 8px gaps, connected by a hairline). The verdict's stop is filled with its `fill` color and scaled 1.7×. Track ends carry tiny mono labels `NOT BS` (left) and `TOTAL BS` (right). Below the track: `TOTAL BS` in mono 700 1rem in the verdict `text` color, followed by ` — Verdict: False` in mono `--ink-60`. Wrapper: `role="img" aria-label="BS meter: Total BS. Verdict: False."` with `aria-hidden` on the decorative track. Pure HTML/CSS.

**Card size** (`.bs-pill`): inline-flex pill — 8px verdict-colored square + BS label in mono 600 `--fs-label` in verdict `text` color; 1px hairline border, 2px 8px padding, radius 3px.

Squares, not circles, everywhere (echoes the wordmark block).

## 5. Layout & components

- **Grid:** max-width 72rem, 24px gutters; article measure 42rem centered. Base spacing unit 4px (use 8/12/16/24/32/48/64).
- **Rules:** 1px hairlines separate every major band; the masthead bottom rule is 3px ink (the "fold line").
- **Folio line** (very top, mono `--fs-label`): weekday+date (build date) · tagline (hidden on mobile) · right: `POWERED BY LENZ ↗` chip (hairline border pill → lenz.io, `rel="noopener"`).
- **Masthead:** centered wordmark — styled HTML text (home: large ~64px; inner pages: ~36px, left-aligned in a compact sticky bar with nav inline). Below: nav row — mono labels: 8 sections · LATEST · ABOUT · SEARCH (icon+label). Active page: yellow underline + `aria-current="page"`. Mobile: horizontal scroll nav (no hamburger).
- **Card** (`.check-card`): top hairline; kicker row (mono: SECTION · date); headline = the key finding (display serif, link); **claim line** (`.check-card__claim`, mono `--fs-meta` in `--ink-60`): uppercase `CLAIM:` label + quoted claim (~80 chars, truncated) + `.bs-pill` inline at line end — the pill never sits alone under the finding. Variant: `--row` (rails/feeds: same anatomy, tighter).
- **Pagination** (mono): `← NEWER · PAGE 2 OF 14 · OLDER →` as links; current page plain text.
- **Filter chips** (section hubs): row of `.bs-pill`-styled buttons: ALL · NOT BS · HARDLY BS · SOME BS · MOSTLY BS · TOTAL BS. JS toggles `hidden` on `[data-verdict]` items; `aria-pressed`; no-JS default = ALL (chips enabled by JS).
- **Attribution box** (article footer, hairline border, yellow left rule 3px): "This check was produced by **Lenz**, an independent fact-checking engine. IsThisBS presents the results." + `READ THE FULL ANALYSIS ON LENZ ↗` and `Fact check any claim yourself ↗`.
- **Footer:** 3px ink top rule; columns: Sections / Site (Latest, BS Files, Checks Out, About, Search, RSS) / Built on Lenz (disclosure paragraph + Fact-check-anything CTA, lenz.io, API docs links).

## 6. Page anatomies

- **Home:** folio → large masthead → nav → **lead check** (kicker, hero headline = the finding, claim group [mono `THE CLAIM` + quoted claim + article-size meter — the signature component stays on the lead], standfirst, READ THE CHECK →) beside **FRESH CHECKS** rail (6 row-cards) → **THE BS FILES** band (label + 4 cards + `ALL BS FILES →`) → two-column section blocks (each: SECTION label, 4 row-cards, `MORE →`) → **CHECKS OUT** band (4 cards) → **FREQUENTLY CHECKED** entity cloud (mono links sized by count) .
- **Section hub:** breadcrumb; H1 (section title); blurb (standfirst); filter chips; feed of cards (20/page); pagination.
- **Article:** breadcrumb (mono: HOME › SECTION · date); **H1 = the key finding** in the display serif, asserted (no quote treatment — it's our reporting); **claim block** (`.claim-block`, hairline-framed): mono `THE CLAIM` kicker, claim in serif 600 at `--fs-standfirst` with the oversized-quote pseudo-elements (the "under examination" cue migrated here from the old H1), meter block + `Verified by Lenz · {date}` mono inside the same group; `THE SHORT VERSION` H2 + body; `CAVEATS` H2 + warning list (only if warnings); panel-divided note (only if split — hairline box, mono `PANEL DIVIDED` label + one line: "Lenz's model panel did not reach unanimous agreement on this one."); `THE RECEIPTS` H2 + numbered source list (title link, mono meta: source_name · date); `MORE CHECKS` H2 + row-cards; attribution box.
- **Topic:** breadcrumb; kicker `TOPIC`; H1 entity name; mono count line ("7 claims checked"); feed; pagination.
- **Latest / collections:** kicker; H1; (collections: one-line neutral description — BS Files: "Claims that didn't survive contact with the evidence."; Checks Out: "Claims the evidence supports."); feed; pagination.
- **Search:** H1 SEARCH; Pagefind UI mount styled to tokens (its CSS vars mapped to ours).
- **About:** article-width prose; sections: What this is / How the checks work / What the meter means (the 5 labels explained + canonical verdicts) / Built on the Lenz API (the pitch + repo/API/SDK links) / Contact (GitHub issues).
- **404:** centered; huge display-serif "404"; "This page is BS — it doesn't exist."; mono links HOME / LATEST / SEARCH.

## 7. OG card (1200×630, Pillow)

Paper background; 12px yellow bar top; mono `FACT CHECK` kicker; **the key finding** in a characterful serif (wrapped, up to 5 lines, 72→48px by length, vertically centered, unquoted — asserted); bottom-right mono `IsThisBS? · @isthisbs · verified by Lenz`. **No claim, no verdict block** — the verdict rates the claim and must never sit beside the bare finding. (The quoted-claim/`THE CLAIM`-kicker variant exists only for the live `/c/` function's pre-conclusion window; static builds never render it.) **X safe zone:** X's timeline title-pill overlays roughly the bottom 75px — only the brand line may live there. **Content-addressed URLs:** cards publish as `/og/{vid}-{hash12}.png` (`config.og_content_key` over text + quoted-flag + `OG_TEMPLATE_VERSION` — stable across rebuilds, changes exactly when the pixels would) so scrape caches pick up changes; the legacy `/og/{vid}.png` copy ships forever. Site-default card variant for non-article pages (wordmark + tagline).

*OG cards are the one place real font files are allowed*: TTFs are downloaded into `.cache/fonts/` at build time and **baked into the PNGs** — pages never load them, so PSI is untouched.

## 8. Accessibility & performance

- Semantic landmarks; skip-link; exactly one `<h1>`/page; correct nesting; `alt` everywhere; visible focus; AA contrast (the `text` verdict tokens exist for this); meter has a text equivalent; filter chips keyboard-operable.
- **System fonts only — zero webfont requests, zero third-party requests on any page.** No JS frameworks: total first-party JS < 5KB (filter enhancement); Pagefind assets load only on /search/. CSS single file < 30KB. Lighthouse/PSI: Perf ≥ 95, SEO ≥ 95, A11y ≥ 95.
