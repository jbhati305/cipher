from __future__ import annotations

import re

from mcp.server.mcpserver.exceptions import ToolError


class PolicyDenied(ToolError, ValueError):
    """Raised when an operation is outside Cipher's configured capability boundary."""


_RESOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")
_ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def validate_resource(value: str, kind: str) -> str:
    if not isinstance(value, str) or not _RESOURCE_RE.fullmatch(value):
        raise PolicyDenied(f"invalid {kind} identifier")
    return value


def require_allowed(value: str, allowed: frozenset[str], kind: str, operation: str) -> str:
    validate_resource(value, kind)
    if value not in allowed:
        raise PolicyDenied(f"{operation} is not allowed for {kind} '{value}'")
    return value


def validate_entity_id(entity_id: str) -> tuple[str, str]:
    if not isinstance(entity_id, str) or not _ENTITY_RE.fullmatch(entity_id):
        raise PolicyDenied("invalid Home Assistant entity_id")
    domain, object_id = entity_id.split(".", 1)
    return domain, object_id


def validate_action(value: str, kind: str = "action") -> str:
    if not isinstance(value, str) or not _ACTION_RE.fullmatch(value):
        raise PolicyDenied(f"invalid {kind}")
    return value
