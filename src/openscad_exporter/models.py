from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExportFormat(StrEnum):
    STL = "stl"
    OFF = "off"
    AMF = "amf"
    THREE_MF = "3mf"
    DXF = "dxf"
    SVG = "svg"
    PNG = "png"


class CameraOptions(BaseModel):
    """OpenSCAD CLI camera flags used only with PNG output."""

    model_config = ConfigDict(frozen=True)

    camera: str | None = Field(
        default=None,
        description="Comma-separated camera tuple: tx,ty,tz,rx,ry,rz,dist.",
    )
    imgsize: str | None = Field(
        default=None,
        description="Image size as WIDTH,HEIGHT.",
    )
    colorscheme: str | None = None
    viewall: bool = False
    render: bool = False

    @field_validator("camera")
    @classmethod
    def _validate_camera(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = v.split(",")
        if len(parts) != 7:
            raise ValueError("--camera expects 7 comma-separated numbers: tx,ty,tz,rx,ry,rz,dist")
        for part in parts:
            try:
                float(part)
            except ValueError as e:
                raise ValueError(f"--camera component {part!r} is not numeric") from e
        return v

    @field_validator("imgsize")
    @classmethod
    def _validate_imgsize(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = v.split(",")
        if len(parts) != 2:
            raise ValueError("--imgsize expects WIDTH,HEIGHT")
        for part in parts:
            if not part.strip().isdigit():
                raise ValueError(f"--imgsize component {part!r} is not a positive integer")
        return v

    def as_cli_args(self) -> list[str]:
        args: list[str] = []
        if self.camera is not None:
            args += ["--camera", self.camera]
        if self.imgsize is not None:
            args += ["--imgsize", self.imgsize]
        if self.colorscheme is not None:
            args += ["--colorscheme", self.colorscheme]
        if self.viewall:
            args.append("--viewall")
        if self.render:
            args.append("--render")
        return args

    def is_empty(self) -> bool:
        return (
            self.camera is None
            and self.imgsize is None
            and self.colorscheme is None
            and not self.viewall
            and not self.render
        )


class CustomizerJson(BaseModel):
    """OpenSCAD customizer parameter file format.

    Per https://en.wikibooks.org/wiki/OpenSCAD_User_Manual/Customizer the on-disk format is::

        {"parameterSets": {<name>: {<param>: <string-value>, ...}, ...},
         "fileFormatVersion": "1"}

    All parameter values are stored as strings; OpenSCAD parses them back to the SCAD
    variable's declared type when loading.
    """

    parameterSets: dict[str, dict[str, str]] = Field(default_factory=dict)
    fileFormatVersion: str = "1"


class ExportSummary(BaseModel):
    exported: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[tuple[str, str]] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.exported) + len(self.skipped) + len(self.failed)
