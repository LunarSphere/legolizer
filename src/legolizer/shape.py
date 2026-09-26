"""Voxelize shape primitives and reserve envelopes for explicit official parts."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from legolizer.catalog import COLORS, DESIGN_COLORS, MAX_STUDS, SPECIAL_PARTS
from legolizer.model import Placement, parse_pieces

PLATE = 0.4  # plate height in stud units (3.2 mm / 8 mm)
BOUNDARY_EPSILON = 1e-9
GRID_PLATES = MAX_STUDS * 3
MAX_HEIGHT = GRID_PLATES * PLATE
SHAPES = ("box", "ellipsoid", "cylinder")
MODES = ("solid", "paint", "carve")
AXES = ("x", "y", "z")

Cell = tuple[int, int, int]

PART_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "shape": {"type": "string", "enum": list(SHAPES)},
        "mode": {"type": "string", "enum": list(MODES)},
        "center": {"type": "array", "items": {"type": "number"}},
        "size": {"type": "array", "items": {"type": "number"}},
        "axis": {"type": "string", "enum": list(AXES)},
        "taper": {"type": "number"},
        "color": {"type": "integer", "enum": list(DESIGN_COLORS)},
        "mirror": {"type": "boolean"},
    },
    "required": ["name", "shape", "mode", "center", "size", "axis", "taper", "color", "mirror"],
}

PIECE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "part": {"type": "string", "enum": [p.code for p in SPECIAL_PARTS]},
        "x": {"type": "integer"},
        "y": {"type": "integer"},
        "z": {"type": "integer"},
        "color": {"type": "integer", "enum": list(DESIGN_COLORS)},
        "rotation": {"type": "integer", "enum": [0, 90, 180, 270]},
    },
    "required": ["part", "x", "y", "z", "color", "rotation"],
}

PROGRAM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "size": {"type": "array", "items": {"type": "number"}},
        "parts": {"type": "array", "items": PART_SCHEMA},
        "pieces": {"type": "array", "items": PIECE_SCHEMA},
    },
    "required": ["name", "size", "parts", "pieces"],
}


@dataclass
class Voxelized:
    cells: dict[Cell, int]
    owners: dict[Cell, str]
    notes: list[str] = field(default_factory=list)
    pieces: tuple[Placement, ...] = ()
    ground_offset: int = 0


def voxelize_program(program: Any) -> Voxelized:
    """Apply parts in order: solid fills, paint recolors filled cells, carve removes."""
    if not isinstance(program, dict) or not isinstance(program.get("parts"), list):
        raise ValueError("Shape program must be an object with a parts list")
    size = program.get("size")
    if not (isinstance(size, list) and len(size) == 3 and all(_is_number(v) for v in size)):
        raise ValueError("Shape program size must be [width, depth, height] in studs")
    mirror_width = max(1, min(MAX_STUDS, round(size[0])))

    cells: dict[Cell, int] = {}
    owners: dict[Cell, str] = {}
    notes: list[str] = []
    for index, raw in enumerate(program["parts"]):
        try:
            part = _parse_part(raw, index)
        except ValueError as exc:
            notes.append(f"skipped part: {exc}")
            continue
        inside, clipped = _part_cells(part)
        if part["mirror"]:
            mirrored, mirrored_clipped = set(), 0
            for x, y, z in inside:
                mx = mirror_width - 1 - x
                if 0 <= mx < MAX_STUDS:
                    mirrored.add((mx, y, z))
                else:
                    mirrored_clipped += 1
            inside |= mirrored
            clipped += mirrored_clipped
        name = part["name"]
        if clipped:
            notes.append(
                f"{name}: {clipped} cells fall outside the build volume "
                f"(0..{MAX_STUDS} x 0..{MAX_STUDS} studs, 0..{MAX_HEIGHT:g} tall) and were dropped"
            )
        if part["mode"] == "carve":
            removed = [cell for cell in inside if cell in cells]
            for cell in removed:
                del cells[cell]
                owners.pop(cell, None)
            if not removed:
                notes.append(f"{name}: carve removed nothing")
        elif part["mode"] == "paint":
            hit = [cell for cell in inside if cell in cells]
            for cell in hit:
                cells[cell] = part["color"]
                owners[cell] = name
            if not hit:
                notes.append(
                    f"{name}: paint touched no filled cells; move it onto the surface it decorates"
                )
        else:
            for cell in inside:
                cells[cell] = part["color"]
                owners[cell] = name

    pieces = parse_pieces(program.get("pieces", []))
    for piece in pieces:
        for cell in piece.envelope():
            cells[cell] = piece.color
            owners[cell] = f"official {piece.part.code}"
    if not cells:
        raise ValueError("Shape program produced no filled cells")
    # Parts entirely overwritten by later parts had no visible effect.
    surviving = Counter(owners.values())
    for raw in program["parts"]:
        if (
            isinstance(raw, dict)
            and raw.get("mode") in ("solid", "paint")
            and not surviving.get(raw.get("name"))
        ):
            if not any(note.startswith(f"{raw.get('name')}:") for note in notes):
                notes.append(
                    f"{raw.get('name')}: completely covered by later parts, no visible effect"
                )
    lowest = min(z for _, _, z in cells)
    if lowest > 0:
        notes.append(f"model did not touch the ground; lowered by {lowest * PLATE:g} units")
        cells = {(x, y, z - lowest): c for (x, y, z), c in cells.items()}
        owners = {(x, y, z - lowest): n for (x, y, z), n in owners.items()}
        pieces = tuple(replace(p, z=p.z - lowest) for p in pieces)
    return Voxelized(cells, owners, notes, pieces, lowest)


def voxel_document(cells: dict[Cell, int], pieces: tuple[Placement, ...] = ()) -> dict:
    """Convert cells to the voxel JSON document accepted by parse_model."""
    reserved = {cell for p in pieces for cell in p.envelope()}
    document = {
        "width": max(x for x, _, _ in cells) + 1,
        "depth": max(y for _, y, _ in cells) + 1,
        "height": (max(z for _, _, z in cells) + 3) // 3,
        "voxels": [
            dict(x=x, y=y, z=z, color=c)
            for (x, y, z), c in sorted(cells.items())
            if (x, y, z) not in reserved
        ],
    }
    if pieces:
        document["pieces"] = [p.document() for p in pieces]
    return document


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_part(raw: Any, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"parts[{index}] is not an object")
    name = (
        raw.get("name") if isinstance(raw.get("name"), str) and raw.get("name") else f"part {index}"
    )
    shape, mode = raw.get("shape"), raw.get("mode", "solid")
    axis = raw.get("axis", "z")
    if shape not in SHAPES or mode not in MODES or axis not in AXES:
        raise ValueError(f"{name}: shape, mode, or axis is not supported")
    center, size = raw.get("center"), raw.get("size")
    for label, vector in (("center", center), ("size", size)):
        if not (
            isinstance(vector, list) and len(vector) == 3 and all(_is_number(v) for v in vector)
        ):
            raise ValueError(f"{name}: {label} must be three numbers")
    if any(v <= 0 for v in size):
        raise ValueError(f"{name}: size values must be positive")
    color = raw.get("color", 0)
    if mode != "carve" and color not in COLORS:
        raise ValueError(f"{name}: color {color} is not in the palette")
    taper = raw.get("taper", 1)
    taper = min(1.0, max(0.0, float(taper))) if _is_number(taper) else 1.0
    return {
        "name": name,
        "shape": shape,
        "mode": mode,
        "axis": axis,
        "center": center,
        "size": size,
        "color": color,
        "taper": taper,
        "mirror": raw.get("mirror") is True,
    }


def _part_cells(part: dict) -> tuple[set[Cell], int]:
    """Return in-grid cells whose centers lie inside the part, and the clipped count."""
    (cx, cy, cz), (sx, sy, sz) = part["center"], part["size"]
    # Search a bounded window so an absurd size cannot stall the loop.
    xs = range(
        max(-MAX_STUDS, math.floor(cx - sx / 2) - 1), min(2 * MAX_STUDS, math.ceil(cx + sx / 2) + 1)
    )
    ys = range(
        max(-MAX_STUDS, math.floor(cy - sy / 2) - 1), min(2 * MAX_STUDS, math.ceil(cy + sy / 2) + 1)
    )
    zs = range(
        max(-GRID_PLATES, math.floor((cz - sz / 2) / PLATE) - 1),
        min(2 * GRID_PLATES, math.ceil((cz + sz / 2) / PLATE) + 1),
    )
    inside: set[Cell] = set()
    clipped = 0
    for z in zs:
        for y in ys:
            for x in xs:
                if not _contains(part, (x + 0.5, y + 0.5, (z + 0.5) * PLATE)):
                    continue
                if 0 <= x < MAX_STUDS and 0 <= y < MAX_STUDS and 0 <= z < GRID_PLATES:
                    inside.add((x, y, z))
                else:
                    clipped += 1
    if not inside and not clipped and part["mode"] != "carve":
        # Features smaller than one cell (eyes, buttons) would otherwise vanish.
        cell = (math.floor(cx), math.floor(cy), math.floor(cz / PLATE))
        if 0 <= cell[0] < MAX_STUDS and 0 <= cell[1] < MAX_STUDS and 0 <= cell[2] < GRID_PLATES:
            inside.add(cell)
    return inside, clipped


def _contains(part: dict, point: tuple[float, float, float]) -> bool:
    d = [point[a] - part["center"][a] for a in range(3)]
    h = [part["size"][a] / 2 for a in range(3)]
    if part["shape"] == "ellipsoid":
        return sum((d[a] / h[a]) ** 2 for a in range(3)) <= 1
    axis = AXES.index(part["axis"])
    # Consistent half-open faces prevent decimal roundoff from dropping a shared course.
    if not -h[axis] - BOUNDARY_EPSILON <= d[axis] < h[axis] - BOUNDARY_EPSILON:
        return False
    # Taper shrinks the cross-section linearly toward the + end of the axis.
    scale = 1 + (part["taper"] - 1) * (d[axis] + h[axis]) / (2 * h[axis])
    if scale <= 1e-6:
        return False
    others = [a for a in range(3) if a != axis]
    if part["shape"] == "box":
        return all(
            -h[a] * scale - BOUNDARY_EPSILON <= d[a] < h[a] * scale - BOUNDARY_EPSILON
            for a in others
        )
    return sum((d[a] / (h[a] * scale)) ** 2 for a in others) <= 1
