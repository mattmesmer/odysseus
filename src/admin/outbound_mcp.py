"""Admin panel integration for Outbound MCP Server (Issue #2521).

Provides:
- /api/admin/outbound-mcp/config GET/PUT
- /api/admin/outbound-mcp/bundles GET
- /api/admin/outbound-mcp/tokens POST/GET/DELETE
- /api/admin/outbound-mcp/audit GET
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional

from aiohttp import web
from pydantic import BaseModel, Field

from ..config import (
    OUTBOUND_MCP_ENABLED,
    OUTBOUND_MCP_RATE_LIMIT,
    OUTBOUND_MCP_ALLOWED_BUNDLES,
    set_config,
)
from ..mcp_server.security import get_audit_log, _rate_buckets
from ..mcp_server.tools_registry import list_bundles, export_mcp_tools_list


# ──────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────

class OutboundMCPConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable outbound MCP server")
    rate_limit: int = Field(default=60, ge=1, le=1000, description="Requests per minute per token")
    allowed_bundles: List[str] = Field(default_factory=list, description="Enabled bundle names")
    http_port: int = Field(default=7000, ge=1024, le=65535, description="HTTP server port")
    http_host: str = Field(default="127.0.0.1", description="HTTP bind address")


class TokenCreate(BaseModel):
    bundles: List[str] = Field(default_factory=list, description="Bundles this token can access")
    user_id: Optional[str] = None
    description: str = Field(default="", description="Human-readable description")


class TokenResponse(BaseModel):
    token: str
    token_id: str
    bundles: List[str]
    user_id: Optional[str]
    description: str
    created_at: float
    last_used: Optional[float] = None


class AuditEntryResponse(BaseModel):
    timestamp: float
    caller_token_id: str
    tool: str
    args: Dict[str, Any]
    exit_code: int
    latency_ms: float
    user_id: Optional[str] = None


# ──────────────────────────────────────────────────────────────
# Token store (in-memory for MVP; replace with DB)
# ──────────────────────────────────────────────────────────────

class TokenStore:
    def __init__(self):
        self._tokens: Dict[str, Dict] = {}  # token_id -> token_data
    
    def create(self, bundles: List[str], user_id: Optional[str], description: str) -> TokenResponse:
        token_id = f"ody_mcp_{secrets.token_urlsafe(24)}"
        token = f"ody_mcp_{secrets.token_urlsafe(32)}"
        now = time.time()
        data = {
            "token": token,
            "token_id": token_id,
            "bundles": bundles,
            "user_id": user_id,
            "description": description,
            "created_at": now,
            "last_used": None,
        }
        self._tokens[token] = data
        return TokenResponse(**data)
    
    def list(self) -> List[TokenResponse]:
        return [TokenResponse(**v) for v in self._tokens.values()]
    
    def get(self, token: str) -> Optional[Dict]:
        return self._tokens.get(token)
    
    def delete(self, token: str) -> bool:
        if token in self._tokens:
            del self._tokens[token]
            return True
        return False
    
    def touch(self, token: str) -> None:
        if token in self._tokens:
            self._tokens[token]["last_used"] = time.time()


TOKEN_STORE = TokenStore()


# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────

async def get_config(request: web.Request) -> web.Response:
    config = OutboundMCPConfig(
        enabled=OUTBOUND_MCP_ENABLED,
        rate_limit=OUTBOUND_MCP_RATE_LIMIT,
        allowed_bundles=OUTBOUND_MCP_ALLOWED_BUNDLES,
        http_port=int(request.app.get("outbound_mcp_port", 7000)),
        http_host=request.app.get("outbound_mcp_host", "127.0.0.1"),
    )
    return web.json_response(config.model_dump())


async def update_config(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        config = OutboundMCPConfig(**data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    
    # Apply config
    set_config("OUTBOUND_MCP_ENABLED", config.enabled)
    set_config("OUTBOUND_MCP_RATE_LIMIT", config.rate_limit)
    set_config("OUTBOUND_MCP_ALLOWED_BUNDLES", config.allowed_bundles)
    
    # Store HTTP config in app for runtime
    request.app["outbound_mcp_port"] = config.http_port
    request.app["outbound_mcp_host"] = config.http_host
    
    # TODO: Restart server if running (signal or task)
    
    return web.json_response(config.model_dump())


async def list_bundles(request: web.Request) -> web.Response:
    bundles = list_bundles()
    # Add schema preview for each
    result = []
    for b in bundles:
        tools = export_mcp_tools_list([b])
        result.append({
            "name": b,
            "tools": [t["name"] for t in tools],
            "tool_count": len(tools),
        })
    return web.json_response(result)


async def create_token(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        token_req = TokenCreate(**data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    
    # Validate bundles exist
    available = set(list_bundles())
    invalid = set(token_req.bundles) - available
    if invalid:
        return web.json_response({"error": f"Unknown bundles: {invalid}"}, status=400)
    
    token = TOKEN_STORE.create(token_req.bundles, token_req.user_id, token_req.description)
    return web.json_response(token.model_dump(), status=201)


async def list_tokens(request: web.Request) -> web.Response:
    return web.json_response([t.model_dump() for t in TOKEN_STORE.list()])


async def delete_token(request: web.Request) -> web.Response:
    token = request.query.get("token") or request.match_info.get("token")
    if not token:
        return web.json_response({"error": "token parameter required"}, status=400)
    
    if not token.startswith("ody_mcp_"):
        token = f"ody_mcp_{token}"
    
    if TOKEN_STORE.delete(token):
        return web.json_response({"ok": True})
    return web.json_response({"error": "Token not found"}, status=404)


async def get_audit(request: web.Request) -> web.Response:
    try:
        limit = int(request.query.get("limit", "100"))
    except ValueError:
        limit = 100
    
    entries = get_audit_log(limit=limit)
    return web.json_response([AuditEntryResponse(
        timestamp=e.timestamp,
        caller_token_id=e.caller_token_id,
        tool=e.tool,
        args=e.args,
        exit_code=e.exit_code,
        latency_ms=e.latency_ms,
        user_id=e.user_id,
    ).model_dump() for e in entries])


async def get_rate_limit_status(request: web.Request) -> web.Response:
    """Debug: show current rate limit buckets."""
    status = {}
    for token_id, bucket in _rate_buckets.items():
        status[token_id] = {
            "tokens_remaining": bucket.tokens,
            "capacity": bucket.capacity,
            "refill_rate": bucket.refill_rate,
        }
    return web.json_response(status)


# ──────────────────────────────────────────────────────────────
# Route registration
# ──────────────────────────────────────────────────────────────

def setup_routes(app: web.Application) -> None:
    """Register admin routes. Call from main app setup."""
    app.router.add_get("/api/admin/outbound-mcp/config", get_config)
    app.router.add_put("/api/admin/outbound-mcp/config", update_config)
    app.router.add_get("/api/admin/outbound-mcp/bundles", list_bundles)
    app.router.add_post("/api/admin/outbound-mcp/tokens", create_token)
    app.router.add_get("/api/admin/outbound-mcp/tokens", list_tokens)
    app.router.add_delete("/api/admin/outbound-mcp/tokens", delete_token)
    app.router.add_get("/api/admin/outbound-mcp/audit", get_audit)
    app.router.add_get("/api/admin/outbound-mcp/rate-limits", get_rate_limit_status)
    
    # Initialize token store from config/env if needed
    app["outbound_mcp_token_store"] = TOKEN_STORE