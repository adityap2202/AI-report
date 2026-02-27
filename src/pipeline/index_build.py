"""
Index builder: produce index_map.json from document.json.
Scans document for statement captions, note labels, section headings.
Per specs/001-annual-report-databook-agent/data-model.md and FR-004.
"""
from __future__ import annotations

import re
import logging
from typing import Any

from src.models.document import Document, DocumentPage
from src.models.index_map import IndexMap, NoteRef, SectionRef, StatementRef

logger = logging.getLogger(__name__)

# Patterns (minimal; extend in reference/patterns)
STATEMENT_CAPTIONS = [
    (r"balance\s+sheet|equity\s+and\s+liabilities", "BS"),
    (r"statement\s+of\s+profit\s+and\s+loss|profit\s+and\s+loss|revenue\s+from\s+operations", "IS"),
    (r"cash\s+flow\s+statement|statement\s+of\s+cash\s+flows|cash\s+flow\s+from", "CF"),
    (r"consolidated\s+balance\s+sheet", "BS"),
    (r"consolidated\s+statement\s+of\s+profit", "IS"),
    (r"consolidated\s+cash\s+flow", "CF"),
    (r"notes?\s+to\s+(?:the\s+)?(?:consolidated\s+)?financial\s+statements?", "Notes"),
]
NOTE_PATTERN = re.compile(r"\bnote\s+(\d+[A-Za-z]?)\b", re.I)
SECTION_HEADINGS = [
    "corporate governance",
    "board's report",
    "management discussion",
    "related party",
    "segment information",
    "notes to accounts",
]


def _detect_scope(text: str) -> str:
    t = text.lower()
    if "consolidated" in t:
        return "consolidated"
    return "standalone"


def _page_text_for_index(doc_page: DocumentPage) -> str:
    """Page text from text_blocks and table grids so index finds content when ingest puts it in tables (e.g. Marker)."""
    parts = [b.text for b in doc_page.text_blocks]
    for t in doc_page.tables:
        if t.grid:
            for row in t.grid:
                for cell in row:
                    if isinstance(cell, str) and cell.strip():
                        parts.append(cell.strip())
    return " ".join(parts)


def build_index_map(
    document: Document,
    company_name_override: str | None = None,
    fiscal_year_override: str | None = None,
    statement_pages_from_llm: dict[str, int] | None = None,
) -> IndexMap:
    """
    Build IndexMap. If statement_pages_from_llm is provided (e.g. {"BS": 70, "IS": 71, "CF": 72}),
    use it for statements and skip regex statement detection. Notes/sections still use regex.
    """
    sections: list[SectionRef] = []
    statements: list[StatementRef] = []
    notes: list[NoteRef] = []
    priority_locations: dict[str, Any] = {}

    if statement_pages_from_llm:
        for stype, page_num in statement_pages_from_llm.items():
            if stype in ("BS", "IS", "CF") and page_num >= 1 and page_num <= document.meta.pages:
                pg = next((p for p in document.pages if p.page == page_num), None)
                caption = _page_text_for_index(pg)[:200] if pg else ""
                statements.append(
                    StatementRef(
                        type=stype,
                        scope="standalone",
                        caption=caption,
                        page_start=page_num,
                        page_end=page_num,
                    )
                )

    for doc_page in document.pages:
        page_num = doc_page.page
        full_text = _page_text_for_index(doc_page).lower()

        # Statement captions (skip if we already have statements from LLM)
        if not statement_pages_from_llm:
            for pattern, stype in STATEMENT_CAPTIONS:
                if re.search(pattern, full_text, re.I):
                    scope = _detect_scope(full_text)
                    if stype != "Notes":
                        statements.append(
                            StatementRef(
                                type=stype,
                                scope=scope,
                                caption=full_text[:200],
                                page_start=page_num,
                                page_end=page_num,
                            )
                        )
                    break

        # Note numbers
        for m in NOTE_PATTERN.finditer(_page_text_for_index(doc_page)):
            num = m.group(1)
            notes.append(
                NoteRef(
                    note_number=num,
                    title="",
                    page_start=page_num,
                    page_end=page_num,
                )
            )

        # Section headings
        for heading in SECTION_HEADINGS:
            if heading in full_text:
                sections.append(
                    SectionRef(
                        title=heading,
                        page_start=page_num,
                        page_end=page_num,
                    )
                )
                # Map to priority_locations keys
                if "segment" in heading:
                    priority_locations["segment"] = {"page_start": page_num, "page_end": page_num}
                elif "related party" in heading:
                    priority_locations["rpt"] = {"page_start": page_num, "page_end": page_num}
                break

    # Dedupe and merge adjacent note/section ranges
    def dedupe_refs(refs: list, key_fn):
        seen = set()
        out = []
        for r in refs:
            k = key_fn(r)
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    statements = dedupe_refs(statements, lambda r: (r.type, r.scope))
    notes = dedupe_refs(notes, lambda r: r.note_number)[:50]  # cap notes
    sections = dedupe_refs(sections, lambda r: r.title)

    return IndexMap(
        company_name=company_name_override or "",
        fiscal_year_label=fiscal_year_override or "",
        units_default="",
        sections=sections,
        statements=statements,
        notes=notes,
        priority_locations=priority_locations,
    )
