"""LLM returns invalid JSON -> fallback to deterministic, trace contains LLM_PLAN_INVALID or fallback."""
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


def test_llm_invalid_json_fallback_to_deterministic() -> None:
    page = DocumentPage(
        page=1,
        type="text",
        text_blocks=[TextBlock(block_id="b0", text="Balance Sheet  Total Assets  FY 2024  FY 2023")],
        tables=[
            TableCandidate(
                table_id="p1_t0",
                grid=[
                    ["Item", "FY 2024", "FY 2023"],
                    ["Equity", "100", "90"],
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
            pages=1,
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
            StatementRef(type="BS", scope="standalone", caption="Balance Sheet", page_start=1, page_end=1),
        ],
        notes=[],
        priority_locations={},
    )

    def bad_rank(statement_type: str, candidates: list, meta: dict):
        raise ValueError("invalid json")

    result = locate_statements(
        document,
        index_map,
        scope="both",
        strategy="llm",
        rank_candidates_fn=bad_rank,
    )
    # Fallback: still finds the table deterministically
    assert "BS" in result.selections or "llm_fallback" in result.meta
