# Externalized Ledger & Lifecycle Hooks Specification

## 1. Ledger Storage & Output Override

ALE stores session state outside the target Git repository. `scripts/ledger.py` creates a deterministic workspace slug `<repo_name>-<sha256_prefix>` under:

```text
$HOME/tmp/ale_harness/
├── active_runtime_model.json   # Live model persisted by PreToolUse hook
├── models_cache.json           # Short-TTL cache of 'agy models' keyed by binary path
├── model_routing.json          # Optional user routing overrides (exclude, pin_role, prefer_effort)
└── <workspace_slug>/
    ├── ledger.json             # Machine-readable gate & state machine
    ├── SESSION_LL.md           # 5D Causal Chain buffer for the active task
    ├── baseline.patch          # Pre-existing dirty working tree snapshot (if dirty at init)
    ├── review_packet.md        # Uncapped diff, untracked files, and invariants for read-only review
    └── last_review_output.txt  # Raw output from the latest cross-family review
```

To redirect all state files during evaluations or custom workflows, set `ALE_OUTPUT_ROOT` or pass `--output_dir`:

```bash
export ALE_OUTPUT_ROOT="$HOME/tmp/eval_sandbox/agent-loop-engineering"
```

## 2. State Transitions in `ledger.json`

| Field | Default | Unlocked / Updated By | Enforced By |
| :--- | :--- | :--- | :--- |
| `status` | `"active"` | Auto-transitions to `"verified"` once `done_recorded` and `review_verified` both pass; `"completed"` via `ledger.py ruling --complete` (blocked while active `SLL-*` entries remain unresolved) | `pretool_gate.py` (`PreToolUse` & `Stop` hooks) and `ledger.py ruling` |
| `baseline_dirty_files` | `[]` | Populated by `ledger.py init` when uncommitted edits already exist in the repo | Injected into `review_packet.md` so reviewers distinguish prior work from session changes |
| `dispatch_in_progress` | `null` | Time-bounded lease (`900s` TTL + live PID check) refreshed by `model_router.py` before each fallback candidate | `pretool_gate.py` (`Stop` hook yields cleanly while lease is active) |
| `ll_gate_passed` | `false` | `ledger.py gate --checked ... --intent ...` | `pretool_gate.py` (`PreToolUse`: `edit_file\|write_file`) |
| `red_gate_passed` | `false` | `red_gate.py --test_cmd "..."` (or `--exempt`) | `pretool_gate.py` (`PreToolUse`: `edit_file\|write_file`) |
| `friction_count` | `0` | Incremented by `ledger.py friction` (resets `ll_gate_passed`) | Cycle 2 -> `STRIKE_BREAKER` (`ALE_SUBPROCESS_ROLE=strike-breaker`); Cycle 3 -> `locked = true` |
| `done_recorded` | `false` | `ledger.py done --verify_cmd "..."` (exit 0 required) | `pretool_gate.py` (`Stop` hook) |
| `review_verified` | `false` | `model_router.py --role review` (`VERIFIED`, or `VERIFIED_WITH_CAVEATS` with zero `must-fix` findings) | `pretool_gate.py` (`Stop` hook) |
| `allow_ship` | `false` | `ledger.py ruling --allow_ship` (after explicit user consent) | `pretool_gate.py` (`PreToolUse`: `run_command` ship regex on `active` and `verified` ledgers) |

## 3. Subprocess Role Isolation & Global Hook Integration

The global plugin at `~/.gemini/config/plugins/ale-harness/hooks.json` binds `pretool_gate.py` to `PreToolUse` and `Stop`.
- When `model_router.py` spawns a child `agy -p` process, it sets `ALE_SUBPROCESS_DISPATCH=1` and `ALE_SUBPROCESS_ROLE=<role>`.
- `review` and `judge` child processes are strictly read-only (`PreToolUse` denies `edit_file`, `write_file`, and `run_command`) while allowing `read_file` on `<session_dir>/review_packet.md` and workspace files.
- `research` child processes deny `edit_file` and `write_file`.
- `strike-breaker` child processes may edit files while `friction_count < 3` and `locked == false`, even after a preceding `friction` event reset `ll_gate_passed`.
