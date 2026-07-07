"""Unified outbound MCP server entrypoint (Issue #2521).

Wires together:
- Transport (stdio / Streamable HTTP)
- Security gates
- Tool registry
- Actual tool implementations (delegates to in-app tool system)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Callable, Awaitable

from .security import check_rate_limit, emit_audit, is_tool_allowed, confine_path, DATA_ROOT
from .tools_registry import (
    initialize_registry,
    get_tool,
    list_bundles,
    export_mcp_tools_list,
)
from .transport.stdio import run_stdio_server, get_token_from_env as get_stdio_token, get_enabled_bundles_from_env as get_stdio_bundles
from .transport.streamable_http import run_http_server, get_enabled_bundles_from_env as get_http_bundles

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Tool executor - bridges to Odysseus in-app tool system
# ──────────────────────────────────────────────────────────────

class ToolExecutor:
    """Executes tools by delegating to Odysseus's internal tool system.
    
    In production, this calls the same tool functions the in-app agent uses.
    """
    
    def __init__(self, app_tool_dispatcher: Callable[[str, Dict[str, Any], str], Awaitable[Any]]):
        self._dispatch = app_tool_dispatcher
    
    async def execute(self, tool_name: str, arguments: Dict[str, Any], token_id: str) -> Any:
        # Path containment for file tools
        if tool_name in ("file_search", "file_read", "file_write", "file_delete"):
            user_root = f"{DATA_ROOT}/{token_id}"  # per-token isolation
            # Arguments with paths get confined
            for key in ("path", "root", "directory"):
                if key in arguments:
                    arguments[key] = confine_path(user_root, arguments[key])
        
        # Delegate to Odysseus tool system
        return await self._dispatch(tool_name, arguments, token_id)


# ──────────────────────────────────────────────────────────────
# Built-in tool implementations (for tools not in app system)
# ──────────────────────────────────────────────────────────────

async def execute_memory_search(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_memory import manage_memory
    return await manage_memory(action="search", query=args["query"], limit=args.get("limit", 10))

async def execute_memory_store(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_memory import manage_memory
    return await manage_memory(action="add", content=args["content"], tags=args.get("tags", []))

async def execute_memory_delete(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_memory import manage_memory
    return await manage_memory(action="delete", memory_id=args["memory_id"])

async def execute_memory_list(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_memory import manage_memory
    return await manage_memory(action="list", limit=args.get("limit", 50))

async def execute_notes_create(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_notes import manage_notes
    return await manage_notes(action="create", title=args["title"], content=args["content"], tags=args.get("tags", []))

async def execute_notes_read(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_notes import manage_notes
    return await manage_notes(action="read", note_id=args["note_id"])

async def execute_notes_update(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_notes import manage_notes
    return await manage_notes(action="update", note_id=args["note_id"], title=args.get("title"), content=args.get("content"), tags=args.get("tags"))

async def execute_notes_delete(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_notes import manage_notes
    return await manage_notes(action="delete", note_id=args["note_id"])

async def execute_notes_list(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_notes import manage_notes
    return await manage_notes(action="list", limit=args.get("limit", 50), tag=args.get("tag"))

async def execute_research_start(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_research import manage_research
    return await manage_research(action="start", topic=args["topic"], depth=args.get("depth", "standard"))

async def execute_research_status(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_research import manage_research
    return await manage_research(action="status", task_id=args["task_id"])

async def execute_research_read(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_research import manage_research
    return await manage_research(action="read", task_id=args["task_id"])

async def execute_skill_load(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_skills import manage_skills
    return await manage_skills(action="view", name=args["name"])

async def execute_skill_save(args: Dict[str, Any], token_id: str) -> Any:
    from ..tools.manage_skills import manage_skills
    return await manage_skills(action="add", name=args["name"], content=args["content"])


# Tool name -> executor function
BUILTIN_EXECUTORS: Dict[str, Callable[[Dict[str, Any], str], Awaitable[Any]]] = {
    "memory_search": execute_memory_search,
    "memory_store": execute_memory_store,
    "memory_delete": execute_memory_delete,
    "memory_list": execute_memory_list,
    "notes_create": execute_notes_create,
    "notes_read": execute_notes_read,
    "notes_update": execute_notes_update,
    "notes_delete": execute_notes_delete,
    "notes_list": execute_notes_list,
    "research_start": execute_research_start,
    "research_status": execute_research_status,
    "research_read": execute_research_read,
    "skill_load": execute_skill_load,
    "skill_save": execute_skill_save,
}


# ──────────────────────────────────────────────────────────────
# Unified dispatcher
# ──────────────────────────────────────────────────────────────

async def unified_executor(
    tool_name: str,
    arguments: Dict[str, Any],
    token_id: str,
    app_dispatcher: Optional[Callable[[str, Dict[str, Any], str], Awaitable[Any]]] = None,
) -> Any:
    """Dispatch to builtin or app tool system."""
    # Try builtin first
    if tool_name in BUILTIN_EXECUTORS:
        return await BUILTIN_EXECUTORS[tool_name](arguments, token_id)
    
    # Fall back to app dispatcher (for shell, web_search, etc. - but those are blocked by allowlist)
    if app_dispatcher:
        return await app_dispatcher(tool_name, arguments, token_id)
    
    raise ValueError(f"No executor for tool: {tool_name}")


# ──────────────────────────────────────────────────────────────
# Server runners
# ──────────────────────────────────────────────────────────────

async def run_stdio(
    enabled_bundles: Optional[List[str]] = None,
    token_id: Optional[str] = None,
    app_dispatcher: Optional[Callable] = None,
) -> None:
    """Run stdio transport."""
    token_id = token_id or get_stdio_token()
    enabled_bundles = enabled_bundles or get_stdio_bundles()
    
    async def executor(tool: str, args: dict, tok: str):
        return await unified_executor(tool, args, tok, app_dispatcher)
    
    await run_stdio_server(enabled_bundles, token_id, executor)


async def run_http(
    enabled_bundles: Optional[List[str]] = None,
    host: str = "127.0.0.1",
    port: int = 7000,
    app_dispatcher: Optional[Callable] = None,
) -> None:
    """Run Streamable HTTP transport."""
    enabled_bundles = enabled_bundles or get_http_bundles()
    
    async def executor(tool: str, args: dict, tok: str):
        return await unified_executor(tool, args, tok, app_dispatcher)
    
    await run_http_server(enabled_bundles, executor, host, port)


# ──────────────────────────────────────────────────────────────
# CLI entrypoint
# ──────────────────────────────────────────────────────────────

import argparse
import os

def main() -> None:
    parser = argparse.ArgumentParser(description="Odysseus Outbound MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7000)
    parser.add_argument("--bundles", help="Comma-separated bundle names")
    parser.add_argument("--token", help="MCP token (overrides ODY_MCP_TOKEN)")
    args = parser.parse_args()
    
    if args.token:
        os.environ["ODY_MCP_TOKEN"] = args.token
    if args.bundles:
        os.environ["ODY_MCP_BUNDLES"] = args.bundles
    
    enabled_bundles = args.bundles.split(",") if args.bundles else None
    
    if args.transport == "stdio":
        asyncio.run(run_stdio(enabled_bundles=enabled_bundles, token_id=args.token))
    else:
        asyncio.run(run_http(enabled_bundles=enabled_bundles, host=args.host, port=args.port))


if __name__ == "__main__":
    main()