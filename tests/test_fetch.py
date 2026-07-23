"""Tests for the incremental fetch/cache layer, driven by a fake SDK client."""

from __future__ import annotations

import json

import pytest

# Real SDK exception types — imported (fetch.py already needs the SDK present).
from lenz_io import LenzError, LenzRateLimitError

from isthisbs import fetch
from isthisbs.config import PAGE_SIZE

# --------------------------------------------------------------------------- #
# Fake SDK
# --------------------------------------------------------------------------- #


class _FakeItem:
    def __init__(self, vid: str, modified_at: str) -> None:
        self.verification_id = vid
        self.modified_at = modified_at


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

    def list(self, page: int = 1, sort: str = "recent") -> _FakeList:
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

    def get(self, vid: str) -> _FakeModel:
        self._c.get_calls.append(vid)
        if vid in self._c.rate_limit_ids:
            # Only rate-limit the first attempt for an id, then succeed.
            self._c.rate_limit_ids.discard(vid)
            raise _rate_limit_error(0)
        if vid in self._c.error_ids:
            raise LenzError(message=f"detail {vid} boom")
        return _FakeModel(self._c.detail.get(vid, {"verification_id": vid}))

    def related(self, vid: str, limit: int = 5) -> _FakeRelated:
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


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Never actually sleep during fetch tests."""
    monkeypatch.setattr(fetch.time, "sleep", lambda *a, **k: None)


def _detail_for(vid: str) -> dict:
    return {
        "verification_id": vid,
        "claim": f"claim {vid}",
        "verdict": "False",
        "language": "en",
    }


# --------------------------------------------------------------------------- #
# Cache decisions
# --------------------------------------------------------------------------- #


def test_new_id_is_fetched_and_cached(tmp_path):
    client = FakeClient(
        catalog=[("A", "2026-07-01T00:00:00Z")],
        detail={"A": _detail_for("A")},
    )
    stats = fetch.sync(client, tmp_path)
    assert stats.new == 1
    assert client.get_calls == ["A"]
    cache_file = tmp_path / "claims" / "A.json"
    assert cache_file.exists()
    doc = json.loads(cache_file.read_text())
    assert doc["detail"]["verification_id"] == "A"
    assert "related" in doc and "fetched_at" in doc
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["A"] == "2026-07-01T00:00:00Z"


def test_unchanged_id_skipped_zero_detail_calls(tmp_path, write_cache):
    doc = {
        "detail": _detail_for("A"),
        "related": [],
        "fetched_at": "2026-07-01T00:00:00+00:00",
    }
    doc["detail"]["modified_at"] = "2026-07-01T00:00:00Z"
    write_cache(tmp_path, [doc])
    client = FakeClient(catalog=[("A", "2026-07-01T00:00:00Z")])
    stats = fetch.sync(client, tmp_path)
    assert stats.unchanged == 1
    assert stats.fetched == 0
    assert client.get_calls == []  # the incremental win: no detail fetch


def test_changed_modified_at_refetched(tmp_path, write_cache):
    doc = {
        "detail": _detail_for("A"),
        "related": [],
        "fetched_at": "2026-07-01T00:00:00+00:00",
    }
    doc["detail"]["modified_at"] = "2026-07-01T00:00:00Z"
    write_cache(tmp_path, [doc])
    client = FakeClient(
        catalog=[("A", "2026-07-05T00:00:00Z")],  # moved
        detail={"A": _detail_for("A")},
    )
    stats = fetch.sync(client, tmp_path)
    assert stats.updated == 1
    assert client.get_calls == ["A"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["A"] == "2026-07-05T00:00:00Z"


def test_disappeared_id_dropped_on_full_walk(tmp_path, write_cache):
    docs = [
        {"detail": _detail_for(v), "related": [], "fetched_at": "x"} for v in ("A", "B")
    ]
    for d in docs:
        d["detail"]["modified_at"] = "m"
    write_cache(tmp_path, docs)
    # Catalog now only has A — B has vanished.
    client = FakeClient(catalog=[("A", "m")])
    stats = fetch.sync(client, tmp_path, max_pages=None)
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
        d["detail"]["modified_at"] = "m"
    write_cache(tmp_path, docs)
    client = FakeClient(catalog=[("A", "m")])
    stats = fetch.sync(client, tmp_path, max_pages=1)
    # Partial walk must NOT mass-delete: B survives.
    assert stats.dropped == 0
    assert (tmp_path / "claims" / "B.json").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "B" in manifest


def test_per_claim_error_logged_counted_skipped(tmp_path, caplog):
    client = FakeClient(
        catalog=[("A", "m1"), ("B", "m2")],
        detail={"A": _detail_for("A")},
        error_ids={"B"},
    )
    with caplog.at_level("WARNING"):
        stats = fetch.sync(client, tmp_path)
    assert stats.errors == 1
    assert stats.new == 1  # A succeeded
    assert (tmp_path / "claims" / "A.json").exists()
    assert not (tmp_path / "claims" / "B.json").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "A" in manifest and "B" not in manifest
    assert any("B" in rec.message for rec in caplog.records)


def test_rate_limit_retried_once_then_succeeds(tmp_path):
    client = FakeClient(
        catalog=[("A", "m")],
        detail={"A": _detail_for("A")},
        rate_limit_ids={"A"},
    )
    stats = fetch.sync(client, tmp_path)
    assert stats.new == 1
    assert stats.errors == 0
    assert client.get_calls == ["A", "A"]  # first attempt + retry


def test_list_page_error_stops_walk_no_drop(tmp_path, write_cache):
    doc = {"detail": _detail_for("A"), "related": [], "fetched_at": "x"}
    doc["detail"]["modified_at"] = "m"
    write_cache(tmp_path, [doc])
    client = FakeClient(catalog=[("A", "m")], list_error_on_page=1)
    stats = fetch.sync(client, tmp_path)
    assert stats.errors == 1
    # Documented intent: an incomplete walk must NOT drop anything; A survives.
    assert stats.dropped == 0
    assert (tmp_path / "claims" / "A.json").exists()


def test_manifest_written_atomically_and_parses(tmp_path):
    client = FakeClient(
        catalog=[("A", "m")],
        detail={"A": _detail_for("A")},
    )
    fetch.sync(client, tmp_path)
    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    # No leftover temp file.
    assert not (tmp_path / "manifest.json.tmp").exists()
    assert isinstance(json.loads(manifest_path.read_text()), dict)


def test_pagination_covers_full_catalog(tmp_path):
    catalog = [(f"V{i:03d}", "m") for i in range(45)]  # 3 pages of 20
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    client = FakeClient(catalog=catalog, detail=detail)
    stats = fetch.sync(client, tmp_path)
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
    catalog = [(f"W{i:04d}", "m") for i in range(100)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    fetch.sync(FakeClient(catalog=catalog, detail=detail), tmp_path)
    assert len(list((tmp_path / "claims").glob("*.json"))) == 100

    # Upstream anomaly: the catalog "completely" walks to only 5 claims.
    tiny = catalog[:5]
    stats = fetch.sync(FakeClient(catalog=tiny, detail=detail), tmp_path)
    assert stats.dropped == 0  # refused
    assert stats.errors >= 1  # surfaced, not silent
    assert len(list((tmp_path / "claims").glob("*.json"))) == 100


def test_small_drop_still_works(tmp_path):
    """Normal churn (a few claims removed upstream) drops fine."""
    catalog = [(f"X{i:04d}", "m") for i in range(30)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    fetch.sync(FakeClient(catalog=catalog, detail=detail), tmp_path)

    smaller = catalog[:25]  # 5 of 30 gone — under max(10, 30//5=6)... floor 10
    stats = fetch.sync(FakeClient(catalog=smaller, detail=detail), tmp_path)
    assert stats.dropped == 5
    assert len(list((tmp_path / "claims").glob("*.json"))) == 25


def test_related_backfill_fills_empty_lists(tmp_path):
    """Once the related endpoint is reachable, cached docs with empty
    related lists get filled on the next full sync (unchanged claims
    never refetch, so without this they'd stay empty forever)."""
    catalog = [(f"B{i:04d}", "m") for i in range(3)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    client = FakeClient(catalog=catalog, detail=detail)
    fetch.sync(client, tmp_path)  # populates cache (fake related non-empty)

    # Simulate the keyless-era gap: blank out the related lists.
    for f in (tmp_path / "claims").glob("*.json"):
        doc = json.loads(f.read_text())
        doc["related"] = []
        f.write_text(json.dumps(doc))

    client2 = FakeClient(catalog=catalog, detail=detail)
    fetch.sync(client2, tmp_path)  # unchanged walk + backfill pass
    for f in (tmp_path / "claims").glob("*.json"):
        assert json.loads(f.read_text())["related"], f"{f.name} not backfilled"


def test_related_backfill_skips_when_unavailable(tmp_path):
    """While the endpoint still needs a key, ONE probe fails and the pass
    bows out — no per-claim hammering."""
    catalog = [(f"C{i:04d}", "m") for i in range(5)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    fetch.sync(FakeClient(catalog=catalog, detail=detail), tmp_path)
    for f in (tmp_path / "claims").glob("*.json"):
        doc = json.loads(f.read_text())
        doc["related"] = []
        f.write_text(json.dumps(doc))

    client = FakeClient(
        catalog=catalog, detail=detail, error_ids={vid for vid, _ in catalog}
    )
    calls_before = len(client.related_calls)
    fetch.sync(client, tmp_path)
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
    catalog = [("STALE001", "m"), ("FRESH001", "m")]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    client = FakeClient(catalog=catalog, detail=detail)
    fetch.sync(client, tmp_path)

    _age_doc(tmp_path / "claims" / "STALE001.json", days=30)

    client2 = FakeClient(catalog=catalog, detail=detail)
    fetch.sync(client2, tmp_path)
    refreshed = [vid for vid, _ in client2.related_calls]
    assert "STALE001" in refreshed
    assert "FRESH001" not in refreshed
    doc = json.loads((tmp_path / "claims" / "STALE001.json").read_text())
    assert doc["related_refreshed_at"]  # stamped so it waits a full cycle


def test_related_refresh_respects_budget(tmp_path, monkeypatch):
    """Per-build cap: only the N stalest docs refresh in one sync, so an 8h
    CI build stays bounded no matter how big the catalog grows."""
    catalog = [(f"R{i:04d}", "m") for i in range(6)]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    fetch.sync(FakeClient(catalog=catalog, detail=detail), tmp_path)
    for i, (vid, _) in enumerate(catalog):
        _age_doc(tmp_path / "claims" / f"{vid}.json", days=30 + i)

    monkeypatch.setattr(fetch, "RELATED_REFRESH_BUDGET", 2)
    client = FakeClient(catalog=catalog, detail=detail)
    fetch.sync(client, tmp_path)
    # oldest two only (R0005 aged 35d, R0004 aged 34d)
    assert [vid for vid, _ in client.related_calls] == ["R0005", "R0004"]


def test_related_refresh_stamps_empty_results(tmp_path):
    """A claim with genuinely no neighbors gets its (empty) result STAMPED —
    it must not be re-probed every single build (the old backfill hit every
    empty list on every sync, ~1.3k calls/build for nothing)."""
    catalog = [("EMPTY001", "m")]
    detail = {vid: _detail_for(vid) for vid, _ in catalog}
    fetch.sync(FakeClient(catalog=catalog, detail=detail), tmp_path)
    path = tmp_path / "claims" / "EMPTY001.json"
    _age_doc(path, days=30, related=[])

    client = FakeClient(catalog=catalog, detail=detail)
    fetch.sync(client, tmp_path)  # stale → refreshed
    doc = json.loads(path.read_text())
    assert doc["related_refreshed_at"]

    # Simulate "server says: no neighbors" — empty list but freshly stamped.
    doc["related"] = []
    path.write_text(json.dumps(doc))
    client2 = FakeClient(catalog=catalog, detail=detail)
    fetch.sync(client2, tmp_path)  # freshly stamped → NOT probed again
    assert client2.related_calls == []
