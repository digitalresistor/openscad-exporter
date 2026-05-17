from __future__ import annotations

import os
import stat
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def rocket_scad() -> Path:
    return FIXTURES / "rocket.scad"


@pytest.fixture
def rocket_csv() -> Path:
    return FIXTURES / "rocket.csv"


@pytest.fixture
def stub_openscad(tmp_path: Path) -> Path:
    """A shell-script stub that mimics `openscad -o <out> ... <scad>`.

    It parses argv to find the `-o` target and `touch`es it so the exporter sees
    a real file. Useful for unit/CLI tests that should not depend on a real
    openscad install.
    """
    script = tmp_path / "openscad_stub.sh"
    script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            # Stub openscad that creates the -o target file.
            out=""
            while [ $# -gt 0 ]; do
                case "$1" in
                    -o)
                        out="$2"
                        shift 2
                        ;;
                    *)
                        shift
                        ;;
                esac
            done
            if [ -n "$out" ]; then
                mkdir -p "$(dirname "$out")"
                printf 'stub-stl' > "$out"
            fi
            exit 0
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.fixture
def failing_openscad(tmp_path: Path) -> Path:
    """A stub openscad that always exits non-zero with stderr output."""
    script = tmp_path / "openscad_fail.sh"
    script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            echo "synthetic openscad failure" >&2
            exit 7
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip $OPENSCAD_BINARY and clear $PATH so discovery tests are deterministic."""
    monkeypatch.delenv("OPENSCAD_BINARY", raising=False)
    monkeypatch.setenv("PATH", "")
    yield
    # monkeypatch handles teardown


def _ensure_openscad_available() -> str | None:
    """Return path to a real openscad binary if present, else None."""
    import shutil

    return shutil.which("openscad") or (
        "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"
        if os.path.isfile("/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD")
        else None
    )


@pytest.fixture
def real_openscad_or_skip() -> str:
    binary = _ensure_openscad_available()
    if binary is None:
        pytest.skip("openscad binary not available on this machine")
    return binary
