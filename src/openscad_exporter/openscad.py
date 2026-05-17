from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

from openscad_exporter.models import CameraOptions, ExportFormat


class OpenScadNotFoundError(RuntimeError):
    """Raised when an `openscad` binary cannot be located."""


_KNOWN_PATHS_MACOS = (
    "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD",
    "/opt/homebrew/bin/openscad",
    "/usr/local/bin/openscad",
)
_KNOWN_PATHS_LINUX = (
    "/usr/bin/openscad",
    "/usr/local/bin/openscad",
    "/snap/bin/openscad",
    "/snap/bin/openscad-nightly",
)
_KNOWN_PATHS_WINDOWS = (
    r"C:\Program Files\OpenSCAD\openscad.exe",
    r"C:\Program Files (x86)\OpenSCAD\openscad.exe",
)


def _platform_known_paths() -> tuple[str, ...]:
    if sys.platform == "darwin":
        return _KNOWN_PATHS_MACOS
    if sys.platform.startswith("linux"):
        return _KNOWN_PATHS_LINUX
    if sys.platform.startswith("win"):
        return _KNOWN_PATHS_WINDOWS
    return ()


def discover_binary(override: Path | str | None = None) -> Path:
    """Resolve the openscad executable.

    Resolution order:
        1. `override` argument (e.g. from --openscad-path)
        2. $OPENSCAD_BINARY environment variable
        3. shutil.which("openscad")
        4. Platform-specific known install paths
    """
    if override is not None:
        path = Path(override)
        if path.is_file():
            return path
        raise OpenScadNotFoundError(f"openscad binary not found at {path!s}")

    env = os.environ.get("OPENSCAD_BINARY")
    if env:
        path = Path(env)
        if path.is_file():
            return path
        raise OpenScadNotFoundError(f"$OPENSCAD_BINARY is set to {env!s} but no file exists there")

    which = shutil.which("openscad")
    if which:
        return Path(which)

    for candidate in _platform_known_paths():
        path = Path(candidate)
        if path.is_file():
            return path

    raise OpenScadNotFoundError(
        "Could not locate openscad. Install it, set $OPENSCAD_BINARY, or pass --openscad-path."
    )


def build_export_args(
    *,
    output_path: Path,
    scad_path: Path,
    json_params_path: Path,
    param_set: str,
    camera: CameraOptions | None = None,
) -> list[str]:
    """Build the argv tail (after the openscad binary) for one export invocation.

    Order matches `openscad -o <out> [<camera flags>] -p <json> -P <set> <scad>`.
    """
    args: list[str] = ["-o", str(output_path)]
    if camera is not None and not camera.is_empty():
        args += camera.as_cli_args()
    args += [
        "-p",
        str(json_params_path),
        "-P",
        param_set,
        str(scad_path),
    ]
    return args


def build_param_dump_args(*, scad_path: Path, output_json: Path) -> list[str]:
    """Build argv for `openscad --export-format param -o <json> <scad>`."""
    return [
        "--export-format",
        "param",
        "-o",
        str(output_json),
        str(scad_path),
    ]


async def run_openscad(
    binary: Path,
    args: list[str],
    *,
    timeout: float | None = None,
) -> tuple[int, bytes, bytes]:
    """Run an openscad subprocess and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        str(binary),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, stdout, stderr


def dump_default_params(binary: Path, scad_path: Path, output_json: Path) -> None:
    """Synchronously run `openscad --export-format param` to produce a defaults JSON."""
    args = [str(binary), *build_param_dump_args(scad_path=scad_path, output_json=output_json)]
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"openscad --export-format param failed (exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace')}"
        )
    if not output_json.is_file():
        raise RuntimeError(f"openscad reported success but did not produce {output_json}")


def output_filename_for(param_set: str, fmt: ExportFormat) -> str:
    return f"{param_set}.{fmt.value}"
