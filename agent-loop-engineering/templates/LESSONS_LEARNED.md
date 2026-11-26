# Project Lessons Learned & Invariants (PROJECT_LL)

Permanent, verified architectural invariants and anti-patterns distilled by `/ale`.
Stored centrally at `~/knowledgebase/lessons/<project_name>/LESSONS_LEARNED.md` (and optionally synced to `docs/LESSONS_LEARNED.md`).

> **Governance Rules**:
> 1. **Ceiling**: Maximum 20 global invariants. Compact when exceeding 20.
> 2. **Three-Test Standard**: Every entry must pass Generalizability, Tool Gap, and Permanence filters.
> 3. **Executable Checks**: Prefix `Verification Check` with `cmd: <shell command>` or `regex-forbid: <regex>` so `red_gate.py` executes it automatically.

---

## 🏛️ Architecture & State

### [LL-ARCH-001] <Title>
- **Trigger**: `<File paths or architectural boundaries>`
- **False Assumption**: `<Flawed belief>`
- **Root Cause**: `<Technical ground truth>`
- **Invariant**: `<Enforceable positive rule>`
- **Verification Check**: `<cmd: pytest tests/unit | regex-forbid: pattern>`

---

## ⚙️ Tooling, Build & Dependencies

### [LL-TOOL-001] <Title>
- **Trigger**: `<Build script, package, or configuration surface>`
- **False Assumption**: `<Flawed belief>`
- **Root Cause**: `<Technical ground truth>`
- **Invariant**: `<Enforceable positive rule>`
- **Verification Check**: `<cmd: shell command>`

---

## 🛡️ Data & API Contracts

### [LL-DATA-001] <Title>
- **Trigger**: `<API endpoints, database queries, schemas>`
- **False Assumption**: `<Flawed belief>`
- **Root Cause**: `<Technical ground truth>`
- **Invariant**: `<Enforceable positive rule>`
- **Verification Check**: `<cmd: shell command>`
