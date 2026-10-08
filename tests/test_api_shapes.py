"""The build and the live function against both API response shapes.

This release still asks for (and gets) the older shape, where the change
time is ``modified_at``. Against that shape nothing differs from before.
A body in the newer shape (``completed_at``) must never crash the build or
the live function; this release does not yet use its new fields, so a
newer-shape claim carries no change time (exact parity is not claimed).

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


def test_canonical_check_never_crashes():
    check = content._parse_check(_cached_doc(_fx()["canonical"]["detail"]))
    assert check is not None
    assert check.claim == "The Earth is round."
    assert check.verdict_key == "True"
    assert [s.source_name for s in check.sources] == ["NASA", "ESA"]
    assert check.modified_at == ""  # this release does not read completed_at


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


def test_canonical_list_item_never_crashes():
    assert fetch._change_key(_item(_fx()["canonical"]["library_item"])) == ""


def test_completed_at_is_only_read_when_modified_at_is_absent():
    class Bare:
        completed_at = "2026-09-02T09:30:00+00:00"

    class Neither:
        pass

    assert fetch._change_key(Bare()) == "2026-09-02T09:30:00+00:00"
    assert fetch._change_key(Neither()) == ""


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
