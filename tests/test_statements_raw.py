"""Tests for statements_raw extraction (uses locator result; invariant: write or missing per sheet)."""
from __future__ import annotations

import pytest

from src.models.document import (
    Document,
    DocumentMeta,
    DocumentPage,
    TableCandidate,
    TextBlock,
)
from src.models.index_map import IndexMap
from src.models.locator import LocatorResult, LocatorSelection, MissingEntry
from src.pipeline.extract.statements_raw import extract_statements_raw


def test_extract_statements_raw_finds_table_from_locator_selection() -> None:
    """When locator selects BS with a 4-col table, we get one write_spec and row with locator fields, col_count>=3."""
    document = Document(
        meta=DocumentMeta(
            file_name="test.pdf",
            sha256="abc",
            pages=1,
            pdf_type="text",
            created_at="2026-01-01T00:00:00Z",
        ),
        pages=[
            DocumentPage(
                page=1,
                type="text",
                text_blocks=[TextBlock(block_id="b0", text="Balance Sheet")],
                tables=[
                    TableCandidate(
                        table_id="p1_t0",
                        grid=[
                            ["Particulars", "FY 2024", "FY 2023", "FY 2022"],
                            ["Equity", "100", "90", "80"],
                            ["Liabilities", "50", "45", "40"],
                        ],
                        confidence="High",
                    )
                ],
                images=[],
            )
        ],
    )
    index_map = IndexMap(
        company_name="Test",
        fiscal_year_label="FY 2024",
        sections=[],
        statements=[],
        notes=[],
        priority_locations={},
    )
    locator_result = LocatorResult(
        selections={
            "BS": LocatorSelection(
                statement_type="BS",
                selected_mode="table",
                selected_page_start=1,
                selected_page_end=1,
                selected_table_id="p1_t0",
                confidence="High",
                col_count=4,
                row_count=3,
            ),
            "IS": None,
            "CF": None,
        },
        attempts=[],
        missing=[
            MissingEntry(field="CF IS", searched_in="pages [1]", reason="NO_VALID_CANDIDATE"),
            MissingEntry(field="CF CFS", searched_in="pages [1]", reason="NO_VALID_CANDIDATE"),
        ],
        meta={},
    )
    extraction, write_specs = extract_statements_raw(document, index_map, locator_result, scope="both")
    assert extraction.module == "statements_raw"
    assert len(extraction.rows) == 1
    assert extraction.rows[0]["statement_type"] == "BS"
    assert extraction.rows[0]["sheet_name"] == "CF BS"
    assert extraction.rows[0]["page_ref"] == "p.1"
    assert extraction.rows[0]["table_id"] == "p1_t0"
    assert extraction.rows[0]["col_count"] >= 3
    assert extraction.rows[0].get("locator_page_range") == "p.1"
    assert extraction.rows[0].get("locator_mode") == "table"
    assert len(write_specs) == 1
    assert write_specs[0]["sheet_name"] == "CF BS"
    assert write_specs[0]["grid"][0] == ["Particulars", "FY 2024", "FY 2023", "FY 2022"]
    assert write_specs[0]["page_start"] == 1
    assert write_specs[0]["table_id"] == "p1_t0"
    # Invariant: each of CF BS, CF IS, CF CFS has write or missing
    assert len(extraction.missing) >= 2  # CF IS, CF CFS
    missing_fields = {m["field"] for m in extraction.missing}
    assert "CF IS" in missing_fields
    assert "CF CFS" in missing_fields


def test_extract_statements_raw_missing_when_no_usable_tables() -> None:
    """When locator has no selection for BS (or only selections with <3 cols), we get missing entry for that sheet."""
    document = Document(
        meta=DocumentMeta(
            file_name="test.pdf",
            sha256="abc",
            pages=1,
            pdf_type="text",
            created_at="2026-01-01T00:00:00Z",
        ),
        pages=[
            DocumentPage(
                page=1,
                type="text",
                text_blocks=[TextBlock(block_id="b0", text="Balance Sheet")],
                tables=[],  # no tables
                images=[],
            )
        ],
    )
    index_map = IndexMap(
        company_name="Test",
        fiscal_year_label="FY 2024",
        sections=[],
        statements=[],
        notes=[],
        priority_locations={},
    )
    locator_result = LocatorResult(
        selections={"BS": None, "IS": None, "CF": None},
        attempts=[],
        missing=[
            MissingEntry(field="CF BS", searched_in="pages [1]", reason="NO_TABLES_FOUND"),
            MissingEntry(field="CF IS", searched_in="pages [1]", reason="NO_VALID_CANDIDATE"),
            MissingEntry(field="CF CFS", searched_in="pages [1]", reason="NO_VALID_CANDIDATE"),
        ],
        meta={},
    )
    extraction, write_specs = extract_statements_raw(document, index_map, locator_result, scope="both")
    assert len(extraction.rows) == 0
    assert len(extraction.missing) >= 3
    missing_fields = {m["field"] for m in extraction.missing}
    assert "CF BS" in missing_fields
    assert "CF IS" in missing_fields
    assert "CF CFS" in missing_fields
    assert len(write_specs) == 0
