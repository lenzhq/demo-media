"""Validate every JSON-LD block in the built dist/ tree.

Checks all blocks parse, and that every ClaimReview / NewsArticle carries the
fields Google's fact-check rich-result documentation lists as required plus
the recommended set this site commits to. Run after a build:

    python scripts/validate_jsonld.py [dist]

Exit code 1 on any problem — wired into CI between build and deploy, so a
template edit that silently drops e.g. ``datePublished`` can't ship.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)

REQUIRED_CLAIMREVIEW = ("claimReviewed", "reviewRating", "url")
RECOMMENDED_CLAIMREVIEW = ("author", "datePublished", "itemReviewed")
NEWSARTICLE_FIELDS = (
    "headline",
    "datePublished",
    "author",
    "publisher",
    "mainEntityOfPage",
)

# Canonical JSON-LD date shape: seconds precision, Z suffix. The API's raw
# microseconds/+00:00 stamps are valid ISO 8601 but trip strict validators.
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _check_dates(node: dict, page, problems: list[str]) -> None:
    for key in ("datePublished", "dateModified"):
        value = node.get(key)
        if value and not DATE_RE.match(value):
            problems.append(
                f"{node.get('@type')} {key} not canonical ISO-Z ({value}): {page}"
            )


def main(dist: Path) -> int:
    stats = {"pages": 0, "blocks": 0, "claimreviews": 0, "newsarticles": 0}
    problems: list[str] = []

    for page in dist.rglob("index.html"):
        blocks = LD_RE.findall(page.read_text(encoding="utf-8"))
        if not blocks:
            continue
        stats["pages"] += 1
        for raw in blocks:
            stats["blocks"] += 1
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                problems.append(f"PARSE {page}: {exc}")
                continue
            for node in data if isinstance(data, list) else [data]:
                kind = node.get("@type")
                if kind == "ClaimReview":
                    stats["claimreviews"] += 1
                    problems += [
                        f"ClaimReview missing REQUIRED {key}: {page}"
                        for key in REQUIRED_CLAIMREVIEW
                        if not node.get(key)
                    ]
                    rating = node.get("reviewRating") or {}
                    has_numeric = all(
                        rating.get(k) is not None
                        for k in ("ratingValue", "bestRating", "worstRating")
                    )
                    if not (rating.get("alternateName") or has_numeric):
                        problems.append(f"ClaimReview reviewRating incomplete: {page}")
                    problems += [
                        f"ClaimReview missing recommended {key}: {page}"
                        for key in RECOMMENDED_CLAIMREVIEW
                        if not node.get(key)
                    ]
                    _check_dates(node, page, problems)
                elif kind == "NewsArticle":
                    stats["newsarticles"] += 1
                    problems += [
                        f"NewsArticle missing {key}: {page}"
                        for key in NEWSARTICLE_FIELDS
                        if not node.get(key)
                    ]
                    _check_dates(node, page, problems)

    print(
        f"jsonld: {stats['blocks']} blocks on {stats['pages']} pages — "
        f"{stats['claimreviews']} ClaimReview, {stats['newsarticles']} NewsArticle"
    )
    if stats["claimreviews"] == 0:
        problems.append(
            "no ClaimReview blocks found — wrong dist path or broken build?"
        )
    for problem in problems[:25]:
        print(f"  PROBLEM: {problem}", file=sys.stderr)
    if problems:
        print(f"jsonld: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("jsonld: all valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "dist")))
