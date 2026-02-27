# Implementation Plan: Phase 3 — Full Databook Population with LLM Planner/Reviewer

**Branch**: `003-full-databook`  
**Date**: 2026-02-26  
**Spec**: `specs/003-full-databook/spec.md`

---

## Summary

Add Phase 3 pipeline steps to populate the complete workbook using:
- Marker-based document reconstruction (preferred)
- LLM planner for navigation and candidate ranking
- deterministic extraction of tables and text blocks
- LLM reviewer/interpreter for semantic checking and interpretive notes
- evidence pack artifacts for traceability

Phase 2 statement extraction remains as-is and is reused.

---

## Architecture

Current:
- ingest → index_map → statement locator → statements_raw → workbook writer

Phase 3 extends to:
- target inventory (from template_map)
- notes locator + extraction
- governance extraction
- MD&A extraction + interpretations
- workbook writer extended for these targets

---

## New Modules

### 1) Target Inventory
Create:
- `src/pipeline/targets/inventory.py`

Responsibilities:
- load template_map
- generate list of targets (notes/governance/MD&A)
- provide validation rules per target

---

### 2) Notes Locator
Create:
- `src/pipeline/locate/notes.py`

API:
- `locate_notes(document, targets, strategy="llm") -> NotesLocatorResult`

Internals:
- candidate generation
- LLM ranking
- deterministic validation
- table selection

Artifacts:
- notes_locator.json

---

### 3) Notes Extractor
Create:
- `src/pipeline/extract/notes_raw.py`

API:
- `extract_notes(document, notes_locator_result) -> NotesRawResult`

Output:
- extracted tables + narrative blocks per target

Artifact:
- notes_raw.json

---

### 4) Governance Extractor
Create:
- `src/pipeline/extract/gov_sections.py`

API:
- `extract_governance(document, targets, planner, reviewer) -> GovResult`

Output:
- extracted paragraphs/tables
- structured director/KMP change objects

Artifact:
- gov_sections.json

---

### 5) Interpretation Engine (LLM reviewer)
Create:
- `src/pipeline/interpret/interpretations.py`

API:
- `generate_interpretations(extracted_blocks, mode) -> InterpretationResult`

Modes:
- mdna
- note_summary (Revenue/PPE/Leases/RPT/Segment)

Artifact:
- interpretations.json

---

### 6) LLM Agent Wrapper
Create:
- `src/llm/agent.py`

Responsibilities:
- provide two functions:
  - `planner_rank(...)`
  - `reviewer_summarize(...)`
- provider: anthropic (Claude Haiku 4.5)
- strict JSON output parsing
- caching of responses per run

---

## Pipeline Integration

Modify:
- `src/main.py` (or pipeline runner)

Add Phase 3 steps after Phase 2 statements extraction:

1. load template_map + generate targets
2. locate notes (LLM strategy default)
3. extract notes tables/text
4. locate/extract governance sections
5. extract MD&A text blocks
6. run reviewer interpretations
7. write everything to workbook

Ensure:
- failures are per-target, not whole-run
- missing entries captured

---

## Workbook Writing

Modify or extend existing writer:
- `src/pipeline/write/workbook_writer.py`

Add support for:
- appending multiple tables under headers
- writing narrative blocks into configured regions
- writing interpretation bullets with evidence refs
- evidence columns: page_ref, table_id, confidence

---

## Config and CLI

Add flags:
- `--phase 2|3` (default 3)
- `--llm-mode off|planner_only|full` (default full)
- `--llm-cache true|false` (default true)
- `--max-target-attempts N` (default 6)

Env vars (already used):
- `LOCATOR_LLM_MODEL`
- `LOCATOR_LLM_API_KEY`
- `LOCATOR_LLM_TIMEOUT`

---

## Testing Strategy

Unit tests:
- target inventory from template_map
- notes locator candidate generation
- LLM planner JSON parsing (stub)
- reviewer interpretation JSON parsing (stub)
- workbook writer places outputs in correct sheets/regions

Integration test (fixture doc model):
- one note extraction writes to correct tab
- mdna interpretation writes bullets with page refs
- missing target produces missing entry

No real LLM calls in CI:
- inject stub planner/reviewer

---

## Rollout / Risk

Risks:
- interpretations hallucination
Mitigation:
- require evidence refs per bullet
- reject interpretations without refs

Risk:
- varying note names across companies
Mitigation:
- synonyms dictionary per target
- LLM planner widening search

Invariant:
For each required target:
- writes > 0 OR missing > 0