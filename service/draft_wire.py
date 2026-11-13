"""Explicit DraftOperationV1 -> accepted legacy transaction mapping (no actor rewrite)."""
from service.tools import ToolFailure


def operation(transaction, actor, channel, fence):
    if transaction.get('schemaVersion') != 1:
        return transaction
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
        if kind == 'replace_module' and isinstance(module, dict):
            item['module'] = module
        elif kind != 'remove_module':
            raise ToolFailure('INVALID_REQUEST', 'unsupported change')
        mapped.append(item)
    for mid, expected in revisions.items():
        if mid not in seen and actor._state.project.module_revisions().get(mid) != expected:
            raise ToolFailure('REVISION_CONFLICT', 'stale dependency revision')
    return dict(schemaVersion='draft-operation-v1', transactionId=transaction['operationId'],
                idempotencyKey=transaction['operationId'], baseProjectRevision=transaction.get('expectedProjectRevision'),
                changes=sorted(mapped, key=lambda c: c['moduleId']))
