"""
Statement finder agent: uses grep over the document + LLM to find exact BS/IS/CF pages.
Agent has a search_document tool (pattern + next N lines); it runs searches and returns
the exact page numbers for the main statements so the pipeline can populate Excel.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.models.document import Document, DocumentPage

logger = logging.getLogger(__name__)

CONTEXT_LINES_AFTER = 10
MAX_AGENT_STEPS = 15


def _page_lines(page: DocumentPage) -> list[str]:
    """Get page content as lines (each table row = one line; then text_blocks split by newline)."""
    lines: list[str] = []
    for t in page.tables:
        if not t.grid:
            continue
        for row in t.grid:
            cell_strs = [str(c).strip() for c in row if c]
            if cell_strs:
                lines.append(" | ".join(cell_strs))
    for b in page.text_blocks:
        if b.text:
            for line in b.text.splitlines():
                if line.strip():
                    lines.append(line.strip())
    return lines


def grep_document(
    document: Document,
    pattern: str,
    context_after: int = CONTEXT_LINES_AFTER,
) -> list[dict[str, Any]]:
    """
    Search all pages for pattern (case-insensitive). For each match return
    page number, the matching line, and the next context_after lines.
    """
    hits = []
    pat = re.compile(re.escape(pattern), re.I)
    for page in document.pages:
        lines = _page_lines(page)
        for i, line in enumerate(lines):
            if pat.search(line):
                context = lines[i + 1 : i + 1 + context_after] if i + 1 < len(lines) else []
                hits.append({
                    "page": page.page,
                    "match_line": line[:500],
                    "context_after": context[:context_after],
                })
    return hits


def _format_hits(hits: list[dict[str, Any]], max_hits: int = 20) -> str:
    """Format grep hits for the LLM."""
    out = []
    for i, h in enumerate(hits[:max_hits]):
        out.append(
            f"  Page {h['page']}: \"{h['match_line'][:200]}...\" "
            if len(h["match_line"]) > 200
            else f"  Page {h['page']}: \"{h['match_line']}\""
        )
        ctx = h.get("context_after") or []
        if ctx:
            out.append("    Next lines: " + " | ".join(c[:80] for c in ctx[:5]))
    if len(hits) > max_hits:
        out.append(f"  ... and {len(hits) - max_hits} more hits.")
    return "\n".join(out) if out else "  (no matches)"


def _call_llm(system: str, user: str, timeout: int = 90) -> str:
    """Call Anthropic API; same env as llm_planner."""
    import os
    import httpx

    provider = (os.getenv("LOCATOR_LLM_PROVIDER") or "anthropic").lower()
    model = os.getenv("LOCATOR_LLM_MODEL")
    api_key = os.getenv("LOCATOR_LLM_API_KEY")
    max_tokens = int(os.getenv("LOCATOR_LLM_MAX_TOKENS") or "2048")
    if provider != "anthropic" or not model or not api_key:
        return ""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        blocks = data.get("content", [])
        if not isinstance(blocks, list):
            return ""
        text_parts = []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text" and "text" in b:
                text_parts.append(b["text"])
        return "\n".join(text_parts).strip()
    except Exception as e:
        logger.debug("Statement finder agent LLM call failed: %s", e)
        return ""


def _parse_result(text: str) -> dict[str, int] | None:
    """Extract RESULT {...} from agent response."""
    if not text:
        return None
    # Look for RESULT followed by JSON
    for marker in ("RESULT", "Result", "result"):
        idx = text.find(marker)
        if idx == -1:
            continue
        rest = text[idx + len(marker) :].strip()
        rest = rest.lstrip(":").strip()
        # Find first { and last }
        start = rest.find("{")
        end = rest.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(rest[start : end + 1])
                if isinstance(data, dict):
                    out = {}
                    for k in ("BS", "IS", "CF"):
                        v = data.get(k)
                        if v is not None:
                            try:
                                out[k] = int(v)
                            except (TypeError, ValueError):
                                pass
                    return out if out else None
            except json.JSONDecodeError:
                pass
    return None


def _parse_search(text: str) -> str | None:
    """Extract search phrase from agent response (SEARCH <phrase>)."""
    if not text:
        return None
    for marker in ("SEARCH", "Search", "search"):
        idx = text.find(marker)
        if idx == -1:
            continue
        rest = text[idx + len(marker) :].strip().lstrip(":").strip()
        # Take first line or first 80 chars so "balance sheet" is kept
        if rest:
            first_line = rest.split("\n")[0].strip()
            return first_line[:80] if first_line else None
    return None


def detect_statement_pages_grep_agent(
    document: Document,
    *,
    max_steps: int = MAX_AGENT_STEPS,
    timeout: int = 90,
    _invoke_llm: Any = None,
) -> dict[str, int]:
    """
    Run the statement-finder agent: it can search the document (grep + next N lines)
    and must return the exact page numbers for BS, IS, CF so Excel can be populated.
    """
    valid_pages = {p.page for p in document.pages}
    invoke = _invoke_llm or (lambda sys, usr: _call_llm(sys, usr, timeout))

    system = (
        "You are a statement finder. Your job is to identify the EXACT page number that contains "
        "the main Balance Sheet, the main Income Statement (P&L), and the main Cash Flow Statement "
        "in a financial report PDF.\n\n"
        "You have a single tool: search_document. When you run a search, you receive every page and line "
        "that matches the phrase, plus the next 10 lines after each match. Use this to tell the difference "
        "between (1) the actual statement table (you will see section headers like 'Equity and Liabilities', "
        "'Revenue from Operations', year columns) and (2) a Table of Contents line or a note reference.\n\n"
        "To request a search, reply with exactly: SEARCH <phrase>\n"
        "Example: SEARCH balance sheet\n\n"
        "When you have identified the single page for each statement type, reply with exactly:\n"
        "RESULT {\"BS\": <page>, \"IS\": <page>, \"CF\": <page>}\n"
        "Use only the page numbers that appeared in the search results. No explanation after RESULT."
    )

    user = (
        f"The document has {document.meta.pages} pages. "
        "Run searches to find the main Balance Sheet, Income Statement, and Cash Flow Statement. "
        "Start by searching for 'balance sheet' or 'equity and liabilities', then 'income statement' or 'revenue from operations', "
        "then 'cash flow'. Use the match line and next lines to pick the page with the full statement table. "
        "When done, output RESULT with the three page numbers."
    )

    conversation = [user]
    for step in range(max_steps):
        user_msg = "\n\n".join(conversation)
        raw = invoke(system, user_msg)
        if not raw:
            break

        result = _parse_result(raw)
        if result:
            return {k: v for k, v in result.items() if v in valid_pages}

        pattern = _parse_search(raw)
        if pattern:
            hits = grep_document(document, pattern, context_after=CONTEXT_LINES_AFTER)
            blob = _format_hits(hits)
            conversation.append(
                f"[Your last message asked to search for \"{pattern}\".]\n\nSearch results for \"{pattern}\":\n{blob}\n\n"
                "Use these results to decide. Run another SEARCH if needed, or output RESULT {\"BS\": p, \"IS\": p, \"CF\": p} when ready."
            )
            continue

        # No RESULT and no SEARCH; prompt again with hint
        conversation.append(
            f"[Assistant replied: {raw[:300]}...]\n\n"
            "Reply with either SEARCH <phrase> or RESULT {\"BS\": page, \"IS\": page, \"CF\": page}."
        )

    return {}
