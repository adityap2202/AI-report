"""
Governance section extraction: directors, KMP, shareholding, corporate structure.
Planner ranks candidate pages; extractor pulls tables and paragraphs; reviewer structures output.
Deterministic extraction; LLM only structures/summarizes with evidence refs. Per FR-003; task T309.
"""
from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any, Callable

from src.models.document import Document, DocumentPage
from src.models.phase3 import (
    ExtractedSnippet,
    GovChangeEntry,
    GovResult,
    GovSectionEntry,
    TargetSpec,
)

logger = logging.getLogger(__name__)

GOV_KEYWORDS: dict[str, list[str]] = {
    "directors": ["directors' report", "board of directors", "appointment", "resignation", "director"],
    "kmp": ["key managerial personnel", "kmp", "company secretary", "cfo", "ceo"],
    "shareholding": ["shareholding pattern", "promoter", "public shareholding", "equity shareholding"],
    "corp_structure": ["corporate structure", "subsidiary", "holding company", "group structure"],
}


def _page_text(page: DocumentPage) -> str:
    return " ".join(b.text for b in page.text_blocks)


def _keyword_score(text: str, keywords: list[str]) -> int:
    lower = text.lower()
    return sum(1 for k in keywords if k in lower)


def _generate_gov_candidates(document: Document, topic: str, max_pages: int = 80) -> list[int]:
    keywords = GOV_KEYWORDS.get(topic, [topic])
    scored: list[tuple[int, int]] = []
    for page in document.pages[:max_pages]:
        text = _page_text(page)
        if not text.strip():
            continue
        s = _keyword_score(text, keywords)
        if s >= 1:
            scored.append((page.page, s))
    scored.sort(key=lambda x: -x[1])
    return [p for p, _ in scored]


def _extract_blocks_from_page(page: DocumentPage) -> list[ExtractedSnippet]:
    out: list[ExtractedSnippet] = []
    for i, b in enumerate(page.text_blocks):
        if not (b.text or "").strip():
            continue
        out.append(
            ExtractedSnippet(
                snippet_id=b.block_id or f"p{page.page}_b{i}",
                page_ref=f"p.{page.page}",
                text=(b.text or "").strip()[:3000],
                block_id=b.block_id or "",
            )
        )
    return out


def _extract_tables_from_page(page: DocumentPage) -> list[list[list[Any]]]:
    return [t.grid for t in page.tables if t.grid]


def extract_governance(
    document: Document,
    targets: list[TargetSpec],
    *,
    planner_rank_fn: Callable[[str, list[dict], Path | None], list[int]] | None = None,
    reviewer_fn: Callable[[str, list[dict], Path | None], dict] | None = None,
    cache_dir: Path | None = None,
    max_attempts: int = 6,
) -> GovResult:
    """
    For each governance target, find candidate pages, extract text/tables, optionally run reviewer.
    Returns GovResult with entries and missing. Data is from document only; reviewer only structures.
    """
    entries: list[GovSectionEntry] = []
    missing: list[dict[str, Any]] = []
    page_by_num = {p.page: p for p in document.pages}
    gov_targets = [t for t in targets if (t.topic or "") in GOV_KEYWORDS]

    for target in gov_targets:
        topic = target.topic or target.target_id
        candidates = _generate_gov_candidates(document, topic)
        if planner_rank_fn and candidates:
            try:
                meta = [{"page": p, "snippet": _page_text(page_by_num[p])[:400]} for p in candidates[:25] if p in page_by_num]
                if meta:
                    ranked = planner_rank_fn(topic, meta, cache_dir)
                    if ranked:
                        candidates = [p for p in ranked if p in set(candidates)]
            except Exception as e:
                logger.debug("Gov planner fallback: %s", e)

        all_blocks: list[ExtractedSnippet] = []
        all_tables: list[list[list[Any]]] = []
        page_refs: list[str] = []
        for pn in candidates[:max_attempts]:
            if pn not in page_by_num:
                continue
            page = page_by_num[pn]
            all_blocks.extend(_extract_blocks_from_page(page))
            all_tables.extend(_extract_tables_from_page(page))
            page_refs.append(f"p.{pn}")

        if not all_blocks and not all_tables:
            missing.append({
                "field": target.sheet_name,
                "searched_in": f"pages {candidates[:15]}",
                "reason": "NO_VALID_CANDIDATE",
            })
            continue

        # Reviewer structures into names/changes if available (only for directors/kmp)
        items: list[dict[str, Any]] = []
        changes: list[GovChangeEntry] = []
        review_kind = "gov_directors" if topic == "directors" else "gov_kmp" if topic == "kmp" else None
        blocks_for_reviewer = [{"snippet_id": b.snippet_id, "page_ref": b.page_ref, "text": b.text[:1500]} for b in all_blocks[:30]]
        if reviewer_fn and blocks_for_reviewer and review_kind:
            try:
                out = reviewer_fn(review_kind, blocks_for_reviewer, cache_dir)
                if isinstance(out.get("items"), list):
                    items = out["items"]
                if isinstance(out.get("changes"), list):
                    for c in out["changes"]:
                        if isinstance(c, dict) and c.get("page_ref") and c.get("snippet_id"):
                            changes.append(
                                GovChangeEntry(
                                    name=str(c.get("name", "")),
                                    action=str(c.get("action", "")),
                                    effective_date=str(c.get("effective_date", "")),
                                    reason_snippet=str(c.get("reason_snippet", "")),
                                    page_ref=str(c.get("page_ref", "")),
                                    snippet_id=str(c.get("snippet_id", "")),
                                )
                            )
            except Exception as e:
                logger.debug("Gov reviewer failed: %s", e)

        entries.append(
            GovSectionEntry(
                section_type=topic,
                sheet_name=target.sheet_name,
                items=items,
                changes=changes,
                narrative_blocks=all_blocks[:20],
                tables=all_tables[:5],
                page_refs=page_refs[:10],
            )
        )

    return GovResult(
        module="gov_sections",
        version="1.0",
        entries=entries,
        missing=missing,
    )
