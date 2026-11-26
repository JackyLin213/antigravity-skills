#!/usr/bin/env python3
"""Dynamic Cross-Family Model Router and Full-Packet Review Dispatcher for ALE."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ledger import (
    INVARIANT_SECTION_SPLIT_REGEX,
    SUPERSEDED_STATUS_REGEX,
    detect_active_session_model,
    discover_servable_models,
    get_session_dir,
    load_ledger,
    model_family,
    normalize_model_id,
    resolve_counterpart_model,
    resolve_dynamic_defaults,
    resolve_fallback_chain,
    resolve_worker_model,
    save_ledger,
)


SENSITIVE_FILENAME_REGEX = re.compile(r"(?:secret|cred|token|\.env|private_key)", re.IGNORECASE)
MAX_INLINE_DIFF_CHARS = 55000
MAX_UNTRACKED_CHARS = 20000
MAX_PROMPT_BYTES = 95000
SOURCE_SUFFIXES = {".py", ".json", ".md", ".sh", ".toml", ".yaml", ".yml", ".ts", ".js"}
VALID_VERDICTS = {"VERIFIED", "VERIFIED_WITH_CAVEATS", "REFUTED"}


def list_servable_models(output_dir: str | None = None) -> list[dict[str, str]]:
    """Query 'agy models' (via ledger registry) to discover live servable models on the host."""
    return discover_servable_models(output_dir, refresh=True)


def select_model_for_role(
    ledger: dict[str, Any],
    role: str,
    override: str | None = None,
    output_dir: str | None = None,
) -> tuple[str, str, str]:
    """Determine (target_model, active_impl_model, routing_reason) using dynamic latest-model discovery."""
    live_model, detect_src = detect_active_session_model(output_dir)
    stored_impl = str(ledger.get("impl_model", "")).strip()
    if stored_impl and ledger.get("model_detection_source") == "cli:--author_model":
        active_impl = normalize_model_id(stored_impl, output_dir)
        impl_src = "ledger:impl_model"
    else:
        default_balanced = resolve_dynamic_defaults(output_dir)["gemini_balanced"]
        active_impl = normalize_model_id(live_model or stored_impl or default_balanced, output_dir)
        impl_src = detect_src

    tier = int(ledger.get("tier", 2))

    if role in ("research", "fast-exec"):
        target = resolve_worker_model(
            role, active_impl, tier=tier, explicit_model=override, output_dir=output_dir
        )
        return target, active_impl, f"dynamic_worker_role (role={role}, tier={tier}, impl={active_impl})"

    if role == "implement":
        target = normalize_model_id(override, output_dir) if override else active_impl
        return target, active_impl, f"primary_implement ({impl_src})"

    if role in ("review", "judge", "strike-breaker"):
        effective_tier = 3 if role == "strike-breaker" else tier
        counterpart = resolve_counterpart_model(
            active_impl,
            str(override) if override else None,
            tier=effective_tier,
            role=role,
            output_dir=output_dir,
        )
        reason = (
            f"cross_family_switch (tier={effective_tier}, role={role}): "
            f"active '{active_impl}' ({model_family(active_impl, output_dir)}) "
            f"-> counterpart '{counterpart}' ({model_family(counterpart, output_dir)}) via {impl_src}"
        )
        return counterpart, active_impl, reason

    return (
        resolve_counterpart_model(active_impl, None, tier=tier, role=role, output_dir=output_dir),
        active_impl,
        "default_counterpart",
    )


def collect_untracked_files_context(
    workspace_dir: Path,
    porcelain_status: str,
    max_total_chars: int = MAX_UNTRACKED_CHARS,
) -> tuple[str, bool]:
    """Read safe untracked source/test files reported by 'git status --porcelain'."""
    resolved_ws = workspace_dir.resolve()
    untracked_paths: list[Path] = []
    for line in porcelain_status.splitlines():
        if not line.startswith("?? "):
            continue
        rel_raw = line[3:].strip().strip('"')
        raw_path = workspace_dir / rel_raw
        if raw_path.is_symlink():
            continue
        candidate = raw_path.resolve()
        if not candidate.is_relative_to(resolved_ws):
            continue
        if (
            candidate.is_file()
            and candidate.suffix in SOURCE_SUFFIXES
            and not SENSITIVE_FILENAME_REGEX.search(candidate.name)
        ):
            untracked_paths.append(candidate)
        elif candidate.is_dir():
            for root_str, dirnames, filenames in os.walk(candidate):
                dirnames[:] = sorted(
                    d for d in dirnames if not d.startswith(".") and d not in ("__pycache__", "node_modules")
                )
                for fname in sorted(filenames):
                    child = Path(root_str) / fname
                    if child.is_symlink():
                        continue
                    resolved_child = child.resolve()
                    if not resolved_child.is_relative_to(resolved_ws):
                        continue
                    if (
                        resolved_child.is_file()
                        and resolved_child.suffix in SOURCE_SUFFIXES
                        and not SENSITIVE_FILENAME_REGEX.search(resolved_child.name)
                    ):
                        untracked_paths.append(resolved_child)

    blocks: list[str] = []
    total_chars = 0
    truncated = False
    per_file_cap = 12000 if max_total_chars > 0 else 10_000_000
    shown = untracked_paths[:8] if max_total_chars > 0 else untracked_paths
    for fpath in shown:
        try:
            rel = fpath.relative_to(resolved_ws)
            full_text = fpath.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        snippet = full_text[:per_file_cap]
        if len(full_text) > per_file_cap:
            snippet += f"\n[TRUNCATED: shown {per_file_cap} of {len(full_text)} chars]"
            truncated = True
        block = f"#### Untracked File: `{rel}`\n```\n{snippet}\n```"
        blocks.append(block)
        total_chars += len(block)
        if max_total_chars > 0 and total_chars >= max_total_chars:
            truncated = True
            break
    if len(untracked_paths) > len(shown):
        omitted = [str(p.relative_to(resolved_ws)) for p in untracked_paths[len(shown):]]
        blocks.append(f"Untracked files omitted ({len(omitted)}): {', '.join(omitted[:20])}")
        truncated = True
    return "\n\n".join(blocks), truncated


def _collect_non_git_snapshots(
    workspace_dir: Path,
    priority_hints: str,
    max_files: int,
    max_total_chars: int,
) -> tuple[str, bool]:
    """Collect recent source snapshots when the workspace is not a Git repository."""
    cutoff = time.time() - 7200
    recent_files: list[tuple[int, float, Path]] = []
    for root_str, dirnames, filenames in os.walk(workspace_dir):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in ("__pycache__", "node_modules")
        )
        for fname in filenames:
            candidate = Path(root_str) / fname
            if (
                candidate.is_symlink()
                or candidate.suffix not in SOURCE_SUFFIXES
                or SENSITIVE_FILENAME_REGEX.search(candidate.name)
            ):
                continue
            try:
                stat_info = candidate.stat()
                if stat_info.st_size > 1_000_000:
                    continue
                mtime = stat_info.st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                is_named = 1 if (candidate.name in priority_hints) else 0
                recent_files.append((is_named, mtime, candidate))
    recent_files.sort(key=lambda item: (item[0], item[1]), reverse=True)

    snapshots: list[str] = []
    total_chars = 0
    truncated = False
    per_file_cap = 22000 if max_total_chars > 0 else 10_000_000
    shown_files = recent_files[:max_files] if max_files > 0 else recent_files
    for _, _, fpath in shown_files:
        rel = fpath.relative_to(workspace_dir)
        full_text = fpath.read_text(encoding="utf-8", errors="replace")
        text = full_text[:per_file_cap]
        if len(full_text) > per_file_cap:
            text += f"\n[TRUNCATED: shown {per_file_cap} of {len(full_text)} chars]"
            truncated = True
        block = f"#### Modified File: `{rel}`\n```\n{text}\n```"
        snapshots.append(block)
        total_chars += len(block)
        if max_total_chars > 0 and total_chars >= max_total_chars:
            truncated = True
            break
    if len(recent_files) > len(shown_files):
        omitted_names = [str(f.relative_to(workspace_dir)) for _, _, f in recent_files[len(shown_files):]]
        snapshots.append(f"Modified files omitted ({len(omitted_names)}): {', '.join(omitted_names[:20])}")
        truncated = True
    body = "\n\n".join(snapshots) if snapshots else "No recent file snapshots found."
    return f"### Non-Git / Untracked Workspace Modified File Snapshots\n{body}", truncated


def collect_git_diff_context(
    workspace_dir: Path,
    base_sha: str | None,
    priority_hints: str = "",
    max_diff_chars: int = MAX_INLINE_DIFF_CHARS,
    baseline_dirty_files: list[str] | None = None,
) -> str:
    """Collect git status, diff stat manifest, git diff, and untracked files (or snapshots)."""
    bundle, _ = collect_diff_bundle(
        workspace_dir,
        base_sha,
        priority_hints=priority_hints,
        max_diff_chars=max_diff_chars,
        baseline_dirty_files=baseline_dirty_files,
    )
    return bundle


def collect_diff_bundle(
    workspace_dir: Path,
    base_sha: str | None,
    priority_hints: str = "",
    max_diff_chars: int = MAX_INLINE_DIFF_CHARS,
    baseline_dirty_files: list[str] | None = None,
) -> tuple[str, bool]:
    """Return (formatted_diff_markdown, was_truncated) with baseline dirty-tree attribution."""
    status_proc = subprocess.run(
        ["git", "-C", str(workspace_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    stat_cmd = ["git", "-C", str(workspace_dir), "diff", "--stat"]
    diff_cmd = ["git", "-C", str(workspace_dir), "diff"]
    if base_sha and base_sha != "UNTRACKED":
        stat_cmd.append(base_sha)
        diff_cmd.append(base_sha)
    stat_proc = subprocess.run(stat_cmd, capture_output=True, text=True, check=False)
    diff_proc = subprocess.run(diff_cmd, capture_output=True, text=True, check=False)

    raw_diff = diff_proc.stdout
    truncated = False
    if max_diff_chars > 0 and len(raw_diff) > max_diff_chars:
        diff_text = raw_diff[:max_diff_chars] + f"\n[DIFF TRUNCATED AT {max_diff_chars} OF {len(raw_diff)} CHARS]"
        truncated = True
    else:
        diff_text = raw_diff

    untracked_cap = MAX_UNTRACKED_CHARS if max_diff_chars > 0 else 0
    untracked_bundle, untracked_trunc = collect_untracked_files_context(
        workspace_dir, status_proc.stdout, max_total_chars=untracked_cap
    )
    truncated = truncated or untracked_trunc

    if diff_text.strip() or untracked_bundle.strip():
        parts = [f"### Git Status\n```\n{status_proc.stdout.strip()}\n```"]
        if baseline_dirty_files:
            parts.append(
                "### Pre-Existing Dirty Baseline Files (Present Before `ledger.py init`)\n"
                + "\n".join(f"- `{item}`" for item in baseline_dirty_files[:40])
            )
        if stat_proc.stdout.strip():
            parts.append(f"### Changed Files Manifest (`git diff --stat`)\n```\n{stat_proc.stdout.strip()}\n```")
        if diff_text.strip():
            parts.append(f"### Git Diff\n```diff\n{diff_text}\n```")
        if untracked_bundle.strip():
            parts.append(f"### Untracked Workspace Files\n{untracked_bundle}")
        return "\n\n".join(parts), truncated

    snap_limit = 10 if max_diff_chars > 0 else 0
    snap_chars = 65000 if max_diff_chars > 0 else 0
    return _collect_non_git_snapshots(workspace_dir, priority_hints, snap_limit, snap_chars)


def _extract_active_invariant_blocks(content: str) -> list[str]:
    """Return active (non-superseded, non-dismissed, non-promoted) ### [ID] sections."""
    blocks: list[str] = []
    for sec in INVARIANT_SECTION_SPLIT_REGEX.split(content):
        if not sec.lstrip().startswith("### ["):
            continue
        if SUPERSEDED_STATUS_REGEX.search(sec):
            continue
        blocks.append(sec.strip())
    return blocks


def load_active_session_ll(ledger: dict[str, Any]) -> str:
    """Load only active (unpromoted/undismissed) invariants from SESSION_LL.md."""
    session_ll_path = Path(str(ledger.get("session_ll_path", "")))
    if not session_ll_path.is_file():
        return "No active session invariants."
    try:
        content = session_ll_path.read_text(encoding="utf-8")
    except OSError:
        return "No active session invariants."
    blocks = _extract_active_invariant_blocks(content)
    return "\n\n".join(blocks) if blocks else "No active session invariants."


def load_active_project_ll(ledger: dict[str, Any]) -> str:
    """Load deduplicated active invariants from project LESSONS_LEARNED.md files."""
    active_blocks: list[str] = []
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    for key in ("kb_ll_path", "repo_ll_path"):
        raw = str(ledger.get(key, "")).strip()
        if not raw or raw in seen_paths:
            continue
        seen_paths.add(raw)
        path = Path(raw)
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for block in _extract_active_invariant_blocks(content):
            id_match = re.match(r"^###\s+\[([A-Z0-9-]+)\]", block)
            rule_id = id_match.group(1) if id_match else block[:40]
            if rule_id in seen_ids:
                continue
            seen_ids.add(rule_id)
            active_blocks.append(block)
    combined = "\n\n".join(active_blocks)
    return combined[:12000] if combined else "No project-level LESSONS_LEARNED entries recorded."


def write_full_review_packet(
    session_dir: Path,
    ledger: dict[str, Any],
    workspace_dir: Path,
    extra_prompt: str,
) -> tuple[Path, str, bool]:
    """Write uncapped review context to <session_dir>/review_packet.md and return inline diff + truncated flag."""
    hints = f"{ledger.get('task', '')} {ledger.get('intent_line', '')} {ledger.get('verify_cmd', '')} {extra_prompt}"
    baseline_dirty = ledger.get("baseline_dirty_files") or []
    full_diff_bundle, _ = collect_diff_bundle(
        workspace_dir,
        ledger.get("base_sha"),
        priority_hints=hints,
        max_diff_chars=0,
        baseline_dirty_files=baseline_dirty,
    )
    inline_diff_bundle, was_truncated = collect_diff_bundle(
        workspace_dir,
        ledger.get("base_sha"),
        priority_hints=hints,
        max_diff_chars=MAX_INLINE_DIFF_CHARS,
        baseline_dirty_files=baseline_dirty,
    )
    session_ll = load_active_session_ll(ledger)
    project_ll = load_active_project_ll(ledger)
    verify_out = str(ledger.get("verify_output", "")).strip()

    packet_path = session_dir / "review_packet.md"
    packet_content = (
        f"# ALE Full Review Packet\n\n"
        f"- **Task**: {ledger.get('task')}\n"
        f"- **Declared Intent**: {ledger.get('intent_line')}\n"
        f"- **Base SHA**: `{ledger.get('base_sha')}`\n"
        f"- **Verification Command**: `{ledger.get('verify_cmd')}`\n\n"
        f"## Verification Output\n```\n{verify_out}\n```\n\n"
        f"## Active Session Invariants (SESSION_LL)\n{session_ll}\n\n"
        f"## Active Project Invariants (PROJECT_LL)\n{project_ll}\n\n"
        f"{full_diff_bundle}\n\n"
        f"{extra_prompt}\n"
    )
    packet_path.write_text(packet_content, encoding="utf-8")
    return packet_path, inline_diff_bundle, was_truncated


def build_role_prompt(
    role: str,
    ledger: dict[str, Any],
    workspace_dir: Path,
    extra_prompt: str,
    session_dir: Path | None = None,
) -> str:
    """Build an isolated prompt for the target model role, referencing full review_packet.md when truncated."""
    session_ll = load_active_session_ll(ledger)
    project_ll = load_active_project_ll(ledger)
    red_summary = (
        f"cmd='{ledger.get('red_test_cmd')}', "
        f"exit_code={ledger.get('red_exit_code')}, "
        f"exempt={ledger.get('red_gate_exempt')}, "
        f"output={ledger.get('red_output', 'AssertionError recorded')}"
    )
    verify_out = str(ledger.get("verify_output", "")).strip()[-8000:]

    if role in ("review", "judge"):
        resolved_sdir = session_dir or Path(str(ledger.get("session_dir", workspace_dir)))
        packet_path, inline_diff_bundle, was_truncated = write_full_review_packet(
            resolved_sdir, ledger, workspace_dir, extra_prompt
        )
        if was_truncated:
            read_guidance = (
                f"IMPORTANT: The inline diff below was truncated. The complete, uncapped diff and context "
                f"are saved at `{packet_path}`. Use `read_file` on `{packet_path}` or workspace source/test "
                f"files to inspect any omitted hunks or callers before deciding your verdict. "
                f"Do NOT modify files or execute shell commands."
            )
        else:
            read_guidance = (
                f"IMPORTANT: All diffs, RED gate evidence, and verification outputs are provided inline below "
                f"(full copy also at `{packet_path}`). You may use `read_file` if you need to check callers "
                f"outside the diff, but do NOT modify files or execute shell commands."
            )
        return (
            "You are an independent, cross-family Adversarial Reviewer combining /fable-judge, "
            "/ponytail-review, and /code-review.\n"
            f"Task: {ledger.get('task')}\n"
            f"Declared Intent: {ledger.get('intent_line')}\n"
            f"RED Gate Evidence: {red_summary}\n"
            f"Claimed Verification Command: {ledger.get('verify_cmd')}\n"
            f"Verification Command Output:\n```\n{verify_out}\n```\n\n"
            "Evaluate the change across three strict axes:\n"
            "1. Fable Judge (6 AI Frauds): Weakened checks/assertions, false completion, scope creep, "
            "unauthorized outward action, spec betrayal, leftover debug debris.\n"
            "2. Ponytail Review (On-Call Senior Dev): Bugs/edge cases, security/data-loss risk, scale under load, "
            "broken callers outside the diff, missing tests on risky branches, and YAGNI bloat to delete.\n"
            "3. Active Invariants: Compliance with all SESSION_LL and active PROJECT_LL rules below.\n\n"
            f"{read_guidance}\n"
            "Return ONLY valid JSON matching the requested schema with fields: "
            "verdict ('VERIFIED' | 'VERIFIED_WITH_CAVEATS' | 'REFUTED'), summary, findings (list of objects "
            "with axis, severity, file_or_surface, issue, smallest_fix), and suggested_invariant.\n\n"
            f"### Active Session Invariants (SESSION_LL)\n{session_ll}\n\n"
            f"### Active Project Invariants (PROJECT_LL)\n{project_ll}\n\n"
            f"{inline_diff_bundle}\n\n"
            f"{extra_prompt}"
        )

    if role == "strike-breaker":
        hints = f"{ledger.get('task', '')} {ledger.get('intent_line', '')} {extra_prompt}"
        diff_bundle, _ = collect_diff_bundle(
            workspace_dir,
            ledger.get("base_sha"),
            priority_hints=hints,
            max_diff_chars=MAX_INLINE_DIFF_CHARS,
            baseline_dirty_files=ledger.get("baseline_dirty_files") or [],
        )
        return (
            "You are the Cross-Family Strike-Breaker model called at Friction Cycle 2/3.\n"
            "The primary implementation model hit repeated friction on this task. "
            "Analyze the accumulated 5D Causal Chains in SESSION_LL, the active PROJECT_LL environment constraints "
            "(including any remote/NAS write constraints), and the current diff cleanly from first principles. "
            "Identify the blind spot or false assumption, and provide the smallest complete fix (/ponytail YAGNI ladder).\n\n"
            f"Task: {ledger.get('task')}\n\n"
            f"### Session Lessons Learned (SESSION_LL)\n{session_ll}\n\n"
            f"### Active Project Invariants (PROJECT_LL)\n{project_ll}\n\n"
            f"{diff_bundle}\n\n"
            f"### Additional Context\n{extra_prompt}\n"
        )

    return f"Task ({role}): {ledger.get('task')}\n\n{extra_prompt}"


def is_sandbox_allowed_for_dry_run(workspace_dir: Path) -> bool:
    """Return True only when the resolved workspace_dir is inside $HOME/tmp/eval_sandbox."""
    sandbox_root = (Path.home() / "tmp" / "eval_sandbox").resolve()
    resolved_ws = Path(workspace_dir).expanduser().resolve()
    return resolved_ws.is_relative_to(sandbox_root)


def build_agy_command(
    agy_bin: str,
    model_id: str,
    prompt: str,
    workspace_dir: Path,
    schema_path: Path | None = None,
    extra_dirs: list[Path] | None = None,
) -> list[str]:
    """Construct the exact 'agy -p' CLI command list safely under Linux argv byte limits."""
    encoded = prompt.encode("utf-8")
    if len(encoded) > MAX_PROMPT_BYTES:
        notice = "\n\n[PROMPT TRUNCATED AT BYTE CAP; INSPECT review_packet.md VIA read_file]\n"
        safe_prompt = encoded[: MAX_PROMPT_BYTES - len(notice.encode("utf-8"))].decode("utf-8", errors="ignore") + notice
    else:
        safe_prompt = prompt

    cmd = [
        agy_bin,
        "-p",
        safe_prompt,
        "--model",
        model_id,
        "--add-dir",
        str(workspace_dir),
        "--disable-slash-commands",
    ]
    for extra_dir in extra_dirs or []:
        if str(extra_dir) != str(workspace_dir):
            cmd.extend(["--add-dir", str(extra_dir)])
    if schema_path and schema_path.is_file():
        cmd.extend(["--output-format", "json", "--json-schema", str(schema_path)])
    return cmd


def _parse_json_payload(raw_text: str) -> dict[str, Any] | None:
    """Extract and decode a JSON object from stdout, tolerating markdown fences or prefix log lines."""
    cleaned = raw_text.strip()
    if not cleaned:
        return None
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            cleaned = cleaned[brace_start : brace_end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def is_cli_error_envelope(raw_text: str) -> bool:
    """Return True if raw_text contains an agy CLI error JSON envelope (e.g. quota exhaustion)."""
    if not raw_text.strip():
        return True
    parsed = _parse_json_payload(raw_text)
    if not isinstance(parsed, dict):
        return False
    return parsed.get("is_error") is True or str(parsed.get("status", "")).upper() == "ERROR"


def workspace_mutation_fingerprint(workspace_dir: Path) -> str:
    """Return a workspace state fingerprint covering both Git repos and non-Git directories."""
    git_check = subprocess.run(
        ["git", "-C", str(workspace_dir), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if git_check.returncode == 0 and git_check.stdout.strip() == "true":
        status = subprocess.run(
            ["git", "-C", str(workspace_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        diff = subprocess.run(
            ["git", "-C", str(workspace_dir), "diff"],
            capture_output=True,
            text=True,
            check=False,
        )
        return f"git:\n{status.stdout}\n---\n{diff.stdout}"

    digest = hashlib.sha256()
    for root_str, dirnames, filenames in os.walk(workspace_dir):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".venv")
        )
        for fname in sorted(filenames):
            fpath = Path(root_str) / fname
            if fpath.is_symlink():
                continue
            try:
                rel = str(fpath.relative_to(workspace_dir))
                st = fpath.stat()
                digest.update(f"{rel}:{st.st_size}:{st.st_mtime_ns}\n".encode("utf-8"))
            except (OSError, ValueError):
                continue
    return f"fs:{digest.hexdigest()}"


def invoke_single_agy_call(
    agy_bin: str,
    model_id: str,
    prompt: str,
    workspace_dir: Path,
    schema_path: Path | None = None,
    role: str = "review",
    extra_dirs: list[Path] | None = None,
) -> tuple[int, str, str]:
    """Run one subprocess call to 'agy -p --model <model_id>' with subprocess role isolation."""
    cmd = build_agy_command(
        agy_bin, model_id, prompt, workspace_dir, schema_path=schema_path, extra_dirs=extra_dirs
    )
    child_env = {
        **os.environ,
        "ALE_SUBPROCESS_DISPATCH": "1",
        "ALE_SUBPROCESS_ROLE": role,
    }
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace_dir),
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"Error: 'agy' model '{model_id}' timed out after 300s."
    except OSError as exc:
        return 1, "", f"Error launching 'agy' for model '{model_id}': {exc}"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def invoke_agy_model(
    model_id: str,
    prompt: str,
    workspace_dir: Path,
    schema_path: Path | None = None,
    dry_run: bool = False,
    output_dir: str | None = None,
    role: str = "review",
    fallback_models: list[str] | None = None,
    extra_dirs: list[Path] | None = None,
    on_attempt: Callable[[str], None] | None = None,
    attempt_meta: dict[str, Any] | None = None,
) -> tuple[int, str, str]:
    """Execute a cross-model call via 'agy -p', advancing fallback on exit errors or CLI error envelopes."""
    _ = output_dir
    if dry_run or os.environ.get("ALE_ROUTER_DRY_RUN") == "1":
        if not is_sandbox_allowed_for_dry_run(workspace_dir):
            return (
                2,
                "",
                (
                    "Error: --dry_run is strictly restricted to eval_sandbox directories. "
                    "Live cross-family model execution is mandatory in production workspaces."
                ),
            )
        synthetic = {
            "status": "SUCCESS",
            "structured_output": {
                "verdict": "VERIFIED",
                "summary": f"Dry-run cross-family verification passed on model {model_id}.",
                "findings": [],
                "suggested_invariant": None,
            },
        }
        if attempt_meta is not None:
            attempt_meta["used_model"] = model_id
            attempt_meta["attempted_models"] = [model_id]
        return 0, json.dumps(synthetic), ""

    agy_bin = shutil.which("agy")
    if not agy_bin:
        return 127, "", "Error: 'agy' CLI binary not found in PATH."

    candidates = [model_id] + [m for m in (fallback_models or []) if m != model_id]
    last_code, last_out, last_err = 1, "", ""
    attempted: list[str] = []
    pre_fingerprint = workspace_mutation_fingerprint(workspace_dir) if role == "strike-breaker" else ""

    for candidate in candidates:
        attempted.append(candidate)
        if on_attempt is not None:
            on_attempt(candidate)
        code, stdout, stderr = invoke_single_agy_call(
            agy_bin,
            candidate,
            prompt,
            workspace_dir,
            schema_path=schema_path,
            role=role,
            extra_dirs=extra_dirs,
        )
        if code == 0 and stdout and not is_cli_error_envelope(stdout):
            if attempt_meta is not None:
                attempt_meta["used_model"] = candidate
                attempt_meta["attempted_models"] = attempted
            return 0, stdout, stderr

        last_code = code if code != 0 else 1
        last_out = stdout
        last_err = stderr or stdout[-500:]

        if role == "strike-breaker":
            post_fingerprint = workspace_mutation_fingerprint(workspace_dir)
            if post_fingerprint != pre_fingerprint:
                last_err = (
                    f"Strike-breaker candidate '{candidate}' failed after modifying workspace files; "
                    f"halting fallback to prevent conflicting edits. Detail: {last_err}"
                )
                break

    if attempt_meta is not None:
        attempt_meta["used_model"] = attempted[-1] if attempted else model_id
        attempt_meta["attempted_models"] = attempted
    return last_code, last_out, last_err


def extract_json_object(raw_text: str) -> dict[str, Any] | None:
    """Parse a JSON object from model stdout, unwrapping 'agy --output-format json' envelopes."""
    parsed = _parse_json_payload(raw_text)
    if not isinstance(parsed, dict):
        return None
    if parsed.get("is_error") is True or str(parsed.get("status", "")).upper() == "ERROR":
        return {
            "verdict": "REFUTED",
            "summary": str(parsed.get("error") or parsed.get("response") or "CLI error envelope"),
            "findings": [],
            "suggested_invariant": None,
        }
    structured = parsed.get("structured_output")
    if isinstance(structured, dict):
        return structured
    if isinstance(structured, str):
        unwrapped_struct = extract_json_object(structured)
        if unwrapped_struct is not None:
            return unwrapped_struct
    inner_resp = parsed.get("response")
    if isinstance(inner_resp, str) and "verdict" not in parsed:
        unwrapped = extract_json_object(inner_resp)
        if unwrapped is not None:
            return unwrapped
    return parsed


def evaluate_review_verdict(verdict_obj: dict[str, Any] | None) -> tuple[bool, str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Evaluate a review verdict JSON, rejecting VERIFIED_WITH_CAVEATS when must-fix findings exist."""
    if not isinstance(verdict_obj, dict):
        return False, "REFUTED", [], []
    raw_verdict = str(verdict_obj.get("verdict", "REFUTED")).strip().upper()
    verdict = raw_verdict if raw_verdict in VALID_VERDICTS else "REFUTED"
    raw_findings = verdict_obj.get("findings", [])
    findings = [f for f in raw_findings if isinstance(f, dict)] if isinstance(raw_findings, list) else []
    must_fix = [f for f in findings if str(f.get("severity", "")).strip().lower() == "must-fix"]
    should_fix = [f for f in findings if str(f.get("severity", "")).strip().lower() == "should-fix"]

    if verdict == "VERIFIED" and not must_fix:
        return True, verdict, must_fix, should_fix
    if verdict == "VERIFIED_WITH_CAVEATS" and not must_fix:
        return True, verdict, must_fix, should_fix
    return False, verdict, must_fix, should_fix


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for model_router.py."""
    parser = argparse.ArgumentParser(description="ALE Cross-Family Model Router and Review Dispatcher.")
    parser.add_argument("--workspace", default=os.getcwd(), help="Target workspace directory.")
    parser.add_argument(
        "--output_dir",
        "--base_dir",
        dest="output_dir",
        default=None,
        help="Override base directory for ALE ledger outputs.",
    )
    parser.add_argument(
        "--role",
        choices=["models", "research", "fast-exec", "implement", "strike-breaker", "review", "judge"],
        default="review",
        help="Routing role to execute.",
    )
    parser.add_argument("--model", default=None, help="Explicit model ID override.")
    parser.add_argument("--prompt", default="", help="Additional prompt instructions or question.")
    parser.add_argument("--dry_run", action="store_true", help="Simulate model invocation for hermetic tests.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint for model_router.py."""
    args = parse_args(argv)
    if args.role == "models":
        models = list_servable_models(args.output_dir)
        resolved = resolve_dynamic_defaults(args.output_dir)
        print(json.dumps({
            "servable_models": models,
            "count": len(models),
            "dynamic_defaults": resolved,
        }, indent=2))
        return 0

    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    try:
        ledger = load_ledger(session_dir)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    target_model, active_impl, routing_reason = select_model_for_role(
        ledger, args.role, args.model, args.output_dir
    )
    fallback_chain = resolve_fallback_chain(active_impl, target_model, args.output_dir)
    ledger["impl_model"] = active_impl
    if args.role in ("review", "judge", "strike-breaker"):
        ledger["counterpart_model"] = target_model
        ledger["fallback_chain"] = fallback_chain
    prompt = build_role_prompt(args.role, ledger, ws_dir, args.prompt, session_dir=session_dir)
    schema_path: Path | None = None
    if args.role in ("review", "judge"):
        schema_path = Path(__file__).resolve().parent.parent / "templates" / "review-verdict.schema.json"

    def _refresh_lease(active_candidate: str) -> None:
        """Refresh the async dispatch lease before attempting each fallback candidate."""
        current = load_ledger(session_dir)
        current["dispatch_in_progress"] = {
            "role": args.role,
            "model": active_candidate,
            "pid": os.getpid(),
            "started_at": time.time(),
        }
        save_ledger(session_dir, current)

    ledger["dispatch_in_progress"] = {
        "role": args.role,
        "model": target_model,
        "pid": os.getpid(),
        "started_at": time.time(),
    }
    save_ledger(session_dir, ledger)

    attempt_meta: dict[str, Any] = {}
    try:
        code, stdout, stderr = invoke_agy_model(
            target_model,
            prompt,
            ws_dir,
            schema_path=schema_path,
            dry_run=args.dry_run,
            output_dir=args.output_dir,
            role=args.role,
            fallback_models=fallback_chain if args.role in ("review", "judge", "strike-breaker") else None,
            extra_dirs=[session_dir] if args.role in ("review", "judge") else None,
            on_attempt=_refresh_lease,
            attempt_meta=attempt_meta,
        )
    finally:
        ledger = load_ledger(session_dir)
        ledger["dispatch_in_progress"] = None
        save_ledger(session_dir, ledger)

    used_model = str(attempt_meta.get("used_model") or target_model)
    attempted_models = attempt_meta.get("attempted_models", [target_model])

    if code != 0:
        if args.role in ("review", "judge"):
            ledger["review_verified"] = False
            save_ledger(session_dir, ledger)
        print(json.dumps({
            "status": "dispatch_error",
            "role": args.role,
            "active_impl_model": active_impl,
            "model": used_model,
            "attempted_models": attempted_models,
            "fallback_chain": fallback_chain,
            "routing_reason": routing_reason,
            "exit_code": code,
            "stderr": stderr[-1000:],
        }, indent=2), file=sys.stderr)
        return code if code == 2 else 1

    artifact_file = session_dir / f"last_{args.role}_output.txt"
    artifact_file.write_text(stdout, encoding="utf-8")

    if args.role in ("review", "judge"):
        ledger["review_rounds"] = int(ledger.get("review_rounds", 0)) + 1
        ledger["review_mode"] = (
            "dry_run"
            if (args.dry_run or os.environ.get("ALE_ROUTER_DRY_RUN") == "1")
            else "live"
        )
        verdict_obj = extract_json_object(stdout)
        passed, verdict, must_fix, should_fix = evaluate_review_verdict(verdict_obj)
        if passed:
            ledger["review_verified"] = True
            if ledger.get("done_recorded") is True:
                ledger["status"] = "verified"
            save_ledger(session_dir, ledger)
            print(json.dumps({
                "status": "review_passed",
                "ledger_status": ledger["status"],
                "active_impl_model": active_impl,
                "model": used_model,
                "attempted_models": attempted_models,
                "fallback_chain": fallback_chain,
                "routing_reason": routing_reason,
                "verdict": verdict,
                "review_rounds": ledger["review_rounds"],
                "open_should_fix_count": len(should_fix),
                "open_should_fix": should_fix,
                "details": verdict_obj or stdout[:1000],
            }, indent=2))
            return 0

        ledger["review_verified"] = False
        save_ledger(session_dir, ledger)
        reason_hint = (
            f"Blocked by {len(must_fix)} must-fix finding(s) despite verdict={verdict}. "
            if must_fix
            else ""
        )
        print(json.dumps({
            "status": "review_refuted",
            "active_impl_model": active_impl,
            "model": used_model,
            "attempted_models": attempted_models,
            "fallback_chain": fallback_chain,
            "routing_reason": routing_reason,
            "verdict": verdict,
            "must_fix_count": len(must_fix),
            "review_rounds": ledger["review_rounds"],
            "directive": f"{reason_hint}Route to Phase 3: record 5D friction via 'ledger.py friction'.",
            "details": verdict_obj or stdout[:1000],
        }, indent=2), file=sys.stderr)
        return 1

    print(json.dumps({
        "status": "dispatched",
        "role": args.role,
        "active_impl_model": active_impl,
        "model": used_model,
        "attempted_models": attempted_models,
        "fallback_chain": fallback_chain,
        "routing_reason": routing_reason,
        "output_path": str(artifact_file),
        "response": stdout[:2000],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
