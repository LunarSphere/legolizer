"""Greedy exact-cell packer with randomized restarts and a connectivity check."""

from __future__ import annotations

import random
import time
from collections import Counter, defaultdict
from dataclasses import replace

from legolizer.catalog import RECTANGULAR_PARTS, orientations
from legolizer.model import Placement, VoxelModel
from legolizer.shape import Region, in_zone

Cell = tuple[int, int, int]

BRICK_BONUS = 64
SEAM_PENALTY = 3
SEAM_PHASES = ((1, 0), (0, 1), (1, 1))
ISOLATED_PENALTY = 1000


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
    model: VoxelModel,
    attempts: int = 24,
    recolor_hidden: bool = True,
    time_budget: float = 6.0,
    fixed: list[Placement] = (),
) -> tuple[list[Placement], list[Placement]]:
    """Return (placements, loose placements) for the best of several packings.

    Attempt 0 is deterministic and alternates the scan corner by course. Later
    attempts randomize the scan direction per course. The best packing has the
    fewest unattached pieces, then the smallest symmetry penalty, then the fewest
    joints aligned with the course below; once one is fully attached, the
    SEAM_PHASES variants of attempt 0 try to stagger seams further within a
    quarter of the time budget. Fixed
    placements are kept as they are and only the remaining cells are packed
    around them.
    """
    cells: dict[Cell, int | None] = {(v.x, v.y, v.z): v.color for v in model.voxels}
    if not cells:
        placements = list(model.pieces)
        return placements, disconnected_placements(placements)
    fallback = Counter(cells.values()).most_common(1)[0][0]
    if recolor_hidden:
        # A cell enclosed on every side is invisible, so any brick color may
        # cover it. Bricks can then span color boundaries inside the model.
        for cell in hidden_cells(cells):
            cells[cell] = None
    fixed = list(fixed)
    claimed = [cell for piece in fixed for cell in placement_cells(piece)]
    if len(claimed) != len(set(claimed)) or not all(cell in cells for cell in claimed):
        raise ValueError("Fixed pieces must cover distinct occupied cells")
    symmetric = not model.pieces and not fixed and _x_symmetric(cells, model.width)
    best: tuple[tuple[int, int, int, int], list[Placement], list[Placement]] | None = None
    started = time.monotonic()
    seam_deadline = started + time_budget / 4
    clean = False
    phases = iter(SEAM_PHASES)
    for attempt in range(max(1, attempts)):
        if attempt and time.monotonic() - started > time_budget:
            break
        if clean:
            # A clean packing exists, so only look for fewer aligned seams.
            phase = next(phases, None)
            if phase is None or time.monotonic() > seam_deadline:
                break
            placements, loose = _repair(
                _greedy(cells, model, None, fallback, fixed, phase=phase),
                cells,
                frozenset(model.pieces) | set(fixed),
                model,
                seam_deadline,
            )
            if loose:
                continue
        else:
            rng = random.Random(attempt) if attempt else None
            # Shared flips align seams in every course, so later attempts restore per-layer staggering.
            placements = _greedy(
                cells, model, rng, fallback, fixed, symmetric=symmetric and attempt < 2
            )
            placements, loose = _repair(
                placements,
                cells,
                frozenset(model.pieces) | set(fixed),
                model if attempt == 0 else None,
                started + time_budget if attempt else None,
            )
        score = (
            len(loose),
            _symmetry_penalty(placements, model.width) if symmetric else 0,
            aligned_seams(placements),
            len(placements),
        )
        if best is None or score < best[0]:
            best = (score, placements, loose)
        if not loose and (not symmetric or score[1] == 0 or attempt >= 1):
            # Mirrored layouts outrank seams, and only shared flips keep them.
            if symmetric or score[2] == 0:
                break
            clean = True
    return best[1], best[2]


def hidden_cells(cells) -> list[Cell]:
    return [
        cell
        for cell in cells
        if all(
            (cell[0] + dx, cell[1] + dy, cell[2] + dz) in cells or cell[2] + dz < 0
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
        )
    ]


def placement_cells(piece: Placement):
    for z in range(piece.z, piece.z + piece.part.height):
        for y in range(piece.y, piece.y + piece.depth):
            for x in range(piece.x, piece.x + piece.width):
                yield x, y, z


def repack_region(
    model: VoxelModel, previous: list[Placement], zone: list[Region] | None
) -> tuple[list[Placement], list[Placement], list[Placement]]:
    """Pack an edited model, keeping as many earlier pieces as possible.

    Returns (placements, loose, rebuilt): rebuilt lists earlier pieces that
    were removed or re-tiled. Pieces entirely outside the zone are always
    kept, so only pieces touching the zone can be rebuilt. Unchanged pieces
    inside the zone are kept too unless that leaves unattached pieces. With no
    zone, the last resort is a full repack.
    """
    cells = {(v.x, v.y, v.z): v.color for v in model.voxels}
    hidden = set(hidden_cells(cells))
    # Specialty pieces come back through model.pieces, not as fixed bricks.
    bricks = [p for p in previous if p.part in RECTANGULAR_PARTS]
    outside = [p for p in bricks if not any(in_zone(c, zone) for c in placement_cells(p))]
    # An unchanged piece still covers present cells, in the right color wherever visible.
    unchanged = [
        p
        for p in bricks
        if p not in outside
        and all(c in cells and (c in hidden or cells[c] == p.color) for c in placement_cells(p))
    ]
    best = None
    for fixed in [outside + unchanged] + ([outside] if unchanged else []):
        placements, loose = pack(model, fixed=fixed)
        kept = set(placements)
        rebuilt = [p for p in previous if p not in kept]
        if best is None or (len(loose), len(rebuilt)) < (len(best[1]), len(best[2])):
            best = (placements, loose, rebuilt)
        if not loose:
            break
    return best


def _greedy(
    cells: dict[Cell, int | None],
    model: VoxelModel,
    rng: random.Random | None,
    fallback: int,
    fixed: list[Placement] = (),
    symmetric: bool = False,
    plates_only: bool = False,
    stagger_plates: bool = False,
    phase: tuple[int, int] = (0, 0),
    context: dict[Cell, int | None] | None = None,
) -> list[Placement]:
    remaining = dict(cells)
    placements: list[Placement] = [*model.pieces, *fixed]
    fixed_by_bottom: dict[int, list[Placement]] = defaultdict(list)
    owner: dict[Cell, Placement] = {}
    for piece in placements:
        fixed_by_bottom[piece.z].append(piece)
        for cell in placement_cells(piece):
            owner[cell] = piece
    for piece in fixed:
        for cell in placement_cells(piece):
            del remaining[cell]
    occupied = set(cells) | set(owner)
    candidates = sorted(
        (part for part in RECTANGULAR_PARTS if not plates_only or part.height == 1),
        key=lambda p: (p.width * p.depth * p.height, p.height, p.width, p.depth),
        reverse=True,
    )
    top_z = model.height * 3

    layers: dict[int, list[Cell]] = defaultdict(list)
    for cell in remaining:
        layers[cell[2]].append(cell)
    if symmetric:
        flip_x = bool(rng and rng.random() < 0.5)
        flip_y = bool(rng and rng.random() < 0.5)
    for z in sorted(layers):
        if rng is None:
            # Consecutive courses start at opposite corners so their seams offset.
            flip_x, flip_y = bool((z + phase[0]) % 2), bool((z + phase[1]) % 2)
        elif not symmetric:
            flip_x = bool(rng.random() < 0.5)
            flip_y = bool(rng.random() < 0.5)
        order = sorted(
            layers[z], key=lambda c: (-c[1] if flip_y else c[1], -c[0] if flip_x else c[0])
        )
        if stagger_plates:
            origin_x = min(c[0] for c in layers[z]) + z % 2
            origin_y = min(c[1] for c in layers[z]) + z % 2
            order.sort(
                key=lambda c: ((c[1] - origin_y) % model.depth, (c[0] - origin_x) % model.width)
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
                    # Only a plate at this level can bridge a neighboring one-plate slab.
                    if part.height > 1 and _borders_slab(
                        remaining, occupied, x0, y0, z, width, depth
                    ):
                        continue
                    placement = Placement(
                        part, x0, y0, z, colors.pop() if colors else None, width, depth
                    )
                    lower = {
                        owner.get((cx, cy, z - 1))
                        for cy in range(y0, y0 + depth)
                        for cx in range(x0, x0 + width)
                    } - {None}
                    supports = sum(_stud_connected(below, placement) for below in lower)
                    # Bricks outrank any plate so solid masses become brick courses;
                    # a capped support bonus still lets wide plates span overhangs.
                    score = (
                        width * depth * part.height
                        + (BRICK_BONUS if part.height > 1 else 0)
                        + 8 * min(max(0, supports - 1), 2)
                        - SEAM_PENALTY
                        * part.height
                        * _aligned_joints(owner, cells, x0, y0, z, width, depth)
                    )
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
                        score -= ISOLATED_PENALTY
                    # Randomness only breaks exact ties; it must not trade a brick for a plate.
                    fitting.append((score, part.height, rng.random() if rng else 0.0, placement))
            if not fitting:
                raise ValueError(f"No catalog part fits voxel {seed}")
            selected = max(fitting, key=lambda item: (item[0], item[1], item[2]))[3]
            if selected.color is None:
                selected = replace(
                    selected, color=_surrounding_color(context or cells, selected, fallback)
                )
            for cell in placement_cells(selected):
                del remaining[cell]
                owner[cell] = selected
            placements.append(selected)
    return placements


def _surrounding_color(cells: dict[Cell, int | None], piece: Placement, fallback: int) -> int:
    """Most common visible color near a fully hidden piece, else the model's dominant color."""
    counts: Counter[int] = Counter()
    reach = 3
    for z in range(piece.z, piece.z + piece.part.height):
        for y in range(piece.y - reach, piece.y + piece.depth + reach):
            for x in range(piece.x - reach, piece.x + piece.width + reach):
                color = cells.get((x, y, z))
                if color is not None:
                    counts[color] += 1
    return counts.most_common(1)[0][0] if counts else fallback


def _borders_slab(
    remaining: dict[Cell, int | None],
    occupied: set[Cell],
    x0: int,
    y0: int,
    z: int,
    width: int,
    depth: int,
) -> bool:
    """Whether an uncovered neighbor at this level has no cell directly above or below."""
    neighbors = [(x, y) for y in range(y0, y0 + depth) for x in (x0 - 1, x0 + width)] + [
        (x, y) for x in range(x0, x0 + width) for y in (y0 - 1, y0 + depth)
    ]
    return any(
        (x, y, z) in remaining and (x, y, z - 1) not in occupied and (x, y, z + 1) not in occupied
        for x, y in neighbors
    )


def _aligned_joints(
    owner: dict[Cell, Placement],
    cells: dict[Cell, int | None],
    x0: int,
    y0: int,
    z: int,
    width: int,
    depth: int,
) -> int:
    """Count stud-wide edges of a footprint that sit on a vertical joint of the course below."""
    if z == 0:
        return 0
    below = z - 1
    edges = [
        ((x, y), (nx, y))
        for y in range(y0, y0 + depth)
        for x, nx in ((x0, x0 - 1), (x0 + width - 1, x0 + width))
    ] + [
        ((x, y), (x, ny))
        for x in range(x0, x0 + width)
        for y, ny in ((y0, y0 - 1), (y0 + depth - 1, y0 + depth))
    ]
    joints = 0
    for (x, y), (nx, ny) in edges:
        if (nx, ny, z) not in cells and (nx, ny, z) not in owner:
            continue
        inner, outer = owner.get((x, y, below)), owner.get((nx, ny, below))
        if inner is not None and outer is not None and inner is not outer:
            joints += 1
    return joints


def aligned_seams(placements: list[Placement]) -> int:
    """Count stud-wide vertical joints that repeat a joint directly below them."""
    owner = {cell: piece for piece in placements for cell in placement_cells(piece)}
    joints = 0
    for piece in placements:
        if piece.z == 0:
            continue
        joints += _aligned_joints(owner, owner, piece.x, piece.y, piece.z, piece.width, piece.depth)
    return joints


def _x_symmetric(cells: dict[Cell, int | None], width: int) -> bool:
    return all(
        cells.get((width - 1 - x, y, z), object()) == color for (x, y, z), color in cells.items()
    )


def _symmetry_penalty(placements: list[Placement], width: int) -> int:
    counts = Counter(
        (p.x, p.y, p.z, p.part.code, p.width, p.depth, p.part.height, p.color) for p in placements
    )
    reflected = Counter(
        (width - p.x - p.width, p.y, p.z, p.part.code, p.width, p.depth, p.part.height, p.color)
        for p in placements
    )
    return sum((counts - reflected).values())


def _repair(
    placements: list[Placement],
    cells: dict[Cell, int | None],
    locked: frozenset[Placement] = frozenset(),
    model: VoxelModel | None = None,
    deadline: float | None = None,
) -> tuple[list[Placement], list[Placement]]:
    """Re-tile each loose piece together with its neighbors in the same course.

    Greedy packing can strand an overhang cell whose only possible anchor was
    already claimed by a neighbor. Merging the loose piece with adjacent pieces
    and re-splitting the union so every piece reaches something above or below
    usually reattaches it. A change is kept only when fewer pieces end up loose.
    Fixed pieces are never re-tiled.
    """
    loose = disconnected_placements(placements)
    if loose and model is not None:
        placements, loose = _repair_plate_courses(placements, loose, cells, model, locked)
    for ring in (1, 2, 1, 2):
        if not loose:
            break
        for piece in list(loose):
            if deadline is not None and time.monotonic() > deadline:
                return placements, loose
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


def _repair_plate_courses(placements, loose, cells, model, locked):
    """Retile a bounded region around each cluster of loose pieces using plates."""
    for cluster in _clusters([p for p in loose if p not in locked]):
        movable = [p for p in cluster if p in loose]
        if movable:
            placements, loose = _retile_with_plates(
                placements, loose, movable, cells, model, locked
            )
    return placements, loose


def _clusters(pieces: list[Placement], gap: int = 2) -> list[list[Placement]]:
    parent = list(range(len(pieces)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(pieces):
        for j in range(i):
            b = pieces[j]
            if (
                a.x - gap < b.x + b.width
                and b.x - gap < a.x + a.width
                and a.y - gap < b.y + b.depth
                and b.y - gap < a.y + a.depth
                and a.z - gap < b.z + b.part.height
                and b.z - gap < a.z + a.part.height
            ):
                parent[find(i)] = find(j)
    groups: dict[int, list[Placement]] = defaultdict(list)
    for i, piece in enumerate(pieces):
        groups[find(i)].append(piece)
    return list(groups.values())


def _retile_with_plates(placements, loose, movable, cells, model, locked):
    xmin = min(p.x for p in movable) - 1
    xmax = max(p.x + p.width for p in movable) + 1
    ymin = min(p.y for p in movable) - 1
    ymax = max(p.y + p.depth for p in movable) + 1
    zmin = min(p.z for p in movable) - 1
    zmax = max(p.z + p.part.height for p in movable) + 1
    group = {
        p
        for p in placements
        if p not in locked
        and p.x < xmax
        and p.x + p.width > xmin
        and p.y < ymax
        and p.y + p.depth > ymin
        and p.z < zmax
        and p.z + p.part.height > zmin
    }
    if sum(p.width * p.depth * p.part.height for p in group) > 6000:
        return placements, loose
    local = {cell: cells[cell] for p in group for cell in p.envelope()}
    others = tuple(p for p in placements if p not in group)
    candidate = _greedy(
        local,
        replace(model, pieces=others),
        None,
        Counter(c for c in cells.values() if c is not None).most_common(1)[0][0],
        plates_only=True,
        stagger_plates=any(p.part.height == 1 and p.width * p.depth > 48 for p in movable),
        context=cells,
    )
    candidate_loose = disconnected_placements(candidate)
    old_volume = sum(p.width * p.depth * p.part.height for p in loose)
    new_volume = sum(p.width * p.depth * p.part.height for p in candidate_loose)
    if new_volume < old_volume:
        return candidate, candidate_loose
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
