# specs/001-annual-report-databook-agent/plan.md
# Implementation Plan: Annual Report → Databook Extraction Agent

**Branch**: `[001-annual-report-databook-agent]` | **Date**: 2026-02-26 | **Spec**: `specs/001-annual-report-databook-agent/spec.md`  
**Input**: Feature specification from `/specs/001-annual-report-databook-agent/spec.md`  
**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow. :contentReference[oaicite:3]{index=3}

## Summary
Build a deterministic extraction pipeline that converts Indian annual report PDFs (text/scanned/mixed) into a canonical document representation, builds a section/note index, extracts statements + priority notes + governance items with evidence/provenance, and populates a fixed Excel databook template using a TemplateMap contract. The system is CLI-first and MCP-ready, with a clean boundary where Excel writing can be done via openpyxl or via an Excel MCP tool adapter.

## Technical Context
**Language/Version**: Python 3.11+  
**Primary Dependencies**:
- PDF parsing: `pymupdf` (fitz) for rendering + text, `pypdf` for metadata fallback
- Text/table parsing: `pdfplumber` (text + table heuristics), optional `camelot` (lattice/stream) for text PDFs
- OCR: `pytesseract` + `opencv-python` for binarization/deskew; optional `tesseract` system dependency
- Data modeling: `pydantic` for JSON schemas
- Excel: `openpyxl` (baseline), plus optional `ExcelMCPAdapter` (pluggable)
- CLI: `typer` (or `argparse` if minimizing deps)
- Logging: `structlog` or stdlib `logging` with JSON output

**Storage**: File outputs only (`runs/<run_id>/...`)  
**Testing**: `pytest` + golden fixtures + snapshot assertions on JSON outputs  
**Target Platform**: macOS/Linux (local) + optional server later  
**Project Type**: CLI tool + library modules (MCP-ready tool boundaries)  
**Performance Goals**:
- Text PDFs: complete run under ~2–5 minutes for 200–300 pages on laptop
- Scanned PDFs: OCR only on relevant pages; avoid full-document OCR unless necessary
**Constraints**:
- Must never hallucinate numeric values
- Must attach evidence for every output write
- Must support multi-page split tables (minimum: partial extraction + explicit “continued” handling)
**Scale/Scope**:
- Single report per run
- 1–5 years per report (as presented)
- Template workbook assumed stable but configurable via TemplateMap JSON

## Constitution Check
GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.
- Simplicity gate: single Python project, no microservices.
- Anti-abstraction gate: direct use of libraries; minimal wrapper layers except tool boundaries.
- Evidence-first gate: enforce provenance in data models and Excel population.

## Project Structure

### Documentation (this feature)
```text
specs/001-annual-report-databook-agent/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   ├── document-json.schema.json
│   ├── index-map.schema.json
│   ├── extraction.schema.json
│   └── template-map.schema.json
└── tasks.md