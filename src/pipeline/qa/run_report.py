"""
Run report generator: coverage + missing summary.
Produces evidence_pack/run_report.md.
Per T012.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def generate_run_report(
    run_id: str,
    output_dir: Path,
    document_path: Optional[Path] = None,
    index_map_path: Optional[Path] = None,
    extraction_paths: Optional[list[Path]] = None,
    coverage_summary: Optional[dict[str, Any]] = None,
    missing_summary: Optional[list[dict[str, Any]]] = None,
) -> str:
    """
    Generate run_report.md content. Writes to output_dir/evidence_pack/run_report.md
    if output_dir is the run folder; else just returns content.
    """
    lines = [
        "# Run Report",
        "",
        f"- **Run ID**: {run_id}",
        "",
        "## Outputs",
        "",
    ]
    if document_path and document_path.exists():
        lines.append(f"- Document: `{document_path.name}`")
    if index_map_path and index_map_path.exists():
        lines.append(f"- Index map: `{index_map_path.name}`")
    if extraction_paths:
        lines.append("- Extractions:")
        for ep in extraction_paths:
            if ep.exists():
                lines.append(f"  - `{ep.name}`")
    lines.extend(["", "## Coverage", ""])
    if coverage_summary:
        for k, v in coverage_summary.items():
            lines.append(f"- **{k}**: {v}")
        if "phase3_notes_found" in coverage_summary:
            lines.extend([
                "",
                "## Phase 3 coverage",
                "",
                f"- Notes populated: {coverage_summary.get('phase3_notes_found', 0)}",
                f"- Governance sections: {coverage_summary.get('phase3_gov_found', 0)}",
                f"- MD&A blocks extracted: {coverage_summary.get('phase3_mdna_blocks', 0)}",
                f"- LLM mode: {coverage_summary.get('phase3_llm_mode', 'N/A')}",
                "",
            ])
    else:
        lines.append("- (No coverage data)")
    lines.extend(["", "## Missing / NOT FOUND", ""])
    if missing_summary:
        for m in missing_summary:
            field = m.get("field", "?")
            reason = m.get("reason", "")
            lines.append(f"- **{field}**: {reason}")
    else:
        lines.append("- (None)")
    lines.append("")
    return "\n".join(lines)


def write_run_report(
    run_folder: Path,
    run_id: str,
    document_path: Optional[Path] = None,
    index_map_path: Optional[Path] = None,
    extraction_paths: Optional[list[Path]] = None,
    coverage_summary: Optional[dict[str, Any]] = None,
    missing_summary: Optional[list[dict[str, Any]]] = None,
) -> Path:
    """Write run_report.md into run_folder/evidence_pack/run_report.md."""
    evidence_pack = run_folder / "evidence_pack"
    evidence_pack.mkdir(parents=True, exist_ok=True)
    report_path = evidence_pack / "run_report.md"
    content = generate_run_report(
        run_id=run_id,
        output_dir=run_folder,
        document_path=document_path,
        index_map_path=index_map_path,
        extraction_paths=extraction_paths,
        coverage_summary=coverage_summary,
        missing_summary=missing_summary,
    )
    report_path.write_text(content, encoding="utf-8")
    logger.info("Wrote run report to %s", report_path)
    return report_path
