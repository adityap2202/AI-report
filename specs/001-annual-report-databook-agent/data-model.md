# specs/001-annual-report-databook-agent/data-model.md
# Data Model

## Overview
The system produces a canonical `document.json` (PDF reconstruction), an `index_map.json` (section/note mapping), multiple module `extractions/*.json`, and a populated Excel workbook.

## Canonical Entities

### RunContext
- run_id (string)
- input_pdf_path (string)
- input_template_xlsx_path (string)
- scope (standalone|consolidated|both)
- output_dir (string)
- created_at (datetime)
- config thresholds (OCR, text-length, etc.)

### Document (document.json)
- meta:
  - file_name, sha256, pages, pdf_type(text|scanned|mixed)
- pages[]:
  - page (int)
  - type (text|image)
  - text_blocks[]: {block_id, text, bbox, role_hint, ocr_confidence}
  - tables[]: {table_id, bbox, caption, grid, confidence}
  - images[]: {image_id, bbox, path}

### IndexMap (index_map.json)
- company_name, fiscal_year_label, units_default
- sections[]: title + page_range
- statements[]: {type(BS/IS/CF/CFS/SOCE), scope, caption, page_range}
- notes[]: {note_number, title, page_range}
- priority_locations: revenue/ppe/leases/rpt/segment -> references

### Extraction (module outputs)
Uniform format:
- module, version
- rows[]: module-defined row schema
- missing[]: {field, searched_in, reason}
- qa: confidence distribution

### TemplateMap
- workbook_name
- sheets:
  - layout_type
  - anchor_cell OR header_row/line_item_col/year_cols
  - evidence_cols
  - line_item_aliases
  - validations (required years, required ranges)

## Confidence
- High: clean text extraction or table parse with stable structure
- Med: partial structure or mild OCR dependence
- Low: OCR-only, ambiguous structure, or weak mapping

## “No Hallucination” Invariant
Any numeric written to Excel must originate from:
- a parsed table cell, or
- a text snippet with a numeric token,
with stored provenance linking to page and evidence.