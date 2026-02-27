"""
TemplateMap model: workbook layout contract.
Per specs/001-annual-report-databook-agent/contracts/template-map.schema.json and data-model.md.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SheetMap(BaseModel):
    """Per-sheet layout: type, anchors, columns."""
    type: str = ""  # financial_statement | note_rollup | governance | etc.
    statement: str | None = None  # balance_sheet | income_statement | cash_flow
    topic: str | None = None  # ppe | revenue | expenses | borrowings | rpt | segment
    anchor_cell: str | None = None  # e.g. A1
    header_row: int | None = None  # 1-based
    line_item_column: str | None = None  # A, B
    year_columns: list[str] = Field(default_factory=list)  # C, D, E...
    evidence_cols: list[str] = Field(default_factory=list)  # Source, Evidence, Confidence
    line_item_aliases: dict[str, list[str]] = Field(default_factory=dict)
    validations: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class TemplateMap(BaseModel):
    workbook_name: str = ""
    sheets: dict[str, SheetMap] = Field(default_factory=dict)  # sheet name -> SheetMap
    write_rules: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)
