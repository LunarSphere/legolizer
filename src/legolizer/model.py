"""Voxel model parsing and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from legolizer.catalog import COLORS, MAX_STUDS, PART_BY_CODE, PartSpec


@dataclass(frozen=True)
class Placement:
    part: PartSpec
    x: int
    y: int
    z: int
    color: int
    width: int
    depth: int
    rotation: int | None = None

    @property
    def turns(self) -> int:
        if self.rotation is not None:
            return self.rotation // 90
        return int((self.width, self.depth) != (self.part.width, self.part.depth))

    def contacts(self, top: bool) -> frozenset[tuple[int, int]]:
        points = self.part.top_studs if top else self.part.bottom_sockets
        if points is None:
            points = tuple((x, y) for x in range(self.part.width) for y in range(self.part.depth))
        result = set()
        for x, y in points:
            w, d = self.part.width, self.part.depth
            for _ in range(self.turns):
                x, y, w, d = y, w - 1 - x, d, w
            result.add((self.x + x, self.y + y))
        return frozenset(result)

    def envelope(self):
        for z in range(self.z, self.z + self.part.height):
            for y in range(self.y, self.y + self.depth):
                for x in range(self.x, self.x + self.width):
                    yield x, y, z

    def document(self) -> dict:
        return dict(
            part=self.part.code,
            x=self.x,
            y=self.y,
            z=self.z,
            color=self.color,
            rotation=self.turns * 90,
        )


def parse_pieces(raw: Any) -> tuple[Placement, ...]:
    if not isinstance(raw, list) or len(raw) > 400:
        raise ValueError("pieces must be a list of at most 400 official parts")
    pieces = []
    reserved = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("part"), str):
            raise ValueError(f"pieces[{index}] needs an official part code")
        part = PART_BY_CODE.get(item["part"])
        values = [item.get(key) for key in ("x", "y", "z", "color", "rotation")]
        if part is None or any(type(value) is not int for value in values):
            raise ValueError(f"pieces[{index}] has an unsupported part or noninteger coordinates")
        x, y, z, color, rotation = values
        if color not in COLORS or rotation not in (0, 90, 180, 270):
            raise ValueError(f"pieces[{index}] has an unsupported color or rotation")
        w, d = (part.depth, part.width) if rotation % 180 else (part.width, part.depth)
        piece = Placement(part, x, y, z, color, w, d, rotation)
        if not (
            0 <= x <= MAX_STUDS - w
            and 0 <= y <= MAX_STUDS - d
            and 0 <= z <= MAX_STUDS * 3 - part.height
        ):
            raise ValueError(f"pieces[{index}] is outside the build volume")
        envelope = set(piece.envelope())
        if reserved & envelope:
            raise ValueError(f"pieces[{index}] overlaps another piece's reserved envelope")
        reserved |= envelope
        pieces.append(piece)
    return tuple(pieces)


@dataclass(frozen=True)
class Voxel:
    x: int
    y: int
    z: int
    color: int


@dataclass(frozen=True)
class VoxelModel:
    width: int
    depth: int
    height: int
    voxels: tuple[Voxel, ...]
    pieces: tuple[Placement, ...] = ()


def load_model(path: Path) -> VoxelModel:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read model JSON at {path}: {exc}") from exc
    return parse_model(raw)


def parse_model(raw: Any) -> VoxelModel:
    if not isinstance(raw, dict):
        raise ValueError("Model JSON must be an object")
    dims: dict[str, int] = {}
    for name in ("width", "depth", "height"):
        value = raw.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > MAX_STUDS:
            raise ValueError(f"{name} must be an integer from 1 to {MAX_STUDS}")
        dims[name] = value
    pieces = parse_pieces(raw.get("pieces", []))
    reserved = {cell for p in pieces for cell in p.envelope()}
    if any(
        x >= dims["width"] or y >= dims["depth"] or z >= dims["height"] * 3 for x, y, z in reserved
    ):
        raise ValueError("pieces are outside the declared dimensions")
    cells = raw.get("voxels")
    if not isinstance(cells, list) or (not cells and not pieces):
        raise ValueError("voxels must be a list; the model needs voxels or pieces")
    voxels: list[Voxel] = []
    seen: set[tuple[int, int, int]] = set()
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            raise ValueError(f"voxels[{index}] must be an object")
        values = [cell.get(axis) for axis in ("x", "y", "z", "color")]
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError(f"voxels[{index}] needs integer x, y, z, and color values")
        x, y, z, color = values
        if not (0 <= x < dims["width"] and 0 <= y < dims["depth"] and 0 <= z < dims["height"] * 3):
            raise ValueError(f"voxels[{index}] is outside the declared dimensions")
        if color not in COLORS:
            raise ValueError(f"voxels[{index}] uses unsupported LDraw color {color}")
        coord = (x, y, z)
        if coord in reserved:
            raise ValueError(f"Voxel at {coord} overlaps a piece's reserved envelope")
        if coord in seen:
            raise ValueError(f"Duplicate voxel at {coord}")
        seen.add(coord)
        voxels.append(Voxel(x, y, z, color))
    return VoxelModel(**dims, voxels=tuple(voxels), pieces=pieces)
