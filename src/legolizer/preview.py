"""Render exact orthographic and 3/4 previews of a voxel model with Pillow.

These renders are derived from the same cells the solver packs, so the
design reviewer sees precisely what will be built.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from legolizer.catalog import color_rgb

Cell = tuple[int, int, int]
PLATE = 0.4
UNIT = 20  # pixels per stud unit in the orthographic views
ISO_UNIT = 16
BACKGROUND = (255, 255, 255)
GRID = (225, 225, 225)
INK = (60, 60, 60)


def render_preview(cells: dict[Cell, int], output: Path, title: str = "") -> None:
    font = _font(14)
    small = _font(11)
    views = [
        ("FRONT (looking toward +Y)", _ortho(cells, "front", small)),
        ("RIGHT (front is on the left)", _ortho(cells, "right", small)),
        ("TOP (front is at the bottom)", _ortho(cells, "top", small)),
        ("3/4 VIEW (front-right)", _iso(cells)),
    ]
    gap, header = 24, 50 if title else 28
    width = sum(image.width for _, image in views) + gap * (len(views) + 1)
    height = max(image.height for _, image in views) + header + gap
    sheet = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    if title:
        draw.text((gap, 8), title, fill=INK, font=font)
    x = gap
    for label, image in views:
        draw.text((x, header - 20), label, fill=INK, font=font)
        sheet.paste(image, (x, header))
        x += image.width + gap
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _shade(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * factor))) for c in rgb)


def _ortho(cells: dict[Cell, int], view: str, font: ImageFont.ImageFont) -> Image.Image:
    """Project the nearest cell along the view axis; nearer surfaces are brighter."""
    xs, ys, zs = (max(c[i] for c in cells) + 1 for i in range(3))
    # Each view maps a cell to (image column, image row) and a depth toward the viewer.
    if view == "front":
        span_h, span_v = xs, zs * PLATE

        def key(x, y, z):
            return (x, z), y
    elif view == "right":
        span_h, span_v = ys, zs * PLATE

        def key(x, y, z):
            return (y, z), -x
    else:
        span_h, span_v = xs, ys

        def key(x, y, z):
            return (x, y), -z

    nearest: dict[tuple[int, int], tuple[int, int]] = {}
    for (x, y, z), color in cells.items():
        pixel, depth = key(x, y, z)
        if pixel not in nearest or depth < nearest[pixel][0]:
            nearest[pixel] = (depth, color)
    depths = [d for d, _ in nearest.values()]
    low, spread = min(depths), max(1, max(depths) - min(depths))

    margin_left, margin_bottom = 26, 18
    width = round(span_h * UNIT) + margin_left + 14
    height = round(span_v * UNIT) + margin_bottom + 4
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    base = height - margin_bottom

    def rect(h: int, v: int) -> tuple[int, int, int, int]:
        # Round shared edges identically so adjacent rows leave no hairline gaps.
        row = UNIT if view == "top" else PLATE * UNIT
        return (
            margin_left + h * UNIT,
            base - round((v + 1) * row),
            margin_left + (h + 1) * UNIT - 1,
            base - round(v * row) - 1,
        )

    for u in range(0, int(span_h) + 1):
        px = margin_left + u * UNIT
        draw.line((px, base - span_v * UNIT, px, base), fill=GRID)
        if u % 2 == 0:
            draw.text((px - 3, base + 3), str(u), fill=INK, font=font)
    for u in range(0, int(span_v) + 1):
        py = base - u * UNIT
        draw.line((margin_left, py, margin_left + span_h * UNIT, py), fill=GRID)
        if u % 2 == 0:
            draw.text((2, py - 6), str(u), fill=INK, font=font)
    for (h, v), (depth, color) in nearest.items():
        factor = 1.0 - 0.45 * (depth - low) / spread
        draw.rectangle(rect(h, v), fill=_shade(color_rgb(color), factor))
    return image


def _iso(cells: dict[Cell, int]) -> Image.Image:
    """Painter's-algorithm voxel render seen from the front-right, above."""
    c30, s30 = 0.866, 0.5

    def project(x: float, y: float, z: float) -> tuple[float, float]:
        return (x + y) * c30 * ISO_UNIT, ((x - y) * s30 - z) * ISO_UNIT

    faces = []
    for (x, y, z), color in cells.items():
        z0, z1 = z * PLATE, (z + 1) * PLATE
        rgb = color_rgb(color)
        depth = (x + 0.5) - (y + 0.5) + (z + 0.5) * PLATE
        if (x, y, z + 1) not in cells:
            faces.append(
                (
                    depth,
                    [(x, y, z1), (x + 1, y, z1), (x + 1, y + 1, z1), (x, y + 1, z1)],
                    _shade(rgb, 1.0),
                )
            )
        if (x, y - 1, z) not in cells:
            faces.append(
                (depth, [(x, y, z0), (x + 1, y, z0), (x + 1, y, z1), (x, y, z1)], _shade(rgb, 0.82))
            )
        if (x + 1, y, z) not in cells:
            faces.append(
                (
                    depth,
                    [(x + 1, y, z0), (x + 1, y + 1, z0), (x + 1, y + 1, z1), (x + 1, y, z1)],
                    _shade(rgb, 0.64),
                )
            )
    points = [project(*corner) for _, corners, _ in faces for corner in corners]
    min_x, min_y = min(p[0] for p in points), min(p[1] for p in points)
    width = round(max(p[0] for p in points) - min_x) + 8
    height = round(max(p[1] for p in points) - min_y) + 8
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for _, corners, fill in sorted(faces, key=lambda face: face[0]):
        polygon = [(px - min_x + 4, py - min_y + 4) for px, py in (project(*c) for c in corners)]
        draw.polygon(polygon, fill=fill, outline=_shade(fill, 0.85))
    return image
