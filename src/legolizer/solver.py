"""Greedy exact-cell packer with randomized restarts and a connectivity check."""

from __future__ import annotations

import random
import time
from collections import Counter, defaultdict

from legolizer.catalog import RECTANGULAR_PARTS, orientations
from legolizer.model import Placement, VoxelModel

Cell = tuple[int, int, int]


def solve(model: VoxelModel) -> list[Placement]:
    """Cover every voxel with catalog pieces; fail if any piece is not attached."""
    placements, loose = pack(model)
    if loose:
        details = ", ".join(f"{p.part.code}@({p.x},{p.y},{p.z})" for p in loose)
        raise ValueError(
            f"Build has floating/disconnected parts that cannot be repacked: {details}"
        )
    return placements


def pack(
    model: VoxelModel, attempts: int = 24, recolor_hidden: bool = True, time_budget: float = 6.0
) -> tuple[list[Placement], list[Placement]]:
    """Return (placements, loose placements) for the best of several packings.

    Attempt 0 is deterministic. Later attempts vary the scan direction per
    course, which staggers seams between layers the way bricklayers bond a wall,
    and keep the packing with the fewest unattached pieces.
    """
    cells: dict[Cell, int | None] = {(v.x, v.y, v.z): v.color for v in model.voxels}
    if not cells:
        placements = list(model.pieces)
        return placements, disconnected_placements(placements)
    fallback = Counter(cells.values()).most_common(1)[0][0]
    if recolor_hidden:
        # A cell enclosed on every side is invisible, so any brick color may
        # cover it. Bricks can then span color boundaries inside the model.
        hidden = [
            cell
            for cell in cells
            if all(
                (cell[0] + dx, cell[1] + dy, cell[2] + dz) in cells or cell[2] + dz < 0
                for dx, dy, dz in (
                    (1, 0, 0),
                    (-1, 0, 0),
                    (0, 1, 0),
                    (0, -1, 0),
                    (0, 0, 1),
                    (0, 0, -1),
                )
            )
        ]
        for cell in hidden:
            cells[cell] = None
    best: tuple[tuple[int, int], list[Placement], list[Placement]] | None = None
    started = time.monotonic()
    for attempt in range(max(1, attempts)):
        if attempt and time.monotonic() - started > time_budget:
            break
        rng = random.Random(attempt) if attempt else None
        placements = _greedy(cells, model, rng, fallback)
        placements, loose = _repair(placements, cells, frozenset(model.pieces))
        score = (len(loose), len(placements))
        if best is None or score < best[0]:
            best = (score, placements, loose)
        if not loose:
            break
    return best[1], best[2]


def _greedy(
    cells: dict[Cell, int | None], model: VoxelModel, rng: random.Random | None, fallback: int
) -> list[Placement]:
    remaining = dict(cells)
    placements: list[Placement] = list(model.pieces)
    by_top: dict[int, list[Placement]] = defaultdict(list)
    fixed_by_bottom: dict[int, list[Placement]] = defaultdict(list)
    placed_color: dict[Cell, int] = {}
    for piece in model.pieces:
        by_top[piece.z + piece.part.height].append(piece)
        fixed_by_bottom[piece.z].append(piece)
    candidates = sorted(
        RECTANGULAR_PARTS,
        key=lambda p: (p.width * p.depth * p.height, p.height, p.width, p.depth),
        reverse=True,
    )
    top_z = model.height * 3

    layers: dict[int, list[Cell]] = defaultdict(list)
    for cell in cells:
        layers[cell[2]].append(cell)
    for z in sorted(layers):
        flip_x = bool(rng and rng.random() < 0.5)
        flip_y = bool(rng and rng.random() < 0.5)
        order = sorted(
            layers[z], key=lambda c: (-c[1] if flip_y else c[1], -c[0] if flip_x else c[0])
        )
        for seed in order:
            if seed not in remaining:
                continue
            x, y, _ = seed
            fitting: list[tuple[float, int, float, Placement]] = []
            for part in candidates:
                if part.height > top_z - z:
                    continue
                for width, depth in orientations(part):
                    # Bricks grow in the scan direction so the seed stays a corner.
                    x0 = x - width + 1 if flip_x else x
                    y0 = y - depth + 1 if flip_y else y
                    colors: set[int] = set()
                    fits = True
                    for cz in range(z, z + part.height):
                        for cy in range(y0, y0 + depth):
                            for cx in range(x0, x0 + width):
                                cell = (cx, cy, cz)
                                if cell not in remaining:
                                    fits = False
                                    break
                                if remaining[cell] is not None:
                                    colors.add(remaining[cell])
                            if not fits or len(colors) > 1:
                                break
                        if not fits or len(colors) > 1:
                            break
                    if not fits or len(colors) > 1:
                        continue
                    # Fully hidden bricks match whatever is below them.
                    color = colors.pop() if colors else placed_color.get((x, y, z - 1), fallback)
                    placement = Placement(part, x0, y0, z, color, width, depth)
                    lower = by_top[z]
                    # Favor an alternative course seam when the footprint can be
                    # covered with almost as much area using a different part size.
                    seam_count = _aligned_joint_count(placement, lower, model)
                    # A part spanning two supporting pieces joins their components;
                    # this matters more than choosing the largest isolated brick.
                    supports = sum(_stud_connected(below, placement) for below in lower)
                    score = width * depth - 3 * seam_count + 8 * max(0, supports - 1)
                    # A piece with nothing directly below or above can only
                    # touch neighbors sideways, which never holds it in place.
                    if (
                        not supports
                        and not any(
                            _stud_connected(placement, above)
                            for above in fixed_by_bottom.get(z + part.height, ())
                        )
                        and not any(
                            (cx, cy, cz) in cells
                            for cz in (z - 1, z + part.height)
                            for cy in range(y0, y0 + depth)
                            for cx in range(x0, x0 + width)
                        )
                    ):
                        score -= 12
                    # Randomness only breaks exact ties; it must not trade a brick for a plate.
                    fitting.append((score, part.height, rng.random() if rng else 0.0, placement))
            if not fitting:
                raise ValueError(f"No catalog part fits voxel {seed}")
            selected = max(fitting, key=lambda item: (item[0], item[1], item[2]))[3]
            for cz in range(selected.z, selected.z + selected.part.height):
                for cy in range(selected.y, selected.y + selected.depth):
                    for cx in range(selected.x, selected.x + selected.width):
                        del remaining[(cx, cy, cz)]
                        placed_color[(cx, cy, cz)] = selected.color
            placements.append(selected)
            by_top[selected.z + selected.part.height].append(selected)
    return placements


def _repair(
    placements: list[Placement],
    cells: dict[Cell, int | None],
    locked: frozenset[Placement] = frozenset(),
) -> tuple[list[Placement], list[Placement]]:
    """Re-tile each loose piece together with its neighbors in the same course.

    Greedy packing can strand an overhang cell whose only possible anchor was
    already claimed by a neighbor. Merging the loose piece with adjacent pieces
    and re-splitting the union so every piece reaches something above or below
    usually reattaches it. A change is kept only when fewer pieces end up loose.
    """
    loose = disconnected_placements(placements)
    for ring in (1, 2, 1, 2):
        if not loose:
            break
        for piece in list(loose):
            if piece not in placements or piece in locked:
                continue
            group = {piece}
            for _ in range(ring):
                group |= {
                    q
                    for q in placements
                    if q not in locked
                    and q.z == piece.z
                    and q.part.height == piece.part.height
                    and any(_side_touch(q, member) for member in group)
                }
            if sum(q.width * q.depth for q in group) > 48:
                continue
            others = [q for q in placements if q not in group]
            tiling = _best_tiling(group, others, cells, loose)
            if tiling is None:
                continue
            candidate = others + tiling
            candidate_loose = disconnected_placements(candidate)
            if len(candidate_loose) < len(loose):
                placements, loose = candidate, candidate_loose
    return placements, loose


def _side_touch(a: Placement, b: Placement) -> bool:
    x_touch = (a.x + a.width == b.x or b.x + b.width == a.x) and max(a.y, b.y) < min(
        a.y + a.depth, b.y + b.depth
    )
    y_touch = (a.y + a.depth == b.y or b.y + b.depth == a.y) and max(a.x, b.x) < min(
        a.x + a.width, b.x + b.width
    )
    return x_touch or y_touch


def _best_tiling(
    group: set[Placement],
    others: list[Placement],
    cells: dict[Cell, int | None],
    loose: list[Placement],
    budget: int = 1500,
) -> list[Placement] | None:
    """Exact-cover the group's footprint, minimizing pieces with nothing above or below."""
    z, height = next(iter(group)).z, next(iter(group)).part.height
    column_color: dict[tuple[int, int], int | None] = {}
    old_color: dict[tuple[int, int], int] = {}
    for piece in group:
        for x in range(piece.x, piece.x + piece.width):
            for y in range(piece.y, piece.y + piece.depth):
                colors = {cells[(x, y, cz)] for cz in range(z, z + height)} - {None}
                column_color[(x, y)] = colors.pop() if colors else None
                old_color[(x, y)] = piece.color
    loose_set = set(loose)
    anchors = [
        q for q in others if q not in loose_set and (q.z + q.part.height == z or q.z == z + height)
    ]

    # Every rectangle that fits inside the footprint, indexed by the cells it covers.
    options: list[tuple[Placement, frozenset[tuple[int, int]], bool]] = []
    by_cell: dict[tuple[int, int], list[int]] = {cell: [] for cell in column_color}
    shapes = {
        (w, d, part)
        for part in RECTANGULAR_PARTS
        if part.height == height
        for w, d in orientations(part)
    }
    for x0, y0 in column_color:
        for width, depth, part in shapes:
            footprint = frozenset(
                (x, y) for x in range(x0, x0 + width) for y in range(y0, y0 + depth)
            )
            if not footprint <= column_color.keys():
                continue
            colors = {column_color[c] for c in footprint} - {None}
            if len(colors) > 1:
                continue
            placement = Placement(
                part, x0, y0, z, colors.pop() if colors else old_color[(x0, y0)], width, depth
            )
            index = len(options)
            options.append(
                (placement, footprint, any(_stud_connected(placement, q) for q in anchors))
            )
            for cell in footprint:
                by_cell[cell].append(index)

    best: tuple[tuple[int, int], list[Placement]] | None = None
    nodes = 0
    anchored_only = True

    def search(covered: set[tuple[int, int]], chosen: list[Placement], unanchored: int) -> None:
        nonlocal best, nodes
        nodes += 1
        if nodes > budget or (best is not None and (unanchored, len(chosen)) >= best[0]):
            return
        # Branch on the uncovered cell with the fewest fitting rectangles.
        target, target_options = None, None
        for cell, indices in by_cell.items():
            if cell in covered:
                continue
            fitting = [
                i
                for i in indices
                if not options[i][1] & covered and (options[i][2] or not anchored_only)
            ]
            if target_options is None or len(fitting) < len(target_options):
                target, target_options = cell, fitting
                if len(fitting) <= 1:
                    break
        if target is None:
            best = ((unanchored, len(chosen)), list(chosen))
            return
        for i in sorted(target_options, key=lambda i: (not options[i][2], -len(options[i][1]))):
            placement, footprint, attached = options[i]
            chosen.append(placement)
            search(covered | footprint, chosen, unanchored + (not attached))
            chosen.pop()

    # First look for a cover in which every piece is attached; a cell with no
    # attached option prunes that branch at once. Otherwise allow loose pieces.
    search(set(), [], 0)
    if best is None:
        anchored_only, nodes = False, 0
        search(set(), [], 0)
    return best[1] if best else None


def _overlaps(a: Placement, b: Placement) -> bool:
    return max(a.x, b.x) < min(a.x + a.width, b.x + b.width) and max(a.y, b.y) < min(
        a.y + a.depth, b.y + b.depth
    )


def _stud_connected(a: Placement, b: Placement) -> bool:
    if b.z + b.part.height == a.z:
        a, b = b, a
    if a.z + a.part.height != b.z or not _overlaps(a, b):
        return False
    if a.part.top_studs is None and b.part.bottom_sockets is None:
        return True
    return bool(a.contacts(top=True) & b.contacts(top=False))


def _aligned_joint_count(
    candidate: Placement, lower_course: list[Placement], model: VoxelModel
) -> int:
    """Count internal vertical joints repeated from the immediately lower course."""
    if candidate.z == 0:
        return 0
    joints = 0
    for lower in lower_course:
        overlaps_x = max(lower.x, candidate.x) < min(
            lower.x + lower.width, candidate.x + candidate.width
        )
        overlaps_y = max(lower.y, candidate.y) < min(
            lower.y + lower.depth, candidate.y + candidate.depth
        )
        if overlaps_y:
            if (
                0 < lower.x + lower.width < model.width
                and candidate.x + candidate.width == lower.x + lower.width
            ):
                joints += 1
            if 0 < lower.x < model.width and candidate.x == lower.x:
                joints += 1
        if overlaps_x:
            if (
                0 < lower.y + lower.depth < model.depth
                and candidate.y + candidate.depth == lower.y + lower.depth
            ):
                joints += 1
            if 0 < lower.y < model.depth and candidate.y == lower.y:
                joints += 1
    return joints


def disconnected_placements(placements: list[Placement]) -> list[Placement]:
    """Return pieces outside the largest grounded, stud-connected assembly.

    Pieces connect only where one sits directly on another with overlapping
    studs and bottom sockets; side-by-side contact and the ground plane join nothing.
    """
    if not placements:
        return []
    parent = list(range(len(placements)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_bottom: dict[int, list[int]] = defaultdict(list)
    for i, p in enumerate(placements):
        by_bottom[p.z].append(i)
    for i, lower in enumerate(placements):
        for j in by_bottom.get(lower.z + lower.part.height, ()):
            if _stud_connected(lower, placements[j]):
                parent[find(i)] = find(j)
    volume: Counter[int] = Counter()
    grounded: set[int] = set()
    for i, p in enumerate(placements):
        root = find(i)
        volume[root] += p.width * p.depth * p.part.height
        if p.z == 0:
            grounded.add(root)
    if not grounded:
        return list(placements)
    main = max(grounded, key=lambda root: volume[root])
    return [p for i, p in enumerate(placements) if find(i) != main]
