# CLI Contract

Command:
- `python -m src.main run`

Arguments:
- `--pdf <path>` (required)
- `--template <path>` (required)
- `--out <dir>` (required)
- `--scope <standalone|consolidated|both>` (default: both)
- `--company-name <string>` (optional override)
- `--fy <string>` (optional override)
- `--max-pages <int>` (optional; for dev)
- `--no-ocr` (optional; forces text-only)
- `--debug-pages <comma-separated>` (optional; dump page images + OCR intermediates)

Outputs:
- `<out>/output_databook.xlsx`
- `<out>/evidence_pack/document.json`
- `<out>/evidence_pack/index_map.json`
- `<out>/evidence_pack/extractions/*.json`
- `<out>/evidence_pack/tables/*.json`
- `<out>/evidence_pack/snippets/*.md`
- `<out>/evidence_pack/run_report.md`

Exit codes:
- 0 success (even with NOT FOUND values)
- 2 invalid input (missing files, unreadable PDF)
- 3 template mismatch (missing required tabs/anchors)
- 4 critical pipeline failure (unhandled exception)
