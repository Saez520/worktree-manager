"""Strict, versioned JSON contracts for the worktree management service."""
from __future__ import annotations

CONTRACT_VERSION = 1
TOOL_VERSION = "1.0.0"
TOOL_NAMES = (
    "worktree_create", "worktree_complete", "worktree_cleanup",
    "worktree_recover", "worktree_list", "worktree_prune", "worktree_status",
)
FIELDS = {
    "worktree_create": {"repo", "work_id", "base", "dry_run", "parent_repo", "submodule_path"},
    "worktree_complete": {"repo", "work_id", "base", "dry_run", "authorization", "preserve_dirty", "target_direct", "parent_repo"},
    "worktree_cleanup": {"repo", "work_id", "base", "dry_run", "authorization", "discard", "discard_consent"},
    "worktree_recover": {"repo", "transaction_id", "dry_run", "authorization", "target_direct", "parent_repo"},
    "worktree_list": {"repo"}, "worktree_prune": {"repo", "dry_run", "authorization"},
    "worktree_status": {"repo", "work_id"},
}
REQUIRED = {
    "worktree_create": {"repo", "work_id"}, "worktree_complete": {"repo", "work_id"},
    "worktree_cleanup": {"repo", "work_id"}, "worktree_recover": {"repo"},
    "worktree_list": {"repo"}, "worktree_prune": {"repo"},
    "worktree_status": {"repo", "work_id"},
}

def validate_request(tool: str, request: dict) -> dict:
    if tool not in FIELDS:
        raise ValueError("unknown_tool")
    if not isinstance(request, dict):
        raise ValueError("invalid_request")
    unknown = set(request) - FIELDS[tool]
    if unknown:
        raise ValueError("unknown_fields: " + ", ".join(sorted(unknown)))
    if not REQUIRED[tool] <= request.keys():
        raise ValueError("missing_required_fields: " + ", ".join(sorted(REQUIRED[tool] - request.keys())))
    repo = request["repo"]
    if not isinstance(repo, str) or not repo or not __import__("pathlib").Path(repo).is_absolute():
        raise ValueError("repo_must_be_absolute")
    for key in ("dry_run", "discard", "preserve_dirty", "discard_consent", "target_direct"):
        if key in request and type(request[key]) is not bool:
            raise ValueError(f"{key}_must_be_boolean")
    for key in ("work_id", "base", "transaction_id", "authorization", "parent_repo", "submodule_path"):
        if key in request and not isinstance(request[key], str):
            raise ValueError(f"{key}_must_be_string")
    if tool in {"worktree_create", "worktree_complete", "worktree_cleanup", "worktree_status"} and not request.get("work_id"):
        raise ValueError("work_id_required")
    if tool == "worktree_create" and bool(request.get("parent_repo")) != bool(request.get("submodule_path")):
        raise ValueError("target_direct_requires_parent_and_submodule_path")
    if request.get("target_direct") and not request.get("parent_repo"):
        raise ValueError("target_direct_requires_parent_repo")
    return request

def output_schema():
    return {"type": "object", "required": ["contract_version", "tool_version", "operation", "repository", "result", "data", "warnings", "error", "transaction_id"], "properties": {
        "contract_version": {"type": "integer"}, "tool_version": {"type": "string"},
        "operation": {"type": "string"}, "repository": {"type": "string"},
        "result": {"type": "string"}, "data": {"type": "object"}, "warnings": {"type": "array"},
        "error": {"type": ["object", "null"]}, "transaction_id": {"type": ["string", "null"]}}, "additionalProperties": False}

def envelope(operation, repo, result="success", data=None, warnings=None, error=None, transaction_id=None):
    return {"contract_version": CONTRACT_VERSION, "tool_version": TOOL_VERSION,
            "operation": operation, "repository": repo, "result": result,
            "data": data or {}, "warnings": warnings or [], "error": error,
            "transaction_id": transaction_id}
