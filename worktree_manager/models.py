"""Domain values shared by the command-line and lifecycle layers."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResultKind(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING_INTERVENTION = "pending_intervention"
    NO_PENDING_WORK = "no_pending_work"


@dataclass(frozen=True)
class ManagerError(Exception):
    code: str
    message: str
    exit_code: int

    def __str__(self) -> str:
        return self.message


@dataclass
class OperationResult:
    operation: str
    result: ResultKind = ResultKind.SUCCESS
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: ManagerError | None = None

    def json_document(self) -> dict[str, Any]:
        return {
            "contract_version": 1,
            "tool_version": "1.0.0",
            "operation": self.operation,
            "result": self.result.value,
            "data": self.data,
            "warnings": self.warnings,
            "error": None if self.error is None else {
                "code": self.error.code,
                "message": self.error.message,
                "exit_code": self.error.exit_code,
            },
        }

    @property
    def exit_code(self) -> int:
        return self.error.exit_code if self.error else 0


@dataclass(frozen=True)
class TransactionIdentity:
    transaction_id: str
    repository: str
    phase: str
    original_head: str


@dataclass(frozen=True)
class TargetDirectIdentity:
    target_repo: str
    parent_repo: str
    submodule_path: str
    link_parent: str = "staged-only"
