"""Tests for the editorial data model: slugs, parsing, grouping, pagination."""

from __future__ import annotations

from isthisbs import content
from isthisbs.config import COLLECTION_SIZE, SECTIONS, VERDICTS

# --------------------------------------------------------------------------- #
# Slug minting
# --------------------------------------------------------------------------- #


def test_mint_slug_stable_and_id_suffixed():
    slug = content.mint_slug("The Earth is round", "abcd1234")
    assert slug == "the-earth-is-round-abcd1234"
    # Stable across calls.
    assert slug == content.mint_slug("The Earth is round", "abcd1234")


def test_mint_slug_uniqueness_via_id_suffix():
    a = content.mint_slug("Same claim text", "id0001")
    b = content.mint_slug("Same claim text", "id0002")
    assert a != b
    assert a.endswith("-id0001")
    assert b.endswith("-id0002")


def test_mint_slug_unicode_transliterated():
    slug = content.mint_slug("Café São Paulo açaí", "u1")
    # slugify transliterates to ASCII; no non-ascii survives.
    assert slug.isascii()
    assert slug.endswith("-u1")
    assert "cafe" in slug


def test_mint_slug_length_capped():
    long_claim = "word " * 200
    slug = content.mint_slug(long_claim, "vid00042")
    text = slug[: -len("-vid00042")]
    assert len(text) <= content.SLUG_MAX


def test_mint_slug_empty_claim_fallback():
    slug = content.mint_slug("", "vidx")
    assert slug == "claim-vidx"
    # Whitespace / punctuation-only claim also falls back.
    assert content.mint_slug("!!! ???", "vidy") == "claim-vidy"


def test_entity_slug_fallback():
    assert content.entity_slug("") == "topic"
    assert content.entity_slug("United Nations") == "united-nations"


# --------------------------------------------------------------------------- #
# build_checks — filtering + sorting + dedupe
# --------------------------------------------------------------------------- #


def test_build_checks_excludes_error_and_unknown(make_detail):
    docs = [
        make_detail(claim="ok", verdict="True", created_at="2026-07-10T00:00:00Z"),
        make_detail(claim="err", verdict="Error", created_at="2026-07-11T00:00:00Z"),
        make_detail(claim="weird", verdict="Bogus", created_at="2026-07-12T00:00:00Z"),
    ]
    checks = content.build_checks(docs)
    verdicts = {c.verdict_key for c in checks}
    assert verdicts == {"True"}
    assert all(c.verdict_key in VERDICTS for c in checks)


def test_build_checks_language_filter(make_detail):
    docs = [
        make_detail(claim="english", language="en"),
        make_detail(claim="spanish", language="es"),
        # region-tagged english still counts (split on '-').
        make_detail(claim="uk english", language="en-GB"),
    ]
    claims = {c.claim for c in content.build_checks(docs)}
    assert claims == {"english", "uk english"}


def test_build_checks_dedupe_by_id(make_detail):
    doc1 = make_detail(verification_id="dupe", claim="first")
    doc2 = make_detail(verification_id="dupe", claim="second")
    checks = content.build_checks([doc1, doc2])
    assert len(checks) == 1
    assert checks[0].verification_id == "dupe"


def test_build_checks_newest_first(make_detail):
    docs = [
        make_detail(claim="old", created_at="2026-01-01T00:00:00Z"),
        make_detail(claim="new", created_at="2026-07-01T00:00:00Z"),
        make_detail(claim="mid", created_at="2026-04-01T00:00:00Z"),
    ]
    order = [c.claim for c in content.build_checks(docs)]
    assert order == ["new", "mid", "old"]


def test_build_checks_skips_missing_required(make_detail):
    no_claim = make_detail(claim="")
    no_vid = make_detail()
    no_vid["detail"]["verification_id"] = ""
    checks = content.build_checks([no_claim, no_vid])
    assert checks == []


def test_build_checks_never_crashes_on_malformed():
    # A doc missing 'detail' entirely must be skipped, not raise.
    checks = content.build_checks([{}, {"detail": None}, {"nonsense": 1}])
    assert checks == []


def test_parse_check_sources_require_url(make_detail):
    # Two URL-bearing sources (clears the editorial floor) + one URL-less
    # entry that must be dropped by parsing.
    doc = make_detail(
        sources=[
            {"source_name": "A", "title": "keep", "url": "https://x/1"},
            {"source_name": "B", "title": "drop", "url": ""},
            {"source_name": "C", "title": "also-keep", "url": "https://x/2"},
        ]
    )
    check = content.build_checks([doc])[0]
    assert [s.title for s in check.sources] == ["keep", "also-keep"]


def test_parse_check_panel_agreement_lowercased(make_detail):
    doc = make_detail(panel_agreement="SPLIT")
    check = content.build_checks([doc])[0]
    assert check.panel_agreement == "split"
    assert check.is_split is True


# --------------------------------------------------------------------------- #
# group_by_section
# --------------------------------------------------------------------------- #


def test_group_by_section_all_keys_present(checks):
    groups = content.group_by_section(checks)
    assert set(groups.keys()) == set(SECTIONS.keys())


def test_group_by_section_unknown_domain_to_general(make_detail):
    doc = make_detail(domain="astrology")
    check = content.build_checks([doc])[0]
    assert check.section.key == "general"


# --------------------------------------------------------------------------- #
# group_by_entity
# --------------------------------------------------------------------------- #


def _mk(make_detail, claim, entities, **kw):
    return make_detail(claim=claim, entities=entities, **kw)


def test_group_by_entity_min_count_threshold(make_detail):
    ent = [{"name": "Vaccines", "qid": "Q134808"}]
    solo = [{"name": "Lonely Topic", "qid": ""}]
    docs = [
        _mk(make_detail, "a", ent, created_at="2026-07-10T00:00:00Z"),
        _mk(make_detail, "b", ent, created_at="2026-07-11T00:00:00Z"),
        _mk(make_detail, "c", solo, created_at="2026-07-12T00:00:00Z"),
    ]
    checks = content.build_checks(docs)
    groups = content.group_by_entity(checks, min_count=2)
    names = {g.entity.name for g in groups}
    assert "Vaccines" in names
    assert "Lonely Topic" not in names


def test_group_by_entity_casefold_merge(make_detail):
    docs = [
        _mk(make_detail, "a", [{"name": "NASA", "qid": ""}]),
        _mk(make_detail, "b", [{"name": "nasa", "qid": ""}]),
    ]
    checks = content.build_checks(docs)
    groups = content.group_by_entity(checks, min_count=2)
    # Same slug + casefold-equal names → one merged group of both checks.
    assert len(groups) == 1
    assert len(groups[0].checks) == 2


def test_group_by_entity_slug_collision_disambiguated(make_detail):
    # Distinct entities (different casefold) that slugify identically.
    docs = [
        _mk(make_detail, "a", [{"name": "Café", "qid": "Q1"}]),
        _mk(make_detail, "b", [{"name": "Café", "qid": "Q1"}]),
        _mk(make_detail, "c", [{"name": "Cafe", "qid": "Q2"}]),
        _mk(make_detail, "d", [{"name": "Cafe", "qid": "Q2"}]),
    ]
    checks = content.build_checks(docs)
    groups = content.group_by_entity(checks, min_count=2)
    slugs = [g.entity.slug for g in groups]
    # Two groups, distinct slugs (one disambiguated by qid).
    assert len(groups) == 2
    assert len(set(slugs)) == 2
    assert any("-q2" in s for s in slugs)


def test_group_by_entity_sorted_by_count_desc(make_detail):
    big = [{"name": "Big Topic", "qid": "QB"}]
    small = [{"name": "Small Topic", "qid": "QS"}]
    docs = [
        _mk(make_detail, "1", big),
        _mk(make_detail, "2", big),
        _mk(make_detail, "3", big),
        _mk(make_detail, "4", small),
        _mk(make_detail, "5", small),
    ]
    checks = content.build_checks(docs)
    groups = content.group_by_entity(checks, min_count=2)
    assert [g.entity.name for g in groups] == ["Big Topic", "Small Topic"]


# --------------------------------------------------------------------------- #
# collections
# --------------------------------------------------------------------------- #


def test_collections_membership(checks):
    colls = content.collections(checks)
    assert all(c.verdict_key in ("False", "Mostly False") for c in colls["bs_files"])
    assert all(c.verdict_key in ("True", "Mostly True") for c in colls["checks_out"])


def test_collections_newest_first_and_capped(make_detail):
    docs = [
        make_detail(
            verdict="False",
            claim=f"false {i}",
            created_at=f"2026-01-{i + 1:02d}T00:00:00Z",
        )
        for i in range(COLLECTION_SIZE + 5)
    ]
    checks = content.build_checks(docs)
    bs = content.collections(checks)["bs_files"]
    assert len(bs) == COLLECTION_SIZE
    dates = [c.created_dt for c in bs]
    assert dates == sorted(dates, reverse=True)


# --------------------------------------------------------------------------- #
# paginate
# --------------------------------------------------------------------------- #


def test_paginate_empty_gives_one_empty_page():
    assert content.paginate([], 20) == [[]]


def test_paginate_splits_evenly(checks):
    pages = content.paginate(checks, 2)
    assert all(len(p) <= 2 for p in pages)
    flat = [c for page in pages for c in page]
    assert len(flat) == len(checks)


def test_paginate_exact_multiple(make_detail):
    docs = [make_detail(claim=str(i)) for i in range(4)]
    checks = content.build_checks(docs)
    pages = content.paginate(checks, 2)
    assert len(pages) == 2
    assert [len(p) for p in pages] == [2, 2]


class TestRelatedFallback:
    """Local entity-overlap 'MORE CHECKS' for keyless builds (no related API)."""

    def test_ranks_by_entity_overlap_then_recency(self, make_detail):
        docs = [
            make_detail(
                verification_id="base1234",
                entities=[{"name": "Alpha"}, {"name": "Beta"}],
            ),
            make_detail(  # two shared entities → strongest
                verification_id="two12345",
                entities=[{"name": "Alpha"}, {"name": "Beta"}],
                created_at="2026-07-01T00:00:00Z",
            ),
            make_detail(  # one shared entity, newer than the other single
                verification_id="one12345",
                entities=[{"name": "Alpha"}],
                created_at="2026-07-20T00:00:00Z",
            ),
            make_detail(  # one shared entity, older
                verification_id="oldshare",
                entities=[{"name": "Beta"}],
                created_at="2026-06-01T00:00:00Z",
            ),
            make_detail(  # no overlap → excluded
                verification_id="none1234",
                entities=[{"name": "Gamma"}],
            ),
        ]
        checks = content.build_checks(docs)
        base = next(c for c in checks if c.verification_id == "base1234")
        got = [c.verification_id for c in content.related_fallback(base, checks)]
        assert got == ["two12345", "one12345", "oldshare"]

    def test_excludes_self_and_respects_limit(self, make_detail):
        docs = [
            make_detail(verification_id=f"vid{i:05d}", entities=[{"name": "X"}])
            for i in range(9)
        ]
        checks = content.build_checks(docs)
        base = checks[0]
        got = content.related_fallback(base, checks, limit=3)
        assert len(got) == 3
        assert base.verification_id not in [c.verification_id for c in got]

    def test_no_entities_returns_empty(self, make_detail):
        docs = [
            make_detail(verification_id="lonely12", entities=[]),
            make_detail(verification_id="other123", entities=[{"name": "X"}]),
        ]
        checks = content.build_checks(docs)
        base = next(c for c in checks if c.verification_id == "lonely12")
        assert content.related_fallback(base, checks) == []


class TestEditorialFloor:
    """E1: thin checks never publish; the lead slot prefers receipts."""

    def test_too_few_sources_withheld(self, make_detail):
        doc = make_detail(
            verification_id="thin0001",
            sources=[{"source_name": "A", "title": "only one", "url": "https://x/1"}],
        )
        assert content.build_checks([doc]) == []

    def test_thin_summary_withheld(self, make_detail):
        doc = make_detail(verification_id="short001", executive_summary="Too short.")
        assert content.build_checks([doc]) == []

    def test_publishable_check_passes(self, make_detail):
        doc = make_detail(verification_id="good0001")  # factory defaults clear it
        assert len(content.build_checks([doc])) == 1

    def test_pick_lead_prefers_well_receipted(self, make_detail):
        three_sources = [
            {"source_name": f"S{i}", "title": f"t{i}", "url": f"https://x/{i}"}
            for i in range(3)
        ]
        docs = [
            make_detail(  # newest, but only the default 2 sources
                verification_id="newest01", created_at="2026-07-22T00:00:00Z"
            ),
            make_detail(  # older, 3 sources → wins the lead slot
                verification_id="lead0001",
                created_at="2026-07-10T00:00:00Z",
                sources=three_sources,
            ),
        ]
        checks = content.build_checks(docs)
        lead = content.pick_lead(checks)
        assert lead is not None and lead.verification_id == "lead0001"

    def test_pick_lead_falls_back_to_newest(self, make_detail):
        docs = [
            make_detail(verification_id="only0001", created_at="2026-07-22T00:00:00Z"),
            make_detail(verification_id="only0002", created_at="2026-07-01T00:00:00Z"),
        ]
        checks = content.build_checks(docs)
        lead = content.pick_lead(checks)
        assert lead is not None and lead.verification_id == "only0001"

    def test_pick_lead_empty(self):
        assert content.pick_lead([]) is None
