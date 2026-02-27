"""Multi-table page: 1-col and 4-col tables -> locator picks 4-col."""
from __future__ import annotations

from src.models.document import (
    Document,
    DocumentMeta,
    DocumentPage,
    TableCandidate,
    TextBlock,
)
from src.models.index_map import IndexMap, StatementRef
from src.pipeline.locate.statements import locate_statements


def test_locator_picks_table_with_more_columns() -> None:
    text = "Balance Sheet\nTotal Assets  Equity\nFY 2024  FY 2023\n"
    page = DocumentPage(
        page=10,
        type="text",
        text_blocks=[TextBlock(block_id="b0", text=text)],
        tables=[
            TableCandidate(table_id="p10_t0", grid=[["Only one column"]], confidence="High"),
            TableCandidate(
                table_id="p10_t1",
                grid=[
                    ["Line", "FY 2024", "FY 2023", "FY 2022"],
                    ["Revenue", "100", "90", "80"],
                ],
                confidence="High",
            ),
        ],
        images=[],
    )
    document = Document(
        meta=DocumentMeta(
            file_name="test.pdf",
            sha256="x",
            pages=10,
            pdf_type="text",
            created_at="2026-01-01T00:00:00Z",
        ),
        pages=[page],
    )
    index_map = IndexMap(
        company_name="Test",
        fiscal_year_label="FY 2024",
        sections=[],
        statements=[
            StatementRef(type="BS", scope="standalone", caption="Balance Sheet", page_start=10, page_end=10),
        ],
        notes=[],
        priority_locations={},
    )
    result = locate_statements(document, index_map, scope="both", strategy="deterministic")
    assert "BS" in result.selections
    sel = result.selections["BS"]
    assert sel is not None
    assert sel.col_count >= 3
    assert sel.selected_table_id == "p10_t1"
