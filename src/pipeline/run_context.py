"""
Run context: run_id, output paths, logging baseline, and run folder creation.
Per specs/001-annual-report-databook-agent/data-model.md RunContext.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class RunContext:
    """One execution instance; inputs, config, outputs, timings."""

    run_id: str
    input_pdf_path: str
    input_template_xlsx_path: str
    scope: str  # standalone | consolidated | both
    output_dir: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    config: dict = field(default_factory=dict)

    @property
    def output_root(self) -> Path:
        return Path(self.output_dir)

    @property
    def run_folder(self) -> Path:
        """Output directory for this run (contract: <out>/output_databook.xlsx, <out>/evidence_pack/)."""
        return self.output_root

    @property
    def evidence_pack_dir(self) -> Path:
        return self.run_folder / "evidence_pack"

    @property
    def extractions_dir(self) -> Path:
        return self.evidence_pack_dir / "extractions"

    @property
    def tables_dir(self) -> Path:
        return self.evidence_pack_dir / "tables"

    @property
    def snippets_dir(self) -> Path:
        return self.evidence_pack_dir / "snippets"

    @property
    def output_databook_path(self) -> Path:
        return self.run_folder / "output_databook.xlsx"

    @property
    def llm_cache_dir(self) -> Path:
        return self.run_folder / "llm_cache"

    def ensure_run_folders(self) -> None:
        """Create run folder and evidence_pack subdirs."""
        self.run_folder.mkdir(parents=True, exist_ok=True)
        self.evidence_pack_dir.mkdir(parents=True, exist_ok=True)
        self.extractions_dir.mkdir(parents=True, exist_ok=True)
        self.tables_dir.mkdir(parents=True, exist_ok=True)
        self.snippets_dir.mkdir(parents=True, exist_ok=True)
        self.llm_cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(
        cls,
        input_pdf_path: str,
        input_template_xlsx_path: str,
        output_dir: str,
        scope: str = "both",
        run_id: str | None = None,
        **config,
    ) -> RunContext:
        rid = run_id or str(uuid.uuid4())[:8]
        return cls(
            run_id=rid,
            input_pdf_path=input_pdf_path,
            input_template_xlsx_path=input_template_xlsx_path,
            scope=scope,
            output_dir=output_dir,
            config=config,
        )


def configure_logging(debug: bool = False) -> None:
    """Baseline logging: JSON-friendly format optional; here use stdlib."""
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%dT%H:%M:%S")
    # Reduce noise from third-party libs
    logging.getLogger("pdfminer").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
