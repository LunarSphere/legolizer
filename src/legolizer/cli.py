"""Command-line entry point."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from legolizer.catalog import COLORS, RECTANGULAR_PARTS
from legolizer.ldraw import read_mpd, write_mpd, write_parts_list
from legolizer.model import VoxelModel, load_model, parse_model
from legolizer.preview import render_preview
from legolizer.render import _ldraw_dir, render_model
from legolizer.shape import (
    PLATE,
    Region,
    Voxelized,
    edit_zone,
    in_zone,
    infill,
    parse_region,
    region_json,
    voxel_document,
    voxelize_program,
)
from legolizer.solver import (
    Placement,
    disconnected_placements,
    pack,
    placement_cells,
    repack_region,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def build_command(args: argparse.Namespace) -> int:
    output_dir: Path = args.out
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.fixture_json:
        model = load_model(args.fixture_json)
        document = json.loads(args.fixture_json.read_text(encoding="utf-8"))
        print(f"Packing {len(model.voxels)} occupied cells...")
        placements, loose = pack(model)
        cells = {(v.x, v.y, v.z): v.color for v in model.voxels}
        _render_build_preview(
            model, cells, placements, loose, output_dir / "preview.png", args.description
        )
    else:
        program, concept = _initial_program(args, output_dir)
        program, document, model, placements, loose = _refine(args, output_dir, program, concept)
        (output_dir / "program.json").write_text(
            json.dumps(program, indent=2) + "\n", encoding="utf-8"
        )
    (output_dir / "model.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return _write_build(output_dir, model, placements, loose)


def _initial_program(args: argparse.Namespace, output_dir: Path) -> tuple[dict, Path | None]:
    concept: Path | None = None
    if args.concept:
        suffix = args.concept.suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise ValueError("Concept image must be PNG, JPEG, WebP, or GIF")
        concept = output_dir / f"concept{suffix}"
        if args.concept.resolve() != concept.resolve():
            shutil.copyfile(args.concept, concept)
    elif not args.program and not args.no_concept:
        from legolizer.providers import generate_concept

        print("Generating a concept image...")
        concept = output_dir / "concept.png"
        generate_concept(args.description, concept)
        print(f"Concept saved to {concept}")

    if args.program:
        program = json.loads(args.program.read_text(encoding="utf-8"))
        # Accept a saved design response as well as a bare program.
        if (
            isinstance(program, dict)
            and "parts" not in program
            and isinstance(program.get("program"), dict)
        ):
            program = program["program"]
        return program, concept

    from legolizer.providers import design_program, estimate_size, parse_max_size

    max_size = getattr(args, "max_size", None)
    if max_size is None:
        print("Estimating build size...")
        sizing = estimate_size(args.description, concept)
        max_size = sizing["size"]
        print(f"Target size: {max_size} studs ({sizing['reason']})")
    else:
        max_size = parse_max_size(max_size)
        sizing = {"size": max_size, "reason": "Chosen by the user."}
    (output_dir / "size.json").write_text(json.dumps(sizing, indent=2) + "\n", encoding="utf-8")
    args.max_size = max_size

    print("Designing the shape program...")
    response = design_program(args.description, concept, max_size)
    _log(output_dir, "initial design", response.get("assessment", ""))
    return response["program"], concept


def _refine(args: argparse.Namespace, output_dir: Path, program: dict, concept: Path | None):
    """Voxelize, pack and render each program; let the reviewer correct it from the renders."""
    iterations = args.iterations if args.iterations is not None else (0 if args.program else 2)
    best = None
    report_progress = getattr(args, "progress", None)
    for round_ in range(iterations + 1):
        if report_progress:
            report_progress(round_, iterations + 1)
        (output_dir / f"program.v{round_}.json").write_text(
            json.dumps(program, indent=2) + "\n", encoding="utf-8"
        )
        try:
            voxelized = voxelize_program(program)
            document = voxel_document(voxelized.cells, voxelized.pieces)
            model = parse_model(document)
        except ValueError as exc:
            _log(output_dir, f"round {round_} validation error", str(exc))
            if round_ < iterations:
                from legolizer.providers import revise_invalid_program

                response = revise_invalid_program(
                    args.description, program, str(exc), concept, getattr(args, "max_size", 16)
                )
                _log(
                    output_dir, f"round {round_} validation review", response.get("assessment", "")
                )
                program = response["program"]
                continue
            if best is None:
                raise
            print(f"Round {round_}: revised program is invalid ({exc}); keeping round {best[0]}")
            break
        placements, loose = pack(model)
        if loose and getattr(args, "repair_supports", not args.program):
            supported = _support_program(program, voxelized, placements, loose)
            if supported is not None:
                supported_voxels = voxelize_program(supported)
                supported_document = voxel_document(supported_voxels.cells, supported_voxels.pieces)
                supported_model = parse_model(supported_document)
                supported_placements, supported_loose = pack(supported_model)
                if len(supported_loose) < len(loose):
                    _log(
                        output_dir,
                        f"round {round_} supports",
                        "Added short specialty support columns.",
                    )
                    program, voxelized, document, model = (
                        supported,
                        supported_voxels,
                        supported_document,
                        supported_model,
                    )
                    placements, loose = supported_placements, supported_loose
        preview = output_dir / f"preview.v{round_}.png"
        _render_build_preview(
            model,
            voxelized.cells,
            placements,
            loose,
            preview,
            program.get("name") or args.description,
        )
        (output_dir / f"program.v{round_}.json").write_text(
            json.dumps(program, indent=2) + "\n", encoding="utf-8"
        )
        report = _build_report(voxelized, placements, loose, getattr(args, "max_size", None))
        _log(output_dir, f"round {round_} build report", report)
        print(
            f"Round {round_}: {len(placements)} pieces, {len(loose)} unattached, "
            f"{len(voxelized.notes)} program warnings ({preview.name})"
        )
        # Unattached pieces are build failures, so they outrank everything else;
        # among equally sound rounds the latest, most reviewed one wins.
        if best is None or len(loose) <= len(best[5]):
            best = (round_, program, document, model, placements, loose, preview)
        if round_ == iterations:
            break

        from legolizer.providers import revise_program

        print("Reviewing the renders...")
        response = revise_program(
            args.description, program, preview, concept, report, getattr(args, "max_size", 16)
        )
        _log(output_dir, f"round {round_} review", response.get("assessment", ""))
        if response.get("satisfied") and not loose and not voxelized.notes:
            print("The reviewer is satisfied with this round.")
            break
        program = response["program"]

    round_, program, document, model, placements, loose, preview = best
    if loose and getattr(args, "prune_loose", not args.program):
        pruned = _prune_program(program, placements, loose)
        if pruned is not None:
            (output_dir / "program.before-pruning.json").write_text(
                json.dumps(program, indent=2) + "\n", encoding="utf-8"
            )
            (output_dir / "pruning.json").write_text(
                json.dumps({"removed": [p.document() for p in loose]}, indent=2) + "\n",
                encoding="utf-8",
            )
            _log(
                output_dir,
                "pruning",
                f"Removed {len(loose)} disconnected pieces; see pruning.json.",
            )
            program, document, model, placements = pruned
            loose = []
            preview = output_dir / "preview.pruned.png"
            _render_build_preview(
                model,
                voxelize_program(program).cells,
                placements,
                loose,
                preview,
                program.get("name") or args.description,
            )
    shutil.copyfile(preview, output_dir / "preview.png")
    print(f"Using round {round_}")
    return program, document, model, placements, loose


def _prune_program(program, placements, loose):
    if not loose or len(loose) > 8 or len(loose) * 20 > len(placements):
        return None
    voxels = voxelize_program(program)
    removed = {cell for piece in loose for cell in piece.envelope()}
    if len(removed) * 50 > len(voxels.cells):
        return None
    loose_set = set(loose)
    kept = [p for p in placements if p not in loose_set]
    if not kept or not any(p.z == 0 for p in kept) or disconnected_placements(kept):
        return None
    pruned = copy.deepcopy(program)
    pruned["pieces"] = [
        raw
        for raw, piece in zip(program.get("pieces", []), voxels.pieces, strict=True)
        if piece not in loose_set
    ]
    # Carve reserved envelopes too, so removing an explicit part cannot uncover old solids.
    for piece in loose:
        pruned["parts"].append(
            {
                "name": f"pruned {piece.part.code} at {piece.x},{piece.y},{piece.z}",
                "shape": "box",
                "mode": "carve",
                "axis": "z",
                "taper": 1,
                "center": [
                    piece.x + piece.width / 2,
                    piece.y + piece.depth / 2,
                    (piece.z + voxels.ground_offset + piece.part.height / 2) * PLATE,
                ],
                "size": [piece.width, piece.depth, piece.part.height * PLATE],
                "color": piece.color,
                "mirror": False,
            }
        )
    after = voxelize_program(pruned)
    if after.cells != {cell: color for cell, color in voxels.cells.items() if cell not in removed}:
        return None
    document = voxel_document(after.cells, after.pieces)
    return pruned, document, parse_model(document), kept


def _support_program(program, voxelized, placements, loose):
    """Propose at most eight short columns under unsupported explicit sockets."""
    loose_set = set(loose)
    floating = [p for p in voxelized.pieces if p in loose_set]
    if not floating:
        return None
    occupied = {cell for p in placements for cell in p.envelope()}
    anchors = {
        (x, y, p.z + p.part.height)
        for p in placements
        if p not in loose_set
        for x, y in p.contacts(top=True)
    }
    shift = program["pieces"][0]["z"] - voxelized.pieces[0].z
    additions = []
    for piece in floating:
        columns = []
        for x, y in sorted(piece.contacts(top=False)):
            for bottom in range(piece.z - 1, max(-1, piece.z - 7), -1):
                if (x, y, bottom) not in anchors:
                    continue
                if any((x, y, z) in occupied for z in range(bottom, piece.z)):
                    continue
                height = piece.z - bottom
                columns.append(
                    {
                        "name": f"support {piece.part.code} at {x},{y}",
                        "shape": "box",
                        "mode": "solid",
                        "center": [x + 0.5, y + 0.5, (bottom + shift + height / 2) * PLATE],
                        "size": [1, 1, height * PLATE],
                        "axis": "z",
                        "taper": 1,
                        "color": piece.color,
                        "mirror": False,
                    }
                )
                break
            else:
                columns = []
                break
        if len(additions) + len(columns) <= 8:
            additions.extend(columns)
    if not additions:
        return None
    supported = copy.deepcopy(program)
    supported["parts"].extend(additions)
    return supported


def _render_build_preview(model, cells, placements, loose, output, name):
    if model.pieces:
        source = output.with_suffix(".mpd")
        write_mpd(model, placements, source)
        render_model(source, output, timeout=120)
    else:
        render_preview(cells, output, title=_title(name, placements, loose))


def refine_command(args: argparse.Namespace) -> int:
    """Regenerate the selected pieces of a finished build, or the whole model when none are selected.

    Several candidate patches are designed in parallel and scored offline; a review round runs
    only while the best candidate still has problems. Pieces outside the editable zone keep
    their placement.
    """
    source: Path = args.source
    output_dir: Path = args.out
    if source.resolve() == output_dir.resolve():
        raise ValueError("Write the refined build to a new directory; the original stays as it is")
    output_dir.mkdir(parents=True, exist_ok=True)
    selection = list(getattr(args, "selection", None) or [])
    zone = edit_zone(selection)
    previous = read_mpd(source / "model.mpd")
    if (source / "model.json").is_file():
        parent = load_model(source / "model.json")
        base = {(v.x, v.y, v.z): v.color for v in parent.voxels}
        pieces = parent.pieces
    else:
        base = {cell: piece.color for piece in previous for cell in placement_cells(piece)}
        pieces = tuple(p for p in previous if p.part not in RECTANGULAR_PARTS)
    base.update({cell: piece.color for piece in pieces for cell in placement_cells(piece)})
    program = (
        json.loads((source / "program.json").read_text(encoding="utf-8"))
        if (source / "program.json").is_file()
        else None
    )
    concept = next(
        (
            p
            for pattern in ("concept.*", "source.*")
            for p in sorted(source.glob(pattern))
            if p.suffix.lower() in IMAGE_SUFFIXES
        ),
        None,
    )
    description = args.description or (program or {}).get("name") or "the existing model"
    request = args.request.strip()
    if not request:
        raise ValueError("Describe the change")
    width, depth, plates = (max(c[a] for c in base) + 1 for a in range(3))
    size = [width, depth, round(plates * PLATE, 1)]
    zone_text = None if zone is None else _zone_text(selection, zone)
    count = (
        args.candidates
        if getattr(args, "candidates", None) is not None
        else int(os.environ.get("LEGOLIZER_INFILL_CANDIDATES", "3"))
    )
    count = max(1, min(count, 6))
    reviews = args.iterations if args.iterations is not None else 1
    report_progress = getattr(args, "progress", None) or (lambda done, total: None)

    from legolizer.providers import design_infill, revise_infill

    before = output_dir / "before.png"
    render_preview(
        base,
        before,
        title=f"{description}  |  {'editable zone' if zone else 'whole model'}",
        regions=zone,
    )
    report_progress(0, reviews + 2)

    def evaluate(label: str, patch: dict) -> dict | None:
        try:
            voxelized = infill(base, patch, zone, pieces)
            document = voxel_document(voxelized.cells, voxelized.pieces)
            model = parse_model(document)
        except ValueError as exc:
            print(f"{label}: invalid patch ({exc})")
            _log(output_dir, f"{label} invalid", str(exc))
            return None
        placements, loose, rebuilt = repack_region(model, previous, zone)
        unchanged = voxelized.cells == base
        preview = output_dir / f"preview.{label}.png"
        render_preview(
            voxelized.cells, preview, title=_title(description, placements, loose), regions=zone
        )
        (output_dir / f"patch.{label}.json").write_text(
            json.dumps(patch, indent=2) + "\n", encoding="utf-8"
        )
        report = "\n".join(
            [
                _build_report(voxelized, placements, loose),
                _zone_report(voxelized.cells, zone, "The editable zone now holds"),
                _rebuilt_report(previous, rebuilt),
            ]
            + (["PROBLEM: the patch changed no cells."] if unchanged else [])
        )
        _log(output_dir, f"{label} build report", report)
        print(
            f"{label}: {len(placements)} pieces, {len(loose)} unattached, "
            f"{len(rebuilt)} earlier pieces rebuilt ({preview.name})"
        )
        # Unattached pieces outrank everything; then an edit that did something; then fewer
        # voxelizer notes; then fewer rebuilt pieces.
        score = (len(loose), unchanged, len(voxelized.notes), len(rebuilt))
        return {
            "label": label,
            "score": score,
            "patch": patch,
            "voxelized": voxelized,
            "document": document,
            "model": model,
            "placements": placements,
            "loose": loose,
            "rebuilt": rebuilt,
            "preview": preview,
            "report": report,
        }

    print(f"Designing {count} candidate edit{'s' if count > 1 else ''} in parallel...")
    base_report = _zone_report(base, zone, "The editable zone currently holds")
    candidates, errors = [], []
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = {
            pool.submit(
                design_infill,
                description,
                request,
                zone_text,
                size,
                before,
                base_report,
                program,
                concept,
            ): f"c{index + 1}"
            for index in range(count)
        }
        # Score each candidate as it arrives, while the other requests are still out.
        for future in as_completed(futures):
            label = futures[future]
            try:
                response = future.result()
            except Exception as exc:  # one failed request should not sink the others
                print(f"{label}: design request failed ({exc})")
                errors.append(exc)
                continue
            _log(output_dir, f"{label} design", response.get("assessment", ""))
            if result := evaluate(label, response["program"]):
                candidates.append(result)
    if not candidates:
        if len(errors) == count:
            raise errors[0]
        raise ValueError("Every candidate edit was invalid. Try a more specific request.")
    report_progress(1, reviews + 2)
    best = min(candidates, key=lambda c: (c["score"], c["label"]))
    for round_ in range(reviews):
        if not any(best["score"][:3]):
            break
        report_progress(2 + round_, reviews + 2)
        print(f"Reviewing {best['label']}...")
        response = revise_infill(
            description,
            request,
            zone_text,
            size,
            best["patch"],
            best["preview"],
            best["report"],
            concept,
        )
        _log(output_dir, f"review {round_ + 1}", response.get("assessment", ""))
        result = evaluate(f"r{round_ + 1}", response["program"])
        if result and result["score"][:3] <= best["score"][:3]:
            best = result

    if best["score"][1]:
        raise ValueError(
            "The edit did not change the model. Select more bricks or be more specific."
        )
    shutil.copyfile(best["preview"], output_dir / "preview.png")
    print(f"Using {best['label']}")
    patch, voxelized, document = best["patch"], best["voxelized"], best["document"]
    clip = [region_json(box) for box in zone] if zone else None
    parts = [part for part in patch.get("parts", []) if isinstance(part, dict)]
    if clip:
        parts = [{**part, "clip": clip} for part in parts]
    added = [piece.document() for piece in voxelized.pieces[len(pieces) :]]
    if program is not None:
        try:
            replayable = voxelize_program(program).cells == base
        except ValueError:
            replayable = False
        if replayable:
            program = {
                **program,
                "parts": program["parts"] + parts,
                "pieces": program.get("pieces", []) + added,
            }
            (output_dir / "program.json").write_text(
                json.dumps(program, indent=2) + "\n", encoding="utf-8"
            )
    (output_dir / "model.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    refinement = {
        "request": request,
        "selection": [region_json(box) for box in selection],
        "zone": clip,
        "patch": {**patch, "parts": parts, "pieces": added},
        "candidates": len(candidates),
        "chosen": best["label"],
        "keptPieces": len(previous) - len(best["rebuilt"]),
        "rebuilt": [
            {"part": p.part.code, "x": p.x, "y": p.y, "z": p.z, "color": p.color}
            for p in best["rebuilt"]
        ],
        "notes": voxelized.notes,
    }
    (output_dir / "refine.json").write_text(
        json.dumps(refinement, indent=2) + "\n", encoding="utf-8"
    )
    return _write_build(output_dir, best["model"], best["placements"], best["loose"])


def _box_text(box: Region) -> str:
    (x0, y0, z0), (x1, y1, z1) = box
    return f"X {x0}..{x1 + 1}, Y {y0}..{y1 + 1}, Z {z0 * PLATE:g}..{(z1 + 1) * PLATE:g}"


def _zone_text(selection: list[Region], zone: list[Region]) -> str:
    return (
        "Selected bricks: " + "; ".join(_box_text(box) for box in selection) + ". "
        "Editable zone (each selected brick plus one brick around it): "
        + "; ".join(_box_text(box) for box in zone)
        + ". Stud units; a cell changes only if its center is inside the zone."
    )


def _zone_report(cells: dict, zone: list[Region] | None, label: str) -> str:
    inside = [color for cell, color in cells.items() if in_zone(cell, zone)]
    if not inside:
        return f"{label} no filled cells."
    counts = Counter(inside).most_common()
    colors = ", ".join(
        f"{COLORS[color].replace('_', ' ').lower()} {count}" for color, count in counts
    )
    return f"{label} {len(inside)} filled cells ({colors})."


def _rebuilt_report(previous: list[Placement], rebuilt: list[Placement]) -> str:
    if not rebuilt:
        return f"All {len(previous)} earlier pieces kept their placement."
    return (
        f"{len(previous) - len(rebuilt)} of {len(previous)} earlier pieces kept their placement; "
        f"{len(rebuilt)} in the editable zone were rebuilt."
    )


def _parse_region_arg(text: str) -> Region:
    try:
        values = [int(v) for v in text.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "a selection must be six integers: x0,y0,z0,x1,y1,z1"
        ) from exc
    if len(values) != 6:
        raise argparse.ArgumentTypeError("a selection must be six integers: x0,y0,z0,x1,y1,z1")
    try:
        return parse_region({"min": values[:3], "max": values[3:]})
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _build_report(
    voxelized: Voxelized,
    placements: list[Placement],
    loose: list[Placement],
    max_size: int | None = None,
) -> str:
    cells = voxelized.cells
    width = max(x for x, _, _ in cells) + 1
    depth = max(y for _, y, _ in cells) + 1
    plates = max(z for _, _, z in cells) + 1
    height = plates * PLATE
    longest = max(width, depth, height)
    lines = [
        f"Size: {width} x {depth} studs, {height:g} units ({plates} plates) tall; "
        f"{len(placements)} official pieces."
    ]
    if max_size is not None and longest > max_size + 1:
        lines.append(
            f"PROBLEM: the longest side is {longest:g} units but the target is about {max_size} studs. "
            "Shrink the model toward that target."
        )
    if voxelized.pieces:
        lines.append(
            "Specialty pieces use official LDraw geometry in the preview. "
            "Their rectangular envelopes are reserved against overlap; "
            "arch openings and curved corners remain empty in the actual build."
        )
    if voxelized.notes:
        lines.append("Program warnings:")
        lines += [f"- {note}" for note in voxelized.notes]
    if loose:
        by_part: dict[str, list[tuple[int, int, int]]] = {}
        for piece in loose:
            for cell in _piece_cells(piece):
                by_part.setdefault(voxelized.owners.get(cell, "unknown"), []).append(cell)
        lines.append(
            f"UNATTACHED: {len(loose)} pieces do not connect to the main build through studs. "
            "They come from these parts:"
        )
        for name, part_cells in sorted(by_part.items(), key=lambda item: -len(item[1])):
            x = sum(c[0] for c in part_cells) / len(part_cells) + 0.5
            y = sum(c[1] for c in part_cells) / len(part_cells) + 0.5
            z = (sum(c[2] for c in part_cells) / len(part_cells) + 0.5) * PLATE
            lines.append(f"- {name}: {len(part_cells)} cells around ({x:.1f}, {y:.1f}, {z:.1f})")
        lines.append(
            "Fix each by overlapping it vertically with the body (a shared course above or below "
            "it, in one color), or remove it."
        )
    else:
        lines.append("Structure: every piece connects to the main build.")
    return "\n".join(lines)


def _piece_cells(piece: Placement):
    for z in range(piece.z, piece.z + piece.part.height):
        for y in range(piece.y, piece.y + piece.depth):
            for x in range(piece.x, piece.x + piece.width):
                yield x, y, z


def _title(name: str, placements: list[Placement], loose: list[Placement]) -> str:
    name = name if len(name) <= 80 else name[:77] + "..."
    return f"{name}  |  {len(placements)} pieces, {len(loose)} unattached"


def _log(output_dir: Path, label: str, text: str) -> None:
    with (output_dir / "design.log").open("a", encoding="utf-8") as log:
        log.write(f"== {label} ==\n{text.strip()}\n\n")


def _write_build(
    output_dir: Path, model: VoxelModel, placements: list[Placement], loose: list[Placement]
) -> int:
    mpd_path = output_dir / "model.mpd"
    parts_path = output_dir / "parts.json"
    write_mpd(model, placements, mpd_path)
    write_parts_list(placements, parts_path)

    from ldraw.parts import Parts
    from ldraw.validation import iter_ldr_issues

    library = _ldraw_dir()
    if library is None or not (Path(library) / "parts.lst").is_file():
        raise RuntimeError(
            "Configure the official library with ldraw download, or set LDRAW_LIBRARY_PATH"
        )
    issues = list(iter_ldr_issues(mpd_path, Parts(Path(library) / "parts.lst")))
    if issues:
        raise RuntimeError(f"Official LDraw library validation failed: {issues}")

    # Parse the emitted model using pyldraw3 so malformed MPD fails before success.
    try:
        from ldraw import read_model

        read_model(mpd_path)
    except ImportError as exc:
        raise RuntimeError("pyldraw3 is required; run `uv sync`") from exc
    except Exception as exc:
        raise RuntimeError(f"pyldraw3 could not parse generated MPD: {exc}") from exc

    print(f"Preview: {output_dir / 'preview.png'}")
    print(f"MPD: {mpd_path}")
    print(f"Parts list: {parts_path}")
    print(f"Placed {len(placements)} official LDraw pieces")
    if loose:
        details = ", ".join(f"{p.part.code}@({p.x},{p.y},{p.z})" for p in loose)
        raise RuntimeError(
            f"{len(loose)} pieces are not attached to the main build ({details}). "
            "The files above were written for inspection; see design.log."
        )
    return 0


def main() -> None:
    # Read .env from the working directory upward; existing environment variables win.
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(
        prog="legolizer", description="Generate a brick build from an object description"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="generate and solve a model")
    build.add_argument("description", help="object to build")
    build.add_argument("--out", type=Path, default=Path("builds/model"), help="output directory")
    build.add_argument(
        "--concept", "--views", type=Path, help="use this concept image instead of generating one"
    )
    build.add_argument(
        "--no-concept",
        action="store_true",
        help="design from the text alone, without a concept image",
    )
    build.add_argument(
        "--program",
        type=Path,
        help="start from a saved shape program (no API calls unless --iterations)",
    )
    build.add_argument(
        "--iterations", type=int, help="render-and-review rounds after the first design (default 2)"
    )
    build.add_argument(
        "--fixture-json", type=Path, help="reuse a voxel JSON document and skip every API"
    )
    build.add_argument(
        "--max-size",
        type=int,
        help="longest side in studs (16-32, steps of 4); omit to estimate from the description",
    )
    build.set_defaults(handler=build_command)

    refine = subparsers.add_parser("refine", help="regenerate selected bricks of a finished build")
    refine.add_argument(
        "source", type=Path, help="directory of the build to refine (left unchanged)"
    )
    refine.add_argument("request", help="change to make")
    refine.add_argument(
        "--select",
        dest="selection",
        type=_parse_region_arg,
        action="append",
        default=[],
        help="a selected brick's inclusive cells x0,y0,z0,x1,y1,z1 (x/y in studs, z in plates); "
        "repeat for more bricks. The edit covers them plus one brick around each; "
        "without --select the whole model may change",
    )
    refine.add_argument(
        "--out", type=Path, required=True, help="output directory for the refined build"
    )
    refine.add_argument(
        "--description", help="what the whole model is (defaults to the program name)"
    )
    refine.add_argument(
        "--candidates",
        type=int,
        help="candidate edits designed in parallel (default LEGOLIZER_INFILL_CANDIDATES or 3)",
    )
    refine.add_argument(
        "--iterations",
        type=int,
        help="review rounds, run only while the best candidate has problems (default 1)",
    )
    refine.set_defaults(handler=refine_command)

    render = subparsers.add_parser("render", help="render an MPD/LDR model")
    render.add_argument("input", type=Path)
    render.add_argument("--out", type=Path, default=Path("render.png"))
    render.set_defaults(
        handler=lambda args: (render_model(args.input, args.out), print(args.out), 0)[-1]
    )

    args = parser.parse_args()
    try:
        result = args.handler(args)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(result)


if __name__ == "__main__":
    main()
