"""Pure logic for the ``claimlive`` function — no Firebase imports.

Serves the window between "claim verified on Lenz" and "next static build":
Firebase Hosting rewrites ``/c/<id>`` and ``/og-live/<id>.png`` here ONLY
while no static file exists at the path — once the daily build materializes
the claim, its stub and card shadow this function automatically.

Kept free of ``firebase_functions`` so the offline test suite can exercise
the HTML/PNG builders directly; ``main.py`` is the thin wrapper.
"""

from __future__ import annotations

import html
import io
import json
import re
import urllib.request

from isthisbs import ogimage
from isthisbs.config import SITE, VERDICTS, section_for_domain
from isthisbs.content import mint_slug

VID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: Keyless public read — the same endpoint the build's fetch layer uses.
API_BASE = f"{SITE.lenz_home}/api/v1/verifications/"


def fetch_detail(vid: str, *, timeout: int = 10) -> dict | None:
    """Fetch one claim keylessly; None on any miss/error (caller 404s)."""
    if not VID_RE.match(vid or ""):
        return None
    try:
        req = urllib.request.Request(
            API_BASE + vid, headers={"User-Agent": "isthisbs-claimlive"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            detail = json.load(resp)
    except Exception:
        return None
    if not detail or not detail.get("claim"):
        return None
    if detail.get("verdict") not in VERDICTS:  # Error / unknown never render
        return None
    return detail


def build_card_png(detail: dict) -> bytes:
    """The claim's OG card, identical to the built one (same renderer)."""
    verdict = VERDICTS[detail["verdict"]]
    img = ogimage.render_card(detail["claim"], verdict)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_live_html(detail: dict) -> str:
    """A self-contained live page for a just-verified claim.

    Full OG/twitter meta (the whole point: the tweet-time link card), the
    claim + verdict + summary, links to Lenz — and no dependency on the
    site's hashed stylesheet (this page must not break when the CSS hash
    rotates), so brand-minimal styles ship inline. Every API string is
    HTML-escaped: external data must never become markup.
    """
    vid = html.escape(str(detail.get("verification_id", "")))
    claim = html.escape(detail["claim"])
    verdict = VERDICTS[detail["verdict"]]
    label = html.escape(verdict.bs_label)
    key = html.escape(verdict.key)
    summary = html.escape((detail.get("executive_summary") or "").strip())
    # Card description: verdict first, then as much summary as fits — X mostly
    # shows title+image, but Slack/WhatsApp/Discord render the description.
    raw_summary = " ".join((detail.get("executive_summary") or "").split())
    desc_summary = (
        raw_summary[:157].rsplit(" ", 1)[0] + "…"
        if len(raw_summary) > 157
        else raw_summary
    )
    description = html.escape(
        f"{verdict.bs_label} — {desc_summary}"
        if desc_summary
        else f"{verdict.bs_label} — Verdict: {verdict.key}. Checked against independent sources."
    )
    warnings = [
        html.escape(str(w)) for w in (detail.get("warnings") or []) if str(w).strip()
    ]
    caveats_html = ""
    if warnings:
        items = "".join(f"<li>{w}</li>" for w in warnings)
        caveats_html = f'<p class="kicker" style="margin-top:2rem">Caveats</p><ul class="caveats">{items}</ul>'
    og_image = f"{SITE.base_url}/og-live/{vid}.png"
    # The permanent article URL is fully computable from the API payload —
    # canonical there from minute zero, so search equity never splits.
    section = section_for_domain(detail.get("domain"))
    slug = mint_slug(detail["claim"], str(detail.get("verification_id", "")))
    canonical = f"{SITE.base_url}{section.path}{slug}/"
    lenz_url = html.escape(SITE.lenz_claim_url(str(detail.get("verification_id", ""))))
    title = html.escape(detail["claim"][:110])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {html.escape(SITE.name)}</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="{canonical}">
<meta name="description" content="{description}">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:image" content="{og_image}">
<meta property="og:url" content="{SITE.base_url}/c/{vid}/">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{og_image}">
<style>
  body {{ margin:0; background:#FAF7F0; color:#141310;
    font-family: ui-serif, 'Iowan Old Style', Palatino, Georgia, serif; }}
  .wrap {{ max-width: 42rem; margin: 0 auto; padding: 48px 24px; }}
  .bar {{ height:12px; background:#FFD23F; }}
  .kicker {{ font-family: ui-monospace, Menlo, monospace; font-size:.6875rem;
    letter-spacing:.08em; text-transform:uppercase; opacity:.65; }}
  h1 {{ font-size: clamp(1.6rem, 5vw, 2.4rem); line-height:1.15; font-weight:800; }}
  .pill {{ font-family: ui-monospace, Menlo, monospace; font-weight:700;
    color:{verdict.text_hex}; }}
  .pill b {{ display:inline-block; width:.7em; height:.7em;
    background:{verdict.fill_hex}; margin-right:.4em; }}
  .note {{ font-family: ui-monospace, Menlo, monospace; font-size:.8125rem;
    opacity:.65; margin-top:2.5rem; }}
  .caveats {{ margin:.5rem 0 0; padding-left:1.2em; }}
  .caveats li {{ margin-bottom:.5rem; opacity:.8; }}
  a {{ color: inherit; text-decoration: underline; text-decoration-color:#FFD23F;
    text-decoration-thickness:2px; text-underline-offset:3px; }}
</style>
</head>
<body>
<div class="bar"></div>
<main class="wrap">
  <p class="kicker">The Claim</p>
  <h1>“{claim}”</h1>
  <p class="pill"><b></b>{label} — Verdict: {key}</p>
  <p>{summary}</p>
  {caveats_html}
  <p><a href="{lenz_url}" rel="noopener">Read the full analysis on Lenz →</a></p>
  <p class="note">Fresh off the desk — the permanent article lands on
    <a href="/">IsThisBS?</a> within a day. This check was summoned by tagging
    <a href="https://x.com/isthisbs" rel="noopener">@isthisbs</a> on X —
    tag it under any post to fact-check it.</p>
</main>
</body>
</html>"""


def build_notfound_html() -> str:
    """On-brand 404 for the function path (invalid/unknown /c/ ids) —
    mirrors 404.html's voice without depending on hosting assets."""
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>404 — IsThisBS?</title><meta name="robots" content="noindex">
<style>
  body { margin:0; background:#FAF7F0; color:#141310; text-align:center;
    font-family: ui-serif, 'Iowan Old Style', Palatino, Georgia, serif; }
  .bar { height:12px; background:#FFD23F; }
  .code { font-size: clamp(4rem, 18vw, 9rem); font-weight:800; margin:1.2em 0 0; line-height:1; }
  h1 { font-size:1.5rem; margin:.6em 0 2em; }
  a { color:inherit; text-decoration:underline; text-decoration-color:#FFD23F;
    text-decoration-thickness:2px; text-underline-offset:3px;
    font-family:ui-monospace, Menlo, monospace; font-size:.8125rem;
    letter-spacing:.08em; text-transform:uppercase; }
</style></head><body><div class="bar"></div>
<p class="code">404</p>
<h1>This claim is BS — it doesn't exist (or hasn't been checked yet).</h1>
<p><a href="/">Home</a> &nbsp;·&nbsp; <a href="/latest/">Latest</a> &nbsp;·&nbsp; <a href="/search/">Search</a></p>
</body></html>"""
