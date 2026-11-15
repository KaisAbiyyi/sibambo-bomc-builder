"""SE-03 (D16 S2): stdio MCP front for local clients (Claude Code / Codex on the owner's machine).

Holds no draft: every tool call is forwarded through ``service.bridge`` to the one canonical
actor. Launch with the environment the trusted launcher printed (``SIBAMBO_BRIDGE_*``).
"""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

from mcp.server import MCPServer

from service.bridge import ENV_PROJECT, bridge_call
from service.mcp_http import INSTRUCTIONS, as_result, register_tools


def build_stdio_server(env=os.environ) -> MCPServer:
    if env.get('SIBAMBO_LOCAL_RUN_ROOT') and env.get('SIBAMBO_CLIENT_SLOT'):
        from service.addon_tools import INSTRUCTIONS_ADDON, as_addon_result, register_addon_tools
        from service.bridge import bridge_call_addon
        session = uuid4().hex
        server = MCPServer('sibambo', instructions=INSTRUCTIONS_ADDON)
        async def run_addon(name: str, args: dict):
            reply = await asyncio.to_thread(bridge_call_addon, name, args, env['SIBAMBO_LOCAL_RUN_ROOT'],
                                            env['SIBAMBO_CLIENT_SLOT'], session)
            return as_addon_result(reply)
        register_addon_tools(server, run_addon)
        return server
    server = MCPServer("sibambo-local-bridge", instructions=INSTRUCTIONS)
    project = env.get(ENV_PROJECT, "")

    async def run(name: str, args: dict):
        reply = await asyncio.to_thread(bridge_call, name, args, env=env)
        if reply.get("ok"):
            return as_result({"ok": True, **reply["result"]}, is_error=False)
        return as_result({"ok": False, "projectId": project, "error": reply.get("error", {})}, is_error=True)

    register_tools(server, run)
    return server


def main() -> None:                              # pragma: no cover - process entry point
    build_stdio_server().run("stdio")


if __name__ == "__main__":                       # pragma: no cover
    main()
