"""Tests for the SEO/AEO layer: JSON-LD builders + off-page assets."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree as ET

from isthisbs import content, seo
from isthisbs.config import SITE, VERDICTS

_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_NEWS = "{http://www.google.com/schemas/sitemap-news/0.9}"
_ATOM = "{http://www.w3.org/2005/Atom}"


def _one(make_detail, **kw) -> content.Check:
    return content.build_checks([make_detail(**kw)])[0]


# --------------------------------------------------------------------------- #
# claim_review
# --------------------------------------------------------------------------- #


def test_claim_review_rating_mapping(make_detail):
    check = _one(make_detail, verdict="False", lenz_score=2)
    ld = seo.claim_review(check, base_url=SITE.base_url)
    rating = ld["reviewRating"]
    assert rating["ratingValue"] == 2
    assert rating["bestRating"] == 10
    assert rating["worstRating"] == 1
    assert ld["@type"] == "ClaimReview"
    assert ld["url"] == check.url
    assert ld["claimReviewed"] == check.claim


def test_claim_review_alternatename_is_canonical_never_bs_label(make_detail):
    for key in VERDICTS:
        check = _one(make_detail, verdict=key)
        ld = seo.claim_review(check, base_url=SITE.base_url)
        alt = ld["reviewRating"]["alternateName"]
        assert alt == key
        assert alt != VERDICTS[key].bs_label


def test_claim_review_author_is_lenz(make_detail):
    check = _one(make_detail)
    ld = seo.claim_review(check, base_url=SITE.base_url)
    assert ld["author"]["name"] == "Lenz"
    assert ld["author"]["url"] == SITE.lenz_home
    # Publisher is IsThisBS, distinct from the reviewer.
    assert ld["publisher"]["name"] == SITE.short_name


def test_claim_review_appearance_points_at_lenz(make_detail):
    check = _one(make_detail)
    ld = seo.claim_review(check, base_url=SITE.base_url)
    assert ld["itemReviewed"]["appearance"]["url"] == check.lenz_url


def test_claim_review_rating_fallback_when_score_missing(make_detail):
    # False → rank 5 → fallback score 1.
    check = _one(make_detail, verdict="False", lenz_score=None)
    ld = seo.claim_review(check, base_url=SITE.base_url)
    assert ld["reviewRating"]["ratingValue"] == 1


def test_claim_review_about_sameas_only_with_qid(make_detail):
    check = _one(
        make_detail,
        entities=[
            {"name": "With Qid", "qid": "Q42"},
            {"name": "No Qid", "qid": ""},
        ],
    )
    ld = seo.claim_review(check, base_url=SITE.base_url)
    about = {t["name"]: t for t in ld["itemReviewed"]["about"]}
    assert about["With Qid"]["sameAs"] == "https://www.wikidata.org/wiki/Q42"
    assert "sameAs" not in about["No Qid"]


# --------------------------------------------------------------------------- #
# news_article
# --------------------------------------------------------------------------- #


def test_news_article_headline_capped(make_detail):
    long_claim = "This is a very long claim. " * 20
    check = _one(make_detail, claim=long_claim)
    ld = seo.news_article(check, base_url=SITE.base_url)
    assert len(ld["headline"]) <= 110


def test_news_article_mentions_sameas_only_with_qid(make_detail):
    check = _one(
        make_detail,
        entities=[
            {"name": "Known", "qid": "Q7"},
            {"name": "Unknown", "qid": ""},
        ],
    )
    ld = seo.news_article(check, base_url=SITE.base_url)
    mentions = {m["name"]: m for m in ld["mentions"]}
    assert "sameAs" in mentions["Known"]
    assert "sameAs" not in mentions["Unknown"]


# --------------------------------------------------------------------------- #
# breadcrumbs / item_list positions
# --------------------------------------------------------------------------- #


def test_breadcrumbs_positions_and_urls():
    ld = seo.breadcrumbs(
        [("Home", "/"), ("Health", "/health/")], base_url=SITE.base_url
    )
    items = ld["itemListElement"]
    assert [i["position"] for i in items] == [1, 2]
    assert items[1]["item"] == f"{SITE.base_url}/health/"


def test_item_list_positions(checks):
    ld = seo.item_list(checks, base_url=SITE.base_url)
    positions = [i["position"] for i in ld["itemListElement"]]
    assert positions == list(range(1, len(checks) + 1))


# --------------------------------------------------------------------------- #
# write_assets — off-page files
# --------------------------------------------------------------------------- #


def test_robots_points_at_sitemaps(tmp_path, checks):
    seo.write_assets(checks, tmp_path)
    robots = (tmp_path / "robots.txt").read_text()
    assert f"Sitemap: {SITE.base_url}/sitemap.xml" in robots
    assert f"Sitemap: {SITE.base_url}/sitemap-news.xml" in robots
    assert "User-agent: *" in robots


def test_sitemap_index_and_children_parse(tmp_path, checks):
    seo.write_assets(checks, tmp_path)
    index = ET.parse(tmp_path / "sitemap.xml").getroot()
    locs = [el.text for el in index.iter(f"{_SM}loc")]
    assert f"{SITE.base_url}/sitemap-articles.xml" in locs
    assert f"{SITE.base_url}/sitemap-pages.xml" in locs
    assert f"{SITE.base_url}/sitemap-news.xml" in locs
    # Children exist and parse.
    arts = ET.parse(tmp_path / "sitemap-articles.xml").getroot()
    art_locs = [el.text for el in arts.iter(f"{_SM}loc")]
    assert {c.url for c in checks} <= set(art_locs)
    pages = ET.parse(tmp_path / "sitemap-pages.xml").getroot()
    page_locs = [el.text for el in pages.iter(f"{_SM}loc")]
    assert f"{SITE.base_url}/" in page_locs
    assert f"{SITE.base_url}/about/" in page_locs


def test_news_sitemap_honors_48h_window(tmp_path, make_detail):
    now = datetime.now(UTC)
    recent = now - timedelta(hours=1)
    old = now - timedelta(hours=72)
    docs = [
        make_detail(claim="recent claim", created_at=recent.isoformat()),
        make_detail(claim="old claim", created_at=old.isoformat()),
    ]
    checks = content.build_checks(docs)
    seo.write_assets(checks, tmp_path)
    root = ET.parse(tmp_path / "sitemap-news.xml").getroot()
    titles = [el.text for el in root.iter(f"{_NEWS}title")]
    assert "recent claim" in titles
    assert "old claim" not in titles


def test_atom_feed_wellformed_and_escaped(tmp_path, make_detail):
    nasty = 'Tom & Jerry said "2 < 3 > 1" — is <this> BS?'
    check = _one(make_detail, claim=nasty)
    seo.write_assets([check], tmp_path)
    root = ET.parse(tmp_path / "feed.xml").getroot()  # raises if malformed
    titles = [el.text for el in root.iter(f"{_ATOM}title")]
    # The raw special characters survive the XML round-trip intact.
    assert nasty in titles


def test_per_section_feeds_written(tmp_path, checks):
    seo.write_assets(checks, tmp_path)
    # Every section gets a (possibly empty) valid feed.
    for key in ("health", "science", "general"):
        feed_path = tmp_path / key / "feed.xml"
        assert feed_path.exists()
        ET.parse(feed_path)  # parses


def test_llms_txt_has_sections(tmp_path, checks):
    seo.write_assets(checks, tmp_path)
    text = (tmp_path / "llms.txt").read_text()
    assert f"# {SITE.name}" in text
    assert "## Sections" in text
    assert "## Collections" in text
    assert "Health" in text


def test_llms_full_txt_lists_every_claim(tmp_path, checks):
    seo.write_assets(checks, tmp_path)
    text = (tmp_path / "llms-full.txt").read_text()
    assert "CLAIM:" in text
    assert "VERDICT:" in text
    for check in checks:
        assert check.claim in text
        # Dual-labelled: canonical key present alongside the BS label.
        assert check.verdict.key in text
