"""Bundle registry + schema export schemas for outbound MCP (Issue #2521).

Mirrors manage_mcp registration pattern + skill_load/skill_save schema shape (#1801).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, FrozenSet
from collections import defaultdict


# ──────────────────────────────────────────────────────────────
# Data structures (match MCP tool schema + skill format)
# ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolSpec:
    """Immutable tool definition — matches MCP Tool schema."""
    name: str
    description: str
    input_schema: Dict[str, Any]  # JSON Schema
    allowed_args: FrozenSet[str] = field(default_factory=frozenset)
    allowed_env: FrozenSet[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class BundleSpec:
    """Immutable bundle of tools — mirrors manage_mcp bundle concept."""
    name: str
    description: str
    tools: FrozenSet[str] = field(default_factory=frozenset)  # tool names


# ──────────────────────────────────────────────────────────────
# Registry (populated at startup, frozen)
# ──────────────────────────────────────────────────────────────

_TOOL_REGISTRY: Dict[str, ToolSpec] = {}
_BUNDLE_REGISTRY: Dict[str, BundleSpec] = {}
_BUNDLE_TOOLS: Dict[str, FrozenSet[str]] = defaultdict(frozenset)  # bundle -> tool names


def register_bundle(spec: BundleSpec) -> None:
    """Register a bundle (admin-only, at startup)."""
    if spec.name in _BUNDLE_REGISTRY:
        raise ValueError(f"Bundle already registered: {spec.name}")
    _BUNDLE_REGISTRY[spec.name] = spec
    _BUNDLE_TOOLS[spec.name] = spec.tools


def register_tool(spec: ToolSpec) -> None:
    """Register a tool (admin-only, at startup)."""
    if spec.name in _TOOL_REGISTRY:
        raise ValueError(f"Tool already registered: {spec.name}")
    _TOOL_REGISTRY[spec.name] = spec


def get_bundle(name: str) -> BundleSpec | None:
    return _BUNDLE_REGISTRY.get(name)


def get_tool(name: str) -> ToolSpec | None:
    return _TOOL_REGISTRY.get(name)


def list_bundles() -> List[BundleSpec]:
    return list(_BUNDLE_REGISTRY.values())


def list_tools() -> List[ToolSpec]:
    return list(_TOOL_REGISTRY.values())


def get_tools_for_bundle(bundle_name: str) -> List[ToolSpec]:
    """Return ToolSpecs for all tools in a bundle."""
    tool_names = _BUNDLE_TOOLS.get(bundle_name, frozenset())
    return [_TOOL_REGISTRY[n] for n in tool_names if n in _TOOL_REGISTRY]


# ──────────────────────────────────────────────────────────────
# Schema export (for MCP initialize/tools/list)
# ──────────────────────────────────────────────────────────────

def export_mcp_tools_list(bundle_names: List[str]) -> List[Dict[str, Any]]:
    """Export tools in MCP ListToolsResult format.
    
    Matches: https://spec.modelcontextprotocol.io/specification/2024-11-05/server/tools/#list-tools
    """
    tools = []
    for bundle_name in bundle_names:
        for spec in get_tools_for_bundle(bundle_name):
            tools.append({
                "name": spec.name,
                "description": spec.description,
                "inputSchema": spec.input_schema,
            })
    return tools


def export_mcp_tool_schema(tool_name: str) -> Dict[str, Any] | None:
    """Export single tool schema for MCP tools/call."""
    spec = _TOOL_REGISTRY.get(tool_name)
    if not spec:
        return None
    return {
        "name": spec.name,
        "description": spec.description,
        "inputSchema": spec.input_schema,
    }


# ──────────────────────────────────────────────────────────────
# Built-in bundle definitions (extend as needed)
# ──────────────────────────────────────────────────────────────

def register_builtin_bundles() -> None:
    """Register core bundles. Called at startup if bundle enabled in config."""
    
    # --- Memory bundle ---
    register_bundle(BundleSpec(
        name="memory",
        description="Persistent cross-session memory (search/store/delete)",
        tools=frozenset(["memory_search", "memory_store", "memory_delete", "memory_list"]),
    ))
    register_tool(ToolSpec(
        name="memory_search",
        description="Search user memory by query",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
        allowed_args=frozenset(["query", "limit"]),
    ))
    register_tool(ToolSpec(
        name="memory_store",
        description="Store a fact in user memory",
        input_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Fact to store"},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["content"],
        },
        allowed_args=frozenset(["content", "tags"]),
    ))
    register_tool(ToolSpec(
        name="memory_delete",
        description="Delete a memory entry by ID",
        input_schema={
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "Memory entry ID"},
            },
            "required": ["memory_id"],
        },
        allowed_args=frozenset(["memory_id"]),
    ))
    register_tool(ToolSpec(
        name="memory_list",
        description="List all memory entries",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            },
        },
        allowed_args=frozenset(["limit"]),
    ))

    # --- Notes bundle ---
    register_bundle(BundleSpec(
        name="notes",
        description="Notes/todos/reminders management",
        tools=frozenset(["notes_create", "notes_read", "notes_update", "notes_delete", "notes_list"]),
    ))
    register_tool(ToolSpec(
        name="notes_create",
        description="Create a note",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["title", "content"],
        },
        allowed_args=frozenset(["title", "content", "tags"]),
    ))
    register_tool(ToolSpec(
        name="notes_read",
        description="Read a note by ID",
        input_schema={
            "type": "object",
            "properties": {
                "note_id": {"type": "string"},
            },
            "required": ["note_id"],
        },
        allowed_args=frozenset(["note_id"]),
    ))
    register_tool(ToolSpec(
        name="notes_update",
        description="Update a note",
        input_schema={
            "type": "object",
            "properties": {
                "note_id": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["note_id"],
        },
        allowed_args=frozenset(["note_id", "title", "content", "tags"]),
    ))
    register_tool(ToolSpec(
        name="notes_delete",
        description="Delete a note",
        input_schema={
            "type": "object",
            "properties": {
                "note_id": {"type": "string"},
            },
            "required": ["note_id"],
        },
        allowed_args=frozenset(["note_id"]),
    ))
    register_tool(ToolSpec(
        name="notes_list",
        description="List notes",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                "tag": {"type": "string"},
            },
        },
        allowed_args=frozenset(["limit", "tag"]),
    ))

    # --- Research bundle ---
    register_bundle(BundleSpec(
        name="research",
        description="Deep research tasks",
        tools=frozenset(["research_start", "research_status", "research_read"]),
    ))
    register_tool(ToolSpec(
        name="research_start",
        description="Start a deep research task",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Research topic/question"},
                "depth": {"type": "string", "enum": ["quick", "standard", "deep"], "default": "standard"},
            },
            "required": ["topic"],
        },
        allowed_args=frozenset(["topic", "depth"]),
    ))
    register_tool(ToolSpec(
        name="research_status",
        description="Check research task status",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
            },
            "required": ["task_id"],
        },
        allowed_args=frozenset(["task_id"]),
    ))
    register_tool(ToolSpec(
        name="research_read",
        description="Read completed research report",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
            },
            "required": ["task_id"],
        },
        allowed_args=frozenset(["task_id"]),
    ))

    # --- Skills bundle (depends on #1801) ---
    register_bundle(BundleSpec(
        name="skills",
        description="Load/save SKILL.md format skills",
        tools=frozenset(["skill_load", "skill_save"]),
    ))
    register_tool(ToolSpec(
        name="skill_load",
        description="Load a skill by name",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
        allowed_args=frozenset(["name"]),
    ))
    register_tool(ToolSpec(
        name="skill_save",
        description="Save a skill (admin only)",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["name", "content"],
        },
        allowed_args=frozenset(["name", "content"]),
    ))


# ──────────────────────────────────────────────────────────────
# Startup initialization
# ──────────────────────────────────────────────────────────────

_initialized = False


def initialize_registry(enabled_bundles: List[str]) -> None:
    """Call once at startup. Registers builtins, then filters to enabled."""
    global _initialized
    if _initialized:
        return
    register_builtin_bundles()
    
    # Filter: remove tools from disabled bundles
    enabled_tool_names = set()
    for bundle_name in enabled_bundles:
        if bundle_name in _BUNDLE_REGISTRY:
            enabled_tool_names.update(_BUNDLE_TOOLS[bundle_name])
    
    # Remove disabled tools
    for tool_name in list(_TOOL_REGISTRY.keys()):
        if tool_name not in enabled_tool_names:
            del _TOOL_REGISTRY[tool_name]
    
    # Remove disabled bundles
    for bundle_name in list(_BUNDLE_REGISTRY.keys()):
        if bundle_name not in enabled_bundles:
            del _BUNDLE_REGISTRY[bundle_name]
            del _BUNDLE_TOOLS[bundle_name]
    
    _initialized = True