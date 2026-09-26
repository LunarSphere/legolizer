"""API adapters: an optional concept image, then a design-and-review loop.

The image model only produces a single 3/4 concept picture used for colors and
proportions; it is never measured. A vision model writes a shape program (see
shape.py), and later reviews previews of the packed result.
"""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any

from legolizer.catalog import COLORS, DESIGN_COLORS, RECTANGULAR_PARTS, SPECIAL_PARTS
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
_RECTANGULAR_CATALOG = ", ".join(
    f"{part.code} ({part.width}x{part.depth}, {part.height} plates)" for part in RECTANGULAR_PARTS
)
_SPECIALTY_CATALOG = ", ".join(
    f"{part.code} ({part.width}x{part.depth}, {part.height} plates, {part.kind})"
    for part in SPECIAL_PARTS
)

_EXAMPLE = {
    "name": "red mushroom",
    "size": [8, 8, 6.4],
    "pieces": [],
    "parts": [
        {
            "name": "cap",
            "shape": "ellipsoid",
            "mode": "solid",
            "center": [4, 4, 3.2],
            "size": [8, 8, 6.4],
            "axis": "z",
            "taper": 1,
            "color": 4,
            "mirror": False,
        },
        {
            "name": "cap underside",
            "shape": "box",
            "mode": "carve",
            "center": [4, 4, 1.6],
            "size": [8, 8, 3.2],
            "axis": "z",
            "taper": 1,
            "color": 4,
            "mirror": False,
        },
        {
            "name": "stem",
            "shape": "cylinder",
            "mode": "solid",
            "center": [4, 4, 1.8],
            "size": [3, 3, 3.6],
            "axis": "z",
            "taper": 1,
            "color": 15,
            "mirror": False,
        },
        {
            "name": "left spot",
            "shape": "ellipsoid",
            "mode": "paint",
            "center": [2, 3, 5],
            "size": [2, 2, 1.2],
            "axis": "z",
            "taper": 1,
            "color": 15,
            "mirror": True,
        },
    ],
}

DESIGN_SYSTEM_PROMPT = f"""You design small sculptures that will be built from real LEGO bricks and plates.
You describe the sculpture as a shape program: an ordered list of 3D primitives that code converts to a
voxel grid and then packs with standard rectangular bricks. Add selected official specialty pieces
using the pieces list for rounded details, slopes, arches and curved corners.

COORDINATES. Primitive coordinates are in stud units (1 unit = 8 mm) on every axis, so proportions are true:
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

OFFICIAL RECTANGULAR INVENTORY. The packer automatically chooses from every listed brick and plate
to cover your shape; you do not need to specify these codes. Available parts, with footprint in studs
and height in plates: {_RECTANGULAR_CATALOG}. Model broad, buildable surfaces so long and wide parts
can bridge joints and reduce unnecessary small pieces. Do not distort the silhouette just to use a
larger part, and do not try to force every code into one model.

SPECIALTY PIECES. Use pieces: [] when none are needed. Each item has part (LDraw code), x, y,
z, color and rotation (0, 90, 180, 270). Unlike primitive coordinates, these x/y are integer studs
at the minimum corner of the rotated footprint, and z is an integer PLATE level (0.4 stud).
Pieces are placed after all primitives and replace voxels throughout their reserved bounding box.
They cannot overlap another explicit piece, including empty areas inside its bounding box.
No automatic mirror: specify each piece. Rotation 90 maps native +X toward model -Y.
Available parts at rotation 0: {_SPECIALTY_CATALOG}. Use round plate 6141 for buttons or lights;
round tile 98138 for a smooth exposed dot; slope 3040b for angled surfaces; arch 3659 for a real
opening; and curved corner 3063b for rounded corners. Their support contacts are part-specific:
6141 uses its stud/socket; 98138 has no top stud; 3040b rises toward +Y with a top stud at (x,y+1)
and both bottom sockets; 3659 has four top studs and bottom sockets at (x,y) and (x+3,y);
3063b has studs/sockets at (x,y) and (x+1,y+1), curving around the empty corner (x,y+1).
Place arch end sockets directly on columns and leave the opening clear.
Use a handful where they improve the subject. Support them on studded courses. Keep solid voxels
out of regions intended as arch openings; no other piece can be packed into a reserved envelope.
Specialty builds are previewed with their actual official LDraw geometry; ordinary builds use voxel views.

BUILDABILITY (critical). Bricks hold together only through studs, where one piece sits directly on top of
another. Side-by-side contact holds nothing. Every piece must overlap vertically with the rest of the
model: rest on something, or hang from something above it. Arms, wings, handles and hat brims that stick
out sideways need a solid course (in the same color) that spans from the body into them, e.g. a shoulder
box across the top of the torso and both arms. Avoid parts floating in the air or touching only at a
corner. The lowest part must rest on Z=0.
Ground contact alone does not join separate towers: connect them through a common bonded base.

COLORS. Only these LDraw color codes: {_PALETTE}.

METHOD. Block in the large masses first (body, head, limbs), then secondary shapes, then paint details.
Get the silhouette right from the front and the side, and make the most recognizable features large
enough to read at this low resolution. 8-40 parts is typical.

Example program:
{json.dumps(_EXAMPLE)}"""


def image_provider() -> str:
    """The concept image provider chosen by IMAGE_PROVIDER: openai (default) or grok."""
    provider = (os.getenv("IMAGE_PROVIDER") or "openai").strip().lower()
    if provider not in ("openai", "grok"):
        raise ValueError(f"Unknown IMAGE_PROVIDER {provider!r}; use openai or grok")
    return provider


def _grok_key() -> str | None:
    return os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")


def image_setup_problem() -> str | None:
    """Return why concept images cannot be generated with the current settings, or None."""
    try:
        provider = image_provider()
    except ValueError as exc:
        return str(exc)
    if provider == "grok" and not _grok_key():
        return "Concept images with IMAGE_PROVIDER=grok need GROK_API_KEY"
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        return "Concept images need OPENAI_API_KEY (or IMAGE_PROVIDER=grok with GROK_API_KEY)"
    return None


def generate_concept(description: str, output: Path) -> None:
    """Generate one 3/4 concept picture of the brick model with OpenAI Images or Grok Imagine."""
    from openai import OpenAI
    from PIL import Image

    if problem := image_setup_problem():
        raise RuntimeError(f"{problem}, or pass --no-concept")
    prompt = (
        "A single three-quarter view, from the front-right and slightly above, of a small "
        "sculpture built from LEGO bricks and plates with a few round plates, round tiles, "
        "slopes, arches and curved corner bricks, in a "
        "chunky, stepped, low-resolution style that a child could build from about 100-300 "
        "bricks. Solid, connected and able to stand on its own. Plain white background, even "
        "studio lighting, whole model in frame, no text, no minifigures, no baseplate. "
        f"Use only these colors: {_PALETTE.replace(',', ';')}.\n"
        f"Subject: {description}"
    )
    if image_provider() == "grok":
        # xAI serves an OpenAI-compatible images endpoint; it takes aspect_ratio instead of size.
        client = OpenAI(
            api_key=_grok_key(), base_url=os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")
        )
        response = client.images.generate(
            model=os.getenv("GROK_IMAGE_MODEL", "grok-imagine-image"),
            prompt=prompt,
            response_format="b64_json",
            extra_body={"aspect_ratio": "1:1"},
        )
        label = "Grok"
    else:
        response = OpenAI().images.generate(
            model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
            prompt=prompt,
            size="1024x1024",
            quality="medium",
        )
        label = "OpenAI"
    image_data = response.data[0].b64_json if response.data else None
    if not image_data:
        raise RuntimeError(f"{label} image response did not contain image data")
    # Grok may return JPEG; the design step sends concept.png with a PNG media type.
    with Image.open(io.BytesIO(base64.b64decode(image_data))) as image:
        image.save(output, format="PNG")


def design_program(description: str, concept: Path | None) -> dict:
    """Ask the vision model for a first shape program."""
    content: list[str | Path] = [f"Object: {description}"]
    if concept is not None:
        content += [
            "Concept image. Use it for colors, proportions and which features matter; it is an "
            "artist's impression, not something to measure.",
            concept,
        ]
    content.append(
        "Design the shape program. Put your reasoning about proportions and attachment in "
        "assessment, and set satisfied to false."
    )
    return _ask_json(content)


def revise_program(
    description: str, program: dict, preview: Path, concept: Path | None, report: str
) -> dict:
    """Show the model exact renders of its current program and ask for a corrected one."""
    content: list[str | Path] = [f"Object: {description}"]
    if concept is not None:
        content += ["Concept image the design is based on:", concept]
    content += [
        "Current shape program:\n" + json.dumps(program),
        "Current build preview: programs with explicit pieces show the official LDraw assembly in "
        "a three-quarter view. Other programs show voxel FRONT (+Y), RIGHT (+X), TOP (front at "
        "bottom), and isometric views. Evaluate the supplied view and the connection report.",
        preview,
        "Build report:\n" + report,
        "Review the renders against the object. List the most important problems: recognizability, "
        "proportions, missing or wrong features, colors, lumpy or lost details, and every problem in "
        "the build report (unattached pieces are build failures and must be fixed). Then return the "
        "complete corrected program, keeping what already works. If the report names only a few "
        "unattached features, change only those features and their supports; preserve the connected "
        "body, dimensions, colors and ground alignment. Set satisfied to true only if the "
        "model is clearly recognizable, well proportioned and the report shows no problems.",
    ]
    return _ask_json(content)


def revise_invalid_program(
    description: str, program: dict, error: str, concept: Path | None
) -> dict:
    content: list[str | Path] = [
        f"Object: {description}",
        "Current shape program:\n" + json.dumps(program),
        "Validation failed before a preview could be made:\n" + error,
        "Correct the validation error and return the complete program. Keep valid geometry, "
        "colors and proportions. For overlapping explicit pieces, move the conflicting pieces "
        "to free supported positions or remove a redundant decoration. Do not overlap their "
        "reserved boxes, including empty arch openings. Set satisfied to false; the corrected "
        "program still needs validation and packing.",
    ]
    if concept is not None:
        content += ["Reference image:", concept]
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
    mime_by_suffix = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
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
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "shape_program", "strict": True, "schema": RESPONSE_SCHEMA},
        },
        messages=[
            {"role": "system", "content": DESIGN_SYSTEM_PROMPT},
            {"role": "user", "content": parts},
        ],
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
            parts.append(
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}
            )
        else:
            parts.append({"type": "text", "text": item})
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    # Forcing a tool call makes Claude return input that matches the schema.
    message = anthropic.Anthropic(api_key=api_key).messages.create(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
        max_tokens=16000,
        system=DESIGN_SYSTEM_PROMPT,
        tools=[
            {
                "name": "submit_design",
                "description": "Submit the assessment and shape program.",
                "input_schema": RESPONSE_SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": "submit_design"},
        messages=[{"role": "user", "content": parts}],
    )
    if message.stop_reason == "max_tokens":
        raise ValueError("The design response was truncated")
    for block in message.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    raise ValueError("Claude did not return a design")
