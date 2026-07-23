"""Incremental fetch + on-disk cache for the public Lenz catalog.

This is the only module that talks to the network. It walks the public
verification catalog through the ``lenz-io`` SDK and maintains a local cache
that later build stages read offline. The whole point of the cache is that a
rebuild only pays for what actually changed: the cheap library walk (20 items
per page) tells us each claim's ``modified_at``, and we fetch the expensive
per-claim detail (which carries ``sources[]``) and related lists *only* for
ids that are new or whose ``modified_at`` moved.

Cache layout under ``cache_dir``::

    claims/{verification_id}.json   # {"detail": {...}, "related": [...], "fetched_at"}
    manifest.json                   # {verification_id: modified_at}

The manifest is the fast-path index: it lets an incremental sync decide
new/changed/unchanged without opening a single claim file. It is written
atomically (temp file + ``os.replace``) so an interrupted build can never
leave a half-written manifest that would desync the whole cache.

Serialization note: the SDK returns Pydantic v2 models. We persist them with
``model_dump(mode="json")`` — that produces a plain, JSON-safe dict (nested
models flattened, ``None`` preserved) that round-trips through ``json.dump``
and is re-read by ``content.build_checks`` as ordinary dicts.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lenz_io import LenzError, LenzRateLimitError

from .config import RELATED_LIMIT
from .content import VID_RE

logger = logging.getLogger(__name__)

# Politeness delay between per-claim detail fetches. The SDK already retries
# 5xx/429 with backoff, so this is not a rate-limit guard — it just keeps us
# from hammering the public endpoint in a tight loop when the cache is cold.
FETCH_DELAY = 0.05

# Hard ceiling on how long we honour a 429's ``Retry-After`` before giving up
# on that claim. A pathological retry_after must not stall the whole build.
MAX_RETRY_AFTER = 60


@dataclass
class SyncStats:
    """Tally of what a :func:`sync` pass did, for human-readable logging.

    * ``new``       — ids seen for the first time (fetched + cached).
    * ``updated``   — ids whose ``modified_at`` moved (re-fetched).
    * ``unchanged`` — ids already cached at the current ``modified_at`` (skipped;
      no detail fetch — this is the incremental win).
    * ``dropped``   — ids gone from the catalog (cache file + manifest entry removed).
    * ``errors``    — per-claim fetch failures that were logged and skipped.
    """

    new: int = 0
    updated: int = 0
    unchanged: int = 0
    dropped: int = 0
    errors: int = 0

    @property
    def fetched(self) -> int:
        """Detail fetches actually performed this pass."""
        return self.new + self.updated

    def __str__(self) -> str:
        return (
            f"sync: {self.new} new, {self.updated} updated, "
            f"{self.unchanged} unchanged, {self.dropped} dropped, "
            f"{self.errors} errors "
            f"({self.fetched} detail fetch{'es' if self.fetched != 1 else ''})"
        )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def sync(client: Any, cache_dir: Path, *, max_pages: int | None = None) -> SyncStats:
    """Bring the local cache in line with the public catalog.

    Walks ``client.library.list(page=N, sort="recent")`` (server-defined page size),
    fetches detail + related for new/changed ids, and — on a full walk — drops
    ids that have disappeared from the catalog.

    ``max_pages`` is a dev/smoke knob: it stops the walk early *and* disables
    the drop pass. A partial walk sees only a slice of the catalog, so deleting
    every unseen id would wipe most of the cache — the drop pass therefore runs
    only when ``max_pages is None`` (a complete walk).

    Never raises on a per-claim failure: a rate limit is retried once after
    sleeping its ``Retry-After`` (capped at 60s); any other per-claim SDK error
    is logged, counted, and skipped so one bad claim can't sink the build.
    """
    cache_dir = Path(cache_dir)
    claims_dir = cache_dir / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / "manifest.json"
    manifest = _load_manifest(manifest_path)

    stats = SyncStats()
    seen: set[str] = set()

    total: int | None = None
    page = 1
    walk_completed = False  # True only when pagination finishes without error
    while max_pages is None or page <= max_pages:
        try:
            resp = client.library.list(page=page, sort="recent")
        except LenzError as exc:
            # A failed list page means we can't reliably paginate further; stop
            # walking rather than guess. Anything already cached stays put — we
            # deliberately do NOT run the drop pass on an incomplete walk
            # (``walk_completed`` stays False).
            logger.warning("Library list page %d failed: %s", page, exc)
            stats.errors += 1
            break

        items = list(resp.items)
        if total is None:
            total = resp.total
            # Completion math uses the server's OWN page size (fall back to
            # the first page's observed batch length — later pages may be
            # short). Assuming a local constant could mark an incomplete walk
            # complete and let the drop pass delete valid cache.
            page_size = getattr(resp, "page_size", None) or len(items)
        if not items:
            walk_completed = True  # ran past the end of the catalog
            break

        for item in items:
            vid = item.verification_id
            if not vid or not VID_RE.match(str(vid)):
                # A hostile/malformed id would become a cache FILENAME —
                # never let it near the filesystem.
                continue
            seen.add(vid)
            modified = item.modified_at or ""
            cache_file = claims_dir / f"{vid}.json"

            # Fast path: manifest agrees on modified_at AND the file is present
            # → nothing changed, skip the expensive detail fetch entirely.
            if manifest.get(vid) == modified and cache_file.exists():
                stats.unchanged += 1
                continue

            is_new = vid not in manifest
            if _fetch_and_store(client, claims_dir, vid, stats):
                manifest[vid] = modified
                if is_new:
                    stats.new += 1
                else:
                    stats.updated += 1

        # Stop once we've walked the whole catalog. ``total`` is authoritative;
        # the empty-page check above is the belt-and-braces fallback.
        if total is not None and page * page_size >= total:
            walk_completed = True
            break
        page += 1

    # Drop pass — only on a COMPLETE, error-free walk of the full catalog. Ids
    # in the manifest we never saw are gone upstream; remove file + manifest
    # entry. A partial walk (max_pages) or an aborted one (list error) must
    # never mass-delete the cache.
    if max_pages is None and walk_completed:
        doomed = [vid for vid in manifest if vid not in seen]
        # Mass-drop guard: a "complete" walk of an anomalously tiny catalog
        # (bad ``total``, upstream regression) must not gut the cache and
        # deploy a near-empty site. Refuse when the drop would exceed 20% of
        # the manifest (floor of 10 so small catalogs behave normally).
        drop_limit = max(10, len(manifest) // 5)
        if len(doomed) > drop_limit:
            logger.warning(
                "Drop pass would remove %d of %d cached claims — refusing "
                "(upstream anomaly? catalog shrank past the 20%% guard)",
                len(doomed),
                len(manifest),
            )
            stats.errors += 1
        else:
            for vid in doomed:
                _drop(claims_dir, manifest, vid)
                stats.dropped += 1

    # Related backfill (full walks only): unchanged claims never refetch, so
    # docs cached while the related endpoint still required a key would keep
    # ``related: []`` forever. One cheap probe per sync; while the endpoint
    # is auth-walled this is a single failed call, and the first sync after
    # it goes keyless fills every empty list.
    if max_pages is None:
        _backfill_related(client, claims_dir)

    _write_manifest_atomic(manifest_path, manifest)
    logger.info("%s", stats)
    return stats


def _backfill_related(client: Any, claims_dir: Path) -> None:
    empty: list[Path] = []
    for path in claims_dir.glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if doc.get("related") == []:
            empty.append(path)
    if not empty:
        return

    filled = 0
    for i, path in enumerate(empty):
        vid = path.stem
        try:
            related = client.verifications.related(vid, limit=RELATED_LIMIT)
        except LenzError as exc:
            if i == 0:
                # Probe failed — endpoint (still) needs a key; try next sync.
                logger.info("Related backfill unavailable (%s) — skipping", exc)
                return
            continue  # per-claim miss mid-backfill: skip just this one
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["related"] = [item.model_dump(mode="json") for item in related.items]
        if doc["related"]:
            filled += 1
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        time.sleep(FETCH_DELAY)
    logger.info("Related backfill: %d of %d empty lists filled", filled, len(empty))


def load_raw(cache_dir: Path) -> list[dict[str, Any]]:
    """Read every cached claim document into a list of plain dicts.

    Unparseable / unreadable files are logged and skipped so a single corrupt
    cache entry can't abort the build. The returned dicts are exactly what
    ``content.build_checks`` expects (``{"detail", "related", "fetched_at"}``).
    """
    claims_dir = Path(cache_dir) / "claims"
    if not claims_dir.is_dir():
        logger.warning("No cache directory at %s — nothing to load", claims_dir)
        return []

    docs: list[dict[str, Any]] = []
    for path in sorted(claims_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable cache file %s: %s", path.name, exc)
            continue
        if isinstance(doc, dict):
            docs.append(doc)
        else:
            logger.warning("Skipping cache file %s: not a JSON object", path.name)
    logger.info("Loaded %d cached claim document(s) from %s", len(docs), claims_dir)
    return docs


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _fetch_and_store(client: Any, claims_dir: Path, vid: str, stats: SyncStats) -> bool:
    """Fetch detail + related for one id and write its cache doc.

    Returns ``True`` on success. On a rate limit, sleeps ``Retry-After``
    (capped) and retries exactly once. Any other SDK error (or a failed retry)
    is logged, counted in ``stats.errors``, and reported as ``False`` — the
    caller then leaves the manifest untouched for this id.
    """
    try:
        doc = _fetch_doc(client, vid)
    except LenzRateLimitError as exc:
        wait = min(max(int(getattr(exc, "retry_after", 0) or 0), 0), MAX_RETRY_AFTER)
        logger.warning("Rate limited on %s; sleeping %ds then retrying once", vid, wait)
        time.sleep(wait)
        try:
            doc = _fetch_doc(client, vid)
        except LenzError as exc2:
            logger.warning("Retry after rate limit failed for %s: %s", vid, exc2)
            stats.errors += 1
            return False
    except LenzError as exc:
        logger.warning("Fetch failed for %s: %s", vid, exc)
        stats.errors += 1
        return False

    _write_cache_doc(claims_dir, vid, doc)
    return True


def _fetch_doc(client: Any, vid: str) -> dict[str, Any]:
    """Fetch the per-claim resources and assemble the cache document.

    Detail carries ``sources[]`` (absent from list items) and is required.
    Related is a **best-effort enhancement**: on any SDK error we store
    ``related: []`` and keep the claim — the site renders "More Fact Checks"
    from an entity-overlap fallback until the backfill pass fills the list.
    (The endpoint historically required an API key; it is keyless since
    lenzhq/Lenz#114.) Both Pydantic
    models are serialized with ``model_dump(mode="json")``.
    """
    detail = client.verifications.get(vid)
    try:
        related = client.verifications.related(vid, limit=RELATED_LIMIT)
        related_items = [item.model_dump(mode="json") for item in related.items]
    except LenzError as exc:
        logger.debug("Related unavailable for %s (%s); continuing without", vid, exc)
        related_items = []
    time.sleep(FETCH_DELAY)  # tiny politeness gap between detail fetches
    return {
        "detail": detail.model_dump(mode="json"),
        "related": related_items,
        "fetched_at": datetime.now(UTC).isoformat(),
    }


def _write_cache_doc(claims_dir: Path, vid: str, doc: dict[str, Any]) -> None:
    """Write one claim's cache document (pretty-printed for readable diffs)."""
    path = claims_dir / f"{vid}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _load_manifest(manifest_path: Path) -> dict[str, str]:
    """Load the id → modified_at manifest; a missing/corrupt one starts empty.

    A corrupt manifest is not fatal: treating it as empty forces a full
    re-fetch, which is correct (if slow) rather than wrong.
    """
    if not manifest_path.exists():
        return {}
    try:
        with manifest_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Manifest unreadable (%s); starting fresh", exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("Manifest is not a JSON object; starting fresh")
        return {}
    # Coerce to str→str; tolerate legacy/None values without crashing.
    return {str(k): ("" if v is None else str(v)) for k, v in data.items()}


def _write_manifest_atomic(manifest_path: Path, manifest: dict[str, str]) -> None:
    """Write the manifest via temp file + ``os.replace`` (atomic on POSIX).

    An interrupted build must never leave a truncated manifest — that would
    make the next sync misjudge which ids are unchanged and silently skip real
    updates. Writing to a sibling temp file and renaming makes the swap atomic.
    """
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_path, manifest_path)


def _drop(claims_dir: Path, manifest: dict[str, str], vid: str) -> None:
    """Remove a disappeared claim: its cache file and its manifest entry."""
    cache_file = claims_dir / f"{vid}.json"
    try:
        cache_file.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - filesystem edge
        logger.warning("Could not delete stale cache file %s: %s", cache_file, exc)
    manifest.pop(vid, None)
