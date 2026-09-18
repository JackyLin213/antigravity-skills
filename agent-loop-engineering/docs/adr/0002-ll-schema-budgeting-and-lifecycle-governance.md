# LL Schema, Execution Budget, and Lifecycle Governance

To ensure LL entries provide high cognitive value without causing context bloat or runaway loops, we established a five-dimensional causal schema, a hard 3-cycle friction budget, a three-test promotion filter, and dual-track compaction with submodule scoping.

## Decisions

1. **Five-Dimensional Causal Chain**: Every LL entry must capture:
   - `Trigger`: Module or context where friction occurs.
   - `False Assumption`: The flawed premise or hallucination held by the agent.
   - `Root Cause`: The underlying architectural or library invariant.
   - `Invariant`: The enforceable, positive rule for future generations.
   - `Verification Check`: A concrete bash command, regex, or test to verify compliance.

2. **Strict 3-Cycle Friction Budget**:
   - Up to 3 iterations of `Friction → Distillation → Pre-flight Retry` are permitted per subtask.
   - Upon the 3rd consecutive failure, the loop aborts immediately. The agent delivers an honest handback containing the accumulated `SESSION_LL` items and the working hypothesis.

3. **Three-Test Promotion Filter**:
   - Only Session LLs that satisfy all three criteria graduate to Project LL:
     1. *Generalizability* (applies beyond the immediate function/file).
     2. *Tool Gap* (cannot be caught by compiler, linter, or existing static checks).
     3. *Permanence* (enduring architectural convention, not temporary WIP state).

4. **Dual-Track Compaction & Submodule Scoping**:
   - Global repository LL is capped at 20 invariants. Exceeding this triggers compaction (merging related rules and retiring superseded ones).
   - In modular or multi-context repositories, domain-specific rules descend into submodule-level `LESSONS_LEARNED.md` files near the code they govern.
