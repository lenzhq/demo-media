#!/usr/bin/env python3
"""IsThisBS? static-site builder — the thin CLI over the ``isthisbs`` package.

This is the reference implementation of "build something real on the Lenz
public API." It is deliberately small and linear: every real step lives in a
package module (``fetch``, ``content``, ``render``, ``seo``, ``ogimage``); this
file only wires them together, times each stage, and owns the CLI surface.

Pipeline
--------
    1. fetch    — incrementally sync the public catalog into ``.cache/``
                  (skipped with ``--skip-fetch`` to rebuild fully offline).
    2. content  — parse the cache into ``Check`` objects and filter/sort.
    3. render   — write every HTML page into ``dist/``.
    4. seo      — sitemaps, feeds, robots.txt, llms.txt, JSON-LD assets.
    5. og       — 1200x630 OG card PNGs (``--skip-og`` to skip).
    6. search   — run Pagefind over ``dist/`` (``--skip-search`` to skip;
                  a missing Pagefind is a warning, never a build failure).

Every read is keyless — no credentials are required to run this from a fresh
checkout. Exit code is 0 on success, non-zero with a clear message on a fatal
error (no claims, a render/seo failure, etc.).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from isthisbs import content, discussions, fetch, ogimage, render, seo

logger = logging.getLogger("isthisbs.build")


# --------------------------------------------------------------------------- #
# Small timing helper — keeps each stage's log line uniform.
# --------------------------------------------------------------------------- #


class _Stage:
    """Context manager that logs a stage's start, wall-clock, and outcome."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._t0 = 0.0

    def __enter__(self) -> _Stage:
        self._t0 = time.monotonic()
        logger.info("→ %s …", self.name)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        dt = time.monotonic() - self._t0
        if exc_type is None:
            logger.info("✓ %s (%.2fs)", self.name, dt)
        else:
            logger.error("✗ %s failed after %.2fs: %s", self.name, dt, exc)
        return False  # never swallow — let fatal errors propagate to main()


# --------------------------------------------------------------------------- #
# Client construction
# --------------------------------------------------------------------------- #


def _make_client():
    """Build a keyless Lenz client.

    The SDK accepts ``base_url=None`` and falls back to ``LENZ_BASE_URL`` then
    its built-in default (``https://lenz.io/api/v1``), so passing the env var
    through — even when unset — is the correct one-liner. No API key is passed:
    every catalog read this site makes is public and keyless.
    """
    from lenz_io import Lenz

    return Lenz(base_url=os.environ.get("LENZ_BASE_URL"))


# --------------------------------------------------------------------------- #
# Search (Pagefind) — optional, best-effort.
# --------------------------------------------------------------------------- #


def _run_pagefind(out_dir: Path) -> bool:
    """Index ``out_dir`` with Pagefind for client-side search.

    Tries a ``pagefind`` binary on PATH first (fastest, no wrapper), then the
    pip wheel (``python -m pagefind``), then the npm runner (``npx pagefind``).
    Search is a progressive enhancement — if none are available we warn and
    return ``False`` so the build still succeeds; the site just ships without
    its search index.
    """
    attempts = [
        ["pagefind", "--site", str(out_dir)],
        [sys.executable, "-m", "pagefind", "--site", str(out_dir)],
        ["npx", "-y", "pagefind", "--site", str(out_dir)],
    ]
    for cmd in attempts:
        try:
            subprocess.run(cmd, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            logger.debug("Pagefind attempt %r failed: %s", cmd[0], exc)
            continue
        else:
            logger.info("Pagefind indexed %s via %r", out_dir, cmd[0])
            return True
    logger.warning(
        "Pagefind unavailable (tried `pagefind`, `python -m pagefind`, `npx`). "
        "Search will be disabled; the rest of the site is unaffected. "
        "Install with `pip install 'pagefind[extended]'` to enable it."
    )
    return False


# --------------------------------------------------------------------------- #
# Build pipeline
# --------------------------------------------------------------------------- #


def build(args: argparse.Namespace) -> int:
    """Run the full pipeline. Returns a process exit code."""
    out_dir = Path(args.out)
    cache_dir = Path(args.cache)

    # 1. Fetch — sync the public catalog into the incremental cache.
    if args.skip_fetch:
        logger.info("Skipping fetch (--skip-fetch); building from existing cache.")
    else:
        with _Stage("fetch"):
            client = _make_client()
            try:
                stats = fetch.sync(client, cache_dir, max_pages=args.max_pages)
                logger.info("%s", stats)
            finally:
                # The SDK holds a persistent httpx connection pool; close it.
                close = getattr(client, "close", None)
                if callable(close):
                    close()

    # 1b. Discussions — bake community counts (CI has GITHUB_TOKEN; locally
    # this degrades to the cached file, or the zero state with none).
    if not args.skip_fetch:
        with _Stage("discussions"):
            discussions.sync(cache_dir)
    dmap = discussions.load(cache_dir)

    # 2. Content — parse the cache into the editorial model.
    with _Stage("content"):
        raw = fetch.load_raw(cache_dir)
        checks = content.build_checks(raw)
    if not checks:
        logger.error(
            "No checks to render (cache at %s is empty or fully filtered out). "
            "Run without --skip-fetch to populate the cache first.",
            cache_dir,
        )
        return 1
    logger.info("Built %d check(s) for rendering.", len(checks))

    # 3. Render — (re)create the output tree, then write every HTML page.
    with _Stage("render"):
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        render.render_site(checks, out_dir, discussions=dmap)

    # 4. SEO — sitemaps, feeds, robots.txt, llms.txt, and friends.
    with _Stage("seo"):
        seo.write_assets(checks, out_dir)

    # 5. OG images — brand cards, hash-cached in the .cache tree.
    if args.skip_og:
        copied = ogimage.copy_cached(cache_dir, out_dir)
        logger.info(
            "Skipping OG rendering (--skip-og); copied %d cached card(s).", copied
        )
    else:
        with _Stage("og-images"):
            count = ogimage.generate(checks, cache_dir, out_dir)
            logger.info("Generated/copied %d OG image(s).", count)

    # 6. Search — Pagefind index (best-effort; never fatal).
    if args.skip_search:
        logger.info("Skipping search index (--skip-search).")
    else:
        with _Stage("search"):
            _run_pagefind(out_dir)

    logger.info("Build complete → %s", out_dir)
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Build the IsThisBS? static site from the public Lenz API.",
    )
    parser.add_argument(
        "--out",
        default="dist",
        help="Output directory for the generated site (default: dist).",
    )
    parser.add_argument(
        "--cache",
        default=".cache",
        help="Incremental fetch/OG cache directory (default: .cache).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help=(
            "Dev/smoke knob: walk at most N catalog pages (20 items each). "
            "Also disables the stale-id drop pass, since a partial walk must "
            "never mass-delete the cache. Omit for a full sync."
        ),
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Build entirely from the existing cache (no network calls).",
    )
    parser.add_argument(
        "--skip-og",
        action="store_true",
        help="Skip OG image generation.",
    )
    parser.add_argument(
        "--skip-search",
        action="store_true",
        help="Skip building the Pagefind search index.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        return build(args)
    except Exception as exc:  # top-level guard → clean non-zero exit, no spew
        logger.error("Build failed: %s", exc, exc_info=args.verbose)
        return 2


if __name__ == "__main__":
    sys.exit(main())
