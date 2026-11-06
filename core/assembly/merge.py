"""BMB-011: assembly merge and shared-wall seam ownership.

`assemble(modules)` merges Module IR modules (docs/MODULE-IR-V1.md) into one
consistent graph or raises before returning anything. A shared wall is a pair of
reciprocal ports that name one seam; exactly one of the two participants must
own that seam. The merge checks identity, parent and dependency links, seam
ownership and port agreement in world space (opposing normals, coincident
frames, equal span). Geometry, collision and bounds diagnostics are BMB-012.
Pure Python; the result does not depend on input order.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from core.graph import dag
from core.textsafe import show

SCHEMA_VERSION = "1.0.0"
MODULE_ID = re.compile(r"[a-z][a-z0-9-]*(/[a-z][a-z0-9-]*)+\Z")
SMALL_ID = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")
MAX_MODULES = 1024
MAX_ITEMS = 256               # ports, seams, dependencies per module (schema maxItems)
MAX_OPERATIONS = 10_000       # operations per module (schema maxItems)
MAX_PARENT_DEPTH = dag.MAX_DEPTH
MAX_JSON_DEPTH = 64           # nesting accepted inside any module value (the real schema needs about 6)
NORMAL_TOL = 1e-6
POSITION_TOL = 1e-3           # metres
SPAN_TOL = 1e-3               # metres


class AssemblyError(ValueError):
    """Rejected module set; no assembly is produced."""


class DuplicateOwnershipError(AssemblyError):
    """More than one module claims ownership of the same shared wall."""


def _need(test: bool, reason: str) -> None:
    if not test:
        raise AssemblyError(reason)


def _sid(value: object, label: str) -> str:
    _need(isinstance(value, str) and SMALL_ID.match(value) is not None, f"{label}: invalid id {show(value)}")
    return value


def _mid(value: object, label: str) -> str:
    _need(isinstance(value, str) and len(value) <= 180 and MODULE_ID.match(value) is not None,
          f"{label}: invalid module id {show(value)}")
    return value


def _list(module: dict, key: str, mid: str, limit: int = MAX_ITEMS) -> list:
    value = module.get(key)
    _need(isinstance(value, list) and len(value) <= limit, f"{mid}: {key} must be a list of at most {limit}")
    return value


@dataclass(frozen=True)
class Seam:
    seam_id: str
    owner: str
    participants: tuple[str, str]
    surface_op_id: str
    ports: tuple[tuple[str, str], tuple[str, str]]  # the reciprocal port pair, sorted


@dataclass(frozen=True)
class Assembly:
    modules: dict[str, dict]                         # deep copies, sorted by id
    order: tuple[str, ...]                           # dependencies before dependents
    world_transforms: dict[str, tuple[float, ...]]   # module frame -> assembly frame
    seams: tuple[Seam, ...]                          # sorted by (participants, seam id)

    def neighbours(self, module_id: str) -> list[str]:
        """Modules sharing a seam with `module_id`, sorted."""
        _need(module_id in self.modules, f"unknown module {show(module_id)}")
        return sorted({p for s in self.seams if module_id in s.participants
                       for p in s.participants if p != module_id})

    def seams_of(self, module_id: str) -> list[Seam]:
        return [s for s in self.seams if module_id in s.participants]

    def owned_by(self, module_id: str) -> list[Seam]:
        return [s for s in self.seams if s.owner == module_id]


def _check_depth(value: object, label: str) -> None:
    """Iterative nesting check: acceptance must not depend on the interpreter's recursion limit."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        _need(depth <= MAX_JSON_DEPTH, f"{label}: JSON nesting exceeds depth {MAX_JSON_DEPTH}")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend((child, depth + 1) for child in item)


def _copy_modules(modules: object) -> dict[str, dict]:
    _need(isinstance(modules, (list, tuple)) and 0 < len(modules) <= MAX_MODULES,
          f"modules must be a list of 1..{MAX_MODULES}")
    out: dict[str, dict] = {}
    for n, raw in enumerate(modules):
        _need(isinstance(raw, dict), f"module {n}: must be an object")
        _check_depth(raw, f"module {n}")
        try:
            module = json.loads(json.dumps(raw, allow_nan=False))  # detach and require plain JSON
        except (TypeError, ValueError, RecursionError) as exc:
            raise AssemblyError(f"module {n}: not plain JSON") from exc
        mid = _mid(module.get("moduleId"), f"module {n}")
        _need(mid not in out, f"duplicate module {show(mid)}")
        _need(module.get("schemaVersion") == SCHEMA_VERSION, f"{mid}: unsupported schemaVersion")
        _need(type(module.get("revision")) is int and module["revision"] >= 0, f"{mid}: bad revision")
        parent = module.get("parentId")
        _need(parent is None or parent != mid, f"{mid}: parent cannot be itself")
        if parent is not None:
            _mid(parent, f"{mid}.parentId")
        out[mid] = module
    return dict(sorted(out.items()))


def _check_links(mods: dict[str, dict]) -> tuple[dict[str, tuple[float, ...]], tuple[str, ...]]:
    """Parent chains, world transforms and dependency order."""
    world: dict[str, tuple[float, ...]] = {}

    def resolve(mid: str, trail: tuple[str, ...]) -> tuple[float, ...]:
        if mid in world:
            return world[mid]
        _need(mid not in trail, "parent cycle: " + " -> ".join(trail + (mid,)))
        _need(len(trail) < MAX_PARENT_DEPTH, f"{mid}: parent chain deeper than {MAX_PARENT_DEPTH}")
        frame = mods[mid].get("localFrame")
        _need(isinstance(frame, dict), f"{mid}: missing localFrame")
        try:
            local = dag.validate_transform(frame.get("transform"), f"{mid}.localFrame.transform")
        except dag.GraphError as exc:
            raise AssemblyError(str(exc)) from exc
        parent = mods[mid].get("parentId")
        base = resolve(parent, trail + (mid,)) if parent in mods else dag.IDENTITY  # a non-module parent is a group
        try:  # a chain of individually valid transforms can still compose to a singular or huge one
            world[mid] = dag.validate_transform(dag.compose(base, local), f"{mid}: composed world transform")
        except dag.GraphError as exc:
            raise AssemblyError(str(exc)) from exc
        return world[mid]

    for mid in mods:
        resolve(mid, ())

    deps: dict[str, list[str]] = {}
    for mid, module in mods.items():
        seen: set[str] = set()
        for d in _list(module, "dependencies", mid):
            _need(isinstance(d, dict), f"{mid}: dependency must be an object")
            dep = _mid(d.get("moduleId"), f"{mid}.dependency")
            need = d.get("minRevision")
            _need(type(need) is int and need >= 0, f"{mid}: dependency {dep} has a bad minRevision")
            _need(dep != mid, f"{mid}: depends on itself")
            _need(dep in mods, f"{mid}: dependency {show(dep)} is not in the assembly")
            _need(dep not in seen, f"{mid}: duplicate dependency {show(dep)}")
            _need(mods[dep]["revision"] >= need,
                  f"{mid}: dependency {dep} at revision {mods[dep]['revision']}, need >= {need}")
            seen.add(dep)
        deps[mid] = sorted(seen)

    # Iterative post-order DFS: a dependency chain as deep as the module cap must not hit the recursion limit.
    order: list[str] = []
    state: dict[str, int] = {}
    for start in mods:
        if state.get(start) == 2:
            continue
        state[start] = 1
        trail = [start]
        stack = [iter(deps[start])]
        while stack:
            dep = next(stack[-1], None)
            if dep is None:
                node = trail.pop()
                stack.pop()
                state[node] = 2
                order.append(node)
                continue
            if state.get(dep) == 2:
                continue
            _need(state.get(dep) != 1, "dependency cycle: " + " -> ".join(trail + [dep]))
            state[dep] = 1
            trail.append(dep)
            stack.append(iter(deps[dep]))
    return world, tuple(order)


def _number(v: object) -> bool:
    """A real, finite, bounded number; compares before any float() so huge ints cannot overflow."""
    return type(v) in (int, float) and abs(v) <= dag.MAX_ABS_VALUE


def _normalise(v: list[float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(c * c for c in v))
    _need(length > 1e-9, "port normal has zero length")
    return (v[0] / length, v[1] / length, v[2] / length)


def _world_port(mid: str, port: dict, world: tuple[float, ...]) -> dict:
    pid = _sid(port.get("portId"), f"{mid}.port")
    label = f"{mid}.{pid}"
    raw = port.get("normal")
    _need(isinstance(raw, list) and len(raw) == 3 and all(_number(c) for c in raw),
          f"{label}: normal must be 3 finite numbers")
    try:
        frame = dag.validate_transform(port.get("localTransform"), f"{label}.localTransform")
    except dag.GraphError as exc:
        raise AssemblyError(str(exc)) from exc
    for key in ("width", "height"):
        v = port.get(key)
        _need(_number(v) and v > 0, f"{label}: {key} must be positive")
    inv = dag.invert(world)  # normals transform by the inverse transpose, which also handles mirrors and shear
    n = _normalise([sum(inv[j * 4 + i] * raw[j] for j in range(3)) for i in range(3)])
    placed = dag.compose(world, frame)
    axes, spans = [], []
    for col, key in ((1, "width"), (2, "height")):  # frame +Y = width direction, +Z = height direction
        vector = [placed[col], placed[4 + col], placed[8 + col]]  # frame axis as placed in the assembly (scale and shear kept)
        axes.append(_normalise(vector))
        _need(abs(sum(a * b for a, b in zip(axes[-1], n))) <= NORMAL_TOL,
              f"{label}: frame {'YZ'[col - 1]} axis is not tangent to the port normal in world space")
        spans.append(float(port[key]) * math.sqrt(sum(c * c for c in vector)))  # world-space opening extent
    peer = port.get("peer")
    if peer is not None:
        _need(isinstance(peer, dict) and set(peer) == {"moduleId", "portId"}, f"{label}: malformed peer")
        peer = (_mid(peer["moduleId"], f"{label}.peer"), _sid(peer["portId"], f"{label}.peer"))
    seam = port.get("seamId")
    if seam is not None:
        _sid(seam, f"{label}.seamId")
    _need((peer is None) == (seam is None), f"{label}: a port needs both peer and seamId, or neither")
    return {"id": (mid, pid), "normal": n, "pos": (placed[3], placed[7], placed[11]),
            "width_axis": axes[0], "height_axis": axes[1], "width": spans[0], "height": spans[1], "peer": peer, "seam": seam}


def _check_seams(mods: dict[str, dict], world: dict[str, tuple[float, ...]]) -> tuple[Seam, ...]:
    owned: dict[tuple[str, str], dict] = {}
    for mid, module in mods.items():
        ops = {o["opId"] for o in _list(module, "operations", mid, MAX_OPERATIONS)
               if isinstance(o, dict) and isinstance(o.get("opId"), str)}
        for seam in _list(module, "ownedSeams", mid):
            _need(isinstance(seam, dict), f"{mid}: seam must be an object")
            sid = _sid(seam.get("seamId"), f"{mid}.seam")
            _need((mid, sid) not in owned, f"{mid}: duplicate seam {show(sid)}")
            _need(seam.get("ownerModuleId") == mid, f"{mid}.{sid}: declared by {mid} but owned by {show(seam.get('ownerModuleId'))}")
            parts = seam.get("participants")
            _need(isinstance(parts, list) and len(parts) == 2 and all(isinstance(p, str) for p in parts)
                  and parts[0] != parts[1], f"{mid}.{sid}: participants must be two distinct modules")
            _need(mid in parts, f"{mid}.{sid}: owner is not a participant")
            for p in parts:
                _need(p in mods, f"{mid}.{sid}: participant {show(p)} is not in the assembly")
            _need(isinstance(seam.get("surfaceOpId"), str) and seam["surfaceOpId"] in ops, f"{mid}.{sid}: surfaceOpId {show(seam.get('surfaceOpId'))} is not an operation of {mid}")
            owned[(mid, sid)] = seam

    ports: dict[tuple[str, str], dict] = {}
    for mid, module in mods.items():
        for raw in _list(module, "ports", mid):
            _need(isinstance(raw, dict), f"{mid}: port must be an object")
            wp = _world_port(mid, raw, world[mid])
            _need(wp["id"] not in ports, f"{mid}: duplicate port {show(wp['id'][1])}")
            ports[wp["id"]] = wp

    seams: list[Seam] = []
    used: set[tuple[str, str]] = set()
    done: set[tuple] = set()
    for key, a in sorted(ports.items()):
        if a["peer"] is None:
            continue
        label = f"{key[0]}.{key[1]}"
        _need(a["peer"][0] != key[0], f"{label}: peer is in the same module")
        b = ports.get(a["peer"])
        _need(b is not None, f"{label}: peer {a['peer']} does not exist")
        _need(b["peer"] == key, f"{label}: peer {a['peer']} does not point back")
        pair = tuple(sorted((key, a["peer"])))
        if pair in done:
            continue
        done.add(pair)
        _need(a["seam"] == b["seam"], f"{label}: peers name different seams ({show(a['seam'])} vs {show(b['seam'])})")
        _need(abs(sum(x * y for x, y in zip(a["normal"], b["normal"])) + 1) <= NORMAL_TOL,
              f"{label}: port normals are not opposite in world space")
        _need(math.dist(a["pos"], b["pos"]) <= POSITION_TOL, f"{label}: peer port frames do not coincide")
        for axis in ("width_axis", "height_axis"):  # same span lines; the sign of an axis is irrelevant
            _need(abs(sum(x * y for x, y in zip(a[axis], b[axis]))) >= 1 - NORMAL_TOL,
                  f"{label}: peer port {axis.split('_')[0]} directions differ")
        _need(abs(a["width"] - b["width"]) <= SPAN_TOL and abs(a["height"] - b["height"]) <= SPAN_TOL,
              f"{label}: peer port spans differ")
        sid, members = a["seam"], (pair[0][0], pair[1][0])
        owners = [m for m in members if (m, sid) in owned]
        if len(owners) > 1:
            raise DuplicateOwnershipError(f"seam {show(sid)} between {members[0]} and {members[1]} is owned by both")
        _need(len(owners) == 1, f"seam {show(sid)} between {members[0]} and {members[1]} has no owner")
        seam = owned[(owners[0], sid)]
        _need(sorted(seam["participants"]) == sorted(members),
              f"{owners[0]}.{sid}: participants do not match the connected modules")
        used.add((owners[0], sid))
        seams.append(Seam(sid, owners[0], tuple(sorted(members)), seam["surfaceOpId"], pair))
    stray = sorted(set(owned) - used)
    _need(not stray, f"seam {show(stray[0][1])} owned by {stray[0][0]} is not referenced by a port pair" if stray else "")
    return tuple(sorted(seams, key=lambda s: (s.participants, s.seam_id)))


def assemble(modules: list[dict]) -> Assembly:
    """Merge modules into one consistent assembly, or raise `AssemblyError`."""
    mods = _copy_modules(modules)
    world, order = _check_links(mods)
    seams = _check_seams(mods, world)
    return Assembly(mods, order, dict(sorted(world.items())), seams)


def merge_assemblies(*assemblies: Assembly) -> Assembly:
    """Union of assemblies with disjoint module ids, re-validated as a whole."""
    _need(len(assemblies) > 0 and all(isinstance(a, Assembly) for a in assemblies), "expected assemblies")
    ids = [m for a in assemblies for m in a.modules]
    dupes = sorted({m for m in ids if ids.count(m) > 1})
    _need(not dupes, f"modules present in more than one assembly: {dupes}")
    return assemble([m for a in assemblies for m in a.modules.values()])
