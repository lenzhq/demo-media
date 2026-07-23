"""Tests for the build.py CLI: argparse surface + an offline full-pipeline run."""

from __future__ import annotations

import pytest

import build
from isthisbs import ogimage

# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #


def test_parse_args_defaults():
    args = build._parse_args([])
    assert args.out == "dist"
    assert args.cache == ".cache"
    assert args.max_pages is None
    assert args.skip_fetch is False
    assert args.skip_og is False
    assert args.skip_search is False


def test_parse_args_flags():
    args = build._parse_args(
        [
            "--skip-fetch",
            "--skip-og",
            "--skip-search",
            "--max-pages",
            "2",
            "--out",
            "build-out",
            "--cache",
            "build-cache",
        ]
    )
    assert args.skip_fetch is True
    assert args.skip_og is True
    assert args.skip_search is True
    assert args.max_pages == 2
    assert args.out == "build-out"
    assert args.cache == "build-cache"


# --------------------------------------------------------------------------- #
# Offline full pipeline via --skip-fetch
# --------------------------------------------------------------------------- #


@pytest.fixture
def offline(monkeypatch):
    """No network anywhere: fake the Pagefind subprocess + OG font downloads."""

    def _fake_run(cmd, *args, **kwargs):
        return None  # pretend Pagefind indexed successfully

    monkeypatch.setattr(build.subprocess, "run", _fake_run)

    def _boom(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(ogimage.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(ogimage, "_font_paths", None)
    ogimage._font_cache.clear()
    yield
    ogimage._font_cache.clear()


def test_skip_fetch_full_pipeline_offline(tmp_path, make_detail, write_cache, offline):
    cache_dir = tmp_path / "cache"
    out_dir = tmp_path / "dist"
    docs = [
        make_detail(claim="alpha claim", verdict="False", domain="health"),
        make_detail(claim="beta claim", verdict="True", domain="science"),
    ]
    write_cache(cache_dir, docs)

    rc = build.main(["--skip-fetch", "--out", str(out_dir), "--cache", str(cache_dir)])
    assert rc == 0

    # The pipeline produced the core of the site.
    assert (out_dir / "index.html").is_file()
    assert (out_dir / "404.html").is_file()
    assert (out_dir / "about" / "index.html").is_file()
    assert (out_dir / "robots.txt").is_file()
    assert (out_dir / "sitemap.xml").is_file()
    assert (out_dir / "llms.txt").is_file()
    assert (out_dir / "og" / "site.png").is_file()


def test_skip_fetch_empty_cache_exits_nonzero(tmp_path, offline):
    cache_dir = tmp_path / "empty-cache"
    (cache_dir / "claims").mkdir(parents=True)
    out_dir = tmp_path / "dist"
    rc = build.main(
        [
            "--skip-fetch",
            "--skip-og",
            "--skip-search",
            "--out",
            str(out_dir),
            "--cache",
            str(cache_dir),
        ]
    )
    assert rc == 1  # no checks to render
