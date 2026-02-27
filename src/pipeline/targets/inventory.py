"""
Target inventory from template_map. Builds list of targets for notes, governance, MD&A.
Per FR-001; tasks T301, T302.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.models.template_map import SheetMap, TemplateMap
from src.models.phase3 import TargetSpec

logger = logging.getLogger(__name__)

# Priority note topics and their anchor/synonym keywords
NOTE_TOPIC_ANCHORS: dict[str, list[str]] = {
    "revenue": ["revenue", "sales", "income from operations", "note on revenue"],
    "ppe": ["property, plant and equipment", "ppe", "fixed assets", "tangible assets"],
    "borrowings": ["borrowings", "loans", "secured loan", "unsecured loan"],
    "expenses": ["other expenses", "operating expenses", "employee benefits expense"],
    "working_capital": ["inventories", "trade receivables", "working capital"],
    "rpt": ["related party", "related parties", "rpt", "transactions with related"],
    "segment": ["segment information", "business segments", "geographical segments"],
}

NOTE_TOPIC_SYNONYMS: dict[str, list[str]] = {
    "revenue": ["Note 20", "Revenue from operations", "Sale of products"],
    "ppe": ["Note 3", "Property Plant Equipment", "Fixed assets"],
    "borrowings": ["Note 11", "Borrowings", "Long-term borrowings"],
    "expenses": ["Note 24", "Other expenses"],
    "working_capital": ["Note 10", "Inventories", "Trade receivables"],
    "rpt": ["Note 33", "Related party transactions"],
    "segment": ["Note 31", "Segment reporting"],
}

# Governance targets (may not be in template_map sheets)
GOVERNANCE_SHEETS = [
    ("corp_structure", "Corporate structure", "narrative", ["corporate structure", "subsidiary", "holding company"]),
    ("shareholding", "Shareholding", "mixed", ["shareholding pattern", "promoter", "public shareholding"]),
    ("directors", "Directors", "mixed", ["board of directors", "directors' report", "appointment", "resignation"]),
    ("kmp", "KMP", "mixed", ["key managerial personnel", "kmp", "company secretary", "cfo"]),
]

# MD&A single target
MDNA_TARGET_ID = "mdna"
MDNA_ANCHORS = ["management discussion", "management's discussion", "business overview", "operational highlights", "md&a"]


def _sheet_to_target(sheet_name: str, sheet_map: SheetMap) -> TargetSpec | None:
    """Convert a template_map sheet to a TargetSpec if it is a note or interpretable target."""
    sheet_type = (sheet_map.type or "").strip().lower()
    topic = (sheet_map.topic or "").strip().lower() or None
    statement = (sheet_map.statement or "").strip().lower() or None

    # Phase 2 statements: skip (handled by statement locator)
    if sheet_type == "financial_statement" and statement in ("balance_sheet", "income_statement", "cash_flow"):
        return None

    target_id = sheet_name.replace(" ", "_").lower()
    content_type = "table"
    if sheet_type == "governance":
        content_type = "mixed"
    anchors = list(NOTE_TOPIC_ANCHORS.get(topic, [])) if topic else []
    synonyms = list(NOTE_TOPIC_SYNONYMS.get(topic, [])) if topic else []
    if not anchors and topic:
        anchors = [topic.replace("_", " ")]

    return TargetSpec(
        target_id=target_id,
        sheet_name=sheet_name,
        content_type=content_type,
        topic=topic or None,
        expected_anchors=anchors,
        synonyms=synonyms,
        paste_anchor_cell=sheet_map.anchor_cell,
        header_row=sheet_map.header_row,
        evidence_cols=sheet_map.evidence_cols or [],
        validation_min_cols=2,
        validation_min_density=0.03,
    )


def build_targets(template_map: TemplateMap) -> list[TargetSpec]:
    """
    Build list of targets from template_map.
    Includes: note tabs (from sheets with topic), governance targets, MD&A.
    """
    targets: list[TargetSpec] = []

    # From sheets: note_rollup and governance
    for sheet_name, sheet_map in template_map.sheets.items():
        t = _sheet_to_target(sheet_name, sheet_map)
        if t is not None:
            targets.append(t)

    # Add governance targets if not already present
    existing_sheets = {t.sheet_name.lower() for t in targets}
    for target_id, sheet_name, content_type, anchors in GOVERNANCE_SHEETS:
        if sheet_name.lower() not in existing_sheets:
            targets.append(
                TargetSpec(
                    target_id=target_id,
                    sheet_name=sheet_name,
                    content_type=content_type,
                    topic=target_id,
                    expected_anchors=anchors,
                    synonyms=[],
                    validation_min_cols=2,
                    validation_min_density=0.02,
                )
            )

    # MD&A interpretation target (always add)
    if not any(t.target_id == MDNA_TARGET_ID for t in targets):
        targets.append(
            TargetSpec(
                target_id=MDNA_TARGET_ID,
                sheet_name="MD&A",
                content_type="interpretation",
                topic="mdna",
                expected_anchors=MDNA_ANCHORS,
                synonyms=["management discussion and analysis", "business overview"],
                validation_min_cols=0,
                validation_min_density=0.02,
            )
        )

    return targets


def load_targets_from_template_map(template_map_path: str | Path) -> tuple[list[TargetSpec], TemplateMap]:
    """Load template_map JSON and build targets. Returns (targets, template_map)."""
    from src.pipeline.populate.template_map import load_template_map
    tm = load_template_map(template_map_path)
    targets = build_targets(tm)
    return targets, tm


def validate_template_map_schema(data: dict[str, Any]) -> list[str]:
    """Validate template_map-like dict has required structure. Return list of errors."""
    errors: list[str] = []
    if not isinstance(data.get("sheets"), dict):
        errors.append("template_map must have 'sheets' object")
    return errors
