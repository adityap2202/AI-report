"""
OCR row reconstruction: build a grid from page text_blocks when no table objects exist.
Only for candidate pages. Requires cols >= 3 (line item + 2 years).
"""
from __future__ import annotations

import re
import logging
from typing import Any

from src.models.document import DocumentPage, TextBlock

logger = logging.getLogger(__name__)

# Lines with at least 2 numeric tokens are data rows
NUMERIC_TOKEN = re.compile(r"[0-9,.\-]+|[₹]|Crores|Lakhs", re.I)


def _tokenize(line: str) -> list[str]:
    return line.split()

def _count_numeric_tokens(tokens: list[str]) -> int:
    return sum(1 for t in tokens if NUMERIC_TOKEN.search(t))


def reconstruct_ocr_rows(
    pages: list[DocumentPage],
) -> tuple[list[list[Any]], str | None]:
    """
    Reconstruct a table grid from text_blocks across pages.
    - Detect lines with >= 2 numeric tokens
    - Group numeric tokens into columns (whitespace/alignment heuristics)
    - Return (grid, None) if cols >= 3 else ([], "OCR_RECONSTRUCTION_FAILED")
    """
    lines_with_nums: list[list[str]] = []
    for doc_page in pages:
        for block in doc_page.text_blocks:
            text = (block.text or "").strip()
            if not text:
                continue
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                tokens = _tokenize(line)
                if _count_numeric_tokens(tokens) >= 2:
                    lines_with_nums.append(tokens)
    if not lines_with_nums:
        return [], "OCR_RECONSTRUCTION_FAILED"
    # Estimate columns: use longest row as reference; align others by token count or position
    max_cols = max(len(row) for row in lines_with_nums)
    if max_cols < 3:
        return [], "OCR_RECONSTRUCTION_FAILED"
    # Build grid: pad short rows with "" so we have uniform cols
    grid: list[list[Any]] = []
    for row in lines_with_nums:
        padded = list(row) + [""] * (max_cols - len(row))
        grid.append(padded[:max_cols])
    return grid, None


def reconstruct_ocr_rows_from_page(doc_page: DocumentPage) -> tuple[list[list[Any]], str | None]:
    """Reconstruct from a single page's text_blocks. Returns (grid, None) or ([], reason)."""
    return reconstruct_ocr_rows([doc_page])
