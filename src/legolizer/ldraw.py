"""Write stepped MPD files and a linked, color-aware parts list."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from legolizer.catalog import COLOR_INFO, COLORS, PART_BY_CODE, PLATE_LDU, STUD_LDU
from legolizer.model import VoxelModel
from legolizer.solver import Placement


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
            matrices = (
                "1 0 0 0 1 0 0 0 1",
                "0 0 1 0 1 0 -1 0 0",
                "-1 0 0 0 1 0 0 0 -1",
                "0 0 -1 0 1 0 1 0 0",
            )
            matrix = matrices[p.turns]
            offset_x, offset_z = p.part.native_center
            for _ in range(p.turns):
                offset_x, offset_z = offset_z, -offset_x
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
