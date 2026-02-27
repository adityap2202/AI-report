"""TOC false positive: index_map points BS to TOC page but real BS exists -> locator selects real page."""
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


def test_locator_rejects_toc_and_selects_real_bs_page() -> None:
    # Page 5: TOC-like (Contents, dotted leaders, low density)
    toc_text = "Contents\nBalance Sheet .............. 5\nNotes ...................... 10\n"
    page5 = DocumentPage(
        page=5,
        type="text",
        text_blocks=[TextBlock(block_id="b0", text=toc_text)],
        tables=[],
        images=[],
    )
    # Page 89: real Balance Sheet with anchors + 4-col table
    real_bs_text = "Balance Sheet as at March 31 2024\nTotal Assets  Equity and Liabilities\nFY 2024  FY 2023  FY 2022\n"
    page89 = DocumentPage(
        page=89,
        type="text",
        text_blocks=[TextBlock(block_id="b0", text=real_bs_text)],
        tables=[
            TableCandidate(
                table_id="p89_t0",
                grid=[
                    ["Particulars", "FY 2024", "FY 2023", "FY 2022"],
                    ["Total Assets", "100", "90", "80"],
                    ["Equity", "50", "45", "40"],
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
            pages=90,
            pdf_type="text",
            created_at="2026-01-01T00:00:00Z",
        ),
        pages=[page5, page89],
    )
    index_map = IndexMap(
        company_name="Test",
        fiscal_year_label="FY 2024",
        sections=[],
        statements=[
            StatementRef(type="BS", scope="standalone", caption="Balance Sheet", page_start=5, page_end=5),
        ],
        notes=[],
        priority_locations={},
    )
    result = locate_statements(document, index_map, scope="both", strategy="deterministic")
    # Should select real BS on page 89, not TOC on 5
    assert "BS" in result.selections
    sel = result.selections["BS"]
    assert sel is not None
    assert sel.selected_page_start == 89
    assert sel.selected_table_id == "p89_t0"
    assert sel.col_count >= 3
    # TOC page should appear in attempts with rejection
    bs_attempts = [a for a in result.attempts if a.statement_type == "BS"]
    toc_attempt = next((a for a in bs_attempts if a.page == 5 and a.rejected_reason), None)
    assert toc_attempt is not None
    assert toc_attempt.rejected_reason in ("TOC_FALSE_POSITIVE", "TABLE_TOO_FEW_COLUMNS") or toc_attempt.is_toc_like
