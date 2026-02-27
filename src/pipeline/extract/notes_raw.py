"""
Extract note tables and nearby narrative from document using notes locator result.
Deterministic: copy tables and text blocks as-is. Per FR-003; task T307.
"""
from __future__ import annotations

import logging
from typing import Any

from src.models.document import Document
from src.models.phase3 import (
    ExtractedSnippet,
    NoteExtractEntry,
    NotesLocatorResult,
    NotesLocatorSelection,
    NotesRawResult,
)

logger = logging.getLogger(__name__)


def _get_grid(document: Document, page_num: int, table_id: str) -> list[list[Any]] | None:
    for page in document.pages:
        if page.page != page_num:
            continue
        for t in page.tables:
            if (t.table_id or "") == table_id and t.grid:
                return t.grid
    return None


def _get_nearby_narrative(
    document: Document,
    page_num: int,
    table_id: str,
    num_blocks: int = 5,
) -> list[ExtractedSnippet]:
    """Extract text blocks from same page (before/after table) for footnote narrative."""
    snippets: list[ExtractedSnippet] = []
    for page in document.pages:
        if page.page != page_num:
            continue
        blocks = page.text_blocks
        for i, b in enumerate(blocks):
            if not (b.text or "").strip():
                continue
            sid = b.block_id or f"p{page_num}_b{i}"
            snippets.append(
                ExtractedSnippet(
                    snippet_id=sid,
                    page_ref=f"p.{page_num}",
                    text=(b.text or "").strip()[:2000],
                    block_id=b.block_id or "",
                )
            )
        # Limit to first N blocks on page if many
        if len(snippets) > num_blocks * 2:
            snippets = snippets[:num_blocks * 2]
        break
    return snippets


def extract_notes(
    document: Document,
    notes_locator_result: NotesLocatorResult,
    *,
    include_narrative: bool = True,
) -> NotesRawResult:
    """
    From NotesLocatorResult selections, extract table grids and optional narrative snippets.
    Returns NotesRawResult. Missing entries come from locator missing list.
    """
    entries: list[NoteExtractEntry] = []
    missing = [m.model_dump() for m in notes_locator_result.missing]

    for target_id, sel in notes_locator_result.selections.items():
        if sel is None:
            continue
        assert isinstance(sel, NotesLocatorSelection)
        page_ref = f"p.{sel.selected_page_start}"
        if sel.selected_page_start != sel.selected_page_end:
            page_ref = f"p.{sel.selected_page_start}-{sel.selected_page_end}"
        grid = _get_grid(document, sel.selected_page_start, sel.selected_table_id or "")
        if not grid:
            missing.append({
                "field": sel.sheet_name,
                "searched_in": page_ref,
                "reason": "NO_TABLES_FOUND",
            })
            continue
        narrative = (
            _get_nearby_narrative(document, sel.selected_page_start, sel.selected_table_id or "", num_blocks=5)
            if include_narrative
            else []
        )
        entries.append(
            NoteExtractEntry(
                target_id=target_id,
                sheet_name=sel.sheet_name,
                page_ref=page_ref,
                table_id=sel.selected_table_id or "",
                grid=grid,
                narrative_snippets=narrative,
                confidence=sel.confidence,
            )
        )

    return NotesRawResult(
        module="notes_raw",
        version="1.0",
        entries=entries,
        missing=missing,
    )
