"""
Marker-based PDF ingestion (datalab-to/marker). Primary and only PDF reconstruction for the pipeline.
Runs entirely locally; no API calls. Produces document.json compatible with the locator (statements.py).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models.document import (
    Document,
    DocumentMeta,
    DocumentPage,
    TableCandidate,
    TextBlock,
)

logger = logging.getLogger(__name__)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _grid_from_block(blk: Any, page_obj: Any = None) -> list[list[Any]]:
    """Extract 2D grid from a Marker table block. datalab-to/marker uses TableCell children."""
    # Direct grid/data/cells (simple format)
    grid = getattr(blk, "grid", None) or getattr(blk, "data", None) or getattr(blk, "cells", None)
    if isinstance(grid, list) and grid:
        out: list[list[Any]] = []
        for row in grid:
            if isinstance(row, list):
                out.append([str(c) if c is not None else "" for c in row])
            else:
                out.append([str(row)])
        return out
    # datalab-to/marker: Table has structure of BlockIds -> TableCell blocks (row_id, col_id, text_lines)
    if page_obj is not None and hasattr(page_obj, "get_block"):
        structure = getattr(blk, "structure", None) or []
        cells: list[tuple[int, int, str]] = []
        for bid in structure:
            try:
                cell = page_obj.get_block(bid)
            except (IndexError, KeyError, TypeError):
                continue
            if cell is None:
                continue
            ctype = getattr(cell, "block_type", None) or getattr(cell, "type", None)
            if ctype is not None and "tablecell" not in str(ctype).lower() and "cell" not in str(ctype).lower():
                continue
            row_id = getattr(cell, "row_id", 0)
            col_id = getattr(cell, "col_id", 0)
            text_lines = getattr(cell, "text_lines", None) or []
            text = "\n".join(text_lines).strip() if isinstance(text_lines, list) else getattr(cell, "text", "") or ""
            cells.append((row_id, col_id, text))
        if not cells:
            return []
        max_r = max(c[0] for c in cells) + 1
        max_c = max(c[1] for c in cells) + 1
        grid_out = [[""] * max_c for _ in range(max_r)]
        for r, c, t in cells:
            if 0 <= r < max_r and 0 <= c < max_c:
                grid_out[r][c] = t
        return grid_out
    return []


def _text_from_block(blk: Any, page_obj: Any = None) -> str:
    """Extract text from a Marker text block (text, content, text_lines, or structure children)."""
    text = getattr(blk, "text", None) or getattr(blk, "content", None)
    if text is None:
        text_lines = getattr(blk, "text_lines", None)
        if isinstance(text_lines, list):
            text = " ".join(str(t) for t in text_lines)
    if text is None and page_obj is not None and hasattr(page_obj, "get_block"):
        structure = getattr(blk, "structure", None) or []
        parts = []
        for bid in structure:
            try:
                sub = page_obj.get_block(bid)
            except (IndexError, KeyError, TypeError):
                continue
            if sub is None:
                continue
            parts.append(
                getattr(sub, "text", None) or getattr(sub, "content", None)
                or (" ".join(getattr(sub, "text_lines", [])) if isinstance(getattr(sub, "text_lines", None), list) else "")
            )
        text = " ".join(str(p).strip() for p in parts if p)
    if text is None:
        return ""
    if isinstance(text, list):
        return " ".join(str(t) for t in text)
    return str(text).strip()


def _normalize_page(page_num: int, page_obj: Any) -> DocumentPage:
    """Map Marker page to our DocumentPage (document.json contract)."""
    text_blocks: list[TextBlock] = []
    tables: list[TableCandidate] = []
    # datalab-to/marker: use structure + get_block for reading order; fallback to children
    children = getattr(page_obj, "current_children", None) or getattr(page_obj, "children", None) or []
    structure = getattr(page_obj, "structure", None)
    block_list: list[Any] = []
    if structure is not None and hasattr(page_obj, "get_block"):
        try:
            for bid in structure:
                blk = page_obj.get_block(bid)
                if blk is not None:
                    block_list.append(blk)
        except (IndexError, KeyError, TypeError):
            pass
    if not block_list and isinstance(children, list):
        block_list = [b for b in children if b is not None]
    for i, blk in enumerate(block_list):
        if getattr(blk, "removed", False):
            continue
        btype = getattr(blk, "block_type", None) or getattr(blk, "type", None)
        btype_str = str(btype).lower() if btype is not None else ""
        if "table" in btype_str:
            grid = _grid_from_block(blk, page_obj)
            if grid:
                tables.append(
                    TableCandidate(
                        table_id=getattr(blk, "id", None) and str(getattr(blk, "id", "")) or f"p{page_num}_t{len(tables)}",
                        grid=grid,
                        caption=getattr(blk, "caption", None) or "",
                    )
                )
        else:
            text = _text_from_block(blk, page_obj)
            if not text and getattr(blk, "structure", None) and hasattr(page_obj, "get_block"):
                for bid in getattr(blk, "structure", []) or []:
                    try:
                        sub = page_obj.get_block(bid)
                        if sub is not None:
                            text += _text_from_block(sub, None)
                    except (IndexError, KeyError, TypeError):
                        pass
            if text.strip():
                bid = getattr(blk, "id", None)
                block_id = str(bid) if bid is not None else f"p{page_num}_b{i}"
                text_blocks.append(
                    TextBlock(
                        block_id=block_id,
                        text=text.strip()[:50000],
                        role_hint="paragraph",
                    )
                )
    return DocumentPage(
        page=page_num,
        type="text",
        text_blocks=text_blocks,
        tables=tables,
        images=[],
    )


def load_document(pdf_path: str | Path, max_pages: int | None = None) -> Document:
    """
    Run Marker on the PDF and return the canonical Document (document.json contract).
    Uses Marker locally only; no API. Compatible with src/pipeline/locate/statements.py.
    Raises FileNotFoundError if file missing; raises RuntimeError if Marker fails.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
    except ImportError as e:
        raise RuntimeError(
            "Marker is required for ingestion. Install with: pip install marker-pdf"
        ) from e

    try:
        try:
            from marker.config.parser import ConfigParser
            config = ConfigParser({"output_format": "json"})
            converter = PdfConverter(
                config=config.generate_config_dict(),
                artifact_dict=create_model_dict(),
                processor_list=config.get_processors(),
                renderer=config.get_renderer(),
            )
        except (ImportError, AttributeError):
            converter = PdfConverter(artifact_dict=create_model_dict())

        filepath_to_use = str(path)
        if hasattr(converter, "filepath_to_str"):
            with converter.filepath_to_str(filepath_to_use) as temp_path:
                doc = converter.build_document(temp_path)
        else:
            doc = converter.build_document(filepath_to_use)

        pages_list = getattr(doc, "pages", None) or []
        if max_pages is not None:
            pages_list = pages_list[:max_pages]

        our_pages: list[DocumentPage] = []
        for i, p in enumerate(pages_list):
            # Always 1-based page numbers for pipeline (locator, statements_raw, etc.)
            page_num = i + 1
            our_pages.append(_normalize_page(page_num, p))

        meta = DocumentMeta(
            file_name=path.name,
            sha256=_sha256(path),
            pages=len(our_pages),
            pdf_type="mixed",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        return Document(meta=meta, pages=our_pages)
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.exception("Marker ingest failed: %s", e)
        raise RuntimeError(f"Marker ingestion failed: {e}") from e
