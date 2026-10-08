"""The build and the live function against both API response shapes.

This release asks for the newer shape (``X-Lenz-API-Version: 2026-10-11``),
where the change time is ``completed_at`` (always set) instead of
``modified_at`` (set only when a claim completed on a later calendar day
than it was created). The build derives the older value from the newer
fields, so everything it renders and every change key it stores is the same
under either shape. Bodies in the older shape still work exactly as before.

Fixtures in ``tests/fixtures/api_shapes.json`` are loaded fresh for every
test and parsed through the real ``lenz_io`` models, as the build does.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest
from lenz_io.models import LibraryItem, Verification

from functions import live_core
from isthisbs import content, fetch

_PATH = Path(__file__).parent / "fixtures" / "api_shapes.json"
SHAPES = ("legacy", "canonical")


def _fx() -> dict:
    return json.loads(_PATH.read_text())  # fresh copy: tests may mutate


def _cached_doc(body: dict) -> dict:
    """What fetch.py writes: the SDK model dumped to JSON."""
    model = Verification.model_validate(body)
    return {"detail": model.model_dump(mode="json"), "related": [], "fetched_at": "x"}


def _item(body: dict) -> LibraryItem:
    return LibraryItem.model_validate(body)


def test_fixtures_hold_both_shapes():
    fx = _fx()
    assert "modified_at" in fx["legacy"]["detail"]
    assert "completed_at" not in fx["legacy"]["detail"]
    assert "completed_at" in fx["canonical"]["detail"]
    assert "modified_at" not in fx["canonical"]["detail"]


def test_legacy_check_keeps_reading_modified_at():
    check = content._parse_check(_cached_doc(_fx()["legacy"]["detail"]))
    assert check is not None
    assert check.modified_at == "2026-09-02T09:30:00.123456+00:00"
    assert check.verdict_key == "True"
    assert check.key_finding == "The Earth is approximately spherical in shape."
    assert [s.source_name for s in check.sources] == ["NASA", "ESA"]


def test_canonical_check_parses():
    check = content._parse_check(_cached_doc(_fx()["canonical"]["detail"]))
    assert check is not None
    assert check.claim == "The Earth is round."
    assert check.verdict_key == "True"
    assert [s.source_name for s in check.sources] == ["NASA", "ESA"]
    # completed a day after it was created -> the older modified_at
    assert check.modified_at == "2026-09-02T09:30:00.123456+00:00"


def test_legacy_list_item_key_is_modified_at():
    assert (
        fetch._change_key(_item(_fx()["legacy"]["library_item"]))
        == "2026-09-02T09:30:00.123456+00:00"
    )


def test_same_day_item_keeps_an_empty_key():
    """modified_at is null for a same-day claim; completed_at must not change
    the key (that would refetch every same-day claim)."""
    item = _item(_fx()["same_day_library_item"])
    assert item.modified_at is None
    assert fetch._change_key(item) == ""


def test_canonical_list_item_key_equals_the_legacy_key():
    """Existing manifests hold the older modified_at; the same value must come
    out of the newer fields, or the whole catalog refetches once."""
    fx = _fx()
    assert fetch._change_key(
        _item(fx["canonical"]["library_item"])
    ) == fetch._change_key(_item(fx["legacy"]["library_item"]))


class _Bare:
    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


def test_change_key_without_a_modified_at_attribute():
    later = _Bare(
        created_at="2026-09-01T23:00:00+00:00", completed_at="2026-09-02T00:01:00Z"
    )
    assert fetch._change_key(later) == "2026-09-02T00:01:00Z"
    assert fetch._change_key(_Bare()) == ""
    assert fetch._change_key(_Bare(completed_at="2026-09-02T09:30:00+00:00")) == ""


# The two boundary cases the API's own contract fixtures use: minutes apart
# across midnight (UTC) -> set; hours apart on one day -> not set.
_PAIRS = {
    "crosses_midnight": (
        "2026-03-14T23:58:01.123456+00:00",
        "2026-03-15T00:03:02.234567+00:00",
        "2026-03-15T00:03:02.234567+00:00",
    ),
    "same_day": (
        "2026-03-14T09:00:01.123456+00:00",
        "2026-03-14T17:30:02.234567+00:00",
        "",
    ),
    # not UTC on the wire: the day is judged in UTC
    "offset_same_utc_day": (
        "2026-03-14T01:00:00+02:00",
        "2026-03-13T23:30:00+00:00",
        "",
    ),
    "completed_equals_created": (
        "2026-03-14T09:00:01.123456+00:00",
        "2026-03-14T09:00:01.123456+00:00",
        "",
    ),
}


@pytest.mark.parametrize("name", sorted(_PAIRS))
def test_newer_fields_give_the_older_change_time(name):
    created, completed, expected = _PAIRS[name]
    legacy = _fx()["legacy"]["detail"] | {
        "created_at": created,
        "modified_at": expected or None,
    }
    canonical = {k: v for k, v in legacy.items() if k != "modified_at"}
    canonical["completed_at"] = completed
    old = content._parse_check(_cached_doc(legacy))
    new = content._parse_check(_cached_doc(canonical))
    assert old is not None and new is not None
    assert new.modified_at == old.modified_at == expected
    assert new == old  # every field the site renders is identical

    item_legacy = _fx()["legacy"]["library_item"] | {
        "created_at": created,
        "modified_at": expected or None,
    }
    item_canonical = {k: v for k, v in item_legacy.items() if k != "modified_at"}
    item_canonical["completed_at"] = completed
    assert (
        fetch._change_key(_item(item_canonical))
        == fetch._change_key(_item(item_legacy))
        == expected
    )


def test_unparseable_times_give_no_change_time():
    assert fetch._change_key(_item({"created_at": "x", "completed_at": "y"})) == ""
    assert (
        fetch._change_key(
            _item({"created_at": None, "completed_at": "2026-03-15T00:00:00+00:00"})
        )
        == ""
    )


class _Resp:
    def __init__(self, body: dict) -> None:
        self._raw = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self._raw


def _serve(monkeypatch, body: dict) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(body))


@pytest.mark.parametrize("shape", SHAPES)
def test_live_fetch_serves_either_shape(shape, monkeypatch):
    _serve(monkeypatch, _fx()[shape]["detail"])
    detail = live_core.fetch_detail("a1b2c3d4")
    assert detail is not None
    assert detail["verdict"] == "True"
    assert detail["key_finding"].startswith("The Earth")
    assert len(detail["sources"]) == 2


@pytest.mark.parametrize("failed", ["failed_legacy", "failed_canonical"])
def test_live_fetch_never_renders_a_failed_item(failed, monkeypatch):
    _serve(monkeypatch, _fx()[failed])
    assert live_core.fetch_detail("a1b2c3d4") is None


def test_legacy_failed_body_is_the_error_verdict():
    assert _fx()["failed_legacy"]["verdict"] == "Error"


def test_older_shape_output_is_byte_identical_to_origin_main():
    """Frozen oracle: the pre-change code's outputs over the older-shape cases
    (provenance inside the file). This tree must reproduce them exactly."""
    import oracle_run

    frozen = json.loads((_PATH.parent / "origin_main_oracle.json").read_text())
    assert frozen["provenance"]["origin_main_commit"]
    fresh = json.dumps(oracle_run.run(), indent=1, sort_keys=True, ensure_ascii=False)
    expected = json.dumps(
        frozen["outputs"], indent=1, sort_keys=True, ensure_ascii=False
    )
    assert fresh == expected


@pytest.mark.parametrize("bad", [5, ["x"], {"a": 1}, True])
def test_live_non_text_key_finding_is_no_result_and_builders_do_not_crash(
    bad, monkeypatch
):
    body = _fx()["legacy"]["detail"] | {"key_finding": bad}
    _serve(monkeypatch, body)
    assert live_core.fetch_detail("a1b2c3d4") is None
    # the builders themselves tolerate it too
    assert "<h1></h1>" in live_core.build_live_html(body)


def test_live_failure_object_is_no_result(monkeypatch):
    _serve(monkeypatch, _fx()["failed_canonical"] | {"status": "completed"})
    assert live_core.fetch_detail("a1b2c3d4") is None


def test_live_legacy_body_with_status_failed_but_a_verdict_is_still_served(
    monkeypatch,
):
    """As origin/main did: only the verdict decided."""
    _serve(monkeypatch, _fx()["legacy"]["detail"] | {"status": "failed"})
    assert live_core.fetch_detail("a1b2c3d4") is not None


# --------------------------------------------------------------------------- #
# The version this release asks for
# --------------------------------------------------------------------------- #


def test_the_build_client_sends_the_new_version_and_its_own_agent():
    import build
    from isthisbs import __version__
    from isthisbs.config import API_VERSION

    assert API_VERSION == "2026-10-11"
    client = build._make_client()
    headers = client._client.headers
    assert headers["X-Lenz-API-Version"] == API_VERSION
    assert headers["User-Agent"] == f"isthisbs-media/{__version__}"
    assert headers["Accept"] == "application/json"
    assert not client._client.is_closed
    client.close()
    assert client._client.is_closed  # the build's close() releases the pool


def test_the_live_function_sends_the_new_version(monkeypatch):
    from isthisbs.config import API_VERSION

    seen = {}

    def fake_urlopen(req, *a, **k):
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _Resp(_fx()["canonical"]["detail"])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert live_core.fetch_detail("a1b2c3d4") is not None
    assert seen["headers"]["x-lenz-api-version"] == API_VERSION
    assert seen["headers"]["user-agent"] == "isthisbs-claimlive"


def test_a_catalog_in_the_newer_shape_refetches_nothing_over_an_older_cache(tmp_path):
    """The first build after switching the version header: a manifest written
    from older-shape lists must still match, claim for claim (cross-day and
    same-day), so no detail is fetched again."""
    from lenz_io.models import LibraryList

    fx = _fx()
    cross = fx["legacy"]["library_item"] | {"verification_id": "cross001"}
    same = fx["same_day_library_item"] | {
        "verification_id": "same0001",
        "completed_at": None,
    }
    same_legacy = {k: v for k, v in same.items() if k != "completed_at"}
    # what the previous build stored: the older list item's modified_at
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    claims = tmp_path / "claims"
    claims.mkdir()
    manifest = {}
    for item in (cross, same_legacy):
        vid = item["verification_id"]
        (claims / f"{vid}.json").write_text(
            json.dumps({"detail": {}, "related": [], "related_refreshed_at": now})
        )
        manifest[vid] = item.get("modified_at") or ""
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert manifest["cross001"] and manifest["same0001"] == ""

    # the same two claims as the newer shape sends them
    new_cross = {k: v for k, v in cross.items() if k != "modified_at"} | {
        "completed_at": cross["modified_at"]
    }
    new_same = {k: v for k, v in same_legacy.items() if k != "modified_at"} | {
        "completed_at": same["created_at"][:11] + "17:30:00+00:00"
    }

    class _Library:
        def list(self, page=1, sort="recent"):
            return LibraryList.model_validate(
                {"items": [new_cross, new_same], "total": 2, "page": 1, "page_size": 20}
            )

    class _Client:
        library = _Library()
        verifications = None  # any detail fetch would raise

    stats = fetch.sync(_Client(), tmp_path)
    assert (stats.unchanged, stats.new, stats.updated, stats.errors) == (2, 0, 0, 0)
