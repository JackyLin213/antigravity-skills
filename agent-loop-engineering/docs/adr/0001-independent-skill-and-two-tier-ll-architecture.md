# Independent Skill with Two-Tier LL Architecture and Syntactic Pre-flight Gate

To enable autonomous error prevention without polluting repository rules or breaking existing skills, we chose to implement Agent Loop Engineering as an independent meta-skill (`agent-loop-engineering` / `/ale`) using a two-tier memory lifecycle (task-scoped `SESSION_LL` promoted to permanent `PROJECT_LL`) and an active syntactic gate (`LL_GATE`).

## Considered Options

- **Direct Fable Mutation**: Embedding LL extraction directly into `fable-loop`. Rejected because it limits learning loops to Fable sessions and breaks modularity.
- **Single-Tier Global LL**: Appending all failures directly to repository root rules. Rejected because transient noise, typos, and task-specific quirks pollute permanent knowledge.
- **Passive Context Injection**: Merely including LL files in context. Rejected because LLMs ignore passive guidance during extended context; a mandatory verbatim syntax declaration (`LL_GATE`) provides provable enforcement.
