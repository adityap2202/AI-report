"""
MD&A section location and extraction: find pages, extract text blocks for interpreter.
Deterministic extraction; LLM used only in interpretations. Per FR-004; task T310.
"""
from __future__ import annotations

import re
import logging
from typing import Any, Callable

from pathlib import Path

from src.models.document import Document, DocumentPage
from src.models.phase3 import ExtractedSnippet, TargetSpec

logger = logging.getLogger(__name__)

MDNA_KEYWORDS = [
    "management discussion",
    "management's discussion",
    "business overview",
    "operational highlights",
    "md&a",
    "management discussion and analysis",
]


def _page_text(page: DocumentPage) -> str:
    return " ".join(b.text for b in page.text_blocks)


def _keyword_score(text: str, keywords: list[str]) -> int:
    lower = text.lower()
    return sum(1 for k in keywords if k in lower)


def _generate_mdna_candidates(document: Document, max_pages: int = 80) -> list[int]:
    scored: list[tuple[int, int]] = []
    for page in document.pages[:max_pages]:
        text = _page_text(page)
        if not text.strip():
            continue
        s = _keyword_score(text, MDNA_KEYWORDS)
        if s >= 1:
            scored.append((page.page, s))
    scored.sort(key=lambda x: -x[1])
    return [p for p, _ in scored]


def extract_mdna_blocks(
    document: Document,
    *,
    planner_rank_fn: Callable[[str, list[dict], Path | None], list[int]] | None = None,
    cache_dir: Path | None = None,
    max_attempts: int = 6,
    max_blocks_per_page: int = 15,
) -> list[ExtractedSnippet]:
    """
    Locate MD&A pages (optionally LLM-ranked), extract text blocks with snippet_id and page_ref.
    Returns list of ExtractedSnippet for use by interpretation engine. Data is from document only.
    """
    page_by_num = {p.page: p for p in document.pages}
    candidates = _generate_mdna_candidates(document)
    if planner_rank_fn and candidates:
        try:
            meta = [{"page": p, "snippet": _page_text(page_by_num[p])[:400]} for p in candidates[:25] if p in page_by_num]
            if meta:
                ranked = planner_rank_fn("mdna", meta, cache_dir)
                if ranked:
                    candidates = [p for p in ranked if p in set(candidates)]
        except Exception as e:
            logger.debug("MD&A planner fallback: %s", e)

    out: list[ExtractedSnippet] = []
    seen_ids: set[str] = set()
    for pn in candidates[:max_attempts]:
        if pn not in page_by_num:
            continue
        page = page_by_num[pn]
        for i, b in enumerate(page.text_blocks):
            if not (b.text or "").strip():
                continue
            sid = b.block_id or f"p{pn}_b{i}"
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            out.append(
                ExtractedSnippet(
                    snippet_id=sid,
                    page_ref=f"p.{pn}",
                    text=(b.text or "").strip()[:3000],
                    block_id=b.block_id or "",
                )
            )
            if len(out) >= max_blocks_per_page * max_attempts:
                break
        if len(out) >= max_blocks_per_page * max_attempts:
            break
    return out
