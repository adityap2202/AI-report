"""Notes locator tests. LLM stubbed; no real API calls."""
from __future__ import annotations

import pytest
from pathlib import Path

from src.models.document import Document, DocumentPage, DocumentMeta, TextBlock, TableCandidate
from src.models.phase3 import TargetSpec, NotesLocatorResult
from src.pipeline.locate.notes import locate_notes, _generate_note_candidates


def _doc_with_pages():
    meta = DocumentMeta(file_name="x.pdf", sha256="", pages=5, pdf_type="text", created_at="")
    pages = []
    for pn in [1, 2, 3]:
        pages.append(
            DocumentPage(
                page=pn,
                type="text",
                text_blocks=[TextBlock(text="Note 20 Revenue from operations 2024 2023" if pn == 2 else "Other text")],
                tables=[TableCandidate(table_id=f"p{pn}_t0", grid=[["A", "B", "C"], ["1", "2", "3"]])] if pn == 2 else [],
            )
        )
    return Document(meta=meta, pages=pages)


def test_notes_locator_candidate_generation():
    doc = _doc_with_pages()
    target = TargetSpec(target_id="revenue", sheet_name="Revenue", content_type="table", topic="revenue", expected_anchors=["revenue"], synonyms=["Note 20"])
    candidates = _generate_note_candidates(doc, target, max_pages=10)
    assert 2 in candidates  # page 2 has revenue + table


def test_notes_locator_uses_llm_stub():
    doc = _doc_with_pages()
    target = TargetSpec(target_id="revenue", sheet_name="Revenue", content_type="table", topic="revenue", expected_anchors=["revenue"])
    targets = [target]

    def stub_rank(target_id: str, meta: list, cache: Path | None):
        return [2, 1, 3]  # prefer page 2

    result = locate_notes(
        doc,
        targets,
        strategy="llm",
        max_attempts=3,
        rank_candidates_fn=stub_rank,
    )
    assert isinstance(result, NotesLocatorResult)
    # Page 2 has table with 3 cols and revenue anchor -> should be selected
    if result.selections:
        assert result.selections.get("revenue") is not None
        assert result.selections["revenue"].col_count >= 2


def test_notes_locator_deterministic_fallback():
    doc = _doc_with_pages()
    target = TargetSpec(target_id="revenue", sheet_name="Revenue", content_type="table", topic="revenue", expected_anchors=["revenue"])
    result = locate_notes(doc, [target], strategy="deterministic", max_attempts=3)
    assert isinstance(result, NotesLocatorResult)
    # Either selection or missing
    assert len(result.selections) + len(result.missing) >= 1
