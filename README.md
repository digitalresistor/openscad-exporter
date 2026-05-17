# openscad-exporter

Bulk-export OpenSCAD models from CSV or customizer JSON parameter sets.

## Requirements

Requires an OpenSCAD binary that supports `--export-format param`
(OpenSCAD 2021.01 development snapshots or the 2024.xx stable release and later).

## Install

```sh
uv sync
```

## Usage

```sh
# Generate a single-row CSV of a SCAD file's default parameter values.
uv run openscad-exporter scad-to-csv path/to/model.scad --output params.csv

# Convert a CSV (one parameter set per row, with an `exported_filename` column)
# into an OpenSCAD customizer JSON file.
uv run openscad-exporter csv-to-json params.csv --scad path/to/model.scad --output model.json

# Export every parameter set to STL (or off/amf/3mf/dxf/svg/png).
uv run openscad-exporter export path/to/model.scad --from-csv params.csv --output-dir out
uv run openscad-exporter export path/to/model.scad --from-json model.json --output-dir out --format stl
```

PNG-specific camera flags (`--camera`, `--imgsize`, `--colorscheme`, `--viewall`, `--render`)
only apply with `--format png`.

OpenSCAD binary is discovered via `--openscad-path`, `$OPENSCAD_BINARY`, `PATH`, then known
platform locations.

## Examples

These examples use `tests/fixtures/rocket.scad`, a small parametric rocket with the customizer
parameters `rocket_d`, `rocket_h`, `head_d`, `head_h`, `wing_w`, `many`, `wing_l`, `wing_h`, and
`$fn`.

### Minimal CSV

Only the `exported_filename` column is required. Any parameter you leave out keeps its default
value from the `.scad` file.

```csv
exported_filename,rocket_h
short,60
tall,150
```

Export both variants to STL:

```sh
uv run openscad-exporter export tests/fixtures/rocket.scad \
    --from-csv rockets.csv --output-dir out --format stl
```

You'll get `out/short.stl` and `out/tall.stl`.

### Multi-parameter CSV

Override several parameters per row:

```csv
exported_filename,rocket_d,rocket_h,head_d,wing_w,many
slim,20,120,30,2,3
classic,30,100,40,2,3
chunky,50,80,60,3,4
```

### Nested directory layout

Slashes in `exported_filename` create subdirectories under `--output-dir`:

```csv
exported_filename,rocket_h
small/v1,60
small/v2,80
large/v1,150
```

```sh
uv run openscad-exporter export tests/fixtures/rocket.scad \
    --from-csv rockets.csv --output-dir out --format stl
```

Produces:

```
out/
├── large/v1.stl
└── small/
    ├── v1.stl
    └── v2.stl
```

### PNG previews

Render each row as a 512×512 PNG with the auto-fit camera:

```sh
uv run openscad-exporter export tests/fixtures/rocket.scad \
    --from-csv rockets.csv --output-dir previews \
    --format png --viewall --imgsize 512,512
```

### Discovering parameters

If you don't yet have a CSV, dump the SCAD file's defaults to seed one:

```sh
uv run openscad-exporter scad-to-csv tests/fixtures/rocket.scad --output rockets.csv
```

This writes a single `default` row with every customizer parameter as a column. Duplicate it,
edit the values, and re-run `export`.
