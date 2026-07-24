"""Tests for the HTML render layer: parse emitted files, assert invariants."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from isthisbs import content, render
from isthisbs.config import SITE, VERDICTS

_H1_RE = re.compile(r"<h1[ >]")
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)

# Internal audit strings that must NEVER reach a rendered page.
_FORBIDDEN = [
    "Internal pro-side debate transcript.",
    "Internal con-side debate transcript.",
    "Panel adjudication summary (internal).",
    "debate_pro",
    "debate_con",
    "adjudication_summary",
]


def _article_path(out: Path, check: content.Check) -> Path:
    return out / check.path.strip("/") / "index.html"


def _jsonld_blocks(html: str) -> list[dict]:
    blocks = []
    for raw in _LD_RE.findall(html):
        blocks.append(json.loads(raw))
    return blocks


@pytest.fixture
def rendered(tmp_path, checks) -> Path:
    render.render_site(checks, tmp_path)
    return tmp_path


# --------------------------------------------------------------------------- #
# Site-wide invariants
# --------------------------------------------------------------------------- #


def test_every_page_has_exactly_one_h1(rendered):
    html_files = list(rendered.rglob("*.html"))
    assert html_files, "no HTML emitted"
    for path in html_files:
        if f"{path.parent.parent.name}" == "c" or "/c/" in path.as_posix():
            continue  # /c/ redirect stubs are noindex shells, not pages
        html = path.read_text(encoding="utf-8")
        count = len(_H1_RE.findall(html))
        assert count == 1, f"{path} has {count} <h1> tags"


def test_404_at_root_and_section_hubs_exist(rendered):
    assert (rendered / "404.html").is_file()
    for key in (
        "health",
        "science",
        "politics",
        "finance",
        "tech",
        "history",
        "legal",
        "general",
    ):
        assert (rendered / key / "index.html").is_file()


def test_static_copied_including_css(rendered):
    # Stylesheet ships ONLY under its content-hashed name (PSI: safe with the
    # immutable /static/** cache header), and pages reference that exact name.
    css_files = list((rendered / "static" / "css").glob("site.*.css"))
    assert len(css_files) == 1
    assert not (rendered / "static" / "css" / "site.css").exists()
    home_html = (rendered / "index.html").read_text(encoding="utf-8")
    assert f'href="/static/css/{css_files[0].name}"' in home_html
    body = css_files[0].read_text(encoding="utf-8")
    assert "/*" not in body  # minified: comments stripped
    assert (rendered / "favicon.svg").is_file()


def test_no_internal_audit_leaks_anywhere(rendered):
    for path in rendered.rglob("*.html"):
        html = path.read_text(encoding="utf-8")
        for needle in _FORBIDDEN:
            assert needle not in html, f"{needle!r} leaked into {path}"


# --------------------------------------------------------------------------- #
# Article page
# --------------------------------------------------------------------------- #


def test_article_disclosure_and_attribution(rendered, checks):
    check = checks[0]
    html = _article_path(rendered, check).read_text(encoding="utf-8")
    assert "produced by" in html
    assert SITE.lenz_home in html
    assert check.lenz_url in html  # per-article backlink to lenz.io/c/{id}


def test_article_canonical_link(rendered, checks):
    check = checks[0]
    html = _article_path(rendered, check).read_text(encoding="utf-8")
    expected = f'<link rel="canonical" href="{SITE.base_url}{check.path}">'
    assert expected in html


def test_article_claimreview_jsonld_parses_with_alternatename(rendered, checks):
    check = checks[0]
    html = _article_path(rendered, check).read_text(encoding="utf-8")
    blocks = _jsonld_blocks(html)
    review = next(b for b in blocks if b.get("@type") == "ClaimReview")
    assert review["reviewRating"]["alternateName"] == check.verdict_key
    assert review["claimReviewed"] == check.claim


def test_article_shows_bs_label_and_canonical_verdict(rendered, checks):
    for check in checks:
        html = _article_path(rendered, check).read_text(encoding="utf-8")
        assert check.verdict.bs_label in html
        assert f"Verdict: {check.verdict.key}" in html


def test_panel_divided_note_only_when_split(rendered, checks):
    split = [c for c in checks if c.is_split]
    unanimous = [c for c in checks if not c.is_split]
    assert split and unanimous, "fixture must contain both"
    for check in split:
        html = _article_path(rendered, check).read_text(encoding="utf-8")
        assert "Panel Divided" in html
    for check in unanimous:
        html = _article_path(rendered, check).read_text(encoding="utf-8")
        assert "Panel Divided" not in html


# --------------------------------------------------------------------------- #
# Feed cards + verdict pill for all five verdicts
# --------------------------------------------------------------------------- #


def test_feed_cards_carry_data_verdict(rendered):
    html = (rendered / "latest" / "index.html").read_text(encoding="utf-8")
    assert "data-verdict=" in html


def test_all_five_verdicts_render_pill(tmp_path, make_detail):
    docs = [
        make_detail(claim=f"claim {key}", verdict=key, domain="general")
        for key in VERDICTS
    ]
    checks = content.build_checks(docs)
    render.render_site(checks, tmp_path)
    for check in checks:
        html = _article_path(tmp_path, check).read_text(encoding="utf-8")
        v = VERDICTS[check.verdict_key]
        assert v.bs_label in html
        assert f'data-pagefind-filter="verdict:{v.key}"' in html
        assert 'data-pagefind-filter="section"' in html


# --------------------------------------------------------------------------- #
# Entity hubs — only >= 2 claims
# --------------------------------------------------------------------------- #


def test_entity_page_only_for_two_plus_claims(tmp_path, make_detail):
    shared = [{"name": "Shared Topic", "qid": "Q100"}]
    solo = [{"name": "Solo Topic", "qid": "Q200"}]
    docs = [
        make_detail(claim="a", entities=shared, created_at="2026-07-10T00:00:00Z"),
        make_detail(claim="b", entities=shared, created_at="2026-07-11T00:00:00Z"),
        make_detail(claim="c", entities=solo, created_at="2026-07-12T00:00:00Z"),
    ]
    checks = content.build_checks(docs)
    render.render_site(checks, tmp_path)
    assert (tmp_path / "topic" / "shared-topic" / "index.html").is_file()
    assert not (tmp_path / "topic" / "solo-topic").exists()


def test_ga_absent_by_default(tmp_path, checks, monkeypatch):
    """No GA_MEASUREMENT_ID at build time → zero analytics markup ships."""
    monkeypatch.delenv("GA_MEASUREMENT_ID", raising=False)
    out = tmp_path / "dist-ga-off"
    render.render_site(checks, out)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "googletagmanager" not in home
    assert "gtag" not in home


def test_ga_present_when_configured(tmp_path, checks, monkeypatch):
    """GA_MEASUREMENT_ID set → async gtag snippet with that id, on every page."""
    monkeypatch.setenv("GA_MEASUREMENT_ID", "G-TESTID123")
    out = tmp_path / "dist-ga-on"
    render.render_site(checks, out)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "googletagmanager.com/gtag/js?id=G-TESTID123" in home
    assert "gtag('config', 'G-TESTID123')" in home
    assert '<script async src="https://www.googletagmanager.com' in home
    notfound = (out / "404.html").read_text(encoding="utf-8")
    assert "G-TESTID123" in notfound


def test_article_serp_contract(tmp_path, checks):
    """SEO round 2: Fact-Check title with verdict; verdict-first description
    with a receipts count. This shape is deliberate — see render.py."""
    out = tmp_path / "dist-serp"
    render.render_site(checks, out)
    check = checks[0]
    html = (out / check.path.lstrip("/") / "index.html").read_text(encoding="utf-8")
    assert "<title>Fact Check: " in html
    assert f" — {check.verdict.key}</title>" in html
    assert f'content="Verdict: {check.verdict.key}. ' in html
    if check.sources:
        assert f"Checked against {len(check.sources)} independent sources." in html
    assert 'property="og:site_name"' in html


def test_filed_under_links_only_topic_entities(tmp_path, make_detail):
    """Entities with topic pages link there; below-threshold ones are plain."""
    shared = [{"name": "Linked Topic", "qid": "Q1"}]
    docs = [
        make_detail(claim="a", entities=shared, created_at="2026-07-10T00:00:00Z"),
        make_detail(
            claim="b",
            entities=shared + [{"name": "Solo Thing", "qid": "Q2"}],
            created_at="2026-07-11T00:00:00Z",
        ),
    ]
    checks = content.build_checks(docs)
    render.render_site(checks, tmp_path)
    check_b = next(c for c in checks if c.claim == "b")
    html = _article_path(tmp_path, check_b).read_text(encoding="utf-8")
    assert "Filed Under" in html
    assert '<a class="tag" href="/topic/linked-topic/">Linked Topic</a>' in html
    assert 'tag--plain">Solo Thing</span>' in html


# --------------------------------------------------------------------------- #
# Discussion CTA (baked GitHub-Discussions counts, zero-hiding)
# --------------------------------------------------------------------------- #


def test_article_zero_state_shows_verdict_challenge(tmp_path, checks):
    """No discussion data -> the challenge prompt, linking to a PREFILLED
    new-discussion form (never a bare '0 votes' line)."""
    render.render_site(checks, tmp_path)
    check = checks[0]
    html = _article_path(tmp_path, check).read_text()
    assert f"{check.verdict.bs_label}? Make your case" in html
    assert "/discussions/new?" in html
    assert check.verification_id in html
    assert "0 ·" not in html  # zero counts are never rendered


def test_article_nonzero_counts_render_and_link(tmp_path, checks):
    check = checks[0]
    dmap = {
        check.verification_id: {
            "url": "https://github.com/lenzhq/demo-media/discussions/42",
            "up": 5,
            "down": 0,
            "comments": 3,
        }
    }
    render.render_site(checks, tmp_path, discussions=dmap)
    html = _article_path(tmp_path, check).read_text()
    assert "discussions/42" in html
    assert "👍 5" in html
    assert "💬 3" in html
    assert "👎" not in html  # zero component hidden
    assert f"{check.verdict.bs_label}? Make your case" not in html


# --------------------------------------------------------------------------- #
# YMYL disclaimers (health / finance / legal)
# --------------------------------------------------------------------------- #


def test_ymyl_sections_carry_inline_disclaimer(tmp_path, checks):
    """Health, finance, and legal articles carry their one-line section
    disclaimer; other sections carry none (the sitewide as-is language on
    /privacy/ covers them)."""
    render.render_site(checks, tmp_path)
    ymyl = {"health", "finance", "legal"}
    seen_ymyl = seen_other = 0
    for check in checks:
        html = _article_path(tmp_path, check).read_text()
        section = check.section
        if section.key in ymyl:
            assert section.disclaimer, f"{section.key} has no disclaimer configured"
            assert section.disclaimer in html, f"disclaimer missing on {check.path}"
            seen_ymyl += 1
        else:
            assert "attribution__disclaimer" not in html, (
                f"unexpected disclaimer on {check.path}"
            )
            seen_other += 1
    assert seen_ymyl and seen_other, "fixture set must cover both kinds of section"
