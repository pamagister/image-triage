"""Full triage pipeline: analyze, group, score, select, report and export."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from blake3 import blake3

from image_triage.analysis.analyze import ProgressCallback, analysis_signature, analyze_library
from image_triage.core.models import ExportMode, Run, RunStatus, Selection
from image_triage.core.settings import Settings
from image_triage.db.repository import Repository
from image_triage.export.export import export_photos
from image_triage.export.previews import write_previews
from image_triage.grouping.build import build_groups_and_events
from image_triage.report.csv_report import write_csv
from image_triage.report.json_report import build_report, write_report
from image_triage.scoring.score import score_library
from image_triage.selection.profiles import SelectionProfile, load_profile
from image_triage.selection.select import SelectedPhoto, select_photos


@dataclass(slots=True)
class PipelineResult:
    """Paths and counts produced by a full run."""

    run_id: str
    analyzed: int
    reused: int
    total: int
    selected: list[SelectedPhoto] = field(default_factory=list)
    report_path: Path | None = None
    csv_path: Path | None = None
    preview_paths: list[Path] = field(default_factory=list)
    export_paths: list[Path] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total": self.total,
            "analyzed": self.analyzed,
            "reused": self.reused,
            "selected": len(self.selected),
            "report": str(self.report_path) if self.report_path else None,
            "csv": str(self.csv_path) if self.csv_path else None,
            "previews": len(self.preview_paths),
            "exported": len(self.export_paths),
            "paths": [item.photo.path for item in self.selected],
        }


def selection_run_id(settings: Settings, photos: list, profile: SelectionProfile) -> str:
    """Deterministic run id for a selection over the current library."""
    material = "\x1f".join(
        [
            str(profile.top_n),
            profile.event_quota,
            *sorted(f"{photo.path}:{photo.digest}" for photo in photos),
        ]
    )
    encoded = "\x1f".join(
        ["run", settings.fingerprint(), analysis_signature(settings), material]
    ).encode("utf-8")
    return blake3(encoded).hexdigest()[:16]


def run_pipeline(
    settings: Settings,
    repository: Repository,
    *,
    output: Path,
    top_n: int | None = None,
    profile_name: str | None = None,
    export: bool = True,
    previews: bool | None = None,
    progress: ProgressCallback | None = None,
) -> PipelineResult:
    """Run the complete pipeline and write report, CSV, previews and export."""
    analysis = analyze_library(settings, repository, progress=progress)
    photos = build_groups_and_events(repository, settings)
    photos = score_library(repository, settings)

    overrides: dict[str, Any] = {}
    if top_n is not None:
        overrides["top_n"] = top_n
    profile = load_profile(settings, profile_name, overrides)
    selected = select_photos(photos, profile)

    run = Run(
        id=selection_run_id(settings, photos, profile),
        command="run",
        started_at=datetime.now(UTC),
        status=RunStatus.COMPLETED,
        config_hash=settings.fingerprint(),
        model_hashes=settings.model_hashes(),
        counts={
            "total": len(photos),
            "selected": len(selected),
            "groups": len({photo.group_id for photo in photos if photo.group_id is not None}),
            "events": len({photo.event_id for photo in photos if photo.event_id is not None}),
        },
    )
    repository.save_run(run)
    repository.set_selection(
        run.id,
        [
            Selection(
                photo_id=item.photo.id,
                rank=item.rank,
                score=item.score,
                reason=item.reason,
                quota_rule=item.quota_rule,
            )
            for item in selected
            if item.photo.id is not None
        ],
    )

    output.mkdir(parents=True, exist_ok=True)
    report = build_report(
        photos,
        [item.photo for item in selected],
        settings,
        run,
    )
    report_path = write_report(report, output / "report.json")
    csv_path = write_csv(photos, output / "selection.csv", settings.report.csv_columns)

    preview_paths = []
    use_previews = settings.report.previews if previews is None else previews
    if use_previews:
        preview_paths = write_previews(
            [item.photo for item in selected],
            Path(settings.cache_path) / "previews",
            settings,
        )

    export_paths = []
    if export:
        root = settings.watched_roots[0] if settings.watched_roots else Path(".")
        mode = ExportMode(settings.export.mode)
        export_paths = export_photos(
            [item.photo for item in selected],
            root,
            output / "originals",
            mode,
            layout=settings.export.layout,
            rerender=settings.export.rerender,
            max_long_edge=settings.export.max_long_edge,
            jpeg_quality=settings.export.jpeg_quality,
        )

    repository.finish_run(run)
    return PipelineResult(
        run_id=run.id,
        analyzed=analysis.analyzed,
        reused=analysis.reused,
        total=analysis.total,
        selected=selected,
        report_path=report_path,
        csv_path=csv_path,
        preview_paths=preview_paths,
        export_paths=export_paths,
    )
