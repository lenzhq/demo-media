"""Tests for the incremental fetch/cache layer, driven by a fake SDK client."""

from __future__ import annotations

import asyncio
import json

import pytest

# Real SDK exception types — imported (fetch.py already needs the SDK present).
from lenz_io import LenzApiVersionError, LenzError, LenzRateLimitError

from isthisbs import fetch
from isthisbs.config import PAGE_SIZE

# --------------------------------------------------------------------------- #
# Fake SDK
# --------------------------------------------------------------------------- #


# Every claim here was created on 2026-07-01 and completed on a later day, so
# its change key is its ``completed_at``.
CREATED = "2026-07-01T09:00:00Z"
LATER = "2026-07-02T09:00:00Z"
LATER2 = "2026-07-03T09:00:00Z"


class _FakeItem:
    def __init__(self, vid: str, completed_at: str) -> None:
        self.verification_id = vid
        self.created_at = CREATED
        self.completed_at = completed_at


class _FakeList:
    def __init__(self, items: list[_FakeItem], total: int) -> None:
        self.items = items
        self.total = total


class _FakeModel:
    def __init__(self, data: dict) -> None:
        self._data = data

    def model_dump(self, mode: str = "json") -> dict:
        return dict(self._data)


class _FakeRelated:
    def __init__(self, items: list[_FakeModel]) -> None:
        self.items = items


class _FakeLibrary:
    def __init__(self, client: FakeClient) -> None:
        self._c = client

    async def list(self, page: int = 1, sort: str = "recent") -> _FakeList:
        self._c.list_calls.append(page)
        if self._c.list_error_on_page == page:
            raise LenzError(message=f"list page {page} boom")
        catalog = self._c.catalog
        start = (page - 1) * PAGE_SIZE
        chunk = catalog[start : start + PAGE_SIZE]
        items = [_FakeItem(vid, mod) for vid, mod in chunk]
        return _FakeList(items, total=len(catalog))


class _FakeVerifications:
    def __init__(self, client: FakeClient) -> None:
        self._c = client

    async def get(self, vid: str) -> _FakeModel:
        self._c.get_calls.append(vid)
        if vid in self._c.rate_limit_ids:
            # Only rate-limit the first attempt for an id, then succeed.
            self._c.rate_limit_ids.discard(vid)
            raise _rate_limit_error(0)
        if vid in self._c.error_ids:
            raise LenzError(message=f"detail {vid} boom")
        return _FakeModel(self._c.detail.get(vid, {"verification_id": vid}))

    async def related(self, vid: str, limit: int = 5) -> _FakeRelated:
        self._c.related_calls.append((vid, limit))
        if vid in self._c.error_ids:
            raise LenzError(message=f"related {vid} requires a key")
        return _FakeRelated([_FakeModel({"verification_id": f"{vid}-r"})])


class FakeClient:
    def __init__(
        self,
        catalog: list[tuple[str, str]],
        detail: dict | None = None,
        *,
        error_ids: set[str] | None = None,
        rate_limit_ids: set[str] | None = None,
        list_error_on_page: int | None = None,
    ) -> None:
        self.catalog = catalog
        self.detail = detail or {}
        self.error_ids = error_ids or set()
        self.rate_limit_ids = rate_limit_ids or set()
        self.list_error_on_page = list_error_on_page
        self.get_calls: list[str] = []
        self.related_calls: list[tuple[str, int]] = []
        self.list_calls: list[int] = []
        self.library = _FakeLibrary(self)
        self.verifications = _FakeVerifications(self)


def _rate_limit_error(retry_after: int) -> LenzRateLimitError:
    try:
        err = LenzRateLimitError("rate limited")
    except TypeError:  # unknown constructor signature
        err = LenzRateLimitError.__new__(LenzRateLimitError)
    err.retry_after = retry_after
    return err


def _sync(client, cache_dir, **kwargs):
    """Run the async sync to completion, as build.py does."""
    return asyncio.run(fetch.sync(client, cache_dir, **kwargs))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Never actually sleep during fetch tests."""

    async def _instant(*a, **k):
        return None

    monkeypatch.setattr(fetch, "_sleep", _instant)


def _detail_for(vid: str) -> dict:
    return {
        "verification_id": vid,
        "claim": f"claim {vid}",
        "verdict": "False",
        "language": "en",
        "created_at": CREATED,
        "completed_at": LATER,
    }


# --------------------------------------------------------------------------- #
# Cache decisions
# --------------------------------------------------------------------------- #


def test_new_id_is_fetched_and_cached(tmp_path):
    client = FakeClient(
        catalog=[("A", LATER)],
        detail={"A": _detail_for("A")},
    )
    stats = _sync(client, tmp_path)
    assert stats.new == 1
    assert client.get_calls == ["A"]
    cache_file = tmp_path / "claims" / "A.json"
    assert cache_file.exists()
    doc = json.loads(cache_file.read_text())
    assert doc["detail"]["verification_id"] == "A"
    assert "related" in doc and "fetched_at" in doc
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["A"] == LATER


def test_unchanged_id_skipped_zero_detail_calls(tmp_path, write_cache):
    doc = {
        "detail": _detail_for("A"),
        "related": [],
        "fetched_at": "2026-07-01T00:00:00+00:00",
    }
    doc["detail"]["completed_at"] = LATER
    write_cache(tmp_path, [doc])
    client = FakeClient(catalog=[("A", LATER)])
    stats = _sync(client, tmp_path)
    assert stats.unchanged == 1
    assert stats.fetched == 0
    assert client.get_calls == []  # the incremental win: no detail fetch


def test_changed_completed_at_refetched(tmp_path, write_cache):
    doc = {
        "detail": _detail_for("A"),
        "related": [],
        "fetched_at": "2026-07-01T00:00:00+00:00",
    }
    doc["detail"]["completed_at"] = LATER
    write_cache(tmp_path, [doc])
    client = FakeClient(
        catalog=[("A", LATER2)],  # moved
        detail={"A": _detail_for("A")},
    )
    stats = _sync(client, tmp_path)
    assert stats.updated == 1
    assert client.get_calls == ["A"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["A"] == LATER2


def test_disappeared_id_dropped_on_full_walk(tmp_path, write_cache):
    docs = [
        {"detail": _detail_for(v), "related": [], "fetched_at": "x"} for v in ("A", "B")
    ]
    for d in docs:
        d["detail"]["completed_at"] = LATER
    write_cache(tmp_path, docs)
    # Catalog now only has A — B has vanished.
    client = FakeClient(catalog=[("A", LATER)])
    stats = _sync(client, tmp_path, max_pages=None)
    assert stats.dropped == 1
    assert not (tmp_path / "claims" / "B.json").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "B" not in manifest
    assert "A" in manifest


def test_disappeared_id_kept_when_max_pages_set(tmp_path, write_cache):
    docs = [
        {"detail": _detail_for(v), "related": [], "fetched_at": "x"} for v in ("A", "B")
    ]
    for d in docs:
        d["detail"]["completed_at"] = LATER
    write_cache(tmp_path, docs)
    client = FakeClient(catalog=[("A", LATER)])
    stats = _sync(client, tmp_path, max_pages=1)
    # Partial walk must NOT mass-delete: B survives.
    assert stats.dropped == 0
    assert (tmp_path / "claims" / "B.json").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "B" in manifest


def test_per_claim_error_logged_counted_skipped(tmp_path, caplog):
    client = FakeClient(
        catalog=[("A", LATER), ("B", LATER2)],
        detail={"A": _detail_for("A")},
        error_ids={"B"},
    )
    with caplog.at_level("WARNING"):
        stats = _sync(client, tmp_path)
    assert stats.errors == 1
    assert stats.new == 1  # A succeeded
    assert (tmp_path / "claims" / "A.json").exists()
    assert not (tmp_path / "claims" / "B.json").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "A" in manifest and "B" not in manifest
    assert any("B" in rec.message for rec in caplog.records)


def test_rate_limit_retried_once_then_succeeds(tmp_path):
    client = FakeClient(
        catalog=[("A", LATER)],
        detail={"A": _detail_for("A")},
        rate_limit_ids={"A"},
    )
    stats = _sync(client, tmp_path)
    assert stats.new == 1
    assert stats.errors == 0
    assert client.get_calls == ["A", "A"]  # first attempt + retry


def test_list_page_error_stops_walk_no_drop(tmp_path, write_cache):
    doc = {"detail": _detail_for("A"), "related": [], "fetched_at": "x"}
    doc["detail"]["completed_at"] = LATER
    write_cache(tmp_path, [doc])
    client = FakeClient(catalog=[("A", LATER)], list_error_on_page=1)
    stats = _sync(client, tmp_path)
    assert stats.errors == 1
    # Documented intent: an incomplete walk must NOT drop anything; A survives.
    assert stats.dropped == 0
    assert (tmp_path / "claims" / "A.json").exists()


def test_api_version_mismatch_is_named_in_the_log(tmp_path, caplog):
    # lenz-io 3 refuses a reply in another API version. The build must say so
    # in words (not as an anonymous "page failed"), stop the walk, and drop nothing.
    client = FakeClient(catalog=[("A", LATER)], detail={"A": _detail_for("A")})

    async def _wrong_version(page: int = 1, sort: str = "recent"):
        raise LenzApiVersionError(api_version="2026-05-13")

    client.library.list = _wrong_version
    with caplog.at_level("WARNING"):
        stats = _sync(client, tmp_path)
    assert stats.errors == 1
    assert stats.dropped == 0
    assert any(
        "2026-05-13" in rec.getMessage() and "out of step" in rec.getMessage()
        for rec in caplog.records
    )


def test_manifest_written_atomically_and_parses(tmp_path):
    client = FakeClient(
        catalog=[("A", LATER)],
        detail={"A": _detail_for("A")},
    )
    _sync(client, tmp_path)
    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    # No leftover temp file.
    assert not (tmp_path / "manifest.json.tmp").exists()
    assert isinstance(json.loads(manifest_path.read_text()), dict)


def test_pagination_covers_full_catalog(tmp_path):
    catalog = [(f"V{i:03d}", LATER) for i in range(45)]  # 3 pages of 20
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    client = FakeClient(catalog=catalog, detail=detail)
    stats = _sync(client, tmp_path)
    assert stats.new == 45
    assert client.list_calls == [1, 2, 3]
    files = list((tmp_path / "claims").glob("*.json"))
    assert len(files) == 45


# --------------------------------------------------------------------------- #
# load_raw
# --------------------------------------------------------------------------- #


def test_load_raw_skips_corrupt_and_non_object(tmp_path):
    claims = tmp_path / "claims"
    claims.mkdir(parents=True)
    (claims / "good.json").write_text(
        json.dumps({"detail": {"verification_id": "good"}}), encoding="utf-8"
    )
    (claims / "corrupt.json").write_text("{not valid json", encoding="utf-8")
    (claims / "list.json").write_text("[1, 2, 3]", encoding="utf-8")
    docs = fetch.load_raw(tmp_path)
    assert len(docs) == 1
    assert docs[0]["detail"]["verification_id"] == "good"


def test_load_raw_missing_dir_returns_empty(tmp_path):
    assert fetch.load_raw(tmp_path / "nope") == []


def test_mass_drop_guard_refuses_catalog_collapse(tmp_path):
    """Eng-review F1: an anomalously tiny-but-'complete' catalog must never
    gut the cache (deploying a near-empty site). >20% prospective drops are
    refused and surfaced as an error."""
    # Seed a 100-claim cache via a full sync.
    catalog = [(f"W{i:04d}", LATER) for i in range(100)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    _sync(FakeClient(catalog=catalog, detail=detail), tmp_path)
    assert len(list((tmp_path / "claims").glob("*.json"))) == 100

    # Upstream anomaly: the catalog "completely" walks to only 5 claims.
    tiny = catalog[:5]
    stats = _sync(FakeClient(catalog=tiny, detail=detail), tmp_path)
    assert stats.dropped == 0  # refused
    assert stats.errors >= 1  # surfaced, not silent
    assert len(list((tmp_path / "claims").glob("*.json"))) == 100


def test_small_drop_still_works(tmp_path):
    """Normal churn (a few claims removed upstream) drops fine."""
    catalog = [(f"X{i:04d}", LATER) for i in range(30)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    _sync(FakeClient(catalog=catalog, detail=detail), tmp_path)

    smaller = catalog[:25]  # 5 of 30 gone — under max(10, 30//5=6)... floor 10
    stats = _sync(FakeClient(catalog=smaller, detail=detail), tmp_path)
    assert stats.dropped == 5
    assert len(list((tmp_path / "claims").glob("*.json"))) == 25


def test_related_backfill_fills_empty_lists(tmp_path):
    """Once the related endpoint is reachable, cached docs with empty
    related lists get filled on the next full sync (unchanged claims
    never refetch, so without this they'd stay empty forever)."""
    catalog = [(f"B{i:04d}", LATER) for i in range(3)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    client = FakeClient(catalog=catalog, detail=detail)
    _sync(client, tmp_path)  # populates cache (fake related non-empty)

    # Simulate the keyless-era gap: blank out the related lists.
    for f in (tmp_path / "claims").glob("*.json"):
        doc = json.loads(f.read_text())
        doc["related"] = []
        f.write_text(json.dumps(doc))

    client2 = FakeClient(catalog=catalog, detail=detail)
    _sync(client2, tmp_path)  # unchanged walk + backfill pass
    for f in (tmp_path / "claims").glob("*.json"):
        assert json.loads(f.read_text())["related"], f"{f.name} not backfilled"


def test_related_backfill_skips_when_unavailable(tmp_path):
    """While the endpoint still needs a key, ONE probe fails and the pass
    bows out — no per-claim hammering."""
    catalog = [(f"C{i:04d}", LATER) for i in range(5)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    _sync(FakeClient(catalog=catalog, detail=detail), tmp_path)
    for f in (tmp_path / "claims").glob("*.json"):
        doc = json.loads(f.read_text())
        doc["related"] = []
        f.write_text(json.dumps(doc))

    client = FakeClient(
        catalog=catalog, detail=detail, error_ids={vid for vid, _ in catalog}
    )
    calls_before = len(client.related_calls)
    _sync(client, tmp_path)
    # probe = at most one related call beyond the (zero) refetches
    assert len(client.related_calls) - calls_before <= 1


def _age_doc(path, *, days: float, related=None) -> None:
    """Rewrite a cache doc as if it were fetched ``days`` ago."""
    from datetime import UTC, datetime, timedelta

    doc = json.loads(path.read_text())
    stamp = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    doc["fetched_at"] = stamp
    doc.pop("related_refreshed_at", None)
    if related is not None:
        doc["related"] = related
    path.write_text(json.dumps(doc))


def test_related_refresh_rotates_stale_docs(tmp_path):
    """A doc whose related list was last (re)fetched over the refresh horizon
    ago gets re-fetched on the next sync — new neighbors published since the
    original build show up on old articles. Fresh docs are left alone."""
    catalog = [("STALE001", LATER), ("FRESH001", LATER)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    client = FakeClient(catalog=catalog, detail=detail)
    _sync(client, tmp_path)

    _age_doc(tmp_path / "claims" / "STALE001.json", days=30)

    client2 = FakeClient(catalog=catalog, detail=detail)
    _sync(client2, tmp_path)
    refreshed = [vid for vid, _ in client2.related_calls]
    assert "STALE001" in refreshed
    assert "FRESH001" not in refreshed
    doc = json.loads((tmp_path / "claims" / "STALE001.json").read_text())
    assert doc["related_refreshed_at"]  # stamped so it waits a full cycle


def test_related_refresh_respects_budget(tmp_path, monkeypatch):
    """Per-build cap: only the N stalest docs refresh in one sync, so an 8h
    CI build stays bounded no matter how big the catalog grows."""
    catalog = [(f"R{i:04d}", LATER) for i in range(6)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    _sync(FakeClient(catalog=catalog, detail=detail), tmp_path)
    for i, (vid, _) in enumerate(catalog):
        _age_doc(tmp_path / "claims" / f"{vid}.json", days=30 + i)

    monkeypatch.setattr(fetch, "RELATED_REFRESH_BUDGET", 2)
    client = FakeClient(catalog=catalog, detail=detail)
    _sync(client, tmp_path)
    # oldest two only (R0005 aged 35d, R0004 aged 34d); parallel workers make
    # the call ORDER nondeterministic, the SELECTION is what's contractual.
    assert {vid for vid, _ in client.related_calls} == {"R0005", "R0004"}


def test_related_refresh_stamps_empty_results(tmp_path):
    """A claim with genuinely no neighbors gets its (empty) result STAMPED —
    it must not be re-probed every single build (the old backfill hit every
    empty list on every sync, ~1.3k calls/build for nothing)."""
    catalog = [("EMPTY001", LATER)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    _sync(FakeClient(catalog=catalog, detail=detail), tmp_path)
    path = tmp_path / "claims" / "EMPTY001.json"
    _age_doc(path, days=30, related=[])

    client = FakeClient(catalog=catalog, detail=detail)
    _sync(client, tmp_path)  # stale → refreshed
    doc = json.loads(path.read_text())
    assert doc["related_refreshed_at"]

    # Simulate "server says: no neighbors" — empty list but freshly stamped.
    doc["related"] = []
    path.write_text(json.dumps(doc))
    client2 = FakeClient(catalog=catalog, detail=detail)
    _sync(client2, tmp_path)  # freshly stamped → NOT probed again
    assert client2.related_calls == []


class _SlowClient(FakeClient):
    """FakeClient whose detail fetches take a moment, and which records how many
    are in flight simultaneously: proves the fan-out overlaps requests and
    never exceeds its bound."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active = 0
        self.peak_concurrency = 0
        real_get = self.verifications.get

        async def slow_get(vid):
            self._active += 1
            self.peak_concurrency = max(self.peak_concurrency, self._active)
            try:
                # The real asyncio.sleep: only fetch._sleep is stubbed out.
                await asyncio.sleep(0.01)
                return await real_get(vid)
            finally:
                self._active -= 1

        self.verifications.get = slow_get


def test_detail_fetches_run_concurrently_up_to_the_bound(tmp_path):
    """New/changed claims fetch concurrently, not one by one, and never more
    than FETCH_WORKERS at once: the difference between an ~80min and a ~10min
    CI build when a large upstream batch changes, without hitting the API's
    rate limit harder. Correctness must be unchanged: every doc cached,
    manifest complete."""
    catalog = [(f"P{i:04d}", LATER) for i in range(12)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    client = _SlowClient(catalog=catalog, detail=detail)
    stats = _sync(client, tmp_path)

    assert stats.new == 12 and stats.errors == 0
    assert client.peak_concurrency == fetch.FETCH_WORKERS
    assert len(list((tmp_path / "claims").glob("*.json"))) == 12
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert set(manifest) == {vid for vid, _ in catalog}


def test_the_bound_is_the_constant(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "FETCH_WORKERS", 2)
    catalog = [(f"Q{i:04d}", LATER) for i in range(8)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    client = _SlowClient(catalog=catalog, detail=detail)
    _sync(client, tmp_path)
    assert client.peak_concurrency == 2


def test_related_refresh_is_bounded_too(tmp_path, monkeypatch):
    catalog = [(f"S{i:04d}", LATER) for i in range(10)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    _sync(FakeClient(catalog=catalog, detail=detail), tmp_path)
    for vid, _ in catalog:
        _age_doc(tmp_path / "claims" / f"{vid}.json", days=30)

    monkeypatch.setattr(fetch, "FETCH_WORKERS", 3)
    client = FakeClient(catalog=catalog, detail=detail)
    active = peak = 0
    real_related = client.verifications.related

    async def counted(vid, limit=5):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            return await real_related(vid, limit)
        finally:
            active -= 1

    client.verifications.related = counted
    _sync(client, tmp_path)
    assert len({vid for vid, _ in client.related_calls}) == 10
    assert peak == 3


def test_rate_limit_waits_retry_after_capped(tmp_path, monkeypatch):
    slept: list[float] = []

    async def record(seconds, *a, **k):
        slept.append(seconds)

    monkeypatch.setattr(fetch, "_sleep", record)
    client = FakeClient(
        catalog=[("A", LATER), ("B", LATER)],
        detail={"A": _detail_for("A"), "B": _detail_for("B")},
        rate_limit_ids={"A", "B"},
    )
    original = client.verifications.get
    limits = {"A": 5, "B": 9999}

    async def get(vid):
        try:
            return await original(vid)
        except LenzRateLimitError:
            raise _rate_limit_error(limits[vid]) from None

    client.verifications.get = get
    stats = _sync(client, tmp_path)
    assert stats.new == 2 and stats.errors == 0
    assert 5 in slept and fetch.MAX_RETRY_AFTER in slept
    assert 9999 not in slept


def test_a_failure_that_is_not_an_sdk_error_fails_the_build(tmp_path):
    """Per-claim SDK errors are skipped; anything else is a bug and must not
    be swallowed into a green build."""
    client = FakeClient(
        catalog=[("A", LATER), ("B", LATER)],
        detail={"A": _detail_for("A"), "B": _detail_for("B")},
    )
    original = client.verifications.get

    async def get(vid):
        if vid == "B":
            raise RuntimeError("not an SDK error")
        return await original(vid)

    client.verifications.get = get
    with pytest.raises(RuntimeError):
        _sync(client, tmp_path)
    # nothing was recorded as fetched: the manifest was never written
    assert not (tmp_path / "manifest.json").exists()
