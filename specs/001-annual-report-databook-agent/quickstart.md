# specs/001-annual-report-databook-agent/quickstart.md
# Quickstart Validation

## Prereqs
- Python 3.11+
- If OCR required: system `tesseract` installed and discoverable in PATH
- Template workbook available (e.g., `tests/fixtures/databook_template.xlsx`)
- Sample PDFs available (text + scanned)

## Run 1: Text PDF Smoke Test
```bash
python -m src.main run \
  --pdf tests/fixtures/sample_text.pdf \
  --template tests/fixtures/databook_template.xlsx \
  --out runs/smoke_text \
  --scope both