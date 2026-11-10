"""SE-02 gates: volatile project actor, revisions and fenced single-writer ownership.

Wholly synthetic and cloud-only. This exercises the in-process actor contract (CAS, fencing,
idempotency, atomic 1-8 module swap, pause/revoke, volatility). It does not exercise auth
transport, WebSocket, Editor or any native/owner acceptance (SE-03/05/11 own those).
"""
from __future__ import annotations

import ast
import builtins
import copy
import io
import json
import os
import pathlib
import subprocess
import sys
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bomc.compiler.graph_to_bomc import compile_document  # noqa: E402
from core.identity import store as identity_store  # noqa: E402
from core.project import operations as ops  # noqa: E402
from core.project.actor import ActorRegistry, ProjectActor  # noqa: E402
from core.project.state import ActorError, Grant  # noqa: E402
from examples import bmb026_house as house  # noqa: E402

BASELINE_SHA = "071ebe152b44d2bae387818094ad67a6f461645d45d1ad33c195848dbb0b49aa"
SE01_IR_SHA = "62fe1f947aa61070307bf72892c745449c836c47b54c112e685179d21e9ff7e0"
SE01_PROJECTION_SHA = "8ac853a5b489a768911be85c0133ae13c1eea1215ba6af301c8a16a809576cfd"
LIVING = house.ROOM_IDS["living"]
BEDROOM = house.ROOM_IDS["bedroom-a"]
OWNER, AGENT_A, AGENT_B, READER = "owner-1", "agent-a", "agent-b", "viewer-1"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Gate:
    """Blocks the first commit at a named point so a test can act 'during' a write."""

    def __init__(self, point="after-validate"):
        self.point, self.armed = point, False
        self.entered, self.release = threading.Event(), threading.Event()

    def __call__(self, name):
        if self.armed and name == self.point:
            self.armed = False
            self.entered.set()
            if not self.release.wait(20):
                raise RuntimeError("test gate timed out")


def grant(subject, *scopes, tenant="tenant-1", project="project-1"):
    return Grant(tenant, project, subject, f"client of {subject}", frozenset(scopes or ("read", "write")))


def make_actor(**kw):
    clock = kw.setdefault("clock", Clock())
    actor = ProjectActor("tenant-1", "project-1", 1, OWNER, **kw)
    actor.owner_heartbeat(OWNER)
    actor.grant(OWNER, grant(AGENT_A))
    actor.grant(OWNER, grant(AGENT_B))
    actor.grant(OWNER, grant(READER, "read"))
    return actor, clock


def txn(base, changes, key):
    return {"schemaVersion": "draft-operation-v1", "transactionId": key, "idempotencyKey": key,
            "baseProjectRevision": base, "changes": changes}


def create(module):
    return {"op": "replace_module", "moduleId": module["moduleId"],
            "expectedModuleRevision": None, "module": module}


def replace(module, expected):
    return {"op": "replace_module", "moduleId": module["moduleId"],
            "expectedModuleRevision": expected, "module": module}


def room(name):
    return next(m for m in house.build_house()["modules"] if m["moduleId"] == house.ROOM_IDS.get(name, name))


def seed(actor, subject=AGENT_A, modules=None, key="seed-1"):
    lease = actor.acquire_lease(subject)
    modules = modules if modules is not None else house.build_house()["modules"]
    actor.submit(subject, lease, txn(0, [create(m) for m in modules], key))
    return lease


def shed(identifier="house/level/shed", x=20.0, deps=None):
    module = house._room("bath", False)                 # plain room: no ports or seams to reciprocate
    module["moduleId"] = identifier
    module["localFrame"]["transform"] = list(house.dag.translation(x, 0, 0))
    module["dependencies"] = deps or []
    house._annotate_repeated_solid_faces(module)        # same label reuse as the house (254-string cap stays)
    return module


def tweak(module, thickness):
    return ops.update_operation(module, "floor", thickness=thickness)


def code_of(test, fn, *args):
    with test.assertRaises(ActorError) as raised:
        fn(*args)
    return raised.exception


@contextmanager
def forbid_disk_writes():
    real_open = builtins.open

    def guarded(file, mode="r", *a, **k):
        if any(c in str(mode) for c in "wax+"):
            raise AssertionError(f"disk write attempted: {file!r}")
        return real_open(file, mode, *a, **k)

    def boom(name):
        return mock.patch(name, side_effect=AssertionError(f"disk call attempted: {name}"))
    names = ["os.fsync", "os.write", "os.replace", "os.rename", "os.mkdir", "os.makedirs", "os.remove",
             "os.unlink", "os.truncate", "pathlib.Path.write_text", "pathlib.Path.write_bytes",
             "pathlib.Path.mkdir", "shutil.copyfile", "tempfile.mkstemp", "tempfile.mkdtemp"]
    patches = [boom(n) for n in names] + [mock.patch("builtins.open", guarded), mock.patch("io.open", guarded)]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()


class Races(unittest.TestCase):
    def test_two_agents_same_revision_one_accepted_other_conflicts(self):
        actor, _ = make_actor()
        seed(actor)
        base = actor.view(READER)["projectRevision"]
        self.assertEqual(base, 1)
        living = room("living")
        lease_a = actor.acquire_lease(AGENT_A)
        accepted = actor.submit(AGENT_A, lease_a, txn(base, [replace(tweak(living, 0.16), 1)], "a-edit"))
        self.assertEqual((accepted["status"], accepted["projectRevision"]), ("COMMITTED", 2))
        self.assertTrue(actor.release_lease(AGENT_A, lease_a))
        lease_b = actor.acquire_lease(AGENT_B)            # B read revision 1 too, and is now stale
        lost = code_of(self, actor.submit, AGENT_B, lease_b, txn(base, [replace(tweak(living, 0.17), 1)], "b-edit"))
        self.assertEqual(lost.code, "REVISION_CONFLICT")
        self.assertEqual(lost.detail["currentProjectRevision"], 2)
        view = actor.view(READER)
        self.assertEqual(view["projectRevision"], 2)
        self.assertEqual(view["moduleRevisions"][LIVING], 2)
        fresh = tweak(tweak(living, 0.16), 0.17)          # B rebases on revision 2 and succeeds
        again = actor.submit(AGENT_B, lease_b, txn(2, [replace(fresh, 2)], "b-edit-2"))
        self.assertEqual(again["projectRevision"], 3)

    def test_concurrent_threads_exactly_one_commits(self):
        actor, _ = make_actor(max_pending=16)
        lease = seed(actor)
        living = room("living")
        barrier, results = threading.Barrier(4), []

        def worker(n):
            barrier.wait(10)
            try:
                results.append(actor.submit(AGENT_A, lease, txn(
                    1, [replace(tweak(living, 0.16 + n / 1000), 1)], f"race-{n}"))["status"])
            except ActorError as exc:
                results.append(exc.code)
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
        self.assertEqual(sorted(results), ["COMMITTED", "REVISION_CONFLICT", "REVISION_CONFLICT", "REVISION_CONFLICT"])
        self.assertEqual(actor.status(OWNER)["projectRevision"], 2)

    def test_project_revision_is_global_even_for_disjoint_modules(self):
        actor, _ = make_actor()
        lease = seed(actor)
        actor.submit(AGENT_A, lease, txn(1, [replace(tweak(room("living"), 0.16), 1)], "k1"))
        stale = code_of(self, actor.submit, AGENT_A, lease,
                        txn(1, [replace(tweak(room("bedroom-b"), 0.16), 1)], "k2"))
        self.assertEqual(stale.code, "REVISION_CONFLICT")

    def test_stale_module_revision_conflicts_without_change(self):
        actor, _ = make_actor()
        lease = seed(actor)
        before = actor.state_digest()
        stale = code_of(self, actor.submit, AGENT_A, lease, txn(1, [replace(tweak(room("living"), 0.16), 7)], "k"))
        self.assertEqual(stale.code, "REVISION_CONFLICT")
        self.assertEqual(actor.state_digest(), before)


class Idempotency(unittest.TestCase):
    def test_exact_repeat_applies_once_and_replays_the_outcome(self):
        actor, _ = make_actor()
        lease = seed(actor)
        request = txn(1, [replace(tweak(room("living"), 0.16), 1)], "once")
        first = actor.submit(AGENT_A, lease, request)
        digest = actor.state_digest()
        second = actor.submit(AGENT_A, lease, copy.deepcopy(request))
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual({k: v for k, v in first.items() if k != "replayed"},
                         {k: v for k, v in second.items() if k != "replayed"})
        self.assertEqual(actor.state_digest(), digest)
        self.assertEqual(actor.status(OWNER)["projectRevision"], 2)

    def test_replay_wins_over_the_stale_revision_check(self):
        actor, _ = make_actor()
        lease = seed(actor)
        request = txn(1, [replace(tweak(room("living"), 0.16), 1)], "k1")
        actor.submit(AGENT_A, lease, request)
        actor.submit(AGENT_A, lease, txn(2, [replace(tweak(tweak(room("living"), 0.16), 0.17), 2)], "k2"))
        replay = actor.submit(AGENT_A, lease, request)       # base 1 is long stale, key is known
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["projectRevision"], 2)
        self.assertEqual(actor.status(OWNER)["projectRevision"], 3)

    def test_key_reuse_with_a_different_request_conflicts(self):
        actor, _ = make_actor()
        lease = seed(actor)
        actor.submit(AGENT_A, lease, txn(1, [replace(tweak(room("living"), 0.16), 1)], "same-key"))
        digest = actor.state_digest()
        clash = code_of(self, actor.submit, AGENT_A, lease,
                        txn(1, [replace(tweak(room("living"), 0.18), 1)], "same-key"))
        self.assertEqual(clash.code, "IDEMPOTENCY_CONFLICT")
        self.assertEqual(actor.state_digest(), digest)

    def test_key_cannot_be_replayed_by_a_different_principal(self):
        actor, _ = make_actor()
        lease_a = seed(actor)
        request = txn(1, [replace(tweak(room("living"), 0.16), 1)], "owned-by-a")
        actor.submit(AGENT_A, lease_a, request)
        actor.release_lease(AGENT_A, lease_a)
        lease_b = actor.acquire_lease(AGENT_B)
        self.assertEqual(code_of(self, actor.submit, AGENT_B, lease_b, request).code, "IDEMPOTENCY_CONFLICT")

    def test_rejected_requests_are_not_cached(self):
        actor, _ = make_actor()
        lease = seed(actor)
        bad = copy.deepcopy(room("living"))
        bad["revision"] = 2
        bad["operations"][1]["thickness"] = -1.0
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, txn(1, [replace(bad, 1)], "retry-me")).code,
                         "INVALID_OPERATION")
        ok = actor.submit(AGENT_A, lease, txn(1, [replace(tweak(room("living"), 0.16), 1)], "retry-me"))
        self.assertFalse(ok["replayed"])


class FailureAtomicity(unittest.TestCase):
    def test_crash_before_swap_leaves_everything_unchanged_and_retry_commits_once(self):
        def crash(point):
            if point == "before-swap":
                raise RuntimeError("simulated crash")
        actor, _ = make_actor(_fault_hook=crash)
        lease = seed_with(actor, crash_after_seed=True)
        before, request = actor.state_digest(), txn(1, [replace(tweak(room("living"), 0.16), 1)], "crashy")
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, request).code, "INTERNAL_ERROR")
        self.assertEqual(actor.state_digest(), before)
        self.assertEqual(actor.view(READER)["projectRevision"], 1)
        actor._fault = None
        done = actor.submit(AGENT_A, lease, request)
        self.assertEqual((done["status"], done["replayed"], done["projectRevision"]), ("COMMITTED", False, 2))

    def test_failure_after_staging_first_participant_changes_nothing(self):
        actor, _ = make_actor()
        lease = seed_pair(actor)
        living, bedroom = connected_pair_modules()
        request = txn(1, [replace(living, 1), replace(bedroom, 1)], "seam-fault")
        before = actor.state_digest()
        actor._fault = lambda point: (_ for _ in ()).throw(RuntimeError("boom")) if point == "after-first-target" else None
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, request).code, "INTERNAL_ERROR")
        self.assertEqual(actor.state_digest(), before)
        status = actor.status(OWNER)
        self.assertEqual((status["projectRevision"], status["moduleRevisions"][LIVING],
                          status["moduleRevisions"][BEDROOM], status["removedModules"]), (1, 1, 1, []))
        actor._fault = None
        self.assertEqual(actor.submit(AGENT_A, lease, request)["projectRevision"], 2)

    def test_invalid_second_participant_changes_nothing(self):
        actor, _ = make_actor()
        lease = seed_pair(actor)
        living, bedroom = connected_pair_modules()
        before = actor.state_digest()
        wrong_rev = code_of(self, actor.submit, AGENT_A, lease,
                            txn(1, [replace(living, 1), replace(bedroom, 5)], "bad-rev"))
        self.assertEqual(wrong_rev.code, "REVISION_CONFLICT")
        broken = copy.deepcopy(bedroom)
        broken["operations"][1]["thickness"] = -1.0
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease,
                                 txn(1, [replace(living, 1), replace(broken, 1)], "bad-geo")).code, "INVALID_OPERATION")
        self.assertEqual(actor.state_digest(), before)

    def test_rejected_geometry_leaves_all_state_and_digests_unchanged(self):
        actor, _ = make_actor()
        lease = seed(actor)
        before, view_before = actor.state_digest(), actor.view(READER)
        bad = copy.deepcopy(room("living"))
        bad["revision"] = 2
        bad["operations"][1]["thickness"] = -1.0
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, txn(1, [replace(bad, 1)], "geo")).code,
                         "INVALID_OPERATION")
        self.assertEqual(actor.state_digest(), before)
        self.assertEqual(actor.view(READER), view_before)

    def test_malformed_requests_are_rejected_before_any_state_change(self):
        actor, _ = make_actor()
        lease = seed(actor)
        before = actor.state_digest()
        for bad in ({}, [], "x", None, {"schemaVersion": "draft-operation-v1"},
                    txn(float("nan"), [], "nan"), txn(1, [], "empty"), txn(1, [{"op": "evil"}], "evil")):
            self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, bad).code, "INVALID_REQUEST")
        self.assertEqual(actor.state_digest(), before)

    def test_strict_bytes_and_size_cap(self):
        actor, _ = make_actor()
        lease = seed(actor)
        self.assertEqual(code_of(self, actor.submit_bytes, AGENT_A, lease, b'{"a":1,"a":2}').code, "INVALID_REQUEST")
        self.assertEqual(code_of(self, actor.submit_bytes, AGENT_A, lease, b" " * (256 * 1024 + 1)).code,
                         "INVALID_REQUEST")
        good = json.dumps(txn(1, [replace(tweak(room("living"), 0.16), 1)], "bytes")).encode()
        self.assertEqual(actor.submit_bytes(AGENT_A, lease, good)["projectRevision"], 2)

    def test_per_module_key_budget_is_a_clean_rejection(self):
        with mock.patch.object(identity_store, "MAX_KEYS_PER_MODULE", 3):
            actor, _ = make_actor()
            lease = seed(actor)
            current = room("living")
            for n in range(2):
                nxt = tweak(current, 0.16 + n / 100)
                actor.submit(AGENT_A, lease, txn(n + 1, [replace(nxt, n + 1)], f"b{n}"))
                current = nxt
            before = actor.state_digest()
            err = code_of(self, actor.submit, AGENT_A, lease, txn(3, [replace(tweak(current, 0.2), 3)], "b9"))
            self.assertEqual(err.code, "BUDGET_EXCEEDED")
            self.assertEqual(actor.state_digest(), before)


def seed_with(actor, crash_after_seed=False):
    hook, actor._fault = actor._fault, None
    lease = seed(actor)
    actor._fault = hook
    return lease


def connected_pair_modules():
    modules = {n: house._room(n, False) for n in ("living", "bedroom-a")}
    house._connect(modules, "living", "bedroom-a", "east", "living-a", opening_offset=1.0)
    for m in modules.values():
        m["revision"] = 2
    return modules["living"], modules["bedroom-a"]


def seed_pair(actor):
    rooms = [house._room(n, False) for n in ("living", "bedroom-a")]
    return seed(actor, modules=rooms)


class AtomicSeam(unittest.TestCase):
    def test_one_sided_halves_are_rejected_and_the_pair_commits_atomically(self):
        actor, _ = make_actor()
        lease = seed_pair(actor)
        living, bedroom = connected_pair_modules()
        before = actor.state_digest()
        for label, change in (("half-living", replace(living, 1)), ("half-bedroom", replace(bedroom, 1))):
            self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, txn(1, [change], label)).code,
                             "INVALID_OPERATION")
            self.assertEqual(actor.state_digest(), before)
        done = actor.submit(AGENT_A, lease, txn(1, [replace(living, 1), replace(bedroom, 1)], "pair"))
        self.assertEqual(done["projectRevision"], 2)
        self.assertEqual(done["moduleRevisions"], {LIVING: 2, BEDROOM: 2})
        self.assertEqual(sorted(done["changedModules"]), sorted([LIVING, BEDROOM]))
        replay = actor.submit(AGENT_A, lease, txn(1, [replace(living, 1), replace(bedroom, 1)], "pair"))
        self.assertTrue(replay["replayed"])
        self.assertEqual(actor.status(OWNER)["projectRevision"], 2)

    def test_dependency_created_in_the_same_transaction_is_honoured(self):
        actor, _ = make_actor()
        lease = seed(actor)
        base_dep = shed("house/level/shed-base", 20.0)
        child = shed("house/level/shed-child", 30.0, [{"moduleId": "house/level/shed-base", "minRevision": 1}])
        done = actor.submit(AGENT_A, lease, txn(1, [create(child), create(base_dep)], "deps-ok"))
        self.assertEqual(done["projectRevision"], 2)

    def test_stale_dependency_minimum_is_rejected(self):
        actor, _ = make_actor()
        lease = seed(actor)
        before = actor.state_digest()
        needy = shed("house/level/needy", 20.0, [{"moduleId": LIVING, "minRevision": 9}])
        err = code_of(self, actor.submit, AGENT_A, lease, txn(1, [create(needy)], "deps-stale"))
        self.assertEqual(err.code, "DEPENDENCY_STALE")
        self.assertEqual((err.detail["required"], err.detail["actual"]), (9, 1))
        self.assertEqual(actor.state_digest(), before)

    def test_new_module_must_start_at_revision_one(self):
        actor, _ = make_actor()
        lease = seed(actor)
        late = shed("house/level/late", 20.0)
        late["revision"] = 4
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, txn(1, [create(late)], "late")).code,
                         "INVALID_OPERATION")

    def test_tombstone_blocks_same_epoch_reuse_but_not_a_new_epoch(self):
        registry = ActorRegistry(clock=Clock())
        actor = registry.open_epoch("tenant-1", "project-1", OWNER)
        actor.owner_heartbeat(OWNER)
        actor.grant(OWNER, grant(AGENT_A))
        lease = seed(actor)
        actor.submit(AGENT_A, lease, txn(1, [create(shed())], "add-shed"))
        removed = actor.submit(AGENT_A, lease, txn(2, [{"op": "remove_module", "moduleId": "house/level/shed",
                                                          "expectedModuleRevision": 1}], "rm-shed"))
        self.assertEqual(removed["removedModules"], ["house/level/shed"])
        self.assertEqual(actor.status(OWNER)["removedModules"], ["house/level/shed"])
        for n, change in enumerate((create(shed()), replace(shed(), 1))):
            self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, txn(3, [change], f"re{n}")).code, "TOMBSTONED")
        fresh = registry.open_epoch("tenant-1", "project-1", OWNER)
        self.assertEqual(fresh.epoch, 2)
        fresh.owner_heartbeat(OWNER)
        fresh.grant(OWNER, grant(AGENT_A))
        lease2 = fresh.acquire_lease(AGENT_A)
        self.assertEqual(fresh.submit(AGENT_A, lease2, txn(0, [create(shed())], "again"))["projectRevision"], 1)

    def test_removing_a_referenced_module_is_rejected(self):
        actor, _ = make_actor()
        lease = seed(actor)
        before = actor.state_digest()
        err = code_of(self, actor.submit, AGENT_A, lease, txn(1, [{"op": "remove_module", "moduleId": LIVING,
                                                                    "expectedModuleRevision": 1}], "rm-live"))
        self.assertIn(err.code, ("INVALID_OPERATION",))
        self.assertEqual(actor.state_digest(), before)


class Ownership(unittest.TestCase):
    def test_second_agent_gets_a_named_lease_held_conflict(self):
        actor, _ = make_actor()
        actor.acquire_lease(AGENT_A)
        err = code_of(self, actor.acquire_lease, AGENT_B)
        self.assertEqual((err.code, err.detail["writer"]), ("LEASE_HELD", AGENT_A))
        self.assertEqual(actor.status(OWNER)["writer"], AGENT_A)

    def test_pause_rejects_a_fenced_write_and_old_leases_stay_dead_after_resume(self):
        actor, _ = make_actor()
        lease = seed(actor)
        fence = actor.status(OWNER)["fence"]
        actor.pause(OWNER)
        self.assertGreater(actor.status(OWNER)["fence"], fence)
        request = txn(1, [replace(tweak(room("living"), 0.16), 1)], "paused")
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, request).code, "PAUSED")
        self.assertEqual(code_of(self, actor.acquire_lease, AGENT_B).code, "PAUSED")
        self.assertEqual(actor.view(READER)["projectRevision"], 1)          # readers still work
        actor.resume(OWNER)
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, request).code, "FENCE_STALE")
        fresh = actor.acquire_lease(AGENT_A)
        self.assertGreater(fresh.fence, lease.fence)
        self.assertEqual(actor.submit(AGENT_A, fresh, request)["projectRevision"], 2)

    def test_revoke_fences_out_the_writer_immediately(self):
        actor, _ = make_actor()
        lease = seed(actor)
        self.assertTrue(actor.revoke(OWNER, AGENT_A))
        request = txn(1, [replace(tweak(room("living"), 0.16), 1)], "revoked")
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, request).code, "GRANT_DENIED")
        self.assertEqual(code_of(self, actor.acquire_lease, AGENT_A).code, "GRANT_DENIED")
        self.assertEqual(code_of(self, actor.view, AGENT_A).code, "GRANT_DENIED")
        self.assertEqual(actor.view(READER)["projectRevision"], 1)
        self.assertIsNone(actor.status(OWNER)["writer"])

    def test_owner_can_take_ownership_and_agent_is_fenced(self):
        actor, _ = make_actor()
        lease = seed(actor)
        mine = actor.owner_acquire(OWNER)
        self.assertGreater(mine.fence, lease.fence)
        request = txn(1, [replace(tweak(room("living"), 0.16), 1)], "from-agent")
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, request).code, "FENCE_STALE")
        self.assertEqual(code_of(self, actor.acquire_lease, AGENT_B).detail["writer"], OWNER)
        self.assertEqual(actor.submit(OWNER, mine, txn(1, [replace(tweak(room("living"), 0.17), 1)], "own"))
                         ["projectRevision"], 2)

    def test_only_the_owner_controls_the_project(self):
        actor, _ = make_actor()
        for call in (actor.pause, actor.resume, actor.owner_acquire, actor.owner_heartbeat, actor.close):
            self.assertEqual(code_of(self, call, AGENT_A).code, "GRANT_DENIED")
        self.assertEqual(code_of(self, actor.revoke, AGENT_A, AGENT_B).code, "GRANT_DENIED")
        self.assertEqual(code_of(self, actor.grant, AGENT_A, grant("evil")).code, "GRANT_DENIED")

    def test_read_only_and_unknown_principals_cannot_write(self):
        actor, _ = make_actor()
        self.assertEqual(code_of(self, actor.acquire_lease, READER).code, "GRANT_DENIED")
        self.assertEqual(code_of(self, actor.acquire_lease, "stranger").code, "GRANT_DENIED")
        self.assertEqual(code_of(self, actor.view, "stranger").code, "GRANT_DENIED")
        self.assertEqual(actor.view(READER)["projectRevision"], 0)

    def test_client_label_is_never_authority(self):
        actor, _ = make_actor()
        impostor = Grant("tenant-1", "project-1", "agent-evil", "agent-a", frozenset({"read"}))
        actor.grant(OWNER, impostor)
        self.assertEqual(code_of(self, actor.acquire_lease, "agent-evil").code, "GRANT_DENIED")

    def test_grant_for_another_tenant_or_project_is_rejected(self):
        actor, _ = make_actor()
        for g in (grant("x", tenant="tenant-2"), grant("x", project="project-2")):
            self.assertEqual(code_of(self, actor.grant, OWNER, g).code, "TENANT_MISMATCH")

    def test_lease_expiry_takeover_and_fence(self):
        actor, clock = make_actor(lease_ttl=60, heartbeat_ttl=10_000)
        lease_a = seed(actor)
        clock.now += 61
        request = txn(1, [replace(tweak(room("living"), 0.16), 1)], "late")
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease_a, request).code, "LEASE_EXPIRED")
        lease_b = actor.acquire_lease(AGENT_B)
        self.assertGreater(lease_b.fence, lease_a.fence)
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease_a, request).code, "FENCE_STALE")
        self.assertEqual(actor.submit(AGENT_B, lease_b, request)["projectRevision"], 2)

    def test_missing_owner_heartbeat_rejects_writes_until_it_returns(self):
        actor, clock = make_actor(heartbeat_ttl=30, lease_ttl=10_000)
        lease = seed(actor)
        clock.now += 31
        request = txn(1, [replace(tweak(room("living"), 0.16), 1)], "hb")
        self.assertEqual(code_of(self, actor.submit, AGENT_A, lease, request).code, "OWNER_ABSENT")
        self.assertFalse(actor.status(READER)["ownerAlive"])
        actor.owner_heartbeat(OWNER)
        self.assertEqual(actor.submit(AGENT_A, lease, request)["projectRevision"], 2)


class Concurrency(unittest.TestCase):
    def test_readers_see_only_committed_state_during_a_write(self):
        gate = Gate()
        actor, _ = make_actor(_fault_hook=gate)
        lease = seed(actor)
        gate.armed = True
        box = {}
        writer = threading.Thread(target=lambda: box.update(out=actor.submit(
            AGENT_A, lease, txn(1, [replace(tweak(room("living"), 0.16), 1)], "slow"))))
        writer.start()
        self.assertTrue(gate.entered.wait(10))
        self.assertEqual(actor.view(READER)["projectRevision"], 1)       # not blocked, old state
        gate.release.set()
        writer.join(10)
        self.assertEqual(box["out"]["projectRevision"], 2)
        self.assertEqual(actor.view(READER)["projectRevision"], 2)

    def test_owner_pause_wins_at_the_next_operation_boundary(self):
        gate = Gate()
        actor, _ = make_actor(_fault_hook=gate, max_pending=8)
        lease = seed(actor)
        gate.armed = True
        out = {}

        def run(name, request):
            try:
                out[name] = actor.submit(AGENT_A, lease, request)["status"]
            except ActorError as exc:
                out[name] = exc.code
        a = threading.Thread(target=run, args=("a", txn(1, [replace(tweak(room("living"), 0.16), 1)], "in-flight")))
        a.start()
        self.assertTrue(gate.entered.wait(10))
        b = threading.Thread(target=run, args=("b", txn(1, [replace(tweak(room("bedroom-b"), 0.16), 1)], "queued")))
        b.start()
        self.assertTrue(wait_for(lambda: actor._pending >= 2))
        c = threading.Thread(target=lambda: actor.pause(OWNER))
        c.start()
        self.assertTrue(wait_for(lambda: actor._pause_requested))
        gate.release.set()
        [t.join(15) for t in (a, b, c)]
        self.assertEqual(out, {"a": "COMMITTED", "b": "PAUSED"})
        self.assertEqual(actor.status(OWNER)["projectRevision"], 2)
        self.assertTrue(actor.status(OWNER)["paused"])

    def test_admission_is_bounded_not_an_unbounded_queue(self):
        gate = Gate()
        actor, _ = make_actor(_fault_hook=gate, max_pending=2)
        lease = seed(actor)
        gate.armed = True
        threads = []
        for n in range(2):
            t = threading.Thread(target=lambda n=n: swallow(actor.submit, AGENT_A, lease, txn(
                1, [replace(tweak(room("living"), 0.16 + n / 100), 1)], f"q{n}")))
            t.start()
            threads.append(t)
            if n == 0:
                self.assertTrue(gate.entered.wait(10))
        self.assertTrue(wait_for(lambda: actor._pending == 2))
        full = code_of(self, actor.submit, AGENT_A, lease, txn(1, [replace(tweak(room("living"), 0.19), 1)], "q9"))
        self.assertEqual((full.code, full.detail["maxPending"]), ("QUEUE_FULL", 2))
        gate.release.set()
        [t.join(15) for t in threads]
        self.assertEqual(actor._pending, 0)


def wait_for(predicate, seconds=10):
    end = threading.Event()
    for _ in range(int(seconds / 0.01)):
        if predicate():
            return True
        end.wait(0.01)
    return False


def swallow(fn, *args):
    try:
        fn(*args)
    except ActorError:
        pass


class Volatility(unittest.TestCase):
    def test_no_disk_write_during_seed_edit_conflict_pause_and_replay(self):
        actor, _ = make_actor()
        with forbid_disk_writes():
            lease = seed(actor)
            actor.submit(AGENT_A, lease, txn(1, [replace(tweak(room("living"), 0.16), 1)], "w1"))
            swallow(actor.submit, AGENT_A, lease, txn(1, [replace(tweak(room("living"), 0.17), 1)], "w2"))
            actor.submit(AGENT_A, lease, txn(1, [replace(tweak(room("living"), 0.16), 1)], "w1"))
            actor.view(READER)
            actor.pause(OWNER)
            actor.resume(OWNER)
        self.assertEqual(actor.status(OWNER)["projectRevision"], 2)

    def test_no_journal_or_storage_import_anywhere_in_the_actor(self):
        for name in ("actor.py", "state.py"):
            tree = ast.parse((ROOT / "core" / "project" / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                for mod in mods:
                    self.assertNotIn("journal", mod)
                    self.assertFalse(mod.startswith("core.storage"), f"{name} imports {mod}")
        out = subprocess.run([sys.executable, "-I", "-c",
                              "import sys; sys.path.insert(0, %r); import core.project.actor as a; "
                              "print('core.storage.journal' in sys.modules)" % str(ROOT)],
                             capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "False")

    def test_returned_views_and_outcomes_are_detached_copies(self):
        actor, _ = make_actor()
        lease = seed(actor)
        digest = actor.state_digest()
        view = actor.view(READER)
        view["projection"]["modules"].clear()
        view["moduleRevisions"]["x"] = 9
        out = actor.submit(AGENT_A, lease, txn(1, [replace(tweak(room("living"), 0.16), 1)], "copy"))
        out["moduleRevisions"].clear()
        self.assertNotEqual(actor.state_digest(), digest)                 # the commit itself
        self.assertEqual(sorted(actor.status(OWNER)["moduleRevisions"]), sorted(house.ROOM_IDS.values()) + [
            house.ROOT + "/roof"])
        self.assertGreater(len(actor.view(READER)["projection"]["modules"]), 0)

    def test_baseline_bytes_and_view_hashes_are_unchanged_through_the_actor(self):
        actor, _ = make_actor()
        seed(actor)
        view = actor.view(READER)
        self.assertEqual((view["canonicalIrSha256"], view["projectionSha256"]), (SE01_IR_SHA, SE01_PROJECTION_SHA))
        self.assertEqual(compile_document(actor._state.project.document()).sha256, BASELINE_SHA)


class Isolation(unittest.TestCase):
    def test_registry_is_exact_triple_with_one_answer_for_every_miss(self):
        registry = ActorRegistry(clock=Clock())
        one = registry.open_epoch("tenant-1", "project-1", OWNER)
        registry.open_epoch("tenant-2", "project-1", "owner-2")
        self.assertIs(registry.get("tenant-1", "project-1", 1), one)
        misses = [("tenant-1", "project-1", 2), ("tenant-1", "project-2", 1), ("tenant-3", "project-1", 1),
                  ("tenant-1", None, 1), (["tenant-1"], "project-1", 1)]
        messages = set()
        for triple in misses:
            err = code_of(self, registry.get, *triple)
            self.assertEqual(err.code, "NOT_FOUND")
            messages.add(err.message)
        self.assertEqual(len(messages), 1)
        for forbidden in ("list", "find", "search", "all", "tenants"):
            self.assertFalse(hasattr(registry, forbidden))

    def test_tenants_do_not_share_state_grants_or_revisions(self):
        registry = ActorRegistry(clock=Clock())
        a = registry.open_epoch("tenant-1", "project-1", OWNER)
        b = registry.open_epoch("tenant-2", "project-1", "owner-2")
        a.owner_heartbeat(OWNER)
        a.grant(OWNER, grant(AGENT_A))
        seed(a)
        self.assertEqual(b.status("owner-2")["projectRevision"], 0)
        self.assertEqual(code_of(self, b.acquire_lease, AGENT_A).code, "GRANT_DENIED")
        self.assertEqual(code_of(self, b.view, OWNER).code, "GRANT_DENIED")

    def test_new_epoch_starts_empty_and_retires_the_old_actor(self):
        registry = ActorRegistry(clock=Clock())
        old = registry.open_epoch("tenant-1", "project-1", OWNER)
        old.owner_heartbeat(OWNER)
        old.grant(OWNER, grant(AGENT_A))
        lease = seed(old)
        new = registry.open_epoch("tenant-1", "project-1", OWNER)
        self.assertEqual((new.epoch, new.status(OWNER)["projectRevision"]), (2, 0))
        self.assertEqual(code_of(self, old.submit, AGENT_A, lease,
                                 txn(1, [replace(tweak(room("living"), 0.16), 1)], "zombie")).code, "EPOCH_CLOSED")
        self.assertEqual(code_of(self, old.view, OWNER).code, "EPOCH_CLOSED")

    def test_constructor_validates_identity_and_limits(self):
        for kwargs in ({"epoch": 0}, {"epoch": True}, {"tenant": "bad tenant"}, {"owner": ""},
                       {"max_pending": 0}, {"lease_ttl": float("nan")}, {"heartbeat_ttl": -1}):
            args = {"tenant": "tenant-1", "project": "project-1", "epoch": 1, "owner": OWNER, **kwargs}
            with self.assertRaises(ActorError):
                ProjectActor(args.pop("tenant"), args.pop("project"), args.pop("epoch"), args.pop("owner"), **args)


if __name__ == "__main__":
    unittest.main()
