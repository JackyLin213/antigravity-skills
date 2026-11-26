#!/usr/bin/env python3
"""Lifecycle hook gate enforcing ALE PreToolUse (RED/LL_GATE & Ship Gate) and Stop invariants."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SHIP_COMMAND_PATTERN = re.compile(
    r"(?:^|[;&|]\s*)(?:git\s+push\b|gh\s+pr\s+create\b|gh\s+release\s+create\b|npm\s+publish\b|npx\s+skills\s+publish\b)"
)
DISPATCH_LEASE_TTL_SECONDS = 900.0


def get_output_root(override: str | None = None) -> Path:
    """Return the base directory storing per-workspace ALE ledgers."""
    env_override = override or os.environ.get("ALE_OUTPUT_ROOT")
    if env_override:
        return Path(env_override).expanduser().resolve()
    return Path.home() / "tmp" / "ale_harness"


def workspace_slug(workspace_path: str) -> str:
    """Compute a deterministic slug for a workspace path."""
    resolved = str(Path(workspace_path).expanduser().resolve())
    name = Path(resolved).name or "root"
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]
    return f"{name}-{digest}"


def load_active_ledger(
    workspace_paths: list[str],
    output_dir: str | None = None,
    include_verified: bool = False,
) -> dict[str, Any] | None:
    """Load the active (or verified, for ship checks) ledger for the current workspace if one exists."""
    base = get_output_root(output_dir)
    candidates: list[Path] = []
    for ws in workspace_paths:
        candidates.append(base / workspace_slug(ws) / "ledger.json")
    candidates.append(base / workspace_slug(os.getcwd()) / "ledger.json")

    allowed_statuses = {"active", "verified", "completed"} if include_verified else {"active"}
    for ledger_path in candidates:
        if ledger_path.is_file():
            try:
                data = json.loads(ledger_path.read_text(encoding="utf-8"))
                if data.get("status") in allowed_statuses:
                    return data
            except (OSError, json.JSONDecodeError):
                continue
    return None


def is_pid_alive(pid: int) -> bool:
    """Return True if a process ID is positive and currently alive on the host."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def has_active_dispatch_lease(ledger: dict[str, Any]) -> bool:
    """Return True when a background model_router.py call holds an active dispatch_in_progress lease."""
    dispatch = ledger.get("dispatch_in_progress")
    if not isinstance(dispatch, dict):
        return False
    started_at = float(dispatch.get("started_at", 0.0) or 0.0)
    if (time.time() - started_at) >= DISPATCH_LEASE_TTL_SECONDS:
        return False
    pid = int(dispatch.get("pid", 0) or 0)
    return is_pid_alive(pid) if pid > 0 else True


def record_runtime_model_from_payload(payload: dict[str, Any], output_dir: str | None = None) -> None:
    """Persist the live modelName or transcript Model Selection from hook stdin payload."""
    if os.environ.get("ALE_SUBPROCESS_DISPATCH") == "1":
        return
    raw_model = str(payload.get("modelName", "")).strip()
    transcript_path = str(payload.get("transcriptPath", "")).strip()
    detected: str | None = None
    if raw_model and raw_model.lower() not in ("auto", "none", ""):
        detected = raw_model
    elif transcript_path and Path(transcript_path).is_file():
        try:
            text = Path(transcript_path).read_text(encoding="utf-8", errors="ignore")
            matches = re.findall(
                r"changed setting `Model Selection` from [^\n]+? to ([^\n<]+?)(?:\.(?:\s|<|$)|<|$)",
                text,
                flags=re.IGNORECASE,
            )
            if matches:
                detected = matches[-1].strip()
        except OSError:
            pass
    if detected:
        base = get_output_root(output_dir)
        base.mkdir(parents=True, exist_ok=True)
        runtime_file = base / "active_runtime_model.json"
        runtime_file.write_text(
            json.dumps({"model_id": detected, "transcript_path": transcript_path}, indent=2),
            encoding="utf-8",
        )


def handle_pre_tool_use(payload: dict[str, Any], output_dir: str | None = None) -> dict[str, Any]:
    """Evaluate PreToolUse hook rules for file modifications and outward ship commands."""
    record_runtime_model_from_payload(payload, output_dir)
    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args", {})
    workspace_paths = payload.get("workspacePaths", [])
    sub_role = os.environ.get("ALE_SUBPROCESS_ROLE", "").strip()

    if tool_name == "run_command":
        if sub_role in ("review", "judge"):
            return {
                "decision": "deny",
                "reason": (
                    f"ALE Subprocess Gate: Role '{sub_role}' is strictly read-only; "
                    f"use read_file on review_packet.md or workspace files instead of run_command."
                ),
            }
        cmd = str(args.get("CommandLine", ""))
        if SHIP_COMMAND_PATTERN.search(cmd):
            ship_ledger = load_active_ledger(workspace_paths, output_dir, include_verified=True)
            if ship_ledger and ship_ledger.get("allow_ship") is True:
                return {"decision": "allow"}
            return {
                "decision": "deny",
                "reason": (
                    "ALE Ship Gate: Outward/irreversible command blocked ('git push' / 'gh pr create'). "
                    "Obtain explicit user confirmation first, then record 'ledger.py ruling --allow_ship'."
                ),
            }
        return {"decision": "allow"}

    if tool_name in ("edit_file", "write_file"):
        if sub_role in ("review", "judge", "research"):
            return {
                "decision": "deny",
                "reason": f"ALE Subprocess Gate: Role '{sub_role}' is strictly read-only and may not modify files.",
            }

        ledger = load_active_ledger(workspace_paths, output_dir, include_verified=False)
        if not ledger:
            return {"decision": "allow"}

        target_path = str(Path(str(args.get("Path", ""))).expanduser().resolve())
        home_str = str(Path.home())
        session_dir = str(ledger.get("session_dir", ""))
        workspace_dir = str(ledger.get("workspace_path", ""))
        in_workspace = bool(workspace_dir and target_path.startswith(workspace_dir))
        if (
            (session_dir and target_path.startswith(session_dir))
            or "/knowledgebase/" in target_path
            or "/drive-fs/" in target_path
            or "/brain/" in target_path
            or target_path.endswith("plan.md")
            or ("/tmp/" in target_path and not in_workspace)
        ):
            return {"decision": "allow"}

        if int(ledger.get("friction_count", 0)) >= 3 or ledger.get("locked") is True:
            return {
                "decision": "deny",
                "reason": (
                    "ALE Friction Budget (3/3) exhausted! Code edits are locked. "
                    "Deliver an Honest Handback with SESSION_LL.md and your root-cause hypothesis."
                ),
            }

        if sub_role == "strike-breaker":
            return {"decision": "allow"}

        if not ledger.get("ll_gate_passed", False):
            return {
                "decision": "deny",
                "reason": (
                    "ALE Pre-flight Gate: 'll_gate_passed' is false in the active ledger. "
                    "Run 'ledger.py gate' and 'red_gate.py' before modifying production files."
                ),
            }

        if not ledger.get("red_gate_passed", False) and not ledger.get("red_gate_exempt", False):
            return {
                "decision": "deny",
                "reason": (
                    f"ALE RED Gate: Record runtime RED via 'red_gate.py' (or '--exempt' for pure refactor/docs) "
                    f"before editing {target_path.replace(home_str, '~')}."
                ),
            }

    return {"decision": "allow"}


def has_unverified_git_changes(workspace_dir: str, base_sha: str | None) -> bool:
    """Check whether the workspace has uncommitted changes or commits ahead of base_sha."""
    if not base_sha or base_sha == "UNTRACKED":
        return False
    proc = subprocess.run(
        ["git", "-C", workspace_dir, "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return True
    head_proc = subprocess.run(
        ["git", "-C", workspace_dir, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if head_proc.returncode == 0 and head_proc.stdout.strip() != base_sha:
        return True
    return False


def handle_stop(payload: dict[str, Any], output_dir: str | None = None) -> dict[str, Any]:
    """Prevent premature turn completion when an active ALE ledger has unverified edits."""
    if payload.get("terminationReason", "NO_TOOL_CALL") != "NO_TOOL_CALL":
        return {"decision": "allow"}

    workspace_paths = payload.get("workspacePaths", [])
    ledger = load_active_ledger(workspace_paths, output_dir, include_verified=False)
    if not ledger:
        return {"decision": "allow"}

    if ledger.get("locked") is True or int(ledger.get("friction_count", 0)) >= 3:
        return {"decision": "allow"}

    if ledger.get("awaiting_user_approval") is True:
        return {"decision": "allow"}

    if has_active_dispatch_lease(ledger):
        return {"decision": "allow"}

    ws_dir = ledger.get("workspace_path", os.getcwd())
    if has_unverified_git_changes(ws_dir, ledger.get("base_sha")):
        if not ledger.get("done_recorded", False) or not ledger.get("review_verified", False):
            return {
                "decision": "continue",
                "reason": (
                    "ALE Stop Gate: Active session has modified files, but 'done_recorded' or "
                    "'review_verified' (Phase 4 Cross-Family Review) is incomplete. Complete "
                    "verification via 'ledger.py done' and 'model_router.py --role review' before stopping."
                ),
            }

    return {"decision": "allow"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the lifecycle hook handler."""
    parser = argparse.ArgumentParser(description="ALE PreToolUse and Stop hook gate.")
    parser.add_argument(
        "--event",
        choices=["PreToolUse", "Stop"],
        default="PreToolUse",
        help="Hook event type.",
    )
    parser.add_argument(
        "--output_dir",
        "--base_dir",
        dest="output_dir",
        default=None,
        help="Override base directory for ALE ledger files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Read hook JSON payload from stdin and emit decision JSON to stdout."""
    args = parse_args(argv)
    raw_input = sys.stdin.read().strip()
    payload: dict[str, Any] = {}
    if raw_input:
        try:
            payload = json.loads(raw_input)
        except json.JSONDecodeError:
            payload = {}

    if args.event == "Stop":
        result = handle_stop(payload, args.output_dir)
    else:
        result = handle_pre_tool_use(payload, args.output_dir)

    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
