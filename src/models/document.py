"""
Canonical document model (document.json).
Per specs/001-annual-report-databook-agent/contracts/document-json.schema.json and data-model.md.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DocumentMeta(BaseModel):
    file_name: str
    sha256: str
    pages: int
    pdf_type: str  # text | scanned | mixed
    created_at: str


class TextBlock(BaseModel):
    block_id: str = ""
    text: str = ""
    bbox: list[float] = Field(default_factory=list)  # x0, top, x1, bottom
    role_hint: str = ""  # e.g. paragraph, heading, caption
    ocr_confidence: float | None = None


class TableCandidate(BaseModel):
    table_id: str = ""
    bbox: list[float] = Field(default_factory=list)
    caption: str = ""
    grid: list[list[Any]] = Field(default_factory=list)  # 2D cell values
    confidence: str = "High"  # High | Med | Low


class ImageRef(BaseModel):
    image_id: str = ""
    bbox: list[float] = Field(default_factory=list)
    path: str = ""


class DocumentPage(BaseModel):
    page: int
    type: str  # text | image
    text_blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[TableCandidate] = Field(default_factory=list)
    images: list[ImageRef] = Field(default_factory=list)


class Document(BaseModel):
    meta: DocumentMeta
    pages: list[DocumentPage] = Field(default_factory=list)
