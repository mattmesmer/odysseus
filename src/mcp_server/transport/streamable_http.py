"""Streamable HTTP transport for outbound MCP server (Issue #2521).

Implements MCP Streamable HTTP transport per spec:
https://spec.modelcontextprotocol.io/specification/2024-11-05/basic/transports/#streamable-http

Reuses client-side Streamable HTTP patterns from src/mcp/client.py (#803).
Mounts at /mcp/ody on port 7000 (configurable).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Callable, Awaitable
from dataclasses import dataclass

from aiohttp import web
from aiohttp.web import Request, Response, StreamResponse

from ..security import (
    check_rate_limit,
    emit_audit,
    is_tool_allowed,
    JSONRPCError,
)
from ..tools_registry import (
    export_mcp_tools_list,
    export_mcp_tool_schema,
    get_tool,
    initialize_registry,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# JSON-RPC 2.0 base (shared with stdio)
# ──────────────────────────────────────────────────────────────

JSONRPC_VERSION = "2.0"


def rpc_error(code: int, message: str, data: Any = None, id: Any = None) -> Dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "error": {"code": code, "message": message, "data": data}, "id": id}


def rpc_result(result: Any, id: Any) -> Dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "result": result, "id": id}


# ──────────────────────────────────────────────────────────────
# Auth & token extraction
# ──────────────────────────────────────────────────────────────

@dataclass
class AuthContext:
    token_id: str
    enabled_bundles: List[str]
    user_id: Optional[str] = None


async def extract_auth(request: Request) -> AuthContext:
    """Extract and validate Bearer token from Authorization header.
    
    Expected format: Authorization: Bearer ody_mcp_xxxxxxxxxxxx
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise JSONRPCError(-32000, "Missing or invalid Authorization header")
    
    token = auth_header[7:].strip()  # strip "Bearer "
    if not token.startswith("ody_mcp_"):
        raise JSONRPCError(-32000, "Invalid token format")
    
    # TODO: Validate token against token store, get associated bundles + user_id
    # For now, parse bundles from token or use default
    # Format could be: ody_mcp_<token_id>_<bundles> or lookup in DB
    token_id = token  # placeholder
    enabled_bundles = ["memory", "notes", "research"]  # placeholder
    
    return AuthContext(token_id=token_id, enabled_bundles=enabled_bundles)


# ──────────────────────────────────────────────────────────────
# MCP method handlers (same logic as stdio)
# ──────────────────────────────────────────────────────────────

async def handle_initialize(params: Dict[str, Any], auth: AuthContext) -> Dict[str, Any]:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {"listChanged": False},
        },
        "serverInfo": {"name": "odysseus-mcp-server", "version": "0.1.0"},
    }


async def handle_tools_list(params: Dict[str, Any], auth: AuthContext) -> Dict[str, Any]:
    if not check_rate_limit(auth.token_id):
        raise JSONRPCError(-32000, "Rate limit exceeded")
    
    tools = export_mcp_tools_list(auth.enabled_bundles)
    return {"tools": tools}


async def handle_tools_call(params: Dict[str, Any], auth: AuthContext, 
                           tool_executor: Callable[[str, Dict[str, Any], str], Awaitable[Any]]) -> Dict[str, Any]:
    if not check_rate_limit(auth.token_id):
        raise JSONRPCError(-32000, "Rate limit exceeded")
    
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    
    if not tool_name:
        raise JSONRPCError(-32602, "Missing tool name")
    
    tool_spec = get_tool(tool_name)
    if not tool_spec:
        raise JSONRPCError(-32601, f"Tool not found: {tool_name}")
    
    if not is_tool_allowed(tool_name, arguments, {}):
        emit_audit(auth.token_id, tool_name, arguments, 403, 0.0, auth.user_id)
        raise JSONRPCError(-32001, f"Tool not allowed or invalid arguments: {tool_name}")
    
    start = time.monotonic()
    try:
        result = await tool_executor(tool_name, arguments, auth.token_id)
        latency_ms = (time.monotonic() - start) * 1000
        emit_audit(auth.token_id, tool_name, arguments, 200, latency_ms, auth.user_id)
        return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": False}
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        emit_audit(auth.token_id, tool_name, arguments, 500, latency_ms, auth.user_id)
        logger.exception("Tool execution failed: %s", tool_name)
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}


# ──────────────────────────────────────────────────────────────
# HTTP handlers
# ──────────────────────────────────────────────────────────────

async def handle_mcp_request(request: Request, tool_executor: Callable) -> Response:
    """Handle MCP requests over Streamable HTTP (POST /mcp/ody)."""
    auth = await extract_auth(request)
    
    # Read JSON-RPC request
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response(rpc_error(-32700, "Parse error"), status=400)
    
    if not isinstance(body, dict) or body.get("jsonrpc") != JSONRPC_VERSION:
        return web.json_response(rpc_error(-32600, "Invalid Request"), status=400)
    
    method = body.get("method")
    params = body.get("params", {})
    req_id = body.get("id")
    
    try:
        if method == "initialize":
            result = await handle_initialize(params, auth)
        elif method == "tools/list":
            result = await handle_tools_list(params, auth)
        elif method == "tools/call":
            result = await handle_tools_call(params, auth, tool_executor)
        elif method == "notifications/initialized":
            return Response(status=204)  # No response for notifications
        else:
            raise JSONRPCError(-32601, f"Method not found: {method}")
        
        return web.json_response(rpc_result(result, req_id))
    
    except JSONRPCError as e:
        return web.json_response(rpc_error(e.code, e.message, e.data, req_id), status=400)
    except Exception as e:
        logger.exception("Unexpected error handling %s", method)
        return web.json_response(rpc_error(-32603, "Internal error", str(e), req_id), status=500)


async def handle_sse_stream(request: Request, tool_executor: Callable) -> StreamResponse:
    """Handle SSE stream for long-running operations (GET /mcp/ody?stream=1).
    
    Optional: for tools that support streaming responses.
    """
    auth = await extract_auth(request)
    
    # For MVP, we don't implement streaming tool calls
    # Return 405 if client requests streaming
    return web.json_response(
        rpc_error(-32601, "Streaming not implemented"), 
        status=501
    )


# ──────────────────────────────────────────────────────────────
# Server setup
# ──────────────────────────────────────────────────────────────

async def create_app(
    enabled_bundles: List[str],
    tool_executor: Callable[[str, Dict[str, Any], str], Awaitable[Any]],
) -> web.Application:
    """Create aiohttp app with MCP routes."""
    initialize_registry(enabled_bundles)
    
    # Load allowlist from registry
    from ..security import load_allowlist_from_registry
    load_allowlist_from_registry()
    
    app = web.Application()
    
    # MCP endpoint
    app.router.add_post("/mcp/ody", lambda req: handle_mcp_request(req, tool_executor))
    app.router.add_get("/mcp/ody", lambda req: handle_sse_stream(req, tool_executor))
    
    # Health check
    async def health(request: Request) -> Response:
        return web.json_response({"status": "ok", "service": "odysseus-mcp-server"})
    app.router.add_get("/health", health)
    
    logger.info("Odysseus MCP HTTP server configured (bundles=%s)", enabled_bundles)
    return app


async def run_http_server(
    enabled_bundles: List[str],
    tool_executor: Callable[[str, Dict[str, Any], str], Awaitable[Any]],
    host: str = "127.0.0.1",
    port: int = 7000,
) -> None:
    """Run MCP server over Streamable HTTP."""
    app = await create_app(enabled_bundles, tool_executor)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    logger.info("Odysseus MCP HTTP server listening on http://%s:%d/mcp/ody", host, port)
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()


# ──────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────

import os

def get_enabled_bundles_from_env() -> List[str]:
    bundles_str = os.environ.get("ODY_MCP_BUNDLES", "memory,notes,research")
    return [b.strip() for b in bundles_str.split(",") if b.strip()]


async def main(
    tool_executor: Callable[[str, Dict[str, Any], str], Awaitable[Any]],
    enabled_bundles: Optional[List[str]] = None,
    host: str = "127.0.0.1",
    port: int = 7000,
) -> None:
    enabled_bundles = enabled_bundles or get_enabled_bundles_from_env()
    await run_http_server(enabled_bundles, tool_executor, host, port)


if __name__ == "__main__":
    async def dummy_executor(tool: str, args: dict, token: str):
        return {"ok": True, "tool": tool, "args": args}
    
    asyncio.run(main(dummy_executor))