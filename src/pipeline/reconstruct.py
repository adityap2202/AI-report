"""
Document reconstruction: build canonical document.json from PDF.
- Text pages: text blocks + table candidates (pdfplumber).
- Image pages: rasterize (pymupdf), optional OCR with confidence.
Per specs/001-annual-report-databook-agent/data-model.md and FR-003.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pdfplumber
import fitz  # pymupdf

from src.models.document import (
    Document,
    DocumentMeta,
    DocumentPage,
    ImageRef,
    TableCandidate,
    TextBlock,
)
from src.pipeline.pdf_type import detect_pdf_type

logger = logging.getLogger(__name__)

# Optional OCR (lazy so CLI loads even if tesseract/pandas not available)
def _ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        return True
    except Exception:
        return False
OCR_AVAILABLE = False  # set on first use


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_text_blocks_and_tables(pdf_path: Path, page_num: int) -> tuple[list[TextBlock], list[TableCandidate]]:
    """Use pdfplumber to get text blocks and table candidates for a text page."""
    blocks: list[TextBlock] = []
    tables: list[TableCandidate] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_num < 1 or page_num > len(pdf.pages):
                return blocks, tables
            page = pdf.pages[page_num - 1]
            # Text: use chars or extract_text with layout
            raw_text = page.extract_text() or ""
            if raw_text:
                # Single block per page for simplicity; could split by line/bbox later
                blocks.append(
                    TextBlock(
                        block_id=f"p{page_num}_b0",
                        text=raw_text,
                        bbox=[],
                        role_hint="body",
                    )
                )
            # Tables
            found = page.find_tables()
            for i, t in enumerate(found):
                grid: list[list] = []
                try:
                    data = t.extract()
                    if data:
                        grid = [[str(cell) if cell is not None else "" for cell in row] for row in data]
                except Exception as e:
                    logger.debug("Table extract failed p%s t%s: %s", page_num, i, e)
                tables.append(
                    TableCandidate(
                        table_id=f"p{page_num}_t{i}",
                        bbox=list(t.bbox) if hasattr(t, "bbox") else [],
                        caption="",
                        grid=grid,
                        confidence="High",
                    )
                )
    except Exception as e:
        logger.warning("_extract_text_blocks_and_tables failed p%s: %s", page_num, e)
    return blocks, tables


def _rasterize_page(pdf_path: Path, page_num: int, dpi: int = 150) -> Optional[bytes]:
    """Rasterize one page to PNG bytes using pymupdf."""
    try:
        doc = fitz.open(pdf_path)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            return None
        page = doc[page_num - 1]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")
        doc.close()
        return png_bytes
    except Exception as e:
        logger.warning("_rasterize_page failed p%s: %s", page_num, e)
        return None


def _ocr_image(png_bytes: bytes) -> tuple[str, float]:
    """Run Tesseract OCR on image bytes. Returns (text, confidence 0..1)."""
    try:
        import pytesseract
    except Exception:
        return "", 0.0
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(png_bytes))
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        # Average confidence of non-empty words (tesseract gives 0-100)
        confs = [c for c in data.get("conf", []) if c > 0]
        avg = sum(confs) / len(confs) / 100.0 if confs else 0.0
        text = pytesseract.image_to_string(img)
        return text.strip(), max(0.0, min(1.0, avg))
    except Exception as e:
        logger.debug("OCR failed: %s", e)
        return "", 0.0


def reconstruct_document(
    pdf_path: str | Path,
    doc_type: str,
    page_types: list[str],
    max_pages: Optional[int] = None,
    run_ocr_for_image_pages: bool = True,
) -> Document:
    """
    Build Document from PDF. doc_type and page_types from detect_pdf_type().
    For image pages: rasterize then optionally OCR; store one text block with ocr_confidence.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    total_pages = min(len(page_types), len(list(range(1, len(page_types) + 1))))
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)

    meta = DocumentMeta(
        file_name=path.name,
        sha256=_sha256(path),
        pages=total_pages,
        pdf_type=doc_type,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    pages: list[DocumentPage] = []

    for i in range(total_pages):
        page_num = i + 1
        ptype = page_types[i] if i < len(page_types) else "text"

        if ptype == "text":
            blocks, tables = _extract_text_blocks_and_tables(path, page_num)
            pages.append(
                DocumentPage(
                    page=page_num,
                    type="text",
                    text_blocks=blocks,
                    tables=tables,
                    images=[],
                )
            )
        else:
            # Image page: rasterize, optionally OCR
            png_bytes = _rasterize_page(path, page_num)
            blocks: list[TextBlock] = []
            tables: list[TableCandidate] = []
            img_ref = ImageRef(image_id=f"p{page_num}_img", bbox=[], path="")
            if png_bytes and run_ocr_for_image_pages:
                text, conf = _ocr_image(png_bytes)
                blocks.append(
                    TextBlock(
                        block_id=f"p{page_num}_ocr",
                        text=text,
                        bbox=[],
                        role_hint="ocr",
                        ocr_confidence=conf,
                    )
                )
                img_ref.path = f"p{page_num}_img.png"  # caller may write to disk if needed
            pages.append(
                DocumentPage(
                    page=page_num,
                    type="image",
                    text_blocks=blocks,
                    tables=tables,
                    images=[img_ref],
                )
            )
    return Document(meta=meta, pages=pages)
