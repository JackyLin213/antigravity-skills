---
name: agent-loop-engineering
description: Autonomous closed-loop execution engine that extracts Lessons Learned (LL) from runtime friction and enforces pre-flight constraints to prevent repeating mistakes. Use when executing non-trivial coding tasks with "/ale <task>".
trigger: /ale
---

# Agent Loop Engineering (ALE)

> **"The agent forgets, the repo doesn't."**
> Standard agent loops fail because they patch local errors without understanding root causes. In step 2 the agent trips over a trap; in step 5 it trips over the exact same trap in another file. 
> ALE serves as the **Meta-Orchestrator Pipeline** that bridges specialized skills (`/tdd`, `/implement`, `/research`, `/fable-judge`, `/code-review`, `/handoff`) and transforms ephemeral runtime friction into durable, enforceable invariants.

---

## 🚀 Usage

```bash
/ale <task description>
```

When invoked, ALE acts as the supervisory engine, routing the task across the 5-phase pipeline, spawning isolated subagents for research and adversarial verification, and gating all file modifications behind `LL_GATE`.

---

## 🗺️ Master Pipeline Architecture & Skill Delegation

```mermaid
flowchart TD
    subgraph Phase1 ["Phase 1: Ingestion & Pre-flight Gate"]
        READ_LL["Read docs/LESSONS_LEARNED.md<br/>& Submodule LLs"] --> INIT_SESS["Init .scratch/SESSION_LL.md"]
        INIT_SESS --> FACT_CHECK{"Missing primary facts / docs?"}
        FACT_CHECK -- Yes --> CALL_RES["📡 Spawn Subagent: /research<br/>(Parallel source discovery)"]
        FACT_CHECK -- No --> PLAN["Formulate Plan"]
        CALL_RES --> PLAN
        PLAN --> GATE["Declare LL_GATE<br/>(Hard constraint declaration)"]
    end

    subgraph Phase2 ["Phase 2: Surgical Execution"]
        GATE --> ROUTE{"Task Domain Track"}
        ROUTE -- Code Task --> CALL_TDD["⚙️ Invoke /tdd or /implement<br/>(Red-Green-Refactor at Seams)"]
        ROUTE -- Non-Code Task --> SURGICAL["📝 Surgical Authoring<br/>(Direct content generation)"]
    end

    subgraph Phase3 ["Phase 3: Friction Adapter & 5D Distillation"]
        CALL_TDD & SURGICAL --> ADAPTER{"Friction detected?<br/>(TDD red loop / Compiler error / Judge refutation)"}
        ADAPTER -- Yes --> HOOK["🚨 Friction Hook Triggered<br/>(HALT code edits)"]
        HOOK --> CHECK_BUDGET{"Friction Budget &le; 3?"}
        CHECK_BUDGET -- "> 3 (Exhausted)" --> HANDBACK["🛑 Honest Handback<br/>(Stop loop, report hypothesis + SESSION_LL)"]
        CHECK_BUDGET -- "&le; 3" --> DISTILL["Distill 5D Causal Chain<br/>(Trigger, False Assumption, Root Cause, Invariant, Check)"]
        DISTILL --> APPEND["Append to .scratch/SESSION_LL.md"]
        APPEND --> GATE
    end

    subgraph Phase4 ["Phase 4: Multi-Lens Adversarial Verification"]
        ADAPTER -- No --> FANOUT["🛡️ Subagent Federation (Parallel In One Message)"]
        FANOUT --> JUDGE_AGENT["Subagent 1: /fable-judge<br/>(Hunt 6 AI frauds & test verification)"]
        FANOUT --> REVIEW_AGENT["Subagent 2: /code-review<br/>(Standards & Spec 2-axis review)"]
        JUDGE_AGENT & REVIEW_AGENT --> AGGREGATE{"All checks passed?"}
        AGGREGATE -- "REFUTED / Violations" --> ADAPTER
        AGGREGATE -- "VERIFIED" --> TWIN["Twin Check (Search for recurring anti-patterns)"]
    end

    subgraph Phase5 ["Phase 5: Promotion Review & Compaction"]
        TWIN --> FILTER["Run Three-Test Filter on SESSION_LL<br/>(Generalizability + Tool Gap + Permanence)"]
        FILTER --> PROMOTE["Promote passing entries to docs/LESSONS_LEARNED.md"]
        PROMOTE --> COMPACT{"Global LLs > 20?"}
        COMPACT -- Yes --> RUN_COMPACT["Execute Compaction<br/>(Merge related, prune obsolete)"]
        COMPACT -- No --> CONTEXT_CHECK{"Context window high?"}
        RUN_COMPACT --> CONTEXT_CHECK
        CONTEXT_CHECK -- Yes --> CALL_HO["🔄 Invoke /handoff<br/>(Generate transition artifact)"]
        CONTEXT_CHECK -- No --> REPORT["Outcome-First Final Delivery"]
        CALL_HO --> REPORT
    end
```

---

## 📋 The 5 Lifecycle Phases & Delegation Matrix

### Phase 1 — Ingestion & Pre-flight Gate
1. **Knowledge Ingestion**:
   - Read `docs/LESSONS_LEARNED.md` at repository root.
   - Read `<submodule>/LESSONS_LEARNED.md` if working within a localized domain directory.
   - Initialize `.scratch/SESSION_LL.md` (using `templates/SESSION_LL.md`).
2. **Fact Delegation (`/research`)**:
   - If the task requires unfamiliar library APIs, framework behaviors, or external documentation:
   - **Spawn `/research` in a subagent**: Do not guess signatures from memory. Wait for distilled factual findings.
3. **The `LL_GATE` Enforcement**:
   - Prior to modifying any file, emit a mandatory verbatim `LL_GATE` declaration:
     ```markdown
     LL_GATE: checked [LL-001, LL-003] - active constraints:
     - [LL-001]: Ref must be passed via props directly (React 19).
     - [LL-003]: All DB transactions must include timeout option.
     Verified: Current implementation plan strictly obeys these invariants.
     ```
   - **Hard Prohibition**: Edits executed without a preceding `LL_GATE` are considered unauthorized violations.

---

### Phase 2 — Execution Delegation
Route automatically according to the task domain:

* **Code Track**:
  - Invoke **`/tdd`** at agreed seams (or **`/implement`** for full spec execution).
  - Enforce Red-Green-Refactor: never write implementation code before a failing test exists.
* **Non-Code Track** (Specs, Docs, Marketing, Research):
  - Execute direct surgical authoring in the main thread according to domain style guidelines.

---

### Phase 3 — Friction Adapter & 5D Distillation (The Learning Engine)
The **Friction Adapter** intercepts failures across all delegated skills:
- `/tdd` red-to-green retry fails more than once.
- Terminal exit code != 0, compiler fail, or linter error.
- `/fable-judge` delivers a `REFUTED` verdict (e.g. weakened checks, false completion, spec betrayal).
- `/code-review` identifies hard standards/spec violations.
- User explicitly points out a mistake or bad assumption.

#### Protocol on Friction:
1. **Immediate Execution Halt**: Strictly prohibited from immediately modifying code to "try another syntax".
2. **Check Friction Budget**:
   - Track iteration count for the current subtask (maximum allowance: 3 cycles).
   - If budget reaches 3: **ABORT IMMEDIATELY**. Deliver an honest handback containing raw failure outputs, accumulated `SESSION_LL`, and working hypothesis.
3. **Distill 5-Dimensional Causal Chain**:
   Extract into `.scratch/SESSION_LL.md`:
   * **Trigger**: Specific surface, module, or pattern where friction occurred.
   * **False Assumption**: Flawed belief or hallucinated behavior held by the agent.
   * **Root Cause**: Objective technical or domain reality discovered.
   * **Invariant**: Enforceable positive rule preventing future recurrence.
   * **Verification Check**: Exact bash command, regex, or test to verify compliance.
4. **Re-route**: Return to Phase 1, update `LL_GATE`, and resume execution with the new invariant active.

---

### Phase 4 — Multi-Lens Verification (Subagent Federation)
Once Phase 2 reports completion, launch parallel verification subagents in **ONE message** to keep the main context clean:

1. **Adversarial Attacker Subagent (`/fable-judge`)**:
   - Re-runs claimed tests independently.
   - Hunts for 6 classic AI frauds: weakened tests, false completion, scope creep, unauthorized action, spec betrayal, and debris.
2. **Standards & Spec Subagent (`/code-review`)**:
   - Performs two-axis review: Conformance to project standards + faithfulness to spec/tickets.
3. **Aggregation**:
   - If either subagent reports `REFUTED` or severe violations: Route directly to Phase 3 as Friction.
   - If both report `VERIFIED`: Run the **Twin Check** in the main thread (search codebase for recurrence of any fixed defect).

---

### Phase 5 — Promotion Review, Compaction & Handoff
1. **The Three-Test Promotion Filter**:
   Review all entries in `.scratch/SESSION_LL.md`. Promote to `docs/LESSONS_LEARNED.md` ONLY IF it passes ALL three tests:
   * **Generalizability**: Applies to future work across the repo (not a single-line typo).
   * **Tool Gap**: Cannot be caught automatically by compilers, linters, or existing CI checks.
   * **Permanence**: Enduring architectural convention, not temporary WIP state.
2. **Compaction Gate (Rule Ceiling: 20)**:
   - If `docs/LESSONS_LEARNED.md` exceeds 20 global invariants, merge related rules and prune obsolete ones.
3. **Handoff & Report**:
   - If context usage is high or the user plans to continue in a fresh session: invoke **`/handoff`**.
   - Deliver outcome-first report displaying verification evidence and newly promoted Project LLs.
