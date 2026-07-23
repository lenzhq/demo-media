"""Firebase Functions entrypoint — the ``claimlive`` fallback.

Hosting rewrites route ``/c/**`` and ``/og-live/**`` here ONLY when no
static file matches (Firebase checks static first), i.e. for claims newer
than the last build. All real logic lives in ``live_core`` (offline-tested);
this file is the thinnest possible HTTP shim.

Deploy note: ``isthisbs/`` is synced into this directory right before
``firebase deploy`` (see deploy/deploy.sh and build-deploy.yml) — the
functions bundle must be self-contained.
"""

from __future__ import annotations

import re

import live_core
from firebase_functions import https_fn, options

_C_RE = re.compile(r"^/c/([A-Za-z0-9_-]{1,64})/?$")
_OG_RE = re.compile(r"^/og-live/([A-Za-z0-9_-]{1,64})\.png$")

_HTML_CACHE = "public, max-age=300"  # static shadows this after the build
_PNG_CACHE = "public, max-age=3600"  # scrapers cache cards anyway


@https_fn.on_request(
    region="us-central1",
    memory=options.MemoryOption.MB_512,
    timeout_sec=30,
    max_instances=5,  # fresh-claim traffic is tiny; cap the blast radius
)
def claimlive(req: https_fn.Request) -> https_fn.Response:
    path = req.path or ""

    if m := _OG_RE.match(path):
        detail = live_core.fetch_detail(m.group(1))
        if detail is None:
            return https_fn.Response("Not found", status=404)
        return https_fn.Response(
            live_core.build_card_png(detail),
            status=200,
            headers={"Content-Type": "image/png", "Cache-Control": _PNG_CACHE},
        )

    if m := _C_RE.match(path):
        detail = live_core.fetch_detail(m.group(1))
        if detail is None:
            return https_fn.Response(
                "<h1>404</h1><p>This claim is BS — it doesn't exist "
                '(or hasn\'t been checked). <a href="/">IsThisBS?</a></p>',
                status=404,
                headers={"Content-Type": "text/html; charset=utf-8"},
            )
        return https_fn.Response(
            live_core.build_live_html(detail),
            status=200,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Cache-Control": _HTML_CACHE,
            },
        )

    return https_fn.Response("Not found", status=404)
