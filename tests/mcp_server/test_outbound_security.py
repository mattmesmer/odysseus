"""Contract tests for outbound MCP security gates (Issue #2521).

These define the security invariants. Implementation must make these pass.
"""

import pytest
import time
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

# Import after path setup
from src.mcp_server.security import (
    check_rate_limit,
    emit_audit,
    get_audit_log,
    is_tool_allowed,
    confine_path,
    ALLOWED_TOOL_SPECS,
    ALLOWED_BUNDLES,
    load_allowlist_from_registry,
    JSONRPCError,
)
from src.mcp_server.tools_registry import (
    initialize_registry,
    get_tool,
    export_mcp_tools_list,
    register_bundle,
    register_tool,
    ToolSpec,
    BundleSpec,
)
from src.mcp_server.transport.stdio import handle_tools_call, handle_tools_list
from src.mcp_server.transport.streamable_http import handle_mcp_request, extract_auth


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state():
    """Reset module state between tests."""
    # Clear rate limit buckets
    from src.mcp_server.security import _rate_buckets, _audit_log
    _rate_buckets.clear()
    _audit_log.clear()
    
    # Clear registries
    from src.mcp_server.tools_registry import _TOOL_REGISTRY, _BUNDLE_REGISTRY, _BUNDLE_TOOLS
    _TOOL_REGISTRY.clear()
    _BUNDLE_REGISTRY.clear()
    _BUNDLE_TOOLS.clear()
    
    yield
    
    _rate_buckets.clear()
    _audit_log.clear()
    _TOOL_REGISTRY.clear()
    _BUNDLE_REGISTRY.clear()
    _BUNDLE_TOOLS.clear()


@pytest.fixture
def sample_bundle():
    """Register a test bundle with tools."""
    register_bundle(BundleSpec(
        name="test_bundle",
        description="Test bundle",
        tools=frozenset(["test_tool", "file_tool"]),
    ))
    register_tool(ToolSpec(
        name="test_tool",
        description="A test tool",
        input_schema={"type": "object", "properties": {"arg1": {"type": "string"}, "api_key": {"type": "string"}, "normal": {"type": "string"}}},
        allowed_args=frozenset(["arg1", "api_key", "normal"]),
        allowed_env=frozenset(),
    ))
    register_tool(ToolSpec(
        name="file_tool",
        description="A file tool",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        allowed_args=frozenset(["path"]),
        allowed_env=frozenset(),
    ))
    initialize_registry(["test_bundle"])
    # Load allowlist from registry
    load_allowlist_from_registry()


# ──────────────────────────────────────────────────────────────
# Test: Unknown tool rejected (allowlist gate)
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_tool_rejected(sample_bundle):
    """Calling an unregistered tool returns 403/MethodNotFound."""
    async def dummy_executor(tool, args, token):
        return {"ok": True}
    
    # Direct handler call (stdio)
    with pytest.raises(JSONRPCError) as exc:
        await handle_tools_call(
            {"name": "unknown_tool", "arguments": {}, "id": 1},
            "test_token",
            ["test_bundle"],
            dummy_executor,
        )
    assert exc.value.code == -32601  # Method not found
    
    # HTTP handler - test that unknown tool returns error response
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request
    
    async def dummy_executor_http(tool, args, token):
        return {"ok": True}
    
    request = make_mocked_request(
        "POST", "/mcp/ody",
        headers={"Authorization": "Bearer ody_mcp_test"},
    )
    # Set the json body
    request._body = b'{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "unknown_tool", "arguments": {}}, "id": 1}'
    
    with patch("src.mcp_server.transport.streamable_http.extract_auth") as mock_auth:
        mock_auth.return_value = MagicMock(token_id="test", enabled_bundles=["test_bundle"], user_id=None)
        response = await handle_mcp_request(request, dummy_executor_http)
        assert response.status == 400


# ──────────────────────────────────────────────────────────────
# Test: Path containment on file tools
# ──────────────────────────────────────────────────────────────

def test_path_containment_on_file_tools():
    """Path escape attempts are rejected."""
    # Valid path under user root
    assert confine_path("/workspace/user123", "/workspace/user123/file.txt") == "/workspace/user123/file.txt"
    
    # Escape attempt
    with pytest.raises(ValueError, match="Path escape attempt"):
        confine_path("/workspace/user123", "/workspace/user123/../../etc/passwd")
    
    with pytest.raises(ValueError, match="Path escape attempt"):
        confine_path("/workspace/user123", "/etc/passwd")


@pytest.mark.asyncio
async def test_file_tool_path_escape_rejected_in_executor(sample_bundle):
    """file_tool with escape path returns error response from executor."""
    async def dummy_executor(tool, args, token):
        # Simulate executor calling confine_path and catching the error
        if tool == "file_tool" and "path" in args:
            try:
                confine_path("/workspace/user123", args["path"])
            except ValueError as e:
                return {"error": str(e)}
        return {"ok": True}
    
    result = await handle_tools_call(
        {"name": "file_tool", "arguments": {"path": "../../../etc/passwd"}, "id": 1},
        "test_token",
        ["test_bundle"],
        dummy_executor,
    )
    # Should return error response, not raise
    assert result["isError"] is True
    assert "Path escape attempt" in result["content"][0]["text"]


# ──────────────────────────────────────────────────────────────
# Test: Rate limit enforced
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_enforced(sample_bundle):
    """61st request in 60s window raises rate limit error (JSONRPCError)."""
    async def dummy_executor(tool, args, token):
        return {"ok": True}
    
    token = "rate_test_token"
    # First 60 should succeed (bucket starts with 60 tokens)
    for i in range(60):
        result = await handle_tools_call(
            {"name": "test_tool", "arguments": {"arg1": f"val{i}"}, "id": i},
            token,
            ["test_bundle"],
            dummy_executor,
        )
        assert result["isError"] is False, f"Request {i} should succeed"
    
    # 61st should fail - bucket exhausted, raises JSONRPCError
    with pytest.raises(JSONRPCError) as exc:
        await handle_tools_call(
            {"name": "test_tool", "arguments": {"arg1": "val61"}, "id": 61},
            token,
            ["test_bundle"],
            dummy_executor,
        )
    assert exc.value.code == -32000  # Rate limit exceeded


# ──────────────────────────────────────────────────────────────
# Test: Audit log emitted with required fields
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_log_emitted(sample_bundle):
    """Audit entry contains caller_token_id, tool, args (redacted), exit_code, latency_ms, user_id."""
    async def dummy_executor(tool, args, token):
        await asyncio.sleep(0.001)  # ensure measurable latency
        return {"ok": True}
    
    await handle_tools_call(
        {"name": "test_tool", "arguments": {"arg1": "secret_value"}, "id": 1},
        "audit_token_123",
        ["test_bundle"],
        dummy_executor,
    )
    
    log = get_audit_log(limit=1)
    assert len(log) == 1
    entry = log[0]
    
    assert entry.caller_token_id == "audit_token_123"
    assert entry.tool == "test_tool"
    assert entry.args == {"arg1": "secret_value"}  # not redacted - not sensitive key
    assert entry.exit_code == 200
    assert entry.latency_ms > 0
    assert entry.user_id is None


@pytest.mark.asyncio
async def test_audit_log_redacts_secrets(sample_bundle):
    """Sensitive argument keys are redacted in audit log."""
    async def dummy_executor(tool, args, token):
        return {"ok": True}
    
    await handle_tools_call(
        {"name": "test_tool", "arguments": {"api_key": "sk-secret", "normal": "value"}, "id": 1},
        "audit_token_456",
        ["test_bundle"],
        dummy_executor,
    )
    
    log = get_audit_log(limit=1)
    entry = log[0]
    assert entry.args["api_key"] == "***REDACTED***"
    assert entry.args["normal"] == "value"


# ──────────────────────────────────────────────────────────────
# Additional: Arg allowlist enforcement
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disallowed_args_rejected(sample_bundle):
    """Arguments not in allowed_args are rejected."""
    async def dummy_executor(tool, args, token):
        return {"ok": True}
    
    with pytest.raises(JSONRPCError) as exc:
        await handle_tools_call(
            {"name": "test_tool", "arguments": {"arg1": "ok", "evil_arg": "nope"}, "id": 1},
            "test_token",
            ["test_bundle"],
            dummy_executor,
        )
    assert exc.value.code == -32001


# ──────────────────────────────────────────────────────────────
# Additional: Bundle filtering (only enabled bundles exposed)
# ──────────────────────────────────────────────────────────────

def test_bundle_filtering():
    """Only enabled bundles tools appear in tools/list."""
    register_bundle(BundleSpec(name="bundle_a", description="Bundle A", tools=frozenset(["tool_a"])))
    register_tool(ToolSpec(name="tool_a", description="A", input_schema={}))
    register_bundle(BundleSpec(name="bundle_b", description="Bundle B", tools=frozenset(["tool_b"])))
    register_tool(ToolSpec(name="tool_b", description="B", input_schema={}))
    
    initialize_registry(["bundle_a"])  # only enable bundle_a
    
    tools = export_mcp_tools_list(["bundle_a"])
    names = [t["name"] for t in tools]
    assert "tool_a" in names
    assert "tool_b" not in names