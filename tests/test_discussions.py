"""Tests for the GitHub-Discussions count layer (option-1 plumbing).

The module bakes reaction/comment counts into the static build: CI fetches
them via GraphQL with the Actions token; locally (no token) the build falls
back to whatever ``discussions.json`` is already cached — or empty, which
renders every article in its zero state (the verdict-challenge prompt).
"""

from __future__ import annotations

import json

from isthisbs import discussions


def _node(title: str, up: int = 0, down: int = 0, comments: int = 0) -> dict:
    return {
        "title": title,
        "url": "https://github.com/lenzhq/demo-media/discussions/1",
        "comments": {"totalCount": comments},
        "reactionGroups": [
            {"content": "THUMBS_UP", "reactors": {"totalCount": up}},
            {"content": "THUMBS_DOWN", "reactors": {"totalCount": down}},
            {"content": "ROCKET", "reactors": {"totalCount": 7}},  # ignored
        ],
    }


def test_vid_extracted_from_title_suffix():
    assert (
        discussions._vid_from_title("Sharks don't get cancer [abc12345]") == "abc12345"
    )
    assert discussions._vid_from_title("No suffix here") is None
    assert discussions._vid_from_title("Weird [not/a/vid]") is None
    # Case: the whole title is just the bracketed id.
    assert discussions._vid_from_title("[deadbeef]") == "deadbeef"


def test_nodes_transform_to_count_map():
    nodes = [
        _node("Claim one [aaaa1111]", up=3, down=1, comments=2),
        _node("Claim two [bbbb2222]"),  # all zero — still mapped (URL is useful)
        _node("Untagged discussion about the site"),  # no vid -> skipped
    ]
    m = discussions._to_map(nodes)
    assert m["aaaa1111"] == {
        "url": "https://github.com/lenzhq/demo-media/discussions/1",
        "up": 3,
        "down": 1,
        "comments": 2,
    }
    assert m["bbbb2222"]["up"] == 0
    assert "Untagged discussion about the site" not in m
    assert len(m) == 2


def test_sync_without_token_keeps_existing_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    existing = {"aaaa1111": {"url": "u", "up": 1, "down": 0, "comments": 0}}
    (tmp_path / "discussions.json").write_text(json.dumps(existing))

    discussions.sync(tmp_path)  # no token -> no network, no overwrite
    assert discussions.load(tmp_path) == existing


def test_load_missing_or_corrupt_is_empty(tmp_path):
    assert discussions.load(tmp_path) == {}
    (tmp_path / "discussions.json").write_text("{not json")
    assert discussions.load(tmp_path) == {}
