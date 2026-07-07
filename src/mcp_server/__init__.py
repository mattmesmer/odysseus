"""Outbound MCP Server package (Issue #2521)."""

from .security import (
    check_rate_limit,
    emit_audit,
    is_tool_allowed,
    confine_path,
    get_audit_log,
    DATA_ROOT,
    SESSION_ROOT,
)
from .tools_registry import (
    ToolSpec,
    BundleSpec,
    register_bundle,
    register_tool,
    get_bundle,
    get_tool,
    list_bundles,
    list_tools,
    get_tools_for_bundle,
    export_mcp_tools_list,
    export_mcp_tool_schema,
    initialize_registry,
)
from .transport.stdio import run_stdio_server, main as stdio_main
from .transport.streamable_http import run_http_server, create_app, main as http_main
from .outbound import (
    ToolExecutor,
    unified_executor,
    run_stdio,
    run_http,
    BUILTIN_EXECUTORS,
    main as cli_main,
)

__all__ = [
    # security
    "check_rate_limit",
    "emit_audit",
    "is_tool_allowed",
    "confine_path",
    "get_audit_log",
    "DATA_ROOT",
    "SESSION_ROOT",
    # tools_registry
    "ToolSpec",
    "BundleSpec",
    "register_bundle",
    "register_tool",
    "get_bundle",
    "get_tool",
    "list_bundles",
    "list_tools",
    "get_tools_for_bundle",
    "export_mcp_tools_list",
    "export_mcp_tool_schema",
    "initialize_registry",
    # transport
    "run_stdio_server",
    "stdio_main",
    "run_http_server",
    "create_app",
    "http_main",
    # outbound
    "ToolExecutor",
    "unified_executor",
    "run_stdio",
    "run_http",
    "BUILTIN_EXECUTORS",
    "cli_main",
]

__version__ = "0.1.0"