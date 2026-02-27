"""
LLM agent: planner_rank (rank candidate pages) and reviewer_interpret (structured interpretations with evidence).
Uses Anthropic Messages API. Never generates numbers; only ranks and summarizes extracted text.
Per plan.md T303, T304.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _parse_llm_json(raw: str) -> dict | list | None:
    """Parse JSON from LLM response; tolerate markdown code fences or leading/trailing text."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
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
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except json.JSONDecodeError:
            pass
    start = s.find("[")
    end = s.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _cache_key(prefix: str, payload: dict | list) -> str:
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return f"{prefix}_{h}.json"


def _call_anthropic(
    system: str,
    user_content: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int = 60,
    max_tokens: int = 4096,
) -> str:
    """Call Anthropic Messages API. Return raw response text or '' on failure."""
    model = model or os.environ.get("LOCATOR_LLM_MODEL") or DEFAULT_MODEL
    api_key = api_key or os.environ.get("LOCATOR_LLM_API_KEY")
    timeout = int(os.environ.get("LOCATOR_LLM_TIMEOUT", str(timeout)))
    if not api_key:
        logger.debug("LOCATOR_LLM_API_KEY not set")
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
        "messages": [{"role": "user", "content": user_content}],
    }
    max_retries = 3
    base_delay = 10
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(url, headers=headers, json=payload)
                if r.status_code == 429 and attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    retry_after = r.headers.get("retry-after")
                    if retry_after and retry_after.isdigit():
                        delay = int(retry_after)
                    logger.warning("Rate limited (429), retrying in %ds (attempt %d/%d)", delay, attempt + 1, max_retries)
                    time.sleep(delay)
                    continue
                r.raise_for_status()
                data = r.json()
            blocks = data.get("content", [])
            if not isinstance(blocks, list):
                return ""
            text_parts = []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and "text" in b:
                    text_parts.append(b["text"])
                elif b.get("type") == "thinking" and "thinking" in b and not text_parts:
                    text_parts.append(b["thinking"])
            return "\n".join(text_parts).strip()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                retry_after = e.response.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    delay = int(retry_after)
                logger.warning("Rate limited (429), retrying in %ds (attempt %d/%d)", delay, attempt + 1, max_retries)
                time.sleep(delay)
                continue
            logger.warning("Anthropic API call failed: %s", e)
            return ""
        except Exception as e:
            logger.warning("Anthropic API call failed: %s", e)
            return ""
    return ""


def planner_rank(
    target_type: str,
    candidates: list[dict[str, Any]],
    *,
    cache_dir: Path | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int = 60,
    _invoke: Callable[[str, str], str] | None = None,
) -> tuple[list[int], str, str]:
    """
    Rank candidate pages for a target (note, governance, mdna).
    Returns (ranked_page_numbers, mode_preference, rationale).
    LLM does NOT extract numbers; only ranks where to look.
    """
    page_numbers = [c.get("page") for c in candidates if c.get("page") is not None]
    if not page_numbers:
        return [], "table", "no candidates"

    key = _cache_key("planner", {"target": target_type, "candidates": candidates})
    if cache_dir:
        cache_file = cache_dir / key
        if cache_file.is_file():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                ranked = data.get("ranked_pages", [])
                ranked = [int(p) for p in ranked if isinstance(p, (int, float))]
                valid = [p for p in ranked if p in page_numbers]
                if valid:
                    return valid, data.get("mode_preference", "table"), data.get("rationale", "cached")
            except Exception as e:
                logger.debug("Cache read failed: %s", e)

    system = (
        "You are a document navigation planner. You do NOT extract numbers or create data. "
        "You ONLY rank candidate PDF pages for the requested section type. "
        "Return ONLY valid JSON with keys: ranked_pages (list of page numbers), mode_preference (table or narrative), rationale (short string)."
    )
    user = (
        f"Target type: {target_type}\n\n"
        "Rank these candidate pages by likelihood of containing relevant content. "
        "Prefer pages with tables for note targets; narrative for MD&A/governance.\n\n"
        f"Candidates:\n{json.dumps(candidates, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON only: {\"ranked_pages\": [...], \"mode_preference\": \"table\"|\"narrative\", \"rationale\": \"...\"}"
    )
    raw = _invoke(system, user) if _invoke else _call_anthropic(system, user, model=model, api_key=api_key, timeout=timeout)
    if not raw:
        return list(page_numbers), "table", "LLM_NOT_CONFIGURED"
    data = _parse_llm_json(raw)
    if not isinstance(data, dict):
        return list(page_numbers), "table", "LLM_PLAN_INVALID"
    ranked = data.get("ranked_pages")
    if isinstance(ranked, list):
        ranked = [int(p) for p in ranked if isinstance(p, (int, float))]
    else:
        ranked = []
    valid = [p for p in ranked if p in page_numbers]
    if not valid:
        valid = page_numbers
    mode = (data.get("mode_preference") or "table").strip().lower()
    if mode not in ("table", "narrative"):
        mode = "table"
    rationale = str(data.get("rationale", ""))[:500]
    if cache_dir:
        try:
            cache_file = cache_dir / key
            cache_file.write_text(
                json.dumps({"ranked_pages": valid, "mode_preference": mode, "rationale": rationale}, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("Cache write failed: %s", e)
    return valid, mode, rationale


def reviewer_interpret(
    kind: str,
    extracted_blocks: list[dict[str, Any]],
    *,
    cache_dir: Path | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int = 90,
    _invoke: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """
    Generate structured interpretation (mdna or note_summary) from extracted text blocks.
    Every bullet MUST include page_ref and snippet_id (evidence). Reject outputs without refs.
    LLM must NOT invent numbers; only summarize/interpret the provided text.
    """
    if not extracted_blocks:
        return _empty_reviewer_output(kind)

    key = _cache_key("reviewer", {"kind": kind, "blocks": extracted_blocks})
    if cache_dir:
        cache_file = cache_dir / key
        if cache_file.is_file():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if _has_evidence_refs(data, kind):
                    return data
            except Exception as e:
                logger.debug("Cache read failed: %s", e)

    if kind == "mdna":
        system = (
            "You are a reviewer summarizing Management Discussion and Analysis. "
            "You must ONLY summarize or interpret the provided extracted text. Do NOT invent numbers or facts. "
            "Every bullet MUST include page_ref and snippet_id from the provided blocks (evidence). "
            "Return ONLY valid JSON with: revenue_drivers, margin_drivers, kpis, outlook, risks. "
            "Each is a list of objects: {\"text\": \"...\", \"page_ref\": \"p.N\", \"snippet_id\": \"...\"}. "
            "If no evidence for a section, use empty list. Never add bullets without page_ref and snippet_id."
        )
        user = (
            "Extracted text blocks (use their page_ref and snippet_id in your output):\n\n"
            f"{json.dumps(extracted_blocks, ensure_ascii=False, indent=2)}\n\n"
            "Return JSON only with keys: revenue_drivers, margin_drivers, kpis, outlook, risks."
        )
    elif kind.startswith("gov_"):
        system = (
            "You are a reviewer extracting governance information (directors or KMP). "
            "You must ONLY use the provided extracted text. Do NOT invent names or dates. "
            "Return ONLY valid JSON with: items (list of {\"name\": \"...\", \"page_ref\": \"p.N\", \"snippet_id\": \"...\"}), "
            "changes (list of {\"name\", \"action\": \"appointed\"|\"resigned\", \"effective_date\", \"reason_snippet\", \"page_ref\", \"snippet_id\"}). "
            "Every entry MUST include page_ref and snippet_id from the blocks. Omit if no evidence."
        )
        user = (
            "Extracted blocks:\n\n"
            f"{json.dumps(extracted_blocks, ensure_ascii=False, indent=2)}\n\n"
            "Return JSON only with keys: items, changes."
        )
    else:
        system = (
            "You are a reviewer summarizing an accounting note. "
            "You must ONLY summarize the provided text. Do NOT invent numbers. "
            "Every bullet MUST include page_ref and snippet_id (evidence). "
            "Return ONLY valid JSON with: key_policies, key_judgements, unusual_movements. "
            "Each is a list of objects: {\"text\": \"...\", \"page_ref\": \"p.N\", \"snippet_id\": \"...\"}. "
            "Never add bullets without page_ref and snippet_id."
        )
        user = (
            "Extracted blocks:\n\n"
            f"{json.dumps(extracted_blocks, ensure_ascii=False, indent=2)}\n\n"
            "Return JSON only with keys: key_policies, key_judgements, unusual_movements."
        )

    raw = _invoke(system, user) if _invoke else _call_anthropic(system, user, model=model, api_key=api_key, timeout=timeout)
    if not raw:
        return _empty_reviewer_output(kind)
    data = _parse_llm_json(raw)
    if not isinstance(data, dict):
        return _empty_reviewer_output(kind)
    # Enforce evidence: drop any bullet missing page_ref or snippet_id
    data = _strip_bullets_without_evidence(data, kind)
    if cache_dir:
        try:
            cache_file = cache_dir / key
            cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("Cache write failed: %s", e)
    return data


def _empty_reviewer_output(kind: str) -> dict[str, Any]:
    if kind == "mdna":
        return {
            "revenue_drivers": [],
            "margin_drivers": [],
            "kpis": [],
            "outlook": [],
            "risks": [],
        }
    if kind.startswith("gov_"):
        return {"items": [], "changes": []}
    return {"key_policies": [], "key_judgements": [], "unusual_movements": []}


def _has_evidence_refs(data: dict, kind: str) -> bool:
    """Check that lists contain items with page_ref and snippet_id (or allow empty)."""
    if kind == "mdna":
        keys = ["revenue_drivers", "margin_drivers", "kpis", "outlook", "risks"]
    elif kind.startswith("gov_"):
        for c in data.get("changes", []):
            if isinstance(c, dict) and (not c.get("page_ref") or not c.get("snippet_id")):
                return False
        return True
    else:
        keys = ["key_policies", "key_judgements", "unusual_movements"]
    for k in keys:
        items = data.get(k)
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict) and (not it.get("page_ref") or not it.get("snippet_id")):
                return False
    return True


def _strip_bullets_without_evidence(data: dict, kind: str) -> dict:
    """Remove any bullet that does not have both page_ref and snippet_id."""
    if kind == "mdna":
        keys = ["revenue_drivers", "margin_drivers", "kpis", "outlook", "risks"]
    elif kind.startswith("gov_"):
        out = dict(data)
        out["changes"] = [c for c in out.get("changes", []) if isinstance(c, dict) and c.get("page_ref") and c.get("snippet_id")]
        return out
    else:
        keys = ["key_policies", "key_judgements", "unusual_movements"]
    out = {}
    for k, v in data.items():
        if k not in keys:
            out[k] = v
            continue
        if not isinstance(v, list):
            out[k] = []
            continue
        out[k] = [it for it in v if isinstance(it, dict) and it.get("page_ref") and it.get("snippet_id")]
    return out
