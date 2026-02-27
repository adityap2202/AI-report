"""
Phase 3 models: notes locator, governance, interpretations.
Evidence-first: all outputs include page_ref and snippet_id/table_id where applicable.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---- Target inventory (from template_map) ----
class TargetSpec(BaseModel):
    """Single extraction target (note tab, governance, MD&A)."""
    target_id: str = ""
    sheet_name: str = ""
    content_type: str = "table"  # table | narrative | interpretation | mixed
    topic: str | None = None  # revenue | ppe | borrowings | rpt | segment | directors | kmp | mdna | etc.
    expected_anchors: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    paste_anchor_cell: str | None = None
    header_row: int | None = None
    evidence_cols: list[str] = Field(default_factory=list)
    validation_min_cols: int = 2
    validation_min_density: float = 0.03


# ---- Notes locator ----
class NoteTableRef(BaseModel):
    table_id: str = ""
    rows: int = 0
    cols: int = 0
    caption: str = ""
    page: int = 0


class NotesLocatorAttempt(BaseModel):
    target_id: str = ""
    page: int = 0
    table_candidates: list[NoteTableRef] = Field(default_factory=list)
    score: float = 0.0
    rejected_reason: str | None = None  # NO_VALID_CANDIDATE | NO_TABLES_FOUND | VALIDATION_FAILED | LLM_PLAN_INVALID


class NotesLocatorSelection(BaseModel):
    target_id: str = ""
    sheet_name: str = ""
    selected_page_start: int = 0
    selected_page_end: int = 0
    selected_table_id: str | None = None
    confidence: str = "Med"
    col_count: int = 0
    row_count: int = 0


class NotesMissingEntry(BaseModel):
    field: str = ""  # sheet name or target_id
    searched_in: str = ""
    reason: str = ""  # NO_VALID_CANDIDATE | NO_TABLES_FOUND | VALIDATION_FAILED | OCR_RECONSTRUCTION_FAILED | LLM_PLAN_INVALID


class NotesLocatorResult(BaseModel):
    selections: dict[str, NotesLocatorSelection | None] = Field(default_factory=dict)  # target_id -> selection
    attempts: list[NotesLocatorAttempt] = Field(default_factory=list)
    missing: list[NotesMissingEntry] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


# ---- Notes raw extraction ----
class ExtractedSnippet(BaseModel):
    snippet_id: str = ""  # e.g. p5_b2
    page_ref: str = ""
    text: str = ""
    block_id: str = ""


class NoteExtractEntry(BaseModel):
    target_id: str = ""
    sheet_name: str = ""
    page_ref: str = ""
    table_id: str = ""
    grid: list[list[Any]] = Field(default_factory=list)
    narrative_snippets: list[ExtractedSnippet] = Field(default_factory=list)
    confidence: str = "Med"


class NotesRawResult(BaseModel):
    module: str = "notes_raw"
    version: str = "1.0"
    entries: list[NoteExtractEntry] = Field(default_factory=list)
    missing: list[dict[str, Any]] = Field(default_factory=list)


# ---- Governance ----
class GovChangeEntry(BaseModel):
    name: str = ""
    action: str = ""  # appointed | resigned
    effective_date: str = ""
    reason_snippet: str = ""
    page_ref: str = ""
    snippet_id: str = ""


class GovSectionEntry(BaseModel):
    section_type: str = ""  # directors | kmp | shareholding | corp_structure | rpt
    sheet_name: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)  # list of directors / KMP names
    changes: list[GovChangeEntry] = Field(default_factory=list)
    narrative_blocks: list[ExtractedSnippet] = Field(default_factory=list)
    tables: list[list[list[Any]]] = Field(default_factory=list)
    page_refs: list[str] = Field(default_factory=list)


class GovResult(BaseModel):
    module: str = "gov_sections"
    version: str = "1.0"
    entries: list[GovSectionEntry] = Field(default_factory=list)
    missing: list[dict[str, Any]] = Field(default_factory=list)


# ---- Interpretations (evidence required) ----
class InterpretationBullet(BaseModel):
    text: str = ""
    page_ref: str = ""
    snippet_id: str = ""  # required for acceptance


class MDNAInterpretation(BaseModel):
    revenue_drivers: list[InterpretationBullet] = Field(default_factory=list)
    margin_drivers: list[InterpretationBullet] = Field(default_factory=list)
    kpis: list[InterpretationBullet] = Field(default_factory=list)
    outlook: list[InterpretationBullet] = Field(default_factory=list)
    risks: list[InterpretationBullet] = Field(default_factory=list)


class NoteSummaryInterpretation(BaseModel):
    key_policies: list[InterpretationBullet] = Field(default_factory=list)
    key_judgements: list[InterpretationBullet] = Field(default_factory=list)
    unusual_movements: list[InterpretationBullet] = Field(default_factory=list)


class InterpretationResult(BaseModel):
    module: str = "interpretations"
    version: str = "1.0"
    mdna: MDNAInterpretation | None = None
    note_summaries: dict[str, NoteSummaryInterpretation] = Field(default_factory=dict)  # target_id -> summary
    missing: list[dict[str, Any]] = Field(default_factory=list)
