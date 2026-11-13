"""Explicit DraftOperationV1 -> accepted legacy transaction mapping (no actor rewrite)."""
from service.tools import ToolFailure
from core.project.operations import canonical_json, sha256_hex


def fingerprint(transaction):
    action = transaction['action']
    changes = sorted(action['changes'], key=lambda c: c.get('module', {}).get('moduleId', c.get('moduleId', '')))
    return sha256_hex(canonical_json(dict(transaction, action=dict(action, changes=changes))))


def _references(module):
    refs = set()
    if isinstance(module.get('parentId'), str):
        refs.add(module['parentId'])
    for key, field in (('dependencies', 'moduleId'), ('ports', 'peer')):
        values = module.get(key, [])
        for value in values if isinstance(values, list) else []:
            if isinstance(value, dict):
                ref = value.get(field)
                ref = ref.get('moduleId') if isinstance(ref, dict) else ref
                if isinstance(ref, str):
                    refs.add(ref)
    return refs


def check_dependencies(transaction, actor):
    live, expected = actor._state.project.modules, transaction['expectedModuleRevisions']
    targets, required = set(), set()
    for change in transaction['action']['changes']:
        module = change.get('module', {})
        mid = module.get('moduleId', change.get('moduleId'))
        targets.add(mid)
        required |= _references(live.get(mid, {})) | _references(module)
    for mid in required - targets:
        if mid in live and mid not in expected:
            raise ToolFailure('REVISION_CONFLICT', 'expected revision for touched dependency is required')
    for mid, revision in expected.items():
        if mid not in targets and (live[mid]['revision'] if mid in live else None) != revision:
            raise ToolFailure('REVISION_CONFLICT', 'stale dependency revision')


def operation(transaction, actor, channel, fence):
    if transaction.get('schemaVersion') != 1:
        return transaction
    if type(transaction['schemaVersion']) is not int or set(transaction) != {
            'schemaVersion', 'projectId', 'epoch', 'operationId', 'expectedProjectRevision',
            'leaseFence', 'expectedModuleRevisions', 'action'}:
        raise ToolFailure('INVALID_REQUEST', 'exact DraftOperationV1 fields required')
    import uuid
    try:
        uuid.UUID(transaction['operationId'])
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ToolFailure('INVALID_REQUEST', 'operationId UUID required') from None
    if transaction.get('projectId') != actor.project or transaction.get('epoch') != channel.epoch:
        raise ToolFailure('EPOCH_CLOSED', 'wrong project or wire epoch')
    if transaction.get('leaseFence') != fence:
        raise ToolFailure('FENCE_STALE', 'lease fence mismatch')
    revisions = transaction.get('expectedModuleRevisions')
    action = transaction.get('action', {})
    if not isinstance(revisions, dict) or not isinstance(action, dict) or action.get('kind') != 'transaction':
        raise ToolFailure('INVALID_REQUEST', 'typed atomic transaction required')
    import re
    if (type(transaction.get('expectedProjectRevision')) is not int or not 0 <= transaction['expectedProjectRevision'] <= 2**53 - 1 or
            type(transaction.get('leaseFence')) is not int or set(action) != {'kind', 'changes'} or
            any(not isinstance(mid, str) or len(mid) > 180 or not re.fullmatch(r'[a-z][a-z0-9-]*(/[a-z][a-z0-9-]*)+', mid) or
                revision is not None and (type(revision) is not int or not 0 <= revision <= 2**53 - 1) for mid, revision in revisions.items())):
        raise ToolFailure('INVALID_REQUEST', 'invalid revision map or transaction fields')
    changes = action.get('changes')
    if not isinstance(changes, list) or not 1 <= len(changes) <= 8:
        raise ToolFailure('INVALID_REQUEST', 'one to eight changes required')
    mapped, seen = [], set()
    for change in changes:
        if not isinstance(change, dict):
            raise ToolFailure('INVALID_REQUEST', 'invalid change')
        kind, module = change.get('kind'), change.get('module')
        mid = module.get('moduleId') if isinstance(module, dict) else change.get('moduleId')
        if not isinstance(mid, str) or mid in seen or mid not in revisions:
            raise ToolFailure('INVALID_REQUEST', 'unique module IDs and expected revisions required')
        seen.add(mid)
        item = dict(op=kind, moduleId=mid, expectedModuleRevision=revisions[mid])
        if kind == 'replace_module' and isinstance(module, dict) and set(change) == {'kind', 'module'}:
            item['module'] = module
        elif kind != 'remove_module' or set(change) != {'kind', 'moduleId'}:
            raise ToolFailure('INVALID_REQUEST', 'unsupported change')
        mapped.append(item)
    return dict(schemaVersion='draft-operation-v1', transactionId=transaction['operationId'],
                idempotencyKey=transaction['operationId'], baseProjectRevision=transaction.get('expectedProjectRevision'),
                changes=sorted(mapped, key=lambda c: c['moduleId']))
