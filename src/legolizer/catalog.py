"""Small official LDraw part and color palette used by the proof of concept."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PartSpec:
    code: str
    width: int
    depth: int
    height: int
    kind: str
    top_studs: tuple[tuple[int, int], ...] | None = None
    bottom_sockets: tuple[tuple[int, int], ...] | None = None
    native_center: tuple[int, int] = (0, 0)
    bricklink_id: str | None = None


PARTS = (
    # Rectangular parts use native X for the long side, Z for the short side.
    # Brick heights are three plate levels. All footprints are official LDraw parts.
    PartSpec("3005", 1, 1, 3, "brick"),
    PartSpec("3004", 2, 1, 3, "brick"),
    PartSpec("3622", 3, 1, 3, "brick"),
    PartSpec("3010", 4, 1, 3, "brick"),
    PartSpec("3009", 6, 1, 3, "brick"),
    PartSpec("3008", 8, 1, 3, "brick"),
    PartSpec("3003", 2, 2, 3, "brick"),
    PartSpec("3002", 3, 2, 3, "brick"),
    PartSpec("3001", 4, 2, 3, "brick"),
    PartSpec("3007", 8, 2, 3, "brick"),
    PartSpec("3024", 1, 1, 1, "plate"),
    PartSpec("3023", 2, 1, 1, "plate"),
    PartSpec("3623", 3, 1, 1, "plate"),
    PartSpec("3710", 4, 1, 1, "plate"),
    PartSpec("3666", 6, 1, 1, "plate"),
    PartSpec("3460", 8, 1, 1, "plate"),
    PartSpec("3022", 2, 2, 1, "plate"),
    PartSpec("3021", 3, 2, 1, "plate"),
    PartSpec("3020", 4, 2, 1, "plate"),
    PartSpec("3034", 8, 2, 1, "plate"),
    PartSpec("2456", 6, 2, 3, "brick"),
    PartSpec("3006", 10, 2, 3, "brick"),
    PartSpec("3795", 6, 2, 1, "plate"),
    PartSpec("3832", 10, 2, 1, "plate"),
    # Wide plates bridge overhangs (hat brims, roofs, wings) and tie courses together.
    PartSpec("3031", 4, 4, 1, "plate"),
    PartSpec("3032", 6, 4, 1, "plate"),
    PartSpec("3035", 8, 4, 1, "plate"),
    PartSpec("3958", 6, 6, 1, "plate"),
    PartSpec("3036", 8, 6, 1, "plate"),
    PartSpec("41539", 8, 8, 1, "plate"),
    PartSpec("6141", 1, 1, 1, "round_plate", bricklink_id="4073"),
    PartSpec("98138", 1, 1, 1, "round_tile", top_studs=()),
    PartSpec(
        "3040b", 1, 2, 3, "slope", top_studs=((0, 1),), native_center=(0, -10), bricklink_id="3040"
    ),
    PartSpec("3659", 4, 1, 3, "arch", bottom_sockets=((0, 0), (3, 0))),
    PartSpec(
        "3063b",
        2,
        2,
        3,
        "curved_brick",
        top_studs=((0, 0), (1, 1)),
        bottom_sockets=((0, 0), (1, 1)),
        native_center=(10, -10),
        bricklink_id="3063",
    ),
)

RECTANGULAR_PARTS = tuple(p for p in PARTS if p.kind in ("brick", "plate"))
SPECIAL_PARTS = tuple(p for p in PARTS if p not in RECTANGULAR_PARTS)
PART_BY_CODE = {p.code: p for p in PARTS}

# LDraw color code -> (official LDConfig name, sRGB). All are solid colors that
# exist for common bricks and plates. 7 and 8 are the pre-2004 grays, accepted
# in fixtures but not offered to the designer (use 71/72 instead).
COLOR_INFO = {
    0: ("Black", "#1B2A34"),
    1: ("Blue", "#1E5AA8"),
    2: ("Green", "#00852B"),
    4: ("Red", "#B40000"),
    7: ("Light_Grey", "#8A928D"),
    8: ("Dark_Grey", "#545955"),
    10: ("Bright_Green", "#58AB41"),
    14: ("Yellow", "#FAC80A"),
    15: ("White", "#F4F4F4"),
    19: ("Tan", "#D7BA8C"),
    25: ("Orange", "#D67923"),
    27: ("Lime", "#A5CA18"),
    28: ("Dark_Tan", "#897D62"),
    29: ("Bright_Pink", "#FF9ECD"),
    70: ("Reddish_Brown", "#5F3109"),
    71: ("Light_Bluish_Grey", "#969696"),
    72: ("Dark_Bluish_Grey", "#646464"),
    73: ("Medium_Blue", "#7396C8"),
    84: ("Medium_Nougat", "#AA7D55"),
    191: ("Bright_Light_Orange", "#FCAC00"),
    272: ("Dark_Blue", "#19325A"),
    288: ("Dark_Green", "#00451A"),
    320: ("Dark_Red", "#720012"),
}
COLORS = {code: name for code, (name, _) in COLOR_INFO.items()}
DESIGN_COLORS = (0, 1, 2, 4, 14, 15, 19, 25, 27, 28, 29, 70, 71, 72, 272)


def color_rgb(code: int) -> tuple[int, int, int]:
    value = COLOR_INFO[code][1]
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


MAX_STUDS = 32
MIN_STUDS = 16
SIZE_STEP = 4
STUD_LDU = 20
PLATE_LDU = 8


def orientations(part: PartSpec) -> tuple[tuple[int, int], ...]:
    """Return unique footprint orientations as (width, depth)."""
    return tuple(sorted({(part.width, part.depth), (part.depth, part.width)}, reverse=True))
