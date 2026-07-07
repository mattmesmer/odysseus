"""Transport layer for outbound MCP server (Issue #2521)."""
from .stdio import run_stdio_server, main as stdio_main
from .streamable_http import run_http_server, create_app, main as http_main

__all__ = [
    "run_stdio_server",
    "stdio_main",
    "run_http_server",
    "create_app",
    "http_main",
]