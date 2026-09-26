"""Voxel model parsing and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from legolizer.catalog import COLORS, MAX_STUDS


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
    cells = raw.get("voxels")
    if not isinstance(cells, list) or not cells:
        raise ValueError("voxels must be a non-empty list")
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
        if coord in seen:
            raise ValueError(f"Duplicate voxel at {coord}")
        seen.add(coord)
        voxels.append(Voxel(x, y, z, color))
    return VoxelModel(**dims, voxels=tuple(voxels))
