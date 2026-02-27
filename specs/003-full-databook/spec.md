# Feature Specification: Phase 3 — Full Databook Population (Notes + Governance + Interpretations) with LLM Planner/Reviewer

**Feature Branch**: `003-full-databook`  
**Created**: 2026-02-26  
**Status**: Draft

---

## Summary

Phase 2 populates only CF BS / CF IS / CF CFS (financial statements) using a locator with optional LLM ranking, then deterministic extraction and Excel writing.

Phase 3 expands the system to populate the **entire databook workbook** (all relevant tabs) from one annual report PDF, including:

1) Corporate structure  
2) Shareholding  
3) Related party transactions detail (table + narrative)  
4) Board of directors: current list + changes during the year + reasons (footnote narrative)  
5) KMPs: same as above  
6) MD&A: drivers of revenue/margins + forward-looking commentary (open-ended, interpretive)  
7) Financial statements (BS/IS/CF) already done  
8) Notes to accounts tables (copy/paste)  
9) Footnotes to notes (non-table narrative disclosures)

Indian filings are generally PDFs and can be mixed scanned/text.

**New requirement**: Phase 3 must employ an **LLM agent** (planner/reviewer) to:
- plan a document navigation strategy per section
- validate that extracted content matches the intended tab (semantic correctness)
- generate **interpretations** (structured analyst notes) for MD&A and key accounting notes
- guide iterative search when deterministic signals are insufficient

Phase 3 will preserve traceability:
- all extracted tables must include page/table evidence
- all interpretations must cite page refs/snippet evidence
- LLM cannot fabricate numbers; it can only summarize/interpret the report’s text

---

## Goals

- Populate all tabs required by the workbook template with extracted tables, narrative, and analyst interpretations.
- Introduce an LLM-driven planning and review loop to improve correctness on messy PDFs.
- Ensure every section either:
  - writes content to the workbook, OR
  - emits a missing entry with reason + searched ranges.
- Keep Phase 2 statement extraction unchanged but allow Phase 3 reviewer to flag anomalies.

---

## Non-Goals

- Multi-year consolidation (5 PDFs → one workbook) is out of scope.
- Full canonical remapping of every line item into standardized rows is out of scope (raw paste + evidence is acceptable).
- Automated reconciliation checks (ties, totals) is deferred to later QA phase.

---

## Workbook-Driven Extraction Contract

Phase 3 is driven by the workbook template. For each sheet/tab, we define:

- **what** must be filled (tables, narrative, interpretations)
- **where** it goes (anchor cells / paste region)
- **evidence columns** (page/table refs)
- **how to validate** correctness (anchors, expected terms, numeric shape)

The system must read a `template_map.json` generated from the workbook (or provided) describing these rules.

---

## Scope: What must be filled

### A) Governance / Company Profile
1. Corporate structure
2. Shareholding (table + narrative)
3. Related party transactions (RPT) details (table + narrative)
4. Board of directors:
   - list of directors
   - changes during the year (appointed/resigned)
   - reason text as footnote evidence
5. KMPs:
   - list of KMP
   - changes during the year + reason

### B) MD&A (Interpretations required)
6. Management Discussion and Analysis:
   - identify KPIs and operational drivers of revenue and margins
   - year-on-year comparison narrative
   - management outlook and key risks (as written)
   - produce structured “analyst interpretation notes” in the workbook

### C) Statements (already implemented)
7. CF BS, CF IS, CF CFS (Phase 2)

### D) Notes to Accounts (Tables + Footnotes)
8. Notes to accounts — copy/paste tables into relevant tabs
9. Footnotes to notes — narrative disclosures and qualifiers

Priority note tabs (must have):
- Revenue
- PPE
- Other expenses
- Employee breakdown
- Leases
- RPT
- Segment information
- Borrowings (if present)

---

## Inputs

- PDF annual report
- Workbook template (.xlsx)
- template_map.json
- document.json (Marker output preferred)

---

## Outputs

Primary:
- Populated workbook: `runs/<id>/output_databook.xlsx`

Evidence pack:
- `runs/<id>/evidence_pack/extractions/notes_locator.json`
- `runs/<id>/evidence_pack/extractions/notes_raw.json`
- `runs/<id>/evidence_pack/extractions/gov_sections.json`
- `runs/<id>/evidence_pack/extractions/interpretations.json`
- Update: `run_report.md` summary extended for Phase 3 coverage

---

## System Architecture

Phase 3 introduces two new agentic components:

### 1) LLM Planner Agent (Navigation & Strategy)
Purpose:
- for each target tab (Revenue note, RPT, Directors changes, MD&A, etc.):
  - propose page ranges and keywords to search
  - rank candidate pages/sections
  - recommend extraction mode (table vs text blocks)
  - recommend iterative refinement if no content found

Constraints:
- LLM does not extract numbers.
- LLM only proposes where to look; deterministic extractors pull the content.

### 2) LLM Reviewer/Interpreter Agent
Purpose:
- check semantic correctness of extracted content vs intended tab
- generate structured analyst interpretations:
  - MD&A notes (drivers, risks, outlook)
  - key accounting note commentary (Revenue recognition, leases, segment changes, RPT context)

Constraints:
- Must cite evidence: page_ref + quoted snippet ids.
- Must never invent data; only summarize/interpret extracted text.

---

## Functional Requirements

### FR-001 Section Inventory
Create a standardized inventory of “targets” derived from template_map:

Targets include:
- statement targets (BS/IS/CF)
- note targets (Revenue, PPE, Leases, etc.)
- governance targets (shareholding, directors, KMP)
- MD&A target (interpretation)

Each target must define:
- target_id
- sheet_name
- content_type (table | narrative | interpretation | mixed)
- expected anchors
- validation rules
- paste region mapping

---

### FR-002 Notes Locator (LLM-assisted)
Implement a Notes Locator similar to StatementLocator:

Pipeline per note target:
1. candidate generation:
   - keyword scan for “Note X”, “Revenue”, “Property, Plant and Equipment”, “Related Party”
   - table presence and numeric density
2. LLM planner ranks candidates
3. deterministic validator confirms
4. choose best page range and table(s)
5. extract tables and/or text blocks

Missing reasons standardized:
- NO_VALID_CANDIDATE
- NO_TABLES_FOUND
- OCR_RECONSTRUCTION_FAILED
- VALIDATION_FAILED
- LLM_PLAN_INVALID (trace only)

Artifacts:
- notes_locator.json includes attempts trace and planner decisions.

---

### FR-003 Governance Section Extractor (LLM-assisted)
For governance targets:
- directors list
- KMP list
- changes during year + reason

Process:
1. candidate generation via keyword scan:
   - “Directors’ Report”, “Board of Directors”, “Appointment”, “Resignation”, “Key Managerial Personnel”
2. LLM planner ranks section pages
3. extractor pulls:
   - tables (if any)
   - narrative paragraphs
4. LLM reviewer produces structured outputs:
   - current directors
   - changes + effective dates
   - reason snippets with page refs

Artifacts:
- gov_sections.json with extracted blocks and interpretation.

---

### FR-004 MD&A Interpretation (LLM required)
MD&A is inherently interpretive.

Process:
1. locate MD&A section pages:
   - “Management Discussion and Analysis”, “Business Overview”, “Operational Highlights”
2. extract key paragraphs (text blocks) + page refs
3. LLM interpreter produces structured notes:
   - Revenue drivers (what drove it this year)
   - Margin drivers (costs, utilization, pricing, mix)
   - Major KPIs mentioned
   - Forward-looking statements (what management expects)
   - Risks/uncertainties explicitly mentioned

Outputs must include evidence pointers:
- each bullet includes (page_ref, snippet_id) references.

Artifact:
- interpretations.json includes MD&A outputs.

---

### FR-005 Notes Footnotes & Narrative Disclosures
For each priority note tab:
- extract narrative disclosures that accompany tables:
  - accounting policies relevant to note
  - qualifiers (contingencies, commitments, segment basis)
  - RPT explanations

LLM reviewer can summarize into 3–8 bullets per note, with evidence refs.

---

### FR-006 Workbook Writing Contract
For each target tab:
- write extracted table(s) into defined paste region(s)
- write evidence into defined evidence cols
- write LLM interpretations into defined “Notes/Footnotes/Interpretation” region

If a sheet has multiple sub-sections (e.g., Revenue note has multiple tables):
- append them vertically with section headers + page refs

---

### FR-007 Traceability and Safety
- All LLM outputs must cite evidence from the document (page refs and snippet ids).
- LLM must be constrained to:
  - ranking/selection
  - summarization/interpretation based on extracted text
- LLM must never create numeric values or alter extracted tables.

---

### FR-008 Iterative Improvement Loop
When extraction fails for a target:
- LLM planner proposes refined search:
  - alternative synonyms
  - broader page range
  - “look near Note X referenced in statements”
- retry up to max_attempts (default 6 per target)

All retries recorded in notes_locator.json trace.

---

## Non-Functional Requirements

- Deterministic extraction remains the source of truth for tables.
- LLM calls must be bounded and cached per run.
- System must run on mixed scanned/text PDFs.
- All artifacts must be written even on partial failure.

---

## Success Criteria

- On the sample workbook and one annual report PDF:
  - All Phase 2 statement tabs remain populated correctly.
  - Priority note tabs are populated with tables and narrative where present.
  - Governance tabs populated with directors/KMP lists and changes with reasons.
  - MD&A tab populated with structured interpretations and evidence refs.
  - Any missing targets have explicit reasons and searched ranges.