"""
Locator result models for statement location (BS/IS/CF).
Per specs/002-statement-locator-hardening.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TableCandidateRef(BaseModel):
    table_id: str = ""
    rows: int = 0
    cols: int = 0
    caption: str = ""


class LocatorAttempt(BaseModel):
    statement_type: str = ""  # BS | IS | CF
    candidate_source: str = ""  # index_map | keyword_scan | numeric_density
    page_start: int = 0
    page_end: int = 0
    page: int = 0  # single page when same
    is_toc_like: bool = False
    toc_score: float = 0.0
    table_candidates: list[TableCandidateRef] = Field(default_factory=list)
    signals: dict[str, Any] = Field(default_factory=dict)  # numeric_density, anchor_hits, year_header_hits
    score: float = 0.0
    rejected_reason: str | None = None  # TOC_FALSE_POSITIVE | TABLE_TOO_FEW_COLUMNS | etc.
    snippet: str = ""


class LocatorSelection(BaseModel):
    statement_type: str = ""
    selected_mode: str = ""  # table | ocr_rows
    selected_page_start: int = 0
    selected_page_end: int = 0
    selected_table_id: str | None = None
    selected_grid_ref: str | None = None  # e.g. "ocr_rows_p5"
    confidence: str = "High"  # High | Med | Low
    col_count: int = 0
    row_count: int = 0


class MissingEntry(BaseModel):
    field: str = ""  # CF BS | CF IS | CF CFS
    searched_in: str = ""
    reason: str = ""  # TOC_FALSE_POSITIVE | NO_TABLES_FOUND | TABLE_TOO_FEW_COLUMNS | OCR_RECONSTRUCTION_FAILED | NO_VALID_CANDIDATE


class LocatorResult(BaseModel):
    selections: dict[str, LocatorSelection | None] = Field(default_factory=dict)  # BS -> selection or None
    attempts: list[LocatorAttempt] = Field(default_factory=list)
    missing: list[MissingEntry] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)  # strategy, max_attempts, thresholds, llm_used
