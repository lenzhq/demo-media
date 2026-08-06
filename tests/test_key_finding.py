"""Finding-first contracts: the key_finding reorg's invariants, end to end.

Two invariants drive every surface (see the plan / DESIGN.md):
1. The verdict never appears without the claim adjacent to it.
2. The executive summary never appears without the claim above it.
Only the key finding stands alone.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import build as build_cli
from isthisbs import content, render, seo


def _one_check(make_detail, **over):
    (check,) = content.build_checks([make_detail(**over)])
    return check


FINDING = "The actual figure is one tenth of the claimed value."
CLAIM = "A widely shared statistic is off by a factor of ten."


# --------------------------------------------------------------------------- #
# Model: headline fallback
# --------------------------------------------------------------------------- #


def test_headline_is_finding_when_present(make_detail):
    check = _one_check(make_detail, key_finding=FINDING)
    assert check.has_finding
    assert check.headline == FINDING


def test_headline_falls_back_to_claim(make_detail):
    check = _one_check(make_detail, key_finding="")
    assert not check.has_finding
    assert check.headline == check.claim


def test_whitespace_finding_is_empty(make_detail):
    check = _one_check(make_detail, key_finding="   ")
    assert not check.has_finding


def test_slug_stays_claim_derived(make_detail):
    """URL stability: the slug never follows the finding."""
    with_f = _one_check(make_detail, verification_id="slug0001", key_finding=FINDING)
    without = _one_check(make_detail, verification_id="slug0001")
    assert with_f.slug == without.slug


# --------------------------------------------------------------------------- #
# Article + card templates
# --------------------------------------------------------------------------- #


def _render_one(tmp_path, make_detail, **over):
    check = _one_check(make_detail, **over)
    render.render_site([check], tmp_path)
    article = (tmp_path / check.path.lstrip("/") / "index.html").read_text()
    home = (tmp_path / "index.html").read_text()
    return check, article, home


def test_article_finding_first_header(tmp_path, make_detail):
    check, article, home = _render_one(tmp_path, make_detail, key_finding=FINDING)
    # H1 is the finding, asserted — no quote styling.
    m = re.search(r"<h1[^>]*>(.*?)</h1>", article, re.S)
    assert m and FINDING in m.group(1)
    assert "claim-quote" not in m.group(0)
    # The claim block binds quoted claim + meter (invariant 1), above summary.
    # (Scoped to the body — the claim also appears in the head's description.)
    assert 'class="claim-block"' in article
    h1_pos = article.index("<h1")
    claim_pos = article.index(check.claim, h1_pos)
    meter_pos = article.index('class="meter ', h1_pos)
    summary_pos = article.index("The Short Version", h1_pos)
    assert h1_pos < claim_pos < meter_pos < summary_pos


def test_card_claim_line_binds_pill_to_claim(tmp_path, make_detail):
    """On feed cards the pill sits in the claim line, never alone under the
    finding (invariant 1)."""
    check, _, home = _render_one(tmp_path, make_detail, key_finding=FINDING)
    # The home rail/lead shows the finding as the linked title...
    assert FINDING in home
    # ...and wherever a card claim line renders, the pill is inside it.
    for cm in re.finditer(r'<p class="check-card__claim">(.*?)</p>', home, re.S):
        assert "bs-pill" in cm.group(1)


def test_fresh_checks_rail_is_headline_only(tmp_path, make_detail):
    """The rail is a headline stack: linked findings only — no claim line,
    no pill (only the finding may stand alone), no truncation."""
    docs = [
        make_detail(
            key_finding=f"Distinct finding number {i} that the rail must show in full.",
            created_at=f"2026-07-{10 + i:02d}T00:00:00Z",
        )
        for i in range(8)
    ]
    checks = content.build_checks(docs)
    render.render_site(checks, tmp_path)
    home = (tmp_path / "index.html").read_text()
    rail = home.split('class="rail"')[1].split("</aside>")[0]
    assert "check-card--headline" in rail
    assert "check-card__claim" not in rail
    assert "bs-pill" not in rail
    assert "…" not in rail  # no truncation in the headline stack


def test_home_lead_keeps_full_meter_in_claim_group(tmp_path, make_detail):
    check, _, home = _render_one(tmp_path, make_detail, key_finding=FINDING)
    lead = home.split('class="lead"')[1].split("</article>")[0]
    assert FINDING in lead
    assert 'class="meter ' in lead  # signature component stays on the lead
    assert check.claim in lead  # bound to the verdict (invariant 1)


# --------------------------------------------------------------------------- #
# Autoescape — LLM-supplied text through the highest-risk sinks
# --------------------------------------------------------------------------- #


def test_adversarial_strings_never_become_markup(tmp_path, make_detail):
    evil = 'x < 1 "quote" <script>alert(1)</script>'
    check, article, home = _render_one(
        tmp_path,
        make_detail,
        claim=f"Claim {evil} end.",
        key_finding=f"Finding {evil} end.",
    )
    seo.write_assets([check], tmp_path)
    for page in (article, home):
        assert "<script>alert(1)</script>" not in page
    feed = (tmp_path / "feed.xml").read_text()
    assert "<script>" not in feed  # ET escapes; markup can't survive raw
    ET.parse(tmp_path / "feed.xml")  # still well-formed XML


# --------------------------------------------------------------------------- #
# JSON-LD + off-page assets
# --------------------------------------------------------------------------- #


def test_claim_review_name_is_finding_claimreviewed_is_claim(make_detail):
    check = _one_check(make_detail, key_finding=FINDING)
    node = seo.claim_review(check, base_url="https://x")
    assert node["name"] == FINDING
    assert node["claimReviewed"] == check.claim  # machine-canonical, unchanged


def test_news_article_headline_and_description(make_detail):
    check = _one_check(make_detail, key_finding=FINDING)
    node = seo.news_article(check, base_url="https://x")
    assert node["headline"] == FINDING
    assert node["description"].startswith("We checked: “")
    assert f"Verdict: {check.verdict.key}." in node["description"]


def test_item_list_names_use_headline(make_detail):
    check = _one_check(make_detail, key_finding=FINDING)
    node = seo.item_list([check], base_url="https://x")
    assert node["itemListElement"][0]["name"] == FINDING


def test_atom_entry_title_finding_summary_binds_claim(tmp_path, make_detail):
    check = _one_check(
        make_detail, key_finding=FINDING, created_at="2099-01-01T00:00:00Z"
    )
    seo.write_assets([check], tmp_path)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    feed = ET.parse(tmp_path / "feed.xml")
    entry = feed.find("a:entry", ns)
    assert entry.find("a:title", ns).text == FINDING
    summary = entry.find("a:summary", ns).text
    assert summary.startswith("Claim: “")
    assert f"Verdict: {check.verdict.key}" in summary
    content_el = entry.find("a:content", ns)
    assert content_el.get("type") == "html"
    assert "<q>" in content_el.text and check.claim in content_el.text


def test_news_sitemap_title_is_headline(tmp_path, make_detail):
    from datetime import UTC, datetime

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    check = _one_check(make_detail, key_finding=FINDING, created_at=now_iso)
    seo.write_assets([check], tmp_path)
    news = (tmp_path / "sitemap-news.xml").read_text()
    assert FINDING in news


def test_llms_files_carry_finding_and_bound_claim(tmp_path, make_detail):
    check = _one_check(make_detail, key_finding=FINDING)
    seo.write_assets([check], tmp_path)
    llms = (tmp_path / "llms.txt").read_text()
    assert f"[{FINDING}]" in llms
    assert "checked claim: “" in llms
    full = (tmp_path / "llms-full.txt").read_text()
    assert f"FINDING: {FINDING}" in full
    # CLAIM/VERDICT precede FINDING — the binding stays unambiguous.
    assert full.index("CLAIM:") < full.index("VERDICT:") < full.index("FINDING:")


def test_llms_full_omits_finding_line_pre_backfill(tmp_path, make_detail):
    check = _one_check(make_detail, key_finding="")
    seo.write_assets([check], tmp_path)
    assert "FINDING:" not in (tmp_path / "llms-full.txt").read_text()


# --------------------------------------------------------------------------- #
# Build skip-gate (finding-less checks never publish)
# --------------------------------------------------------------------------- #


def _fake_checks(make_detail, with_finding: int, without: int):
    docs = [make_detail() for _ in range(with_finding)]
    docs += [make_detail(key_finding="") for _ in range(without)]
    return content.build_checks(docs)


def test_gate_passes_through_full_coverage(make_detail, monkeypatch):
    monkeypatch.delenv("ALLOW_PARTIAL_FINDINGS", raising=False)
    checks = _fake_checks(make_detail, 10, 0)
    assert build_cli._apply_findings_gate(checks) == checks


def test_gate_skips_small_number_of_stragglers(make_detail, monkeypatch):
    monkeypatch.delenv("ALLOW_PARTIAL_FINDINGS", raising=False)
    checks = _fake_checks(make_detail, 39, 1)
    gated = build_cli._apply_findings_gate(checks)
    assert len(gated) == 39
    assert all(c.has_finding for c in gated)


def test_gate_fails_on_mass_missing(make_detail, monkeypatch):
    """>5% missing = stale cache / partial backfill — never silently shrink
    the site (existing article URLs would 404)."""
    monkeypatch.delenv("ALLOW_PARTIAL_FINDINGS", raising=False)
    assert build_cli._apply_findings_gate(_fake_checks(make_detail, 5, 5)) is None


def test_gate_mass_missing_overridable(make_detail, monkeypatch):
    monkeypatch.setenv("ALLOW_PARTIAL_FINDINGS", "1")
    gated = build_cli._apply_findings_gate(_fake_checks(make_detail, 5, 5))
    assert len(gated) == 5
    assert all(c.has_finding for c in gated)


# --------------------------------------------------------------------------- #
# /c/ stub coherence
# --------------------------------------------------------------------------- #


def test_claim_stub_finding_title_and_anchored_description(tmp_path, make_detail):
    check, _, _ = _render_one(tmp_path, make_detail, key_finding=FINDING)
    stub = (tmp_path / "c" / check.verification_id / "index.html").read_text()
    assert FINDING in stub
    assert "We checked: “" in stub
    assert check.og_path in stub  # hashed card URL flows through
