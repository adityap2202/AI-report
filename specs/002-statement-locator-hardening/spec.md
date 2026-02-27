# Feature Specification: Intelligent Statement Locator (BS / IS / CF)

Feature Branch: 002-statement-locator
Created: 2026-02-26
Status: Draft

---

## Summary

Phase 2 extraction currently trusts `index_map` to locate financial statements.
In real annual reports this fails due to:

- TOC page matches (example: page 5)
- scanned statements without structured tables
- multiple tables per page
- OCR text without table structure
- captions varying across companies
- standalone vs consolidated duplicates

This feature introduces a Statement Locator that actively searches for the true statement pages before extraction.

The locator determines:
- correct page range
- extraction mode (table vs OCR rows)
- correct table selection

Extraction and Excel writing remain deterministic.

---

## Scope

Statements supported:

Balance Sheet → CF BS  
Income Statement / P&L → CF IS  
Cash Flow Statement → CF CFS

Not included:
- Notes
- Governance
- MD&A interpretation
- Line-item canonical mapping

---

## High-Level Workflow

Old workflow:
index_map → statements_raw

New workflow:
index_map
→ candidate generation
→ LLM planner (optional ranking)
→ deterministic validation
→ table selection OR OCR reconstruction
→ statements_raw extraction

---

## Functional Requirements

### FR-001 Candidate Generation
For each statement type (BS/IS/CF), generate candidate pages from:

1. index_map ranges
2. keyword caption scan
3. numeric density scan
4. proximity to financial statements section

Synonyms:

BS:
- Balance Sheet
- Statement of Financial Position

IS:
- Statement of Profit and Loss
- Income Statement
- Profit & Loss

CF:
- Cash Flow Statement

Candidates are deduplicated and limited to top K (default 30).

---

### FR-002 TOC Rejection

A page must be rejected as TOC-like if it matches at least two indicators:

- dotted leader patterns (.....)
- repeated trailing page numbers
- contains "Contents"
- low numeric density
- no financial anchors

Rejected pages recorded with reason TOC_FALSE_POSITIVE.

---

### FR-003 Candidate Scoring Signals

Each candidate page is scored using:

Signals:
- numeric_density (ratio of tokens containing digits)
- anchor_hits (presence of statement keywords)
- year_header_hits (FY2024 / 2023-24 / “As at March 31”)
- table_shapes (rows/columns of detected tables)

Anchors:

Balance Sheet:
- Total Assets
- Equity and Liabilities
- Share Capital
- Non-current assets

Income Statement:
- Revenue
- Total Income
- Profit for the year

Cash Flow:
- Net cash from operating activities
- Cash and cash equivalents

---

### FR-004 Validation Gates

A candidate is valid if at least two conditions hold:

- numeric_density ≥ threshold
- year_header_hits ≥ 1
- anchor_hits ≥ 2
- best_table_cols ≥ 3

Reject if:
- best table columns < 3
- TOC-like and no anchors

Reject reason TABLE_TOO_FEW_COLUMNS.

---

### FR-005 Table Selection

If multiple tables exist:

Select table with priority:
1. highest column count
2. year headers
3. numeric density
4. caption match

---

### FR-006 OCR Row Reconstruction

If no usable table exists:

Locator attempts OCR reconstruction:

- detect lines with ≥ 2 numeric tokens
- cluster numeric tokens into columns
- produce grid

Accept only if columns ≥ 3.

Else emit missing reason OCR_RECONSTRUCTION_FAILED.

---

### FR-007 Iterative Search

For each statement:

1. rank candidates
2. validate best candidate
3. if fail → try next
4. if all fail → regenerate candidates
5. stop after max_attempts (default 8)

---

### FR-008 Missing Entries

If no valid candidate found emit:

field: CF BS / CF IS / CF CFS  
searched_in: attempted ranges  
reason: standardized code

Allowed reasons:
- TOC_FALSE_POSITIVE
- NO_TABLES_FOUND
- TABLE_TOO_FEW_COLUMNS
- OCR_RECONSTRUCTION_FAILED
- NO_VALID_CANDIDATE

Silent success is forbidden.

---

### FR-009 Confidence

High:
- table mode
- ≥3 columns
- year header detected

Medium:
- OCR reconstruction

Low:
- debugging only

---

## LLM Planner Integration

### FR-010 Planner Mode
Locator supports two strategies:

deterministic (default)  
llm (optional)

LLM is used only to rank candidate pages.

---

### FR-011 Planner Inputs

Planner receives only metadata:

For each page:
- page number
- snippet (≤400 chars)
- toc_score
- numeric_density
- anchor hits
- table shapes

Full document text is forbidden.

---

### FR-012 Planner Output Contract

LLM must return strict JSON:

{
  "statement_type": "BS",
  "ranked_pages": [88, 89, 87],
  "mode_preference": "table",
  "rationale": "multi-column financial statement detected"
}

Invalid response → fallback deterministic and record LLM_PLAN_INVALID.

---

### FR-013 Planner Safety

The LLM must never:
- extract numbers
- write Excel
- override validators
- mark statements valid

Validators are final authority.

---

## Artifacts

New file:

runs/<id>/evidence_pack/extractions/statements_locator.json

Contains:
- chosen page range
- selected table_id
- mode
- attempts trace
- rejection reasons
- planner decisions (if used)

---

## Success Criteria

The feature is complete when:

1. Balance Sheet no longer maps to TOC page
2. Mixed scanned/text PDFs work
3. No 1-column tables accepted
4. No silent empty extraction
5. Missing entries include explicit reasons
6. LLM planner improves page selection but system works without it

