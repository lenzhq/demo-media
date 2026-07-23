"""Tests for the OG card generator — forced onto the offline default-font path."""

from __future__ import annotations

import pytest
from PIL import Image

from isthisbs import content, ogimage
from isthisbs.config import VERDICTS


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


def test_render_card_dimensions_all_verdicts():
    for verdict in VERDICTS.values():
        img = ogimage.render_card("Some claim under examination.", verdict)
        assert isinstance(img, Image.Image)
        assert img.size == (1200, 630)


def test_render_site_card_dimensions():
    img = ogimage.render_site_card()
    assert img.size == (1200, 630)


def test_render_card_offline_uses_no_downloaded_fonts(tmp_path):
    ogimage.render_card("Claim", next(iter(VERDICTS.values())))
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
        card = out_dir / "og" / f"{check.verification_id}.png"
        assert card.is_file()
        assert Image.open(card).size == (1200, 630)
    site = out_dir / "og" / "site.png"
    assert site.is_file()
    assert Image.open(site).size == (1200, 630)


def test_generate_is_incremental(tmp_path, make_detail):
    checks = _checks(make_detail)
    cache_dir = tmp_path / "cache"
    out_dir = tmp_path / "out"
    first = ogimage.generate(checks, cache_dir, out_dir)
    second = ogimage.generate(checks, cache_dir, out_dir)
    assert first == len(checks) + 1
    assert second == 0  # nothing changed → nothing re-rendered


def test_generate_content_key_is_deterministic():
    a = ogimage._content_key("same claim", "False")
    b = ogimage._content_key("same claim", "False")
    c = ogimage._content_key("other claim", "False")
    assert a == b
    assert a != c
