"""WP2 corrective isolation: add-on credentials cannot enter the legacy actor."""
import unittest
import json
import os
import stat
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch
from service.bridge import BridgeServer
from service.local_demo import LocalDemo


class LegacyActor:
    def __init__(self):
        self.calls = []

    def call(self, principal, project, tool, args):
        self.calls.append((tool, args))
        return {'legacyExecuted': True}


class Relay:
    def __init__(self):
        self.calls = []

    def call_sync(self, slot, session, tool, args):
        self.calls.append((slot, session, tool, args))
        return {'ok': True, 'result': {'revision': 1}}


class DispatcherIsolationTests(unittest.TestCase):
    def test_addon_bridge_refuses_unmarked_and_unknown_api_before_any_actor_call(self):
        actor, relay = LegacyActor(), Relay()
        bridge = BridgeServer(actor, None, 'house', relay=relay, slot='codex')
        self.addCleanup(bridge.stop)
        for api in (None, 'legacy', 'addon-2', '', 1):
            for tool in ('read_project', 'apply_operation', 'acquire_writer', 'release_writer',
                         'inspect_module', 'operation_status', 'validate_draft', 'read_owner_requests'):
                frame = {'id': 7, 'tool': tool, 'args': {}}
                if api is not None:
                    frame['api'] = api
                reply = bridge.dispatch(frame)
                self.assertFalse(reply['ok'], (api, tool))
                self.assertEqual(reply['error']['code'], 'INVALID_REQUEST')
        self.assertEqual(actor.calls, [])
        self.assertEqual(relay.calls, [])

    def test_addon_marker_cannot_smuggle_legacy_tool_and_slot_comes_from_server(self):
        actor, relay = LegacyActor(), Relay()
        bridge = BridgeServer(actor, None, 'house', relay=relay, slot='codex')
        self.addCleanup(bridge.stop)
        for tool in ('read_project', 'apply_operation', 'acquire_writer', 'read_guide'):
            reply = bridge.dispatch({'id': 1, 'api': 'addon-1', 'session': 'a' * 32, 'tool': tool, 'args': {}})
            self.assertFalse(reply['ok'])
            self.assertEqual(reply['error']['code'], 'INVALID_REQUEST')
        self.assertEqual(actor.calls, [])
        self.assertEqual(relay.calls, [])
        reply = bridge.dispatch({'id': 2, 'api': 'addon-1', 'session': 'a' * 32,
                                 'slot': 'claude-code', 'tool': 'describe_scene', 'args': {}})
        self.assertTrue(reply['ok'])
        self.assertEqual(relay.calls, [('codex', 'a' * 32, 'describe_scene', {})])
        self.assertEqual(actor.calls, [])

    def test_separate_legacy_server_still_calls_its_actor_but_rejects_addon(self):
        actor = LegacyActor()
        bridge = BridgeServer(actor, None, 'house')
        self.addCleanup(bridge.stop)
        self.assertTrue(bridge.dispatch({'id': 1, 'tool': 'read_project', 'args': {}})['ok'])
        self.assertEqual(actor.calls, [('read_project', {})])
        reply = bridge.dispatch({'id': 2, 'api': 'addon-1', 'session': 'a' * 32,
                                 'tool': 'describe_scene', 'args': {}})
        self.assertEqual(reply['error']['code'], 'INVALID_REQUEST')
        self.assertEqual(actor.calls, [('read_project', {})])


def current_windows_sid():
    import win32api, win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()


def make_broad(path):
    if os.name == 'nt':
        import win32security, ntsecuritycon
        acl = win32security.ACL()
        acl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS,
                               win32security.CreateWellKnownSid(win32security.WinWorldSid))
        win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)
    else:
        os.chmod(path, 0o777 if path.is_dir() else 0o666)


def assert_private(test, path, directory=False):
    if os.name == 'nt':
        import win32security, ntsecuritycon
        descriptor = win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION)
        owner = current_windows_sid()
        test.assertEqual(descriptor.GetSecurityDescriptorOwner(), owner)
        test.assertTrue(descriptor.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED)
        acl = descriptor.GetSecurityDescriptorDacl()
        test.assertIsNotNone(acl)
        test.assertEqual(acl.GetAceCount(), 1, 'No inherited/broad-principal ACE may expose a credential')
        header, mask, sid = acl.GetAce(0)
        test.assertEqual(header[0], win32security.ACCESS_ALLOWED_ACE_TYPE)
        test.assertEqual(header[1], 3 if directory else 0)
        test.assertEqual(mask, ntsecuritycon.FILE_ALL_ACCESS)
        test.assertEqual(sid, owner)
    else:
        info = os.lstat(path)
        test.assertEqual(info.st_uid, os.geteuid())
        test.assertEqual(stat.S_IMODE(info.st_mode), 0o700 if directory else 0o600)


class DiscoveryPermissionTests(unittest.TestCase):
    def demo(self):
        demo = LocalDemo(project='isolation', port=8765, owner_secret='s' * 40,
                         editor_origins=('http://localhost:5175',), clients=('codex',), no_record=True)
        self.addCleanup(demo.stop)
        return demo

    def test_permissive_umask_cannot_expose_folder_temp_or_published_credential(self):
        demo = self.demo()
        original_replace = os.replace
        checked = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            def checked_replace(source, destination):
                assert_private(self, root, directory=True)
                assert_private(self, root / 'private', directory=True)
                assert_private(self, Path(source))
                checked.append(json.loads(Path(source).read_text())['slot'])
                return original_replace(source, destination)
            previous = os.umask(0)
            try:
                with patch('service.local_demo.os.replace', side_effect=checked_replace):
                    demo.write_client_files(root)
            finally:
                os.umask(previous)
            path = root / 'private/bridge-codex.json'
            assert_private(self, path)
            self.assertEqual(json.loads(path.read_text())['secret'], demo.bridges['codex'].secret)
            self.assertEqual(checked, ['codex'])

    def test_broad_existing_permissions_are_removed_before_new_secret_is_published(self):
        demo = self.demo()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            private = root / 'private'
            private.mkdir(parents=True)
            path = private / 'bridge-codex.json'
            path.write_text('{"old":"synthetic"}')
            for item in (root, private, path):
                make_broad(item)
            demo.write_client_files(root)
            assert_private(self, root, directory=True)
            assert_private(self, private, directory=True)
            assert_private(self, path)
            self.assertEqual(json.loads(path.read_text())['slot'], 'codex')

    def test_permission_failure_never_publishes_or_writes_credentials(self):
        demo = self.demo()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            with patch('service.local_demo._secure_private_path', side_effect=PermissionError('denied'), create=True):
                with self.assertRaises(PermissionError):
                    demo.write_client_files(root)
            self.assertFalse((root / 'private/bridge-codex.json').exists())
            self.assertFalse((root / 'manifest.json').exists())
            for file in root.rglob('*'):
                if file.is_file():
                    self.assertNotIn(demo.bridges['codex'].secret, file.read_text())


class WireIsolationTests(unittest.TestCase):
    def test_real_addon_credentials_cannot_read_or_mutate_legacy_actor(self):
        demo = LocalDemo(project='wire-isolation', port=8765, owner_secret='s' * 40,
            editor_origins=('http://localhost:5175',), clients=('codex', 'claude-code'), no_record=True)
        demo.start_bridges()
        self.addCleanup(demo.stop)
        actor = demo.host.actor('local', 'wire-isolation')
        before = actor._state
        for bridge in demo.bridges.values():
            with socket.create_connection(bridge.address, timeout=3) as connection:
                with connection.makefile('rb') as reader:
                    for api in (None, 'unknown', 'addon-1'):
                        for tool in ('read_project', 'apply_operation', 'acquire_writer', 'release_writer',
                                     'inspect_module', 'operation_status', 'validate_draft', 'read_owner_requests'):
                            frame = {'secret': bridge.secret, 'id': 1, 'session': 'a' * 32, 'tool': tool, 'args': {}}
                            if api is not None:
                                frame['api'] = api
                            connection.sendall((json.dumps(frame) + '\n').encode())
                            reply = json.loads(reader.readline())
                            self.assertFalse(reply['ok'], (api, tool))
                            self.assertEqual(reply['error']['code'], 'INVALID_REQUEST')
                            self.assertNotIn(bridge.secret, json.dumps(reply))
            with socket.create_connection(bridge.address, timeout=3) as connection:
                connection.sendall((json.dumps({'secret': 'wrong', 'tool': 'read_project', 'args': {}}) + '\n').encode())
                with connection.makefile('rb') as reader:
                    self.assertEqual(reader.readline(), b'')
        self.assertIs(actor._state, before)
        self.assertEqual(actor._state.project.project_revision, 0)
