from __future__ import annotations

from pathlib import Path

import pytest

from openscad_exporter import openscad as oe
from openscad_exporter.models import CameraOptions, ExportFormat
from openscad_exporter.openscad import (
    OpenScadNotFoundError,
    build_export_args,
    build_param_dump_args,
    discover_binary,
    output_filename_for,
)


def test_build_export_args_basic(tmp_path: Path) -> None:
    args = build_export_args(
        output_path=tmp_path / "foo.stl",
        scad_path=tmp_path / "model.scad",
        json_params_path=tmp_path / "model.json",
        param_set="foo",
    )
    assert args == [
        "-o",
        str(tmp_path / "foo.stl"),
        "-p",
        str(tmp_path / "model.json"),
        "-P",
        "foo",
        str(tmp_path / "model.scad"),
    ]


def test_build_export_args_includes_camera_flags(tmp_path: Path) -> None:
    cam = CameraOptions(camera="0,0,0,0,0,0,100", imgsize="512,512", viewall=True)
    args = build_export_args(
        output_path=tmp_path / "foo.png",
        scad_path=tmp_path / "model.scad",
        json_params_path=tmp_path / "model.json",
        param_set="foo",
        camera=cam,
    )
    # Camera args sit between -o and -p.
    assert args[0:2] == ["-o", str(tmp_path / "foo.png")]
    assert "--camera" in args
    assert "0,0,0,0,0,0,100" in args
    assert "--imgsize" in args
    assert "512,512" in args
    assert "--viewall" in args
    p_index = args.index("-p")
    assert args.index("--camera") < p_index


def test_build_export_args_skips_empty_camera(tmp_path: Path) -> None:
    args = build_export_args(
        output_path=tmp_path / "foo.stl",
        scad_path=tmp_path / "model.scad",
        json_params_path=tmp_path / "model.json",
        param_set="foo",
        camera=CameraOptions(),
    )
    assert "--camera" not in args
    assert "--viewall" not in args


def test_camera_validators_reject_bad_input() -> None:
    with pytest.raises(ValueError, match="--camera"):
        CameraOptions(camera="1,2,3")
    with pytest.raises(ValueError, match="--camera"):
        CameraOptions(camera="a,b,c,d,e,f,g")
    with pytest.raises(ValueError, match="--imgsize"):
        CameraOptions(imgsize="100")
    with pytest.raises(ValueError, match="--imgsize"):
        CameraOptions(imgsize="-1,200")


def test_build_param_dump_args(tmp_path: Path) -> None:
    args = build_param_dump_args(
        scad_path=tmp_path / "a.scad",
        output_json=tmp_path / "a.json",
    )
    assert args == [
        "--export-format",
        "param",
        "-o",
        str(tmp_path / "a.json"),
        str(tmp_path / "a.scad"),
    ]


def test_output_filename_for() -> None:
    assert output_filename_for("ParamSet1", ExportFormat.STL) == "ParamSet1.stl"
    assert output_filename_for("foo", ExportFormat.THREE_MF) == "foo.3mf"


def test_discover_binary_override(tmp_path: Path, isolated_env: None) -> None:
    bin_path = tmp_path / "openscad"
    bin_path.write_text("#!/bin/sh\nexit 0\n")
    bin_path.chmod(0o755)
    assert discover_binary(bin_path) == bin_path


def test_discover_binary_override_missing(tmp_path: Path, isolated_env: None) -> None:
    with pytest.raises(OpenScadNotFoundError, match="not found"):
        discover_binary(tmp_path / "nope")


def test_discover_binary_env_var(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_env: None,
) -> None:
    bin_path = tmp_path / "openscad"
    bin_path.write_text("#!/bin/sh\nexit 0\n")
    bin_path.chmod(0o755)
    monkeypatch.setenv("OPENSCAD_BINARY", str(bin_path))
    assert discover_binary() == bin_path


def test_discover_binary_env_var_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_env: None,
) -> None:
    monkeypatch.setenv("OPENSCAD_BINARY", str(tmp_path / "no.exe"))
    with pytest.raises(OpenScadNotFoundError, match="OPENSCAD_BINARY"):
        discover_binary()


def test_discover_binary_uses_which(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_env: None,
) -> None:
    bin_path = tmp_path / "openscad"
    bin_path.write_text("#!/bin/sh\n")
    bin_path.chmod(0o755)
    monkeypatch.setattr(
        "openscad_exporter.openscad.shutil.which",
        lambda name: str(bin_path) if name == "openscad" else None,
    )
    assert discover_binary() == bin_path


def test_discover_binary_falls_back_to_known_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_env: None,
) -> None:
    bin_path = tmp_path / "openscad"
    bin_path.write_text("#!/bin/sh\n")
    bin_path.chmod(0o755)
    monkeypatch.setattr("openscad_exporter.openscad.shutil.which", lambda name: None)
    monkeypatch.setattr(oe, "_platform_known_paths", lambda: (str(bin_path),))
    assert discover_binary() == bin_path


def test_discover_binary_raises_when_nothing_found(
    monkeypatch: pytest.MonkeyPatch,
    isolated_env: None,
) -> None:
    monkeypatch.setattr("openscad_exporter.openscad.shutil.which", lambda name: None)
    monkeypatch.setattr(oe, "_platform_known_paths", lambda: ())
    with pytest.raises(OpenScadNotFoundError, match="Could not locate"):
        discover_binary()
