---
description: "Statement locator hardening (BS/IS/CF) with TOC rejection, scanned fallback, and optional LLM planner ranking."
---

# Tasks: Intelligent Statement Locator (BS/IS/CF)

**Input**: `specs/002-statement-locator/spec.md`, `plan.md`  
**Dependencies**: Phase 2 exists (statements_raw extraction + excel writing + evidence pack)  
**Scope**: Only CF BS, CF IS, CF CFS. No notes.

---

## Phase 1: Data model + scaffolding

- [ ] T201 Add locator model types in `src/models/` (or extend existing models):
  - `LocatorAttempt`:
    - statement_type (BS/IS/CF)
    - candidate_source (index_map|keyword_scan|numeric_density)
    - page_start/page_end OR page
    - is_toc_like (bool)
    - table_candidates: list[{table_id, rows, cols, caption?}]
    - signals: {numeric_density, anchor_hits, year_header_hits}
    - score (float)
    - rejected_reason (nullable)
  - `LocatorSelection`:
    - statement_type
    - selected_mode (table|ocr_rows)
    - selected_page_start/page_end
    - selected_table_id (nullable)
    - selected_grid_ref (nullable; if ocr_rows)
    - confidence (High|Med|Low)
  - `LocatorResult`:
    - selections: dict[statement_type -> LocatorSelection or null]
    - attempts: list[LocatorAttempt]
    - missing: list[MissingEntry]
    - meta: {strategy, max_attempts, thresholds}
  - Ensure JSON-serializable.

- [ ] T202 Add writer utility:
  - write `statements_locator.json` into `runs/<id>/evidence_pack/extractions/`
  - ensure file is always written (even if only missing).

---

## Phase 2: Implement StatementLocator (deterministic core)

- [ ] T203 Implement `src/pipeline/locate/statements.py` with public API:
  - `locate_statements(document, index_map, scope, strategy="deterministic") -> LocatorResult`

- [ ] T204 Candidate generation per statement_type:
  - Seed 1: index_map candidate ranges (even if wrong)
  - Seed 2: keyword scan (caption synonyms) across page text snippets
  - Seed 3: numeric density pages (top K pages with high digit/₹ density)
  - Merge/dedupe, keep top N candidates (configurable, default 30)

- [ ] T205 TOC detection `is_toc_like(page)`:
  - dotted leaders `.....`
  - "Contents" / "Table of Contents"
  - many lines ending in page numbers
  - produce `toc_score` 0..1 and bool threshold
  - reject TOC-like candidates early unless anchors + numeric density are strong

- [ ] T206 Scoring `score_candidate(statement_type, candidate)`:
  - signals:
    - numeric_density
    - anchor_hits for statement_type
    - year_header_hits (FY2024, 2023-24, "As at March 31")
    - table_shape bonus (max cols, max rows)
  - output:
    - score float
    - rejection reason (nullable)

- [ ] T207 Validation gates:
  - If best table has `cols < 3` => reject with `TABLE_TOO_FEW_COLUMNS` unless OCR reconstruction yields >=3
  - Require at least 2 of:
    - year header hit
    - anchor hit
    - numeric_density >= threshold
    - table cols >= 3
  - Never accept candidate with `toc_score` above threshold unless it passes anchors+numeric hard check.

- [ ] T208 Iterative search loop:
  - For each statement_type:
    - try candidates in descending score order
    - validate
    - if pass => select and stop for that statement
    - else continue
  - Stop after `max_attempts` per statement (default 8)
  - Record every attempt into trace.

---

## Phase 3: OCR-row reconstruction fallback

- [ ] T209 Implement `src/pipeline/locate/ocr_rows.py`:
  - input: page text_blocks (OCR output) for a page range
  - output: reconstructed grid (rows x cols) OR failure
  - required:
    - detect lines with >=2 numeric tokens
    - group numeric tokens into consistent columns (bbox if available; else whitespace heuristics)
    - ensure final grid has `cols >= 3` (line item + 2 years)
  - if fail => return reason `OCR_RECONSTRUCTION_FAILED`

- [ ] T210 Integrate fallback into locator:
  - if no usable tables found in candidate range:
    - attempt OCR-row reconstruction on that range
    - if grid cols >=3 => select mode `ocr_rows`, confidence Med
    - else reject candidate with `OCR_RECONSTRUCTION_FAILED`

---

## Phase 4: Optional LLM planner strategy (ranking only)

- [ ] T211 Add `src/pipeline/locate/llm_planner.py` with strict interface:
  - `rank_candidates(statement_type, candidates, doc_meta) -> RankedPages`
  - The planner sees only metadata (no full document text):
    - page numbers
    - short snippet (<=400 chars)
    - toc_score, numeric_density
    - table shapes list
    - anchor/year hits
  - Output must be strict JSON:
    - `statement_type`
    - `ranked_pages` (list[int])
    - `mode_preference` ("table"|"ocr_rows")
    - `rationale` (string)

- [ ] T212 Add config + flag plumbing:
  - CLI flag `--locator-strategy deterministic|llm`
  - default deterministic
  - if `llm` but env not set => fallback deterministic with trace entry `LLM_NOT_CONFIGURED`

- [ ] T213 Add robust JSON parsing + safety:
  - invalid JSON => fallback deterministic with `LLM_PLAN_INVALID`
  - ranked pages outside range => ignore those and continue
  - LLM must never bypass validators

- [ ] T214 Integrate LLM ranking into StatementLocator:
  - candidates generated deterministically
  - LLM only reorders them
  - validation/selection unchanged
  - store LLM decision in trace

---

## Phase 5: Integrate into statements_raw

- [ ] T215 Update `src/pipeline/extract/statements_raw.py`:
  - call locator for BS/IS/CF
  - use locator selection:
    - table-mode: extract chosen table_id
    - ocr_rows-mode: write reconstructed grid
  - never trust index_map directly

- [ ] T216 Enforce invariant:
  - for each requested statement, outputs must satisfy:
    - at least one write OR a missing entry (no silent empty)

- [ ] T217 Update confidence assignment:
  - High only if table-mode and cols>=3 and year/date header hit
  - Med if ocr_rows with cols>=3
  - Never High for cols<3

- [ ] T218 Standardize missing reasons:
  - TOC_FALSE_POSITIVE
  - NO_TABLES_FOUND
  - TABLE_TOO_FEW_COLUMNS
  - OCR_RECONSTRUCTION_FAILED
  - NO_VALID_CANDIDATE
  - LLM_PLAN_INVALID (trace only; missing should still be one of the core reasons)

---

## Phase 6: Tests (deterministic)

- [ ] T219 Add unit test `tests/test_statement_locator_toc_false_positive.py`:
  - index_map points BS to TOC page (toc_score high)
  - real BS page exists with anchors + 4-col table
  - assert locator rejects TOC and selects real page/table

- [ ] T220 Add unit test `tests/test_statement_locator_multitable_select.py`:
  - same page has 1-col and 4-col tables
  - assert 4-col selected

- [ ] T221 Add unit test `tests/test_statement_locator_ocr_rows.py`:
  - no tables but OCR text_lines contain line items + 2 year values
  - assert cols>=3, mode=ocr_rows

- [ ] T222 Update `tests/test_statements_raw.py`:
  - no-tables case asserts missing emitted (not empty-success)
  - table case asserts evidence includes page_range + table_id and cols>=3

---

## Phase 7: Tests (LLM strategy without calling a real LLM)

- [ ] T223 Add stub planner for tests:
  - provide deterministic ranked_pages output

- [ ] T224 Add unit test `tests/test_statement_locator_llm_ranking_used.py`:
  - planner ranks correct page first
  - assert locator uses ranking but still validates

- [ ] T225 Add unit test `tests/test_statement_locator_llm_invalid_fallback.py`:
  - planner returns invalid JSON
  - assert fallback to deterministic and trace contains LLM_PLAN_INVALID

---

## Phase 8: Reporting / Debuggability

- [ ] T226 Add locator summary to `run_report.md`:
  - per statement: selected page/table/mode/confidence
  - attempts count
  - top rejection reasons

- [ ] T227 Add optional debug dump flag:
  - write `candidates_ranked.json` with candidate scores + snippets (truncated)

---

## Definition of Done

- [ ] For a PDF where BS was incorrectly indexed to page 5, locator finds correct BS pages OR emits missing with explicit searched ranges and standardized reasons.
- [ ] No statement result is accepted as High confidence with cols < 3.
- [ ] `statements_raw.json` never has both `rows=[]` and `missing=[]` for requested statements.
- [ ] LLM ranking is optional, gated, and never bypasses validators.
- [ ] All tests pass.