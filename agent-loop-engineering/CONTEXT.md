# Antigravity Agent Harness & Skills Ecosystem

Defines the core domain vocabulary for orchestrating autonomous agent loops, always-on rules, and cross-model verification across the skill suite.

## Language

**Harness**:
The deterministic control layer surrounding an LLM session—comprising lifecycle hooks, externalized state ledgers, executable checks, and model dispatchers—that enforces behavioral boundaries outside the model's own prompt compliance.
_Avoid_: Wrapper, prompt template, workflow

**Always-On Rule**:
A concise, permanently loaded constraint (living in `~/.gemini/config/plugins/ale-harness/rules/AGENTS.md`) that governs every conversational turn, including daily Q&A and ad-hoc edits.
_Avoid_: System prompt, global skill, passive doc

**On-Demand Skill**:
A multi-phase procedural runbook (`SKILL.md`) loaded via progressive disclosure when triggered by a slash command or matching task intent.
_Avoid_: Rule, plugin, macro

**Ledger**:
The externalized per-workspace state file (`$HOME/tmp/ale_harness/<workspace_slug>/ledger.json`, overridable via `ALE_OUTPUT_ROOT`) that records `Tier · Type`, `plan.md` SHA-256, `RED Gate`, `LL_GATE`, `Friction Count`, `DONE` verification, and `Ship Gate` rulings without polluting the target Git repository.
_Avoid_: Scratch file, session log, temp state

**Counterpart Model**:
A frontier LLM from a different model family than the active session model, dispatched for cross-family adversarial review or Cycle-2 Strike-Breaking to break correlated blind spots.
_Avoid_: Subagent model, fallback model, backup LLM

**Worker Role**:
A non-authoring execution role dispatched by the Harness or multi-agent orchestrator, including fast discovery (`research`), fast mechanical editing (`fast-exec`), subagents (`invoke_subagent`), and `/swarm` workers, whose target model is resolved dynamically from the live host model catalog.
_Avoid_: Hardcoded helper, fixed subagent, generic worker

**Dynamic Model Registry**:
Live discovery and capability ranking of servable host models via `agy models` combined with an optional user override file (`$HOME/tmp/ale_harness/model_routing.json`), keeping both Worker Roles and Counterpart Models current as new model generations appear.
_Avoid_: Static model table, hardcoded 22-model map

**Review Packet**:
The full, uncapped markdown context file (`<session_dir>/review_packet.md`) containing git diffs, untracked files, baseline dirty-tree separation, test outputs, and active invariants that a read-only reviewer can inspect on demand when inline CLI prompts exceed safe argv limits.
_Avoid_: Truncated inline diff, manual extra prompt workaround

**Strike-Breaker**:
The automated handoff of a stalled task (at Friction Cycle 2) to a Counterpart Model with the accumulated diff, failure output, and session invariants to escape the primary model's reasoning rut.
_Avoid_: Retry, fallback, escalation

**RED Gate**:
The mandatory pre-edit proof recorded in the Ledger confirming a runtime test or reproduction command fails on the target behavior (distinguishing test assertion failure from build/syntax failure) prior to modifying production code.
_Avoid_: Failing build, syntax error, manual check

**Executable Invariant (`LL_GATE`)**:
A positive domain or architectural rule in `LESSONS_LEARNED.md` paired with a deterministic shell or regex check (`Verification Check`) that the Harness executes before and after code changes.
_Avoid_: Guideline, best practice, tip

**Ship Gate**:
The hard-stop boundary enforced by `PreToolUse` hooks before any outward-facing or irreversible action (`git push`, `gh pr create`, tag/release) requiring explicit user confirmation recorded via `ruling --allow-ship`.
_Avoid_: Commit hook, CI check

**Shortcut Ledger**:
An explicit inline code marker (`# ponytail: <reason>` or `# shortcut: <ceiling>, <upgrade trigger>`) that records a deliberate YAGNI simplification and the exact condition under which it must be upgraded.
_Avoid_: TODO, FIXME, hack

**Hybrid Humanizer Tiering**:
The two-tier prose governance model that embeds core anti-AI-slop structural rules as an Always-On Rule for zero-latency daily conversation while dynamically loading the full `humanizer-zh-tw` (zh-TW) or `humanizer` (English) On-Demand Skill in silent Embedded Mode whenever authoring or editing documents and long-form prose.
_Avoid_: Full-skill every turn, raw chatbot prose, telegraphic bullet spam

**Tiered Counterpart Routing**:
The quota-aware cross-family model pairing policy that dispatches high-efficiency frontier counterparts (`claude-sonnet-5-5-high` <-> `gemini-4-argon-high`) for Tier 2 standard reviews while reserving flagship deep-reasoning counterparts (`claude-opus-5-5-high` <-> `gemini-4-carbon-high`) for Tier 3 architectural reviews, Cycle-2 Strike-Breaking, and flagship-authored changes, backed by a cross-family fallback chain.
_Avoid_: Flat Opus routing, same-family review, static model table

**Async Dispatch Lease**:
A time-bounded process record (`dispatch_in_progress`) written to the Ledger while `model_router.py` executes a cross-model CLI call, allowing the `Stop` hook to yield the turn cleanly so the parent session can await background task completion without `sleep` polling.
_Avoid_: Sleep polling loop, duplicate background dispatch, manual stop override

**Superseded Invariant**:
A historical rule in `LESSONS_LEARNED.md` marked `Status: Superseded by <ID>` via `retire-ll` when an architectural transition replaces its behavior, preserving audit provenance while instructing `red_gate.py` to skip its obsolete verification check.
_Avoid_: Zombie invariant, deleted lesson, unguarded dead code
