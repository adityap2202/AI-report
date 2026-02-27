"""
Index map model (index_map.json).
Per specs/001-annual-report-databook-agent/contracts/index-map.schema.json and data-model.md.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SectionRef(BaseModel):
    title: str = ""
    page_start: int = 0
    page_end: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class StatementRef(BaseModel):
    type: str = ""  # BS | IS | CF | CFS | SOCE
    scope: str = ""  # standalone | consolidated
    caption: str = ""
    page_start: int = 0
    page_end: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class NoteRef(BaseModel):
    note_number: str = ""
    title: str = ""
    page_start: int = 0
    page_end: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class IndexMap(BaseModel):
    company_name: str = ""
    fiscal_year_label: str = ""
    units_default: str = ""
    sections: list[SectionRef] = Field(default_factory=list)
    statements: list[StatementRef] = Field(default_factory=list)
    notes: list[NoteRef] = Field(default_factory=list)
    priority_locations: dict[str, Any] = Field(default_factory=dict)  # revenue, ppe, leases, rpt, segment -> refs
