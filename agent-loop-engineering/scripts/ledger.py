#!/usr/bin/env python3
"""Externalized state ledger, dynamic model registry, and invariant manager for ALE."""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ANSI_ESCAPE_REGEX = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
INVARIANT_SECTION_SPLIT_REGEX = re.compile(r"(?=^###\s+\[[A-Z0-9-]+\])", re.MULTILINE)
SUPERSEDED_STATUS_REGEX = re.compile(
    r"^-\s+\*\*Status\*\*:\s*(?:Superseded|Dismissed|Promoted)\b",
    re.IGNORECASE | re.MULTILINE,
)
SETTINGS_CHANGE_REGEX = re.compile(
    r"changed setting `Model Selection` from [^\n]+? to ([^\n<]+?)(?:\.(?:\s|<|$)|<|$)",
    re.IGNORECASE,
)
MODEL_ID_PREFIXES = ("gemini-", "claude-", "gpt-", "o1-", "o3-", "o4-", "deepseek-", "llama-", "qwen-")
MODELS_CACHE_TTL_SECONDS = 300.0
NEGATIVE_CACHE_TTL_SECONDS = 60.0
NON_FLAGSHIP_HINTS = ("lite", "image", "embedding", "audio", "tts", "nano", "mini", "vision")
DEFAULT_TIER_SUBRANK: dict[str, dict[str, int]] = {
    "gemini": {"neon": 30, "carbon": 20, "argon": 10, "hydrogen": 5, "flash": 1},
    "claude": {"opus": 30, "sonnet": 20, "haiku": 10},
}
_DISCOVERY_MEMO: dict[tuple[str, str], tuple[float, float, list[dict[str, str]]]] = {}

FALLBACK_MODEL_CATALOG: list[dict[str, str]] = [
    {"id": "gemini-4-neon-high", "label": "Gemini 4 Neon (High)"},
    {"id": "gemini-4-neon-xhigh", "label": "Gemini 4 Neon (XHigh)"},
    {"id": "gemini-4-neon-medium", "label": "Gemini 4 Neon (Medium)"},
    {"id": "gemini-4-neon-low", "label": "Gemini 4 Neon (Low)"},
    {"id": "gemini-4-carbon-high", "label": "Gemini 4 Carbon (High)"},
    {"id": "gemini-4-carbon-medium", "label": "Gemini 4 Carbon (Medium)"},
    {"id": "gemini-4-carbon-low", "label": "Gemini 4 Carbon (Low)"},
    {"id": "gemini-4-argon-high", "label": "Gemini 4 Argon (High)"},
    {"id": "gemini-4-argon-medium", "label": "Gemini 4 Argon (Medium)"},
    {"id": "gemini-4-argon-low", "label": "Gemini 4 Argon (Low)"},
    {"id": "gemini-4-hydrogen-high", "label": "Gemini 4 Hydrogen (High)"},
    {"id": "gemini-4-hydrogen-xhigh", "label": "Gemini 4 Hydrogen (XHigh)"},
    {"id": "gemini-4-hydrogen-medium", "label": "Gemini 4 Hydrogen (Medium)"},
    {"id": "gemini-4-hydrogen-low", "label": "Gemini 4 Hydrogen (Low)"},
    {"id": "gemini-pro-orchestrator-neon", "label": "Orchestrator (Neon)"},
    {"id": "gemini-pro-orchestrator", "label": "Orchestrator (Carbon)"},
    {"id": "gemini-pro-orchestrator-argon", "label": "Orchestrator (Argon)"},
    {"id": "gemini-3.8-flash-high", "label": "Gemini 3.8 Flash (High)"},
    {"id": "gemini-3.8-flash-medium", "label": "Gemini 3.8 Flash (Medium)"},
    {"id": "gemini-3.8-flash-low", "label": "Gemini 3.8 Flash (Low)"},
    {"id": "claude-opus-5-5-high", "label": "Claude Opus 5.5 (High)"},
    {"id": "claude-opus-5-5-medium", "label": "Claude Opus 5.5 (Medium)"},
    {"id": "claude-opus-5-5-low", "label": "Claude Opus 5.5 (Low)"},
    {"id": "claude-sonnet-5-5-high", "label": "Claude Sonnet 5.5 (High)"},
    {"id": "claude-sonnet-5-5-medium", "label": "Claude Sonnet 5.5 (Medium)"},
    {"id": "claude-sonnet-5-5-low", "label": "Claude Sonnet 5.5 (Low)"},
    {"id": "gpt-oss-120b-medium", "label": "GPT-OSS 120B (Medium)"},
]


def get_output_root(override: str | None = None) -> Path:
    """Resolve the base output directory for ALE runtime state."""
    raw = override or os.environ.get("ALE_OUTPUT_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / "tmp" / "ale_harness"


def load_routing_config(output_dir: str | None = None) -> dict[str, Any]:
    """Load optional model routing overrides from <output_root>/model_routing.json."""
    cfg_path = get_output_root(output_dir) / "model_routing.json"
    if not cfg_path.is_file():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def parse_agy_models_output(raw_stdout: str) -> list[dict[str, str]]:
    """Parse 'agy models' stdout into ordered [{'id', 'label'}] dictionaries."""
    cleaned = ANSI_ESCAPE_REGEX.sub("", raw_stdout)
    models: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for line in cleaned.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        model_id = parts[0].strip()
        label = parts[1].strip()
        if not model_id.startswith(MODEL_ID_PREFIXES) or model_id in seen_ids:
            continue
        seen_ids.add(model_id)
        models.append({"id": model_id, "label": label})
    return models


def discover_servable_models(
    output_dir: str | None = None,
    refresh: bool = False,
) -> list[dict[str, str]]:
    """Discover live servable models via 'agy models' with memoization, negative cache, and fallback."""
    agy_bin = shutil.which("agy")
    if not agy_bin:
        return list(FALLBACK_MODEL_CATALOG)

    cache_path = get_output_root(output_dir) / "models_cache.json"
    memo_key = (agy_bin, str(cache_path))
    now = time.time()
    if not refresh and memo_key in _DISCOVERY_MEMO:
        cached_at, ttl, memo_models = _DISCOVERY_MEMO[memo_key]
        if (now - cached_at) < ttl and memo_models:
            return list(memo_models)

    if not refresh and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_bin = str(cached.get("agy_bin", ""))
            cached_at = float(cached.get("cached_at", 0.0) or 0.0)
            ttl = NEGATIVE_CACHE_TTL_SECONDS if cached.get("negative") else MODELS_CACHE_TTL_SECONDS
            cached_models = cached.get("models", [])
            if (
                cached_bin == agy_bin
                and (now - cached_at) < ttl
                and isinstance(cached_models, list)
                and cached_models
            ):
                _DISCOVERY_MEMO[memo_key] = (cached_at, ttl, cached_models)
                return list(cached_models)
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    parsed: list[dict[str, str]] = []
    try:
        proc = subprocess.run(
            [agy_bin, "models"],
            capture_output=True,
            text=True,
            check=False,
            timeout=25,
        )
        parsed = parse_agy_models_output(proc.stdout)
    except (subprocess.SubprocessError, OSError):
        parsed = []

    is_negative = not parsed
    result = parsed if parsed else list(FALLBACK_MODEL_CATALOG)
    ttl = NEGATIVE_CACHE_TTL_SECONDS if is_negative else MODELS_CACHE_TTL_SECONDS
    _DISCOVERY_MEMO[memo_key] = (now, ttl, result)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "agy_bin": agy_bin,
                    "cached_at": now,
                    "negative": is_negative,
                    "models": result,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
    return list(result)


def is_model_excluded(model_id: str, config: dict[str, Any]) -> bool:
    """Return True if model_id matches any exact or glob pattern in routing config exclude."""
    excludes = config.get("exclude", [])
    if not isinstance(excludes, list):
        return False
    lowered = model_id.lower()
    for pattern in excludes:
        pat = str(pattern).strip().lower()
        if not pat:
            continue
        if lowered == pat or fnmatch.fnmatch(lowered, pat):
            return True
    return False


def parse_model_descriptor(model_id: str, list_index: int = 0) -> dict[str, Any]:
    """Extract family, generation version, capability tier, and effort from a model ID."""
    lowered = model_id.strip().lower()
    if lowered.startswith("claude-"):
        family = "claude"
    elif lowered.startswith(("gpt-", "o1-", "o3-", "o4-")):
        family = "gpt"
    elif lowered.startswith("gemini-"):
        family = "gemini"
    else:
        family = lowered.split("-", 1)[0] if "-" in lowered else "unknown"

    effort = "high"
    for suffix in ("xhigh", "max", "high", "medium", "low"):
        if lowered.endswith(f"-{suffix}"):
            effort = suffix
            break

    is_orchestrator = "orchestrator" in lowered
    version_nums: list[int] = []
    if family == "claude":
        ver_match = re.search(r"claude-[a-z]+-(\d+)(?:[.-](\d+))?", lowered)
        if ver_match:
            version_nums = [int(ver_match.group(1)), int(ver_match.group(2) or 0)]
    elif family == "gemini":
        ver_match = re.search(r"gemini-(\d+)(?:[.-](\d+))?", lowered)
        if ver_match:
            version_nums = [int(ver_match.group(1)), int(ver_match.group(2) or 0)]
        elif is_orchestrator:
            version_nums = [4, 0]
    else:
        ver_match = re.search(r"(?:^|-)(\d+)(?:[.-](\d+))?(?=-|$)", lowered)
        if ver_match:
            version_nums = [int(ver_match.group(1)), int(ver_match.group(2) or 0)]
    version_tuple = (version_nums[0], version_nums[1]) if len(version_nums) >= 2 else (0, 0)

    if family == "gemini":
        tokens = set(re.split(r"[-_.\s]+", lowered))
        if is_orchestrator:
            role_tier = "orchestrator"
        elif tokens.intersection(NON_FLAGSHIP_HINTS):
            role_tier = "specialized"
        elif "flash" in lowered:
            role_tier = "research"
        elif "hydrogen" in lowered:
            role_tier = "fast-exec"
        elif "argon" in lowered:
            role_tier = "balanced"
        else:
            role_tier = "flagship"
    elif family == "claude":
        if "opus" in lowered:
            role_tier = "flagship"
        elif "haiku" in lowered:
            role_tier = "research"
        else:
            role_tier = "balanced"
    else:
        role_tier = "balanced"

    return {
        "id": lowered,
        "family": family,
        "version": version_tuple,
        "role_tier": role_tier,
        "effort": effort,
        "is_orchestrator": is_orchestrator,
        "list_index": list_index,
    }


def _effort_score(effort: str, prefer_effort: str = "high") -> int:
    """Rank effort labels relative to the preferred effort depth."""
    pref = prefer_effort.strip().lower()
    if pref == "xhigh":
        order = {"xhigh": 5, "max": 4, "high": 3, "medium": 2, "low": 1}
    elif pref == "medium":
        order = {"medium": 5, "high": 4, "low": 3, "xhigh": 2, "max": 1}
    elif pref == "low":
        order = {"low": 5, "medium": 4, "high": 3, "xhigh": 2, "max": 1}
    else:
        order = {"high": 5, "xhigh": 4, "max": 3, "medium": 2, "low": 1}
    return order.get(effort, 0)


def rank_models_for_slot(
    models: list[dict[str, str]],
    family: str,
    role_tier: str,
    prefer_effort: str = "high",
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Return ordered model IDs matching (family, role_tier) ranked newest/highest first."""
    cfg = config or {}
    tier_order_cfg = cfg.get("tier_order", {})
    custom_order = tier_order_cfg.get(family, []) if isinstance(tier_order_cfg, dict) else []

    scored: list[tuple[tuple[Any, ...], str]] = []
    for idx, entry in enumerate(models):
        model_id = str(entry.get("id", "")).strip().lower()
        if not model_id or is_model_excluded(model_id, cfg):
            continue
        desc = parse_model_descriptor(model_id, list_index=idx)
        if desc["family"] != family or desc["is_orchestrator"]:
            continue
        if desc["role_tier"] != role_tier:
            continue

        custom_bonus = 0
        if isinstance(custom_order, list) and custom_order:
            for pos, token in enumerate(custom_order):
                if str(token).lower() in model_id:
                    custom_bonus = len(custom_order) - pos
                    break

        default_subrank = 0
        for token, score in DEFAULT_TIER_SUBRANK.get(family, {}).items():
            if token in model_id:
                default_subrank = score
                break

        key = (
            custom_bonus,
            desc["version"],
            default_subrank,
            _effort_score(desc["effort"], prefer_effort),
            -idx,
        )
        scored.append((key, model_id))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [model_id for _, model_id in scored]


def _pick_first(candidates: list[str], fallback: str) -> str:
    """Return the first non-empty candidate or fallback."""
    return candidates[0] if candidates else fallback


def resolve_dynamic_defaults(
    output_dir: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Resolve current latest models per role/tier from live 'agy models' and routing overrides."""
    models = discover_servable_models(output_dir, refresh=refresh)
    cfg = load_routing_config(output_dir)
    prefer_effort = str(cfg.get("prefer_effort", "high") or "high").strip().lower()

    gemini_flagship = _pick_first(
        rank_models_for_slot(models, "gemini", "flagship", prefer_effort, cfg),
        "gemini-4-neon-high",
    )
    gemini_balanced = _pick_first(
        rank_models_for_slot(models, "gemini", "balanced", prefer_effort, cfg),
        gemini_flagship,
    )
    gemini_fast_high = _pick_first(
        rank_models_for_slot(models, "gemini", "fast-exec", "high", cfg),
        gemini_balanced,
    )
    gemini_fast_xhigh = _pick_first(
        rank_models_for_slot(models, "gemini", "fast-exec", "xhigh", cfg),
        gemini_fast_high,
    )
    gemini_research = _pick_first(
        rank_models_for_slot(models, "gemini", "research", "high", cfg),
        gemini_fast_high,
    )
    claude_flagship = _pick_first(
        rank_models_for_slot(models, "claude", "flagship", prefer_effort, cfg),
        "claude-opus-5-5-high",
    )
    claude_balanced = _pick_first(
        rank_models_for_slot(models, "claude", "balanced", prefer_effort, cfg),
        claude_flagship,
    )
    gpt_fallback = _pick_first(
        rank_models_for_slot(models, "gpt", "balanced", "medium", cfg),
        "gpt-oss-120b-medium",
    )

    return {
        "gemini_flagship": gemini_flagship,
        "gemini_balanced": gemini_balanced,
        "gemini_fast_exec_high": gemini_fast_high,
        "gemini_fast_exec_xhigh": gemini_fast_xhigh,
        "gemini_research": gemini_research,
        "claude_flagship": claude_flagship,
        "claude_balanced": claude_balanced,
        "gpt_fallback": gpt_fallback,
        "prefer_effort": prefer_effort,
        "routing_config_active": bool(cfg),
        "servable_count": len(models),
    }


def normalize_model_id(raw_name: str, output_dir: str | None = None) -> str:
    """Normalize a human-readable model label or alias into a canonical agy model ID."""
    cleaned = raw_name.strip().strip("`'\"").lower()
    if not cleaned:
        return resolve_dynamic_defaults(output_dir)["gemini_balanced"]

    models = discover_servable_models(output_dir)
    for entry in models:
        entry_id = str(entry.get("id", "")).strip().lower()
        entry_label = str(entry.get("label", "")).strip().lower()
        if cleaned == entry_id or cleaned == entry_label:
            return entry_id

    if cleaned.startswith(MODEL_ID_PREFIXES) and " " not in cleaned:
        return cleaned

    for entry in FALLBACK_MODEL_CATALOG:
        if cleaned == entry["id"] or cleaned == entry["label"].lower():
            return entry["id"]

    if "orchestrator" in cleaned:
        if "neon" in cleaned:
            return "gemini-pro-orchestrator-neon"
        if "argon" in cleaned:
            return "gemini-pro-orchestrator-argon"
        return "gemini-pro-orchestrator"

    effort = "high"
    if "xhigh" in cleaned:
        effort = "xhigh"
    elif "low" in cleaned:
        effort = "low"
    elif "medium" in cleaned:
        effort = "medium"

    if "neon" in cleaned:
        return f"gemini-4-neon-{effort}"
    if "carbon" in cleaned:
        return f"gemini-4-carbon-{effort if effort != 'xhigh' else 'high'}"
    if "hydrogen" in cleaned:
        return f"gemini-4-hydrogen-{effort}"
    if "argon" in cleaned:
        return f"gemini-4-argon-{effort if effort != 'xhigh' else 'high'}"
    if "flash" in cleaned:
        return _pick_first(
            rank_models_for_slot(models, "gemini", "research", effort),
            f"gemini-3.8-flash-{effort if effort != 'xhigh' else 'high'}",
        )
    if "opus" in cleaned:
        return _pick_first(
            rank_models_for_slot(models, "claude", "flagship", effort),
            f"claude-opus-5-5-{effort if effort != 'xhigh' else 'high'}",
        )
    if "sonnet" in cleaned:
        return _pick_first(
            rank_models_for_slot(models, "claude", "balanced", effort),
            f"claude-sonnet-5-5-{effort if effort != 'xhigh' else 'high'}",
        )
    if "gpt-oss" in cleaned or "120b" in cleaned:
        return _pick_first(
            rank_models_for_slot(models, "gpt", "balanced", "medium"),
            "gpt-oss-120b-medium",
        )
    return resolve_dynamic_defaults(output_dir)["gemini_balanced"]


def model_family(model_id: str, output_dir: str | None = None) -> str:
    """Return the provider family ('gemini', 'claude', or 'gpt') for a model ID."""
    norm = normalize_model_id(model_id, output_dir)
    if norm.startswith("claude-"):
        return "claude"
    if norm.startswith(("gpt-", "o1-", "o3-", "o4-")):
        return "gpt"
    return "gemini"


def is_flagship_model(model_id: str, output_dir: str | None = None) -> bool:
    """Return True when a model belongs to a flagship tier (Neon, Carbon, Opus, or XHigh)."""
    norm = normalize_model_id(model_id, output_dir)
    desc = parse_model_descriptor(norm)
    if desc["role_tier"] == "flagship":
        return True
    if desc["is_orchestrator"] and ("neon" in norm or norm == "gemini-pro-orchestrator"):
        return True
    return False


def extract_model_from_transcript(
    transcript_path: Path,
    output_dir: str | None = None,
) -> str | None:
    """Scan a conversation transcript.jsonl for the most recent Model Selection setting."""
    if not transcript_path.is_file():
        return None
    try:
        text = transcript_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    matches = SETTINGS_CHANGE_REGEX.findall(text)
    if matches:
        return normalize_model_id(matches[-1], output_dir)
    return None


def detect_active_session_model(output_dir: str | None = None) -> tuple[str, str]:
    """Auto-detect the current session model and return (model_id, detection_source)."""
    env_model = os.environ.get("ALE_AUTHOR_MODEL")
    if env_model:
        return normalize_model_id(env_model, output_dir), "env:ALE_AUTHOR_MODEL"

    runtime_file = get_output_root(output_dir) / "active_runtime_model.json"
    if runtime_file.is_file():
        try:
            data = json.loads(runtime_file.read_text(encoding="utf-8"))
            if data.get("model_id"):
                return (
                    normalize_model_id(str(data["model_id"]), output_dir),
                    "hook:active_runtime_model.json",
                )
        except (OSError, json.JSONDecodeError):
            pass

    env_transcript = os.environ.get("ALE_TRANSCRIPT_PATH")
    if env_transcript:
        found = extract_model_from_transcript(Path(env_transcript).expanduser(), output_dir)
        if found:
            return found, "transcript:ALE_TRANSCRIPT_PATH"

    gemini_dir = Path.home() / ".gemini"
    if gemini_dir.is_dir():
        transcripts = sorted(
            gemini_dir.glob("antigravity*/brain/*/.system_generated/logs/transcript.jsonl"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
            reverse=True,
        )
        for t_path in transcripts[:3]:
            found = extract_model_from_transcript(t_path, output_dir)
            if found:
                return found, f"transcript:{t_path.parent.parent.parent.name}"

    default_model = resolve_dynamic_defaults(output_dir)["gemini_balanced"]
    return default_model, f"default:{default_model}"


def get_knowledgebase_root() -> Path:
    """Resolve the centralized cloud-backed knowledgebase directory."""
    kb_override = os.environ.get("ALE_KNOWLEDGEBASE_ROOT")
    if kb_override:
        return Path(kb_override).expanduser().resolve()
    kb_default = Path.home() / "knowledgebase"
    if kb_default.exists():
        return kb_default.resolve()
    return Path.home() / "tmp" / "ale_knowledgebase"


def resolve_project_name(workspace_dir: Path) -> str:
    """Resolve the canonical knowledgebase project slug for a workspace directory."""
    resolved = workspace_dir.expanduser().resolve()
    gemini_config = (Path.home() / ".gemini" / "config").resolve()
    if resolved == gemini_config or resolved.is_relative_to(gemini_config):
        return "antigravity-skills"
    return resolved.name or "default-project"


def workspace_slug(workspace_dir: Path) -> str:
    """Create a deterministic directory slug for a workspace path."""
    resolved = str(workspace_dir.resolve())
    name = workspace_dir.resolve().name or "workspace"
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]
    return f"{name}-{digest}"


def resolve_counterpart_model(
    author_model: str,
    explicit_review_model: str | None = None,
    tier: int = 3,
    role: str = "review",
    output_dir: str | None = None,
) -> str:
    """Select a dynamic cross-family Counterpart Model according to Tiered Counterpart Routing."""
    norm_author = normalize_model_id(author_model, output_dir)
    author_fam = model_family(norm_author, output_dir)

    if explicit_review_model:
        norm_explicit = normalize_model_id(explicit_review_model, output_dir)
        if model_family(norm_explicit, output_dir) != author_fam:
            return norm_explicit

    cfg = load_routing_config(output_dir)
    pin_role = cfg.get("pin_role", {})
    if isinstance(pin_role, dict) and pin_role.get(role):
        pinned = normalize_model_id(str(pin_role[role]), output_dir)
        if model_family(pinned, output_dir) != author_fam:
            return pinned

    defaults = resolve_dynamic_defaults(output_dir)
    need_flagship = (
        role == "strike-breaker"
        or int(tier) >= 3
        or (author_fam == "gemini" and is_flagship_model(norm_author, output_dir))
    )

    if author_fam == "gemini":
        return defaults["claude_flagship"] if need_flagship else defaults["claude_balanced"]
    return defaults["gemini_flagship"] if need_flagship else defaults["gemini_balanced"]


def resolve_worker_model(
    role: str,
    active_impl: str,
    tier: int = 2,
    explicit_model: str | None = None,
    output_dir: str | None = None,
) -> str:
    """Resolve the latest dynamic model for non-review Worker Roles ('research', 'fast-exec')."""
    if explicit_model:
        return normalize_model_id(explicit_model, output_dir)

    cfg = load_routing_config(output_dir)
    pin_role = cfg.get("pin_role", {})
    if isinstance(pin_role, dict) and pin_role.get(role):
        return normalize_model_id(str(pin_role[role]), output_dir)

    defaults = resolve_dynamic_defaults(output_dir)
    if role == "research":
        return defaults["gemini_research"]
    if role == "fast-exec":
        use_xhigh = int(tier) >= 3 or is_flagship_model(active_impl, output_dir)
        return defaults["gemini_fast_exec_xhigh"] if use_xhigh else defaults["gemini_fast_exec_high"]
    return normalize_model_id(active_impl, output_dir)


def resolve_fallback_chain(
    author_model: str,
    primary_counterpart: str,
    output_dir: str | None = None,
) -> list[str]:
    """Return ordered cross-family fallback models derived dynamically from live servable models."""
    author_fam = model_family(author_model, output_dir)
    norm_primary = normalize_model_id(primary_counterpart, output_dir)
    defaults = resolve_dynamic_defaults(output_dir)
    models = discover_servable_models(output_dir)
    cfg = load_routing_config(output_dir)
    prefer_effort = defaults["prefer_effort"]

    raw_candidates: list[str] = []
    if author_fam == "gemini":
        raw_candidates.extend(
            [
                defaults["claude_flagship"],
                defaults["claude_balanced"],
                defaults["gpt_fallback"],
            ]
        )
    else:
        gemini_flagships = rank_models_for_slot(models, "gemini", "flagship", prefer_effort, cfg)
        gemini_balanced = rank_models_for_slot(models, "gemini", "balanced", prefer_effort, cfg)
        distinct_flagships: list[str] = []
        seen_prefixes: set[str] = set()
        for mid in gemini_flagships:
            stem = mid.rsplit("-", 1)[0]
            if stem not in seen_prefixes:
                seen_prefixes.add(stem)
                distinct_flagships.append(mid)
        raw_candidates.extend(distinct_flagships[:2])
        if gemini_balanced:
            raw_candidates.append(gemini_balanced[0])
        raw_candidates.append(defaults["gemini_fast_exec_xhigh"])
        if author_fam != "claude":
            raw_candidates.append(defaults["claude_balanced"])

    deduped: list[str] = []
    seen: set[str] = {norm_primary}
    for candidate in raw_candidates:
        norm_cand = normalize_model_id(candidate, output_dir)
        if (
            norm_cand not in seen
            and model_family(norm_cand, output_dir) != author_fam
            and not is_model_excluded(norm_cand, cfg)
        ):
            seen.add(norm_cand)
            deduped.append(norm_cand)
    return deduped[:3]


def detect_git_head(workspace_dir: Path) -> str:
    """Return the current HEAD SHA of the workspace or 'UNTRACKED' if not a Git repo."""
    proc = subprocess.run(
        ["git", "-C", str(workspace_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return "UNTRACKED"


def capture_baseline_dirty_state(
    workspace_dir: Path,
    session_dir: Path,
    base_sha: str,
) -> tuple[list[str], str | None, str | None]:
    """Snapshot pre-existing uncommitted dirty files at init so reviews separate prior work."""
    if base_sha == "UNTRACKED":
        return [], None, None
    status_proc = subprocess.run(
        ["git", "-C", str(workspace_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status_proc.returncode != 0 or not status_proc.stdout.strip():
        return [], None, None

    dirty_files: list[str] = []
    for line in status_proc.stdout.splitlines():
        if len(line) >= 4:
            dirty_files.append(line[3:].strip().strip('"'))

    diff_proc = subprocess.run(
        ["git", "-C", str(workspace_dir), "diff", base_sha],
        capture_output=True,
        text=True,
        check=False,
    )
    patch_text = diff_proc.stdout or ""
    patch_path = session_dir / "baseline.patch"
    patch_path.write_text(patch_text, encoding="utf-8")
    diff_sha = hashlib.sha256(patch_text.encode("utf-8")).hexdigest() if patch_text else None
    return sorted(set(dirty_files)), diff_sha, str(patch_path)


def get_session_dir(workspace_dir: Path, output_dir: str | None = None) -> Path:
    """Return the externalized directory holding ledger.json and SESSION_LL.md."""
    root = get_output_root(output_dir)
    session_dir = root / workspace_slug(workspace_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def load_ledger(session_dir: Path) -> dict[str, Any]:
    """Load ledger.json from the session directory or raise ValueError if missing."""
    ledger_path = session_dir / "ledger.json"
    if not ledger_path.is_file():
        raise ValueError(f"No active ledger found at {ledger_path}. Run 'ledger.py init' first.")
    return json.loads(ledger_path.read_text(encoding="utf-8"))


def save_ledger(session_dir: Path, data: dict[str, Any]) -> Path:
    """Write updated ledger dictionary to ledger.json."""
    data["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ledger_path = session_dir / "ledger.json"
    ledger_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return ledger_path


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a fresh ALE session ledger and SESSION_LL.md outside the Git tree."""
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    if args.author_model:
        author_model = normalize_model_id(args.author_model, args.output_dir)
        detection_source = "cli:--author_model"
    else:
        author_model, detection_source = detect_active_session_model(args.output_dir)
    impl_model = (
        normalize_model_id(args.impl_model, args.output_dir) if args.impl_model else author_model
    )
    review_counterpart = resolve_counterpart_model(
        impl_model, args.review_model, tier=args.tier, role="review", output_dir=args.output_dir
    )
    strike_counterpart = resolve_counterpart_model(
        impl_model, args.review_model, tier=3, role="strike-breaker", output_dir=args.output_dir
    )
    fast_exec_model = resolve_worker_model(
        "fast-exec", impl_model, tier=args.tier, output_dir=args.output_dir
    )
    research_model = resolve_worker_model(
        "research", impl_model, tier=args.tier, output_dir=args.output_dir
    )
    base_sha = detect_git_head(ws_dir)
    baseline_dirty_files, baseline_diff_sha, baseline_patch_path = capture_baseline_dirty_state(
        ws_dir, session_dir, base_sha
    )
    project_name = resolve_project_name(ws_dir)

    kb_ll_path = get_knowledgebase_root() / "lessons" / project_name / "LESSONS_LEARNED.md"
    repo_ll_path = ws_dir / "docs" / "LESSONS_LEARNED.md"
    session_ll_path = session_dir / "SESSION_LL.md"

    ledger_data: dict[str, Any] = {
        "status": "active",
        "project_name": project_name,
        "workspace_path": str(ws_dir),
        "session_dir": str(session_dir),
        "task": args.task,
        "tier": args.tier,
        "task_type": args.type,
        "base_sha": base_sha,
        "baseline_dirty_files": baseline_dirty_files,
        "baseline_diff_sha256": baseline_diff_sha,
        "baseline_patch_path": baseline_patch_path,
        "author_model": author_model,
        "model_detection_source": detection_source,
        "impl_model": impl_model,
        "counterpart_model": review_counterpart,
        "tier2_review_model": resolve_counterpart_model(
            impl_model, None, tier=2, role="review", output_dir=args.output_dir
        ),
        "strike_breaker_model": strike_counterpart,
        "fast_exec_model": fast_exec_model,
        "research_model": research_model,
        "fallback_chain": resolve_fallback_chain(impl_model, review_counterpart, args.output_dir),
        "dispatch_in_progress": None,
        "plan_sha256": None,
        "ll_gate_passed": False,
        "red_gate_passed": False,
        "red_gate_exempt": False,
        "intent_line": None,
        "checked_invariants": [],
        "friction_count": 0,
        "locked": False,
        "done_recorded": False,
        "verify_cmd": None,
        "review_rounds": 0,
        "review_verified": False,
        "allow_ship": False,
        "awaiting_user_approval": False,
        "session_ll_path": str(session_ll_path),
        "kb_ll_path": str(kb_ll_path),
        "repo_ll_path": str(repo_ll_path),
        "session_invariants": [],
    }
    ledger_path = save_ledger(session_dir, ledger_data)

    session_ll_content = (
        f"# Active Session Lessons Learned (SESSION_LL)\n\n"
        f"- **Task**: {args.task}\n"
        f"- **Tier · Type**: Tier {args.tier} · {args.type}\n"
        f"- **Impl Model**: `{impl_model}`\n"
        f"- **Review Counterpart**: `{review_counterpart}`\n"
        f"- **Strike-Breaker Counterpart**: `{strike_counterpart}`\n"
        f"- **Fast-Exec Worker**: `{fast_exec_model}`\n"
        f"- **Research Worker**: `{research_model}`\n"
        f"- **Base SHA**: `{base_sha}`\n\n"
        f"---\n\n"
        f"## Active Invariants\n"
    )
    session_ll_path.write_text(session_ll_content, encoding="utf-8")

    header = f"Tier {args.tier} · {args.type} · [Impl: {impl_model} | Review: {review_counterpart}]"
    print(json.dumps({
        "header": header,
        "ledger_path": str(ledger_path),
        "session_ll_path": str(session_ll_path),
        "kb_ll_exists": kb_ll_path.is_file(),
        "repo_ll_exists": repo_ll_path.is_file(),
        "baseline_dirty_files_count": len(baseline_dirty_files),
    }, indent=2))
    return 0


def cmd_bind_plan(args: argparse.Namespace) -> int:
    """Bind the approved plan.md SHA-256 hash into the active ledger."""
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    ledger = load_ledger(session_dir)

    plan_path = Path(args.plan_file).expanduser().resolve()
    if not plan_path.is_file():
        print(f"Error: Plan file not found at {plan_path}", file=sys.stderr)
        return 1

    digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    ledger["plan_sha256"] = digest
    ledger["plan_file"] = str(plan_path)
    save_ledger(session_dir, ledger)
    print(json.dumps({"status": "plan_bound", "plan_file": str(plan_path), "sha256": digest}, indent=2))
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    """Record LL_GATE and INTENT declaration in the active ledger."""
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    ledger = load_ledger(session_dir)

    if ledger.get("locked") is True or int(ledger.get("friction_count", 0)) >= 3:
        print("Error: Ledger is locked due to exhausted Friction Budget (3/3).", file=sys.stderr)
        return 1

    checked_list = [item.strip() for item in args.checked.split(",") if item.strip()]
    ledger["checked_invariants"] = checked_list
    ledger["intent_line"] = f"INTENT: {args.intent}"
    ledger["ll_gate_passed"] = True
    if ledger.get("status") == "verified":
        ledger["status"] = "active"
    save_ledger(session_dir, ledger)

    print(json.dumps({
        "status": "ll_gate_unlocked",
        "checked_invariants": checked_list,
        "intent_line": ledger["intent_line"],
    }, indent=2))
    return 0


def cmd_friction(args: argparse.Namespace) -> int:
    """Record a friction event, distill 5D Causal Chain into SESSION_LL.md, and route next action."""
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    ledger = load_ledger(session_dir)

    count = int(ledger.get("friction_count", 0)) + 1
    ledger["friction_count"] = count
    ledger["status"] = "active"
    ledger["ll_gate_passed"] = False
    ledger["done_recorded"] = False
    ledger["review_verified"] = False

    sll_id = f"SLL-{count:03d}"
    entry = {
        "id": sll_id,
        "title": args.title,
        "trigger": args.trigger,
        "false_assumption": args.assumption,
        "root_cause": args.root_cause,
        "invariant": args.invariant,
        "verification_check": args.check,
        "status": "Active",
    }
    ledger.setdefault("session_invariants", []).append(entry)

    session_ll_path = Path(ledger["session_ll_path"])
    markdown_block = (
        f"\n### [{sll_id}] {args.title}\n"
        f"- **Trigger**: `{args.trigger}`\n"
        f"- **False Assumption**: {args.assumption}\n"
        f"- **Root Cause**: {args.root_cause}\n"
        f"- **Invariant**: {args.invariant}\n"
        f"- **Verification Check**: `{args.check}`\n"
        f"- **Status**: Active\n"
    )
    with session_ll_path.open("a", encoding="utf-8") as handle:
        handle.write(markdown_block)

    impl_model = str(ledger.get("impl_model") or resolve_dynamic_defaults(args.output_dir)["gemini_balanced"])
    strike_counterpart = resolve_counterpart_model(
        impl_model, None, tier=3, role="strike-breaker", output_dir=args.output_dir
    )
    ledger["strike_breaker_model"] = strike_counterpart
    if count == 1:
        action = "CYCLE_1_RETRY"
        directive = "Build a tight reproduction loop (/diagnosing-bugs), re-run red_gate.py & ledger.py gate, and fix."
    elif count == 2:
        action = "CYCLE_2_STRIKE_BREAKER"
        directive = (
            f"Friction reached 2/3. Trigger Cross-Family Strike-Breaker via "
            f"'model_router.py --role strike-breaker' using Counterpart Model '{strike_counterpart}'."
        )
    else:
        action = "CYCLE_3_ABORT"
        ledger["locked"] = True
        directive = (
            "Friction Budget (3/3) EXHAUSTED. Edits are now LOCKED. "
            "Deliver an Honest Handback with observed outputs, SESSION_LL.md, and root-cause hypothesis."
        )

    save_ledger(session_dir, ledger)
    print(json.dumps({
        "sll_id": sll_id,
        "friction_count": count,
        "locked": ledger["locked"],
        "action_required": action,
        "counterpart_model": strike_counterpart,
        "directive": directive,
    }, indent=2))
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    """Execute the verification command and record DONE in the ledger only if it passes."""
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    ledger = load_ledger(session_dir)

    proc = subprocess.run(
        args.verify_cmd,
        shell=True,
        cwd=str(ws_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(json.dumps({
            "status": "verification_failed",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-1500:],
            "stderr": proc.stderr[-1500:],
        }, indent=2), file=sys.stderr)
        return 1

    ledger["done_recorded"] = True
    ledger["verify_cmd"] = args.verify_cmd
    ledger["verify_output"] = proc.stdout[-15000:]
    if args.twins:
        ledger["twins_line"] = f"TWINS: {args.twins}"
    if ledger.get("review_verified") is True:
        ledger["status"] = "verified"
    save_ledger(session_dir, ledger)

    print(json.dumps({
        "status": "done_recorded",
        "ledger_status": ledger["status"],
        "verify_cmd": args.verify_cmd,
        "stdout_preview": proc.stdout[-800:],
    }, indent=2))
    return 0


def update_section_status(markdown_text: str, rule_id: str, new_status: str) -> tuple[str, bool]:
    """Update the Status line of a specific ### [<rule_id>] section in a LESSONS_LEARNED document."""
    sections = INVARIANT_SECTION_SPLIT_REGEX.split(markdown_text)
    updated = False
    new_sections: list[str] = []
    header_pat = re.compile(rf"^###\s+\[{re.escape(rule_id)}\]\s+", re.MULTILINE)
    status_pat = re.compile(r"^-\s+\*\*Status\*\*:\s*.*$", re.MULTILINE)
    replacement_line = f"- **Status**: {new_status}"

    for sec in sections:
        if header_pat.search(sec):
            updated = True
            if status_pat.search(sec):
                sec = status_pat.sub(replacement_line, sec)
            else:
                sec = sec.rstrip() + f"\n{replacement_line}\n"
        new_sections.append(sec)
    return "".join(new_sections), updated


def mark_section_superseded(markdown_text: str, rule_id: str, superseded_by: str) -> tuple[str, bool]:
    """Mark a specific ### [<rule_id>] section as Superseded in a LESSONS_LEARNED markdown string."""
    return update_section_status(markdown_text, rule_id, f"Superseded by {superseded_by}")


def find_unresolved_session_invariants(ledger: dict[str, Any]) -> list[str]:
    """Return IDs of session_invariants whose status is still Active."""
    unresolved: list[str] = []
    for item in ledger.get("session_invariants", []):
        if isinstance(item, dict) and str(item.get("status", "Active")).strip().lower() == "active":
            unresolved.append(str(item.get("id", "UNKNOWN")))
    return unresolved


def cmd_ruling(args: argparse.Namespace) -> int:
    """Record user ruling (such as --allow_ship or --complete) in the active ledger."""
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    ledger = load_ledger(session_dir)

    if args.complete:
        unresolved = find_unresolved_session_invariants(ledger)
        if unresolved:
            print(json.dumps({
                "status": "completion_blocked",
                "reason": (
                    "Active SESSION_LL invariants must be promoted ('promote-ll') or "
                    "explicitly dismissed ('dismiss-ll') before completing the session."
                ),
                "unresolved_session_invariants": unresolved,
            }, indent=2), file=sys.stderr)
            return 1

    if args.allow_ship:
        ledger["allow_ship"] = True
    if args.awaiting_user_approval is not None:
        ledger["awaiting_user_approval"] = args.awaiting_user_approval
    if args.complete:
        ledger["status"] = "completed"

    save_ledger(session_dir, ledger)
    print(json.dumps({
        "status": ledger["status"],
        "allow_ship": ledger["allow_ship"],
        "awaiting_user_approval": ledger["awaiting_user_approval"],
    }, indent=2))
    return 0


def cmd_promote_ll(args: argparse.Namespace) -> int:
    """Promote a verified SESSION_LL entry to the centralized knowledgebase LESSONS_LEARNED.md."""
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    ledger = load_ledger(session_dir)

    invariants: list[dict[str, Any]] = ledger.get("session_invariants", [])
    target = next((item for item in invariants if item.get("id") == args.id), None)
    if not target:
        print(f"Error: Invariant ID '{args.id}' not found in active ledger.", file=sys.stderr)
        return 1

    kb_ll_path = Path(ledger["kb_ll_path"])
    kb_ll_path.parent.mkdir(parents=True, exist_ok=True)
    if not kb_ll_path.is_file():
        template_path = Path(__file__).resolve().parent.parent / "templates" / "LESSONS_LEARNED.md"
        if template_path.is_file():
            kb_ll_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            kb_ll_path.write_text("# Project Lessons Learned & Invariants (PROJECT_LL)\n\n", encoding="utf-8")

    existing_text = kb_ll_path.read_text(encoding="utf-8")
    existing_ids = re.findall(r"\[LL-[A-Z]+-(\d+)\]", existing_text)
    next_num = max([int(num) for num in existing_ids], default=0) + 1
    category = args.category.upper()
    new_id = f"LL-{category}-{next_num:03d}"

    promoted_block = (
        f"\n### [{new_id}] {target['title']}\n"
        f"- **Trigger**: `{target['trigger']}`\n"
        f"- **False Assumption**: {target['false_assumption']}\n"
        f"- **Root Cause**: {target['root_cause']}\n"
        f"- **Invariant**: {target['invariant']}\n"
        f"- **Verification Check**: `{target['verification_check']}`\n"
        f"- **Status**: Active\n"
    )
    with kb_ll_path.open("a", encoding="utf-8") as handle:
        handle.write(promoted_block)

    promoted_status = f"Promoted to {new_id}"
    target["status"] = promoted_status
    session_ll_path = Path(str(ledger.get("session_ll_path", "")))
    if session_ll_path.is_file():
        updated_sll, changed = update_section_status(
            session_ll_path.read_text(encoding="utf-8"), args.id, promoted_status
        )
        if changed:
            session_ll_path.write_text(updated_sll, encoding="utf-8")
    save_ledger(session_dir, ledger)

    total_rules = len(existing_ids) + 1
    print(json.dumps({
        "status": "promoted",
        "promoted_id": new_id,
        "source_id": args.id,
        "kb_ll_path": str(kb_ll_path),
        "total_global_rules": total_rules,
        "compaction_required": total_rules > 20,
    }, indent=2))
    return 0


def cmd_dismiss_ll(args: argparse.Namespace) -> int:
    """Dismiss a session-only SLL entry that does not pass the Three-Test promotion filter."""
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    ledger = load_ledger(session_dir)

    reason = args.reason.strip()
    if not reason:
        print("Error: --reason must be non-empty when dismissing a session invariant.", file=sys.stderr)
        return 1

    invariants: list[dict[str, Any]] = ledger.get("session_invariants", [])
    target = next((item for item in invariants if item.get("id") == args.id), None)
    if not target:
        print(f"Error: Invariant ID '{args.id}' not found in active ledger.", file=sys.stderr)
        return 1

    dismissed_status = f"Dismissed ({reason})"
    target["status"] = dismissed_status
    session_ll_path = Path(str(ledger.get("session_ll_path", "")))
    if session_ll_path.is_file():
        updated_sll, changed = update_section_status(
            session_ll_path.read_text(encoding="utf-8"), args.id, dismissed_status
        )
        if changed:
            session_ll_path.write_text(updated_sll, encoding="utf-8")
    save_ledger(session_dir, ledger)

    print(json.dumps({
        "status": "dismissed",
        "dismissed_id": args.id,
        "reason": reason,
    }, indent=2))
    return 0


def cmd_retire_ll(args: argparse.Namespace) -> int:
    """Mark an obsolete LESSONS_LEARNED invariant as Superseded so red_gate.py skips its check."""
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    ledger = load_ledger(session_dir)

    candidate_paths = [
        Path(str(ledger.get("kb_ll_path", ""))),
        Path(str(ledger.get("repo_ll_path", ""))),
        Path(str(ledger.get("session_ll_path", ""))),
    ]
    touched_files: list[str] = []
    for path in candidate_paths:
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        new_content, changed = mark_section_superseded(content, args.id, args.superseded_by)
        if changed:
            path.write_text(new_content, encoding="utf-8")
            touched_files.append(str(path))

    for item in ledger.get("session_invariants", []):
        if item.get("id") == args.id:
            item["status"] = f"Superseded by {args.superseded_by}"
            save_ledger(session_dir, ledger)
            touched_files.append(str(session_dir / "ledger.json"))

    if not touched_files:
        print(f"Error: Invariant ID '{args.id}' not found in knowledgebase or session LL files.", file=sys.stderr)
        return 1

    print(json.dumps({
        "status": "retired",
        "retired_id": args.id,
        "superseded_by": args.superseded_by,
        "updated_files": touched_files,
    }, indent=2))
    return 0


def cmd_check_portability(args: argparse.Namespace) -> int:
    """Scan a skill or plugin directory for hardcoded personal paths or non-portable usernames."""
    target_dir = Path(args.target_dir).expanduser().resolve()
    if not target_dir.exists():
        print(f"Error: Target path {target_dir} does not exist.", file=sys.stderr)
        return 1

    user = os.environ.get("USER", "")
    home_str = str(Path.home())
    patterns: list[tuple[str, re.Pattern[str]]] = [
        ("hardcoded-home-path", re.compile(re.escape(home_str))),
        ("hardcoded-linux-home", re.compile(r"/home/[a-zA-Z0-9_-]+")),
    ]
    if user and len(user) >= 3:
        patterns.append(("hardcoded-username", re.compile(rf"~{re.escape(user)}\b")))

    violations: list[dict[str, Any]] = []
    files = [target_dir] if target_dir.is_file() else sorted(target_dir.rglob("*"))
    for path in files:
        if not path.is_file() or "__pycache__" in path.parts or ".git" in path.parts:
            continue
        if path.suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pyc", ".tar", ".gz"):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for idx, line in enumerate(lines, start=1):
            for rule_name, regex in patterns:
                if regex.search(line):
                    violations.append({
                        "file": str(path.relative_to(target_dir) if path != target_dir else path.name),
                        "line": idx,
                        "rule": rule_name,
                        "snippet": line.strip()[:120],
                    })

    if violations:
        print(json.dumps({"passed": False, "violations": violations}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps({"passed": True, "target_dir": str(target_dir), "violations": []}, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print the current workspace ledger status."""
    ws_dir = Path(args.workspace).expanduser().resolve()
    session_dir = get_session_dir(ws_dir, args.output_dir)
    ledger = load_ledger(session_dir)
    print(json.dumps(ledger, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser for ledger.py."""
    parser = argparse.ArgumentParser(description="ALE Externalized State Ledger CLI.")
    parser.add_argument(
        "--workspace",
        default=os.getcwd(),
        help="Target workspace path (defaults to current working directory).",
    )
    parser.add_argument(
        "--output_dir",
        "--base_dir",
        dest="output_dir",
        default=None,
        help="Override base directory for ALE ledger outputs (or set ALE_OUTPUT_ROOT).",
    )

    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_init = sub.add_parser("init", help="Initialize an active ALE ledger.")
    p_init.add_argument("--task", required=True, help="Task description.")
    p_init.add_argument("--tier", type=int, choices=[1, 2, 3], default=2, help="Task tier (1, 2, or 3).")
    p_init.add_argument("--type", default="Feature", help="Task type (Feature, Bugfix, Refactor, Skill).")
    p_init.add_argument("--author_model", default=None, help="Primary session model.")
    p_init.add_argument("--impl_model", default=None, help="Model used for implementation.")
    p_init.add_argument("--review_model", default=None, help="Explicit override for Counterpart Model.")

    p_plan = sub.add_parser("bind-plan", help="Bind approved plan.md SHA-256 hash.")
    p_plan.add_argument("--plan_file", required=True, help="Path to approved plan.md.")

    p_gate = sub.add_parser("gate", help="Record LL_GATE and INTENT declaration.")
    p_gate.add_argument("--checked", default="NONE", help="Comma-separated list of checked LL IDs.")
    p_gate.add_argument("--intent", required=True, help="INTENT statement: code does X; check expects Y; spec says Z.")

    p_fric = sub.add_parser("friction", help="Record a friction event and 5D Causal Chain.")
    p_fric.add_argument("--title", required=True, help="Short title of the constraint.")
    p_fric.add_argument("--trigger", required=True, help="File, module, or command where friction occurred.")
    p_fric.add_argument("--assumption", required=True, help="Flawed assumption held by the agent.")
    p_fric.add_argument("--root_cause", required=True, help="Objective technical root cause discovered.")
    p_fric.add_argument("--invariant", required=True, help="Positive rule preventing recurrence.")
    p_fric.add_argument("--check", required=True, help="Executable check ('cmd: ...' or 'regex-forbid: ...').")

    p_done = sub.add_parser("done", help="Run verification command and record DONE.")
    p_done.add_argument("--verify_cmd", required=True, help="Verification shell command.")
    p_done.add_argument("--twins", default=None, help="TWINS search summary.")

    p_rule = sub.add_parser("ruling", help="Record user ship or completion ruling.")
    p_rule.add_argument("--allow_ship", action="store_true", help="Unlock the Ship Gate for git push / PR creation.")
    p_rule.add_argument("--awaiting_user_approval", type=bool, default=None, help="Pause Stop gate while awaiting user.")
    p_rule.add_argument("--complete", action="store_true", help="Mark the ALE ledger session as completed.")

    p_prom = sub.add_parser("promote-ll", help="Promote a SESSION_LL entry to knowledgebase LESSONS_LEARNED.md.")
    p_prom.add_argument("--id", required=True, help="Session LL ID (e.g., SLL-001).")
    p_prom.add_argument("--category", default="ARCH", choices=["ARCH", "TOOL", "DATA"], help="Target LL category.")

    p_dism = sub.add_parser("dismiss-ll", help="Dismiss a session-only SLL entry that stays outside PROJECT_LL.")
    p_dism.add_argument("--id", required=True, help="Session LL ID (e.g., SLL-001).")
    p_dism.add_argument("--reason", required=True, help="Reason the invariant does not pass Three-Test promotion.")

    p_retire = sub.add_parser("retire-ll", help="Mark an obsolete LESSONS_LEARNED invariant as Superseded.")
    p_retire.add_argument("--id", required=True, help="Invariant ID to retire (e.g., LL-ARCH-008).")
    p_retire.add_argument("--superseded_by", required=True, help="Replacement Invariant ID (e.g., LL-ARCH-009).")

    p_port = sub.add_parser("check-portability", help="Verify zero hardcoded personal paths in a directory.")
    p_port.add_argument("target_dir", help="Skill or plugin directory to scan.")

    sub.add_parser("status", help="Display current ledger status.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for ledger.py."""
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {
        "init": cmd_init,
        "bind-plan": cmd_bind_plan,
        "gate": cmd_gate,
        "friction": cmd_friction,
        "done": cmd_done,
        "ruling": cmd_ruling,
        "promote-ll": cmd_promote_ll,
        "dismiss-ll": cmd_dismiss_ll,
        "retire-ll": cmd_retire_ll,
        "check-portability": cmd_check_portability,
        "status": cmd_status,
    }
    try:
        return dispatch[args.subcommand](args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
