# Global & Agent Harness Rules

## Part 1: Global Rules (Daily Q&A, Documentation & Deliverables)

### 1. Language & Output Standards
- Always use **Traditional Chinese (`zh-TW`)** when conversing and replying to the user.
- Always use **English** when writing or modifying source code, code comments, commit/PR descriptions, evaluation suites (`evals.json`, `TEST.md`), and technical documentation (`SKILL.md`, `README.md`, `references/`).

### 2. Communication Style, Natural Human Voice & Token Efficiency (`/caveman` + `/humanizer-zh-tw` + `/humanizer`)
- **Outcome-First & Direct Execution (`/caveman` structural discipline)**: Lead with the conclusion, omit throat-clearing pleasantries ("好問題", "希望這對您有幫助", "In today's fast-paced landscape"), and execute tool calls directly without conversational narration before or between calls.
- **Always-On Humanizer Core (Daily Conversation & Explanations)**:
  - Write all conversational replies and explanations in a natural, authentic human voice with varied sentence rhythm; prefer coherent prose paragraphs when explaining concepts rather than mechanically chopping every reply into telegraphic fragments, forced triads, or bold-label bullet spam.
  - Eliminate staging and inflation tells: avoid false contrasts (`不是 X，而是 Y`, `不僅…更…`, `not just X, but Y`), dramatic one-line closers (`這才是關鍵`, `That is the real win`, `Let that sink in`), em-dash (`—`) overuse, and stock AI vocabulary (`賦能`, `抓手`, `底層邏輯`, `閉環`, `至關重要`, `不言而喻`, `delve`, `tapestry`, `testament`, `game-changer`, `seamless`, `unlock`, `elevate`).
  - Strictly preserve facts, numbers, attributions, and epistemic certainty (never upgrade correlation to causation or `可能`/`might` to `必定`/`will`), leaving code blocks, inline code, URLs, paths, and identifiers untouched.
- **On-Demand Full Skill Load (Documents, Reports & Long-Form Prose)**:
  - Whenever creating, editing, or reviewing any document, note, ADR, report, `README.md`, `SKILL.md`, commit/PR description, or long-form prose, read and apply the full skill runbook matched to the target language:
    - **Traditional Chinese (`zh-TW`)**: `~/.gemini/config/skills/humanizer-zh-tw/SKILL.md`
    - **English**: `~/.gemini/config/skills/humanizer/SKILL.md`
- **Silent Embedded Delivery**:
  - Run both humanizer skills in **Embedded Mode** by default: deliver **only the final polished text** without intermediate drafts, AI-tell diagnostic lists, or unsolicited `text-watermark-cleaner-zh-tw` prompts (surface diagnostics or run watermark inspection/cleaning only when explicitly requested by the user).
- **Auto-Clarity Boundary**: Revert to explicit, complete phrasing for safety-critical confirmations, destructive/irreversible actions, and when compression risks technical ambiguity.

### 3. Centralized Knowledge Base & Documentation Policy (`~/knowledgebase/`)
- Do NOT store project-local markdown documentation, ADRs, research notes, or context files scattered across individual project directories unless explicitly requested by the user.
- ALL documentation, Architecture Decision Records (ADRs), technical research, domain contexts, lessons learned, and engineering notes must be centrally stored under `~/knowledgebase/` (backed by cloud storage at `$HOME/drive-fs/knowledgebase`).
- **Directory Taxonomy**:
  - `~/knowledgebase/adr/[<project_name>/]`: Architecture Decision Records (ADRs). Use project subdirectories when project-specific.
  - `~/knowledgebase/docs/[<project_name>/]`: Curated system documentation, architectural guides, and specifications.
  - `~/knowledgebase/research/[<project_name>/]`: Spikes, technical feasibility studies, and research findings.
  - `~/knowledgebase/notes/[<project_name>/]`: Engineering notes, summaries, and source ledgers.
  - `~/knowledgebase/lessons/[<project_name>/]LESSONS_LEARNED.md`: Permanent 5-dimensional project invariants distilled by `/ale`.
  - `~/knowledgebase/CONTEXT.md`: Ubiquitous domain language and central glossary.
- **Multi-Project Segregation**: Store project-specific artifacts in subdirectories named after the project/workspace under the appropriate taxonomy folder to prevent naming and numbering collisions.
- Use standard filesystem tools (`write_file`, `edit_file`, `read_file`) directly.

### 4. Grounded Deliverables Workflow (Spreadsheets / Presentations / Docs / Reports)
- **Trigger**: Creating or editing any spreadsheet, presentation deck, document, or `.xlsx`/`.pptx`/`.docx`/`.csv`/`.md` report that contains numbers, quotes, names, dates, or cited facts. Run Stages 1–4 in order; skip a stage only when the user explicitly says so.
- **Stage 1 — Source Ledger (Citations)**: Before drafting any content, read every primary source with read-only tools and record each fact (`id`, `value`, `verbatim_excerpt`, `exact_source_uri_or_path`, `retrieved_at`) in `~/knowledgebase/notes/<project>/<YYYY-MM-DD>-<slug>/sources.tsv`.
- **Stage 2 — Build Only from Ledger Values**:
  - Compute derived numbers (sums, percentages, deltas) with Python from `sources.tsv`, never mentally.
  - Show `TBD` for missing data; never invent sample data unless explicitly asked (then label `ILLUSTRATIVE — SAMPLE DATA`).
- **Stage 3 — Independent Audit**: Dispatch a read-only auditor subagent (using the cross-family Counterpart Model when available) that re-fetches the original sources rather than trusting the ledger, verifying every table and point claim. Fix every mismatch and re-audit (max 2 rounds); if still failing, stop and report.
- **Stage 4 — Provenance**: Include a `Sources` section/tab/notes in the deliverable. The final reply must list the `sources.tsv` ledger path, the audit verdict, and every remaining `TBD`.

---

## Part 2: Harness Rules (Engineering, Skills, MCP & Model Routing)

### 5. Minimalist Engineering & YAGNI Principle (`/ponytail`)
- Apply `/ponytail` (the `ponytail` skill) across all coding, refactoring, bug-fixing, and architecture tasks to enforce the smallest complete solution and prevent over-engineering.
- **The YAGNI Ladder** (stop at the first rung that works):
  1. Does this need to exist at all? Speculative need = skip it (YAGNI).
  2. Already in this codebase? Reuse existing helpers, utilities, and patterns first.
  3. Standard library does it? Use it.
  4. Native platform feature covers it? Use it.
  5. Already-installed dependency solves it? Use it (never add new dependencies for simple logic).
  6. Can it be one line? Write one line.
  7. Only then: write the minimum code that works.
- **Read First, Be Lazy Second**: Never simplify comprehension. Trace the full flow and grep all callers before editing. Fix the shared root cause once rather than patching symptoms across multiple callers.
- **Quality & Safety Boundaries**:
  - All Python code written under `/ponytail` MUST still strictly comply with `/python-readability`.
  - Never simplify away input validation at trust boundaries, error handling preventing data loss, or security checks.
  - Keep tests minimal: leave behind a single runnable check/assertion for non-trivial logic rather than bulky test suites unless explicitly requested.
- **Output Format**: Present code first, followed by at most 3 short lines summarizing deliberate simplifications (`skipped: [X], add when [Y]`). Use inline `# ponytail: [reason]` or `# shortcut: <ceiling>, <upgrade trigger>` comments for deliberate trade-offs.

### 6. Python Code Quality & Readability Verification (`/python-readability`)
- Before completing, delivering, or handing off any Python code changes, you MUST use `/python-readability` (`~/.gemini/config/skills/python-readability/SKILL.md` and `scripts/check_python.py`) to verify the code.
- Ensure full compliance with PEP 8, complete type annotations, docstrings, and zero static readability violations before final delivery.

### 7. Portable Skill & Plugin Authoring & Eval Sandbox Isolation (`$HOME/tmp/eval_sandbox/<skill_name>/`)
- When creating or modifying a `SKILL.md` or plugin, design it to run unmodified for ANY user who installs it. Never hardcode author- or machine-specific values.
- **Scope**: `SKILL.md` and every file shipped with the skill or plugin (`resources/`, `references/`, `scripts/`, `templates/`, `plugin.json`, `skills.json`, `hooks.json`, `mcp_config.json`, `rules/`).
- **Forbidden Hardcoded Values**:
  - Personal home directories (`/home/<username>`) or `~<username>` prefixes.
  - Personal usernames, emails, hostnames, or local workspace paths.
- **Required Portable Substitutes**:
  - User home: `$HOME` or `~` (`Path.home()` in Python).
  - User identity: `${USER}` (`os.environ.get("USER")` in Python).
  - `mcp_config.json` / plugin configs: `${PLUGIN_ROOT}`, `${PLUGIN_DATA}`.
  - Files inside the skill directory (`references/`, `scripts/`, `templates/`) MUST be referenced by paths relative to the `SKILL.md` directory.
  - Runtime outputs and per-user state MUST be written under `$HOME/tmp/<skill_name>/`, created on first run with `mkdir -p`. NEVER write runtime state into the skill directory itself.
- **Output Root Override & Eval Sandbox Isolation**:
  - Every skill script (`scripts/*.py`) that reads or writes under `$HOME/tmp/...` MUST support an environment variable (e.g., `ALE_OUTPUT_ROOT` or `<SKILL>_OUTPUT_ROOT`) and CLI flag (`--output_dir` / `--base_dir`) to override the default output root.
  - `SKILL.md` MUST explicitly document this override so callers and evaluations can redirect all reads/writes cleanly.
  - Every evaluation run MUST route all setup fixtures and temporary test directories into `$HOME/tmp/eval_sandbox/<skill_name>/...`, never scattering test files directly under `$HOME/tmp/` or production output roots.
- **Delivery Gate**: Before completing any skill or plugin change, run `python3 ~/.gemini/config/skills/agent-loop-engineering/scripts/ledger.py check-portability <target_dir>` to verify zero hardcoded personal paths or usernames remain.

### 8. MCP Server Development, Verification & Integration Workflow
- **Trigger**: Whenever creating, modifying, configuring, or debugging an MCP server (`mcp_server.py`, FastMCP/MCP SDK tools, or `mcp_config.json`), follow this 3-stage workflow:
  - **Stage 1 — Design & Implementation**: Enforce action-oriented tool names, strict Pydantic/Zod input and output schemas, tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`), and actionable error messages. Keep `stdout` strictly clean for stdio JSON-RPC transport (route all logging to `stderr`). Enforce the 64-character prefixed tool name limit (`len("mcp_<pluginDirName>_<serverName>_<toolName>") <= 64` matching `^[a-zA-Z0-9_-]{1,64}$`). Run `/python-readability` on all Python MCP files.
  - **Stage 2 — Standalone CLI Verification**: Before mounting the server or completing the task, run a standalone smoke test verifying server startup (`initialize`/`ping`), tool registration & schema serialization (`tools/list`), and normal + error call behavior (`tools/call`).
  - **Stage 3 — Mounting & End-to-End Verification**: Follow portable path rules (`${PLUGIN_ROOT}` or `$HOME`, never hardcoded user paths) in `mcp_config.json` and verify end-to-end tool execution.

### 9. Skill Evaluation Coverage, Quality & Verification Workflow
- **Trigger**: Whenever creating or modifying an agent skill (`SKILL.md`, `references/`, `scripts/`) or its evaluation suite (`evals/evals.json`), execute this 3-stage workflow (via `skill-creator` and `/fable-judge suite`):
  - **Stage 1 — Capability Coverage & Hermeticity Audit**: Map all workflows, CLI flags, environment overrides (`<SKILL>_OUTPUT_ROOT`, `--output_dir`), and error halt conditions to task-oriented test cases (no knowledge-recall quizzes, no script filenames leaked in user prompts). Route all fixtures and outputs into `$HOME/tmp/eval_sandbox/<skill_name>/`.
  - **Stage 2 — Runtime Execution**: Run with-skill vs. baseline evaluations and deterministic grading scripts inspecting generated artifacts.
  - **Stage 3 — Pre-Delivery Self-Review**: Confirm baseline lift and zero portability violations before final delivery.

### 10. Agent Loop Engineering Software Harness (`/ale`) & Standing Model Routing
- **Trigger**: Before searching or editing on any non-trivial software or skill code change in Python modules, parsers, validators, CLI tools, agent skills, evaluators, or MCP servers, load and follow `/agent-loop-engineering` (`~/.gemini/config/skills/agent-loop-engineering/SKILL.md`).
- **Non-Negotiable Gates**:
  1. Emit `Tier <1|2|3> · <Type> · [Impl: <model> | Review: <counterpart>]` on line 1.
  2. Keep harness artifacts outside the Git working tree via `ledger.py` (`$HOME/tmp/ale_harness/<workspace_slug>/ledger.json`, overridable via `ALE_OUTPUT_ROOT`).
  3. Bind `plan.md` SHA-256 on approval (`ledger.py bind-plan`) for plan-first/architectural work.
  4. Record runtime **RED Gate** (`red_gate.py`, distinguishing test assertion exit from syntax/build error; refactor/perf/docs exempt with `--exempt` when behavior is unchanged) and **LL_GATE** (executing all `Verification Check` commands from `~/knowledgebase/lessons/<project>/LESSONS_LEARNED.md` and repo `docs/LESSONS_LEARNED.md`) before production edits.
  5. Intercept any runtime/review friction via **5D Causal Chain Distillation** into `SESSION_LL.md`; trigger **Cross-Family Strike-Breaker** at Friction Cycle 2 (`model_router.py --role strike-breaker`), and hard-abort with Honest Handback at Cycle 3.
  6. Record **DONE** only via passing verification commands (`ledger.py done`), run **Independent Cross-Family Review** (`model_router.py --role review`, combining `/fable-judge` + `/ponytail-review` + `/code-review`, max 3 rounds), and **hard-stop before `git push`, `gh pr create`, or publishing** until the user explicitly confirms (`ledger.py ruling --allow_ship`; enforced by `pretool_gate.py`).
- **Standing Model Routing Directive (Dynamic Registry + Tiered Cross-Family Pairing)**:
  - Never hardcode stale model lists when selecting Worker Roles or Counterpart Models. Discover live servable models and resolved defaults via `python3 ~/.gemini/config/skills/agent-loop-engineering/scripts/model_router.py --role models` (backed by live `agy models` discovery with optional overrides in `$HOME/tmp/ale_harness/model_routing.json`).
  - **Primary Implementation (`impl_model`)**: Use the active session frontier model (auto-detected from hook payload or transcript across all servable `agy models`, including `Gemini 4 Neon`, `Carbon`, `Argon`, `Hydrogen`, `Orchestrator`, `Claude Opus/Sonnet`, and future generations).
  - **Tiered Cross-Family Review & Cycle-2 Strike-Breaker**: Always pair across distinct model families using the latest servable models:
    - When authoring on standard Gemini (`Argon`, `Hydrogen`, `Flash`, `Orchestrator (Argon)`): dispatch the latest Claude Balanced model (`claude-sonnet-*` at `high`) for Tier 2 reviews to conserve shared third-party quota, and the latest Claude Flagship (`claude-opus-*` at `high`) for Tier 3 reviews and Cycle-2 `strike-breaker`.
    - When authoring on flagship Gemini (`Neon`, `Carbon`, `Orchestrator (Neon)`, `Orchestrator (Carbon)`): dispatch the latest Claude Flagship (`claude-opus-*` at `high`) for both review and `strike-breaker`.
    - When authoring on Claude (`Opus` / `Sonnet`) or `GPT`: dispatch the latest Gemini Balanced model (`gemini-4-argon-high`) for Tier 2 reviews, and the latest Gemini Flagship (currently `gemini-4-neon-high`, falling back to `gemini-4-carbon-high`) for Tier 3 reviews and Cycle-2 `strike-breaker`.
  - **Worker Roles (`research`, `fast-exec`, `invoke_subagent`, `/swarm`)**:
    - `model_router.py --role research` dynamically picks the latest Gemini research model (`flash-high`); native `invoke_subagent` uses `Model="flash"` for fast read-only search and `Model="inherit"` for standard subagents.
    - `model_router.py --role fast-exec` dynamically picks the latest Gemini fast-coding tier (`hydrogen-high`, upgrading to `hydrogen-xhigh` at Tier 3 or when the author is flagship).
    - `/swarm` workers should inherit the active frontier model or pick a live ID from `model_router.py --role models`.
  - **Cross-Family Fallback Chain**: Derived dynamically from live servable models and triggered on both non-zero exits and exit-0 CLI error envelopes (`is_error: true` / `status: ERROR`), always yielding to explicit per-turn user model overrides or `model_routing.json`.
- **Exclusions**: Do NOT trigger the heavy `/ale` ledger harness when answering pure Q&A or code explanations, running existing read-only skills, checking `git status`/`git log`, or drafting notes/documentation in `~/knowledgebase/`.
