"""OCR row reconstruction: no tables but text lines with >=2 numeric tokens -> grid with cols>=3, mode=ocr_rows."""
from __future__ import annotations

from src.models.document import Document, DocumentMeta, DocumentPage, TextBlock
from src.models.index_map import IndexMap, StatementRef
from src.pipeline.locate.statements import locate_statements


def test_locator_uses_ocr_reconstruction_when_no_tables() -> None:
    # Line-item style lines with two year values (so >=2 numeric tokens per line)
    text = """Balance Sheet
Total Assets  100  90
Equity  50  45
Liabilities  50  45"""
    page = DocumentPage(
        page=7,
        type="text",
        text_blocks=[TextBlock(block_id="b0", text=text)],
        tables=[],
        images=[],
    )
    document = Document(
        meta=DocumentMeta(
            file_name="test.pdf",
            sha256="x",
            pages=7,
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
            StatementRef(type="BS", scope="standalone", caption="Balance Sheet", page_start=7, page_end=7),
        ],
        notes=[],
        priority_locations={},
    )
    result = locate_statements(document, index_map, scope="both", strategy="deterministic")
    assert "BS" in result.selections
    sel = result.selections["BS"]
    assert sel is not None
    assert sel.selected_mode == "ocr_rows"
    assert sel.col_count >= 3
    assert result.meta.get("ocr_grids", {}).get("BS") is not None
