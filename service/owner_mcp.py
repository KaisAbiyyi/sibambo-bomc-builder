"""Public owner/BFF contract adapter. No dependency on private Editor implementation."""
from __future__ import annotations

import asyncio
import hmac
import json
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import JSONResponse
from core.project.state import ActorError, Grant
from core.project.requests import RequestError
from service.auth import principal_id
from service.tools import OwnerApi, ToolFailure

CONTRACT = 'se04-owner-mcp-v1'


class OwnerMcp:
    def __init__(self, app, host, verifier):
        self.app, self.host, self.verifier = app, host, verifier
        self.api = OwnerApi(host)

    def own(self, principal, project):
        return self.api._own(principal, project)

    def status(self, principal, project):
        actor = self.own(principal, project)
        channel = self.host.drafts.channel(actor)
        status = actor.status(principal.id)
        with self.host.drafts.lock:
            pending = [self.host.drafts.request_pairing(item['principal'], actor)
                       for key, item in list(self.host.drafts.pending.items()) if key[:2] == (actor.tenant, project)]
            # Pairing code is compared by the owner, never treated as an authentication credential.
            for item in pending:
                item.pop('pairingCode', None)
            grants = [dict(id=g.subject, agentSubject=self.host.drafts.identities.get(g.subject, g.subject),
                           clientId=g.client, displayName=g.client, scopes=sorted(g.scopes), state='active')
                      for g in actor._grants.values()]
            phase = ('paused' if status['paused'] else 'awaiting-owner-grant' if pending else
                     'writer-active' if status['writer'] else 'connected/read-only')
            return dict(contract=CONTRACT, projectId=project, projectName=project, phase=phase,
                        capabilities=['read', 'write'], pending=pending, grants=grants,
                        writer=status['writer'], seenRevision=status['projectRevision'],
                        renderedRevision=max(0, channel.acked), paused=status['paused'],
                        requests=self.requests(actor), epoch=channel.epoch)

    def requests(self, actor):
        channel = self.host.drafts.channel(actor)
        items = self.host.requests.read(actor.tenant, actor.project)
        live = {str(item['id']) for item in items}
        channel.requests = {k: v for k, v in channel.requests.items() if k in live}
        return [dict(id=str(item['id']), body=item['text'], moduleIds=channel.requests.get(str(item['id']), {}).get('moduleIds', []),
                     status=channel.requests.get(str(item['id']), {}).get('status', 'open'),
                     kind=channel.requests.get(str(item['id']), {}).get('kind', 'instruction'),
                     parameters=channel.requests.get(str(item['id']), {}).get('parameters', {})) for item in items]

    def request_status(self, actor):
        channel = self.host.drafts.channel(actor)
        message = dict(type='owner_request_status', projectId=actor.project, epoch=channel.epoch,
                       requests=[dict(id=item['id'], status=item['status']) for item in self.requests(actor)])
        for peer in channel.peers:
            peer.enqueue(message)  # deliberately no text, geometry or project revision

    def dispatch(self, principal, project, endpoint, method, body):
        if endpoint == '/open' and method == 'POST':
            self.api.open(principal, project)
        actor = self.own(principal, project)
        hub = self.host.drafts
        with hub.lock:
            if endpoint == '/ticket' and method == 'POST':
                return dict(contract=CONTRACT, projectId=project, **hub.issue_ticket(actor))
            if endpoint == '/pause' and method == 'POST':
                if type(body.get('paused')) is not bool:
                    raise ToolFailure('INVALID_REQUEST', 'paused boolean required')
                (actor.pause if body['paused'] else actor.resume)(principal.id)
                hub.invalidate(actor)
            elif endpoint == '/grants' and method == 'POST':
                action, gid = body.get('action'), body.get('grantId')
                if action in ('approve', 'deny'):
                    entry = next(((k, p) for k, p in hub.pending.items() if k[:2] == (actor.tenant, project) and p['id'] == gid), None)
                    if not entry:
                        raise ToolFailure('FORBIDDEN', 'pairing is absent or expired')
                    key, pending = entry
                    if pending['deadline'] <= hub.clock() or pending['attempts'] >= 5:
                        hub.pending.pop(key, None)
                        raise ToolFailure('FORBIDDEN', 'pairing is absent or expired')
                    scopes = body.get('scopes')
                    if (body.get('agentSubject') != pending['agentSubject'] or body.get('clientId') != pending['clientId'] or
                            scopes != pending['scopes']):
                        raise ToolFailure('FORBIDDEN', 'exact credential identity and scopes required')
                    if action == 'approve':
                        pending['attempts'] += 1
                        code = body.get('confirmationCode')
                        if not isinstance(code, str) or not hmac.compare_digest(code, pending['pairingCode']):
                            raise ToolFailure('FORBIDDEN', 'pairing comparison failed')
                        existing = actor._grants.get(pending['principal'].id)
                        if existing and existing.client != pending['clientId']:
                            actor.revoke(principal.id, existing.subject)
                        actor.grant(principal.id, Grant(actor.tenant, project, pending['principal'].id,
                                                       pending['clientId'], frozenset(scopes)))
                        hub.identities[pending['principal'].id] = pending['agentSubject']
                    hub.pending.pop(key, None)
                elif action in ('revoke', 'remove'):
                    scopes = body.get('scopes')
                    if not isinstance(scopes, list) or any(s not in ('read', 'write') for s in scopes):
                        raise ToolFailure('INVALID_REQUEST', 'grant scopes required')
                    target = principal_id(principal.issuer, body.get('agentSubject', ''), body.get('clientId', ''))
                    grant = actor._grants.get(target)
                    if gid != target or not grant or body.get('clientId') != grant.client or sorted(scopes) != sorted(grant.scopes):
                        raise ToolFailure('FORBIDDEN', 'exact credential grant required')
                    actor.revoke(principal.id, target)
                else:
                    raise ToolFailure('INVALID_REQUEST', 'invalid grant action')
                hub.invalidate(actor)
            elif endpoint == '/requests' and method == 'POST':
                channel = hub.channel(actor)
                action = body.get('action')
                if action == 'create':
                    text, mids, kind, params = body.get('body'), body.get('moduleIds'), body.get('kind'), body.get('parameters')
                    import re
                    if (not isinstance(mids, list) or len(mids) > 8 or
                            any(not isinstance(mid, str) or len(mid) > 180 or not re.fullmatch(r'[a-z][a-z0-9-]*(/[a-z][a-z0-9-]*)+', mid) for mid in mids) or
                            len(set(mids)) != len(mids)):
                        raise ToolFailure('INVALID_REQUEST', 'at most eight module IDs required')
                    if kind not in ('instruction', 'typed-parameters') or not isinstance(params, dict) or len(params) > 16:
                        raise ToolFailure('INVALID_REQUEST', 'invalid typed request')
                    import math
                    import re
                    if any(not isinstance(k, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', k) or
                           type(v) not in (int, float) or abs(v) > 1e6 or not math.isfinite(v) for k, v in params.items()) or (kind == 'typed-parameters' and not params):
                        raise ToolFailure('INVALID_REQUEST', 'invalid typed parameters')
                    rid = str(self.host.requests.post(actor.tenant, project, text))
                    channel.requests[rid] = dict(status='open', moduleIds=mids, kind=kind, parameters=params)
                elif action in ('withdraw', 'mark-read', 'mark-addressed'):
                    rid = body.get('requestId')
                    item = next((x for x in self.requests(actor) if x['id'] == rid), None)
                    if not item:
                        raise ToolFailure('NOT_FOUND', 'no such owner request')
                    # Only a rendered operation can address a request; owner UI cannot forge this proof.
                    if action == 'mark-addressed':
                        raise ToolFailure('FORBIDDEN', 'addressed requires a rendered operation receipt')
                    channel.requests.setdefault(rid, {})['status'] = 'withdrawn' if action == 'withdraw' else 'read'
                else:
                    raise ToolFailure('INVALID_REQUEST', 'invalid request action')
                self.request_status(actor)
            elif endpoint not in ('', '/open', '/requests'):
                raise ToolFailure('NOT_FOUND', 'no such owner action')
            return self.status(principal, project)

    async def __call__(self, scope, receive, send):
        import re
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        match = re.fullmatch(r'/v1/projects/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/owner/mcp(/[a-z-]+)?', scope['path'])
        logout = scope['path'] == '/owner/v1/logout'
        if not match and not logout:
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        headers = {'cache-control': 'no-store', 'x-content-type-options': 'nosniff', 'x-accel-buffering': 'no'}
        principal = None
        auth = request.headers.get('authorization', '')
        if auth[:7].lower() == 'bearer ':
            principal = await asyncio.to_thread(self.verifier.principal_of, auth[7:].strip())
        try:
            if principal is None:
                raise ToolFailure('UNAUTHENTICATED', 'owner authentication required')
            if logout:
                if request.method != 'POST':
                    return await JSONResponse({}, status_code=405, headers=headers)(scope, receive, send)
                await asyncio.to_thread(self.host.drafts.disconnect_owner, principal)
                return await JSONResponse({'contract': CONTRACT, 'ok': True}, headers=headers)(scope, receive, send)
            project, endpoint = match[1], match[2] or ''
            if request.method not in ('GET', 'POST') or (request.method == 'GET' and endpoint not in ('', '/requests')):
                return await JSONResponse({}, status_code=405, headers=headers)(scope, receive, send)
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 16384:
                    raise ToolFailure('INVALID_REQUEST', 'owner body exceeds 16 KiB')
            try:
                body = json.loads(raw) if raw else {}
                if not isinstance(body, dict):
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise ToolFailure('INVALID_REQUEST', 'expected JSON object') from None
            result = await asyncio.to_thread(self.dispatch, principal, project, endpoint, request.method, body)
            response = JSONResponse(result, headers=headers)
        except (ToolFailure, ActorError, RequestError) as exc:
            from service import errors
            code = getattr(exc, 'code', 'INVALID_REQUEST')
            response = JSONResponse({'error': errors.error_body(code, 'owner action rejected')},
                                    status_code=errors.http_status(code), headers=headers)
        await response(scope, receive, send)
