"""
PDF type detection: per-page text-length heuristic.
Page with little/no text → image (scanned); otherwise text.
Document-level: all text → text, all image → scanned, mixed → mixed.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import pdfplumber

PageType = Literal["text", "image"]
DocPDFType = Literal["text", "scanned", "mixed"]

# Characters per page below this → treat as image page (needs OCR)
DEFAULT_TEXT_THRESHOLD = 100

logger = logging.getLogger(__name__)


def get_page_text_length(pdf_path: str | Path, page_num: int, max_pages: int | None = None) -> int:
    """Return character count of extracted text for given 1-based page."""
    if max_pages is not None and page_num > max_pages:
        return 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_num < 1 or page_num > len(pdf.pages):
                return 0
            page = pdf.pages[page_num - 1]
            text = page.extract_text() or ""
            return len(text)
    except Exception as e:
        logger.warning("get_page_text_length failed for page %s: %s", page_num, e)
        return 0


def classify_page(
    pdf_path: str | Path,
    page_num: int,
    text_threshold: int = DEFAULT_TEXT_THRESHOLD,
    max_pages: int | None = None,
) -> PageType:
    """Classify a single page as 'text' or 'image' by extracted text length."""
    n = get_page_text_length(pdf_path, page_num, max_pages)
    return "text" if n >= text_threshold else "image"


def detect_pdf_type(
    pdf_path: str | Path,
    text_threshold: int = DEFAULT_TEXT_THRESHOLD,
    max_pages: int | None = None,
) -> tuple[DocPDFType, list[PageType]]:
    """
    Detect document-level PDF type and per-page types.
    Returns (doc_type, list of page types for each page).
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    page_types: list[PageType] = []
    try:
        with pdfplumber.open(path) as pdf:
            total = len(pdf.pages) if max_pages is None else min(len(pdf.pages), max_pages)
            for i in range(1, total + 1):
                pt = classify_page(path, i, text_threshold, max_pages)
                page_types.append(pt)
    except Exception as e:
        logger.exception("detect_pdf_type failed: %s", e)
        raise

    n_text = sum(1 for p in page_types if p == "text")
    n_image = len(page_types) - n_text
    if n_image == 0:
        doc_type: DocPDFType = "text"
    elif n_text == 0:
        doc_type = "scanned"
    else:
        doc_type = "mixed"
    logger.info("PDF type: %s (text pages=%s, image pages=%s)", doc_type, n_text, n_image)
    return doc_type, page_types
