# Dynamic Cross-Family Model Routing Matrix (Dynamic Registry + Tiered Counterpart Routing)

This reference defines the live model discovery and tiered routing policy enforced by `scripts/ledger.py` and `scripts/model_router.py`.

## 1. Dynamic Model Discovery & Override Config

Rather than maintaining a frozen model list, `scripts/ledger.py` queries `agy models` live (cached for 300 seconds per `agy` binary path, with a built-in fallback catalog when `agy` is offline). Models are ranked by provider family, generation version, capability tier, effort preference (`high` default for flagships; `xhigh` for Tier 3 or flagship-authored `fast-exec`), and live `agy models` ordering so newly released models (such as the Gemini 4 Neon line or future generations) become active immediately.

Optional operator overrides live in `$HOME/tmp/ale_harness/model_routing.json` (respecting `ALE_OUTPUT_ROOT`):

```json
{
  "prefer_effort": "high",
  "exclude": ["gpt-oss-*"],
  "pin_role": {
    "fast-exec": "gemini-4-hydrogen-xhigh"
  },
  "tier_order": {
    "gemini": ["neon", "carbon", "argon", "hydrogen", "flash"]
  }
}
```

## 2. Role Pairing & Quota-Aware Tiering Policy

When one model family both writes and reviews code, correlated blind spots let flawed assumptions slip through. ALE separates **Worker Roles** (fast discovery, fast mechanical execution, subagents, `/swarm` workers) from **Counterpart Models** (cross-family review and Cycle-2 Strike-Breaking):

| Active Author Model (`impl_model`) | Tier 2 Standard Review (`review` / `judge`) | Tier 3 Architectural Review & Cycle-2 `strike-breaker` | Fast Mechanical Execution (`fast-exec`) | Fast Discovery (`research`) | Dynamic Cross-Family Fallback Chain |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Gemini Standard (`argon`, `hydrogen`, `flash`, `orchestrator-argon`) | Latest Claude Balanced (`claude-sonnet-*` at `high`) | Latest Claude Flagship (`claude-opus-*` at `high`) | Latest Gemini Fast-Exec (`hydrogen-high`; `xhigh` at Tier 3) | Latest Gemini Research (`flash-high`) | Other Claude tier -> Latest GPT fallback |
| Gemini Flagship (`neon`, `carbon`, `orchestrator-neon`, `orchestrator`) | Latest Claude Flagship (`claude-opus-*` at `high`) | Latest Claude Flagship (`claude-opus-*` at `high`) | Latest Gemini Fast-Exec (`hydrogen-xhigh`) | Latest Gemini Research (`flash-high`) | Latest Claude Balanced -> Latest GPT fallback |
| Claude (`opus`, `sonnet`) | Latest Gemini Balanced (`gemini-4-argon-high`) | Latest Gemini Flagship (e.g. `gemini-4-neon-high`, then `carbon`) | Latest Gemini Fast-Exec (`hydrogen-high`; `xhigh` at Tier 3 or Opus author) | Latest Gemini Research (`flash-high`) | Next Gemini flagship/balanced tiers -> `hydrogen-xhigh` |
| GPT (`gpt-*`) | Latest Gemini Balanced (`gemini-4-argon-high`) | Latest Gemini Flagship (`gemini-4-neon-high`) | Latest Gemini Fast-Exec (`hydrogen-high`; `xhigh` at Tier 3) | Latest Gemini Research (`flash-high`) | Next Gemini tiers -> Latest Claude Balanced |

## 3. Worker & Subagent Alignment (`invoke_subagent` & `/swarm`)

- **`model_router.py` workers (`research`, `fast-exec`)**: Always resolved via `resolve_worker_model()` against the live `agy models` catalog and `model_routing.json`.
- **Native `invoke_subagent`**: Use `Model="flash"` for fast read-only exploration and `Model="inherit"` for standard delegation so it tracks the live session model.
- **`/swarm` workers**: Inspect `python3 scripts/model_router.py --role models` before pinning a worker model, or omit `model` to inherit the active frontier model.

## 4. Role Dispatch Commands

1. **Discover Live Servable Models & Resolved Dynamic Defaults**:
   ```bash
   python3 scripts/model_router.py --role models
   ```
2. **Phase 1 Fact Discovery (`research`)**:
   ```bash
   python3 scripts/model_router.py --role research --prompt "Verify API signature for..."
   ```
3. **Phase 2 Fast Mechanical Execution / Test Wiring (`fast-exec`)**:
   ```bash
   python3 scripts/model_router.py --role fast-exec --prompt "Add unit test assertions for..."
   ```
4. **Phase 3 Cycle-2 Strike-Breaker (`strike-breaker`)**:
   Triggered when `friction_count == 2`. Passes `SESSION_LL.md`, active `PROJECT_LL` rules, and workspace diff context to the flagship Counterpart Model. Fallback stops immediately if the first candidate modified workspace files before failing:
   ```bash
   python3 scripts/model_router.py --role strike-breaker --prompt "Diagnose and resolve the recurring test failure."
   ```
5. **Phase 4 Independent Cross-Family Review (`review`)**:
   ```bash
   python3 scripts/model_router.py --role review
   ```
   Writes the full uncapped diff and context to `<session_dir>/review_packet.md`, sends a compact prompt under Linux argv byte limits, allows read-only `read_file` inspection when truncated, advances fallback on exit-0 CLI error envelopes, and blocks `VERIFIED_WITH_CAVEATS` whenever any finding has `severity == "must-fix"`.
