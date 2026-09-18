# Meta-Orchestration Pipeline and Subagent Federation

To transform ALE from a standalone engine into a supreme orchestrator pipeline, we established an authoritative stage-to-skill delegation matrix, a hybrid subagent isolation architecture, a strict friction adapter protocol, and dual-track routing for code and non-code domains.

## Decisions

1. **Authoritative Stage-to-Skill Delegation Matrix**:
   - **Phase 1 (Preparation)**: Dispatches `/research` when primary sources or library APIs are unknown.
   - **Phase 2 (Execution)**: Delegates to `/tdd` (or `/implement`) for code changes at agreed seams, or direct surgical authoring for non-code artifacts.
   - **Phase 3 (Distillation)**: Handled internally by ALE to extract the 5-dimensional causal chain into `SESSION_LL.md`.
   - **Phase 4 (Verification)**: Spawns parallel adversarial subagents running `/fable-judge` (fraud/claims refutation) and `/code-review` (standards and spec conformance).
   - **Phase 5 (Promotion & Handoff)**: Promotes invariants to `docs/LESSONS_LEARNED.md`; invokes `/handoff` when session context limits are reached.

2. **Hybrid Isolation Architecture**:
   - The main thread preserves state, the active `LL_GATE`, and `SESSION_LL` orchestration.
   - Expensive research lookups (`/research`) and adversarial judging (`/fable-judge`, `/code-review`) fan out to parallel subagents in a single message, keeping the main context pristine.

3. **Strict Friction Adapter Protocol**:
   - A red-to-green failure in `/tdd` (>1 retry cycle), any `REFUTED` verdict from `/fable-judge` (weakened checks, false completions, spec betrayals), or hard violations from `/code-review` are intercepted immediately as hard Friction. The agent is strictly prohibited from re-executing without recording an invariant.

4. **Dual-Track Routing (Code vs. Non-Code)**:
   - **Code Track**: Routes through `/tdd` → `/code-review` + `/fable-judge`.
   - **Non-Code Track**: Routes through `/research` → Direct authoring → `/fable-domain` / `/fable-judge` (testing against domain fraud tables: fabricated figures, stale citations, tone deviations).
