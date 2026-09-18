# Unified Single-Command Interface and Ecosystem Registration

To maximize ergonomics and reduce cognitive burden on the user, we decided to expose a minimal single-command interface (`/ale <task>`) with automated internal compaction and auditing, built as a fully self-contained closed-loop execution engine, registered globally as the 5th Ecosystem in the skills catalog.

## Decisions

1. **Unified Command Interface (`/ale <task>`)**:
   - Instead of exposing fragmented subcommands, ALE runs as a seamless, unified workflow. Compaction, friction extraction, pre-flight checks, and promotion reviews happen automatically within the loop lifecycle.

2. **Self-Contained Execution Engine**:
   - ALE manages its own five-phase loop (`Plan → Pre-flight → Act → Verify → Distill/Promote`) end-to-end, guaranteeing that every file modification is intercepted by `LL_GATE` without hard dependency on other skills.

3. **Global Ecosystem Registration**:
   - Installed globally at `~/.gemini/config/skills/agent-loop-engineering/`.
   - Formally designated as Ecosystem 5 ("自主演化與經驗閉環") in the master skills documentation, bridging execution (`implement`, `fable-loop`) and review (`fable-judge`, `code-review`).
