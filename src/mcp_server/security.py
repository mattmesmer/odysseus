"""Security gates for outbound MCP server (Issue #2521).

Mirrors patterns from:
- manage_mcp allowlist (#438)
- OAuth path containment (#2272/#2267)
- Prompt-injection resistance (test_skill_index_prompt_injection.py)
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import FrozenSet, Dict, Any, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# JSON-RPC Error (shared with transport layer)
# ──────────────────────────────────────────────────────────────

class JSONRPCError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


# ──────────────────────────────────────────────────────────────
# Allowlist (frozen at startup, admin-configurable via config.py)
# ──────────────────────────────────────────────────────────────

# Bundle name -> set of tool names
ALLOWED_BUNDLES: Dict[str, FrozenSet[str]] = {}

# Tool name -> (allowed_args_frozenset, allowed_env_frozenset)
# Mirrors manage_mcp's ALLOWED_COMMANDS / ALLOWED_ARGS / ALLOWED_ENV pattern
ALLOWED_TOOL_SPECS: Dict[str, tuple[FrozenSet[str], FrozenSet[str]]] = {}


def load_allowlist_from_registry() -> None:
    """Populate allowlists from the tools registry. Call once at startup."""
    global ALLOWED_BUNDLES, ALLOWED_TOOL_SPECS
    # Import here to avoid circular imports
    from .tools_registry import _BUNDLE_REGISTRY, _TOOL_REGISTRY, _BUNDLE_TOOLS
    
    ALLOWED_BUNDLES = {
        name: spec.tools for name, spec in _BUNDLE_REGISTRY.items()
    }
    
    ALLOWED_TOOL_SPECS = {}
    for tool_name, tool_spec in _TOOL_REGISTRY.items():
        ALLOWED_TOOL_SPECS[tool_name] = (tool_spec.allowed_args, tool_spec.allowed_env)
    
    logger.info("Outbound MCP allowlist loaded: %d bundles, %d tools", 
                len(ALLOWED_BUNDLES), len(ALLOWED_TOOL_SPECS))


def is_tool_allowed(tool: str, args: dict, env: dict) -> bool:
    """Gate every outbound tool call. Returns True if allowed."""
    if tool not in ALLOWED_TOOL_SPECS:
        logger.warning("Outbound MCP: rejected unknown tool %s", tool)
        return False
    allowed_args, allowed_env = ALLOWED_TOOL_SPECS[tool]
    if not set(args.keys()).issubset(allowed_args):
        logger.warning("Outbound MCP: tool %s got disallowed args %s", tool, set(args) - allowed_args)
        return False
    if not set(env.keys()).issubset(allowed_env):
        logger.warning("Outbound MCP: tool %s got disallowed env %s", tool, set(env) - allowed_env)
        return False
    return True


# ──────────────────────────────────────────────────────────────
# Path containment (mirrors OAuth _confine_path)
# ──────────────────────────────────────────────────────────────

DATA_ROOT: str = "/workspace"
SESSION_ROOT: str = "/workspace"


def confine_path(user_root: str, requested: str) -> str:
    """Resolve requested path under user_root; raise if escape attempt."""
    import os
    user_root = os.path.abspath(user_root)
    requested = os.path.abspath(requested)
    if not requested.startswith(user_root):
        raise ValueError(f"Path escape attempt: {requested} not under {user_root}")
    return requested


# ──────────────────────────────────────────────────────────────
# Rate limiting (token-bucket, per-token)
# ──────────────────────────────────────────────────────────────

@dataclass
class TokenBucket:
    capacity: int
    refill_rate: float  # tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self):
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()

    def take(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


_rate_buckets: Dict[str, TokenBucket] = defaultdict(
    lambda: TokenBucket(capacity=60, refill_rate=1.0)  # 60 req/min default
)


def check_rate_limit(token_id: str, limit: Optional[int] = None) -> bool:
    """Returns True if request allowed, False if rate limited."""
    bucket = _rate_buckets[token_id]
    if limit is not None:
        bucket.capacity = limit
        bucket.refill_rate = limit / 60.0
    return bucket.take()


# ──────────────────────────────────────────────────────────────
# Audit logging (structured, secrets redacted)
# ──────────────────────────────────────────────────────────────

SENSITIVE_KEYS = {"token", "password", "secret", "key", "authorization", "api_key"}


def redact_args(args: dict) -> dict:
    """Return copy with sensitive values masked."""
    redacted = {}
    for k, v in args.items():
        if any(s in k.lower() for s in SENSITIVE_KEYS):
            redacted[k] = "***REDACTED***"
        else:
            redacted[k] = v
    return redacted


@dataclass
class AuditEntry:
    timestamp: float
    caller_token_id: str
    tool: str
    args: dict
    exit_code: int
    latency_ms: float
    user_id: Optional[str] = None


_audit_log: list[AuditEntry] = []


def emit_audit(
    caller_token_id: str,
    tool: str,
    args: dict,
    exit_code: int,
    latency_ms: float,
    user_id: Optional[str] = None,
) -> None:
    """Append to in-memory audit log; also logs to structured logger."""
    entry = AuditEntry(
        timestamp=time.time(),
        caller_token_id=caller_token_id,
        tool=tool,
        args=redact_args(args),
        exit_code=exit_code,
        latency_ms=latency_ms,
        user_id=user_id,
    )
    _audit_log.append(entry)
    logger.info(
        "outbound_mcp_audit",
        extra={
            "caller_token_id": caller_token_id,
            "tool": tool,
            "args": entry.args,
            "exit_code": exit_code,
            "latency_ms": latency_ms,
            "user_id": user_id,
        },
    )


def get_audit_log(limit: int = 1000) -> list[AuditEntry]:
    return _audit_log[-limit:]