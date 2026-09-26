"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from legolizer.ldraw import write_mpd, write_parts_list
from legolizer.model import VoxelModel, load_model, parse_model
from legolizer.preview import render_preview
from legolizer.render import _ldraw_dir, render_model
from legolizer.shape import PLATE, Voxelized, voxel_document, voxelize_program
from legolizer.solver import Placement, pack

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

    from legolizer.providers import design_program

    print("Designing the shape program...")
    response = design_program(args.description, concept)
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
        try:
            voxelized = voxelize_program(program)
            document = voxel_document(voxelized.cells, voxelized.pieces)
            model = parse_model(document)
        except ValueError as exc:
            if best is None:
                raise
            print(f"Round {round_}: revised program is invalid ({exc}); keeping round {best[0]}")
            break
        placements, loose = pack(model)
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
        report = _build_report(voxelized, placements, loose)
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
        response = revise_program(args.description, program, preview, concept, report)
        _log(output_dir, f"round {round_} review", response.get("assessment", ""))
        if response.get("satisfied") and not loose and not voxelized.notes:
            print("The reviewer is satisfied with this round.")
            break
        program = response["program"]

    round_, program, document, model, placements, loose, preview = best
    shutil.copyfile(preview, output_dir / "preview.png")
    print(f"Using round {round_}")
    return program, document, model, placements, loose


def _render_build_preview(model, cells, placements, loose, output, name):
    if model.pieces:
        source = output.with_suffix(".mpd")
        write_mpd(model, placements, source)
        render_model(source, output, timeout=120)
    else:
        render_preview(cells, output, title=_title(name, placements, loose))


def _build_report(voxelized: Voxelized, placements: list[Placement], loose: list[Placement]) -> str:
    cells = voxelized.cells
    width = max(x for x, _, _ in cells) + 1
    depth = max(y for _, y, _ in cells) + 1
    plates = max(z for _, _, z in cells) + 1
    lines = [
        f"Size: {width} x {depth} studs, {plates * PLATE:g} units ({plates} plates) tall; "
        f"{len(placements)} official pieces."
    ]
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
    build.set_defaults(handler=build_command)

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
