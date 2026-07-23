"""Shared fixtures for the offline IsThisBS test suite.

Everything here is network-free: cached-claim dicts are synthesised in-memory,
written to temp cache dirs, and fed through the real ``content`` / ``fetch`` /
``render`` / ``seo`` / ``ogimage`` code exactly as a live build would.
"""

from __future__ import annotations

import itertools
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# Ensure the repo root is importable so ``build`` (build.py, not part of the
# installed package) resolves alongside the ``isthisbs`` package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from isthisbs import content  # noqa: E402

_ID_COUNTER = itertools.count(1)


def _next_id() -> str:
    """A deterministic, unique 8-char-ish verification id."""
    return f"vid{next(_ID_COUNTER):05d}"


_DEFAULT_SUMMARY = (
    "The evidence does not support this claim.\n\n"
    "Independent sources contradict the specific figure cited, and the "
    "original context has been stripped away."
)


def _build_detail(
    *,
    verification_id: str,
    claim: str,
    verdict: str,
    lenz_score: int | None,
    executive_summary: str,
    created_at: str,
    modified_at: str,
    language: str,
    domain: str | None,
    entities: list[dict[str, Any]] | None,
    warnings: list[str] | None,
    sources: list[dict[str, Any]] | None,
    panel_agreement: str,
    presumed_intent: str,
) -> dict[str, Any]:
    """Assemble a detail dict mirroring the SDK ``Verification`` shape."""
    return {
        "verification_id": verification_id,
        "claim": claim,
        "verdict": verdict,
        "confidence": "high",
        "lenz_score": lenz_score,
        "executive_summary": executive_summary,
        "created_at": created_at,
        "modified_at": modified_at,
        "language": language,
        "domain": domain,
        "presumed_intent": presumed_intent,
        "entities": entities if entities is not None else [],
        "warnings": warnings if warnings is not None else [],
        "sources": sources if sources is not None else [],
        "audit": {
            # These internal fields MUST NOT leak into any rendered surface.
            "adjudication_summary": "Panel adjudication summary (internal).",
            "assessments": [
                {"model": "model-a", "verdict": verdict, "reasoning": "..."},
                {"model": "model-b", "verdict": verdict, "reasoning": "..."},
            ],
            "debate_pro": "Internal pro-side debate transcript.",
            "debate_con": "Internal con-side debate transcript.",
            "panel_agreement": panel_agreement,
        },
    }


@pytest.fixture
def make_detail() -> Callable[..., dict[str, Any]]:
    """Factory producing a realistic cached-doc dict.

    Returns ``{"detail": {...}, "related": [...], "fetched_at": iso}`` — exactly
    what ``fetch`` writes and ``content.build_checks`` reads. Every field has a
    sensible default and can be overridden per call.
    """

    def factory(
        *,
        verification_id: str | None = None,
        claim: str = "A widely shared statistic is off by a factor of ten.",
        verdict: str = "False",
        lenz_score: int | None = 2,
        executive_summary: str = _DEFAULT_SUMMARY,
        created_at: str = "2026-07-20T12:00:00Z",
        modified_at: str | None = None,
        language: str = "en",
        domain: str | None = "health",
        entities: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
        sources: list[dict[str, Any]] | None = None,
        panel_agreement: str = "unanimous",
        presumed_intent: str = "informational",
        related: list[dict[str, Any]] | None = None,
        fetched_at: str = "2026-07-21T00:00:00+00:00",
    ) -> dict[str, Any]:
        vid = verification_id or _next_id()
        if entities is None:
            entities = [
                {"name": "World Health Organization", "qid": "Q7817"},
                {"name": "Aspirin", "qid": ""},
            ]
        if warnings is None:
            warnings = ["The claim omits the study's small sample size."]
        if sources is None:
            sources = [
                {
                    "source_name": "Reuters",
                    "title": "Fact check: the real figure",
                    "url": "https://example.com/reuters",
                    "snippet": "The actual value is far lower.",
                    "date": "2026-07-10",
                },
                {
                    "source_name": "WHO",
                    "title": "Official guidance",
                    "url": "https://example.com/who",
                    "snippet": "Guidance document.",
                    "date": "2026-06-01",
                },
            ]
        detail = _build_detail(
            verification_id=vid,
            claim=claim,
            verdict=verdict,
            lenz_score=lenz_score,
            executive_summary=executive_summary,
            created_at=created_at,
            modified_at=modified_at if modified_at is not None else created_at,
            language=language,
            domain=domain,
            entities=entities,
            warnings=warnings,
            sources=sources,
            panel_agreement=panel_agreement,
            presumed_intent=presumed_intent,
        )
        if related is None:
            related = [
                {
                    "verification_id": f"{vid}-rel",
                    "claim": "A related claim on the same topic.",
                    "verdict": "Mostly False",
                }
            ]
        return {"detail": detail, "related": related, "fetched_at": fetched_at}

    return factory


@pytest.fixture
def sample_docs(make_detail) -> list[dict[str, Any]]:
    """A diverse set of raw cached docs spanning every rendered verdict,
    panel state, entity shape, and a couple of edge cases (unicode, long
    claim, missing optionals, an Error doc, a non-English doc)."""
    docs = [
        make_detail(
            claim="Drinking eight glasses of water a day is medically required.",
            verdict="False",
            domain="health",
            lenz_score=2,
            panel_agreement="split",
            created_at="2026-07-22T09:00:00Z",
            entities=[{"name": "Hydration", "qid": "Q188486"}],
        ),
        make_detail(
            claim="The Great Wall of China is visible from space with the naked eye.",
            verdict="Mostly False",
            domain="history",
            lenz_score=3,
            panel_agreement="majority",
            created_at="2026-07-21T09:00:00Z",
            entities=[{"name": "Great Wall of China", "qid": "Q12501"}],
        ),
        make_detail(
            claim="A mixed-evidence claim with arguments on both sides.",
            verdict="Mixed",
            domain="science",
            lenz_score=5,
            created_at="2026-07-20T09:00:00Z",
            entities=[{"name": "Climate", "qid": ""}],
            warnings=[],
        ),
        make_detail(
            claim="Regular exercise is associated with lower cardiovascular risk.",
            verdict="Mostly True",
            domain="health",
            lenz_score=8,
            created_at="2026-07-19T09:00:00Z",
            entities=[{"name": "World Health Organization", "qid": "Q7817"}],
        ),
        make_detail(
            claim="Water boils at 100 degrees Celsius at sea level.",
            verdict="True",
            domain="science",
            lenz_score=10,
            created_at="2026-07-18T09:00:00Z",
            entities=[{"name": "Water", "qid": "Q283"}],
        ),
        # Unicode + very long claim, missing lenz_score, no entities/sources.
        make_detail(
            claim=(
                "Café owners in São Paulo claim that a 350‑year‑old "
                "recipe — passed down through générations — cures the common "
                "cold, boosts “immunity”, and outperforms every "
                "modern pharmaceutical on the market today, which is a very "
                "long and unwieldy assertion indeed."
            ),
            verdict="False",
            domain="finance",
            lenz_score=None,
            created_at="2026-07-17T09:00:00Z",
            entities=[],
            sources=[],
            warnings=[],
        ),
        # Error verdict — must be filtered out entirely.
        make_detail(
            claim="A claim the engine could not resolve.",
            verdict="Error",
            domain="general",
            created_at="2026-07-16T09:00:00Z",
        ),
        # Non-English — filtered out by the LANGS gate.
        make_detail(
            claim="La Tierra es plana según algunos.",
            verdict="False",
            domain="science",
            language="es",
            created_at="2026-07-15T09:00:00Z",
        ),
    ]
    return docs


@pytest.fixture
def checks(sample_docs) -> list[content.Check]:
    """The diverse doc set parsed through the real build pipeline."""
    return content.build_checks(sample_docs)


@pytest.fixture
def write_cache() -> Callable[[Path, list[dict[str, Any]]], Path]:
    """Write raw docs into a temp cache dir (``claims/*.json`` + manifest)."""

    def _writer(cache_dir: Path, docs: list[dict[str, Any]]) -> Path:
        cache_dir = Path(cache_dir)
        claims_dir = cache_dir / "claims"
        claims_dir.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, str] = {}
        for doc in docs:
            vid = doc["detail"]["verification_id"]
            path = claims_dir / f"{vid}.json"
            path.write_text(
                json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            manifest[vid] = doc["detail"].get("modified_at") or ""
        (cache_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return cache_dir

    return _writer
