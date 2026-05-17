from __future__ import annotations

import json
import stat
import textwrap
import time
from pathlib import Path

import pytest

from openscad_exporter.exporter import UnsafeOutputPathError, export_all
from openscad_exporter.models import ExportFormat


def _write_customizer_json(path: Path, names: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "parameterSets": {n: {"x": "1"} for n in names},
                "fileFormatVersion": "1",
            }
        )
    )


async def test_export_all_runs_each_parameter_set(
    tmp_path: Path,
    stub_openscad: Path,
) -> None:
    scad = tmp_path / "m.scad"
    scad.write_text("// scad")
    json_path = tmp_path / "m.json"
    _write_customizer_json(json_path, ["a", "b", "c"])
    out_dir = tmp_path / "out"

    summary = await export_all(
        scad_path=scad,
        json_path=json_path,
        output_dir=out_dir,
        fmt=ExportFormat.STL,
        binary=stub_openscad,
    )

    assert sorted(summary.exported) == ["a", "b", "c"]
    assert summary.skipped == []
    assert summary.failed == []
    for name in ("a", "b", "c"):
        assert (out_dir / f"{name}.stl").is_file()


async def test_export_all_skips_existing_when_not_overwriting(
    tmp_path: Path,
    stub_openscad: Path,
) -> None:
    scad = tmp_path / "m.scad"
    scad.write_text("// scad")
    json_path = tmp_path / "m.json"
    _write_customizer_json(json_path, ["a", "b"])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "a.stl").write_text("preexisting")

    summary = await export_all(
        scad_path=scad,
        json_path=json_path,
        output_dir=out_dir,
        fmt=ExportFormat.STL,
        binary=stub_openscad,
        overwrite=False,
    )

    assert summary.exported == ["b"]
    assert summary.skipped == ["a"]
    assert (out_dir / "a.stl").read_text() == "preexisting"


async def test_export_all_overwrites_with_flag(
    tmp_path: Path,
    stub_openscad: Path,
) -> None:
    scad = tmp_path / "m.scad"
    scad.write_text("// scad")
    json_path = tmp_path / "m.json"
    _write_customizer_json(json_path, ["a"])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "a.stl").write_text("preexisting")

    summary = await export_all(
        scad_path=scad,
        json_path=json_path,
        output_dir=out_dir,
        fmt=ExportFormat.STL,
        binary=stub_openscad,
        overwrite=True,
    )

    assert summary.exported == ["a"]
    assert summary.skipped == []
    assert (out_dir / "a.stl").read_text() != "preexisting"


async def test_export_all_reports_failures(
    tmp_path: Path,
    failing_openscad: Path,
) -> None:
    scad = tmp_path / "m.scad"
    scad.write_text("// scad")
    json_path = tmp_path / "m.json"
    _write_customizer_json(json_path, ["a", "b"])
    out_dir = tmp_path / "out"

    summary = await export_all(
        scad_path=scad,
        json_path=json_path,
        output_dir=out_dir,
        fmt=ExportFormat.STL,
        binary=failing_openscad,
    )

    assert summary.exported == []
    assert {name for name, _ in summary.failed} == {"a", "b"}
    for _name, msg in summary.failed:
        assert "synthetic openscad failure" in msg


async def test_export_all_respects_concurrency_limit(
    tmp_path: Path,
) -> None:
    """Use timestamp logging to compute max simultaneous invocations.

    Each stub appends a (start_ns, end_ns) line on exit; the test sweeps the
    timeline to find peak concurrency. This avoids needing `flock`, which is
    not available in macOS' default bash.
    """
    log_file = tmp_path / "events.log"
    log_file.write_text("")

    stub = tmp_path / "stub.sh"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            LOG="{log_file}"
            start=$(python3 -c 'import time; print(time.time_ns())')
            sleep 0.15
            end=$(python3 -c 'import time; print(time.time_ns())')
            # Single atomic line append.
            printf '%s %s\\n' "$start" "$end" >> "$LOG"
            out=""
            while [ $# -gt 0 ]; do
                case "$1" in
                    -o) out="$2"; shift 2;;
                    *) shift;;
                esac
            done
            [ -n "$out" ] && printf 'x' > "$out"
            exit 0
            """
        )
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    scad = tmp_path / "m.scad"
    scad.write_text("// scad")
    json_path = tmp_path / "m.json"
    _write_customizer_json(json_path, [f"p{i}" for i in range(6)])

    start = time.perf_counter()
    await export_all(
        scad_path=scad,
        json_path=json_path,
        output_dir=tmp_path / "out",
        fmt=ExportFormat.STL,
        binary=stub,
        concurrency=2,
    )
    elapsed = time.perf_counter() - start

    # Sweep the timeline to compute peak concurrency.
    events: list[tuple[int, int]] = []
    for line in log_file.read_text().splitlines():
        s_str, e_str = line.split()
        events.append((int(s_str), 1))
        events.append((int(e_str), -1))
    events.sort()
    peak = 0
    current = 0
    for _t, delta in events:
        current += delta
        peak = max(peak, current)

    assert peak <= 2, f"concurrency exceeded limit: peak={peak}"
    # 6 jobs / 2 concurrency * 0.15s sleep = ~0.45s minimum
    assert elapsed >= 0.35, f"jobs ran too quickly: {elapsed:.2f}s"


async def test_export_all_creates_subdirectories_for_slashed_names(
    tmp_path: Path,
    stub_openscad: Path,
) -> None:
    """exported_filename may contain slashes; parent dirs are created on demand."""
    scad = tmp_path / "m.scad"
    scad.write_text("// scad")
    json_path = tmp_path / "m.json"
    _write_customizer_json(json_path, ["small/v1", "small/v2", "large/v1"])
    out_dir = tmp_path / "out"

    summary = await export_all(
        scad_path=scad,
        json_path=json_path,
        output_dir=out_dir,
        fmt=ExportFormat.STL,
        binary=stub_openscad,
    )

    assert sorted(summary.exported) == ["large/v1", "small/v1", "small/v2"]
    assert (out_dir / "small" / "v1.stl").is_file()
    assert (out_dir / "small" / "v2.stl").is_file()
    assert (out_dir / "large" / "v1.stl").is_file()


async def test_export_all_rejects_path_escape(
    tmp_path: Path,
    stub_openscad: Path,
) -> None:
    scad = tmp_path / "m.scad"
    scad.write_text("// scad")
    json_path = tmp_path / "m.json"
    _write_customizer_json(json_path, ["../escape"])
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with pytest.raises(UnsafeOutputPathError, match="outside"):
        await export_all(
            scad_path=scad,
            json_path=json_path,
            output_dir=out_dir,
            fmt=ExportFormat.STL,
            binary=stub_openscad,
        )


async def test_export_all_no_jobs_short_circuits(tmp_path: Path, stub_openscad: Path) -> None:
    scad = tmp_path / "m.scad"
    scad.write_text("// scad")
    json_path = tmp_path / "m.json"
    _write_customizer_json(json_path, [])
    summary = await export_all(
        scad_path=scad,
        json_path=json_path,
        output_dir=tmp_path / "out",
        fmt=ExportFormat.STL,
        binary=stub_openscad,
    )
    assert summary.total == 0
