# Agent Loop Engineering (ALE)

A system that enables AI agents to autonomously extract structured Lessons Learned (LL) from execution friction, and enforce pre-flight constraints to prevent repeating mistakes.

## Language

### Core Concepts

**Lessons Learned (LL)**:
A structured invariant distilled from a failure or surprise, specifying the trigger, anti-pattern, root cause, and enforceable rule.
_Avoid_: Error log, post-mortem, notes, scratchpad

**Session LL**:
A temporary, task-scoped lesson recorded during the current execution loop to prevent immediate repetitive blunders.
_Avoid_: Working memory, temp notes, cache

**Project LL**:
A permanent, verified lesson promoted from Session LL that applies across all future sessions in the repository.
_Avoid_: Rules, guidelines, best practices

### Loop Mechanisms

**Friction**:
Any deterministic failure, test break, tool error, or verification rejection that halts blind retry.
_Avoid_: Bug, mistake, crash

**Friction Hook**:
The mandatory execution pause triggered by friction that forces root-cause distillation before code modification.
_Avoid_: Error handler, retry logic, catch block

**Pre-flight Gate**:
The mandatory self-check phase prior to generating code or plans, cross-referencing active LL invariants.
_Avoid_: Verification, sanity check, review

**LL_GATE**:
The explicit, required syntax declaration emitted in thought or output stating which LL invariants are being honored before invoking write tools.
_Avoid_: Disclaimer, safety note, check-in

**Distillation**:
The analytical transformation of an observed friction event into a structured, transferable LL invariant.
_Avoid_: Summary, logging, post-mortem writeup

**Promotion**:
The selective graduation of a verified Session LL into a permanent Project LL upon task completion.
_Avoid_: Saving, persisting, exporting

**Three-Test Filter**:
The gating criteria (Generalizability, Tool Gap, Permanence) required for a Session LL to qualify for Promotion.
_Avoid_: Heuristics, screening, checklist

**Friction Budget**:
The maximum allowance of 3 consecutive friction-distillation-retry iterations before mandatory execution abort.
_Avoid_: Retry limit, max attempts, timeout

**Compaction**:
The consolidation and deduplication of Project LLs once the repository exceeds the 20-rule ceiling.
_Avoid_: Pruning, cleanup, archiving

**Submodule LL**:
A localized set of invariants scoped to a specific package or domain directory rather than the repository root.
_Avoid_: Local rules, component config

### Orchestration & Federation

**Meta-Orchestrator**:
The supervisory role assumed by ALE that coordinates specialized skills across a 5-phase closed loop pipeline.
_Avoid_: Manager, master script, task runner

**Subagent Federation**:
The architectural pattern where heavy research and adversarial verifications fan out to isolated parallel subagents.
_Avoid_: Multi-agent swarm, background tasks

**Friction Adapter**:
The protocol that maps tool errors, test red-loops, and adversarial review rejections directly into standard Friction events.
_Avoid_: Error mapper, handler

**Dual-Track Routing**:
The automatic dispatch mechanism that selects either the Code Track (TDD + Review) or Non-Code Track (Research + Domain Judge).
_Avoid_: Branching logic, mode switch



