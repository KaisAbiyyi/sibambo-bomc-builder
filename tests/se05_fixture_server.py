"""Loopback-only cross-repository test driver, never mounted by the production app.

Writes only synthetic credentials and ephemeral certificate metadata to the chosen D: test
directory. All command routes require a random per-launch driver key. No real IdP/client data.
"""
import argparse
import asyncio
import copy
import json
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.remote_support import Env, TENANT, ISSUER
from tests.test_remote_mcp import txn, create, swap
from examples import bmb026_house as house
from starlette.responses import JSONResponse


async def main(output, port):
    env = Env(port=port, allowed_origins=('http://localhost:5175', 'http://127.0.0.1:5175'))
    driver = secrets.token_urlsafe(32)
    product = env.app
    async def test_driver(scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/__se05_test/'):
            return await product(scope, receive, send)
        from starlette.requests import Request
        request = Request(scope, receive)
        if request.headers.get('authorization') != 'Bearer ' + driver:
            return await JSONResponse({}, status_code=403)(scope, receive, send)
        body = await request.json()
        project = body.get('project', 'live-test')
        actor = env.host.actor(TENANT, project)
        action = scope['path'].rsplit('/', 1)[-1]
        if action == 'operation':
            async with env.client(env.mint('agent-1'), project) as client:
                lease = await client.call_tool('acquire_writer', {})
                if lease.is_error:
                    result = lease.structured_content
                else:
                    revision = actor._state.project.project_revision
                    module = house._room('living', False)
                    if revision:
                        module = actor._state.project.module(module['moduleId'])
                        module['revision'] += 1
                        module['materials'][0]['rgba'][0] = (module['materials'][0]['rgba'][0] + 5) % 256
                    transaction = txn(revision, [create(module) if revision == 0 else swap(module, revision)], 'browser-op-' + str(revision + 1))
                    reply = await client.call_tool('apply_operation', {'fence': lease.structured_content['fence'], 'transaction': transaction, 'requestId': body.get('requestId')})
                    result = reply.structured_content
        elif action == 'close':
            channel = env.host.drafts.channel(actor)
            with env.host.drafts.lock:
                for peer in channel.peers:
                    peer.closed = True
            result = {'ok': True}
        elif action == 'fault':
            channel = env.host.drafts.channel(actor)
            with env.host.drafts.lock:
                event = copy.deepcopy(channel.events[-1][0])
                event['revision'] += 2
                if body.get('kind') == 'corrupt':
                    event['changed'][0]['canonicalIrJson'] = '{}'
                for peer in channel.peers:
                    peer.enqueue(event)
            result = {'ok': True}
        elif action == 'status':
            channel = env.host.drafts.channel(actor)
            result = {'revision': actor._state.project.project_revision, 'acked': channel.acked,
                      'events': len(channel.events), 'epoch': channel.epoch}
        else:
            result = {'ok': False}
        await JSONResponse(result)(scope, receive, send)
    env.server.config.app = test_driver
    env.start()
    try:
        owner = await env.setup_project('live-test')
        await env.setup_project('other-live')
        output.mkdir(parents=True, exist_ok=True)
        bootstrap = dict(base=env.base, certificate=str(env.dir / 'cert.pem'), ownerToken=owner,
                         issuer=ISSUER,
                         audience=env.audience, driver=driver, sessionKey=secrets.token_urlsafe(32))
        (output / 'bootstrap.json').write_text(json.dumps(bootstrap), encoding='utf-8')
        print('SE05_FIXTURE_READY', flush=True)
        while True:
            await asyncio.sleep(1)
    finally:
        env.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    asyncio.run(main(args.output.resolve(), args.port))
