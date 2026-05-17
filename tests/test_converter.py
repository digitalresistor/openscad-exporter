from __future__ import annotations

import json
from pathlib import Path

import pytest

from openscad_exporter.converter import (
    CsvSchemaError,
    JsonOverwriteError,
    csv_to_customizer_json,
    default_params_to_csv,
    load_parameter_set_names,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_csv_to_json_basic(tmp_path: Path) -> None:
    csv_path = _write(
        tmp_path / "in.csv",
        "exported_filename,n,name,flag\nfoo,10,Alice,true\nbar,3.14,Bob,false\n",
    )
    json_path = tmp_path / "out.json"

    count = csv_to_customizer_json(csv_path, json_path)

    assert count == 2
    doc = json.loads(json_path.read_text())
    assert doc["fileFormatVersion"] == "1"
    assert doc["parameterSets"] == {
        "foo": {"n": "10", "name": "Alice", "flag": "true"},
        "bar": {"n": "3.14", "name": "Bob", "flag": "false"},
    }


def test_csv_values_are_strings(tmp_path: Path) -> None:
    """Customizer spec stores every value as a JSON string, including numbers."""
    csv_path = _write(
        tmp_path / "in.csv",
        'exported_filename,n,v\nrow,42,"[1, 2, 3]"\n',
    )
    json_path = tmp_path / "out.json"

    csv_to_customizer_json(csv_path, json_path)
    doc = json.loads(json_path.read_text())

    for value in doc["parameterSets"]["row"].values():
        assert isinstance(value, str)
    assert doc["parameterSets"]["row"]["n"] == "42"
    assert doc["parameterSets"]["row"]["v"] == "[1, 2, 3]"


def test_csv_missing_required_column(tmp_path: Path) -> None:
    csv_path = _write(tmp_path / "in.csv", "name,value\nfoo,10\n")
    with pytest.raises(CsvSchemaError, match="exported_filename"):
        csv_to_customizer_json(csv_path, tmp_path / "out.json")


def test_csv_empty_filename(tmp_path: Path) -> None:
    csv_path = _write(tmp_path / "in.csv", "exported_filename,n\n,5\n")
    with pytest.raises(CsvSchemaError, match="empty"):
        csv_to_customizer_json(csv_path, tmp_path / "out.json")


def test_csv_duplicate_filenames(tmp_path: Path) -> None:
    csv_path = _write(
        tmp_path / "in.csv",
        "exported_filename,n\nfoo,1\nfoo,2\n",
    )
    with pytest.raises(CsvSchemaError, match="duplicate"):
        csv_to_customizer_json(csv_path, tmp_path / "out.json")


def test_csv_to_json_refuses_overwrite_without_force(tmp_path: Path) -> None:
    csv_path = _write(tmp_path / "in.csv", "exported_filename,n\nfoo,1\n")
    json_path = tmp_path / "out.json"
    json_path.write_text("{}")

    with pytest.raises(JsonOverwriteError):
        csv_to_customizer_json(csv_path, json_path)


def test_csv_to_json_overwrites_with_force(tmp_path: Path) -> None:
    csv_path = _write(tmp_path / "in.csv", "exported_filename,n\nfoo,1\n")
    json_path = tmp_path / "out.json"
    json_path.write_text("{}")

    csv_to_customizer_json(csv_path, json_path, force=True)

    doc = json.loads(json_path.read_text())
    assert "foo" in doc["parameterSets"]


def test_load_parameter_set_names_preserves_order(tmp_path: Path) -> None:
    json_path = tmp_path / "p.json"
    json_path.write_text(
        json.dumps(
            {
                "parameterSets": {"a": {}, "b": {}, "c": {}},
                "fileFormatVersion": "1",
            }
        )
    )
    assert load_parameter_set_names(json_path) == ["a", "b", "c"]


def test_load_parameter_set_names_rejects_bad_shape(tmp_path: Path) -> None:
    json_path = tmp_path / "p.json"
    json_path.write_text(json.dumps({"foo": "bar"}))
    with pytest.raises(ValueError, match="parameterSets"):
        load_parameter_set_names(json_path)


def test_default_params_to_csv(tmp_path: Path) -> None:
    src = {
        "parameters": [
            {"name": "n", "initial": 42, "type": "number"},
            {"name": "f", "initial": 3.14},
            {"name": "flag", "initial": True},
            {"name": "label", "initial": "hello"},
            {"name": "v", "initial": [1, 2, 3]},
        ]
    }
    src_path = tmp_path / "params.json"
    src_path.write_text(json.dumps(src))

    out_csv = tmp_path / "defaults.csv"
    cols = default_params_to_csv(src_path, out_csv)

    assert cols == 5
    lines = out_csv.read_text().splitlines()
    assert lines[0] == "exported_filename,n,f,flag,label,v"
    # CSV-quote the vector field since it contains commas.
    assert lines[1] == 'default,42,3.14,true,hello,"[1, 2, 3]"'


def test_default_params_to_csv_rejects_bad_shape(tmp_path: Path) -> None:
    src_path = tmp_path / "params.json"
    src_path.write_text(json.dumps({"foo": "bar"}))
    with pytest.raises(ValueError, match="parameters"):
        default_params_to_csv(src_path, tmp_path / "x.csv")
