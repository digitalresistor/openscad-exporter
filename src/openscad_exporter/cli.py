from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

from openscad_exporter import __version__
from openscad_exporter.converter import (
    CsvSchemaError,
    JsonOverwriteError,
    csv_to_customizer_json,
    default_params_to_csv,
)
from openscad_exporter.exporter import export_all
from openscad_exporter.models import CameraOptions, ExportFormat
from openscad_exporter.openscad import (
    OpenScadNotFoundError,
    discover_binary,
    dump_default_params,
)

_console = Console(stderr=True)
log = logging.getLogger("openscad_exporter")

_FORMAT_CHOICES = [f.value for f in ExportFormat]


def _setup_logging(verbose: int) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=_console, show_path=False, markup=True)],
    )


def _resolve_binary(override: str | None) -> Path:
    try:
        return discover_binary(Path(override) if override else None)
    except OpenScadNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="openscad-exporter")
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase logging verbosity (-v info, -vv debug).",
)
def cli(verbose: int) -> None:
    """Bulk-export OpenSCAD models from CSV or customizer JSON parameter sets."""
    _setup_logging(verbose)


# ---------------------------------------------------------------------------
# scad-to-csv
# ---------------------------------------------------------------------------
@cli.command("scad-to-csv")
@click.argument(
    "scad_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--output",
    "output_csv",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Path to write the resulting one-row CSV.",
)
@click.option(
    "--openscad-path",
    type=click.Path(dir_okay=False, path_type=str),
    default=None,
    help="Path to the openscad executable.",
)
def scad_to_csv(scad_path: Path, output_csv: Path, openscad_path: str | None) -> None:
    """Generate a single-row CSV of SCAD_PATH's default customizer parameters."""
    binary = _resolve_binary(openscad_path)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        dump_default_params(binary, scad_path, tmp_path)
        count = default_params_to_csv(tmp_path, output_csv)
    finally:
        tmp_path.unlink(missing_ok=True)
    click.echo(f"Wrote {output_csv} ({count} parameters).")


# ---------------------------------------------------------------------------
# csv-to-json
# ---------------------------------------------------------------------------
@cli.command("csv-to-json")
@click.argument(
    "csv_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--scad",
    "scad_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the .scad file (used to derive the default JSON output location).",
)
@click.option(
    "--output",
    "output_json",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to write the customizer JSON (defaults to <scad-stem>.json beside the .scad).",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite the output JSON if it already exists.",
)
def csv_to_json(
    csv_path: Path,
    scad_path: Path,
    output_json: Path | None,
    force: bool,
) -> None:
    """Convert a CSV of parameter sets into an OpenSCAD customizer JSON."""
    target = output_json or scad_path.with_suffix(".json")
    try:
        count = csv_to_customizer_json(csv_path, target, force=force)
    except JsonOverwriteError as exc:
        raise click.ClickException(str(exc)) from exc
    except CsvSchemaError as exc:
        raise click.ClickException(f"Invalid CSV: {exc}") from exc
    click.echo(f"Wrote {target} ({count} parameter sets).")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------
def _validate_camera_flags_only_with_png(
    *,
    fmt: ExportFormat,
    camera: CameraOptions,
) -> None:
    if fmt is ExportFormat.PNG:
        return
    if camera.is_empty():
        return
    used = []
    if camera.camera is not None:
        used.append("--camera")
    if camera.imgsize is not None:
        used.append("--imgsize")
    if camera.colorscheme is not None:
        used.append("--colorscheme")
    if camera.viewall:
        used.append("--viewall")
    if camera.render:
        used.append("--render")
    raise click.UsageError(
        f"Camera flag(s) {', '.join(used)} are only valid with --format png "
        f"(got --format {fmt.value})."
    )


@cli.command("export")
@click.argument(
    "scad_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Directory to write exported files into (created if missing).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(_FORMAT_CHOICES, case_sensitive=False),
    default=ExportFormat.STL.value,
    show_default=True,
    help="Output file format.",
)
@click.option(
    "--from-csv",
    "from_csv",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="CSV of parameter sets. Mutually exclusive with --from-json.",
)
@click.option(
    "--from-json",
    "from_json",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Existing customizer JSON. Mutually exclusive with --from-csv.",
)
@click.option("--force", is_flag=True, help="Overwrite existing output files.")
@click.option(
    "--concurrency",
    type=click.IntRange(min=1),
    default=8,
    show_default=True,
    help="Maximum number of parallel openscad processes.",
)
@click.option(
    "--openscad-path",
    type=click.Path(dir_okay=False, path_type=str),
    default=None,
    help="Path to the openscad executable.",
)
@click.option(
    "--camera",
    "camera_arg",
    default=None,
    help="Camera tuple tx,ty,tz,rx,ry,rz,dist (PNG only).",
)
@click.option(
    "--imgsize",
    default=None,
    help="Image size WIDTH,HEIGHT (PNG only).",
)
@click.option(
    "--colorscheme",
    default=None,
    help="OpenSCAD color scheme name (PNG only).",
)
@click.option("--viewall", is_flag=True, help="Pass --viewall to openscad (PNG only).")
@click.option("--render", is_flag=True, help="Pass --render to openscad (PNG only).")
def export(
    scad_path: Path,
    output_dir: Path,
    fmt: str,
    from_csv: Path | None,
    from_json: Path | None,
    force: bool,
    concurrency: int,
    openscad_path: str | None,
    camera_arg: str | None,
    imgsize: str | None,
    colorscheme: str | None,
    viewall: bool,
    render: bool,
) -> None:
    """Export every parameter set in --from-csv or --from-json to OUTPUT_DIR."""
    if (from_csv is None) == (from_json is None):
        raise click.UsageError("Provide exactly one of --from-csv or --from-json.")

    format_enum = ExportFormat(fmt)
    try:
        camera = CameraOptions(
            camera=camera_arg,
            imgsize=imgsize,
            colorscheme=colorscheme,
            viewall=viewall,
            render=render,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    _validate_camera_flags_only_with_png(fmt=format_enum, camera=camera)

    binary = _resolve_binary(openscad_path)

    if from_csv is not None:
        json_path = scad_path.with_suffix(".json")
        try:
            csv_to_customizer_json(from_csv, json_path, force=force)
        except JsonOverwriteError as exc:
            raise click.ClickException(
                f"{exc} (the JSON next to the .scad is rewritten from --from-csv)."
            ) from exc
        except CsvSchemaError as exc:
            raise click.ClickException(f"Invalid CSV: {exc}") from exc
    else:
        assert from_json is not None
        json_path = from_json

    summary = asyncio.run(
        export_all(
            scad_path=scad_path,
            json_path=json_path,
            output_dir=output_dir,
            fmt=format_enum,
            binary=binary,
            camera=camera if not camera.is_empty() else None,
            overwrite=force,
            concurrency=concurrency,
            console=_console,
        )
    )

    click.echo(
        f"Exported: {len(summary.exported)}  "
        f"Skipped: {len(summary.skipped)}  "
        f"Failed: {len(summary.failed)}  "
        f"Total: {summary.total}"
    )
    if summary.failed:
        for name, msg in summary.failed:
            click.echo(f"  FAILED {name}: {msg}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
