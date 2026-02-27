"""
Statement locator: find correct BS/IS/CF pages and table (or OCR grid) before extraction.
Deterministic core + optional LLM ranking. Never trusts index_map alone.
"""
from __future__ import annotations

import re
import logging
from typing import Any, Callable

from src.models.document import Document, DocumentPage
from src.models.index_map import IndexMap, StatementRef
from src.models.locator import (
    LocatorAttempt,
    LocatorResult,
    LocatorSelection,
    MissingEntry,
    TableCandidateRef,
)
from src.pipeline.locate.ocr_rows import reconstruct_ocr_rows

logger = logging.getLogger(__name__)

STATEMENT_TYPES = ("BS", "IS", "CF")
SHEET_BY_TYPE = {"BS": "CF BS", "IS": "CF IS", "CF": "CF CFS"}

# Caption synonyms per statement type
CAPTION_KEYWORDS: dict[str, list[str]] = {
    "BS": ["balance sheet", "statement of financial position"],
    "IS": ["statement of profit", "income statement", "profit & loss", "profit and loss"],
    "CF": ["cash flow statement", "statement of cash flows"],
}

# Anchors (presence boosts score)
ANCHORS: dict[str, list[str]] = {
    "BS": ["total assets", "equity and liabilities", "share capital", "non-current assets", "non current assets"],
    "IS": ["revenue", "total income", "profit for the year", "profit after tax"],
    "CF": ["net cash from operating", "cash and cash equivalents", "cash flow from"],
}

YEAR_HEADER_PATTERN = re.compile(
    r"FY\s*\d{4}|20\d{2}[-/]\d{2}|as\s+at\s+march\s+31|year\s+ended",
    re.I
)

# TOC indicators
TOC_PATTERNS = [
    re.compile(r"\.{2,}\s*\d+\s*$", re.M),  # ..... 5
    re.compile(r"contents|table of contents", re.I),
    re.compile(r"^\s*\d+\s*$", re.M),  # line of just page number
]


def _snippet(text: str, max_len: int = 400) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t[:max_len] if len(t) > max_len else t


def _numeric_density(text: str) -> float:
    if not text:
        return 0.0
    tokens = text.split()
    if not tokens:
        return 0.0
    numeric = sum(1 for t in tokens if re.search(r"[0-9,.]", t) or t in ("₹", "Crores", "Lakhs"))
    return numeric / len(tokens)


def _anchor_hits(statement_type: str, text: str) -> int:
    lower = text.lower()
    return sum(1 for a in ANCHORS.get(statement_type, []) if a in lower)


def _year_header_hits(text: str) -> int:
    return len(YEAR_HEADER_PATTERN.findall(text))


def is_toc_like(page: DocumentPage) -> tuple[bool, float]:
    """Return (is_toc, toc_score 0..1)."""
    text = " ".join(b.text for b in page.text_blocks)
    score = 0.0
    if re.search(r"contents|table of contents", text, re.I):
        score += 0.4
    if re.search(r"\.{2,}\s*\d+", text):
        score += 0.3
    lines = text.splitlines()
    if len(lines) > 5:
        only_digit_lines = sum(1 for L in lines if re.match(r"^\s*\d+\s*$", L.strip()))
        if only_digit_lines / len(lines) > 0.2:
            score += 0.3
    density = _numeric_density(text)
    if density < 0.05:
        score += 0.2
    return score >= 0.5, min(1.0, score)


def get_page_text(page: DocumentPage) -> str:
    """Page text from text_blocks and table grids (so scoring works when Marker leaves text_blocks empty)."""
    parts = [b.text for b in page.text_blocks]
    for t in page.tables:
        if t.grid:
            for row in t.grid:
                for cell in row:
                    if isinstance(cell, str) and cell.strip():
                        parts.append(cell.strip())
    return " ".join(parts)


def _score_candidate(
    statement_type: str,
    page: DocumentPage,
    table_candidates: list[TableCandidateRef],
    *,
    use_llm_ranking: bool = False,
) -> tuple[float, str | None]:
    """
    Score a candidate page. Return (score, rejected_reason).
    When use_llm_ranking: allow 2-col tables (LLM will rank). Otherwise reject if best cols < 3.
    """
    text = get_page_text(page)
    is_toc, toc_score = is_toc_like(page)
    density = _numeric_density(text)
    anchor_hits = _anchor_hits(statement_type, text)
    year_hits = _year_header_hits(text)
    best_cols = max((t.cols for t in table_candidates), default=0)
    best_rows = max((t.rows for t in table_candidates), default=0)
    min_cols = 2 if use_llm_ranking else 3
    if table_candidates and best_cols > 0 and best_cols < min_cols:
        return 0.0, "TABLE_TOO_FEW_COLUMNS"
    if is_toc and (anchor_hits < 2 or density < 0.08):
        return 0.0, "TOC_FALSE_POSITIVE"
    score = 0.0
    score += min(0.3, density * 2)  # numeric density cap
    score += min(0.3, anchor_hits * 0.15)
    score += min(0.2, year_hits * 0.2)
    score += min(0.3, best_cols * 0.08)  # prefer 4-col
    score += min(0.1, best_rows * 0.005)
    score -= toc_score * 0.4
    return max(0.0, score), None


def _validate_candidate(
    statement_type: str,
    page: DocumentPage,
    table_candidates: list[TableCandidateRef],
    density_threshold: float = 0.05,
    *,
    use_llm_ranking: bool = False,
) -> tuple[bool, str | None]:
    """
    When use_llm_ranking: accept any page with a table (2+ cols) that is not obvious TOC.
    Otherwise: at least 2 of (year hit, anchor>=2, density>=threshold, best_table_cols>=3).
    """
    text = get_page_text(page)
    density = _numeric_density(text)
    anchor_hits = _anchor_hits(statement_type, text)
    year_hits = _year_header_hits(text)
    best_cols = max((t.cols for t in table_candidates), default=0)
    is_toc, toc_score = is_toc_like(page)
    if use_llm_ranking:
        # Low threshold: trust LLM to rank. Reject only obvious TOC or no usable table.
        if best_cols < 2:
            return False, "NO_VALID_CANDIDATE"
        if is_toc and density < 0.02:
            return False, "TOC_FALSE_POSITIVE"
        return True, None
    conditions = [
        year_hits >= 1,
        anchor_hits >= 2,
        density >= density_threshold,
        best_cols >= 3,
    ]
    if sum(conditions) < 2:
        return False, "NO_VALID_CANDIDATE"
    if best_cols > 0 and best_cols < 3:
        return False, "TABLE_TOO_FEW_COLUMNS"
    if is_toc and (anchor_hits < 2 or density < 0.08):
        return False, "TOC_FALSE_POSITIVE"
    return True, None


def _get_table_candidates_from_page(page: DocumentPage) -> list[TableCandidateRef]:
    refs: list[TableCandidateRef] = []
    for t in page.tables:
        rows = len(t.grid)
        cols = len(t.grid[0]) if t.grid else 0
        refs.append(TableCandidateRef(table_id=t.table_id or "", rows=rows, cols=cols, caption=t.caption or ""))
    return refs


def _pick_best_table_on_page(
    page: DocumentPage,
    min_cols: int = 3,
) -> tuple[list[list[Any]], str, int, int] | None:
    """Pick table with highest column count (>= min_cols). Return (grid, table_id, rows, cols) or None."""
    best = None
    best_cols = -1
    for t in page.tables:
        if not t.grid:
            continue
        cols = len(t.grid[0])
        if cols >= min_cols and cols > best_cols:
            best_cols = cols
            best = (t.grid, t.table_id or "", len(t.grid), cols)
    return best


def _generate_candidates(
    document: Document,
    index_map: IndexMap,
    statement_type: str,
    scope: str,
    max_candidates: int = 30,
) -> list[int]:
    """Generate candidate page numbers: index_map seed + keyword scan + numeric density."""
    candidates_set: set[int] = set()
    # Seed 1: index_map
    for s in index_map.statements:
        if s.type != statement_type:
            continue
        if scope != "both" and s.scope != scope:
            continue
        if s.page_start and s.page_start >= 1:
            for p in range(s.page_start, min(s.page_end or s.page_start, s.page_start + 5) + 1):
                if 1 <= p <= document.meta.pages:
                    candidates_set.add(p)
    # Seed 2: keyword scan
    keywords = CAPTION_KEYWORDS.get(statement_type, [])
    for doc_page in document.pages:
        text = get_page_text(doc_page).lower()
        if any(kw in text for kw in keywords):
            candidates_set.add(doc_page.page)
    # Seed 3: numeric density (top pages)
    page_densities: list[tuple[int, float]] = []
    for doc_page in document.pages:
        d = _numeric_density(get_page_text(doc_page))
        page_densities.append((doc_page.page, d))
    page_densities.sort(key=lambda x: -x[1])
    for p, _ in page_densities[:15]:
        candidates_set.add(p)
    out = sorted(candidates_set)
    return out[:max_candidates]


def locate_statements(
    document: Document,
    index_map: IndexMap,
    scope: str = "both",
    strategy: str = "deterministic",
    max_attempts: int = 8,
    rank_candidates_fn: Callable[[str, list[dict], dict], list[int]] | None = None,
) -> LocatorResult:
    """
    Locate BS, IS, CF: candidate generation -> optional LLM rank -> validate -> table or OCR.
    Returns LocatorResult with selections and/or missing. Never returns silent empty.
    """
    result = LocatorResult(
        meta={"strategy": strategy, "max_attempts": max_attempts},
    )
    page_by_num = {p.page: p for p in document.pages}

    for statement_type in STATEMENT_TYPES:
        sheet_name = SHEET_BY_TYPE[statement_type]
        candidates = _generate_candidates(document, index_map, statement_type, scope)
        candidates_set = set(candidates)
        if rank_candidates_fn and strategy == "llm":
            try:
                # Only send sensible candidates: pages with at least one table (2+ cols, 3+ rows)
                sensible_pages = set()
                for pn in candidates:
                    if pn not in page_by_num:
                        continue
                    page = page_by_num[pn]
                    for t in page.tables:
                        if t.grid and len(t.grid[0]) >= 2 and len(t.grid) >= 3:
                            sensible_pages.add(pn)
                            break
                list_for_llm = [pn for pn in candidates if pn in sensible_pages][:50]
                if not list_for_llm:
                    list_for_llm = candidates[:50]

                candidate_meta = []
                for pn in list_for_llm:
                    if pn not in page_by_num:
                        continue
                    page = page_by_num[pn]
                    text = get_page_text(page)
                    is_toc, toc_score = is_toc_like(page)
                    table_refs = _get_table_candidates_from_page(page)
                    shapes = [{"rows": t.rows, "cols": t.cols} for t in table_refs]
                    largest = max((t.rows * t.cols for t in table_refs), default=0)
                    header_row: list[str] = []
                    for t in page.tables:
                        if not t.grid or len(t.grid[0]) < 2:
                            continue
                        if len(t.grid) * len(t.grid[0]) == largest:
                            header_row = [str(c) for c in t.grid[0]]
                            break
                    candidate_meta.append({
                        "page": pn,
                        "snippet": _snippet(text, 800),
                        "header_row": header_row,
                        "toc_score": toc_score,
                        "numeric_density": _numeric_density(text),
                        "anchor_hits": _anchor_hits(statement_type, text),
                        "year_header_hits": _year_header_hits(text),
                        "table_shapes": shapes,
                        "largest_table_cells": largest,
                    })
                doc_meta = {"pages": document.meta.pages, "file_name": document.meta.file_name or ""}
                ranked = rank_candidates_fn(statement_type, candidate_meta, doc_meta)
                if ranked:
                    candidates = [p for p in ranked if p in candidates_set]
                    if not candidates:
                        candidates = list(candidates_set)
            except Exception as e:
                logger.warning("LLM rank fallback: %s", e)
                result.meta["llm_fallback"] = str(e)

        selected: LocatorSelection | None = None

        for attempt_idx in range(max_attempts):
            if not candidates:
                break
            page_num = candidates.pop(0) if candidates else 0
            if page_num not in page_by_num:
                continue
            page = page_by_num[page_num]
            text = get_page_text(page)
            is_toc, toc_score = is_toc_like(page)
            table_refs = _get_table_candidates_from_page(page)
            use_llm = strategy == "llm"
            score, rejected = _score_candidate(
                statement_type, page, table_refs, use_llm_ranking=use_llm
            )
            attempt = LocatorAttempt(
                statement_type=statement_type,
                candidate_source="index_map" if attempt_idx == 0 else "keyword_scan",
                page_start=page_num,
                page_end=page_num,
                page=page_num,
                is_toc_like=is_toc,
                toc_score=toc_score,
                table_candidates=table_refs,
                signals={
                    "numeric_density": _numeric_density(text),
                    "anchor_hits": _anchor_hits(statement_type, text),
                    "year_header_hits": _year_header_hits(text),
                },
                score=score,
                rejected_reason=rejected,
                snippet=_snippet(text),
            )
            result.attempts.append(attempt)
            if rejected:
                continue
            valid, fail_reason = _validate_candidate(
                statement_type, page, table_refs, use_llm_ranking=use_llm
            )
            no_tables = len(table_refs) == 0
            if not valid and not no_tables:
                attempt.rejected_reason = fail_reason
                continue
            if not valid and no_tables:
                attempt.rejected_reason = None  # allow OCR attempt
            # Try table first
            min_cols = 2 if use_llm else 3
            picked = _pick_best_table_on_page(page, min_cols=min_cols)
            if picked:
                grid, table_id, rows, cols = picked
                if cols >= min_cols:
                    selected = LocatorSelection(
                        statement_type=statement_type,
                        selected_mode="table",
                        selected_page_start=page_num,
                        selected_page_end=page_num,
                        selected_table_id=table_id,
                        confidence="High" if (_year_header_hits(text) >= 1 and cols >= 3) else "Med",
                        col_count=cols,
                        row_count=rows,
                    )
                    break
            # OCR fallback
            grid, ocr_fail = reconstruct_ocr_rows([page])
            if grid and len(grid) and len(grid[0]) >= 3:
                selected = LocatorSelection(
                    statement_type=statement_type,
                    selected_mode="ocr_rows",
                    selected_page_start=page_num,
                    selected_page_end=page_num,
                    selected_grid_ref=f"ocr_rows_p{page_num}",
                    confidence="Med",
                    col_count=len(grid[0]),
                    row_count=len(grid),
                )
                # Attach grid to selection for extractor (via meta)
                if "ocr_grids" not in result.meta:
                    result.meta["ocr_grids"] = {}
                result.meta["ocr_grids"][statement_type] = grid
                break
            attempt.rejected_reason = "OCR_RECONSTRUCTION_FAILED"

        if selected is None:
            last_reason = None
            for a in reversed(result.attempts):
                if a.statement_type == statement_type and a.rejected_reason:
                    last_reason = a.rejected_reason
                    break
            reason = last_reason or "NO_VALID_CANDIDATE"
            result.missing.append(MissingEntry(
                field=sheet_name,
                searched_in=f"pages {sorted(candidates_set)}" if candidates_set else "none",
                reason=reason,
            ))
        else:
            result.selections[statement_type] = selected

    return result
