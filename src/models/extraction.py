"""
Extraction module output model.
Per specs/001-annual-report-databook-agent/contracts/extraction.schema.json and data-model.md.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Extraction(BaseModel):
    module: str
    version: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    missing: list[dict[str, Any]] = Field(default_factory=list)  # {field, searched_in, reason}
    notes: str | None = None
    qa: dict[str, Any] = Field(default_factory=dict)  # confidence distribution etc.
