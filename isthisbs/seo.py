"""SEO / AEO layer: JSON-LD builders and off-page assets.

This module teaches the two things that make a fact-check site legible to
search engines *and* answer engines (LLMs):

1. **JSON-LD builders** — pure functions returning ``dict`` graphs that
   ``render.py`` serialises into ``<script type="application/ld+json">``
   tags. The headline act is ``claim_review``: schema.org ``ClaimReview`` is
   the structured-data type Google surfaces in fact-check rich results and
   that answer engines read to attribute a verdict. The cardinal rule is that
   the machine-readable ``alternateName`` carries the **canonical API verdict**
   (``"False"``), never the playful BS-Meter label — the BS labels are a
   presentation-layer flourish and must not leak into structured data.

2. **Off-page assets** (``write_assets``) — ``robots.txt``, a sitemap index
   with article / page / Google-News children, per-section + site Atom feeds,
   and the ``llms.txt`` / ``llms-full.txt`` pair that the emerging llms.txt
   convention uses to hand a curated, token-cheap map of the site to LLMs.

Every URL is derived from ``SITE.base_url`` plus the ``.path`` properties on
``Check`` / ``Section`` / ``Entity`` — paths are never hand-assembled here, so
the URL scheme stays owned by ``content.py`` / ``config.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from .config import (
    FEED_SIZE,
    NEWS_SITEMAP_HOURS,
    PAGE_SIZE,
    SECTION_FEED_SIZE,
    SECTIONS,
    SITE,
    SOURCES_SHOWN_MAX,
)
from .content import Check, collections, group_by_entity, group_by_section

logger = logging.getLogger(__name__)

SCHEMA = "https://schema.org"

# XML namespaces used by the sitemap / news-sitemap / Atom outputs.
_SM_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"
_ATOM_NS = "http://www.w3.org/2005/Atom"

# lenz_score maps 1 (fully false) .. 10 (fully true). When the API omits it we
# fall back to a verdict-rank estimate so the Rating node is always valid — an
# absent/None ratingValue would make the ClaimReview fail validation.
_RANK_TO_SCORE = {1: 10, 2: 8, 3: 5, 4: 3, 5: 1}


# --------------------------------------------------------------------------- #
# Small shared node helpers
# --------------------------------------------------------------------------- #


def _isthisbs_org(base_url: str) -> dict:
    """The IsThisBS publisher node (no ``@context`` — safe to embed)."""
    return {
        "@type": "Organization",
        "name": SITE.short_name,
        "url": SITE.base_url,
        "logo": {"@type": "ImageObject", "url": f"{base_url}/static/logo.svg"},
    }


def _lenz_author() -> dict:
    """Lenz is the actual reviewer — author of every verdict on the site."""
    return {"@type": "Organization", "name": "Lenz", "url": SITE.lenz_home}


def _entity_things(check: Check) -> list[dict]:
    """Entities as schema.org ``Thing`` nodes, ``sameAs`` Wikidata when known.

    A resolvable ``sameAs`` (the Wikidata entity URL) disambiguates the subject
    for both crawlers and answer engines — that's the whole point of carrying
    the ``qid`` through from the API.
    """
    things: list[dict] = []
    for entity in check.entities:
        thing: dict = {"@type": "Thing", "name": entity.name}
        if entity.qid:
            thing["sameAs"] = entity.wikidata_url
        things.append(thing)
    return things


def _rating_value(check: Check) -> int:
    if check.lenz_score is not None:
        return check.lenz_score
    return _RANK_TO_SCORE[check.verdict.rank]


def _trim(text: str, limit: int) -> str:
    """Collapse whitespace and truncate to ``limit`` chars with an ellipsis.

    Cuts at the last word boundary inside the budget — a mid-word chop reads
    as a typo when Google renders the headline in a rich result.
    """
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:–—-") + "…"


# --------------------------------------------------------------------------- #
# JSON-LD builders (pure)
# --------------------------------------------------------------------------- #


def claim_review(check: Check, *, base_url: str) -> dict:
    """schema.org ``ClaimReview`` for one article — the AEO centrepiece.

    Mapping decisions worth knowing:
    - ``reviewRating.alternateName`` is the **canonical** verdict key
      (``"False"``), NOT the BS label — machine surfaces stay canonical.
    - ``reviewRating`` uses lenz_score on a 1(worst)..10(best) scale.
    - ``author`` is Lenz (the entity that actually produced the review);
      ``publisher`` is IsThisBS (the entity that publishes this page).
    - ``itemReviewed`` is a ``Claim`` with an unknown-safe author (the original
      claimant is unknown) and an ``appearance`` pointing at the Lenz canonical
      record; ``about`` carries the entity subjects with Wikidata ``sameAs``.
    """
    item_reviewed: dict = {
        "@type": "Claim",
        "text": check.claim,
        # The original claimant is unknown; an explicit unknown-safe author
        # keeps the Claim node valid without fabricating attribution.
        "author": {"@type": "Organization", "name": "Unknown"},
        # Where an instance of the claim can be inspected in full.
        "appearance": {"@type": "CreativeWork", "url": check.lenz_url},
    }
    about = _entity_things(check)
    if about:
        item_reviewed["about"] = about

    return {
        "@context": SCHEMA,
        "@type": "ClaimReview",
        "url": check.url,
        "claimReviewed": check.claim,
        "datePublished": check.created_at,
        "reviewBody": check.executive_summary,
        "reviewRating": {
            "@type": "Rating",
            "ratingValue": _rating_value(check),
            "bestRating": 10,
            "worstRating": 1,
            "alternateName": check.verdict.key,
        },
        "itemReviewed": item_reviewed,
        "author": _lenz_author(),
        "publisher": _isthisbs_org(base_url),
    }


def news_article(check: Check, *, base_url: str) -> dict:
    """schema.org ``NewsArticle`` — the article's editorial identity.

    Complements the ClaimReview: search engines treat the page as a dated news
    item (author Lenz, publisher IsThisBS) with the OG card as its image and
    the entity subjects as ``mentions`` (Wikidata ``sameAs`` when known).
    """
    node: dict = {
        "@context": SCHEMA,
        "@type": "NewsArticle",
        "headline": _trim(check.claim, 110),
        "url": check.url,
        "mainEntityOfPage": check.url,
        "datePublished": check.created_at,
        "dateModified": check.modified_at or check.created_at,
        "image": [f"{base_url}{check.og_path}"],
        "articleSection": check.section.title,
        "author": _lenz_author(),
        "publisher": _isthisbs_org(base_url),
    }
    summary = check.summary_paragraphs
    if summary:
        node["description"] = _trim(summary[0], 300)
    mentions = _entity_things(check)
    if mentions:
        node["mentions"] = mentions
    return node


def breadcrumbs(items: list[tuple[str, str]], *, base_url: str) -> dict:
    """``BreadcrumbList`` from ``(name, path)`` pairs (paths start with ``/``)."""
    return {
        "@context": SCHEMA,
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i,
                "name": name,
                "item": f"{base_url}{path}",
            }
            for i, (name, path) in enumerate(items, start=1)
        ],
    }


def item_list(checks: list[Check], *, base_url: str) -> dict:
    """``ItemList`` of article URLs — used on feed/hub pages for rich results."""
    return {
        "@context": SCHEMA,
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i,
                "url": check.url,
                "name": check.claim,
            }
            for i, check in enumerate(checks, start=1)
        ],
    }


def organization() -> dict:
    """The IsThisBS ``Organization`` node with cross-profile ``sameAs`` links."""
    node = _isthisbs_org(SITE.base_url)
    node["@context"] = SCHEMA
    node["description"] = SITE.description
    node["sameAs"] = [SITE.github_repo, "https://x.com/isthisbs"]
    return node


def website() -> dict:
    """``WebSite`` node with a ``SearchAction`` wired to the Pagefind page."""
    return {
        "@context": SCHEMA,
        "@type": "WebSite",
        "name": SITE.name,
        "url": SITE.base_url,
        "description": SITE.description,
        "inLanguage": SITE.language,
        "publisher": {
            "@type": "Organization",
            "name": SITE.short_name,
            "url": SITE.base_url,
        },
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{SITE.base_url}/search/?q={{search_term_string}}",
            },
            "query-input": "required name=search_term_string",
        },
    }


# --------------------------------------------------------------------------- #
# Off-page assets
# --------------------------------------------------------------------------- #


def _now() -> datetime:
    return datetime.now(UTC)


def _rfc3339(dt: datetime) -> str:
    """Atom / news timestamps: RFC 3339 (``2026-07-23T09:00:00+00:00``)."""
    return dt.astimezone(UTC).isoformat()


def _to_dt(iso: str, fallback: datetime) -> datetime:
    """Parse an API ISO timestamp, tolerating ``Z`` and naive values."""
    if iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            logger.warning("Unparseable timestamp %r", iso)
    return fallback


def _write_tree(root: ET.Element, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


# -- robots.txt ------------------------------------------------------------- #


def _write_robots(out_dir: Path) -> None:
    """Allow everything, AI crawlers included — this catalog *wants* ingestion.

    We name the sitemap index and the news sitemap explicitly; the index fans
    out to the article / page children.
    """
    lines = [
        "# IsThisBS? — fact-check catalog. Crawlers (search + AI) are welcome.",
        "User-agent: *",
        "Allow: /",
        "",
        f"Sitemap: {SITE.base_url}/sitemap.xml",
        f"Sitemap: {SITE.base_url}/sitemap-news.xml",
        "",
    ]
    (out_dir / "robots.txt").write_text("\n".join(lines), encoding="utf-8")


# -- sitemaps --------------------------------------------------------------- #


def _write_sitemap_index(out_dir: Path, today: str) -> None:
    ET.register_namespace("", _SM_NS)
    root = ET.Element(f"{{{_SM_NS}}}sitemapindex")
    for name in ("sitemap-articles.xml", "sitemap-pages.xml", "sitemap-news.xml"):
        sm = _sub(root, f"{{{_SM_NS}}}sitemap")
        _sub(sm, f"{{{_SM_NS}}}loc", f"{SITE.base_url}/{name}")
        _sub(sm, f"{{{_SM_NS}}}lastmod", today)
    _write_tree(root, out_dir / "sitemap.xml")


def _write_sitemap_articles(checks: list[Check], out_dir: Path) -> None:
    ET.register_namespace("", _SM_NS)
    root = ET.Element(f"{{{_SM_NS}}}urlset")
    for check in checks:
        url = _sub(root, f"{{{_SM_NS}}}url")
        _sub(url, f"{{{_SM_NS}}}loc", check.url)
        # lastmod tracks the freshest signal we have for the claim.
        lastmod = _to_dt(check.modified_at or check.created_at, check.created_dt)
        _sub(url, f"{{{_SM_NS}}}lastmod", lastmod.date().isoformat())
    _write_tree(root, out_dir / "sitemap-articles.xml")


def _paged(base: str, count: int, page_size: int) -> list[str]:
    """A feed's full path set: page 1 at ``base``, then ``base``page/N/."""
    pages = max(1, -(-count // page_size)) if count else 1
    return [base] + [f"{base}page/{n}/" for n in range(2, pages + 1)]


def _write_sitemap_pages(checks: list[Check], out_dir: Path, today: str) -> None:
    """Every non-article page — INCLUDING /page/N/ variants, mirroring what
    render.py actually emits (a sitemap that hides half the site is worse
    than none)."""
    ET.register_namespace("", _SM_NS)
    root = ET.Element(f"{{{_SM_NS}}}urlset")
    sections = group_by_section(checks)
    colls = collections(checks)
    paths = ["/"]
    for section in SECTIONS.values():
        paths += _paged(section.path, len(sections.get(section.key, [])), PAGE_SIZE)
    paths += _paged("/latest/", len(checks), PAGE_SIZE)
    paths += _paged("/bs-files/", len(colls["bs_files"]), PAGE_SIZE)
    paths += _paged("/checks-out/", len(colls["checks_out"]), PAGE_SIZE)
    paths += ["/search/", "/about/", "/privacy/"]
    # Every entity hub that cleared the >= min-claims threshold.
    for group in group_by_entity(checks):
        paths += _paged(group.entity.path, len(group.checks), PAGE_SIZE)
    for path in paths:
        url = _sub(root, f"{{{_SM_NS}}}url")
        _sub(url, f"{{{_SM_NS}}}loc", f"{SITE.base_url}{path}")
        _sub(url, f"{{{_SM_NS}}}lastmod", today)
    _write_tree(root, out_dir / "sitemap-pages.xml")


def _write_sitemap_news(checks: list[Check], out_dir: Path) -> None:
    """Google-News sitemap: only articles inside the recent window, cap 1000.

    Still emits a valid (empty) ``urlset`` when nothing is recent enough.
    """
    ET.register_namespace("", _SM_NS)
    ET.register_namespace("news", _NEWS_NS)
    root = ET.Element(f"{{{_SM_NS}}}urlset")
    cutoff = _now() - timedelta(hours=NEWS_SITEMAP_HOURS)
    recent = [c for c in checks if c.created_dt >= cutoff][:1000]
    for check in recent:
        url = _sub(root, f"{{{_SM_NS}}}url")
        _sub(url, f"{{{_SM_NS}}}loc", check.url)
        news = _sub(url, f"{{{_NEWS_NS}}}news")
        pub = _sub(news, f"{{{_NEWS_NS}}}publication")
        _sub(pub, f"{{{_NEWS_NS}}}name", SITE.short_name)
        _sub(pub, f"{{{_NEWS_NS}}}language", "en")
        _sub(
            news,
            f"{{{_NEWS_NS}}}publication_date",
            check.created_at or _rfc3339(check.created_dt),
        )
        _sub(news, f"{{{_NEWS_NS}}}title", check.claim)
    _write_tree(root, out_dir / "sitemap-news.xml")


# -- Atom feeds ------------------------------------------------------------- #


def _atom_feed(
    checks: list[Check],
    *,
    title: str,
    self_href: str,
    alternate_href: str,
    out_path: Path,
) -> None:
    """Well-formed Atom 1.0 feed. ElementTree handles XML escaping of the
    quotes / ampersands / unicode that live in real claim text."""
    ET.register_namespace("", _ATOM_NS)
    feed = ET.Element(f"{{{_ATOM_NS}}}feed")
    _sub(feed, f"{{{_ATOM_NS}}}id", self_href)
    _sub(feed, f"{{{_ATOM_NS}}}title", title)

    updated = max((c.created_dt for c in checks), default=_now())
    _sub(feed, f"{{{_ATOM_NS}}}updated", _rfc3339(updated))

    self_link = _sub(feed, f"{{{_ATOM_NS}}}link")
    self_link.set("rel", "self")
    self_link.set("type", "application/atom+xml")
    self_link.set("href", self_href)

    alt_link = _sub(feed, f"{{{_ATOM_NS}}}link")
    alt_link.set("rel", "alternate")
    alt_link.set("type", "text/html")
    alt_link.set("href", alternate_href)

    author = _sub(feed, f"{{{_ATOM_NS}}}author")
    _sub(author, f"{{{_ATOM_NS}}}name", "Lenz")
    _sub(author, f"{{{_ATOM_NS}}}uri", SITE.lenz_home)

    for check in checks:
        entry = _sub(feed, f"{{{_ATOM_NS}}}entry")
        _sub(entry, f"{{{_ATOM_NS}}}id", check.url)
        _sub(entry, f"{{{_ATOM_NS}}}title", check.claim)
        link = _sub(entry, f"{{{_ATOM_NS}}}link")
        link.set("rel", "alternate")
        link.set("type", "text/html")
        link.set("href", check.url)
        modified = _to_dt(check.modified_at, check.created_dt)
        _sub(entry, f"{{{_ATOM_NS}}}updated", _rfc3339(modified))
        _sub(entry, f"{{{_ATOM_NS}}}published", _rfc3339(check.created_dt))
        summary_paras = check.summary_paragraphs
        summary_text = summary_paras[0] if summary_paras else check.claim
        summary = _sub(entry, f"{{{_ATOM_NS}}}summary", summary_text)
        summary.set("type", "text")
        # Two facets per entry: the canonical verdict, and the section.
        verdict_cat = _sub(entry, f"{{{_ATOM_NS}}}category")
        verdict_cat.set("term", check.verdict.key)
        verdict_cat.set("label", check.verdict.bs_label)
        section_cat = _sub(entry, f"{{{_ATOM_NS}}}category")
        section_cat.set("term", check.section.key)
        section_cat.set("label", check.section.title)
        ent_author = _sub(entry, f"{{{_ATOM_NS}}}author")
        _sub(ent_author, f"{{{_ATOM_NS}}}name", "Lenz")

    _write_tree(feed, out_path)


def _write_feeds(checks: list[Check], out_dir: Path) -> None:
    # Site-wide feed.
    _atom_feed(
        checks[:FEED_SIZE],
        title=f"{SITE.name} — Latest Checks",
        self_href=f"{SITE.base_url}/feed.xml",
        alternate_href=f"{SITE.base_url}/",
        out_path=out_dir / "feed.xml",
    )
    # One feed per section (empty sections still get a valid feed).
    by_section = group_by_section(checks)
    for key, section in SECTIONS.items():
        _atom_feed(
            by_section[key][:SECTION_FEED_SIZE],
            title=f"{SITE.name} — {section.title}",
            self_href=f"{SITE.base_url}{section.path}feed.xml",
            alternate_href=f"{SITE.base_url}{section.path}",
            out_path=out_dir / key / "feed.xml",
        )


# -- llms.txt / llms-full.txt ---------------------------------------------- #


def _write_llms_txt(checks: list[Check], out_dir: Path) -> None:
    """Curated Markdown site map per the llms.txt convention.

    A short, link-dense overview an answer engine can read cheaply to
    understand what the site is and where the good stuff lives.
    """
    by_section = group_by_section(checks)
    lines = [
        f"# {SITE.name}",
        "",
        (
            f"> {SITE.tagline} An automated fact-check publication where every "
            "article is one claim, verified against independent sources by "
            f"[Lenz]({SITE.lenz_home}), an independent fact-checking engine. "
            "Every article carries schema.org ClaimReview JSON-LD (the "
            "canonical verdict lives in `alternateName`)."
        ),
        "",
        "## Sections",
        "",
    ]
    for key, section in SECTIONS.items():
        count = len(by_section[key])
        lines.append(
            f"- [{section.title}]({SITE.base_url}{section.path}): "
            f"{count} checks — {section.blurb}"
        )
    lines += [
        "",
        "## Collections",
        "",
        (
            f"- [The BS Files]({SITE.base_url}/bs-files/): claims that did not "
            "survive contact with the evidence (False / Mostly False)."
        ),
        (
            f"- [Checks Out]({SITE.base_url}/checks-out/): claims the evidence "
            "supports (True / Mostly True)."
        ),
        "",
        "## Browse",
        "",
        f"- [Latest]({SITE.base_url}/latest/): every check, newest first.",
        f"- [Search]({SITE.base_url}/search/): full-text search.",
        f"- [About]({SITE.base_url}/about/): how the checks work + the API.",
        "",
        "## Built on Lenz",
        "",
        (
            f"Verdicts are produced by Lenz — {SITE.lenz_home} — and every "
            f"article links to its full analysis. API docs: {SITE.lenz_api_docs}"
        ),
        "",
    ]
    (out_dir / "llms.txt").write_text("\n".join(lines), encoding="utf-8")


def _write_llms_full_txt(checks: list[Check], out_dir: Path) -> None:
    """Flat plain-text index — one block per article for bulk LLM ingestion.

    Newest first, every check. Verdict is dual-labelled (canonical + BS label)
    so an ingesting model sees the machine value alongside the display one.
    """
    blocks: list[str] = [
        f"{SITE.name} — full claim index",
        f"{SITE.description}",
        "",
    ]
    for check in checks:
        summary_paras = check.summary_paragraphs
        summary = summary_paras[0] if summary_paras else ""
        block = [
            f"CLAIM: {check.claim}",
            f"VERDICT: {check.verdict.key} ({check.verdict.bs_label})",
            f"SUMMARY: {summary}",
            f"URL: {check.url}",
            f"LENZ: {check.lenz_url}",
        ]
        if check.sources:
            # Cap like the article page does (SOURCES_SHOWN_MAX) — 40 URLs per
            # claim would bloat the file without adding ingestion value; the
            # LENZ line above carries the full source list.
            block.append("SOURCES:")
            block += [
                f"  - {source.url}" for source in check.sources[:SOURCES_SHOWN_MAX]
            ]
        blocks.append("\n".join(block))
    (out_dir / "llms-full.txt").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def write_assets(checks: list[Check], out_dir: Path) -> None:
    """Write every off-page asset into ``out_dir`` (the ``dist/`` root).

    ``checks`` is expected newest-first (as ``build_checks`` returns them);
    that ordering flows straight into the feeds and the llms index.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = _now().date().isoformat()

    _write_robots(out_dir)
    _write_sitemap_index(out_dir, today)
    _write_sitemap_articles(checks, out_dir)
    _write_sitemap_pages(checks, out_dir, today)
    _write_sitemap_news(checks, out_dir)
    _write_feeds(checks, out_dir)
    _write_llms_txt(checks, out_dir)
    _write_llms_full_txt(checks, out_dir)
    logger.info("Wrote SEO assets for %d checks to %s", len(checks), out_dir)
