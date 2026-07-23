"""Build-time GitHub-Discussions counts — community signal with zero JS.

Each article maps to (at most) one GitHub Discussion, matched by a
``[verification_id]`` suffix in the discussion title (the prefilled
new-discussion links in ``article.html`` bake that suffix in, so discussions
created by readers are picked up automatically on the next build).

``sync`` fetches every discussion's 👍/👎 reaction and comment counts via the
GraphQL API and caches them as ``discussions.json`` next to the claims cache.
It needs a token (``GITHUB_TOKEN``/``GH_TOKEN``) — present in CI, where the
builds run every 8 hours; absent locally, where sync degrades to a no-op and
the build renders from the cached file (or, with no file, renders every
article in its zero state). Counts are therefore at most one build stale.

Zero-hiding is the display contract (rendered in ``article.html``): counts
appear only once they are non-zero — a fresh article shows the
verdict-challenge prompt instead of a dead "👍 0".
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

REPO_OWNER = "lenzhq"
REPO_NAME = "demo-media"
_GRAPHQL_URL = "https://api.github.com/graphql"
_PAGE = 100

#: ``[verification_id]`` suffix in a discussion title (same shape content.VID_RE
#: accepts, anchored to the end of the title).
_TITLE_VID_RE = re.compile(r"\[([A-Za-z0-9_-]{1,64})\]\s*$")

_QUERY = f"""
query($owner: String!, $name: String!, $after: String) {{
  repository(owner: $owner, name: $name) {{
    discussions(first: {_PAGE}, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        title
        url
        comments {{ totalCount }}
        reactionGroups {{ content reactors {{ totalCount }} }}
      }}
    }}
  }}
}}
"""


def _vid_from_title(title: str) -> str | None:
    m = _TITLE_VID_RE.search(title or "")
    return m.group(1) if m else None


def _to_map(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """GraphQL discussion nodes -> {vid: {url, up, down, comments}}.

    Discussions without a ``[vid]`` title suffix (site meta, announcements)
    are simply not article discussions — skipped. If two discussions claim
    the same vid (a creation race), the first one returned wins.
    """
    out: dict[str, dict[str, Any]] = {}
    for node in nodes:
        vid = _vid_from_title(node.get("title", ""))
        if not vid or vid in out:
            continue
        up = down = 0
        for group in node.get("reactionGroups") or []:
            count = (group.get("reactors") or {}).get("totalCount", 0)
            if group.get("content") == "THUMBS_UP":
                up = count
            elif group.get("content") == "THUMBS_DOWN":
                down = count
        out[vid] = {
            "url": node.get("url", ""),
            "up": up,
            "down": down,
            "comments": (node.get("comments") or {}).get("totalCount", 0),
        }
    return out


def sync(cache_dir: Path) -> None:
    """Refresh ``discussions.json`` from the GitHub API (token required).

    Without a token this is a logged no-op — the cached file (if any) keeps
    serving. Any API failure likewise leaves the existing cache untouched:
    stale counts beat a build failure or a silently emptied file.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        logger.info(
            "Discussions sync skipped (no GITHUB_TOKEN) — using cached counts if any"
        )
        return

    nodes: list[dict[str, Any]] = []
    after: str | None = None
    try:
        with httpx.Client(timeout=30) as client:
            while True:
                resp = client.post(
                    _GRAPHQL_URL,
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "query": _QUERY,
                        "variables": {
                            "owner": REPO_OWNER,
                            "name": REPO_NAME,
                            "after": after,
                        },
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                if payload.get("errors"):
                    raise RuntimeError(str(payload["errors"][:1]))
                conn = payload["data"]["repository"]["discussions"]
                nodes.extend(conn["nodes"])
                if not conn["pageInfo"]["hasNextPage"]:
                    break
                after = conn["pageInfo"]["endCursor"]
    except Exception as exc:
        logger.warning("Discussions sync failed (%s) — keeping cached counts", exc)
        return

    mapping = _to_map(nodes)
    path = Path(cache_dir) / "discussions.json"
    path.write_text(json.dumps(mapping, indent=1, ensure_ascii=False), encoding="utf-8")
    logger.info("Discussions sync: %d article discussion(s) mapped", len(mapping))


def load(cache_dir: Path) -> dict[str, dict[str, Any]]:
    """Read the cached count map; missing/corrupt reads as empty (zero state)."""
    path = Path(cache_dir) / "discussions.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
