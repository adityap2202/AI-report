"""Workbook writer Phase 3 extensions: section header, interpretation bullets."""
from __future__ import annotations

import pytest
from pathlib import Path

from src.models.template_map import TemplateMap, SheetMap
from src.pipeline.populate.excel_writer import ExcelWriter


def test_write_section_header_and_interpretation_bullets(tmp_path):
    template = tmp_path / "template.xlsx"
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active.title = "MD&A"
        wb.save(template)
    except ImportError:
        pytest.skip("openpyxl required")
    tm = TemplateMap(workbook_name=template.name, sheets={"MD&A": SheetMap()})
    writer = ExcelWriter(template, tm)
    writer.load()
    writer.write_section_header("MD&A", 1, "Revenue drivers", "p.12")
    row = writer.write_interpretation_bullets("MD&A", 2, "Risks", [("Price volatility", "p.15"), ("Currency risk", "p.16")])
    writer.save(tmp_path / "out.xlsx")
    assert row == 5  # 2 (header) + 1 (section title) + 2 bullets
