from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from openscad_exporter.models import CustomizerJson

EXPORTED_FILENAME_COLUMN = "exported_filename"


class CsvSchemaError(ValueError):
    """The CSV does not match the expected shape."""


class JsonOverwriteError(FileExistsError):
    """A customizer JSON file already exists and --force was not given."""


def _normalize_value(raw: str) -> str:
    """Return a CSV cell as the string OpenSCAD's customizer expects.

    The customizer format stores every parameter as a JSON string regardless of
    declared SCAD type, so no type-specific coercion happens here — we only
    strip surrounding whitespace to keep diffs clean.
    """
    return raw.strip()


def csv_to_customizer_json(
    csv_path: Path,
    json_path: Path,
    *,
    force: bool = False,
) -> int:
    """Read a CSV of parameter sets and write an OpenSCAD customizer JSON.

    Returns the number of parameter sets written.
    """
    if json_path.exists() and not force:
        raise JsonOverwriteError(f"{json_path} already exists. Re-run with --force to overwrite.")

    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or EXPORTED_FILENAME_COLUMN not in reader.fieldnames:
            raise CsvSchemaError(
                f"CSV must contain an {EXPORTED_FILENAME_COLUMN!r} column. "
                f"Found columns: {reader.fieldnames}"
            )

        parameter_sets: dict[str, dict[str, str]] = {}
        for row_index, row in enumerate(reader, start=2):
            name = (row.get(EXPORTED_FILENAME_COLUMN) or "").strip()
            if not name:
                raise CsvSchemaError(
                    f"Row {row_index}: {EXPORTED_FILENAME_COLUMN!r} value is empty."
                )
            if name in parameter_sets:
                raise CsvSchemaError(
                    f"Row {row_index}: duplicate {EXPORTED_FILENAME_COLUMN}={name!r}. "
                    "Each row must have a unique name."
                )

            params: dict[str, str] = {}
            for key, raw in row.items():
                if key is None or key == EXPORTED_FILENAME_COLUMN:
                    continue
                if raw is None:
                    continue
                params[key] = _normalize_value(raw)
            parameter_sets[name] = params

    doc = CustomizerJson(parameterSets=parameter_sets)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(doc.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(parameter_sets)


def load_parameter_set_names(json_path: Path) -> list[str]:
    """Read a customizer JSON and return the ordered list of parameter set names."""
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    sets = raw.get("parameterSets")
    if not isinstance(sets, dict):
        raise ValueError(f"{json_path} is not a customizer JSON (missing parameterSets object).")
    return list(sets.keys())


def _stringify_initial(value: Any) -> str:
    """Render the `initial` value from `openscad --export-format param` as a CSV cell."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        # Render lists as JSON-style so they round-trip through openscad customizer.
        return json.dumps(value, separators=(", ", ": "))
    return json.dumps(value)


def default_params_to_csv(param_json_path: Path, csv_path: Path) -> int:
    """Convert the JSON output of `openscad --export-format param` to a 1-row CSV.

    The CSV has one column per parameter, plus the leading ``exported_filename`` column.
    Returns the number of parameter columns written.
    """
    raw = json.loads(param_json_path.read_text(encoding="utf-8"))
    params = raw.get("parameters")
    if not isinstance(params, list):
        raise ValueError(
            f"{param_json_path} is not an openscad param-export JSON (missing parameters list)."
        )

    columns: list[str] = [EXPORTED_FILENAME_COLUMN]
    row: dict[str, str] = {EXPORTED_FILENAME_COLUMN: "default"}
    for entry in params:
        if not isinstance(entry, dict) or "name" not in entry:
            continue
        name = str(entry["name"])
        columns.append(name)
        row[name] = _stringify_initial(entry.get("initial"))

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerow(row)
    return len(columns) - 1
