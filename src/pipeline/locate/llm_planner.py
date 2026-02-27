"""
Optional LLM planner: (1) detect statement pages for index_map; (2) rank candidate pages for locator.
Invalid response -> fallback deterministic; validators are final authority.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)


def detect_statement_pages(
    document: Any,
    *,
    max_digest_pages: int = 60,
    timeout: int = 60,
    _invoke_llm: Callable[[str, str], str] | None = None,
) -> dict[str, int]:
    """
    One LLM call: given a document digest (page, snippet, table header row), return
    the single page number for each of BS, IS, CF. Used to build index_map from LLM instead of regex.
    Returns e.g. {"BS": 70, "IS": 71, "CF": 72}. Missing or invalid keys -> {}.
    """
    from src.models.document import Document

    doc = document if isinstance(document, Document) else document
    page_by_num = {p.page: p for p in doc.pages}

    def _page_text(pg: Any) -> str:
        parts = [b.text for b in getattr(pg, "text_blocks", [])]
        for t in getattr(pg, "tables", []):
            grid = getattr(t, "grid", None) or []
            for row in grid:
                for cell in row:
                    if isinstance(cell, str) and cell.strip():
                        parts.append(cell.strip())
        return " ".join(parts)

    digest_entries = []
    for pg in doc.pages:
        tables = getattr(pg, "tables", []) or []
        if not tables:
            continue
        best_size = 0
        header_row: list[str] = []
        for t in tables:
            grid = getattr(t, "grid", None) or []
            if not grid:
                continue
            r, c = len(grid), len(grid[0]) if grid[0] else 0
            if c < 2:
                continue
            size = r * c
            if size > best_size:
                best_size = size
                header_row = [str(cell) for cell in grid[0]]
        if best_size == 0:
            continue
        text = _page_text(pg)[:350]
        digest_entries.append({
            "page": pg.page,
            "snippet": text,
            "table_cells": best_size,
            "header_row": header_row,
        })
    digest_entries.sort(key=lambda x: -x["table_cells"])
    digest_entries = digest_entries[:max_digest_pages]

    if not digest_entries:
        return {}

    prompt = (
        "Below is a digest of a financial report PDF. Each entry has: page number, a short text snippet, "
        "table size (cells), and the first row of the largest table on that page (header).\n\n"
        "Identify the SINGLE page number that contains:\n"
        "1. The MAIN Balance Sheet (statement of financial position: Equity and Liabilities, Assets).\n"
        "2. The MAIN Income Statement / P&L (Revenue, expenses, profit).\n"
        "3. The MAIN Cash Flow Statement (operating, investing, financing activities).\n\n"
        "Prefer pages whose header row and snippet clearly show the full statement (e.g. 'PARTICULARS', year columns, "
        "section titles like 'Equity and Liabilities' or 'Revenue from Operations'). "
        "Reject Table of Contents and small schedules.\n\n"
        "Return ONLY valid JSON with exactly these keys and integer page numbers:\n"
        '{"BS": <page>, "IS": <page>, "CF": <page>}\n\n'
        f"Digest ({len(digest_entries)} pages):\n"
        f"{json.dumps(digest_entries, ensure_ascii=False, indent=2)}"
    )

    system = (
        "You are a document analyst. You ONLY return a JSON object with keys BS, IS, CF and integer page numbers. "
        "No explanation, no markdown, just the JSON."
    )

    raw = ""
    if _invoke_llm:
        raw = _invoke_llm(system, prompt)
    else:
        raw = _call_llm_api(prompt, timeout, system_override=system)

    if not raw:
        return {}

    data = _parse_llm_json(raw)
    if not isinstance(data, dict):
        return {}

    out: dict[str, int] = {}
    valid_pages = {e["page"] for e in digest_entries}
    for key in ("BS", "IS", "CF"):
        v = data.get(key)
        if v is not None and int(v) in valid_pages:
            out[key] = int(v)
    return out


def rank_candidates(
    statement_type: str,
    candidates: list[dict[str, Any]],
    doc_meta: dict[str, Any],
    *,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int = 30,
    _invoke_llm: Callable[[str, list[dict], dict], str] | None = None,
) -> tuple[list[int], str, str]:
    """
    Return (ranked_page_numbers, mode_preference, rationale).
    If LLM not configured or invalid response, returns ([], "table", "fallback").
    """
    model = model or os.environ.get("LOCATOR_LLM_MODEL")
    api_key = api_key or os.environ.get("LOCATOR_LLM_API_KEY")
    timeout = int(os.environ.get("LOCATOR_LLM_TIMEOUT", str(timeout)))
    if not api_key or not model:
        logger.debug("LLM not configured: LOCATOR_LLM_MODEL or LOCATOR_LLM_API_KEY unset")
        return [], "table", "LLM_NOT_CONFIGURED"
    page_numbers = [c.get("page") for c in candidates if c.get("page") is not None]
    if not page_numbers:
        return [], "table", "no candidates"
    try:
        if _invoke_llm:
            raw = _invoke_llm(statement_type, candidates, doc_meta)
        else:
            prompt = build_planner_prompt(statement_type, candidates, doc_meta)
            raw = _call_llm_api(prompt, timeout)
        if not raw:
            return [], "table", "LLM_PLAN_INVALID"
        data = _parse_llm_json(raw)
        if not isinstance(data, dict):
            return [], "table", "LLM_PLAN_INVALID"
        ranked = data.get("ranked_pages")
        if isinstance(ranked, list):
            ranked = [int(p) for p in ranked if isinstance(p, (int, float))]
        else:
            ranked = []
        valid_ranked = [p for p in ranked if p in page_numbers]
        if not valid_ranked:
            valid_ranked = page_numbers
        mode = (data.get("mode_preference") or "table").strip().lower()
        if mode not in ("table", "ocr_rows"):
            mode = "table"
        rationale = str(data.get("rationale", ""))[:500]
        return valid_ranked, mode, rationale
    except json.JSONDecodeError as e:
        logger.warning("LLM plan invalid JSON: %s", e)
        return [], "table", "LLM_PLAN_INVALID"
    except Exception as e:
        logger.warning("LLM planner error: %s", e)
        return [], "table", "LLM_PLAN_INVALID"


def _parse_llm_json(raw: str) -> dict | None:
    """Parse JSON from LLM response; tolerate markdown code fences or leading/trailing text."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Try to extract from ```json ... ``` or ``` ... ```
    for marker in ("```json", "```"):
        if marker in s:
            start = s.find(marker) + len(marker)
            end = s.find("```", start)
            if end == -1:
                end = len(s)
            chunk = s[start:end].strip()
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                continue
    # Try first { to last }
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def build_planner_prompt(statement_type: str, candidates: list[dict[str, Any]], doc_meta: dict[str, Any] | None = None) -> str:
    """Build the user prompt for the LLM from statement type and candidate metadata."""
    doc_meta = doc_meta or {}
    total_pages = doc_meta.get("total_pages") or doc_meta.get("pages")
    total_line = f" (Document has {total_pages} pages.)" if total_pages else ""

    return (
        "Task: Pick the ONE page that contains the **main** "
        + _statement_label(statement_type)
        + ", then rank the rest by likelihood.\n\n"
        "Important:\n"
        "- The **main** statement is usually a **large table** (many rows and columns) with full section headers.\n"
        "- Schedules, notes, or excerpts are **smaller tables** (fewer rows) that repeat similar keywords.\n"
        "- Prefer the page whose table is **largest** (see largest_table_cells; main statement is usually 100+ cells).\n"
        "- Balance Sheet: look for 'Equity and Liabilities', 'Assets', or 'As at March 31' in a **big** table.\n"
        "- Income Statement: look for 'Revenue from Operations', 'Profit before tax' in a **big** table.\n"
        "- Cash Flow: look for 'Cash flow from operating activities' in a **big** table.\n"
        "- Reject Table of Contents and pages with only a tiny table (e.g. 3–5 rows).\n\n"
        f"Return ONLY valid JSON: "
        '{"ranked_pages": [best_page_first, ...], "mode_preference": "table", "rationale": "one sentence"}\n\n'
        "Use header_row (first row of largest table) to see what each table contains; prefer the page whose header_row has year columns or section titles (e.g. PARTICULARS, Equity and Liabilities, Revenue from Operations).\n\n"
        f"Candidates (page, snippet, header_row, table_shapes, largest_table_cells):\n"
        f"{json.dumps(candidates, ensure_ascii=False, indent=2)}\n"
        + (total_line if total_line else "")
    )


def _statement_label(statement_type: str) -> str:
    if statement_type == "BS":
        return "Balance Sheet"
    if statement_type == "IS":
        return "Income Statement / P&L"
    if statement_type == "CF":
        return "Cash Flow Statement"
    return statement_type


def _call_llm_api(prompt: str, timeout: int = 30, system_override: str | None = None) -> str:
    """
    Call Anthropic Messages API and return raw response text (expected to be JSON).
    Returns "" on failure. system_override: use this system message instead of default.
    """

    provider = (os.getenv("LOCATOR_LLM_PROVIDER") or "anthropic").lower()
    model = os.getenv("LOCATOR_LLM_MODEL")
    api_key = os.getenv("LOCATOR_LLM_API_KEY")
    max_tokens = int(os.getenv("LOCATOR_LLM_MAX_TOKENS") or "1024")
    temperature = float(os.getenv("LOCATOR_LLM_TEMPERATURE") or "0")

    if provider != "anthropic" or not model or not api_key:
        return ""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    system = system_override or (
        "You are a document navigation planner. You ONLY rank PDF page numbers. "
        "Pick the single best page first in ranked_pages (the full main statement, not a small schedule). "
        "Return ONLY valid JSON: ranked_pages (list, best first), mode_preference (\"table\"), rationale (one sentence)."
    )

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()

        # Anthropic returns content as a list of blocks. Prefer "text" blocks; fallback to "thinking".
        blocks = data.get("content", [])
        if not isinstance(blocks, list):
            return ""
        text_parts = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            # Text block (final answer)
            if b.get("type") == "text" and "text" in b:
                text_parts.append(b["text"])
            # Thinking block (extended thinking); sometimes the only content if model ran out of tokens
            elif b.get("type") == "thinking" and "thinking" in b and not text_parts:
                text_parts.append(b["thinking"])
        out = "\n".join(text_parts).strip()
        if not out:
            logger.debug("Anthropic response had no text/thinking content; keys=%s", list(data.keys()) if isinstance(data, dict) else None)
        return out

    except Exception as e:
        logger.debug("Anthropic API call failed: %s", e)
        return ""
