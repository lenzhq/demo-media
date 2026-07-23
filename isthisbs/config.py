"""Site-wide configuration: brand, sections, and the verdict → BS Meter mapping.

This module is the single source of truth that every other module codes
against. It has no dependencies beyond the standard library, so anything
can import it freely (templates receive these objects as Jinja globals).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Site identity
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Site:
    """Brand + canonical URLs. ``base_url`` is overridable via SITE_BASE_URL."""

    name: str = "IsThisBS?"
    short_name: str = "IsThisBS"
    tagline: str = "The claims desk. Receipts included."
    description: str = (
        "IsThisBS is an automated fact-check publication. Every article is one "
        "claim, verified against independent sources by Lenz, with the receipts "
        "to show for it."
    )
    base_url: str = field(
        default_factory=lambda: os.environ.get(
            "SITE_BASE_URL", "https://isthisbs.org"
        ).rstrip("/")
    )
    language: str = "en"
    # Attribution targets (the "Powered by Lenz" disclosure).
    lenz_home: str = "https://lenz.io"
    lenz_api_docs: str = "https://lenz.io/developers"
    lenz_verify: str = "https://lenz.io/verify"  # "Verify any claim" CTA target
    lenz_sdk_python: str = "https://pypi.org/project/lenz-io/"
    lenz_sdk_node: str = "https://www.npmjs.com/package/lenz-io"
    github_repo: str = "https://github.com/lenzhq/isthisbs"
    twitter_handle: str = "@isthisbs"

    def lenz_claim_url(self, verification_id: str) -> str:
        """Canonical 'full analysis' page on lenz.io for a claim."""
        return f"{self.lenz_home}/c/{verification_id}"


SITE = Site()


# --------------------------------------------------------------------------- #
# Verdicts — the BS Meter mapping
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Verdict:
    """One point on the 5-stop BS Meter.

    ``key`` is the canonical API verdict and is what every machine-readable
    surface (ClaimReview ``alternateName``, data attributes) must carry;
    ``bs_label`` is presentation-only. ``rank`` is the meter stop, 1 (NOT BS)
    through 5 (TOTAL BS). Hex colors exist for the OG-image generator; the
    CSS owns its own tokens keyed by ``css`` class (see DESIGN.md §3).
    """

    key: str
    bs_label: str
    rank: int
    css: str
    fill_hex: str
    text_hex: str


VERDICTS: dict[str, Verdict] = {
    "True": Verdict("True", "NOT BS", 1, "v-not-bs", "#2E7D32", "#1E6B24"),
    "Mostly True": Verdict(
        "Mostly True", "HARDLY BS", 2, "v-hardly-bs", "#558B2F", "#41701F"
    ),
    "Mixed": Verdict("Mixed", "SOME BS", 3, "v-some-bs", "#B58900", "#7A5D00"),
    "Mostly False": Verdict(
        "Mostly False", "MOSTLY BS", 4, "v-mostly-bs", "#C75000", "#9C3F00"
    ),
    "False": Verdict("False", "TOTAL BS", 5, "v-total-bs", "#C62828", "#B3261E"),
}

#: Verdicts that never appear on the site (build-time filter).
EXCLUDED_VERDICTS = frozenset({"Error"})

#: Meter order, NOT BS → TOTAL BS (used by filter chips and the meter track).
VERDICT_ORDER: list[Verdict] = sorted(VERDICTS.values(), key=lambda v: v.rank)


# --------------------------------------------------------------------------- #
# Sections — the 8 Lenz domains, in nav order
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Section:
    key: str  # URL segment + lowercase API ``domain``
    title: str
    blurb: str

    @property
    def path(self) -> str:
        return f"/{self.key}/"


_SECTION_LIST = [
    Section(
        "health",
        "Health",
        "Medical claims, wellness fads, and what the evidence actually supports.",
    ),
    Section(
        "science",
        "Science",
        "Research findings, viral studies, and scientific claims under the lens.",
    ),
    Section(
        "politics",
        "Politics",
        "Statements from and about the political arena, checked against the record.",
    ),
    Section(
        "finance",
        "Finance",
        "Money, markets, and economic claims — separated from the noise.",
    ),
    Section(
        "tech", "Tech", "Claims about technology, AI, and the companies that build it."
    ),
    Section(
        "history",
        "History",
        "What really happened — historical claims measured against the sources.",
    ),
    Section(
        "legal", "Legal", "Laws, rights, and legal claims — what actually holds up."
    ),
    Section("general", "General", "Everything else people repeat — checked."),
]

SECTIONS: dict[str, Section] = {s.key: s for s in _SECTION_LIST}


def section_for_domain(domain: str | None) -> Section:
    """Map an API ``domain`` value to a Section; unknown/missing → general."""
    if domain:
        return SECTIONS.get(domain.strip().lower(), SECTIONS["general"])
    return SECTIONS["general"]


# --------------------------------------------------------------------------- #
# Build knobs (env-overridable where it makes sense)
# --------------------------------------------------------------------------- #

#: Languages included in the build (v1: English only). BUILD_LANGS="en,de" etc.
LANGS: tuple[str, ...] = tuple(
    lang.strip()
    for lang in os.environ.get("BUILD_LANGS", "en").split(",")
    if lang.strip()
)

# Editorial quality floor (CEO review E1): a check must clear this bar to be
# published at all. The catalog is screened upstream for safety, not editorial
# weight — thin checks (no receipts, one-line reasoning) would read like a
# database dump, so they never become articles. Tune, don't remove.
# Tuning note (measured on live catalog data, 2026-07-23): real checks carry
# 18-41 cited sources and 280-460-char summaries — the floor exists to catch
# DEGENERATE content (empty/one-line summaries, sourceless checks) if the
# upstream shape ever changes, not to bisect the normal distribution.
ARTICLE_MIN_SOURCES = 2  # cited sources required to publish a check
ARTICLE_MIN_SUMMARY_CHARS = 200  # catches broken/empty summaries only
LEAD_MIN_SOURCES = 3  # the home lead slot wants a well-receipted check
SOURCES_SHOWN_MAX = 10  # receipts rendered on an article; rest link to Lenz

PAGE_SIZE = 20  # cards per page on section/latest/topic feeds
COLLECTION_SIZE = 40  # items in /bs-files/ and /checks-out/
ENTITY_MIN_CLAIMS = 2  # entities need >= this many claims to earn a /topic/ page
HOME_RAIL_SIZE = 6  # "Fresh Checks" rail (8 left ~350px dead air under the lead)
HOME_SECTION_SIZE = 4  # cards per section block on home
HOME_STRIP_SIZE = 4  # BS Files / Checks Out strips on home
FEED_SIZE = 50  # site-wide Atom feed entries
SECTION_FEED_SIZE = 30  # per-section Atom feed entries
NEWS_SITEMAP_HOURS = 48  # Google News sitemap window
RELATED_LIMIT = 6  # related checks fetched per claim (server caps at 10)
