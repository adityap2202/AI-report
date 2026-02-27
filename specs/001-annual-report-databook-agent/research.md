
---

```markdown
# specs/001-annual-report-databook-agent/research.md
# Research: Annual Report PDF Extraction & Databook Population

## Goals
- Reliable extraction from Indian annual report PDFs (text/scanned/mixed).
- Deterministic module behavior (not “chatty RAG”), with evidence-first outputs.
- Excel template population without layout drift.

## Key Findings / Decisions

### PDF Handling Strategy
- Per-page classification: if extracted text length < threshold OR page has no text objects -> treat as image/OCR page.
- Prefer not to OCR the entire document; OCR only pages likely containing needed sections (statements/notes/governance) discovered via indexing signals (captions, headers, note patterns).

### Table Extraction Strategy
- For text PDFs: attempt `pdfplumber` table extraction first; fallback to `camelot` where `pdfplumber` fails.
- For scanned pages: detect table-like regions via contours; fallback to row-wise OCR with delimiter heuristics. Always mark confidence Low/Med with OCR score.

### Indexing Strategy (No RAG Required)
- Build an index map by scanning for:
  - statement captions: Balance Sheet, Statement of Profit and Loss, Cash Flow Statement, Notes to Accounts
  - note labels: `Note <number>` patterns + nearby titles
  - section headings: Corporate Governance, Board’s Report, MD&A, Related Party Transactions, Segment Information
- Store mapping as `index_map.json`. Every extractor only searches within mapped ranges to avoid expensive full-doc passes.

### Evidence Strategy
- Every extracted item MUST link to:
  - page number(s)
  - block_id or table_id
  - evidence text snippet (verbatim) OR table grid fragment
  - confidence classification

### Template Population Strategy
- Use a TemplateMap JSON describing exact cell anchors, year columns, and evidence columns for each sheet.
- Do not attempt “smart” sheet discovery at runtime beyond validating expected sheet names exist.

## Risks / Mitigations
- Multi-page split tables: mitigate by capturing each page’s table and storing a combined representation with explicit “continued” markers.
- Rotated tables: mitigate by rotation detection (90/270) and re-render before OCR.
- Units and scaling: mitigate by detecting units per statement/note and storing units field explicitly; avoid auto-scaling unless template requires it.