"""BMB-009: definition-instance DAG with nested affine transform operations.

Matrices follow docs/MODULE-IR-V1.md: flat row-major 4x4, translation at
indices 3/7/11, last row [0,0,0,1], metres, right-handed +Z up. A world
transform is parent_world x local. Pure Python, no geometry or BOMC logic.
Every mutator validates first and commits last, so a rejected edit leaves the
graph untouched.
"""
from __future__ import annotations

import math
import re

ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")
IDENTITY = (1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0)
MAX_DEFINITIONS = 256
MAX_INSTANCES_PER_DEFINITION = 256
MAX_DEPTH = 32
MAX_EXPANDED_INSTANCES = 10_000
MAX_ABS_VALUE = 1e6
MIN_ABS_DET = 1e-9


class GraphError(ValueError):
    """Rejected graph input or edit; the graph is never partially mutated."""


class CycleError(GraphError):
    """Definition reference would create a cycle; `path` lists the loop."""

    def __init__(self, path: list[str]):
        super().__init__("definition cycle: " + " -> ".join(path))
        self.path = path


def _need(test: bool, reason: str) -> None:
    if not test:
        raise GraphError(reason)


def _id(value: object, label: str) -> str:
    _need(isinstance(value, str) and ID_PATTERN.match(value) is not None,
          f"{label}: invalid id {value!r}")
    return value


# --- matrix operations -----------------------------------------------------

def determinant(m: tuple[float, ...]) -> float:
    a, b, c, d, e, f, g, h, i = (m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10])
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def validate_transform(value: object, label: str = "transform") -> tuple[float, ...]:
    """Return a checked 16-tuple: finite, bounded, affine, invertible."""
    _need(isinstance(value, (list, tuple)) and len(value) == 16,
          f"{label}: requires 16 row-major scalars")
    _need(all(type(v) in (int, float) for v in value), f"{label}: non-numeric entry")
    try:
        m = tuple(float(v) for v in value)
    except OverflowError as exc:
        raise GraphError(f"{label}: number exceeds budget") from exc
    _need(all(math.isfinite(v) and abs(v) <= MAX_ABS_VALUE for v in m),
          f"{label}: non-finite or out-of-range entry")
    _need(m[12:] == (0.0, 0.0, 0.0, 1.0), f"{label}: last row must be [0,0,0,1]")
    _need(abs(determinant(m)) > MIN_ABS_DET, f"{label}: degenerate (non-invertible)")
    return tuple(v + 0.0 for v in m)  # normalise -0.0


def compose(parent: tuple[float, ...], child: tuple[float, ...]) -> tuple[float, ...]:
    """parent x child (child applied first)."""
    out = []
    for r in range(4):
        for c in range(4):
            out.append(sum(parent[r * 4 + k] * child[k * 4 + c] for k in range(4)) + 0.0)
    return tuple(out)


def invert(m: tuple[float, ...]) -> tuple[float, ...]:
    """Inverse of an affine matrix."""
    det = determinant(m)
    _need(abs(det) > MIN_ABS_DET, "degenerate transform cannot be inverted")
    a, b, c, d, e, f, g, h, i = (m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10])
    inv = ((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
           (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
           (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det)
    t = (m[3], m[7], m[11])
    out = []
    for r in range(3):
        row = inv[r * 3:r * 3 + 3]
        out.extend(row)
        out.append(-sum(row[k] * t[k] for k in range(3)) + 0.0)
    return tuple(out) + (0.0, 0.0, 0.0, 1.0)


def apply_point(m: tuple[float, ...], p: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(m[r * 4] * p[0] + m[r * 4 + 1] * p[1] + m[r * 4 + 2] * p[2] + m[r * 4 + 3]
                 for r in range(3))


def translation(x: float, y: float, z: float) -> tuple[float, ...]:
    return (1.0, 0.0, 0.0, float(x), 0.0, 1.0, 0.0, float(y), 0.0, 0.0, 1.0, float(z), 0.0, 0.0, 0.0, 1.0)


def scale(x: float, y: float, z: float) -> tuple[float, ...]:
    return (float(x), 0.0, 0.0, 0.0, 0.0, float(y), 0.0, 0.0, 0.0, 0.0, float(z), 0.0, 0.0, 0.0, 0.0, 1.0)


def mirror(axis: str) -> tuple[float, ...]:
    _need(axis in ("x", "y", "z"), "mirror axis must be x, y or z")
    return scale(*(-1.0 if a == axis else 1.0 for a in "xyz"))


def rotation_z(degrees: float) -> tuple[float, ...]:
    r = math.radians(degrees)
    c, s = math.cos(r), math.sin(r)
    return (c, -s, 0.0, 0.0, s, c, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def shear_xy(k: float) -> tuple[float, ...]:
    """x' = x + k*y (affine shear in the XY plane)."""
    return (1.0, float(k), 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def is_mirrored(m: tuple[float, ...]) -> bool:
    """True when the transform flips handedness (negative determinant)."""
    return determinant(m) < 0.0


# --- graph -----------------------------------------------------------------

class DefinitionGraph:
    """Definitions hold instances; each instance places another definition.

    The reference relation must stay acyclic. A definition may be instanced
    many times (shared), so expanded world placements are enumerated by path.
    """

    def __init__(self) -> None:
        # defId -> {instanceId: (targetDefId, transform)}
        self._defs: dict[str, dict[str, tuple[str, tuple[float, ...]]]] = {}

    # queries
    def definitions(self) -> list[str]:
        return sorted(self._defs)

    def instances(self, definition: str) -> list[tuple[str, str, tuple[float, ...]]]:
        _need(definition in self._defs, f"unknown definition {definition!r}")
        return [(i, t, m) for i, (t, m) in sorted(self._defs[definition].items())]

    # edits
    def add_definition(self, definition: str) -> None:
        _id(definition, "definition")
        _need(definition not in self._defs, f"duplicate definition {definition!r}")
        _need(len(self._defs) < MAX_DEFINITIONS, "definition budget exceeded")
        self._defs[definition] = {}

    def add_instance(self, owner: str, instance: str, target: str,
                     transform: tuple[float, ...] = IDENTITY) -> None:
        _id(instance, "instance")
        _need(owner in self._defs, f"unknown definition {owner!r}")
        _need(target in self._defs, f"unknown definition {target!r}")
        _need(instance not in self._defs[owner], f"duplicate instance {owner}/{instance}")
        _need(len(self._defs[owner]) < MAX_INSTANCES_PER_DEFINITION, "instance budget exceeded")
        m = validate_transform(transform, f"{owner}/{instance}")
        loop = self._path_between(target, owner)
        if loop is not None:
            raise CycleError([owner] + loop)
        self._defs[owner][instance] = (target, m)

    def set_transform(self, owner: str, instance: str, transform: tuple[float, ...]) -> None:
        _need(owner in self._defs and instance in self._defs[owner],
              f"unknown instance {owner}/{instance}")
        m = validate_transform(transform, f"{owner}/{instance}")
        self._defs[owner][instance] = (self._defs[owner][instance][0], m)

    def remove_instance(self, owner: str, instance: str) -> None:
        _need(owner in self._defs and instance in self._defs[owner],
              f"unknown instance {owner}/{instance}")
        del self._defs[owner][instance]

    # analysis
    def _path_between(self, start: str, goal: str) -> list[str] | None:
        """Definition path start..goal following references, or None."""
        stack = [(start, [start])]
        seen: set[str] = set()
        while stack:
            node, path = stack.pop()
            if node == goal:
                return path
            if node in seen:
                continue
            seen.add(node)
            for key in sorted(self._defs[node], reverse=True):
                stack.append((self._defs[node][key][0], path + [self._defs[node][key][0]]))
        return None

    def find_cycle(self) -> list[str] | None:
        """Return one definition cycle (first == last) or None."""
        state: dict[str, int] = {}

        def visit(node: str, path: list[str]) -> list[str] | None:
            state[node] = 1
            for key in sorted(self._defs[node]):
                target = self._defs[node][key][0]
                if state.get(target) == 1:
                    return path[path.index(target):] + [target]
                if target not in state:
                    found = visit(target, path + [target])
                    if found:
                        return found
            state[node] = 2
            return None

        for d in sorted(self._defs):
            if d not in state:
                found = visit(d, [d])
                if found:
                    return found
        return None

    def topological_order(self) -> list[str]:
        """Definitions with every referenced definition listed before its user."""
        cycle = self.find_cycle()
        if cycle:
            raise CycleError(cycle)
        order: list[str] = []
        done: set[str] = set()

        def visit(node: str) -> None:
            if node in done:
                return
            done.add(node)
            for key in sorted(self._defs[node]):
                visit(self._defs[node][key][0])
            order.append(node)

        for d in sorted(self._defs):
            visit(d)
        return order

    def world_transforms(self, root: str,
                         root_transform: tuple[float, ...] = IDENTITY) -> dict[str, tuple[float, ...]]:
        """World matrix of every expanded instance under `root`, keyed by path.

        Paths are slash-joined instance ids (`wing/room`). Output order and
        values do not depend on insertion order.
        """
        _need(root in self._defs, f"unknown definition {root!r}")
        cycle = self.find_cycle()
        if cycle:
            raise CycleError(cycle)
        base = validate_transform(root_transform, "root transform")
        out: dict[str, tuple[float, ...]] = {}

        def walk(definition: str, world: tuple[float, ...], prefix: str, depth: int) -> None:
            _need(depth <= MAX_DEPTH, "nesting depth budget exceeded")
            for key in sorted(self._defs[definition]):
                target, local = self._defs[definition][key]
                path = prefix + key
                _need(len(out) < MAX_EXPANDED_INSTANCES, "expanded instance budget exceeded")
                m = compose(world, local)
                _need(all(math.isfinite(v) and abs(v) <= MAX_ABS_VALUE for v in m),
                      f"{path}: world transform out of range")
                out[path] = m
                walk(target, m, path + "/", depth + 1)

        walk(root, base, "", 1)
        return dict(sorted(out.items()))
