from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from openscad_exporter.converter import load_parameter_set_names
from openscad_exporter.models import CameraOptions, ExportFormat, ExportSummary
from openscad_exporter.openscad import (
    build_export_args,
    output_filename_for,
    run_openscad,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PlannedExport:
    param_set: str
    output_path: Path
    args: list[str]


class UnsafeOutputPathError(ValueError):
    """A parameter set's name resolves to a path outside the output directory."""


def _resolve_output_path(output_dir: Path, name: str, fmt: ExportFormat) -> Path:
    """Build an output path that may contain slash-delimited subdirectories.

    Rejects names whose resolved path would escape ``output_dir`` (e.g. via ``..``).
    """
    filename = output_filename_for(name, fmt)
    candidate = (output_dir / filename).resolve()
    base = output_dir.resolve()
    if base != candidate and base not in candidate.parents:
        raise UnsafeOutputPathError(
            f"exported_filename {name!r} resolves outside the output directory."
        )
    return candidate


def _plan_exports(
    *,
    scad_path: Path,
    json_path: Path,
    output_dir: Path,
    fmt: ExportFormat,
    camera: CameraOptions | None,
    overwrite: bool,
) -> tuple[list[_PlannedExport], list[str]]:
    """Return (jobs to run, names that will be skipped because the file exists)."""
    names = load_parameter_set_names(json_path)
    jobs: list[_PlannedExport] = []
    skipped: list[str] = []
    for name in names:
        out_path = _resolve_output_path(output_dir, name, fmt)
        if out_path.exists() and not overwrite:
            skipped.append(name)
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        args = build_export_args(
            output_path=out_path,
            scad_path=scad_path,
            json_params_path=json_path,
            param_set=name,
            camera=camera,
        )
        jobs.append(_PlannedExport(param_set=name, output_path=out_path, args=args))
    return jobs, skipped


async def export_all(
    *,
    scad_path: Path,
    json_path: Path,
    output_dir: Path,
    fmt: ExportFormat,
    binary: Path,
    camera: CameraOptions | None = None,
    overwrite: bool = False,
    concurrency: int = 8,
    console: Console | None = None,
) -> ExportSummary:
    """Run all parameter-set exports in parallel under a semaphore."""
    output_dir.mkdir(parents=True, exist_ok=True)
    jobs, skipped = _plan_exports(
        scad_path=scad_path,
        json_path=json_path,
        output_dir=output_dir,
        fmt=fmt,
        camera=camera,
        overwrite=overwrite,
    )
    summary = ExportSummary(skipped=skipped)

    if not jobs:
        return summary

    semaphore = asyncio.Semaphore(concurrency)
    use_progress = console is not None

    progress = (
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )
        if use_progress
        else None
    )
    task_id = None
    if progress is not None:
        progress.start()
        task_id = progress.add_task(
            f"Exporting {fmt.value.upper()}",
            total=len(jobs),
        )

    async def _run_one(job: _PlannedExport) -> None:
        async with semaphore:
            try:
                rc, _stdout, stderr = await run_openscad(binary, job.args)
            except Exception as exc:
                summary.failed.append((job.param_set, f"subprocess error: {exc}"))
                log.exception("Failed to launch openscad for %s", job.param_set)
            else:
                if rc != 0:
                    msg = stderr.decode(errors="replace").strip() or f"exit code {rc}"
                    summary.failed.append((job.param_set, msg))
                    log.error("openscad failed for %s: %s", job.param_set, msg)
                else:
                    summary.exported.append(job.param_set)
                    log.debug("Exported %s -> %s", job.param_set, job.output_path)
            if progress is not None and task_id is not None:
                progress.update(task_id, advance=1)

    try:
        await asyncio.gather(*(_run_one(job) for job in jobs))
    finally:
        if progress is not None:
            progress.stop()

    return summary
