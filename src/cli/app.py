"""
CLI run command: arguments per contracts/cli.md.
Exit codes: 0 success, 2 invalid input, 3 template mismatch, 4 critical failure.
"""
from __future__ import annotations

import logging
from pathlib import Path

import typer

from src.pipeline.run_context import RunContext, configure_logging
from src.pipeline.pdf_type import detect_pdf_type
from src.pipeline.reconstruct import reconstruct_document
from src.pipeline.ingest import load_document
from src.models.document import Document
from src.models.index_map import IndexMap
from src.pipeline.index_build import build_index_map
from src.pipeline.template_analyzer import write_template_map_from_workbook
from src.pipeline.populate.template_map import load_template_map, validate_template_against_workbook
from src.pipeline.populate.excel_writer import ExcelWriter
from src.pipeline.qa.run_report import write_run_report
from src.pipeline.extract.statements_raw import extract_statements_raw
from src.pipeline.locate.statements import locate_statements
from src.pipeline.locate.llm_planner import rank_candidates as llm_rank_candidates
from src.pipeline.targets.inventory import build_targets
from src.pipeline.locate.notes import locate_notes
from src.pipeline.extract.notes_raw import extract_notes
from src.pipeline.extract.gov_sections import extract_governance
from src.pipeline.extract.mdna import extract_mdna_blocks
from src.pipeline.interpret.interpretations import generate_interpretations
from src.llm.agent import planner_rank, reviewer_interpret
from src.models.phase3 import NotesLocatorResult, NotesRawResult, GovResult, InterpretationResult

# Exit codes per contract
EXIT_SUCCESS = 0
EXIT_INVALID_INPUT = 2
EXIT_TEMPLATE_MISMATCH = 3
EXIT_CRITICAL = 4

app = typer.Typer(help="Annual report → databook extraction")
logger = logging.getLogger(__name__)


# Default path for generated template map (from workbook analysis)
TEMPLATE_MAP_DIR = Path(__file__).resolve().parents[2] / "template_map"
DEFAULT_TEMPLATE_MAP_NAME = "knowledge_marine_v1.json"


def _ensure_template_map(template_xlsx: Path, template_map_path: Path | None) -> Path:
    """If template_map_path is provided and exists, use it. Else analyze template xlsx and write knowledge_marine_v1.json."""
    if template_map_path and Path(template_map_path).is_file():
        return Path(template_map_path)
    # Auto-analyze workbook and populate template_map/knowledge_marine_v1.json
    out_map = TEMPLATE_MAP_DIR / DEFAULT_TEMPLATE_MAP_NAME
    write_template_map_from_workbook(template_xlsx, out_map)
    return out_map


@app.command()
def version() -> None:
    """Show version."""
    typer.echo("0.1.0")


@app.command("run")
def run(
    pdf: Path = typer.Option(..., "--pdf", help="Annual report PDF path", path_type=Path),
    template: Path = typer.Option(..., "--template", help="Databook template xlsx path", path_type=Path),
    out: Path = typer.Option(..., "--out", help="Output directory", path_type=Path),
    scope: str = typer.Option("both", "--scope", help="standalone | consolidated | both"),
    company_name: str | None = typer.Option(None, "--company-name"),
    fy: str | None = typer.Option(None, "--fy"),
    max_pages: int | None = typer.Option(None, "--max-pages", help="For dev: limit pages"),
    no_ocr: bool = typer.Option(False, "--no-ocr", help="Force text-only, no OCR"),
    debug_pages: str | None = typer.Option(None, "--debug-pages"),
    debug: bool = typer.Option(False, "--debug"),
    template_map: Path | None = typer.Option(None, "--template-map", help="Pre-built template map JSON; else auto-analyze workbook"),
    locator_strategy: str = typer.Option("llm", "--locator-strategy", help="llm (default) | deterministic"),
    phase: int = typer.Option(3, "--phase", help="2 = statements only; 3 = full databook (notes, gov, MD&A)"),
    llm_mode: str = typer.Option("full", "--llm-mode", help="off | planner_only | full"),
    max_target_attempts: int = typer.Option(6, "--max-target-attempts", help="Max attempts per Phase 3 target"),
    ingest: str = typer.Option("marker", "--ingest", help="marker (default) | reconstruct"),
) -> None:
    """Run extraction: PDF → document → index → locator → populate → evidence pack."""
    _run_impl(
        pdf=pdf,
        template=template,
        out=out,
        scope=scope,
        company_name=company_name,
        fy=fy,
        max_pages=max_pages,
        no_ocr=no_ocr,
        debug_pages=debug_pages,
        debug=debug,
        template_map=template_map,
        locator_strategy=locator_strategy,
        phase=phase,
        llm_mode=llm_mode,
        max_target_attempts=max_target_attempts,
        ingest=ingest,
    )


def _run_impl(
    pdf: Path,
    template: Path,
    out: Path,
    scope: str = "both",
    company_name: str | None = None,
    fy: str | None = None,
    max_pages: int | None = None,
    no_ocr: bool = False,
    debug_pages: str | None = None,
    debug: bool = False,
    template_map: Path | None = None,
    locator_strategy: str = "llm",
    phase: int = 3,
    llm_mode: str = "full",
    max_target_attempts: int = 6,
    ingest: str = "marker",
) -> None:
    """Shared run implementation."""
    configure_logging(debug=debug)

    # Validate inputs → EXIT_INVALID_INPUT
    if not pdf.is_file():
        logger.error("PDF not found: %s", pdf)
        raise typer.Exit(EXIT_INVALID_INPUT)
    if not template.is_file():
        logger.error("Template not found: %s", template)
        raise typer.Exit(EXIT_INVALID_INPUT)
    out.mkdir(parents=True, exist_ok=True)

    # Ensure template map exists (auto-analyze workbook if needed)
    try:
        map_path = _ensure_template_map(template, template_map)
    except Exception as e:
        logger.exception("Template map analysis failed: %s", e)
        raise typer.Exit(EXIT_CRITICAL)

    # Load template map and validate against workbook → EXIT_TEMPLATE_MISMATCH
    try:
        tm = load_template_map(map_path)
        errors = validate_template_against_workbook(tm, template)
        if errors:
            for err in errors:
                logger.error(err)
            raise typer.Exit(EXIT_TEMPLATE_MISMATCH)
    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Template load/validate failed: %s", e)
        raise typer.Exit(EXIT_TEMPLATE_MISMATCH)

    # Run context: output_dir = out (contract: <out>/output_databook.xlsx, <out>/evidence_pack/...)
    ctx = RunContext.create(
        input_pdf_path=str(pdf),
        input_template_xlsx_path=str(template),
        output_dir=str(out),
        scope=scope,
        config={"no_ocr": no_ocr, "max_pages": max_pages},
    )
    ctx.ensure_run_folders()

    try:
        # 1) Document ingestion: Marker (default, local only) or reconstruct (legacy)
        doc_type = "mixed"
        if ingest == "marker":
            document = load_document(pdf, max_pages=max_pages)
            doc_type = document.meta.pdf_type
        else:
            doc_type, page_types = detect_pdf_type(pdf, max_pages=max_pages)
            document = reconstruct_document(
                pdf,
                doc_type=doc_type,
                page_types=page_types,
                max_pages=max_pages,
                run_ocr_for_image_pages=not no_ocr,
            )
        doc_path = ctx.evidence_pack_dir / "document.json"
        doc_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Wrote %s", doc_path)

        # 3) Index map
        index = build_index_map(
            document,
            company_name_override=company_name or None,
            fiscal_year_override=fy or None,
        )
        index_path = ctx.evidence_pack_dir / "index_map.json"
        index_path.write_text(index.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Wrote %s", index_path)

        # 4) Statement locator (BS/IS/CF)
        def _rank_fn(stmt_type: str, candidates: list, meta: dict):
            ranked, _mode, _rationale = llm_rank_candidates(stmt_type, candidates, meta)
            return ranked
        locator_result = locate_statements(
            document,
            index,
            scope=scope,
            strategy=locator_strategy,
            rank_candidates_fn=_rank_fn if locator_strategy == "llm" else None,
        )
        locator_path = ctx.extractions_dir / "statements_locator.json"
        locator_path.write_text(locator_result.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Wrote %s", locator_path)

        # 5) Statements raw: use locator result only (no index_map for selection)
        statements_extraction, statements_write_specs = extract_statements_raw(
            document, index, locator_result, scope=scope
        )
        extraction_path = ctx.extractions_dir / "statements_raw.json"
        extraction_path.write_text(
            statements_extraction.model_dump_json(indent=2), encoding="utf-8"
        )
        logger.info("Wrote %s", extraction_path)

        # 6) Copy template and populate CF BS, CF IS, CF CFS with raw tables + evidence
        writer = ExcelWriter(template, tm)
        writer.load()
        for spec in statements_write_specs:
            sheet_name = spec["sheet_name"]
            if sheet_name not in tm.sheets:
                continue
            sheet_map = tm.sheets[sheet_name]
            start_row = sheet_map.header_row or 1
            grid = spec.get("grid") or []
            if grid:
                writer.write_table(sheet_name, start_row, grid, sheet_map)
                page_ref = f"p.{spec['page_start']}" if spec["page_start"] == spec["page_end"] else f"p.{spec['page_start']}-{spec['page_end']}"
                writer.write_evidence_for_table(
                    sheet_name,
                    start_row + 1,
                    page_ref=page_ref,
                    table_id=spec.get("table_id") or "",
                    confidence=spec.get("confidence") or "High",
                    sheet_map=sheet_map,
                )
                logger.info("Populated %s with table %s (%s rows)", sheet_name, spec.get("table_id"), len(grid))

        extraction_paths = [extraction_path, locator_path]
        phase3_missing: list[dict] = list(statements_extraction.missing)
        phase3_summary: dict = {
            "pdf_type": doc_type,
            "pages": len(document.pages),
            "statements_raw": len(statements_write_specs),
            "locator_strategy": locator_strategy,
        }

        if phase >= 3:
            targets = build_targets(tm)
            use_llm = llm_mode in ("planner_only", "full")
            cache_dir = ctx.llm_cache_dir if use_llm else None

            def _planner(target_id: str, meta: list, cache: Path | None):
                return planner_rank(target_id, meta, cache_dir=cache)[0]

            def _reviewer(kind: str, blocks: list, cache: Path | None):
                return reviewer_interpret(kind, blocks, cache_dir=cache)

            notes_locator_result: NotesLocatorResult = locate_notes(
                document,
                targets,
                strategy="llm" if use_llm else "deterministic",
                max_attempts=max_target_attempts,
                rank_candidates_fn=_planner if use_llm else None,
                cache_dir=cache_dir,
            )
            notes_locator_path = ctx.extractions_dir / "notes_locator.json"
            notes_locator_path.write_text(
                notes_locator_result.model_dump_json(indent=2), encoding="utf-8"
            )
            logger.info("Wrote notes_locator.json")
            extraction_paths.append(notes_locator_path)

            notes_raw_result: NotesRawResult = extract_notes(document, notes_locator_result)
            (ctx.extractions_dir / "notes_raw.json").write_text(
                notes_raw_result.model_dump_json(indent=2), encoding="utf-8"
            )
            extraction_paths.append(ctx.extractions_dir / "notes_raw.json")
            phase3_missing.extend(notes_raw_result.missing)

            gov_result: GovResult = extract_governance(
                document,
                targets,
                planner_rank_fn=_planner if use_llm else None,
                reviewer_fn=_reviewer if llm_mode == "full" else None,
                cache_dir=cache_dir,
                max_attempts=max_target_attempts,
            )
            (ctx.extractions_dir / "gov_sections.json").write_text(
                gov_result.model_dump_json(indent=2), encoding="utf-8"
            )
            extraction_paths.append(ctx.extractions_dir / "gov_sections.json")
            phase3_missing.extend(gov_result.missing)

            mdna_blocks = extract_mdna_blocks(
                document,
                planner_rank_fn=_planner if use_llm else None,
                cache_dir=cache_dir,
                max_attempts=max_target_attempts,
            )
            interp_result: InterpretationResult = generate_interpretations(
                mdna_blocks,
                note_entries=[e.model_dump() for e in notes_raw_result.entries],
                mode="full",
                reviewer_fn=_reviewer if llm_mode == "full" else None,
                cache_dir=cache_dir,
            )
            (ctx.extractions_dir / "interpretations.json").write_text(
                interp_result.model_dump_json(indent=2), encoding="utf-8"
            )
            extraction_paths.append(ctx.extractions_dir / "interpretations.json")

            phase3_summary["phase3_notes_found"] = len(notes_raw_result.entries)
            phase3_summary["phase3_gov_found"] = len(gov_result.entries)
            phase3_summary["phase3_mdna_blocks"] = len(mdna_blocks)
            phase3_summary["phase3_llm_mode"] = llm_mode

            for entry in notes_raw_result.entries:
                sheet_name = entry.sheet_name
                if sheet_name not in tm.sheets:
                    continue
                sheet_map = tm.sheets[sheet_name]
                start_row = sheet_map.header_row or 1
                writer.write_section_header(sheet_name, start_row, entry.sheet_name, entry.page_ref)
                if entry.grid:
                    writer.write_table(sheet_name, start_row + 1, entry.grid, sheet_map)
                    writer.write_evidence_for_table(
                        sheet_name, start_row + 2,
                        page_ref=entry.page_ref, table_id=entry.table_id,
                        confidence=entry.confidence, sheet_map=sheet_map,
                    )
                    logger.info("Populated note %s (%s rows)", sheet_name, len(entry.grid))

            for gov_entry in gov_result.entries:
                sheet_name = gov_entry.sheet_name
                if sheet_name not in tm.sheets:
                    try:
                        if sheet_name not in writer._wb.sheetnames:
                            writer._wb.create_sheet(sheet_name)
                    except Exception:
                        continue
                start_row = 1
                if gov_entry.page_refs:
                    writer.write_section_header(sheet_name, start_row, gov_entry.section_type, gov_entry.page_refs[0])
                for ch in gov_entry.changes[:15]:
                    start_row += 1
                    writer.write_cell(sheet_name, f"A{start_row}", f"{ch.name} ({ch.action})")
                    writer.write_cell(sheet_name, f"B{start_row}", ch.page_ref or "")

            if interp_result.mdna and (interp_result.mdna.revenue_drivers or interp_result.mdna.risks or interp_result.mdna.outlook):
                mdna_sheet = "MD&A"
                if mdna_sheet not in tm.sheets:
                    try:
                        if mdna_sheet not in writer._wb.sheetnames:
                            writer._wb.create_sheet(mdna_sheet)
                    except Exception:
                        mdna_sheet = next(iter(tm.sheets), "Sheet1")
                row = 1
                for section, bullets in [
                    ("Revenue drivers", [(b.text, b.page_ref) for b in interp_result.mdna.revenue_drivers]),
                    ("Margin drivers", [(b.text, b.page_ref) for b in interp_result.mdna.margin_drivers]),
                    ("KPIs", [(b.text, b.page_ref) for b in interp_result.mdna.kpis]),
                    ("Outlook", [(b.text, b.page_ref) for b in interp_result.mdna.outlook]),
                    ("Risks", [(b.text, b.page_ref) for b in interp_result.mdna.risks]),
                ]:
                    if bullets:
                        row = writer.write_interpretation_bullets(mdna_sheet, row, section, bullets)

        writer.save(ctx.output_databook_path)
        logger.info("Wrote %s", ctx.output_databook_path)

        # 7) Run report
        write_run_report(
            run_folder=ctx.run_folder,
            run_id=ctx.run_id,
            document_path=doc_path,
            index_map_path=index_path,
            extraction_paths=extraction_paths,
            coverage_summary=phase3_summary,
            missing_summary=phase3_missing,
        )
    except Exception as e:
        logger.exception("Pipeline failed: %s", e)
        raise typer.Exit(EXIT_CRITICAL)

    logger.info("Run complete. Run ID: %s", ctx.run_id)
    raise typer.Exit(EXIT_SUCCESS)


if __name__ == "__main__":
    app()
