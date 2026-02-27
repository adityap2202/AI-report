# specs/001-annual-report-databook-agent/tasks.md
--- 
description: "Task list template for feature implementation"
---

# Tasks: Annual Report → Databook Extraction Agent

**Input**: Design documents from `/specs/001-annual-report-databook-agent/`  
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/  
**Tests**: Tests are included (RECOMMENDED for this project). :contentReference[oaicite:4]{index=4}

**Organization**: Tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`
- **[P]**: Can run in parallel
- **[Story]**: US1, US2, US3, ...
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)
- [ ] T001 Create repository skeleton per plan (src/, tests/, reference/, template_map/, runs/)
- [ ] T002 [P] Add `pyproject.toml` with pinned deps (pdfplumber, pymupdf, pytesseract, opencv-python, pydantic, typer, pytest)
- [ ] T003 [P] Implement logging baseline and run folder creation in `src/pipeline/run_context.py`
- [ ] T004 [P] Add schema files under `specs/.../contracts/` into repo (copy as-is)
- [ ] T005 [P] Add minimal ontology placeholders in `reference/ontology/` and patterns in `reference/patterns/`

## Phase 2: Foundational (Blocking Prerequisites)
**⚠️ CRITICAL**: No user story work can begin until complete.
- [ ] T006 Implement PDF type detection in `src/pipeline/pdf_type.py` (per-page text-length heuristic)
- [ ] T007 Implement canonical models (pydantic) in `src/models/document.py`, `src/models/index_map.py`, `src/models/extraction.py`, `src/models/template_map.py`
- [ ] T008 Implement document reconstruction in `src/pipeline/reconstruct.py`:
  - text block extraction for text pages
  - rasterization for image pages
  - optional OCR path with confidence
  - table candidate extraction for text pages
- [ ] T009 Implement index builder in `src/pipeline/index_build.py` to produce `index_map.json`
- [ ] T010 Implement TemplateMap loader/validator in `src/pipeline/populate/template_map.py`
- [ ] T011 Implement Excel writer abstraction in `src/pipeline/populate/excel_writer.py` (openpyxl baseline + pluggable MCP adapter later)
- [ ] T012 Implement run report generator in `src/pipeline/qa/run_report.py` (coverage + missing summary)

**Checkpoint**: Foundation ready.

## Phase 3: User Story 1 (P1) - One-click databook generation
### Tests (write first)
- [ ] T013 [P] [US1] Add smoke test harness `tests/test_pipeline_smoke.py` (runs pipeline on fixtures, checks outputs exist)
- [ ] T014 [P] [US1] Add JSON schema validation tests for document/index/extraction outputs

### Implementation
- [ ] T015 [US1] Implement `src/cli/app.py` and `src/main.py` CLI `run` command (arguments per contracts/cli.md)
- [ ] T016 [US1] Implement orchestrator `src/pipeline/populate/populate.py` (load template, apply TemplateMap, write outputs)
- [ ] T017 [US1] Implement extraction modules (minimal first):
  - `src/pipeline/extract/statements_raw.py` (BS/IS/CF/CFS as-is)
  - `src/pipeline/extract/notes_copy.py` (notes to accounts copy/paste blocks)
- [ ] T018 [US1] Wire evidence pack output folder structure and write JSON/MD artifacts

**Checkpoint**: US1 runs end-to-end for a text PDF.

## Phase 4: User Story 2 (P1) - Scanned PDF robustness
### Tests
- [ ] T019 [P] [US2] Add scanned PDF fixture test (ensures run completes + outputs evidence + OCR confidence)

### Implementation
- [ ] T020 [US2] Enhance OCR pipeline in `reconstruct.py` (deskew, thresholding, rotation handling)
- [ ] T021 [US2] Add OCR-only table fallback extraction (row-wise) with Low confidence labeling

**Checkpoint**: US2 runs end-to-end for scanned PDF fixture.

## Phase 5: User Story 3 (P1) - Evidence-first enforcement
### Tests
- [ ] T022 [P] [US3] Add test to ensure every populated numeric output has provenance fields set (evidence/page/confidence)

### Implementation
- [ ] T023 [US3] Enforce provenance invariants in extraction outputs and Excel writing layer (reject writes without provenance unless explicitly allowed for “as-is copied statements” blocks with table_id references)

## Phase 6: User Story 4 (P2) - Priority notes + analyst tabs
### Implementation (module-by-module; can be parallel once foundation stable)
- [ ] T024 [P] [US4] Implement `ppe.py` extractor + populate PPE tab ranges
- [ ] T025 [P] [US4] Implement `revenue.py` extractor + populate Revenue & OI tab
- [ ] T026 [P] [US4] Implement `expenses.py` extractor including Other expenses + employee breakdown
- [ ] T027 [P] [US4] Implement `borrowings.py` extractor including lease liabilities where present
- [ ] T028 [P] [US4] Implement `rpt.py` extractor and write RPT detail tables + evidence
- [ ] T029 [P] [US4] Implement `segment.py` extractor and write segment tables + evidence
- [ ] T030 [US4] Implement `statements_canonical.py` for canonical mapping into CF BS/IS/CFS where template expects normalized line items

## Phase 7: User Story 5 (P3) - Scope control
- [ ] T031 [US5] Implement `--scope` selection in index + extraction modules (standalone/consolidated/both)
- [ ] T032 [US5] Add tests verifying scope behavior

## Phase N: Polish & Cross-Cutting
- [ ] T033 [P] Improve TemplateMap coverage validations and friendly error messages for missing sheets/anchors
- [ ] T034 [P] Add performance guardrails (skip OCR outside mapped ranges; caching page renders)
- [ ] T035 Run `specs/.../quickstart.md` validations and update run_report format for analyst readability