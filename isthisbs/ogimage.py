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
TEMPLATE_VERSION = "6"  # v6: site card uses the real wordmark lockup

# Canvas + palette (DESIGN.md §3 / §7). Pillow accepts hex strings directly.
CARD_W, CARD_H = 1200, 630
PAPER = "#FAF7F0"
INK = "#141310"
INK_60 = "#5C574C"
ACCENT = "#FFD23F"
TOP_BAR_H = 12
MARGIN = 72

# Wordmark lockup — mirrors `.wordmark*` in static/css/site.css so the share
# card and the masthead read as the same mark. Values are em fractions of the
# lockup font size, lifted from the computed styles of the live header.
CHIP_BG = "#171717"  # .wordmark__mark background
CHIP_BS = "#FBF9F2"  # .wordmark__bs
CHIP_Q = ACCENT  # .wordmark__q
LOCKUP_TRACKING = -0.02  # letter-spacing: -0.02em
LOCKUP_GAP = 0.14  # .wordmark { gap: 0.14em }
CHIP_PAD_X, CHIP_PAD_TOP, CHIP_PAD_BOTTOM = 0.16, 0.06, 0.10  # chip padding
CHIP_RADIUS = 0.16  # border-radius: 0.16em

#: Published filename of the site-default card. Article cards are named for
#: their verification id; this one carries the brand instead of "site" so it is
#: identifiable wherever it gets saved or inspected.
SITE_CARD_NAME = "isthisbs.png"
#: Retained so pre-v6 links keep resolving — see ``generate``.
_LEGACY_SITE_CARD_NAME = "site.png"

# Static TTFs verified present on the Google Fonts GitHub mirrors. Fraunces
# ships variable in google/fonts, so its *static* Black instance comes from the
# upstream googlefonts/fraunces repo (default branch: master).
_FRAUNCES_BASE = (
    "https://raw.githubusercontent.com/googlefonts/fraunces/master/fonts/static/ttf"
)
_PLEX_BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexmono"
_INTER_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/"
    "Inter%5Bopsz,wght%5D.ttf"
)
_FONT_SOURCES: dict[str, str] = {
    "Fraunces72pt-Black.ttf": f"{_FRAUNCES_BASE}/Fraunces72pt-Black.ttf",
    "IBMPlexMono-SemiBold.ttf": f"{_PLEX_BASE}/IBMPlexMono-SemiBold.ttf",
    "IBMPlexMono-Regular.ttf": f"{_PLEX_BASE}/IBMPlexMono-Regular.ttf",
    "Inter-Variable.ttf": _INTER_URL,
}
_DISPLAY = "Fraunces72pt-Black.ttf"
_MONO = "IBMPlexMono-SemiBold.ttf"
_MONO_LIGHT = "IBMPlexMono-Regular.ttf"
# The masthead chip is set in the system UI sans at weight 900 — SF Pro Black on
# Apple platforms. Inter is that face's closest open relative: instanced at
# opsz 32 / wght 900 its "BS?" measures within 2% of the live mark, so the card
# and the header read as one lockup. Embedding it (rather than reaching for a
# system font) keeps the card byte-identical on every build host.
_SANS_BLACK = "Inter-Variable.ttf"
_SANS_BLACK_AXES = [32.0, 900.0]  # (Optical size, Weight) — see get_variation_axes

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
        try:
            font = ImageFont.truetype(str(path), size)
            if name == _SANS_BLACK:
                # Inter ships variable-only; pin the Black display instance.
                # A FreeType build without variation support would leave the
                # chip at Regular — visibly wrong, but never a failed build.
                try:
                    font.set_variation_by_axes(_SANS_BLACK_AXES)
                except (OSError, AttributeError) as exc:
                    logger.warning("Could not instance %s Black (%s)", name, exc)
        except OSError:
            # A corrupt/truncated cached TTF (interrupted download) must take
            # the fallback path, not crash the build. Remove it so the next
            # run re-fetches a clean copy.
            logger.warning("Corrupt cached font %s — removing, using default", path)
            path.unlink(missing_ok=True)
            font = _default_font(size)
            _font_cache[key] = font
            return font
    else:
        font = _default_font(size)
    _font_cache[key] = font
    return font


def _default_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size)  # Pillow >= 10.1
    except TypeError:  # older Pillow ignores size
        return ImageFont.load_default()


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
    # Cut at a word boundary — "paral…" reads sloppy; drop the partial word
    # (keep the char-level cut when even the first word doesn't fit).
    if " " in trimmed.strip():
        trimmed = trimmed[: trimmed.rstrip().rfind(" ")]
    return (trimmed.rstrip(" ,;:—-") + ell) if trimmed else ell


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


def _tracked_width(font, text: str, tracking: float) -> float:
    """Measured width of tracked ``text`` — no trailing letter-space, which is
    what CSS does and what the lockup needs to center honestly."""
    if not text:
        return 0.0
    return sum(_text_width(font, ch) for ch in text) + tracking * (len(text) - 1)


def _draw_tracked_baseline(draw, x, baseline, text, font, fill, tracking) -> float:
    """``_draw_tracked`` anchored on the baseline (``anchor="ls"``).

    The lockup aligns the serif and the chip's sans on a shared baseline — the
    same thing ``align-items: baseline`` does in the masthead — so both faces
    must be positioned by baseline, not by their differing ascent boxes.
    """
    start = x
    for ch in text:
        draw.text((x, baseline), ch, font=font, fill=fill, anchor="ls")
        x += _text_width(font, ch) + tracking
    return x - start - tracking if text else 0.0


# --------------------------------------------------------------------------- #
# Card renderers (pure — given loaded fonts)
# --------------------------------------------------------------------------- #


def render_card(claim: str, verdict: Verdict) -> Image.Image:
    """Render one article's OG card: claim + dual-labelled verdict block.

    Layout (v3, after visual review of 10 rendered cards):
    - attribution sits top-RIGHT on the kicker line (folio convention) so the
      bottom row belongs entirely to the verdict — "MOSTLY TRUE"-length
      suffixes always fit now instead of silently disappearing;
    - the claim scales 72→48px by length and is vertically centered between
      kicker and verdict, so one-liners don't strand a void and five-liners
      keep guaranteed air above the verdict row.
    """
    _load_fonts_if_needed()
    img = Image.new("RGB", (CARD_W, CARD_H), PAPER)
    draw = ImageDraw.Draw(img)

    # Caution-yellow top bar.
    draw.rectangle([0, 0, CARD_W, TOP_BAR_H], fill=ACCENT)

    label_font = _font(_MONO, 26)
    _draw_tracked(draw, (MARGIN, 60), "THE CLAIM", label_font, INK_60, 4)

    # Attribution — top-right, opposite the kicker.
    attr_font = _font(_MONO_LIGHT, 22)
    # The handle rides on every share card — the cards travel on X itself,
    # so this advertises the reply bot in the medium where it works.
    attr = "IsThisBS?  ·  @isthisbs  ·  verified by Lenz"
    attr_w = _text_width(attr_font, attr)
    draw.text((CARD_W - MARGIN - attr_w, 62), attr, font=attr_font, fill=INK_60)

    # --- Claim: adaptive size, vertically centered in its area ---
    area_top = 132
    # 150 (not 96) from the bottom: X's timeline title-pill overlays roughly
    # the bottom 75px of the card — the verdict row must clear it.
    block_y = CARD_H - 150
    area_bottom = block_y - 36  # guaranteed air above the verdict row
    max_text_w = CARD_W - 2 * MARGIN
    quoted = f"“{claim}”"
    lines: list[str] = []
    claim_font = _font(_DISPLAY, 48)
    line_h = 60
    for size in (72, 64, 56, 48):
        font = _font(_DISPLAY, size)
        lh = int(size * 1.24)
        max_lines = max(1, (area_bottom - area_top) // lh)
        wrapped = _wrap(font, quoted, max_text_w, max_lines)
        # Accept the first size whose wrap needed no truncation; the smallest
        # size takes whatever fits (with word-boundary ellipsis from _wrap).
        joined = "".join(wrapped)
        if not joined.endswith("…") or size == 48:
            claim_font, line_h, lines = font, lh, wrapped
            break
    text_h = len(lines) * line_h
    y = area_top + max(0, (area_bottom - area_top - text_h) // 2)
    for line in lines:
        draw.text((MARGIN, y), line, font=claim_font, fill=INK)
        y += line_h

    # --- Bottom verdict row (owns the full width now) ---
    square = 34
    draw.rectangle(
        [MARGIN, block_y, MARGIN + square, block_y + square],
        fill=verdict.fill_hex,
    )
    vfont = _font(_MONO, 30)
    tx = MARGIN + square + 20
    ty = block_y + (square - 30) // 2
    label = verdict.bs_label
    suffix = f" — VERDICT: {verdict.key.upper()}"
    draw.text((tx, ty), label, font=vfont, fill=verdict.text_hex)
    if _text_width(vfont, label + suffix) <= CARD_W - MARGIN - tx:
        draw.text((tx + _text_width(vfont, label), ty), suffix, font=vfont, fill=INK)
    return img


def draw_wordmark(draw, center_x: float, baseline: float, size: int) -> None:
    """Draw the IsThisBS? lockup centered on ``center_x``, sat on ``baseline``.

    A pixel translation of the masthead's `.wordmark` rule: serif "IsThis" in
    ink, then the @isthisbs mark — a dark rounded chip with "BS" reversed out
    in paper white and a caution-yellow "?" — both faces sharing one baseline.
    There is no strikethrough and no yellow highlight; those belonged to an
    older mark and made the card contradict the site it links to.
    """
    serif = _font(_DISPLAY, size)
    sans = _font(_SANS_BLACK, size)
    tracking = LOCKUP_TRACKING * size

    ink_w = _tracked_width(serif, "IsThis", tracking)
    bs_w = _tracked_width(sans, "BS", tracking)
    q_w = _tracked_width(sans, "?", tracking)
    # "BS" and "?" are adjacent inline spans: one shared letter-space joins them.
    mark_text_w = bs_w + tracking + q_w
    pad_x = CHIP_PAD_X * size
    chip_w = mark_text_w + 2 * pad_x
    total = ink_w + LOCKUP_GAP * size + chip_w

    x = center_x - total / 2
    _draw_tracked_baseline(draw, x, baseline, "IsThis", serif, INK, tracking)
    x += ink_w + LOCKUP_GAP * size

    # Chip box: a line-height:1 box around the sans, plus the CSS padding.
    ascent, descent = sans.getmetrics()
    half_leading = (size - (ascent + descent)) / 2
    box_top = baseline - ascent - half_leading
    chip = [
        x,
        box_top - CHIP_PAD_TOP * size,
        x + chip_w,
        box_top + size + CHIP_PAD_BOTTOM * size,
    ]
    draw.rounded_rectangle(chip, radius=CHIP_RADIUS * size, fill=CHIP_BG)

    tx = x + pad_x
    _draw_tracked_baseline(draw, tx, baseline, "BS", sans, CHIP_BS, tracking)
    _draw_tracked_baseline(
        draw, tx + bs_w + tracking, baseline, "?", sans, CHIP_Q, tracking
    )


def render_site_card() -> Image.Image:
    """The site-default card for non-article pages: wordmark + tagline."""
    _load_fonts_if_needed()
    img = Image.new("RGB", (CARD_W, CARD_H), PAPER)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, CARD_W, TOP_BAR_H], fill=ACCENT)

    draw_wordmark(draw, CARD_W / 2, baseline=330, size=128)

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


def copy_cached(cache_dir: Path, out_dir: Path) -> int:
    """Copy already-rendered cards from the cache into ``out_dir/og/``.

    Used by ``--skip-og`` builds: skipping should skip the (slow) rendering,
    not lose the cards from the output — the render step wipes ``out_dir``,
    so without this every skip-og rebuild shipped a site whose og:image
    URLs 404. Costs ~0.2s for a full catalog.
    """
    og_cache = Path(cache_dir) / "og"
    if not og_cache.is_dir():
        return 0
    dest = Path(out_dir) / "og"
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for png in og_cache.glob("*.png"):
        # Cached names are ``{id}-{hash}.png``; published names are ``{id}.png``.
        public = png.stem.rsplit("-", 1)[0] + ".png" if "-" in png.stem else png.name
        shutil.copyfile(png, dest / public)
        copied += 1
        if public == _LEGACY_SITE_CARD_NAME:
            # The site card is cached under its old "site-" prefix but ships
            # under both names; skip-og builds must publish the one the meta
            # tags actually reference, not just the legacy alias.
            shutil.copyfile(png, dest / SITE_CARD_NAME)
            copied += 1
    return copied


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
    shutil.copyfile(site_cache, og_out / SITE_CARD_NAME)
    # Legacy alias: the card shipped as site.png until the v6 relayout. Social
    # scrapers key their caches on the image URL, so publishing under a new
    # name is what forces them to re-fetch — but anything already pointing at
    # the old path (a scraped card, an external embed) must not 404.
    shutil.copyfile(site_cache, og_out / _LEGACY_SITE_CARD_NAME)

    logger.info("OG cards: %d newly rendered, %d total", rendered, len(checks) + 1)
    return rendered
