"""Editorial data model: raw cached claim dicts → Check objects → groupings.

The cache layer (``fetch.py``) stores one JSON document per claim:
``{"detail": {...verification fields...}, "related": [...], "fetched_at": iso}``.
This module parses those into ``Check`` objects and derives every grouping
the site renders (sections, entity hubs, collections, pagination).

Pure functions, standard library + ``python-slugify`` only — fully testable
offline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from slugify import slugify

from .config import (
    ARTICLE_MIN_SOURCES,
    ARTICLE_MIN_SUMMARY_CHARS,
    COLLECTION_SIZE,
    ENTITY_MIN_CLAIMS,
    EXCLUDED_VERDICTS,
    LANGS,
    LEAD_MIN_SOURCES,
    SITE,
    VERDICTS,
    Section,
    Verdict,
    section_for_domain,
)

logger = logging.getLogger(__name__)

SLUG_MAX = 60  # slug text budget before the verification_id suffix


# --------------------------------------------------------------------------- #
# Slug minting
# --------------------------------------------------------------------------- #


def mint_slug(claim: str, verification_id: str) -> str:
    """Stable, unique article slug: slugified claim (≤60 chars) + id suffix.

    The id suffix guarantees uniqueness and stability even if the claim text
    is edited upstream; the slug prefix is purely for humans and SEO.
    """
    text = slugify(claim or "", max_length=SLUG_MAX, word_boundary=True) or "claim"
    return f"{text}-{verification_id}"


def entity_slug(name: str) -> str:
    return slugify(name or "", max_length=SLUG_MAX, word_boundary=True) or "topic"


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Source:
    source_name: str
    title: str
    url: str
    snippet: str = ""
    date: str = ""


@dataclass(frozen=True)
class Entity:
    name: str
    qid: str = ""  # Wikidata QID when known ('' otherwise)
    slug: str = ""

    @property
    def path(self) -> str:
        return f"/topic/{self.slug}/"

    @property
    def wikidata_url(self) -> str:
        return f"https://www.wikidata.org/wiki/{self.qid}" if self.qid else ""


@dataclass(frozen=True)
class RelatedRef:
    """A related claim as returned by the API — resolved (or dropped) at
    render time against the set of locally rendered checks."""

    verification_id: str
    claim: str
    verdict: str = ""


@dataclass(frozen=True)
class Check:
    """One verified claim — one article."""

    verification_id: str
    claim: str
    verdict_key: str
    lenz_score: int | None
    executive_summary: str
    created_at: str  # original ISO string (JSON-LD wants it verbatim)
    modified_at: str
    language: str
    section: Section
    entities: tuple[Entity, ...] = ()
    warnings: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()
    panel_agreement: str = ""  # unanimous | majority | split | ''
    related: tuple[RelatedRef, ...] = ()
    created_dt: datetime = field(default_factory=lambda: datetime.now(UTC))

    # -- derived ----------------------------------------------------------- #

    @property
    def verdict(self) -> Verdict:
        return VERDICTS[self.verdict_key]

    @property
    def slug(self) -> str:
        return mint_slug(self.claim, self.verification_id)

    @property
    def path(self) -> str:
        return f"{self.section.path}{self.slug}/"

    @property
    def url(self) -> str:
        return f"{SITE.base_url}{self.path}"

    @property
    def og_path(self) -> str:
        return f"/og/{self.verification_id}.png"

    @property
    def lenz_url(self) -> str:
        return SITE.lenz_claim_url(self.verification_id)

    @property
    def is_split(self) -> bool:
        return self.panel_agreement == "split"

    @property
    def summary_paragraphs(self) -> tuple[str, ...]:
        """executive_summary is plain text; render as paragraphs on blank lines."""
        return tuple(
            p.strip() for p in self.executive_summary.split("\n\n") if p.strip()
        )


@dataclass(frozen=True)
class EntityGroup:
    """An entity hub page: the entity + every check that mentions it."""

    entity: Entity
    checks: tuple[Check, ...]


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def _parse_dt(value: str | None) -> datetime:
    """Parse an API ISO timestamp; tolerate 'Z' and missing values."""
    if value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            logger.warning("Unparseable timestamp %r", value)
    return datetime.fromtimestamp(0, tz=UTC)


def _parse_check(doc: dict[str, Any]) -> Check | None:
    """One cached document → Check, or None if it shouldn't be on the site."""
    d = doc.get("detail") or {}
    vid = d.get("verification_id")
    claim = (d.get("claim") or "").strip()
    verdict = (d.get("verdict") or "").strip()
    if not vid or not claim:
        return None
    if verdict in EXCLUDED_VERDICTS or verdict not in VERDICTS:
        return None  # Error verdicts (and anything unknown) never render
    language = (d.get("language") or "en").strip().lower()
    if LANGS and language.split("-")[0] not in LANGS:
        return None

    audit = d.get("audit") or {}
    entities = tuple(
        Entity(name=name, qid=(e.get("qid") or ""), slug=entity_slug(name))
        for e in (d.get("entities") or [])
        if (name := (e.get("name") or "").strip())
    )
    sources = tuple(
        Source(
            source_name=s.get("source_name") or "",
            title=(s.get("title") or s.get("source_name") or "Source").strip(),
            url=s.get("url") or "",
            snippet=s.get("snippet") or "",
            date=s.get("date") or "",
        )
        for s in (d.get("sources") or [])
        if s.get("url")
    )
    related = tuple(
        RelatedRef(
            verification_id=r["verification_id"],
            claim=(r.get("claim") or "").strip(),
            verdict=(r.get("verdict") or "").strip(),
        )
        for r in (doc.get("related") or [])
        if r.get("verification_id")
    )
    return Check(
        verification_id=vid,
        claim=claim,
        verdict_key=verdict,
        lenz_score=d.get("lenz_score"),
        executive_summary=(d.get("executive_summary") or "").strip(),
        created_at=d.get("created_at") or "",
        modified_at=d.get("modified_at") or "",
        language=language,
        section=section_for_domain(d.get("domain")),
        entities=entities,
        warnings=tuple(w.strip() for w in (d.get("warnings") or []) if w and w.strip()),
        sources=sources,
        panel_agreement=(audit.get("panel_agreement") or "").strip().lower(),
        related=related,
        created_dt=_parse_dt(d.get("created_at")),
    )


def meets_editorial_floor(check: Check) -> bool:
    """The publish bar: enough receipts and a real explanation.

    The Lenz catalog is screened upstream for safety, not editorial weight.
    A check with fewer than ARTICLE_MIN_SOURCES cited sources or a one-line
    summary would make a thin, low-trust article — it stays out of the site
    entirely (no page, no listing, no dead links).
    """
    return (
        len(check.sources) >= ARTICLE_MIN_SOURCES
        and len(check.executive_summary) >= ARTICLE_MIN_SUMMARY_CHARS
    )


def build_checks(raw_docs: list[dict[str, Any]]) -> list[Check]:
    """Parse + filter + editorial floor + sort (newest first).

    Silently skips malformed docs; logs how many parsed checks the editorial
    floor withheld so a floor misconfiguration is visible in build output.
    """
    seen: set[str] = set()
    checks: list[Check] = []
    floored = 0
    for doc in raw_docs:
        try:
            check = _parse_check(doc)
        except Exception:  # one bad document must never sink the build
            logger.exception("Skipping malformed cached document")
            continue
        if not check or check.verification_id in seen:
            continue
        seen.add(check.verification_id)
        if not meets_editorial_floor(check):
            floored += 1
            continue
        checks.append(check)
    checks.sort(key=lambda c: c.created_dt, reverse=True)
    if floored:
        logger.info(
            "Editorial floor: published %d checks, withheld %d thin ones",
            len(checks),
            floored,
        )
    return checks


def pick_lead(checks: list[Check]) -> Check | None:
    """The home lead: newest check with LEAD_MIN_SOURCES+ receipts.

    Falls back to the newest check outright — the lead slot must never be
    empty while the site has content.
    """
    if not checks:
        return None
    for check in checks:
        if len(check.sources) >= LEAD_MIN_SOURCES:
            return check
    return checks[0]


# --------------------------------------------------------------------------- #
# Groupings
# --------------------------------------------------------------------------- #


def group_by_section(checks: list[Check]) -> dict[str, list[Check]]:
    """Section key → checks (newest first). Every section key is present."""
    from .config import SECTIONS

    groups: dict[str, list[Check]] = {key: [] for key in SECTIONS}
    for check in checks:
        groups[check.section.key].append(check)
    return groups


def group_by_entity(
    checks: list[Check], min_count: int = ENTITY_MIN_CLAIMS
) -> list[EntityGroup]:
    """Entity hubs for entities appearing on ≥ ``min_count`` checks.

    Grouped by slug; on a slug collision between distinct entities (rare),
    the later one is disambiguated with its QID (or a counter). Sorted by
    claim count desc, then name.
    """
    by_slug: dict[str, tuple[Entity, list[Check]]] = {}
    for check in checks:
        for entity in check.entities:
            slot = by_slug.get(entity.slug)
            if slot is None:
                by_slug[entity.slug] = (entity, [check])
            elif slot[0].name.casefold() == entity.name.casefold():
                if check not in slot[1]:
                    slot[1].append(check)
            else:  # distinct entity, same slug → disambiguate
                alt = (
                    f"{entity.slug}-{entity.qid.lower()}"
                    if entity.qid
                    else f"{entity.slug}-2"
                )
                entity = Entity(entity.name, entity.qid, alt)
                alt_slot = by_slug.setdefault(alt, (entity, []))
                if check not in alt_slot[1]:
                    alt_slot[1].append(check)
    groups = [
        EntityGroup(entity=entity, checks=tuple(members))
        for entity, members in by_slug.values()
        if len(members) >= min_count
    ]
    groups.sort(key=lambda g: (-len(g.checks), g.entity.name.casefold()))
    return groups


def collections(checks: list[Check]) -> dict[str, list[Check]]:
    """The two curated cross-site collections, computed locally.

    ``bs_files``: recent False / Mostly False. ``checks_out``: recent
    True / Mostly True. Both newest-first, capped at COLLECTION_SIZE.
    """
    bs_files = [c for c in checks if c.verdict_key in ("False", "Mostly False")]
    checks_out = [c for c in checks if c.verdict_key in ("True", "Mostly True")]
    return {
        "bs_files": bs_files[:COLLECTION_SIZE],
        "checks_out": checks_out[:COLLECTION_SIZE],
    }


def related_fallback(check: Check, checks: list[Check], limit: int = 6) -> list[Check]:
    """Local "MORE CHECKS" when the API's related list is unavailable.

    The related endpoint requires an API key (detail and library are keyless),
    so a keyless build computes relatedness locally: checks sharing the most
    entities win, recency breaks ties. Returns [] when nothing overlaps —
    the template simply omits the section.
    """
    own = {e.slug for e in check.entities}
    if not own:
        return []
    scored = [
        (len(own & {e.slug for e in other.entities}), other)
        for other in checks
        if other.verification_id != check.verification_id
    ]
    ranked = [
        other
        for overlap, other in sorted(
            ((s, o) for s, o in scored if s > 0),
            key=lambda pair: (-pair[0], -pair[1].created_dt.timestamp()),
        )
    ]
    return ranked[:limit]


def paginate(items: list[Check], page_size: int) -> list[list[Check]]:
    """Split into pages; always at least one (possibly empty) page."""
    if not items:
        return [[]]
    return [items[i : i + page_size] for i in range(0, len(items), page_size)]
