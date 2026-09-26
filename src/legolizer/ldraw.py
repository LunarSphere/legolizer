"""Write stepped MPD files and a linked, color-aware parts list."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from legolizer.catalog import (
    COLOR_INFO,
    COLORS,
    PART_BY_CODE,
    PLATE_LDU,
    RECTANGULAR_PARTS,
    STUD_LDU,
)
from legolizer.model import VoxelModel
from legolizer.solver import Placement

# Upright rotations by quarter turns.
MATRICES = (
    "1 0 0 0 1 0 0 0 1",
    "0 0 1 0 1 0 -1 0 0",
    "-1 0 0 0 1 0 0 0 -1",
    "0 0 -1 0 1 0 1 0 0",
)


def _native_offset(part, turns: int) -> tuple[int, int]:
    offset_x, offset_z = part.native_center
    for _ in range(turns):
        offset_x, offset_z = offset_z, -offset_x
    return offset_x, offset_z


def read_mpd(path: Path) -> list[Placement]:
    """Read placements back from an MPD written by write_mpd."""
    placements: list[Placement] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split()
        if not fields or fields[0] != "1":
            continue
        try:
            color, center_x, top_y, center_z = (int(float(v)) for v in fields[1:5])
            matrix = " ".join(str(int(float(v))) for v in fields[5:14])
            part = PART_BY_CODE[fields[14].lower().removesuffix(".dat")]
        except (ValueError, KeyError, IndexError) as exc:
            raise ValueError(
                f"{path.name} line {number} is not a supported Legolizer piece"
            ) from exc
        if matrix not in MATRICES or color not in COLORS:
            raise ValueError(f"{path.name} line {number} uses an unsupported rotation or color")
        turns = MATRICES.index(matrix)
        width, depth = (part.depth, part.width) if turns % 2 else (part.width, part.depth)
        offset_x, offset_z = _native_offset(part, turns)
        center_x, center_z = center_x + offset_x, center_z + offset_z
        x = (center_x - width * STUD_LDU // 2) / STUD_LDU
        y = (center_z - depth * STUD_LDU // 2) / STUD_LDU
        z = -top_y / PLATE_LDU - part.height
        if not (x.is_integer() and y.is_integer() and z.is_integer()) or min(x, y, z) < 0:
            raise ValueError(f"{path.name} line {number} is off the stud grid")
        rotation = None if part in RECTANGULAR_PARTS else turns * 90
        placements.append(Placement(part, int(x), int(y), int(z), color, width, depth, rotation))
    if not placements:
        raise ValueError(f"{path.name} contains no pieces")
    return placements


def write_mpd(model: VoxelModel, placements: list[Placement], output: Path) -> None:
    max_z = max((p.z for p in placements), default=0)
    lines = [
        f"0 FILE {output.name}",
        "0 Name: Legolizer generated model",
        "0 Author: Legolizer proof of concept",
        "0 BFC CERTIFY CCW",
        "0",
    ]
    for layer in range(max_z + 1):
        layer_parts = [p for p in placements if p.z == layer]
        if not layer_parts:
            continue
        for p in layer_parts:
            center_x = p.x * STUD_LDU + p.width * STUD_LDU // 2
            center_z = p.y * STUD_LDU + p.depth * STUD_LDU // 2
            # Official bricks/plates have their top at native Y=0 and extend
            # downwards; voxel z denotes the bottom of the placed part.
            top_y = -(layer + p.part.height) * PLATE_LDU
            matrix = MATRICES[p.turns]
            offset_x, offset_z = _native_offset(p.part, p.turns)
            center_x -= offset_x
            center_z -= offset_z
            lines.append(f"1 {p.color} {center_x} {top_y} {center_z} {matrix} {p.part.code}.dat")
        lines.append("0 STEP")
    lines.append("0 NOFILE")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_parts_list(placements: list[Placement], output: Path) -> None:
    counts = Counter((p.part.code, p.color) for p in placements)
    parts = [
        {
            "part_id": part_id,
            "color_id": color,
            "color": COLORS[color].replace("_", " "),
            "rgb": COLOR_INFO[color][1],
            "quantity": quantity,
            "bricklink_url": "https://www.bricklink.com/v2/catalog/catalogitem.page?P="
            + (PART_BY_CODE[part_id].bricklink_id or part_id),
        }
        for (part_id, color), quantity in sorted(counts.items())
    ]
    output.write_text(json.dumps({"parts": parts}, indent=2) + "\n", encoding="utf-8")
