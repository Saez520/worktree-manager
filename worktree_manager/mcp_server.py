"""Minimal stdio JSON-RPC server exposing the worktree management tools."""
import json
import sys
from .mcp_contract import TOOL_NAMES
from .mcp_operations import call
from .models import ManagerError

def schemas():
    from .mcp_contract import FIELDS, REQUIRED, output_schema
    props = {"repo": {"type": "string"}, "work_id": {"type": "string"},
             "base": {"type": "string"}, "transaction_id": {"type": "string"},
             "authorization": {"type": "string", "enum": ["I_AUTHORIZE_THIS_CALL"]},
             "dry_run": {"type": "boolean"}, "discard": {"type": "boolean"},
             "discard_consent": {"type": "boolean"}, "preserve_dirty": {"type": "boolean"}}
    props.update({"parent_repo": {"type": "string"}, "submodule_path": {"type": "string"},
                  "target_direct": {"type": "boolean"}})
    return [{"name": name, "description": "Manage repository worktrees", "inputSchema": {
        "type": "object", "properties": {key: props[key] for key in sorted(FIELDS[name])},
        "required": sorted(REQUIRED[name]), "additionalProperties": False}, "outputSchema": output_schema()} for name in TOOL_NAMES]

def dispatch(message):
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}}, "serverInfo": {"name": "worktree-manager", "version": "1.0.0"}}
    if method == "notifications/initialized": return None
    if method == "ping": return {}
    if method == "tools/list": return {"tools": schemas()}
    if method == "tools/call":
        name = params.get("name")
        try:
            result = call(name, params.get("arguments", {}))
            return {"content": [{"type": "text", "text": json.dumps(result, sort_keys=True)}], "structuredContent": result, "isError": False}
        except Exception as exc:
            err = {"code": getattr(exc, "code", "invalid_request"), "message": str(exc), "cause": type(exc).__name__, "action": "Check the request and repository state; no success is implied."}
            result = {"contract_version": 1, "tool_version": "1.0.0", "operation": name, "repository": (params.get("arguments") or {}).get("repo"), "result": "failure", "data": {}, "warnings": [], "error": err, "transaction_id": None}
            return {"content": [{"type": "text", "text": json.dumps(result, sort_keys=True)}], "structuredContent": result, "isError": True}
    raise ValueError("method_not_found")

def main():
    for line in sys.stdin:
        try:
            message = json.loads(line)
            result = dispatch(message)
            if "id" in message and result is not None:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            if "id" in locals().get("message", {}):
                response = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601 if str(exc) == "method_not_found" else -32600, "message": str(exc)}}
                sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n"); sys.stdout.flush()
            else:
                print(f"MCP request failed: {type(exc).__name__}", file=sys.stderr)
