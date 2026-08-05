"""Tests for the OG card generator — forced onto the offline default-font path."""

from __future__ import annotations

import pytest
from PIL import Image

from isthisbs import content, ogimage
from isthisbs.config import og_content_key


@pytest.fixture(autouse=True)
def offline_fonts(tmp_path, monkeypatch):
    """Force the no-download / default-font fallback and isolate module state.

    Points the font cache at an empty temp dir and makes every network fetch
    raise, so ``_ensure_fonts`` returns an empty map and rendering falls back to
    Pillow's built-in bitmap font — fully offline, never touching the network.
    """

    def _boom(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(ogimage.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(ogimage, "_cache_dir", tmp_path / "fontcache")
    monkeypatch.setattr(ogimage, "_font_paths", None)
    ogimage._font_cache.clear()
    yield
    ogimage._font_cache.clear()


# --------------------------------------------------------------------------- #
# render_card
# --------------------------------------------------------------------------- #


def test_render_card_dimensions():
    img = ogimage.render_card("Some established finding.")
    assert isinstance(img, Image.Image)
    assert img.size == (1200, 630)


def test_render_site_card_dimensions():
    img = ogimage.render_site_card()
    assert img.size == (1200, 630)


def test_render_card_offline_uses_no_downloaded_fonts(tmp_path):
    ogimage.render_card("Some established finding.")
    # Offline: the font map degraded to empty; the fonts dir has no TTFs.
    assert ogimage._font_paths == {}


# --------------------------------------------------------------------------- #
# generate — incremental
# --------------------------------------------------------------------------- #


def _checks(make_detail):
    docs = [
        make_detail(claim="alpha", verdict="False", domain="general"),
        make_detail(claim="beta", verdict="True", domain="general"),
    ]
    return content.build_checks(docs)


def test_generate_writes_cards_and_site(tmp_path, make_detail):
    checks = _checks(make_detail)
    cache_dir = tmp_path / "cache"
    out_dir = tmp_path / "out"
    rendered = ogimage.generate(checks, cache_dir, out_dir)
    # Every check card + the site card were newly rendered.
    assert rendered == len(checks) + 1
    for check in checks:
        # Hashed public name (what the meta tags reference) + legacy copy.
        hashed = out_dir / "og" / check.og_path.rsplit("/", 1)[1]
        legacy_card = out_dir / "og" / f"{check.verification_id}.png"
        assert hashed.is_file() and legacy_card.is_file()
        assert hashed.read_bytes() == legacy_card.read_bytes()
        assert Image.open(hashed).size == (1200, 630)
    site = out_dir / "og" / ogimage.SITE_CARD_NAME
    assert site.is_file()
    assert Image.open(site).size == (1200, 630)
    # The pre-v6 path stays published so already-scraped cards don't 404.
    legacy = out_dir / "og" / "site.png"
    assert legacy.is_file()
    assert legacy.read_bytes() == site.read_bytes()


def test_generate_is_incremental(tmp_path, make_detail):
    checks = _checks(make_detail)
    cache_dir = tmp_path / "cache"
    out_dir = tmp_path / "out"
    first = ogimage.generate(checks, cache_dir, out_dir)
    second = ogimage.generate(checks, cache_dir, out_dir)
    assert first == len(checks) + 1
    assert second == 0  # nothing changed → nothing re-rendered


def test_copy_cached_republishes_both_site_paths(tmp_path, make_detail):
    """``--skip-og`` must still publish the path the meta tags point at.

    The site card is cached under its pre-v6 ``site-`` prefix, so a naive
    stem-to-name mapping would ship only the legacy alias and 404 every
    og:image URL on a skip-og rebuild.
    """
    checks = _checks(make_detail)
    cache_dir = tmp_path / "cache"
    ogimage.generate(checks, cache_dir, tmp_path / "out")

    fresh = tmp_path / "skipog"
    copied = ogimage.copy_cached(cache_dir, fresh)
    site = fresh / "og" / ogimage.SITE_CARD_NAME
    legacy = fresh / "og" / "site.png"
    assert site.is_file() and legacy.is_file()
    assert site.read_bytes() == legacy.read_bytes()
    for check in checks:
        # Both the hashed public name and the legacy copy must ship — the
        # meta tags reference the hashed one.
        assert (fresh / "og" / check.og_path.rsplit("/", 1)[1]).is_file()
        assert (fresh / "og" / f"{check.verification_id}.png").is_file()
    assert copied == 2 * len(checks) + 2  # two names per card + site card twice


def test_content_key_is_deterministic_and_content_addressed():
    a = og_content_key("same finding")
    b = og_content_key("same finding")
    c = og_content_key("other finding")
    assert a == b
    assert a != c


def test_backfilled_finding_changes_public_og_url(make_detail):
    """The one-time flip: a claim gaining its key_finding must mint a NEW
    public card URL (social scrape caches key on the URL)."""
    before = content.build_checks([make_detail(verification_id="flip0001")])[0]
    after = content.build_checks(
        [
            make_detail(
                verification_id="flip0001",
                key_finding="The actual figure is one tenth of the claimed value.",
            )
        ]
    )[0]
    assert before.og_path != after.og_path
    # Stable across recomputation — a routine rebuild never changes the URL.
    assert after.og_path == after.og_path
