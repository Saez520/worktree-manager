"""Direct CLI/MCP preflight binding matrix against isolated Git repositories."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp_client import McpClient
from test_mcp_e2e import fixture, state


class DirectTransportMatrix(unittest.TestCase):
    cases = (
        "happy", "operation", "repo", "work_id", "confirm_false",
        "transaction_id", "plan_hash", "operation_repo", "transaction_hash",
        "repo_work_id", "confirm_hash", "three_dimensions",
    )

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
                        for case in self.cases:
                            work_id = f"matrix-{transport}-{name}-{case}".replace("_", "-")
                            request = {"operation": "create", "repo": str(repo), "work_id": work_id,
                                       "base": "main", "dry_run": True}
                            if transport == "cli":
                                pre = self.cli(request)
                            else:
                                pre, err = mcp.call("worktree_create", {k:v for k,v in request.items() if k != "operation"})
                                self.assertFalse(err, pre)
                            plan_hash = pre["data"]["plan_hash"]
                            request["dry_run"] = False
                            request["plan_hash"] = plan_hash
                            expected = "success"
                            if case != "happy":
                                expected = "plan_mismatch"
                                if "transaction" in case or case == "three_dimensions": expected = "invalid_request"
                                if case in {"operation", "operation_repo", "three_dimensions"}: request["operation"] = "cleanup"
                                if request["operation"] == "cleanup": request["authorization"] = "I_AUTHORIZE_THIS_CALL"
                                if case in {"repo", "operation_repo", "repo_work_id", "three_dimensions"}: request["repo"] = str(repos["B"] if name == "A" else repos["A"])
                                if case in {"work_id", "repo_work_id", "three_dimensions"}: request["work_id"] += "-altered"
                                if case in {"confirm_false", "confirm_hash", "three_dimensions"}: request["confirm"] = False
                                if case in {"transaction_id", "transaction_hash", "three_dimensions"}: request["transaction_id"] = "wt-altered"
                                if case in {"plan_hash", "transaction_hash", "confirm_hash", "three_dimensions", "confirm_false"}: request["plan_hash"] = "0" * 64
                            before = {key: state(value) for key, value in repos.items()}
                            if transport == "cli":
                                result = self.cli(request)
                                observed = (result.get("error") or {}).get("code", result.get("result"))
                            else:
                                operation = request.pop("operation")
                                result, err = mcp.call("worktree_create" if operation == "create" else "worktree_cleanup", request)
                                observed = (result.get("error") or {}).get("code", result.get("result"))
                                request["operation"] = operation
                            after = {key: state(value) for key, value in repos.items()}
                            cell_ok = observed == expected
                            if expected != "success": cell_ok &= before == after
                            evidence.append({"transport": transport, "repo": name, "case": case,
                                "request": request, "effective_payload": request,
                                "envelope": result, "expected_code": expected,
                                "observed_code": observed, "barrier": None,
                                "state_before_after_digest": {"before": before, "after": after}, "ok": bool(cell_ok)})
                            self.assertTrue(cell_ok, evidence[-1])
            self.assertEqual(len(evidence), 48)
            dest = os.environ.get("MCP_MATRIX_EVIDENCE")
            if dest:
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def cli(request):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
        p = subprocess.run([sys.executable, "-m", "worktree_manager", "--request-json", "-", "--json"],
            input=json.dumps(request), text=True, capture_output=True, env=env)
        try:
            return json.loads(p.stdout)
        except ValueError:
            raise AssertionError(f"CLI returned {p.returncode}: {p.stdout} {p.stderr}")


if __name__ == "__main__":
    unittest.main()
