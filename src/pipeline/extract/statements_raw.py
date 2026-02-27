"""
Extract Balance Sheet, Income Statement, and Cash Flow as raw tables.
Uses StatementLocator output (never index_map directly). Enforces:
- Each of CF BS / CF IS / CF CFS has either a write OR a missing entry.
- Never High confidence for col_count < 3.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from src.models.document import Document
from src.models.extraction import Extraction
from src.models.index_map import IndexMap
from src.models.locator import LocatorResult, LocatorSelection

logger = logging.getLogger(__name__)

STATEMENT_TYPE_TO_SHEET = {"BS": "CF BS", "IS": "CF IS", "CF": "CF CFS"}


def _get_grid_from_document(document: Document, page_num: int, table_id: str) -> list[list[Any]] | None:
    """Return table grid from document by page and table_id."""
    for doc_page in document.pages:
        if doc_page.page != page_num:
            continue
        for t in doc_page.tables:
            if (t.table_id or "") == table_id and t.grid:
                return t.grid
    return None


def extract_statements_raw(
    document: Document,
    index_map: IndexMap,
    locator_result: LocatorResult,
    scope: str = "both",
) -> tuple[Extraction, list[dict[str, Any]]]:
    """
    Use locator_result only (no index_map for page/table choice).
    Returns (Extraction with locator fields, write_specs). Invariant: each CF BS/IS/CFS has write or missing.
    """
    rows: list[dict[str, Any]] = []
    write_specs: list[dict[str, Any]] = []
    missing = [m.model_dump() for m in locator_result.missing]

    for statement_type in ("BS", "IS", "CF"):
        sheet_name = STATEMENT_TYPE_TO_SHEET[statement_type]
        sel: LocatorSelection | None = locator_result.selections.get(statement_type)
        if sel is None:
            # Ensure missing entry exists for this sheet
            if not any(m.get("field") == sheet_name for m in missing):
                missing.append({
                    "field": sheet_name,
                    "searched_in": "locator",
                    "reason": "NO_VALID_CANDIDATE",
                })
            continue
        page_start = sel.selected_page_start
        page_end = sel.selected_page_end
        page_ref = f"p.{page_start}" if page_start == page_end else f"p.{page_start}-{page_end}"
        confidence = sel.confidence
        if sel.col_count < 3 and confidence == "High":
            confidence = "Med"
        grid: list[list[Any]] | None = None
        table_id = sel.selected_table_id or ""
        if sel.selected_mode == "table":
            grid = _get_grid_from_document(document, page_start, table_id or "")
            if not grid:
                missing.append({
                    "field": sheet_name,
                    "searched_in": page_ref,
                    "reason": "NO_TABLES_FOUND",
                })
                continue
        elif sel.selected_mode == "ocr_rows":
            grid = (locator_result.meta.get("ocr_grids") or {}).get(statement_type)
            if not grid or len(grid[0]) < 3:
                missing.append({
                    "field": sheet_name,
                    "searched_in": page_ref,
                    "reason": "OCR_RECONSTRUCTION_FAILED",
                })
                continue
        if not grid:
            continue
        col_count = len(grid[0]) if grid else 0
        if col_count < 3:
            missing.append({
                "field": sheet_name,
                "searched_in": page_ref,
                "reason": "TABLE_TOO_FEW_COLUMNS",
            })
            continue
        rows.append({
            "statement_type": statement_type,
            "sheet_name": sheet_name,
            "page_start": page_start,
            "page_end": page_end,
            "page_ref": page_ref,
            "table_id": table_id,
            "mode": sel.selected_mode,
            "confidence": confidence,
            "row_count": len(grid),
            "col_count": col_count,
            "locator_page_range": page_ref,
            "locator_table_id": table_id,
            "locator_mode": sel.selected_mode,
        })
        write_specs.append({
            "sheet_name": sheet_name,
            "grid": grid,
            "page_start": page_start,
            "page_end": page_end,
            "table_id": table_id,
            "confidence": confidence,
            "mode": sel.selected_mode,
        })

    # Invariant: for each CF BS, CF IS, CF CFS we must have either a write or missing
    for sheet_name in ("CF BS", "CF IS", "CF CFS"):
        has_write = any(w["sheet_name"] == sheet_name for w in write_specs)
        has_missing = any(m.get("field") == sheet_name for m in missing)
        if not has_write and not has_missing:
            missing.append({
                "field": sheet_name,
                "searched_in": "locator",
                "reason": "NO_VALID_CANDIDATE",
            })

    extraction = Extraction(
        module="statements_raw",
        version="2.0",
        rows=rows,
        missing=missing,
        qa={
            "confidence": "High" if rows else "N/A",
            "count": len(rows),
            "locator_strategy": locator_result.meta.get("strategy", "deterministic"),
        },
    )
    return extraction, write_specs
