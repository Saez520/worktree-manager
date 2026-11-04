"""Strict, versioned JSON contracts for the worktree management service."""
from __future__ import annotations

import pathlib

CONTRACT_VERSION = 1
from . import __version__ as TOOL_VERSION
from .worktree_lifecycle import MERGE_STRATEGIES
TOOL_NAMES = (
    "worktree_create", "worktree_complete", "worktree_cleanup",
    "worktree_recover", "worktree_list", "worktree_prune", "worktree_status",
)
MCP_INSTRUCTIONS = "Before you touch the main branch, offer to create an isolated worktree: create it with worktree_create, do all the work inside it, and close it with worktree_complete to integrate or worktree_cleanup to discard. If the worktree cannot be created or closed, correct the cause named in the error message before retrying."
TOOL_DESCRIPTIONS = {
    "worktree_create": "Creates an isolated worktree and its branch for a work identifier; use it before starting a change, spec, or flow so the base branch stays untouched.",
    "worktree_complete": "Integrates the worktree into the base branch and removes it; use it when the isolated work is finished and should land on the base branch.",
    "worktree_cleanup": "Removes the worktree and its branch without integrating; use it to discard abandoned work and, with discard and discard_consent, its uncommitted changes.",
    "worktree_recover": "Continues a pending transaction by its identifier; use it after an interrupted create or complete before starting another operation.",
    "worktree_list": "Lists the worktrees registered for the repository; use it to find existing work identifiers before creating or closing one.",
    "worktree_prune": "Removes worktree records whose directories no longer exist; use it after deleting a worktree by hand to clean the stale registration.",
    "worktree_status": "Reports one work item's worktree, journal transactions, and pending intervention; use it before completing or cleaning up to confirm the current state.",
}
FIELDS = {
    "worktree_create": {"repo", "work_id", "base", "dry_run", "parent_repo", "submodule_path", "confirm", "plan_hash", "init_submodules", "prepare", "verify"},
    "worktree_complete": {"repo", "work_id", "base", "dry_run", "authorization", "confirm", "plan_hash", "transaction_id", "preserve_dirty", "target_direct", "parent_repo", "commit_title", "commit_body", "merge_strategy"},
    "worktree_cleanup": {"repo", "work_id", "base", "dry_run", "authorization", "confirm", "plan_hash", "discard", "discard_consent"},
    "worktree_recover": {"repo", "transaction_id", "dry_run", "authorization", "confirm", "target_direct", "parent_repo"},
    "worktree_list": {"repo"}, "worktree_prune": {"repo", "dry_run", "authorization", "confirm", "plan_hash"},
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
    for key in ("dry_run", "discard", "preserve_dirty", "discard_consent", "target_direct", "confirm", "init_submodules", "prepare", "verify"):
        if key in request and type(request[key]) is not bool:
            raise ValueError(f"{key}_must_be_boolean")
    for key in ("work_id", "base", "transaction_id", "authorization", "parent_repo", "submodule_path", "commit_title", "commit_body", "merge_strategy"):
        if key in request and not isinstance(request[key], str):
            raise ValueError(f"{key}_must_be_string")
    if tool == "worktree_complete" and "merge_strategy" in request and request["merge_strategy"] not in MERGE_STRATEGIES:
        raise ValueError("merge_strategy_invalid")
    if tool in {"worktree_create", "worktree_complete", "worktree_cleanup", "worktree_status"} and not request.get("work_id"):
        raise ValueError("work_id_required")
    if tool == "worktree_create" and bool(request.get("parent_repo")) != bool(request.get("submodule_path")):
        raise ValueError("target_direct_requires_parent_and_submodule_path")
    if request.get("target_direct") and not request.get("parent_repo"):
        raise ValueError("target_direct_requires_parent_repo")
    normalized = dict(request)
    has_confirm = "confirm" in normalized
    confirm = normalized.pop("confirm", False)
    if confirm:
        if normalized.get("authorization") not in (None, "I_AUTHORIZE_THIS_CALL"):
            raise ValueError("authorization_mismatch")
        normalized["authorization"] = "I_AUTHORIZE_THIS_CALL"
    elif has_confirm and normalized.get("authorization") == "I_AUTHORIZE_THIS_CALL":
        raise ValueError("authorization_mismatch")
    if "plan_hash" in normalized and (not isinstance(normalized["plan_hash"], str) or len(normalized["plan_hash"]) != 64 or any(c not in "0123456789abcdef" for c in normalized["plan_hash"])):
        raise ValueError("plan_hash_must_be_sha256")
    return normalized

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

def absolute_repository(value):
    """Absolute form of a requested repository, or an empty string when unknown."""
    if not isinstance(value, str) or not value:
        return ""
    path = pathlib.Path(value).expanduser()
    try:
        return str(path.resolve())
    except (OSError, RuntimeError):
        return str(path.absolute())

def error_envelope(operation, repository, code, message, exit_code):
    """Canonical envelope for a failed operation, shared by every transport."""
    result = "pending_intervention" if code == "intervention_required" else "failure"
    return envelope(operation, repository or "", result, data={}, warnings=[],
                    error={"code": code, "message": message, "exit_code": exit_code},
                    transaction_id=None)
