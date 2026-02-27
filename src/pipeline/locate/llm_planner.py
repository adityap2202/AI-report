"""
Optional LLM planner: ranks candidate pages only. Does not extract numbers or validate.
Invalid response -> fallback deterministic; validators are final authority.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)


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
            prompt = build_planner_prompt(statement_type, candidates)
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


def build_planner_prompt(statement_type: str, candidates: list[dict[str, Any]]) -> str:
    """Build the user prompt for the LLM from statement type and candidate metadata."""
    return (
        "Task: Rank candidate PDF pages that may contain a financial statement.\n"
        f"Statement type: {statement_type}\n\n"
        "Rules:\n"
        "- Prefer pages with multi-column numeric tables and year headers.\n"
        "- Reject Table of Contents and narrative pages.\n"
        "- Balance Sheet: assets/liabilities/equity (often 'As at March 31').\n"
        "- Income Statement: revenue/expenses/profit.\n"
        "- Cash Flow: operating/investing/financing sections.\n\n"
        "Return ONLY valid JSON with exactly these keys:\n"
        '{ "ranked_pages": [..], "mode_preference": "table"|"ocr_rows", "rationale": "..." }\n\n'
        "Candidates JSON:\n"
        f"{json.dumps(candidates, ensure_ascii=False, indent=2)}\n"
    )


def _call_llm_api(prompt: str, timeout: int) -> str:
    """
    Call Anthropic Messages API and return raw response text (expected to be JSON).
    Returns "" on failure, which upstream treats as invalid and falls back deterministic.
    """

    provider = (os.getenv("LOCATOR_LLM_PROVIDER") or "").lower()
    model = os.getenv("LOCATOR_LLM_MODEL")
    api_key = os.getenv("LOCATOR_LLM_API_KEY")
    max_tokens = int(os.getenv("LOCATOR_LLM_MAX_TOKENS") or "700")
    temperature = float(os.getenv("LOCATOR_LLM_TEMPERATURE") or "0")

    if provider != "anthropic" or not model or not api_key:
        return ""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    system = (
        "You are a document navigation planner. "
        "You do NOT extract numbers. You do NOT write Excel. "
        "You ONLY rank candidate pages for the requested statement type. "
        "Return ONLY valid JSON with keys: ranked_pages, mode_preference, rationale."
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
