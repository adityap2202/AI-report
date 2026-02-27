---
description: "Phase 3 task list to populate full databook (notes + governance + MD&A interpretations) using LLM planner/reviewer with evidence."
---

# Tasks: Phase 3 — Full Databook Population with LLM Planner/Reviewer

**Input**: `specs/003-full-databook/spec.md`, `plan.md`  
**Dependencies**: Phase 2 exists and statements are working (BS/IS/CF).  
**Scope**: Populate full workbook for one PDF: notes, governance, MD&A interpretations.

---

## Phase 1: Template-driven target inventory

- [ ] T301 Create `src/pipeline/targets/inventory.py`
  - load template_map.json
  - build target objects for:
    - note tabs (Revenue, PPE, Leases, RPT, Segment, Borrowings, Other exp, Employee breakdown)
    - governance tabs (Corp structure, Shareholding, Directors, KMP)
    - MD&A tab
  - each target includes:
    - target_id, sheet_name, content_type
    - expected anchors + synonyms
    - paste region (anchor cell, max rows)
    - evidence region (page ref col, table id col, confidence col)
    - validation thresholds

- [ ] T302 Add JSON schema validation for template_map and targets (fail fast)

---

## Phase 2: LLM agent wrapper (planner + reviewer)

- [ ] T303 Add `src/llm/agent.py`
  - provider: Anthropic Messages API
  - functions:
    - `planner_rank(statement_or_target_type, candidates) -> ranked_pages`
    - `reviewer_interpret(kind, extracted_blocks) -> structured_json`
  - strict JSON parsing
  - retries for transient errors
  - caching responses to `runs/<id>/llm_cache/*.json`

- [ ] T304 Define required JSON outputs:
  - planner output: ranked_pages, mode_preference, rationale
  - reviewer output for mdna:
    - revenue_drivers[]
    - margin_drivers[]
    - kpis[]
    - outlook[]
    - risks[]
    - each bullet contains evidence: {page_ref, snippet_id}
  - reviewer output for note_summary:
    - key_policies[]
    - key_judgements[]
    - unusual_movements[]
    - each with evidence refs

---

## Phase 3: Notes locator (LLM-guided)

- [ ] T305 Create `src/pipeline/locate/notes.py`
  - candidate generation:
    - keyword scan for note names + “Note” patterns
    - numeric density + table count
    - references from statements (if statement tables contain “Note X”)
  - LLM planner ranks candidates
  - deterministic validation:
    - table presence OR text anchors depending on target type
    - reject TOC/narrative pages for table targets
  - iterative retry up to max_attempts per target
  - write artifact: `notes_locator.json`

- [ ] T306 Add standardized missing reasons for notes targets:
  - NO_VALID_CANDIDATE
  - NO_TABLES_FOUND
  - VALIDATION_FAILED
  - OCR_RECONSTRUCTION_FAILED
  - LLM_PLAN_INVALID (trace only)

---

## Phase 4: Notes extraction (tables + narrative)

- [ ] T307 Create `src/pipeline/extract/notes_raw.py`
  - extract selected tables by table_id
  - also extract nearby narrative text blocks (±N blocks around caption)
  - output `notes_raw.json` with:
    - tables grids
    - narrative blocks with snippet_id and page_ref
    - confidence
    - table_id/page_range

- [ ] T308 Extend workbook writer to paste note tables into correct sheet regions
  - append multiple tables vertically with section headers
  - write evidence columns per table
  - write narrative blocks to footnote region
  - invariant: write OR missing

---

## Phase 5: Governance extraction (directors, KMP, shareholding, corp structure)

- [ ] T309 Create `src/pipeline/extract/gov_sections.py`
  - candidate generation:
    - “Directors’ Report”, “Board of Directors”, “Appointment”, “Resignation”
    - “Key Managerial Personnel”, “KMP”, “Company Secretary”
    - “Shareholding Pattern”
    - “Corporate Structure”, “Subsidiary”, “Holding”
  - planner ranks candidates
  - extractor pulls tables + paragraphs
  - reviewer structures into:
    - list of directors
    - director changes (name, date, action, reason)
    - list of KMP
    - KMP changes (same)
    - shareholding summary (promoter/non-promoter if present)
  - write artifact `gov_sections.json`
  - write to workbook tabs

---

## Phase 6: MD&A extraction and interpretations (LLM required)

- [ ] T310 Create `src/pipeline/extract/mdna.py`
  - locate MD&A pages (planner-assisted)
  - extract key paragraphs (text blocks) with snippet_ids

- [ ] T311 Create `src/pipeline/interpret/interpretations.py`
  - call reviewer for mdna outputs with evidence requirements
  - produce bullet lists + evidence refs
  - write artifact `interpretations.json`

- [ ] T312 Write MD&A interpretations into workbook:
  - structured sections:
    - Revenue drivers
    - Margin drivers
    - KPIs
    - Outlook
    - Risks
  - each bullet includes page_ref in adjacent column or inline

---

## Phase 7: Pipeline integration

- [ ] T313 Modify `src/main.py` to add Phase 3 orchestration
  - add CLI flags:
    - --phase 2|3
    - --llm-mode off|planner_only|full
    - --max-target-attempts
  - Phase 3 default: enabled
  - Phase 2 still runnable

- [ ] T314 Add run_report.md Phase 3 summary
  - per target: found/missing, page refs, confidence
  - count of LLM calls and cache hits

---

## Phase 8: Tests (no real LLM calls)

- [ ] T315 Add unit tests for target inventory parsing
- [ ] T316 Add notes locator tests:
  - keyword candidate generation works
  - LLM ranking stub used
  - invalid LLM output falls back deterministic ordering
- [ ] T317 Add reviewer tests:
  - mdna JSON schema enforced
  - missing evidence refs causes rejection
- [ ] T318 Add workbook writer placement tests:
  - note tables pasted at correct anchor
  - mdna bullets written
  - missing entries recorded when no candidates

---

## Definition of Done

- [ ] Running Phase 3 on the sample annual report produces:
  - statements populated (Phase 2)
  - all priority note tabs populated with tables + footnotes where present
  - governance tabs populated with structured lists + change reasons
  - MD&A tab populated with LLM interpretations with evidence refs
  - missing entries exist for anything not found (no silent skips)
- [ ] Evidence pack includes:
  - notes_locator.json
  - notes_raw.json
  - gov_sections.json
  - interpretations.json
- [ ] All tests pass with stubbed LLM calls