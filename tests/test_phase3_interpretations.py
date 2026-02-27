"""Interpretation engine tests. Reviewer stubbed; evidence refs enforced."""
from __future__ import annotations

import pytest

from src.models.phase3 import ExtractedSnippet, InterpretationResult, MDNAInterpretation, InterpretationBullet
from src.pipeline.interpret.interpretations import generate_interpretations


def test_interpretations_reject_bullets_without_evidence():
    blocks = [
        {"snippet_id": "p5_b1", "page_ref": "p.5", "text": "Revenue increased due to volume."},
    ]
    # Stub that returns bullets without refs
    def stub_no_refs(kind: str, blks: list, cache):
        return {
            "revenue_drivers": [{"text": "Volume growth", "page_ref": "", "snippet_id": ""}],
            "margin_drivers": [],
            "kpis": [],
            "outlook": [],
            "risks": [],
        }

    result = generate_interpretations(
        [ExtractedSnippet(snippet_id="p5_b1", page_ref="p.5", text="Revenue increased.")],
        mode="mdna_only",
        reviewer_fn=stub_no_refs,
    )
    assert result.mdna is not None
    # Bullets without page_ref/snippet_id must be stripped
    assert len(result.mdna.revenue_drivers) == 0


def test_interpretations_keep_bullets_with_evidence():
    def stub_with_refs(kind: str, blks: list, cache):
        return {
            "revenue_drivers": [{"text": "Volume growth", "page_ref": "p.5", "snippet_id": "p5_b1"}],
            "margin_drivers": [],
            "kpis": [],
            "outlook": [],
            "risks": [],
        }

    result = generate_interpretations(
        [ExtractedSnippet(snippet_id="p5_b1", page_ref="p.5", text="Revenue increased.")],
        mode="mdna_only",
        reviewer_fn=stub_with_refs,
    )
    assert result.mdna is not None
    assert len(result.mdna.revenue_drivers) == 1
    assert result.mdna.revenue_drivers[0].page_ref == "p.5"
    assert result.mdna.revenue_drivers[0].snippet_id == "p5_b1"


def test_interpretations_empty_without_reviewer():
    result = generate_interpretations(
        [ExtractedSnippet(snippet_id="p1_b0", page_ref="p.1", text="Text")],
        reviewer_fn=None,
    )
    assert result.mdna is None or (result.mdna and not result.mdna.revenue_drivers)
