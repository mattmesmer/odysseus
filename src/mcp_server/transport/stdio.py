"""Stdio transport for outbound MCP server (Issue #2521).

Implements MCP stdio transport per spec:
https://spec.modelcontextprotocol.io/specification/2024-11-05/basic/transports/#stdio

Reuses patterns from client-side stdio in src/mcp/client.py (#803).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Callable, Awaitable

from ..security import (
    check_rate_limit,
    emit_audit,
    is_tool_allowed,
    confine_path,
    DATA_ROOT,
    JSONRPCError,
)
from ..tools_registry import (
    export_mcp_tools_list,
    export_mcp_tool_schema,
    get_tool,
    initialize_registry,
    list_bundles,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# JSON-RPC 2.0 base
# ──────────────────────────────────────────────────────────────

JSONRPC_VERSION = "2.0"


def rpc_error(code: int, message: str, data: Any = None) -> Dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "error": {"code": code, "message": message, "data": data}, "id": None}


def rpc_result(result: Any, id: Any) -> Dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "result": result, "id": id}


# ──────────────────────────────────────────────────────────────
# MCP method handlers
# ──────────────────────────────────────────────────────────────

async def handle_initialize(params: Dict[str, Any], token_id: str) -> Dict[str, Any]:
    """MCP initialize - returns server capabilities."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {"listChanged": False},
        },
        "serverInfo": {"name": "odysseus-mcp-server", "version": "0.1.0"},
    }


async def handle_tools_list(params: Dict[str, Any], token_id: str, enabled_bundles: List[str]) -> Dict[str, Any]:
    """MCP tools/list - returns all tools from enabled bundles."""
    # Rate limit
    if not check_rate_limit(token_id):
        raise JSONRPCError(-32000, "Rate limit exceeded")
    
    tools = export_mcp_tools_list(enabled_bundles)
    return {"tools": tools}


async def handle_tools_call(params: Dict[str, Any], token_id: str, enabled_bundles: List[str], 
                           tool_executor: Callable[[str, Dict[str, Any], str], Awaitable[Any]]) -> Dict[str, Any]:
    """MCP tools/call - executes a tool with security gates."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    req_id = params.get("id")
    
    if not tool_name:
        raise JSONRPCError(-32602, "Missing tool name")
    
    # Security gate: tool must be in enabled bundles
    tool_spec = get_tool(tool_name)
    if not tool_spec:
        raise JSONRPCError(-32601, f"Tool not found: {tool_name}")
    
    # Security gate: arg allowlist
    if not is_tool_allowed(tool_name, arguments, {}):
        emit_audit(token_id, tool_name, arguments, 403, 0.0)
        raise JSONRPCError(-32001, f"Tool not allowed or invalid arguments: {tool_name}")
    
    # Execute with rate limit check inside try block
    start = time.monotonic()
    try:
        # Rate limit check
        if not check_rate_limit(token_id):
            raise JSONRPCError(-32000, "Rate limit exceeded")
        
        result = await tool_executor(tool_name, arguments, token_id)
        
        # Check if executor returned an error dict
        if isinstance(result, dict) and result.get("error"):
            latency_ms = (time.monotonic() - start) * 1000
            emit_audit(token_id, tool_name, arguments, 400, latency_ms)
            return {"content": [{"type": "text", "text": result["error"]}], "isError": True}
        
        latency_ms = (time.monotonic() - start) * 1000
        emit_audit(token_id, tool_name, arguments, 200, latency_ms)
        return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": False}
    except JSONRPCError as e:
        latency_ms = (time.monotonic() - start) * 1000
        emit_audit(token_id, tool_name, arguments, e.code if e.code < 0 else 500, latency_ms)
        raise
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        emit_audit(token_id, tool_name, arguments, 500, latency_ms)
        logger.exception("Tool execution failed: %s", tool_name)
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}


# ──────────────────────────────────────────────────────────────
# Stdio server loop
# ──────────────────────────────────────────────────────────────

async def run_stdio_server(
    enabled_bundles: List[str],
    token_id: str,
    tool_executor: Callable[[str, Dict[str, Any], str], Awaitable[Any]],
) -> None:
    """Run MCP server over stdio.
    
    Reads newline-delimited JSON-RPC requests from stdin,
    writes responses to stdout.
    """
    # Initialize registry
    initialize_registry(enabled_bundles)
    
    # Load allowlist from registry
    from ..security import load_allowlist_from_registry
    load_allowlist_from_registry()
    
    # Read stdin line by line
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)
    
    writer = sys.stdout
    
    logger.info("Odysseus MCP stdio server started (token=%s, bundles=%s)", token_id, enabled_bundles)
    
    while True:
        line = await reader.readline()
        if not line:
            break
        
        line = line.decode().strip()
        if not line:
            continue
        
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            response = rpc_error(-32700, "Parse error")
            writer.write(json.dumps(response) + "\n")
            writer.flush()
            continue
        
        # Validate JSON-RPC
        if not isinstance(req, dict) or req.get("jsonrpc") != JSONRPC_VERSION:
            response = rpc_error(-32600, "Invalid Request")
            writer.write(json.dumps(response) + "\n")
            writer.flush()
            continue
        
        method = req.get("method")
        params = req.get("params", {})
        req_id = req.get("id")
        
        try:
            if method == "initialize":
                result = await handle_initialize(params, token_id)
            elif method == "tools/list":
                result = await handle_tools_list(params, token_id, enabled_bundles)
            elif method == "tools/call":
                result = await handle_tools_call(params, token_id, enabled_bundles, tool_executor)
            elif method == "notifications/initialized":
                continue
            else:
                raise JSONRPCError(-32601, f"Method not found: {method}")
            
            response = rpc_result(result, req_id)
        
        except JSONRPCError as e:
            response = rpc_error(e.code, e.message, e.data)
            if req_id is not None:
                response["id"] = req_id
        except Exception as e:
            logger.exception("Unexpected error handling %s", method)
            response = rpc_error(-32603, "Internal error", str(e))
            if req_id is not None:
                response["id"] = req_id
        
        writer.write(json.dumps(response) + "\n")
        writer.flush()


# ──────────────────────────────────────────────────────────────
# Entrypoint helper
# ──────────────────────────────────────────────────────────────

def get_token_from_env() -> str:
    token = os.environ.get("ODY_MCP_TOKEN")
    if not token:
        raise RuntimeError("ODY_MCP_TOKEN environment variable required")
    return token


def get_enabled_bundles_from_env() -> List[str]:
    bundles_str = os.environ.get("ODY_MCP_BUNDLES", "memory,notes,research")
    return [b.strip() for b in bundles_str.split(",") if b.strip()]


async def main(
    tool_executor: Callable[[str, Dict[str, Any], str], Awaitable[Any]],
    token_id: Optional[str] = None,
    enabled_bundles: Optional[List[str]] = None,
) -> None:
    token_id = token_id or get_token_from_env()
    enabled_bundles = enabled_bundles or get_enabled_bundles_from_env()
    
    await run_stdio_server(enabled_bundles, token_id, tool_executor)


if __name__ == "__main__":
    async def dummy_executor(tool: str, args: dict, token: str):
        return {"ok": True, "tool": tool, "args": args}
    
    asyncio.run(main(dummy_executor))