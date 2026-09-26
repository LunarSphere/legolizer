"""API adapters: an optional concept image, then a design-and-review loop.

The image model only produces a single 3/4 concept picture used for colors and
proportions; it is never measured. A vision model writes a shape program (see
shape.py), and later reviews exact renders of the voxelized result.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from legolizer.catalog import COLORS, DESIGN_COLORS
from legolizer.shape import MAX_HEIGHT, PROGRAM_SCHEMA

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "assessment": {"type": "string"},
        "satisfied": {"type": "boolean"},
        "program": PROGRAM_SCHEMA,
    },
    "required": ["assessment", "satisfied", "program"],
}

_PALETTE = ", ".join(f"{code} {COLORS[code].replace('_', ' ').lower()}" for code in DESIGN_COLORS)

_EXAMPLE = {
    "name": "red mushroom",
    "size": [8, 8, 6.4],
    "parts": [
        {"name": "cap", "shape": "ellipsoid", "mode": "solid", "center": [4, 4, 3.2], "size": [8, 8, 6.4],
         "axis": "z", "taper": 1, "color": 4, "mirror": False},
        {"name": "cap underside", "shape": "box", "mode": "carve", "center": [4, 4, 1.6], "size": [8, 8, 3.2],
         "axis": "z", "taper": 1, "color": 4, "mirror": False},
        {"name": "stem", "shape": "cylinder", "mode": "solid", "center": [4, 4, 1.8], "size": [3, 3, 3.6],
         "axis": "z", "taper": 1, "color": 15, "mirror": False},
        {"name": "left spot", "shape": "ellipsoid", "mode": "paint", "center": [2, 3, 5], "size": [2, 2, 1.2],
         "axis": "z", "taper": 1, "color": 15, "mirror": True},
    ],
}

DESIGN_SYSTEM_PROMPT = f"""You design small sculptures that will be built from real LEGO bricks and plates.
You describe the sculpture as a shape program: an ordered list of 3D primitives that code converts to a
voxel grid and then packs with standard rectangular bricks.

COORDINATES. All numbers are in stud units (1 unit = 8 mm) on every axis, so proportions are true:
a [4, 4, 4] box is a cube. One brick is 1.2 units tall and one plate is 0.4 units tall.
X is width (left to right as seen from the front). Y is depth: Y=0 is the FRONT face and Y grows toward
the back. Z is height: Z=0 is the ground. The build volume is X 0..20, Y 0..20, Z 0..{MAX_HEIGHT:g}.
Small recognizable models are usually 8-16 units on their longest side. program.size is the overall
[width, depth, height]; keep every part inside it.

VOXELS. Cells are 1 x 1 stud and 1 plate (0.4) tall; a cell is filled when its center lies inside a
shape. Horizontal features narrower than 1 unit disappear, so limbs and details must be at least 1 unit
wide. Parts run in order:
- solid: fill cells with the part's color (overwriting earlier colors).
- paint: recolor only cells that are already filled; adds no volume. Use it for eyes, mouths, buttons,
  stripes and logos, placed after the solids they decorate, overlapping the outer surface layer.
- carve: remove cells, e.g. the gap between legs, windows, the underside of a cap.
Shapes: box, ellipsoid, cylinder. center is the shape's center; size is its full extent along X, Y, Z
(diameters for round shapes). cylinder uses axis (x, y or z) as its length direction. taper (0..1)
shrinks a box or cylinder cross-section linearly toward the + end of its axis (1 = none, 0 = a point),
for cones, roofs, hats and tree tops; ellipsoids ignore it. mirror: true also places a copy reflected
across X = size[0]/2; define only the left-hand one of a symmetric pair. Always give every field; use
axis "z", taper 1 and mirror false when they do not apply.

BUILDABILITY (critical). Bricks hold together only through studs, where one piece sits directly on top of
another. Side-by-side contact holds nothing. Every piece must overlap vertically with the rest of the
model: rest on something, or hang from something above it. Arms, wings, handles and hat brims that stick
out sideways need a solid course (in the same color) that spans from the body into them, e.g. a shoulder
box across the top of the torso and both arms. Avoid parts floating in the air or touching only at a
corner. The lowest part must rest on Z=0.

COLORS. Only these LDraw color codes: {_PALETTE}.

METHOD. Block in the large masses first (body, head, limbs), then secondary shapes, then paint details.
Get the silhouette right from the front and the side, and make the most recognizable features large
enough to read at this low resolution. 8-40 parts is typical.

Example program:
{json.dumps(_EXAMPLE)}"""


def generate_concept(description: str, output: Path) -> None:
    """Generate one 3/4 concept picture of the brick model with OpenAI Images."""
    from openai import OpenAI

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY to generate a concept image, or pass --no-concept")
    response = OpenAI().images.generate(
        model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        prompt=(
            "A single three-quarter view, from the front-right and slightly above, of a small "
            "sculpture built entirely from standard rectangular LEGO bricks and plates, in a "
            "chunky, stepped, low-resolution style that a child could build from about 100-300 "
            "bricks. Solid, connected and able to stand on its own. Plain white background, even "
            "studio lighting, whole model in frame, no text, no minifigures, no baseplate. "
            f"Use only these colors: {_PALETTE.replace(',', ';')}.\n"
            f"Subject: {description}"
        ),
        size="1024x1024",
        quality="medium",
    )
    image_data = response.data[0].b64_json
    if not image_data:
        raise RuntimeError("OpenAI image response did not contain image data")
    output.write_bytes(base64.b64decode(image_data))


def design_program(description: str, concept: Path | None) -> dict:
    """Ask the vision model for a first shape program."""
    content: list[str | Path] = [f"Object: {description}"]
    if concept is not None:
        content += [
            "Concept image. Use it for colors, proportions and which features matter; it is an "
            "artist's impression, not something to measure.",
            concept,
        ]
    content.append("Design the shape program. Put your reasoning about proportions and attachment in "
                   "assessment, and set satisfied to false.")
    return _ask_json(content)


def revise_program(description: str, program: dict, preview: Path, concept: Path | None, report: str) -> dict:
    """Show the model exact renders of its current program and ask for a corrected one."""
    content: list[str | Path] = [f"Object: {description}"]
    if concept is not None:
        content += ["Concept image the design is based on:", concept]
    content += [
        "Current shape program:\n" + json.dumps(program),
        "Exact renders of the current voxel result. These are what will be built. Axes are in stud "
        "units; FRONT looks toward +Y, RIGHT shows the +X side with the front on the left, TOP has "
        "the front at the bottom. Shading is darker for surfaces farther from the viewer.",
        preview,
        "Build report:\n" + report,
        "Review the renders against the object. List the most important problems: recognizability, "
        "proportions, missing or wrong features, colors, lumpy or lost details, and every problem in "
        "the build report (unattached pieces are build failures and must be fixed). Then return the "
        "complete corrected program, keeping what already works. Set satisfied to true only if the "
        "model is clearly recognizable, well proportioned and the report shows no problems.",
    ]
    return _ask_json(content)


def _region_rules(region_text: str, size: list) -> str:
    return (
        "REGION EDIT. You are changing one region of an existing model, not designing a new one. "
        f"The editable region is {region_text}. It is outlined in magenta in the renders. Return a patch "
        "program: parts that run after the existing model, in order, with the usual solid / paint / carve "
        "meaning. Every patch cell is clipped to the region, so nothing outside it can change. Existing "
        "cells inside the region stay unless you carve or paint them; to replace the region's content, "
        "start with a carve box that covers the whole region. New material must still connect: overlap "
        "it vertically with kept cells at the region's edge, or with cells you add. Use the model's "
        f"coordinates and set program.size to {json.dumps(size)}. Use as few parts as the change needs."
    )


def design_infill(description: str, request: str, region_text: str, size: list, preview: Path,
                  report: str, program: dict | None, concept: Path | None) -> dict:
    """Ask for a patch program that changes only the selected region."""
    content: list[str | Path] = [f"Object: {description}", _region_rules(region_text, size)]
    if program is not None:
        content.append("Shape program that produced the existing model:\n" + json.dumps(program))
    if concept is not None:
        content += ["Concept image the model was based on:", concept]
    content += [
        "Exact renders of the existing model with the region outlined:", preview,
        "Existing model report:\n" + report,
        f"Requested change for the region: {request}",
        "Put your plan in assessment, set satisfied to false, and return the patch program.",
    ]
    return _ask_json(content)


def revise_infill(description: str, request: str, region_text: str, size: list, patch: dict,
                  preview: Path, report: str, concept: Path | None) -> dict:
    """Show the model the edited result and ask for a corrected patch."""
    content: list[str | Path] = [f"Object: {description}", _region_rules(region_text, size)]
    if concept is not None:
        content += ["Concept image the model was based on:", concept]
    content += [
        f"Requested change for the region: {request}",
        "Current patch program:\n" + json.dumps(patch),
        "Exact renders of the model after the patch, region outlined. Axes are in stud units; FRONT "
        "looks toward +Y, RIGHT shows the +X side with the front on the left, TOP has the front at the "
        "bottom.", preview,
        "Build report:\n" + report,
        "Check that the region now shows the requested change and fits the rest of the model, and fix "
        "every problem in the build report (unattached pieces are build failures). Return the complete "
        "corrected patch. Set satisfied to true only if the change is clearly visible and the report "
        "shows no problems.",
    ]
    return _ask_json(content)


def _provider() -> str:
    anthropic_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    provider = (os.getenv("SCENE_PROVIDER") or ("anthropic" if anthropic_key else "openai")).lower()
    if provider == "anthropic" and not anthropic_key:
        raise RuntimeError("Set ANTHROPIC_API_KEY, or SCENE_PROVIDER=openai, to design the model")
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY or ANTHROPIC_API_KEY to design the model")
    if provider not in ("openai", "anthropic"):
        raise ValueError(f"Unknown SCENE_PROVIDER {provider!r}; use openai or anthropic")
    return provider


def _image_part(path: Path) -> tuple[str, str]:
    mime_by_suffix = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".webp": "image/webp", ".gif": "image/gif"}
    try:
        mime = mime_by_suffix[path.suffix.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported image format: {path.suffix}") from exc
    return mime, base64.b64encode(path.read_bytes()).decode("ascii")


def _ask_json(content: list[str | Path]) -> dict:
    if _provider() == "anthropic":
        return _ask_claude(content)
    return _ask_openai(content)


def _ask_openai(content: list[str | Path]) -> dict:
    from openai import OpenAI

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, Path):
            mime, data = _image_part(item)
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
        else:
            parts.append({"type": "text", "text": item})
    response = OpenAI().chat.completions.create(
        model=os.getenv("OPENAI_SCENE_MODEL", "gpt-5"),
        # Reasoning models spend part of this budget thinking before they answer.
        max_completion_tokens=32000,
        response_format={"type": "json_schema",
                         "json_schema": {"name": "shape_program", "strict": True, "schema": RESPONSE_SCHEMA}},
        messages=[{"role": "system", "content": DESIGN_SYSTEM_PROMPT}, {"role": "user", "content": parts}],
    )
    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise ValueError("The design response was truncated")
    if getattr(choice.message, "refusal", None):
        raise ValueError(f"The model declined: {choice.message.refusal}")
    return json.loads(choice.message.content or "{}")


def _ask_claude(content: list[str | Path]) -> dict:
    import anthropic

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, Path):
            mime, data = _image_part(item)
            parts.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
        else:
            parts.append({"type": "text", "text": item})
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    # Forcing a tool call makes Claude return input that matches the schema.
    message = anthropic.Anthropic(api_key=api_key).messages.create(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
        max_tokens=16000,
        system=DESIGN_SYSTEM_PROMPT,
        tools=[{"name": "submit_design", "description": "Submit the assessment and shape program.",
                "input_schema": RESPONSE_SCHEMA}],
        tool_choice={"type": "tool", "name": "submit_design"},
        messages=[{"role": "user", "content": parts}],
    )
    if message.stop_reason == "max_tokens":
        raise ValueError("The design response was truncated")
    for block in message.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    raise ValueError("Claude did not return a design")
