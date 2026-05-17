"""End-to-end tests that drive a real OpenSCAD binary.

Skipped unless an `openscad` binary is on PATH (or installed at the macOS app
location). Run explicitly with:

    pytest -m integration

The CI workflow installs OpenSCAD before invoking this marker.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from openscad_exporter.cli import cli

pytestmark = pytest.mark.integration


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def scad_in_tmp(tmp_path: Path, rocket_scad: Path) -> Path:
    """Copy rocket.scad into tmp_path so the auto-generated `<stem>.json` lands there."""
    dest = tmp_path / rocket_scad.name
    shutil.copy(rocket_scad, dest)
    return dest


def _looks_like_stl(data: bytes) -> bool:
    # ASCII STL starts with "solid "; binary STL is 80-byte header + uint32 count.
    if data.startswith(b"solid "):
        return True
    return len(data) >= 84


def _looks_like_3mf(data: bytes) -> bool:
    # 3MF is a zip — local file header magic.
    return data.startswith(b"PK\x03\x04")


def _looks_like_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


def test_scad_to_csv_then_csv_to_json_round_trip(
    runner: CliRunner,
    tmp_path: Path,
    rocket_scad: Path,
    real_openscad_or_skip: str,
) -> None:
    """Dump defaults to CSV, then convert the CSV into a customizer JSON."""
    csv_path = tmp_path / "defaults.csv"
    result = runner.invoke(
        cli,
        [
            "scad-to-csv",
            str(rocket_scad),
            "--output",
            str(csv_path),
            "--openscad-path",
            real_openscad_or_skip,
        ],
    )
    assert result.exit_code == 0, result.output

    json_path = tmp_path / "rocket.json"
    result = runner.invoke(
        cli,
        [
            "csv-to-json",
            str(csv_path),
            "--scad",
            str(rocket_scad),
            "--output",
            str(json_path),
        ],
    )
    assert result.exit_code == 0, result.output

    doc = json.loads(json_path.read_text())
    assert doc["fileFormatVersion"] == "1"
    assert "default" in doc["parameterSets"]
    assert "rocket_d" in doc["parameterSets"]["default"]


def test_export_stl_produces_real_geometry(
    runner: CliRunner,
    tmp_path: Path,
    scad_in_tmp: Path,
    real_openscad_or_skip: str,
) -> None:
    csv_path = tmp_path / "params.csv"
    csv_path.write_text(
        "exported_filename,rocket_h,many\n"
        "short,60,3\n"
        "tall,150,4\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    result = runner.invoke(
        cli,
        [
            "export",
            str(scad_in_tmp),
            "--from-csv",
            str(csv_path),
            "--output-dir",
            str(out_dir),
            "--format",
            "stl",
            "--openscad-path",
            real_openscad_or_skip,
        ],
    )
    assert result.exit_code == 0, result.output

    for name in ("short", "tall"):
        path = out_dir / f"{name}.stl"
        assert path.is_file(), f"missing output: {path}"
        data = path.read_bytes()
        assert _looks_like_stl(data), f"{path} does not look like an STL file"
        assert len(data) > 1000, f"{path} suspiciously small: {len(data)} bytes"


def test_export_3mf_produces_valid_archive(
    runner: CliRunner,
    tmp_path: Path,
    scad_in_tmp: Path,
    real_openscad_or_skip: str,
) -> None:
    csv_path = tmp_path / "params.csv"
    csv_path.write_text(
        "exported_filename,rocket_h\nmodel,80\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    result = runner.invoke(
        cli,
        [
            "export",
            str(scad_in_tmp),
            "--from-csv",
            str(csv_path),
            "--output-dir",
            str(out_dir),
            "--format",
            "3mf",
            "--openscad-path",
            real_openscad_or_skip,
        ],
    )
    assert result.exit_code == 0, result.output

    data = (out_dir / "model.3mf").read_bytes()
    assert _looks_like_3mf(data), "output does not look like a 3MF zip archive"


def test_export_png_with_camera_flags(
    runner: CliRunner,
    tmp_path: Path,
    scad_in_tmp: Path,
    real_openscad_or_skip: str,
) -> None:
    csv_path = tmp_path / "params.csv"
    csv_path.write_text(
        "exported_filename,rocket_h\npreview,90\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    result = runner.invoke(
        cli,
        [
            "export",
            str(scad_in_tmp),
            "--from-csv",
            str(csv_path),
            "--output-dir",
            str(out_dir),
            "--format",
            "png",
            "--viewall",
            "--imgsize",
            "256,256",
            "--openscad-path",
            real_openscad_or_skip,
        ],
    )
    assert result.exit_code == 0, result.output

    data = (out_dir / "preview.png").read_bytes()
    assert _looks_like_png(data), "output does not look like a PNG"


def test_export_nested_directory_layout(
    runner: CliRunner,
    tmp_path: Path,
    scad_in_tmp: Path,
    real_openscad_or_skip: str,
) -> None:
    """Slashed exported_filename values become subdirectories under --output-dir."""
    csv_path = tmp_path / "params.csv"
    csv_path.write_text(
        "exported_filename,rocket_h\n"
        "small/v1,60\n"
        "small/v2,70\n"
        "large/v1,150\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    result = runner.invoke(
        cli,
        [
            "export",
            str(scad_in_tmp),
            "--from-csv",
            str(csv_path),
            "--output-dir",
            str(out_dir),
            "--format",
            "stl",
            "--openscad-path",
            real_openscad_or_skip,
        ],
    )
    assert result.exit_code == 0, result.output

    for relative in ("small/v1.stl", "small/v2.stl", "large/v1.stl"):
        path = out_dir / relative
        assert path.is_file(), f"missing output: {path}"
        assert _looks_like_stl(path.read_bytes())


def test_export_from_json_skips_existing_without_force(
    runner: CliRunner,
    tmp_path: Path,
    rocket_scad: Path,
    real_openscad_or_skip: str,
) -> None:
    """Re-running export without --force preserves existing files."""
    json_path = tmp_path / "rocket.json"
    json_path.write_text(
        json.dumps(
            {
                "parameterSets": {
                    "a": {"rocket_h": "70"},
                    "b": {"rocket_h": "90"},
                },
                "fileFormatVersion": "1",
            }
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    first = runner.invoke(
        cli,
        [
            "export",
            str(rocket_scad),
            "--from-json",
            str(json_path),
            "--output-dir",
            str(out_dir),
            "--format",
            "stl",
            "--openscad-path",
            real_openscad_or_skip,
        ],
    )
    assert first.exit_code == 0, first.output
    a_first_bytes = (out_dir / "a.stl").read_bytes()

    sentinel = b"PREEXISTING"
    (out_dir / "a.stl").write_bytes(sentinel)

    second = runner.invoke(
        cli,
        [
            "export",
            str(rocket_scad),
            "--from-json",
            str(json_path),
            "--output-dir",
            str(out_dir),
            "--format",
            "stl",
            "--openscad-path",
            real_openscad_or_skip,
        ],
    )
    assert second.exit_code == 0, second.output
    assert (out_dir / "a.stl").read_bytes() == sentinel, "a.stl was overwritten without --force"
    # b should still be a real STL (rendered on the second run or unchanged from the first).
    assert _looks_like_stl((out_dir / "b.stl").read_bytes())
    # Sanity: the first run did produce real STL for a.
    assert _looks_like_stl(a_first_bytes)
