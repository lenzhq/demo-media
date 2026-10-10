"""Runs the oracle cases through this tree (the current response shape).

``tests/fixtures/origin_main_oracle.json`` holds what the pre-change code
produced for the same claims over the older response shape (provenance inside
the file), reduced to what does not depend on the shape. The test suite
compares this module's output with it byte for byte, so moving to the current
shape changed nothing the site renders or stores as a change key.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "api_shapes.json"


def _cases() -> dict:
    fx = json.loads(FIXTURES.read_text())
    detail = fx["detail"]
    item = fx["library_item"]
    # completed the same UTC day it was created: no change time
    same_day_detail = copy.deepcopy(detail) | {
        "completed_at": "2026-09-01T17:30:00.123456+00:00"
    }
    same_day_item = fx["same_day_library_item"]
    many = copy.deepcopy(detail)
    many["sources"] = [
        {
            "source_name": f"Outlet {i}",
            "title": f"Report {i} <b>",
            "url": f"https://example.com/{i}",
            "snippet": "s",
            "date": f"2025-01-0{i % 9 + 1}",
        }
        for i in range(9)
    ]
    return {
        "details": {
            "completed_later_day": detail,
            "same_day": same_day_detail,
            "many_sources": many,
        },
        "items": {
            "completed_later_day": item,
            "same_day": same_day_item,
        },
        "live_bodies": {
            "valid": detail,
            "same_day": same_day_detail,
            "many_sources": many,
            "no_verdict": detail | {"verdict": None, "confidence": None},
            "no_key_finding": {k: v for k, v in detail.items() if k != "key_finding"},
            "blank_key_finding": detail | {"key_finding": "   "},
            "unknown_verdict": detail | {"verdict": "Maybe"},
            "no_claim": detail | {"claim": ""},
            "empty_object": {},
            "html_in_strings": detail
            | {"claim": '<script>x</script> & "q"', "key_finding": " <i>f</i> "},
        },
    }


def _ser(obj) -> object:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _ser(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _ser(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_ser(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


class _Resp:
    def __init__(self, body) -> None:
        self._raw = json.dumps(body).encode()
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self._raw


class _List:
    def __init__(self, items):
        self.items = items
        self.total = len(items)
        self.page_size = 20


def run() -> dict:
    from lenz_io.models import LibraryItem, Verification

    from functions import live_core
    from isthisbs import content, fetch

    cases = _cases()
    out: dict = {}

    # parse + filter + floor + sort over each cached detail
    out["parse_check"] = {}
    for name, body in cases["details"].items():
        model = Verification.model_validate(body)
        doc = {
            "detail": model.model_dump(mode="json"),
            "related": [],
            "fetched_at": "x",
        }
        out["parse_check"][name] = _ser(content._parse_check(doc))
        out["parse_check"][name + ":build_checks"] = _ser(content.build_checks([doc]))

    # fetch.sync over the list items: manifest, stats and stored details
    class _Lib:
        def __init__(self, items):
            self._items = items

        async def list(self, page=1, sort="recent"):
            return _List(self._items if page == 1 else [])

    class _Ver:
        async def get(self, vid):
            body = cases["details"]["completed_later_day"] | {"verification_id": vid}
            return Verification.model_validate(body)

        async def related(self, vid, limit=5):
            return _List([])

    class _Client:
        def __init__(self, items):
            self.library = _Lib(items)
            self.verifications = _Ver()

    items = [
        LibraryItem.model_validate(body | {"verification_id": f"item{i}name"})
        for i, body in enumerate(cases["items"].values())
    ]
    with tempfile.TemporaryDirectory() as tmp:
        stats = asyncio.run(fetch.sync(_Client(items), Path(tmp)))
        manifest = json.loads((Path(tmp) / "manifest.json").read_text())
        # second pass against the same cache: what is refetched?
        stats2 = asyncio.run(fetch.sync(_Client(items), Path(tmp)))
    out["sync"] = {
        "first": _ser(stats),
        "second": _ser(stats2),
        "manifest": manifest,
    }

    # live function: what fetch_detail returns and the HTML built from it
    out["live"] = {}
    real = urllib.request.urlopen
    try:
        for name, body in cases["live_bodies"].items():
            urllib.request.urlopen = lambda *a, _b=body, **k: _Resp(_b)
            got = live_core.fetch_detail("a1b2c3d4")
            entry = {"served": got is not None}
            if got is not None:
                entry["html"] = live_core.build_live_html(got)
            out["live"][name] = entry
    finally:
        urllib.request.urlopen = real
    return out


if __name__ == "__main__":
    json.dump(run(), sys.stdout, indent=1, sort_keys=True, ensure_ascii=False)
