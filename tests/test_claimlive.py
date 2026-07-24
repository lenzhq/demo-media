"""Offline tests for the /c/ short-link system: stubs + the claimlive core."""

from __future__ import annotations

import json
import urllib.request

import pytest

from functions import live_core
from isthisbs import content, ogimage, render


@pytest.fixture(autouse=True)
def _offline_fonts(monkeypatch, tmp_path):
    """OG rendering must not hit the network in tests (default-font path)."""
    monkeypatch.setattr(ogimage, "_cache_dir", tmp_path)
    monkeypatch.setattr(ogimage, "_font_paths", None)
    monkeypatch.setattr(ogimage, "_font_cache", {})
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )


def _detail(**over):
    d = {
        "verification_id": "abc12345",
        "claim": "The moon is made of rock.",
        "verdict": "True",
        "domain": "Science",
        "executive_summary": "Yes — rock, confirmed by many missions.",
    }
    d.update(over)
    return d


class TestStubs:
    def test_every_check_gets_a_stub(self, tmp_path, checks):
        render.render_site(checks, tmp_path)
        for check in checks:
            stub = tmp_path / "c" / check.verification_id / "index.html"
            assert stub.is_file()
            body = stub.read_text(encoding="utf-8")
            assert f'<link rel="canonical" href="{check.url}">' in body
            assert 'content="noindex"' in body
            assert f"url={check.path}" in body  # meta refresh target
            assert check.og_path in body  # static card meta for re-crawls


class TestLiveCore:
    def test_fetch_rejects_hostile_ids(self):
        for bad in ("../etc", "a/b", "", "x" * 65):
            assert live_core.fetch_detail(bad) is None

    def test_html_escapes_api_strings(self):
        html_out = live_core.build_live_html(
            _detail(claim='<script>alert(1)</script> & "quotes"')
        )
        assert "<script>alert(1)" not in html_out
        assert "&lt;script&gt;" in html_out

    def test_html_carries_og_and_canonical(self):
        html_out = live_core.build_live_html(_detail())
        assert (
            'property="og:image" content="https://isthisbs.org/og-live/abc12345.png"'
            in html_out
        )
        assert 'name="twitter:card" content="summary_large_image"' in html_out
        assert 'content="noindex"' in html_out
        # canonical = minted future article URL (section + slug + id)
        slug = content.mint_slug("The moon is made of rock.", "abc12345")
        assert (
            f'rel="canonical" href="https://isthisbs.org/science/{slug}/"' in html_out
        )
        assert "NOT BS" in html_out and "Verdict: True" in html_out

    def test_error_verdict_refused(self, monkeypatch):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(_detail(verdict="Error")).encode()

        monkeypatch.setattr(
            live_core.urllib.request, "urlopen", lambda *a, **k: _Resp()
        )
        assert live_core.fetch_detail("abc12345") is None

    def test_card_png_dimensions(self):
        png = live_core.build_card_png(_detail())
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        import io

        from PIL import Image

        assert Image.open(io.BytesIO(png)).size == (1200, 630)


def test_live_page_card_carries_summary_and_caveats():
    """The /c/ interim page: og:description leads verdict-then-summary, and
    the body renders the caveats list when warnings exist."""
    from functions.live_core import build_live_html

    detail = _detail()
    detail["executive_summary"] = "Solid evidence contradicts the stated numbers. " * 8
    detail["warnings"] = [
        "Numbers come from two different datasets.",
        "<script>x</script>",
    ]
    page = build_live_html(detail)
    # description: verdict label first, then trimmed summary, ellipsis capped
    assert 'og:description" content="' in page
    desc = page.split('og:description" content="')[1].split('"')[0]
    assert desc.startswith(("NOT BS", "HARDLY BS", "SOME BS", "MOSTLY BS", "TOTAL BS"))
    assert "Solid evidence contradicts" in desc and desc.endswith("…")
    # caveats render, escaped
    assert "Caveats" in page
    assert "Numbers come from two different datasets." in page
    assert "<script>x</script>" not in page and "&lt;script&gt;" in page


def test_live_page_no_caveats_section_without_warnings():
    from functions.live_core import build_live_html

    detail = _detail()
    detail.pop("warnings", None)
    assert "Caveats" not in build_live_html(detail)


def test_live_page_receipts_render_capped_and_safe():
    """Receipts: capped at RECEIPTS_MAX, +N-more tail, http(s)-only links,
    everything escaped."""
    from functions.live_core import RECEIPTS_MAX, build_live_html

    detail = _detail()
    detail["sources"] = [
        {
            "title": f"Source {i} <b>bold</b>",
            "url": f"https://example.org/{i}",
            "source_name": "Example Org",
            "date": "2026-07-01T00:00:00+00:00",
        }
        for i in range(RECEIPTS_MAX + 3)
    ] + [{"title": "evil", "url": "javascript:alert(1)"}]
    page = build_live_html(detail)
    assert "The Receipts" in page
    assert page.count('rel="noopener nofollow"') == RECEIPTS_MAX
    assert "+ 3 more sources" in page
    assert "javascript:alert" not in page
    assert "<b>bold</b>" not in page and "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "Jul 1, 2026" in page


def test_live_page_no_receipts_section_without_sources():
    from functions.live_core import build_live_html

    assert "The Receipts" not in build_live_html(_detail())
