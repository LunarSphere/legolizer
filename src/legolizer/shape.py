"""Shape programs: an ordered list of 3D primitives, voxelized deterministically.

A shape program is the single 3D source of truth for a build. The designer
model writes it in uniform stud units (1 unit = 8 mm on every axis, so a
brick is 1.2 units tall); this module quantizes it to 1 stud x 1 stud x
1 plate cells. Every preview is rendered from these cells, so the views can
never disagree with each other the way independently generated images do.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from legolizer.catalog import COLORS, DESIGN_COLORS, MAX_STUDS

PLATE = 0.4  # plate height in stud units (3.2 mm / 8 mm)
GRID_PLATES = MAX_STUDS * 3
MAX_HEIGHT = GRID_PLATES * PLATE
SHAPES = ("box", "ellipsoid", "cylinder")
MODES = ("solid", "paint", "carve")
AXES = ("x", "y", "z")

Cell = tuple[int, int, int]
Region = tuple[Cell, Cell]

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

PROGRAM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "size": {"type": "array", "items": {"type": "number"}},
        "parts": {"type": "array", "items": PART_SCHEMA},
    },
    "required": ["name", "size", "parts"],
}


@dataclass
class Voxelized:
    cells: dict[Cell, int]
    owners: dict[Cell, str]
    notes: list[str] = field(default_factory=list)


def voxelize_program(program: Any) -> Voxelized:
    """Apply parts in order: solid fills, paint recolors filled cells, carve removes."""
    if not isinstance(program, dict) or not isinstance(program.get("parts"), list):
        raise ValueError("Shape program must be an object with a parts list")
    size = program.get("size")
    if not (isinstance(size, list) and len(size) == 3 and all(_is_number(v) for v in size)):
        raise ValueError("Shape program size must be [width, depth, height] in studs")
    cells: dict[Cell, int] = {}
    owners: dict[Cell, str] = {}
    notes: list[str] = []
    _apply_parts(program["parts"], cells, owners, notes, _mirror_width(size))
    if not cells:
        raise ValueError("Shape program produced no filled cells")
    lowest = min(z for _, _, z in cells)
    if lowest > 0:
        notes.append(f"model did not touch the ground; lowered by {lowest * PLATE:g} units")
        cells = {(x, y, z - lowest): c for (x, y, z), c in cells.items()}
        owners = {(x, y, z - lowest): n for (x, y, z), n in owners.items()}
    return Voxelized(cells, owners, notes)


def infill(base: dict[Cell, int], patch: Any, region: Region) -> Voxelized:
    """Apply a patch program on top of existing cells, changing nothing outside the region.

    Existing cells inside the region stay unless a patch part carves or paints
    them. The result is never lowered to the ground: that would move bricks
    outside the region.
    """
    if not isinstance(patch, dict) or not isinstance(patch.get("parts"), list):
        raise ValueError("Patch program must be an object with a parts list")
    size = patch.get("size")
    if not (isinstance(size, list) and len(size) == 3 and all(_is_number(v) for v in size)):
        size = [max(x for x, _, _ in base) + 1, 0, 0]
    cells = dict(base)
    owners = {cell: "existing model" for cell in cells}
    notes: list[str] = []
    _apply_parts(patch["parts"], cells, owners, notes, _mirror_width(size), region)
    if not cells:
        raise ValueError("The region edit removed every cell")
    if min(z for _, _, z in cells) > 0:
        raise ValueError("The region edit removed every cell that touches the ground")
    return Voxelized(cells, owners, notes)


def parse_region(raw: Any) -> Region:
    """Validate {"min": [x, y, z], "max": [x, y, z]}: inclusive cells, z in plates."""
    if not isinstance(raw, dict) or set(raw) != {"min", "max"}:
        raise ValueError("Region must be an object with min and max cells")
    corners = []
    for label in ("min", "max"):
        corner = raw[label]
        if not (isinstance(corner, list) and len(corner) == 3
                and all(isinstance(v, int) and not isinstance(v, bool) for v in corner)):
            raise ValueError(f"Region {label} must be three integers")
        corners.append(tuple(corner))
    low, high = corners
    limits = (MAX_STUDS, MAX_STUDS, GRID_PLATES)
    if not all(0 <= low[a] <= high[a] < limits[a] for a in range(3)):
        raise ValueError(f"Region must lie inside 0..{MAX_STUDS - 1} studs across and "
                         f"0..{GRID_PLATES - 1} plates up, with min <= max")
    return low, high


def region_json(region: Region) -> dict:
    return {"min": list(region[0]), "max": list(region[1])}


def in_region(cell: Cell, region: Region) -> bool:
    low, high = region
    return all(low[a] <= cell[a] <= high[a] for a in range(3))


def _mirror_width(size: list) -> int:
    return max(1, min(MAX_STUDS, round(size[0])))


def _apply_parts(parts: list, cells: dict[Cell, int], owners: dict[Cell, str], notes: list[str],
                 mirror_width: int, region: Region | None = None) -> None:
    """Run parts in order: solid fills, paint recolors filled cells, carve removes."""
    for index, raw in enumerate(parts):
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
            notes.append(f"{name}: {clipped} cells fall outside the build volume "
                         f"(0..{MAX_STUDS} x 0..{MAX_STUDS} studs, 0..{MAX_HEIGHT:g} tall) and were dropped")
        for bounds in (part["clip"], region):
            if bounds is None:
                continue
            kept = {cell for cell in inside if in_region(cell, bounds)}
            if inside and not kept:
                notes.append(f"{name}: lies entirely outside the editable region, no effect")
            inside = kept
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
                notes.append(f"{name}: paint touched no filled cells; move it onto the surface it decorates")
        else:
            for cell in inside:
                cells[cell] = part["color"]
                owners[cell] = name

    # Parts entirely overwritten by later parts had no visible effect.
    surviving = Counter(owners.values())
    for raw in parts:
        if isinstance(raw, dict) and raw.get("mode") in ("solid", "paint") and not surviving.get(raw.get("name")):
            if not any(note.startswith(f"{raw.get('name')}:") for note in notes):
                notes.append(f"{raw.get('name')}: completely covered by later parts, no visible effect")


def voxel_document(cells: dict[Cell, int]) -> dict:
    """Convert cells to the voxel JSON document accepted by parse_model."""
    return {
        "width": max(x for x, _, _ in cells) + 1,
        "depth": max(y for _, y, _ in cells) + 1,
        "height": (max(z for _, _, z in cells) + 3) // 3,
        "voxels": [dict(x=x, y=y, z=z, color=c) for (x, y, z), c in sorted(cells.items())],
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_part(raw: Any, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"parts[{index}] is not an object")
    name = raw.get("name") if isinstance(raw.get("name"), str) and raw.get("name") else f"part {index}"
    shape, mode = raw.get("shape"), raw.get("mode", "solid")
    axis = raw.get("axis", "z")
    if shape not in SHAPES or mode not in MODES or axis not in AXES:
        raise ValueError(f"{name}: shape, mode, or axis is not supported")
    center, size = raw.get("center"), raw.get("size")
    for label, vector in (("center", center), ("size", size)):
        if not (isinstance(vector, list) and len(vector) == 3 and all(_is_number(v) for v in vector)):
            raise ValueError(f"{name}: {label} must be three numbers")
    if any(v <= 0 for v in size):
        raise ValueError(f"{name}: size values must be positive")
    color = raw.get("color", 0)
    if mode != "carve" and color not in COLORS:
        raise ValueError(f"{name}: color {color} is not in the palette")
    taper = raw.get("taper", 1)
    taper = min(1.0, max(0.0, float(taper))) if _is_number(taper) else 1.0
    # Region edits saved into a program keep their clip box so re-voxelizing reproduces them.
    clip = parse_region(raw["clip"]) if raw.get("clip") is not None else None
    return {"name": name, "shape": shape, "mode": mode, "axis": axis, "center": center,
            "size": size, "color": color, "taper": taper, "mirror": raw.get("mirror") is True, "clip": clip}


def _part_cells(part: dict) -> tuple[set[Cell], int]:
    """Return in-grid cells whose centers lie inside the part, and the clipped count."""
    (cx, cy, cz), (sx, sy, sz) = part["center"], part["size"]
    # Search a bounded window so an absurd size cannot stall the loop.
    xs = range(max(-MAX_STUDS, math.floor(cx - sx / 2) - 1), min(2 * MAX_STUDS, math.ceil(cx + sx / 2) + 1))
    ys = range(max(-MAX_STUDS, math.floor(cy - sy / 2) - 1), min(2 * MAX_STUDS, math.ceil(cy + sy / 2) + 1))
    zs = range(max(-GRID_PLATES, math.floor((cz - sz / 2) / PLATE) - 1),
               min(2 * GRID_PLATES, math.ceil((cz + sz / 2) / PLATE) + 1))
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
    # Half-open along each axis so a size of n covers exactly n cells.
    if not -h[axis] <= d[axis] < h[axis]:
        return False
    # Taper shrinks the cross-section linearly toward the + end of the axis.
    scale = 1 + (part["taper"] - 1) * (d[axis] + h[axis]) / (2 * h[axis])
    if scale <= 1e-6:
        return False
    others = [a for a in range(3) if a != axis]
    if part["shape"] == "box":
        return all(-h[a] * scale <= d[a] < h[a] * scale for a in others)
    return sum((d[a] / (h[a] * scale)) ** 2 for a in others) <= 1
