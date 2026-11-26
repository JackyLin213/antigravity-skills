#!/usr/bin/env python3
"""Runtime RED Gate and Executable LESSONS_LEARNED Verification Check runner."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from ledger import (
    INVARIANT_SECTION_SPLIT_REGEX,
    SUPERSEDED_STATUS_REGEX,
    get_session_dir,
    load_ledger,
    save_ledger,
)


CHECK_LINE_REGEX = re.compile(
    r"^-\s+\*\*Verification Check\*\*:\s*`?([^`\n]+)`?\s*$",
    re.MULTILINE,
)
HEADER_ID_REGEX = re.compile(r"^###\s+\[([A-Z0-9-]+)\]\s+(.+)$", re.MULTILINE)


def parse_invariant_checks(markdown_path: Path) -> list[dict[str, str]]:
    """Extract active executable Verification Check directives from a LESSONS_LEARNED markdown file."""
    if not markdown_path.is_file():
        return []
    content = markdown_path.read_text(encoding="utf-8")
    sections = INVARIANT_SECTION_SPLIT_REGEX.split(content)
    checks: list[dict[str, str]] = []
    for section in sections:
        header_match = HEADER_ID_REGEX.search(section)
        check_match = CHECK_LINE_REGEX.search(section)
        if not header_match or not check_match:
            continue
        if SUPERSEDED_STATUS_REGEX.search(section):
            continue
        rule_id = header_match.group(1).strip()
        title = header_match.group(2).strip()
        raw_check = check_match.group(1).strip()
        if (raw_check.startswith("<") and raw_check.endswith(">")) or "<Title>" in title:
            continue
        checks.append({
            "id": rule_id,
            "title": title,
            "check": raw_check,
            "source": str(markdown_path),
        })
    return checks


def match_file_scope(rel_path_str: str, scope_glob: str | None) -> bool:
    """Return True if rel_path_str matches the optional 'path :: pattern' scope."""
    if not scope_glob:
        return True
    norm_rel = rel_path_str.replace("\\", "/")
    norm_scope = scope_glob.strip().replace("\\", "/")
    if norm_rel == norm_scope or Path(norm_rel).name == norm_scope:
        return True
    return fnmatch.fnmatch(norm_rel, norm_scope)


def scan_workspace_regex(
    workspace_dir: Path,
    raw_spec: str,
) -> tuple[list[str], str | None, str]:
    """Scan workspace files matching optional 'scope :: regex' with pruned directory traversal."""
    scope_glob: str | None = None
    pattern_str = raw_spec.strip()
    if " :: " in pattern_str:
        left, _, right = pattern_str.partition(" :: ")
        scope_glob = left.strip()
        pattern_str = right.strip()

    regex = re.compile(pattern_str)
    hits: list[str] = []
    for root_str, dirnames, filenames in os.walk(workspace_dir):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".venv")
        )
        for fname in sorted(filenames):
            path = Path(root_str) / fname
            if path.is_symlink():
                continue
            rel_str = str(path.relative_to(workspace_dir))
            if not match_file_scope(rel_str, scope_glob):
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if regex.search(text):
                hits.append(rel_str)
    return hits, scope_glob, pattern_str


def execute_single_check(item: dict[str, str], workspace_dir: Path) -> dict[str, Any]:
    """Run a single 'cmd:', 'regex-forbid:', or 'regex-require:' check against the workspace."""
    raw = item["check"]
    if raw.startswith("cmd:"):
        cmd_str = raw[len("cmd:"):].strip()
        try:
            proc = subprocess.run(
                cmd_str,
                shell=True,
                cwd=str(workspace_dir),
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            return {
                "id": item["id"],
                "check": raw,
                "passed": False,
                "detail": "Command timed out after 300s",
            }
        return {
            "id": item["id"],
            "check": raw,
            "passed": proc.returncode == 0,
            "detail": (proc.stdout + proc.stderr).strip()[:500],
        }

    if raw.startswith("regex-forbid:"):
        spec = raw[len("regex-forbid:"):].strip()
        try:
            hits, scope_glob, _ = scan_workspace_regex(workspace_dir, spec)
        except re.error as exc:
            return {
                "id": item["id"],
                "check": raw,
                "passed": False,
                "detail": f"Invalid regular expression: {exc}",
            }
        return {
            "id": item["id"],
            "check": raw,
            "scope": scope_glob,
            "passed": len(hits) == 0,
            "detail": f"Forbidden pattern matched in: {', '.join(hits)}" if hits else "Clean",
        }

    if raw.startswith("regex-require:"):
        spec = raw[len("regex-require:"):].strip()
        try:
            hits, scope_glob, _ = scan_workspace_regex(workspace_dir, spec)
        except re.error as exc:
            return {
                "id": item["id"],
                "check": raw,
                "passed": False,
                "detail": f"Invalid regular expression: {exc}",
            }
        return {
            "id": item["id"],
            "check": raw,
            "scope": scope_glob,
            "passed": len(hits) > 0,
            "detail": f"Required pattern matched in: {', '.join(hits)}" if hits else "Missing required pattern",
        }

    return {
        "id": item["id"],
        "check": raw,
        "passed": True,
        "detail": "Descriptive check (non-automated prefix); verified via manual LL_GATE review.",
    }


def run_all_ll_checks(ledger: dict[str, Any], workspace_dir: Path) -> tuple[bool, list[dict[str, Any]]]:
    """Run all executable checks across knowledgebase, repo, and session LESSONS_LEARNED files."""
    raw_sources = [
        ledger.get("kb_ll_path", ""),
        ledger.get("repo_ll_path", ""),
        ledger.get("session_ll_path", ""),
    ]
    all_items: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    for raw_src in raw_sources:
        if not raw_src or str(raw_src) in seen_paths:
            continue
        seen_paths.add(str(raw_src))
        for item in parse_invariant_checks(Path(str(raw_src))):
            if item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            all_items.append(item)

    results: list[dict[str, Any]] = []
    all_passed = True
    for item in all_items:
        res = execute_single_check(item, workspace_dir)
        results.append(res)
        if not res["passed"]:
            all_passed = False
    return all_passed, results


def classify_red_output(exit_code: int, stdout: str, stderr: str) -> str:
    """Distinguish valid test assertion failures from syntax/import/collection crashes."""
    combined = f"{stdout}\n{stderr}"
    if exit_code in (126, 127):
        return "COMMAND_NOT_FOUND"
    if any(token in combined for token in ("SyntaxError:", "IndentationError:", "ModuleNotFoundError:")):
        return "BUILD_OR_SYNTAX_ERROR"
    return "RUNTIME_TEST_RED"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for red_gate.py."""
    parser = argparse.ArgumentParser(description="Verify LL checks and record Runtime RED Gate.")
    parser.add_argument("--workspace", default=os.getcwd(), help="Target workspace directory.")
    parser.add_argument(
        "--output_dir",
        "--base_dir",
        dest="output_dir",
        default=None,
        help="Override base directory for ALE ledger outputs.",
    )
    parser.add_argument("--test_cmd", default=None, help="Command expected to fail on the target behavior (RED).")
    parser.add_argument("--exempt", action="store_true", help="Exempt from runtime RED (for pure refactor/docs).")
    parser.add_argument("--reason", default="", help="Justification when --exempt is used.")
    parser.add_argument("--verify_ll_only", action="store_true", help="Only run LESSONS_LEARNED checks.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint for red_gate.py."""
    args = parse_args(argv)
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    try:
        ledger = load_ledger(session_dir)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    ll_passed, ll_results = run_all_ll_checks(ledger, ws_dir)
    if not ll_passed:
        print(json.dumps({
            "status": "ll_checks_failed",
            "results": ll_results,
        }, indent=2), file=sys.stderr)
        return 1

    if args.verify_ll_only:
        print(json.dumps({"status": "ll_checks_passed", "results": ll_results}, indent=2))
        return 0

    if args.exempt:
        if not args.reason.strip():
            print("Error: --exempt requires a non-empty --reason.", file=sys.stderr)
            return 1
        ledger["red_gate_exempt"] = True
        ledger["red_gate_reason"] = args.reason.strip()
        save_ledger(session_dir, ledger)
        print(json.dumps({
            "status": "red_gate_exempt",
            "reason": args.reason.strip(),
            "ll_checks": ll_results,
        }, indent=2))
        return 0

    if not args.test_cmd:
        print("Error: Specify either --test_cmd '<cmd>' or --exempt --reason '<why>'.", file=sys.stderr)
        return 1

    try:
        proc = subprocess.run(
            args.test_cmd,
            shell=True,
            cwd=str(ws_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print(json.dumps({
            "status": "red_gate_rejected",
            "classification": "TIMEOUT",
            "reason": "RED test command timed out after 300s.",
            "test_cmd": args.test_cmd,
        }, indent=2), file=sys.stderr)
        return 1

    if proc.returncode == 0:
        print(json.dumps({
            "status": "red_gate_rejected",
            "reason": "Test command exited with 0 (GREEN). A RED gate must fail on the unimplemented/buggy behavior first.",
            "test_cmd": args.test_cmd,
        }, indent=2), file=sys.stderr)
        return 1

    classification = classify_red_output(proc.returncode, proc.stdout, proc.stderr)
    if classification != "RUNTIME_TEST_RED":
        print(json.dumps({
            "status": "red_gate_rejected",
            "classification": classification,
            "exit_code": proc.returncode,
            "reason": "Command failed due to syntax/import/missing-binary error rather than a runtime test assertion.",
            "stderr": proc.stderr[-1000:],
        }, indent=2), file=sys.stderr)
        return 1

    ledger["red_gate_passed"] = True
    ledger["red_test_cmd"] = args.test_cmd
    ledger["red_exit_code"] = proc.returncode
    ledger["red_output"] = f"{proc.stdout}\n{proc.stderr}".strip()[-1500:]
    save_ledger(session_dir, ledger)

    print(json.dumps({
        "status": "red_gate_recorded",
        "classification": classification,
        "exit_code": proc.returncode,
        "ll_checks_count": len(ll_results),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
