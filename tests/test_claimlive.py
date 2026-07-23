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
