"""
Notes locator: find pages/tables for note targets (Revenue, PPE, Borrowings, etc.).
LLM planner ranks candidates; deterministic validation and table selection.
Per FR-002; tasks T305, T306.
"""
from __future__ import annotations

import re
import logging
from typing import Any, Callable

from src.models.document import Document, DocumentPage
from src.models.phase3 import (
    NoteTableRef,
    NotesLocatorAttempt,
    NotesLocatorResult,
    NotesLocatorSelection,
    NotesMissingEntry,
    TargetSpec,
)

logger = logging.getLogger(__name__)


def _page_text(page: DocumentPage) -> str:
    return " ".join(b.text for b in page.text_blocks)


def _numeric_density(text: str) -> float:
    if not text:
        return 0.0
    tokens = text.split()
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if re.search(r"[0-9,.]", t)) / len(tokens)


def _anchor_hits(target: TargetSpec, text: str) -> int:
    lower = text.lower()
    hits = sum(1 for a in target.expected_anchors if a.lower() in lower)
    hits += sum(1 for s in target.synonyms if s.lower() in lower)
    return hits


def _is_toc_like(text: str) -> bool:
    if re.search(r"contents|table of contents", text, re.I):
        return True
    if re.search(r"\.{2,}\s*\d+", text):
        return True
    return False


def _get_note_table_refs(page: DocumentPage) -> list[NoteTableRef]:
    refs: list[NoteTableRef] = []
    for t in page.tables:
        rows = len(t.grid)
        cols = len(t.grid[0]) if t.grid else 0
        refs.append(
            NoteTableRef(
                table_id=t.table_id or "",
                rows=rows,
                cols=cols,
                caption=t.caption or "",
                page=page.page,
            )
        )
    return refs


def _score_note_page(target: TargetSpec, page: DocumentPage) -> tuple[float, str | None]:
    text = _page_text(page)
    density = _numeric_density(text)
    anchors = _anchor_hits(target, text)
    refs = _get_note_table_refs(page)
    best_cols = max((r.cols for r in refs), default=0)
    if refs and best_cols > 0 and best_cols < 2:
        return 0.0, "TABLE_TOO_FEW_COLUMNS"
    if _is_toc_like(text) and (anchors < 1 or density < 0.05):
        return 0.0, "TOC_FALSE_POSITIVE"
    score = min(0.3, density * 2) + min(0.4, anchors * 0.2) + min(0.3, best_cols * 0.1)
    return max(0.0, score), None


def _validate_note_page(target: TargetSpec, page: DocumentPage) -> tuple[bool, str | None]:
    refs = _get_note_table_refs(page)
    if target.content_type == "table" and not refs:
        return False, "NO_TABLES_FOUND"
    text = _page_text(page)
    density = _numeric_density(text)
    anchors = _anchor_hits(target, text)
    best_cols = max((r.cols for r in refs), default=0)
    if best_cols > 0 and best_cols < 2:
        return False, "TABLE_TOO_FEW_COLUMNS"
    if density < target.validation_min_density and anchors < 1:
        return False, "VALIDATION_FAILED"
    return True, None


def _pick_best_table_on_page(page: DocumentPage) -> tuple[list[list[Any]], str, int, int] | None:
    best = None
    best_cols = -1
    for t in page.tables:
        if not t.grid:
            continue
        cols = len(t.grid[0])
        if cols >= 2 and cols > best_cols:
            best_cols = cols
            best = (t.grid, t.table_id or "", len(t.grid), cols)
    return best


def _generate_note_candidates(document: Document, target: TargetSpec, max_pages: int = 50) -> list[int]:
    """Candidate page numbers: keyword scan + numeric density."""
    candidates: list[tuple[int, float]] = []
    for page in document.pages[:max_pages]:
        text = _page_text(page)
        if not text.strip():
            continue
        score, reject = _score_note_page(target, page)
        if reject:
            continue
        anchors = _anchor_hits(target, text)
        density = _numeric_density(text)
        if anchors >= 1 or density >= target.validation_min_density:
            candidates.append((page.page, score))
    candidates.sort(key=lambda x: -x[1])
    return [p for p, _ in candidates]


def locate_notes(
    document: Document,
    targets: list[TargetSpec],
    *,
    strategy: str = "llm",
    max_attempts: int = 6,
    rank_candidates_fn: Callable[[str, list[dict], Path | None], list[int]] | None = None,
    cache_dir: Path | None = None,
) -> NotesLocatorResult:
    """
    For each note target (table or mixed), locate best page and table.
    Interpretation targets (e.g. mdna) are skipped here.
    Returns NotesLocatorResult with selections and/or missing. No silent skips.
    """
    result = NotesLocatorResult(
        meta={"strategy": strategy, "max_attempts": max_attempts},
    )
    page_by_num = {p.page: p for p in document.pages}
    note_targets = [t for t in targets if t.content_type in ("table", "mixed") and t.topic != "mdna"]
    # Exclude governance from notes locator (handled by gov_sections)
    gov_topics = {"directors", "kmp", "shareholding", "corp_structure"}
    note_targets = [t for t in note_targets if (t.topic or "") not in gov_topics]

    for target in note_targets:
        candidates = _generate_note_candidates(document, target)
        candidates_set = set(candidates)
        if rank_candidates_fn and strategy == "llm":
            try:
                meta_list = []
                for pn in candidates[:30]:
                    if pn not in page_by_num:
                        continue
                    page = page_by_num[pn]
                    text = _page_text(page)
                    refs = _get_note_table_refs(page)
                    meta_list.append({
                        "page": pn,
                        "snippet": text[:500],
                        "numeric_density": _numeric_density(text),
                        "anchor_hits": _anchor_hits(target, text),
                        "table_shapes": [{"rows": r.rows, "cols": r.cols} for r in refs],
                    })
                if meta_list:
                    ranked = rank_candidates_fn(target.target_id, meta_list, cache_dir)
                    if ranked:
                        candidates = [p for p in ranked if p in candidates_set]
                        if not candidates:
                            candidates = list(candidates_set)[:max_attempts * 2]
            except Exception as e:
                logger.warning("Notes LLM rank fallback: %s", e)
                result.meta["llm_fallback"] = str(e)

        selected: NotesLocatorSelection | None = None
        for attempt_idx in range(max_attempts):
            if not candidates:
                break
            page_num = candidates.pop(0)
            if page_num not in page_by_num:
                continue
            page = page_by_num[page_num]
            refs = _get_note_table_refs(page)
            score, rejected = _score_note_page(target, page)
            result.attempts.append(
                NotesLocatorAttempt(
                    target_id=target.target_id,
                    page=page_num,
                    table_candidates=refs,
                    score=score,
                    rejected_reason=rejected,
                )
            )
            if rejected:
                continue
            valid, fail_reason = _validate_note_page(target, page)
            if not valid:
                result.attempts[-1].rejected_reason = fail_reason
                continue
            picked = _pick_best_table_on_page(page)
            if picked:
                grid, table_id, rows, cols = picked
                selected = NotesLocatorSelection(
                    target_id=target.target_id,
                    sheet_name=target.sheet_name,
                    selected_page_start=page_num,
                    selected_page_end=page_num,
                    selected_table_id=table_id,
                    confidence="High" if (cols >= 3 and _anchor_hits(target, _page_text(page)) >= 1) else "Med",
                    col_count=cols,
                    row_count=rows,
                )
                break

        if selected is not None:
            result.selections[target.target_id] = selected
        else:
            result.missing.append(
                NotesMissingEntry(
                    field=target.sheet_name,
                    searched_in=f"pages {sorted(candidates_set)[:20]}" if candidates_set else "none",
                    reason="NO_VALID_CANDIDATE",
                )
            )

    return result
