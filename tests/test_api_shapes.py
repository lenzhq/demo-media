"""The build and the live function against the Lenz API's 2026-10-11 shape.

The site asks for that response version (``X-Lenz-API-Version``) and reads
only it. In that shape the change time is ``completed_at`` (always set); the
site counts a claim as modified only when it completed on a later UTC calendar
day than it was created, which is the value its change keys, sitemap and
``article:modified_time`` have always carried.

Fixtures in ``tests/fixtures/api_shapes.json`` have the field set of the API's
published response bodies and are loaded fresh for every test; the build parses
them through the real ``lenz_io`` models, as it does in production.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from pathlib import Path

import lenz_io
import pytest
from lenz_io.models import LibraryItem, LibraryList, Verification

from functions import live_core
from isthisbs import content, fetch
from isthisbs.config import API_VERSION, API_VERSION_HEADER

_PATH = Path(__file__).parent / "fixtures" / "api_shapes.json"


def _fx() -> dict:
    return json.loads(_PATH.read_text())  # fresh copy: tests may mutate


def _cached_doc(body: dict) -> dict:
    """What fetch.py writes: the SDK model dumped to JSON."""
    model = Verification.model_validate(body)
    return {"detail": model.model_dump(mode="json"), "related": [], "fetched_at": "x"}


def _item(body: dict) -> LibraryItem:
    return LibraryItem.model_validate(body)


def test_fixtures_have_the_current_shape():
    fx = _fx()
    assert "completed_at" in fx["detail"] and "modified_at" not in fx["detail"]
    assert "completed_at" in fx["library_item"]
    assert "modified_at" not in fx["library_item"]


def test_check_parses():
    check = content._parse_check(_cached_doc(_fx()["detail"]))
    assert check is not None
    assert check.claim == "The Earth is round."
    assert check.verdict_key == "True"
    assert check.key_finding == "The Earth is approximately spherical in shape."
    assert [s.source_name for s in check.sources] == ["NASA", "ESA"]
    # completed a day after it was created -> that is its change time
    assert check.modified_at == "2026-09-02T09:30:00.123456+00:00"


def test_list_item_key_is_the_change_time():
    assert (
        fetch._change_key(_item(_fx()["library_item"]))
        == "2026-09-02T09:30:00.123456+00:00"
    )


def test_same_day_item_has_an_empty_key():
    """A claim completed on the day it was created has no change time."""
    assert fetch._change_key(_item(_fx()["same_day_library_item"])) == ""


class _Bare:
    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


def test_change_key_needs_both_times():
    later = _Bare(
        created_at="2026-09-01T23:00:00+00:00", completed_at="2026-09-02T00:01:00Z"
    )
    assert fetch._change_key(later) == "2026-09-02T00:01:00Z"
    assert fetch._change_key(_Bare()) == ""
    assert fetch._change_key(_Bare(completed_at="2026-09-02T09:30:00+00:00")) == ""


def test_the_deprecated_modified_at_is_not_read():
    """The SDK still offers ``modified_at`` as a 2.x alias; the site takes the
    change time from ``completed_at`` only."""
    assert fetch._change_key(_Bare(modified_at="2030-01-01T00:00:00Z")) == ""
    doc = _cached_doc(_fx()["detail"] | {"completed_at": "2026-09-01T10:00:00+00:00"})
    doc["detail"]["modified_at"] = "2030-01-01T00:00:00Z"
    check = content._parse_check(doc)
    assert check is not None
    assert check.modified_at == ""


# The boundary cases the API's own contract fixtures use: minutes apart across
# midnight (UTC) -> set; hours apart on one day -> not set.
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
def test_change_time_is_judged_on_the_utc_day(name):
    created, completed, expected = _PAIRS[name]
    detail = _fx()["detail"] | {"created_at": created, "completed_at": completed}
    check = content._parse_check(_cached_doc(detail))
    assert check is not None
    assert check.modified_at == expected
    item = _fx()["library_item"] | {"created_at": created, "completed_at": completed}
    assert fetch._change_key(_item(item)) == expected


def test_unparseable_times_give_no_change_time():
    assert fetch._change_key(_item({"created_at": "x", "completed_at": "y"})) == ""
    assert (
        fetch._change_key(
            _item({"created_at": None, "completed_at": "2026-03-15T00:00:00+00:00"})
        )
        == ""
    )


class _Resp:
    def __init__(self, body: dict, headers: dict | None = None) -> None:
        self._raw = json.dumps(body).encode()
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self._raw


def _serve(monkeypatch, body: dict, headers: dict | None = None) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(body, headers))


def test_live_fetch_serves_a_completed_check(monkeypatch):
    _serve(monkeypatch, _fx()["detail"], {API_VERSION_HEADER: API_VERSION})
    detail = live_core.fetch_detail("a1b2c3d4")
    assert detail is not None
    assert detail["verdict"] == "True"
    assert detail["key_finding"].startswith("The Earth")
    assert len(detail["sources"]) == 2


def test_live_fetch_refuses_a_reply_in_another_version(monkeypatch):
    _serve(monkeypatch, _fx()["detail"], {API_VERSION_HEADER: "2026-05-13"})
    assert live_core.fetch_detail("a1b2c3d4") is None


def test_live_fetch_without_a_verdict_is_no_result(monkeypatch):
    _serve(monkeypatch, _fx()["detail"] | {"verdict": None, "confidence": None})
    assert live_core.fetch_detail("a1b2c3d4") is None


def test_older_output_is_byte_identical_to_origin_main():
    """Frozen oracle: the pre-change code's outputs over the same claims
    (provenance inside the file). This tree, reading the current shape, must
    reproduce them exactly."""
    import oracle_run

    frozen = json.loads((_PATH.parent / "origin_main_oracle.json").read_text())
    assert frozen["provenance"]["origin_main_commit"]
    fresh = json.dumps(oracle_run.run(), indent=1, sort_keys=True, ensure_ascii=False)
    expected = json.dumps(
        frozen["outputs"], indent=1, sort_keys=True, ensure_ascii=False
    )
    assert fresh == expected


# --------------------------------------------------------------------------- #
# The version this site asks for
# --------------------------------------------------------------------------- #


def test_the_site_asks_for_the_version_the_sdk_asks_for():
    assert API_VERSION == "2026-10-11"
    assert lenz_io.API_VERSION == API_VERSION


@pytest.mark.skipif(
    not hasattr(lenz_io, "AsyncLenz"),
    reason="AsyncLenz ships in lenz-io 3.1",
)
def test_the_build_client_sends_that_version_and_its_own_agent():
    import build
    from isthisbs import __version__

    client = build._make_client()
    try:
        headers = client._client.headers
        assert headers[API_VERSION_HEADER] == API_VERSION
        assert headers["User-Agent"].startswith(f"isthisbs-media/{__version__}")
    finally:
        asyncio.run(client.aclose())


def test_the_live_function_sends_that_version(monkeypatch):
    seen = {}

    def fake_urlopen(req, *a, **k):
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _Resp(_fx()["detail"])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert live_core.fetch_detail("a1b2c3d4") is not None
    assert seen["headers"]["x-lenz-api-version"] == API_VERSION
    assert seen["headers"]["user-agent"] == "isthisbs-claimlive"


def test_a_catalog_refetches_nothing_over_a_cache_in_the_current_shape(tmp_path):
    """Cross-day and same-day claims keep the change keys the manifest holds,
    so a build over an existing cache fetches no detail."""
    fx = _fx()
    cross = fx["library_item"] | {"verification_id": "cross001"}
    same = fx["same_day_library_item"] | {"verification_id": "same0001"}
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    claims = tmp_path / "claims"
    claims.mkdir()
    manifest = {}
    for item in (cross, same):
        vid = item["verification_id"]
        (claims / f"{vid}.json").write_text(
            json.dumps(
                {
                    "detail": {"completed_at": item["completed_at"]},
                    "related": [],
                    "related_refreshed_at": now,
                }
            )
        )
        manifest[vid] = fetch._change_key(_item(item))
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert manifest["cross001"] and manifest["same0001"] == ""

    class _Library:
        async def list(self, page=1, sort="recent"):
            return LibraryList.model_validate(
                {"items": [cross, same], "total": 2, "page": 1, "page_size": 20}
            )

    class _Client:
        library = _Library()
        verifications = None  # any detail fetch would raise

    stats = asyncio.run(fetch.sync(_Client(), tmp_path))
    assert (stats.unchanged, stats.new, stats.updated, stats.errors) == (2, 0, 0, 0)
