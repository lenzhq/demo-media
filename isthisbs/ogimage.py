"""Open Graph card generator (1200×630 PNG) — DESIGN.md §7.

Every article gets a share card rendered in the IsThisBS house style: newsprint
paper, the caution-yellow top bar, the claim set in Fraunces, and the verdict
block dual-labelled (BS label + canonical verdict) so the card reads correctly
even stripped of color. A single site-default card covers non-article pages.

Design notes:
- **Fonts are fetched at build time** into ``cache_dir/fonts/`` from the Google
  Fonts GitHub mirrors (verified reachable static TTFs — see ``_FONT_SOURCES``)
  so the *repo* stays font-free. If the download fails (offline build), we fall
  back to Pillow's bitmap default with a logged warning — card generation must
  never crash the build.
- **Rendering is incremental**: each card is cached under a content hash of
  ``claim + verdict + TEMPLATE_VERSION``. A build only re-renders cards whose
  content (or the template itself) changed; stale variants are pruned.

Text is wrapped by *measuring* with ``font.getlength`` / ``getbbox`` rather than
counting characters, so wrapping is correct for a proportional display face.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Verdict

logger = logging.getLogger(__name__)

# Bump when the card layout changes so every cached card re-renders.
TEMPLATE_VERSION = "1"

# Canvas + palette (DESIGN.md §3 / §7). Pillow accepts hex strings directly.
CARD_W, CARD_H = 1200, 630
PAPER = "#FAF7F0"
INK = "#141310"
INK_60 = "#5C574C"
ACCENT = "#FFD23F"
TOP_BAR_H = 12
MARGIN = 72

# Static TTFs verified present on the Google Fonts GitHub mirrors. Fraunces
# ships variable in google/fonts, so its *static* Black instance comes from the
# upstream googlefonts/fraunces repo (default branch: master).
_FRAUNCES_BASE = (
    "https://raw.githubusercontent.com/googlefonts/fraunces/master/fonts/static/ttf"
)
_PLEX_BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexmono"
_FONT_SOURCES: dict[str, str] = {
    "Fraunces72pt-Black.ttf": f"{_FRAUNCES_BASE}/Fraunces72pt-Black.ttf",
    "IBMPlexMono-SemiBold.ttf": f"{_PLEX_BASE}/IBMPlexMono-SemiBold.ttf",
    "IBMPlexMono-Regular.ttf": f"{_PLEX_BASE}/IBMPlexMono-Regular.ttf",
}
_DISPLAY = "Fraunces72pt-Black.ttf"
_MONO = "IBMPlexMono-SemiBold.ttf"
_MONO_LIGHT = "IBMPlexMono-Regular.ttf"

# Module-level font state, lazily populated by the first render.
_cache_dir: Path | None = None
_font_paths: dict[str, Path] | None = None
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #


def _ensure_fonts(cache_dir: Path) -> dict[str, Path]:
    """Download any missing TTFs into ``cache_dir/fonts/``; return name→path.

    Idempotent (skips files already present). A download failure logs a warning
    and drops that font from the map — the caller falls back to the default.
    """
    fonts_dir = cache_dir / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    available: dict[str, Path] = {}
    for name, url in _FONT_SOURCES.items():
        dest = fonts_dir / name
        if not dest.exists():
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = resp.read()
                dest.write_bytes(data)
                logger.info("Fetched OG font %s", name)
            except Exception as exc:  # offline build — degrade, never crash
                logger.warning("Could not fetch font %s (%s); using default", name, exc)
                continue
        available[name] = dest
    return available


def _font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A sized font, memoized. Falls back to Pillow's default when missing."""
    key = (name, size)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    path = (_font_paths or {}).get(name)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    if path and path.exists():
        font = ImageFont.truetype(str(path), size)
    else:
        try:
            font = ImageFont.load_default(size)  # Pillow >= 10.1
        except TypeError:  # older Pillow ignores size
            font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def _load_fonts_if_needed() -> None:
    global _font_paths
    if _font_paths is None:
        _font_paths = _ensure_fonts(_cache_dir or Path(".cache"))


# --------------------------------------------------------------------------- #
# Text helpers (measured, not counted)
# --------------------------------------------------------------------------- #


def _text_width(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, text: str) -> float:
    try:
        return font.getlength(text)
    except AttributeError:  # very old Pillow
        return font.getbbox(text)[2]


def _ellipsize(font, text: str, max_width: float) -> str:
    """Trim ``text`` (adding an ellipsis) until it fits ``max_width``."""
    if _text_width(font, text) <= max_width:
        return text
    ell = "…"
    trimmed = text
    while trimmed and _text_width(font, trimmed + ell) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed.rstrip() + ell) if trimmed else ell


def _wrap(font, text: str, max_width: float, max_lines: int) -> list[str]:
    """Greedy word-wrap by measured width, capped at ``max_lines``.

    If the text overflows the line budget the final line is ellipsized, so a
    long claim degrades gracefully rather than spilling off the card.
    """
    words = " ".join((text or "").split()).split(" ")
    lines: list[str] = []
    current = ""
    i = 0
    while i < len(words):
        word = words[i]
        trial = f"{current} {word}".strip()
        if not current or _text_width(font, trial) <= max_width:
            current = trial
            i += 1
        else:
            lines.append(current)
            current = ""
            if len(lines) == max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
        i = len(words)  # consumed everything

    if i < len(words) and lines:
        # Ran out of lines with words remaining — ellipsize the last line,
        # appending the leftover so the trim has material to eat into.
        remainder = " ".join(words[i:])
        lines[-1] = _ellipsize(font, f"{lines[-1]} {remainder}".strip(), max_width)
    elif lines:
        lines[-1] = _ellipsize(font, lines[-1], max_width)
    return lines or [""]


def _draw_tracked(draw, pos, text, font, fill, tracking) -> float:
    """Draw ``text`` with manual letter-spacing (Pillow has none). Returns the
    x advance. Used for the mono labels, whose tracked caps are a brand cue."""
    x, y = pos
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += _text_width(font, ch) + tracking
    return x - pos[0]


# --------------------------------------------------------------------------- #
# Card renderers (pure — given loaded fonts)
# --------------------------------------------------------------------------- #


def render_card(claim: str, verdict: Verdict) -> Image.Image:
    """Render one article's OG card: claim + dual-labelled verdict block."""
    _load_fonts_if_needed()
    img = Image.new("RGB", (CARD_W, CARD_H), PAPER)
    draw = ImageDraw.Draw(img)

    # Caution-yellow top bar.
    draw.rectangle([0, 0, CARD_W, TOP_BAR_H], fill=ACCENT)

    label_font = _font(_MONO, 26)
    _draw_tracked(draw, (MARGIN, 60), "THE CLAIM", label_font, INK_60, 4)

    # Claim in the display face, wrapped to <=5 lines.
    claim_font = _font(_DISPLAY, 66)
    line_h = 84
    max_text_w = CARD_W - 2 * MARGIN
    lines = _wrap(claim_font, f"“{claim}”", max_text_w, 5)
    y = 128
    for line in lines:
        draw.text((MARGIN, y), line, font=claim_font, fill=INK)
        y += line_h

    # --- Bottom-left verdict block ---
    block_y = CARD_H - 96
    square = 34
    draw.rectangle(
        [MARGIN, block_y, MARGIN + square, block_y + square],
        fill=verdict.fill_hex,
    )
    vfont = _font(_MONO, 30)
    tx = MARGIN + square + 20
    ty = block_y + (square - 30) // 2
    # BS label in the verdict's accessible text color, canonical verdict in ink.
    label = verdict.bs_label
    draw.text((tx, ty), label, font=vfont, fill=verdict.text_hex)
    tx += _text_width(vfont, label)
    draw.text(
        (tx, ty),
        f" — VERDICT: {verdict.key.upper()}",
        font=vfont,
        fill=INK,
    )

    # --- Bottom-right attribution ---
    attr_font = _font(_MONO_LIGHT, 24)
    attr = "IsThisBS?  ·  verified by Lenz"
    attr_w = _text_width(attr_font, attr)
    draw.text(
        (CARD_W - MARGIN - attr_w, block_y + 4),
        attr,
        font=attr_font,
        fill=INK_60,
    )
    return img


def render_site_card() -> Image.Image:
    """The site-default card for non-article pages: wordmark + tagline."""
    _load_fonts_if_needed()
    img = Image.new("RGB", (CARD_W, CARD_H), PAPER)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, CARD_W, TOP_BAR_H], fill=ACCENT)

    word_font = _font(_DISPLAY, 132)
    # Wordmark: "IsThis" + "BS" reversed out of a yellow block + "?".
    part1, part2, part3 = "IsThis", "BS", "?"
    w1 = _text_width(word_font, part1)
    w2 = _text_width(word_font, part2)
    w3 = _text_width(word_font, part3)
    pad = 16
    total = w1 + pad + w2 + pad + w3
    x = (CARD_W - total) / 2
    y = 210
    draw.text((x, y), part1, font=word_font, fill=INK)
    x += w1 + pad
    # Yellow block behind "BS" with an ink strikethrough.
    block_top = y + 18
    block_bottom = y + 150
    draw.rectangle([x - 8, block_top, x + w2 + 8, block_bottom], fill=ACCENT)
    draw.text((x, y), part2, font=word_font, fill=INK)
    strike_y = (block_top + block_bottom) / 2
    draw.line([x - 4, strike_y, x + w2 + 4, strike_y], fill=INK, width=6)
    x += w2 + pad
    draw.text((x, y), part3, font=word_font, fill=INK)

    tag_font = _font(_MONO, 30)
    tagline = "THE CLAIMS DESK · RECEIPTS INCLUDED"
    tw = _text_width(tag_font, tagline)
    draw.text(((CARD_W - tw) / 2, 400), tagline, font=tag_font, fill=INK_60)

    attr_font = _font(_MONO_LIGHT, 24)
    attr = "verified by Lenz"
    aw = _text_width(attr_font, attr)
    draw.text(((CARD_W - aw) / 2, 470), attr, font=attr_font, fill=INK_60)
    return img


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def _content_key(claim: str, verdict_key: str) -> str:
    """Short content hash keying the cache — id-independent so an edited claim
    or verdict yields a new cache file (and the old one gets pruned)."""
    raw = f"{claim}\x00{verdict_key}\x00{TEMPLATE_VERSION}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _prune_variants(og_cache: Path, prefix: str, keep: str) -> None:
    """Delete stale ``{prefix}-*.png`` cache files that aren't ``keep``."""
    for stale in og_cache.glob(f"{prefix}-*.png"):
        if stale.name != keep:
            try:
                stale.unlink()
            except OSError:
                logger.warning("Could not prune stale OG card %s", stale)


def generate(checks: list, cache_dir: Path, out_dir: Path) -> int:
    """Render every card (incrementally) and publish to ``out_dir/og/``.

    Returns the number of cards *newly* rendered this run. Cached cards are
    copied straight through; stale variants of a changed claim are pruned so
    the cache doesn't grow without bound.
    """
    global _cache_dir
    cache_dir = Path(cache_dir)
    out_dir = Path(out_dir)
    _cache_dir = cache_dir
    _load_fonts_if_needed()

    og_cache = cache_dir / "og"
    og_out = out_dir / "og"
    og_cache.mkdir(parents=True, exist_ok=True)
    og_out.mkdir(parents=True, exist_ok=True)

    rendered = 0
    for check in checks:
        vid = check.verification_id
        key = _content_key(check.claim, check.verdict.key)
        cache_file = og_cache / f"{vid}-{key}.png"
        if not cache_file.exists():
            render_card(check.claim, check.verdict).save(cache_file, "PNG")
            rendered += 1
        _prune_variants(og_cache, vid, cache_file.name)
        shutil.copyfile(cache_file, og_out / f"{vid}.png")

    # Site-default card (keyed only on the template version).
    site_key = _content_key("__site__", "__site__")
    site_cache = og_cache / f"site-{site_key}.png"
    if not site_cache.exists():
        render_site_card().save(site_cache, "PNG")
        rendered += 1
    _prune_variants(og_cache, "site", site_cache.name)
    shutil.copyfile(site_cache, og_out / "site.png")

    logger.info("OG cards: %d newly rendered, %d total", rendered, len(checks) + 1)
    return rendered
