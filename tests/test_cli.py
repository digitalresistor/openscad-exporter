from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from openscad_exporter.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write_scad(path: Path) -> Path:
    path.write_text("a = 1;\nb = 2;\ncube([a, b, 1]);\n")
    return path


def _write_csv(path: Path) -> Path:
    path.write_text("exported_filename,a,b\nfoo,3,4\nbar,5,6\n", encoding="utf-8")
    return path


def test_help(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "scad-to-csv" in result.output
    assert "csv-to-json" in result.output
    assert "export" in result.output


def test_csv_to_json_command(runner: CliRunner, tmp_path: Path) -> None:
    scad = _write_scad(tmp_path / "m.scad")
    csv_path = _write_csv(tmp_path / "p.csv")
    out_json = tmp_path / "p.json"

    result = runner.invoke(
        cli,
        ["csv-to-json", str(csv_path), "--scad", str(scad), "--output", str(out_json)],
    )

    assert result.exit_code == 0, result.output
    doc = json.loads(out_json.read_text())
    assert set(doc["parameterSets"].keys()) == {"foo", "bar"}
    assert doc["fileFormatVersion"] == "1"


def test_csv_to_json_requires_force_when_target_exists(runner: CliRunner, tmp_path: Path) -> None:
    scad = _write_scad(tmp_path / "m.scad")
    csv_path = _write_csv(tmp_path / "p.csv")
    out_json = tmp_path / "p.json"
    out_json.write_text("{}")

    result = runner.invoke(
        cli,
        ["csv-to-json", str(csv_path), "--scad", str(scad), "--output", str(out_json)],
    )
    assert result.exit_code != 0
    assert "force" in result.output.lower()

    result_force = runner.invoke(
        cli,
        [
            "csv-to-json",
            str(csv_path),
            "--scad",
            str(scad),
            "--output",
            str(out_json),
            "--force",
        ],
    )
    assert result_force.exit_code == 0, result_force.output


def test_export_camera_flag_rejected_without_png(
    runner: CliRunner,
    tmp_path: Path,
    stub_openscad: Path,
) -> None:
    scad = _write_scad(tmp_path / "m.scad")
    json_path = tmp_path / "m.json"
    json_path.write_text(
        json.dumps({"parameterSets": {"foo": {"a": "1"}}, "fileFormatVersion": "1"})
    )

    result = runner.invoke(
        cli,
        [
            "export",
            str(scad),
            "--from-json",
            str(json_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--format",
            "stl",
            "--viewall",
            "--openscad-path",
            str(stub_openscad),
        ],
    )
    assert result.exit_code != 0
    assert "--viewall" in result.output
    assert "--format png" in result.output


def test_export_requires_one_of_from_csv_or_from_json(
    runner: CliRunner,
    tmp_path: Path,
    stub_openscad: Path,
) -> None:
    scad = _write_scad(tmp_path / "m.scad")
    result = runner.invoke(
        cli,
        [
            "export",
            str(scad),
            "--output-dir",
            str(tmp_path / "out"),
            "--openscad-path",
            str(stub_openscad),
        ],
    )
    assert result.exit_code != 0
    assert "from-csv" in result.output or "from-json" in result.output


def test_export_with_from_json_uses_stub(
    runner: CliRunner,
    tmp_path: Path,
    stub_openscad: Path,
) -> None:
    scad = _write_scad(tmp_path / "m.scad")
    json_path = tmp_path / "m.json"
    json_path.write_text(
        json.dumps(
            {
                "parameterSets": {"a": {"x": "1"}, "b": {"x": "2"}},
                "fileFormatVersion": "1",
            }
        )
    )
    out_dir = tmp_path / "out"

    result = runner.invoke(
        cli,
        [
            "export",
            str(scad),
            "--from-json",
            str(json_path),
            "--output-dir",
            str(out_dir),
            "--format",
            "stl",
            "--openscad-path",
            str(stub_openscad),
            "--concurrency",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (out_dir / "a.stl").is_file()
    assert (out_dir / "b.stl").is_file()
    assert "Exported: 2" in result.output


def test_export_with_from_csv_builds_json_alongside_scad(
    runner: CliRunner,
    tmp_path: Path,
    stub_openscad: Path,
) -> None:
    scad = _write_scad(tmp_path / "m.scad")
    csv_path = _write_csv(tmp_path / "p.csv")
    out_dir = tmp_path / "out"

    result = runner.invoke(
        cli,
        [
            "export",
            str(scad),
            "--from-csv",
            str(csv_path),
            "--output-dir",
            str(out_dir),
            "--openscad-path",
            str(stub_openscad),
        ],
    )

    assert result.exit_code == 0, result.output
    # The CSV→JSON step writes <scad-stem>.json next to the scad file.
    assert scad.with_suffix(".json").is_file()
    assert (out_dir / "foo.stl").is_file()
    assert (out_dir / "bar.stl").is_file()


def test_export_failure_returns_nonzero(
    runner: CliRunner,
    tmp_path: Path,
    failing_openscad: Path,
) -> None:
    scad = _write_scad(tmp_path / "m.scad")
    json_path = tmp_path / "m.json"
    json_path.write_text(json.dumps({"parameterSets": {"foo": {}}, "fileFormatVersion": "1"}))

    result = runner.invoke(
        cli,
        [
            "export",
            str(scad),
            "--from-json",
            str(json_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--openscad-path",
            str(failing_openscad),
        ],
    )

    assert result.exit_code != 0
    assert "FAILED" in result.output


def test_scad_to_csv_with_stub_fails_gracefully(
    runner: CliRunner,
    tmp_path: Path,
    stub_openscad: Path,
) -> None:
    """The stub never writes JSON, so scad-to-csv should error cleanly."""
    scad = _write_scad(tmp_path / "m.scad")
    out_csv = tmp_path / "p.csv"

    result = runner.invoke(
        cli,
        [
            "scad-to-csv",
            str(scad),
            "--output",
            str(out_csv),
            "--openscad-path",
            str(stub_openscad),
        ],
    )
    # The stub doesn't write a param JSON, so we should get a non-zero exit.
    assert result.exit_code != 0


@pytest.mark.integration
def test_scad_to_csv_real(
    runner: CliRunner,
    tmp_path: Path,
    rocket_scad: Path,
    real_openscad_or_skip: str,
) -> None:
    out_csv = tmp_path / "rocket.csv"
    result = runner.invoke(
        cli,
        [
            "scad-to-csv",
            str(rocket_scad),
            "--output",
            str(out_csv),
            "--openscad-path",
            real_openscad_or_skip,
        ],
    )
    assert result.exit_code == 0, result.output
    lines = out_csv.read_text().splitlines()
    assert len(lines) == 2
    header = lines[0].split(",")
    assert header[0] == "exported_filename"
    assert "rocket_d" in header
