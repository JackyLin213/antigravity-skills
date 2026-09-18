# Project Lessons Learned & Invariants (PROJECT_LL)

This document contains permanent, verified architectural invariants and anti-patterns distilled by `/ale`.
All AI agents modifying this repository must cross-reference these invariants during the **Pre-flight Gate** before writing code.

> **Governance Rules**:
> 1. **Ceiling**: Maximum 20 global invariants. When exceeding 20, compaction is mandatory.
> 2. **Three-Test Standard**: Every entry passed Generalizability, Tool Gap, and Permanence filters.
> 3. **Submodule Scoping**: Package-specific rules should reside in `<submodule>/LESSONS_LEARNED.md`.

---

## 🏛️ Architecture & State

### [LL-ARCH-001] <Title>
- **Trigger**: `<File paths or architectural boundaries>`
- **False Assumption**: `<Flawed belief>`
- **Root Cause**: `<Technical ground truth>`
- **Invariant**: `<Enforceable rule>`
- **Verification Check**: `<Verification command or pattern>`

---

## ⚙️ Tooling, Build & Dependencies

### [LL-TOOL-001] <Title>
- **Trigger**: `<Build script, package, or configuration surface>`
- **False Assumption**: `<Flawed belief>`
- **Root Cause**: `<Technical ground truth>`
- **Invariant**: `<Enforceable rule>`
- **Verification Check**: `<Verification command or pattern>`

---

## 🛡️ Data & API Contracts

### [LL-DATA-001] <Title>
- **Trigger**: `<API endpoints, database queries, schemas>`
- **False Assumption**: `<Flawed belief>`
- **Root Cause**: `<Technical ground truth>`
- **Invariant**: `<Enforceable rule>`
- **Verification Check**: `<Verification command or pattern>`
