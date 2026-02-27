"""Unit tests for Phase 3 target inventory. No LLM calls."""
from __future__ import annotations

import pytest
from pathlib import Path

from src.pipeline.targets.inventory import (
    build_targets,
    load_targets_from_template_map,
    validate_template_map_schema,
    MDNA_TARGET_ID,
)
from src.models.template_map import TemplateMap, SheetMap


def test_build_targets_includes_note_and_mdna():
    tm = TemplateMap(
        workbook_name="test.xlsx",
        sheets={
            "CF BS": SheetMap(type="financial_statement", statement="balance_sheet"),
            "Revenue & OI": SheetMap(type="note_rollup", topic="revenue", header_row=1),
            "PPE": SheetMap(type="note_rollup", topic="ppe", header_row=1),
        },
    )
    targets = build_targets(tm)
    # CF BS skipped (statement); Revenue, PPE as notes; MD&A added
    note_ids = [t.target_id for t in targets if t.content_type == "table" or t.topic]
    assert "revenue_&_oi" in note_ids or any("revenue" in (t.topic or "") for t in targets)
    assert any(t.target_id == MDNA_TARGET_ID for t in targets)


def test_load_targets_from_template_map(tmp_path):
    json_path = tmp_path / "tm.json"
    json_path.write_text('{"workbook_name": "x", "sheets": {"Sheet1": {"type": "note_rollup"}}}')
    targets, tm = load_targets_from_template_map(json_path)
    assert len(tm.sheets) == 1
    assert len(targets) >= 1  # at least Sheet1 or MD&A


def test_validate_template_map_schema():
    assert len(validate_template_map_schema({})) > 0
    assert len(validate_template_map_schema({"sheets": {}})) == 0
