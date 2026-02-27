"""LLM planner ranking: stub returns ranked pages; locator uses them but still validates (no real LLM)."""
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


def test_llm_ranking_reorders_candidates_validation_unchanged() -> None:
    # Page 3 has weak table (2 cols); page 8 has strong table (4 cols). Index points to 3.
    page3 = DocumentPage(
        page=3,
        type="text",
        text_blocks=[TextBlock(block_id="b0", text="Balance Sheet\nA  B")],
        tables=[TableCandidate(table_id="p3_t0", grid=[["X", "Y"]], confidence="High")],
        images=[],
    )
    page8 = DocumentPage(
        page=8,
        type="text",
        text_blocks=[TextBlock(block_id="b0", text="Balance Sheet  Total Assets  FY 2024  FY 2023")],
        tables=[
            TableCandidate(
                table_id="p8_t0",
                grid=[
                    ["Item", "FY 2024", "FY 2023", "FY 2022"],
                    ["Equity", "100", "90", "80"],
                ],
                confidence="High",
            )
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
        pages=[page3, page8],
    )
    index_map = IndexMap(
        company_name="Test",
        fiscal_year_label="FY 2024",
        sections=[],
        statements=[
            StatementRef(type="BS", scope="standalone", caption="Balance Sheet", page_start=3, page_end=3),
        ],
        notes=[],
        priority_locations={},
    )

    def stub_rank(statement_type: str, candidates: list, meta: dict):
        # Rank page 8 first (the good one)
        pages = [c.get("page") for c in candidates if c.get("page") is not None]
        if 8 in pages and 3 in pages:
            return [8, 3]
        return pages

    result = locate_statements(
        document,
        index_map,
        scope="both",
        strategy="llm",
        rank_candidates_fn=stub_rank,
    )
    assert "BS" in result.selections
    sel = result.selections["BS"]
    assert sel is not None
    assert sel.selected_page_start == 8
    assert sel.col_count >= 3
