"""
TemplateMap loader and validator.
Load from JSON (e.g. template_map/knowledge_marine_v1.json) and validate against schema / required sheets.
Per T010; FR-007.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from src.models.template_map import SheetMap, TemplateMap

logger = logging.getLogger(__name__)


def load_template_map(path: str | Path) -> TemplateMap:
    """Load TemplateMap from JSON file."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"TemplateMap not found: {p}")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return _parse_template_map(data)


def _parse_template_map(data: dict) -> TemplateMap:
    """Parse dict into TemplateMap; sheets as dict of string -> SheetMap."""
    workbook_name = data.get("workbook_name", "")
    sheets_data = data.get("sheets", {})
    sheets: dict[str, SheetMap] = {}
    for name, s in sheets_data.items():
        if isinstance(s, dict):
            sheets[name] = SheetMap(**s)
        else:
            sheets[name] = SheetMap()
    write_rules = data.get("write_rules", {})
    extra = {k: v for k, v in data.items() if k not in ("workbook_name", "sheets", "write_rules")}
    return TemplateMap(
        workbook_name=workbook_name,
        sheets=sheets,
        write_rules=write_rules,
        extra=extra,
    )


def validate_template_against_workbook(
    template_map: TemplateMap,
    workbook_path: str | Path,
) -> list[str]:
    """
    Check that workbook has all sheets referenced in template_map.
    Returns list of error messages (empty if valid).
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
        sheet_names = set(wb.sheetnames)
        wb.close()
    except Exception as e:
        return [f"Cannot open workbook: {e}"]

    errors: list[str] = []
    for name in template_map.sheets:
        if name not in sheet_names:
            errors.append(f"Template requires sheet '{name}' but workbook does not have it.")
    return errors
