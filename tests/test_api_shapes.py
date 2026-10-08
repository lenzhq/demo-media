"""The build and the live function read both API response shapes.

Fixtures in ``tests/fixtures/api_shapes.json`` hold the same verification and
library item in the older shape (``modified_at``) and the newer one
(``completed_at``), plus a failed item in each. Every field the site reads
must come out the same from either.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from functions import live_core
from isthisbs import content, fetch

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "api_shapes.json").read_text()
)
SHAPES = ("legacy", "canonical")


def _doc(shape: str) -> dict:
    return {"detail": FIXTURES[shape]["detail"], "related": [], "fetched_at": "x"}


def test_fixtures_differ_only_in_the_timestamp_name():
    legacy, canonical = FIXTURES["legacy"]["detail"], FIXTURES["canonical"]["detail"]
    assert "modified_at" in legacy and "completed_at" not in legacy
    assert "completed_at" in canonical and "modified_at" not in canonical


@pytest.mark.parametrize("shape", SHAPES)
def test_parse_check_reads_the_completion_time(shape):
    check = content._parse_check(_doc(shape))
    assert check is not None
    assert check.modified_at == "2026-09-02T09:30:00.123456+00:00"
    assert check.claim == "The Earth is round."
    assert check.verdict_key == "True"
    assert check.key_finding == "The Earth is approximately spherical in shape."
    assert [s.source_name for s in check.sources] == ["NASA", "ESA"]


def test_completed_at_wins_when_both_are_present():
    doc = _doc("legacy")
    doc["detail"]["completed_at"] = "2026-09-05T00:00:00Z"
    assert content._parse_check(doc).modified_at == "2026-09-05T00:00:00Z"


class _Item:
    def __init__(self, **kw):
        self.verification_id = "a1b2c3d4"
        self.__dict__.update(kw)


@pytest.mark.parametrize("shape", SHAPES)
def test_change_key_reads_either_list_item(shape):
    li = FIXTURES[shape]["library_item"]
    key = fetch._change_key(_Item(**{k: v for k, v in li.items() if k != "claim"}))
    assert key == "2026-09-02T09:30:00.123456+00:00"


def test_change_key_stays_modified_at_so_existing_caches_are_not_refetched():
    item = _Item(
        modified_at="2026-07-01T00:00:00Z", completed_at="2026-07-03T00:00:00Z"
    )
    assert fetch._change_key(item) == "2026-07-01T00:00:00Z"


def test_change_key_without_either_is_empty():
    assert fetch._change_key(_Item(modified_at=None)) == ""
    assert fetch._change_key(_Item()) == ""


@pytest.mark.parametrize("shape", SHAPES)
def test_live_fetch_serves_either_shape(shape, monkeypatch):
    body = json.dumps(FIXTURES[shape]["detail"]).encode()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return body

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    detail = live_core.fetch_detail("a1b2c3d4")
    assert detail is not None
    assert detail["verdict"] == "True"
    assert detail["key_finding"].startswith("The Earth")
    assert len(detail["sources"]) == 2


@pytest.mark.parametrize("failed", ["failed_legacy", "failed_canonical"])
def test_live_fetch_never_renders_a_failed_item(failed, monkeypatch):
    body = json.dumps({**FIXTURES[failed], "claim": "x", "key_finding": "y"}).encode()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return body

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert live_core.fetch_detail("a1b2c3d4") is None


@pytest.mark.parametrize(
    "extra", [{"verdict": None}, {"verdict": "Error"}, {"verdict": ["True"]}]
)
def test_live_fetch_rejects_null_error_and_odd_verdicts(extra, monkeypatch):
    detail = {**FIXTURES["canonical"]["detail"], **extra}
    body = json.dumps(detail).encode()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return body

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert live_core.fetch_detail("a1b2c3d4") is None
