# specs/001-annual-report-databook-agent/spec.md
# Feature Specification: Annual Report → Databook Extraction Agent

**Feature Branch**: `[001-annual-report-databook-agent]`  
**Created**: 2026-02-26  
**Status**: Draft  
**Input**: User description: "Take an Indian annual report (PDF), extract relevant information, and populate an Excel databook (template). I already have MCP for Excel; I need intelligent extraction (not necessarily RAG). Must handle generated text PDFs and scanned PDFs. Populate key tabs like CF BS/IS/CFS, PPE, Revenue, Expenses, Borrowings, RPT, Segment, governance changes, and analyst footnotes for non-standard items."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One-click databook generation from an annual report PDF (Priority: P1)
As an analyst, I want to provide an Indian annual report PDF and a databook template workbook, and receive a populated databook workbook with evidence and provenance so I can review quickly without manually searching the PDF.

**Why this priority**: This is the core value: reducing analyst time for building a databook.

**Independent Test**: Can be fully tested by running the CLI on a known annual report PDF and verifying:
- output workbook exists,
- required tabs contain populated values/tables,
- every populated row includes evidence + page references,
- missing values are explicitly marked as NOT FOUND/NOT DISCLOSED.

**Acceptance Scenarios**:
1. **Given** a text-based annual report PDF and a databook template, **When** I run the agent, **Then** it generates `output_databook.xlsx` with the statements and priority notes populated and evidence attached.
2. **Given** a PDF where a priority note exists (e.g., Revenue note), **When** I run the agent, **Then** it writes the extracted table as-is (or normalized grid) and stores page references + evidence snippet/table id.
3. **Given** a PDF where a requested field is absent, **When** I run the agent, **Then** it marks the field as `NOT FOUND` and logs where it searched.

---

### User Story 2 - Robust handling of scanned PDFs (Priority: P1)
As an analyst, I want the agent to work even when the annual report is a scanned PDF (or mixed scanned+text), so I can use it on Indian filings where scanning is common.

**Why this priority**: Indian filings are often scanned; the agent must not fail or silently hallucinate.

**Independent Test**: Provide a scanned annual report PDF and verify:
- pipeline completes,
- it performs OCR for relevant pages,
- it extracts at least the primary statements or marks them NOT FOUND with documented search ranges,
- evidence includes OCR confidence.

**Acceptance Scenarios**:
1. **Given** a scanned-only PDF, **When** I run the agent, **Then** it detects scan pages, runs OCR, and produces an output workbook + evidence pack without crashing.
2. **Given** a mixed PDF, **When** I run the agent, **Then** it uses text extraction on text pages and OCR on image pages, merging into a unified document representation.

---

### User Story 3 - Evidence-first review workflow (Priority: P1)
As an analyst, I want every extracted value/table to be traceable back to the PDF so I can trust the databook and quickly validate questionable items.

**Why this priority**: Financial extraction without provenance is unusable in an analyst workflow.

**Independent Test**: Inspect an output workbook row and confirm it includes:
- page range,
- section/note identifier,
- verbatim evidence snippet or table reference,
- confidence (High/Med/Low).

**Acceptance Scenarios**:
1. **Given** any populated numeric field, **When** I check the row evidence columns (or linked comments), **Then** I can see the page number(s) and a snippet/table reference that supports the value.
2. **Given** a low-confidence OCR extraction, **When** I inspect evidence, **Then** it indicates low OCR confidence and includes the raw OCR snippet.

---

### User Story 4 - Populate analyst-specific tabs and priorities (Priority: P2)
As an analyst, I want the agent to populate the databook in the same structure as my existing workbook (e.g., Knowledge Marine databook), including:
- CF BS / CF IS / CF CFS (copy statements “as is” + canonical mapping where applicable)
- Notes to accounts (copy/paste)
- Footnotes to notes (non-standard narrative)
- Priority notes: Revenue, PPE, Other Expenses, Employee breakdown, Leases, RPT, Segment info
- Governance: corp structure, shareholding, board/KMP changes with reasons as footnotes

**Why this priority**: The workbook structure is the working model; output must match the template.

**Independent Test**: Compare populated workbook tabs against required tab list; verify required anchors/ranges are filled.

**Acceptance Scenarios**:
1. **Given** a report with disclosures for Revenue/PPE/RPT/Segment, **When** I run the agent, **Then** those are populated into their corresponding tabs/sections in the databook.
2. **Given** board/KMP changes are disclosed, **When** I run the agent, **Then** the agent records changes historically and includes stated reasons as footnotes with citations.

---

### User Story 5 - Controlled output scope and statement selection (Priority: P3)
As an analyst, I want to choose whether to populate standalone, consolidated, or both sets of statements and notes, so the workbook matches my coverage.

**Why this priority**: Annual reports often include both and analysts differ.

**Independent Test**: Run with `--scope standalone` and verify only standalone statements/notes are used.

**Acceptance Scenarios**:
1. **Given** both standalone and consolidated are present, **When** I run with `--scope consolidated`, **Then** the databook is populated using consolidated statements and matching notes where possible.

---

### Edge Cases
- What happens when the PDF contains multiple unit conventions (₹ in lakhs vs crores) across sections?
- How does the system handle restated comparatives / prior-period regrouping disclosures?
- What happens when tables are rotated, multi-page, or split across columns?
- How does the system handle missing note numbers (some reports use “Note A/B” or “Annexure”)?
- What happens when the report is password-protected or images are low-resolution?
- How does the system handle negative numbers formatted with parentheses or trailing minus?
- What happens when the workbook template differs slightly (extra columns/years)?

## Requirements *(mandatory)*

### Functional Requirements
- **FR-001**: System MUST accept an annual report PDF (`.pdf`) and a databook template (`.xlsx`) as inputs and produce a populated output workbook (`.xlsx`).
- **FR-002**: System MUST detect PDF type at a per-page level (text vs scanned vs mixed) and select extraction method accordingly.
- **FR-003**: System MUST reconstruct a canonical document representation (`document.json`) including page text blocks, table candidates, and provenance metadata.
- **FR-004**: System MUST build an index map (`index_map.json`) identifying key sections: Financial Statements, Notes to Accounts, MD&A, Corporate Governance, RPT, Segment, etc.
- **FR-005**: System MUST extract the following categories (as available) with provenance:
  - Corp structure
  - Shareholding
  - Related party transactions (details)
  - Board of directors changes historically + reasons as footnotes
  - KMP changes historically + reasons as footnotes
  - MD&A KPI drivers for revenue and margins (narrative + quantified KPIs where present)
  - Statements: BS, IS, CF, CFS (copy/paste “as-is” tables)
  - Notes to accounts (copy/paste)
  - Footnotes to notes (non-standard narrative not captured by standard tables)
- **FR-006**: System MUST prioritize extraction and explicit mapping for the most important notes:
  - Revenue
  - PPE
  - Other expenses
  - Employee breakdown
  - Leases
  - RPT
  - Segment information
- **FR-007**: System MUST populate the workbook template without renaming sheets or breaking layout. It MUST write into pre-defined anchors/ranges from a template map.
- **FR-008**: System MUST attach evidence/provenance for every extracted item written into Excel (page range + evidence snippet/table id + confidence).
- **FR-009**: System MUST never fabricate numeric values. If not found, it MUST write `NOT FOUND` / `NOT DISCLOSED` and log where it searched.
- **FR-010**: System MUST output an evidence pack folder containing `document.json`, `index_map.json`, extractions, and a run report.

### Key Entities *(include if feature involves data)*
- **Run**: One execution instance; inputs, config, outputs, timings, coverage.
- **Document**: Canonical reconstructed representation of the PDF with page-level artifacts.
- **IndexMap**: Section/note map for targeted extraction.
- **Extraction**: Structured output per module (statements, PPE, RPT, governance, etc.).
- **TemplateMap**: Workbook layout contract describing where to write outputs and evidence.

## Success Criteria *(mandatory)*

### Measurable Outcomes
- **SC-001**: For text-based PDFs, agent populates at least: CF BS, CF IS, CF CFS, Revenue, PPE, Borrowings, Expenses tabs (or their template equivalents) with ≥80% coverage of expected line items that exist in the report.
- **SC-002**: For scanned PDFs, agent completes without crash and produces an evidence pack; it populates at least the primary statements OR clearly marks them as NOT FOUND with documented search ranges.
- **SC-003**: 100% of populated numeric fields have provenance (page range + evidence snippet/table id + confidence).
- **SC-004**: No numeric hallucinations in output: values not found are blank/NOT FOUND/NOT DISCLOSED.