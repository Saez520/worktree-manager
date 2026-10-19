"""Direct CLI/MCP request matrix against two independent real Git repositories."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp_client import McpClient
from test_mcp_e2e import fixture, git, state


class DirectTransportMatrix(unittest.TestCase):
    cases = (
        "happy", "operation", "repo", "work_id", "confirm_false",
        "transaction_id", "plan_hash", "operation_repo", "transaction_hash",
        "repo_work_id", "confirm_hash", "three_dimensions",
    )

    def test_case_table_semantics(self):
        self.assertEqual(len(self.cases), 12)
        self.assertEqual(len(set(self.cases)), 12)
        self.assertEqual(self.expected("transaction_id"), ("plan_mismatch", "Repository state or request changed since preflight"))
        self.assertEqual(self.expected("confirm_false"), ("invalid_request", "authorization_mismatch"))
        self.assertEqual(self.expected("transaction_hash"), self.expected("transaction_id"))
        self.assertEqual(self.expected("confirm_hash"), self.expected("confirm_false"))

    def test_cli_mcp_ab_matrix(self):
        evidence = []
        with tempfile.TemporaryDirectory(prefix="mcp-matrix-") as temp:
            root = Path(temp)
            repos = {name: root / name for name in ("A", "B")}
            for repo in repos.values():
                fixture(repo)
            with McpClient() as mcp:
                for transport in ("cli", "mcp"):
                    for name, repo in repos.items():
                        other_name = "B" if name == "A" else "A"
                        for case in self.cases:
                            cell = self.run_cell(transport, case, name, repo, repos[other_name], mcp)
                            evidence.append(cell)
                            self.assertTrue(cell["ok"], cell)
            self.assertEqual(len(evidence), 48)
            self.assertEqual(len({(x["transport"], x["repo"], x["case"]) for x in evidence}), 48)
            dest = os.environ.get("MCP_MATRIX_EVIDENCE")
            if dest:
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")

    def run_cell(self, transport, case, name, repo, other, mcp):
        work_id = f"matrix-{transport}-{name}-{case}".replace("_", "-")
        tool = "worktree_create"
        setup_result = None
        if case in {"transaction_id", "transaction_hash"}:
            created = self.invoke(transport, mcp, "worktree_create", {
                "repo": str(repo), "work_id": work_id, "base": "main"})
            setup_result = created
            wt = repo / ".worktrees" / work_id
            (wt / "change.txt").write_text("complete me\n")
            git(wt, "add", "change.txt")
            git(wt, "commit", "-qm", "matrix change")
            tool = "worktree_complete"
            planned = {"repo": str(repo), "work_id": work_id, "base": "main", "dry_run": True,
                       "authorization": "I_AUTHORIZE_THIS_CALL"}
        elif case in {"confirm_false", "confirm_hash"}:
            created = self.invoke(transport, mcp, "worktree_create", {
                "repo": str(repo), "work_id": work_id, "base": "main"})
            setup_result = created
            tool = "worktree_cleanup"
            planned = {"repo": str(repo), "work_id": work_id, "base": "main", "dry_run": True,
                       "authorization": "I_AUTHORIZE_THIS_CALL"}
        else:
            planned = {"repo": str(repo), "work_id": work_id, "base": "main", "dry_run": True}

        pre = self.invoke(transport, mcp, tool, planned)
        pdata = pre.get("data", {})
        request = dict(planned)
        request["dry_run"] = False
        if "plan_hash" in pdata:
            request["plan_hash"] = pdata["plan_hash"]
        expected_code, expected_message = self.expected(case)
        op = "create"
        if case in {"operation", "operation_repo", "three_dimensions"}:
            op, tool = "cleanup", "worktree_cleanup"
            request = {"repo": str(repo), "work_id": work_id, "base": "main", "authorization": "I_AUTHORIZE_THIS_CALL",
                       "plan_hash": request.get("plan_hash", "")}
        if op == "cleanup" and tool != "worktree_cleanup":
            tool = "worktree_cleanup"
        if case in {"repo", "operation_repo", "repo_work_id", "three_dimensions"}:
            request["repo"] = str(other)
        if case in {"work_id", "repo_work_id", "three_dimensions"}:
            request["work_id"] += "-altered"
        if case in {"confirm_false", "confirm_hash"}:
            request["confirm"] = False
            if case == "confirm_hash": request["plan_hash"] = "0" * 64
        if case in {"transaction_id", "transaction_hash"}:
            planned_tx = pre.get("transaction_id") or pdata.get("transaction_id")
            request["transaction_id"] = (planned_tx or "wt-" + work_id) + "-altered"
            if case == "transaction_hash": request["plan_hash"] = "0" * 64
        if case == "plan_hash": request["plan_hash"] = "0" * 64
        if case == "transaction_hash": expected_code, expected_message = "plan_mismatch", "Repository state or request changed since preflight"
        if case == "confirm_hash": expected_code, expected_message = "invalid_request", "authorization_mismatch"

        before = {key: state(value) for key, value in ((name, repo), ("other", other))}
        before_count = len(git(repo, "worktree", "list", "--porcelain").strip().split("\n\n"))
        result = self.invoke(transport, mcp, tool, request)
        after = {key: state(value) for key, value in ((name, repo), ("other", other))}
        after_count = len(git(repo, "worktree", "list", "--porcelain").strip().split("\n\n"))
        observed = self.error_code(result)
        if case == "happy":
            ok = result.get("result") == "success" and after_count == before_count + 1 and before["other"] == after["other"]
        else:
            ok = observed == expected_code and before == after
        if expected_message and observed == expected_code:
            message = self.error_message(result)
            ok = ok and expected_message in message
        cell = {"transport": transport, "repo": name, "case": case, "operation": op,
                "request": request, "effective_payload": request, "setup": setup_result,
                "envelope": result, "expected_code": expected_code, "observed_code": observed,
                "expected_message": expected_message, "observed_message": self.error_message(result),
                "barrier": None, "state_before": before, "state_after": after, "ok": bool(ok)}
        # Each cell starts from a clean fixture; this cleanup is outside its measured interval.
        cleanup_id = work_id
        cleanup_path = repo / ".worktrees" / cleanup_id
        if cleanup_path.exists():
            subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(cleanup_path)],
                           check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "branch", "-D", f"worktree/{cleanup_id}"],
                       check=False, capture_output=True, text=True)
        return cell

    @staticmethod
    def expected(case):
        if case == "happy": return "success", ""
        if case in {"confirm_false", "confirm_hash"}: return "invalid_request", "authorization_mismatch"
        return "plan_mismatch", "Repository state or request changed since preflight"

    @staticmethod
    def error_code(result):
        return (result.get("error") or {}).get("code", result.get("result"))

    @staticmethod
    def error_message(result):
        error = result.get("error")
        if isinstance(error, dict): return str(error.get("message", ""))
        return str(error or "")

    @staticmethod
    def invoke(transport, mcp, tool, request):
        if transport == "mcp":
            response, _ = mcp.call(tool, request)
            return response
        request = dict(request)
        request["operation"] = {
            "worktree_create": "create", "worktree_complete": "complete",
            "worktree_cleanup": "cleanup",
        }.get(tool, tool.removeprefix("worktree_"))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run([sys.executable, "-m", "worktree_manager", "--request-json", "-", "--json"],
                              input=json.dumps(request), text=True, capture_output=True, env=env)
        try:
            return json.loads(proc.stdout)
        except ValueError:
            raise AssertionError(f"CLI returned {proc.returncode}: {proc.stdout} {proc.stderr}")


if __name__ == "__main__":
    unittest.main()
