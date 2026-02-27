"""
Index builder: produce index_map.json from document.json.
Scans document for statement captions, note labels, section headings.
Per specs/001-annual-report-databook-agent/data-model.md and FR-004.
"""
from __future__ import annotations

import re
import logging
from typing import Any

from src.models.document import Document
from src.models.index_map import IndexMap, NoteRef, SectionRef, StatementRef

logger = logging.getLogger(__name__)

# Patterns (minimal; extend in reference/patterns)
STATEMENT_CAPTIONS = [
    (r"balance\s+sheet", "BS"),
    (r"statement\s+of\s+profit\s+and\s+loss|profit\s+and\s+loss", "IS"),
    (r"cash\s+flow\s+statement|statement\s+of\s+cash\s+flows", "CF"),
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


def build_index_map(
    document: Document,
    company_name_override: str | None = None,
    fiscal_year_override: str | None = None,
) -> IndexMap:
    """
    Scan document pages for sections, statements, notes. Build IndexMap.
    """
    sections: list[SectionRef] = []
    statements: list[StatementRef] = []
    notes: list[NoteRef] = []
    priority_locations: dict[str, Any] = {}

    for doc_page in document.pages:
        page_num = doc_page.page
        full_text = " ".join(b.text for b in doc_page.text_blocks).lower()

        # Statement captions
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
        for m in NOTE_PATTERN.finditer(" ".join(b.text for b in doc_page.text_blocks)):
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

    # Dedupe and merge adjacent note/section ranges (simplified: keep first occurrence)
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
