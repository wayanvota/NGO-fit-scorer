"""Scoring orchestration for the template: dynamic dimensions and data-driven
hard/soft filters. The weighted math and knockout logic live here in plain
Python so results are auditable; the model supplies per-dimension judgment.
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import claude_agents


def apply_filters(parsed: Dict[str, Any], scored: Dict[str, Any],
                  profile: Dict[str, Any]) -> Dict[str, Any]:
    """Split tripped filters into hard (disqualify) and soft (cap tier)."""
    flags = scored.get("hard_filter_flags", {})
    tripped: List[str] = []
    soft: List[Dict[str, str]] = []
    detail: Dict[str, str] = {}

    for f in profile.get("hard_filters", []):
        if not f.get("enabled"):
            continue
        key = f["key"]
        if flags.get(key, {}).get("tripped"):
            reason = flags[key].get("reason", "")
            detail[key] = reason
            if f.get("mode", "hard") == "soft":
                soft.append({"key": key, "reason": reason})
            else:
                tripped.append(key)

    # Optional deterministic knockout: small AND fully restricted.
    th = profile.get("thresholds", {})
    if th.get("small_and_fully_restricted_knockout"):
        amt = parsed.get("amount")
        floor = th.get("grant_floor", 0) or 0
        if amt is not None and floor and amt < floor and parsed.get("funding_type") == "fully_restricted":
            tripped.append("small_and_fully_restricted")
            detail["small_and_fully_restricted"] = (
                f"Amount {amt:,.0f} is below the {floor:,.0f} floor and fully restricted.")

    return {"disqualified": bool(tripped), "tripped": tripped, "soft": soft, "detail": detail}


def compute_overall(scored: Dict[str, Any], profile: Dict[str, Any]) -> float:
    dims = scored.get("dimensions", {})
    total_w = sum(d.get("weight", 0) for d in profile.get("dimensions", [])) or 1
    acc = 0.0
    for d in profile.get("dimensions", []):
        sub = dims.get(d["key"], {}).get("score", 0)
        acc += d.get("weight", 0) * float(sub)
    return round(acc / total_w, 1)


def tier_for(overall: float, disqualified: bool, profile: Dict[str, Any]) -> str:
    if disqualified:
        return "Disqualified"
    t = profile.get("tiers", {"pursue": 80, "pursue_review": 60, "watch": 40})
    if overall >= t["pursue"]:
        return "Pursue"
    if overall >= t["pursue_review"]:
        return "Pursue with review"
    if overall >= t["watch"]:
        return "Watch"
    return "Pass"


def _cap_tier_at_watch(tier: str) -> str:
    return "Watch" if tier in ("Pursue", "Pursue with review") else tier


def score_pipeline(text: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    parsed = claude_agents.parse_opportunity(text)
    scored = claude_agents.score_opportunity(parsed, profile)
    hfr = apply_filters(parsed, scored, profile)

    if hfr["disqualified"]:
        overall = 0.0
        tier = "Disqualified"
    else:
        overall = compute_overall(scored, profile)
        tier = tier_for(overall, False, profile)
        if hfr.get("soft"):
            tier = _cap_tier_at_watch(tier)

    memo = claude_agents.write_memo(parsed, scored, overall, tier, hfr, profile)

    return {"parsed": parsed, "parse_confidence": parsed.get("parse_confidence", "unknown"),
            "dimension_scores": scored.get("dimensions", {}), "hard_filter_result": hfr,
            "overall_score": overall, "tier": tier, "memo_markdown": memo}
