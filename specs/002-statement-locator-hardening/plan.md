# Implementation Plan: Intelligent Statement Locator

Branch: 002-statement-locator  
Date: 2026-02-26  
Spec: specs/002-statement-locator/spec.md

---

## Architecture Change

Current pipeline:
index_map → statements_raw

New pipeline:
index_map → StatementLocator → statements_raw

StatementLocator determines the correct statement pages before extraction.

---

## New Modules

### Core Locator

Create:
src/pipeline/locate/statements.py

Public API:
locate_statements(document, index_map, scope, strategy="deterministic") -> LocatorResult

---

### LLM Planner

Create:
src/pipeline/locate/llm_planner.py

Function:
rank_candidates(statement_type, candidates, config) -> PlannerDecision

PlannerDecision fields:
- ranked_pages: list[int]
- mode_preference: str
- rationale: str
- valid: bool

---

## Subsystems

Candidate Builder:
- index_map seed
- keyword scan
- numeric density pages

TOC Detector:
Rejects table-of-contents pages.

Validator:
Checks:
- column count
- anchors
- year headers
- numeric density

Table Selector:
Chooses correct table on page.

OCR Row Reconstructor:
Builds grid when no table objects exist.

Planner (optional):
Ranks candidates only.

---

## Integration Changes

Modify:
src/pipeline/extract/statements_raw.py

Replace index_map usage with locator result:

table mode → extract table_id  
ocr_rows mode → write reconstructed grid  
locator failure → emit missing

---

## CLI

Add flag:
--locator-strategy deterministic|llm

Default deterministic.

---

## Configuration

Environment variables:

LOCATOR_LLM_MODEL  
LOCATOR_LLM_API_KEY  
LOCATOR_LLM_TIMEOUT

If unset → deterministic fallback.

---

## Output Changes

Add:
runs/<id>/evidence_pack/extractions/statements_locator.json

Update statements_raw.json to include:
- locator page_range
- selected table_id
- mode
- confidence

---

## Safety Rules

Validators gate all writes.

If locator fails:
- do not write Excel
- emit missing

LLM cannot bypass validators.

---

## Testing Strategy

Unit tests:
1. TOC false positive
2. multi-table page
3. OCR-only statement
4. invalid table rejected
5. missing emitted

LLM tests use stub planner (no real API calls).

---

## Risk Mitigation

Risk: scoring thresholds incorrect  
Mitigation:
- configurable thresholds
- trace logging

Invariant:
writes > 0 OR missing > 0 for each statement

Silent success is disallowed.