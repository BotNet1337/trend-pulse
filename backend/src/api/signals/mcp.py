"""Minimal MCP server exposing recent signals as a tool (T7b).

A thin JSON-RPC-over-stdio shim (no external `mcp` dependency, to keep the worker/api
image lean) so AI agents / Claude can call `list_signals` and get the noise-filtered,
independence-weighted signals. The tool handler (`handle_request`) is pure and
unit-tested; `serve_stdio` is just the transport loop for `python -m api.signals.mcp`.
"""

import json
import sys
from typing import Any

from api.signals.service import EmptySignalSource, SignalSource, recent_signals

_PROTOCOL_VERSION = "2024-11-05"
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_signals",
        "description": (
            "Recent actionable crypto signals: cross-channel stories ranked by an "
            "independence-weighted score with ad/shill noise excluded. Each carries the "
            "event category, origin channel, independent-channel count and lead-time."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_LIMIT,
                    "description": f"Max signals (1..{_MAX_LIMIT}, default {_DEFAULT_LIMIT}).",
                }
            },
        },
    }
]


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _ok(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def handle_list_signals(source: SignalSource, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the `list_signals` tool: return recent signals as plain dicts."""
    limit = arguments.get("limit", _DEFAULT_LIMIT)
    if not isinstance(limit, int) or limit < 1:
        limit = _DEFAULT_LIMIT
    limit = min(limit, _MAX_LIMIT)
    return [signal.model_dump() for signal in recent_signals(source, limit)]


def handle_request(request: dict[str, Any], source: SignalSource) -> dict[str, Any]:
    """Dispatch one JSON-RPC request (MCP subset: initialize, tools/list, tools/call)."""
    req_id = request.get("id")
    method = request.get("method")

    if method == "initialize":
        return _ok(req_id, {"protocolVersion": _PROTOCOL_VERSION, "capabilities": {"tools": {}}})
    if method == "tools/list":
        return _ok(req_id, {"tools": _TOOLS})
    if method == "tools/call":
        params = request.get("params") or {}
        if params.get("name") != "list_signals":
            return _error(req_id, -32602, f"unknown tool {params.get('name')!r}")
        signals = handle_list_signals(source, params.get("arguments") or {})
        return _ok(req_id, {"content": signals, "isError": False})
    return _error(req_id, -32601, f"method not found: {method}")


def serve_stdio(source: SignalSource | None = None) -> None:  # pragma: no cover - transport
    """Read JSON-RPC requests from stdin, write responses to stdout (one per line)."""
    src = source if source is not None else EmptySignalSource()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(_error(None, -32700, "parse error")) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps(handle_request(request, src)) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":  # pragma: no cover
    serve_stdio()
