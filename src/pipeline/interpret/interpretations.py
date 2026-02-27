"""
Generate structured interpretations (MD&A, note summaries) via LLM reviewer.
All bullets must cite page_ref + snippet_id; reject outputs without refs. Per FR-004, FR-005; tasks T311, T312.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from src.models.phase3 import (
    InterpretationBullet,
    InterpretationResult,
    MDNAInterpretation,
    NoteSummaryInterpretation,
    ExtractedSnippet,
)

logger = logging.getLogger(__name__)


def _to_bullet(d: dict) -> InterpretationBullet:
    return InterpretationBullet(
        text=str(d.get("text", "")),
        page_ref=str(d.get("page_ref", "")),
        snippet_id=str(d.get("snippet_id", "")),
    )


def generate_interpretations(
    mdna_blocks: list[ExtractedSnippet],
    note_entries: list[dict[str, Any]] | None = None,
    *,
    mode: str = "full",  # mdna_only | note_summary_only | full
    reviewer_fn: Callable[[str, list[dict], Path | None], dict] | None = None,
    cache_dir: Path | None = None,
) -> InterpretationResult:
    """
    Call LLM reviewer for mdna and/or note summaries. Only bullets with page_ref and snippet_id are kept.
    Extracted data is from document; LLM only summarizes/interprets with evidence.
    """
    result = InterpretationResult(module="interpretations", version="1.0")
    blocks_for_llm = [{"snippet_id": b.snippet_id, "page_ref": b.page_ref, "text": b.text[:2000]} for b in mdna_blocks]

    if mode in ("full", "mdna_only") and blocks_for_llm and reviewer_fn:
        try:
            raw = reviewer_fn("mdna", blocks_for_llm, cache_dir)
            result.mdna = MDNAInterpretation(
                revenue_drivers=[_to_bullet(x) for x in raw.get("revenue_drivers", []) if x.get("page_ref") and x.get("snippet_id")],
                margin_drivers=[_to_bullet(x) for x in raw.get("margin_drivers", []) if x.get("page_ref") and x.get("snippet_id")],
                kpis=[_to_bullet(x) for x in raw.get("kpis", []) if x.get("page_ref") and x.get("snippet_id")],
                outlook=[_to_bullet(x) for x in raw.get("outlook", []) if x.get("page_ref") and x.get("snippet_id")],
                risks=[_to_bullet(x) for x in raw.get("risks", []) if x.get("page_ref") and x.get("snippet_id")],
            )
        except Exception as e:
            logger.warning("MD&A interpretation failed: %s", e)
            result.mdna = MDNAInterpretation()

    if mode in ("full", "note_summary_only") and note_entries and reviewer_fn:
        for entry in note_entries:
            target_id = entry.get("target_id") or entry.get("sheet_name", "")
            snippets = entry.get("narrative_snippets", [])
            blocks = [{"snippet_id": s.get("snippet_id", ""), "page_ref": s.get("page_ref", ""), "text": (s.get("text") or "")[:1500]} for s in snippets]
            if not blocks:
                continue
            try:
                raw = reviewer_fn("note_summary", blocks, cache_dir)
                result.note_summaries[target_id] = NoteSummaryInterpretation(
                    key_policies=[_to_bullet(x) for x in raw.get("key_policies", []) if x.get("page_ref") and x.get("snippet_id")],
                    key_judgements=[_to_bullet(x) for x in raw.get("key_judgements", []) if x.get("page_ref") and x.get("snippet_id")],
                    unusual_movements=[_to_bullet(x) for x in raw.get("unusual_movements", []) if x.get("page_ref") and x.get("snippet_id")],
                )
            except Exception as e:
                logger.debug("Note summary for %s failed: %s", target_id, e)

    return result
