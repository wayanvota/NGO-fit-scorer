"""Claude-powered agents: parser, scorer, memo, recalibration, and a profile
bootstrap agent. All are org-agnostic: they read the scoring dimensions and
hard filters from the active StrategyProfile, which is data, not code.

With no ANTHROPIC_API_KEY the module runs in MOCK mode (deterministic heuristics)
so the app works end to end for a demo.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict, List

from .config import settings

_client = None


def _today() -> str:
    return date.today().isoformat()


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _call_json(model: str, system: str, user: str, schema: Dict[str, Any],
               tool_name: str, max_tokens: int = 2500) -> Dict[str, Any]:
    client = _get_client()
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        tools=[{"name": tool_name, "description": f"Return the {tool_name} result.",
                "input_schema": schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user}])
    for block in resp.content:
        if block.type == "tool_use":
            return dict(block.input)
    raise RuntimeError("Model did not return a tool_use block")


def _call_text(model: str, system: str, user: str, max_tokens: int = 2400) -> str:
    client = _get_client()
    resp = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in resp.content if b.type == "text").strip()


# ---------------------------------------------------------------------------
# Helpers to read the data-driven profile
# ---------------------------------------------------------------------------
def enabled_filters(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [f for f in profile.get("hard_filters", []) if f.get("enabled")]


def dimension_keys(profile: Dict[str, Any]) -> List[str]:
    return [d["key"] for d in profile.get("dimensions", [])]


# ---------------------------------------------------------------------------
# 1. Parser
# ---------------------------------------------------------------------------
_PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "funder": {"type": "string"},
        "program": {"type": "string"},
        "purpose": {"type": "string"},
        "geographies": {"type": "array", "items": {"type": "string"}},
        "amount": {"type": ["number", "null"]},
        "amount_text": {"type": "string"},
        "funding_type": {"type": "string",
                         "enum": ["unrestricted", "partially_restricted", "fully_restricted", "unknown"]},
        "duration": {"type": "string"},
        "deadline": {"type": "string"},
        "eligibility_requirements": {"type": "array", "items": {"type": "string"}},
        "reporting_burden": {"type": "string", "enum": ["low", "medium", "high", "unknown"]},
        "parse_confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["title", "funder", "purpose", "geographies", "funding_type", "parse_confidence"],
}


def parse_opportunity(text: str) -> Dict[str, Any]:
    if settings.mock_mode:
        return _mock_parse(text)
    system = (
        "You extract structured facts from a funding opportunity (an RFP, grant call, or funder "
        "email). Only report what the text supports. If a field is not stated, leave it empty or "
        "null and lower parse_confidence. Put the funding amount as a number in 'amount'.")
    return _call_json(settings.fast_model, system, text[:20000], _PARSE_SCHEMA,
                      "parsed_opportunity", max_tokens=1500)


# ---------------------------------------------------------------------------
# 2. Scorer (schema built dynamically from the profile)
# ---------------------------------------------------------------------------
def _score_schema(profile: Dict[str, Any]) -> Dict[str, Any]:
    dim_obj = {"type": "object",
               "properties": {"score": {"type": "number", "minimum": 0, "maximum": 100},
                              "justification": {"type": "string"}, "evidence": {"type": "string"}},
               "required": ["score", "justification"]}
    flag_obj = {"type": "object",
                "properties": {"tripped": {"type": "boolean"}, "reason": {"type": "string"}},
                "required": ["tripped"]}
    dkeys = dimension_keys(profile)
    fkeys = [f["key"] for f in enabled_filters(profile)]
    return {
        "type": "object",
        "properties": {
            "dimensions": {"type": "object",
                           "properties": {k: dim_obj for k in dkeys}, "required": dkeys},
            "hard_filter_flags": {"type": "object",
                                  "properties": {k: flag_obj for k in fkeys}, "required": fkeys},
        },
        "required": ["dimensions", "hard_filter_flags"],
    }


def score_opportunity(parsed: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    if settings.mock_mode:
        return _mock_score(parsed, profile)
    dim_desc = "\n".join(f"- {d['key']} ({d['label']}): {d['description']}"
                         for d in profile.get("dimensions", []))
    filt_desc = "\n".join(
        f"- {f['key']} ({f.get('mode', 'hard')}): {f['description']}" for f in enabled_filters(profile))
    org = profile.get("profile_doc", {})
    system = (
        f"Today's date is {_today()}. Use it to judge deadline runway and feasibility.\n\n"
        "You are a funding-fit scoring engine. Score a funding opportunity against the "
        "organization's strategy profile provided below. Score each dimension 0-100 with a "
        "one-line justification and the evidence you used. Be a critical sparring partner, not a "
        "cheerleader: reward genuine strategic fit and mark down weak fit plainly. Judge only "
        "against this organization's stated strategy, not generic desirability.\n\n"
        "Hard-filter flags are exceptional. Apply a HIGH bar and default tripped=false. Set "
        "tripped=true only when the opportunity's own text makes the disqualifier explicit and "
        "unavoidable. A 'soft' filter (see the mode) means the blocker is often resolvable (for "
        "example, ineligible org type can be solved with a partner or co-applicant), so trip it "
        "only when clearly blocking, knowing it will flag rather than kill the opportunity. When "
        "eligibility or fit is merely unclear or borderline, set tripped=false and let the "
        "weighted dimensions carry the judgement.\n\n"
        f"SCORING DIMENSIONS:\n{dim_desc}\n\nHARD FILTERS:\n{filt_desc}"
    )
    user = ("ORGANIZATION STRATEGY (JSON):\n" + json.dumps(org, indent=2)
            + "\n\nTHRESHOLDS:\n" + json.dumps(profile.get("thresholds", {}), indent=2)
            + "\n\nPARSED OPPORTUNITY (JSON):\n" + json.dumps(parsed, indent=2))
    return _call_json(settings.strong_model, system, user, _score_schema(profile),
                      "opportunity_score", max_tokens=2600)


# ---------------------------------------------------------------------------
# 3. Memo
# ---------------------------------------------------------------------------
def write_memo(parsed, scored, overall, tier, hard_filter_result, profile) -> str:
    if settings.mock_mode:
        return _mock_memo(parsed, scored, overall, tier, hard_filter_result)
    system = (
        f"Today's date is {_today()}. Any date you suggest must be in the future and before the "
        "opportunity's deadline; never propose a date that has already passed.\n\n"
        "You write a one-page go/no-go memo for a fundraising team. Peers, not students: "
        "argument-driven, specific, no filler. Do not use em dashes. Keep it to one page and "
        "finish every section. Include, as markdown: a headline recommendation with the score and "
        "confidence; a one-line per-dimension breakdown; top three reasons for and against; key "
        "risks and the biggest open question; a suggested next step with an owner and a future "
        "date; and a short 'what would change this' line. Every factual claim about the "
        "opportunity must trace to the parsed source.\n\n"
        "Stay consistent with hard_filter_result. If disqualified is true it is a NO-GO: do not "
        "offer a path to pursue. If the 'soft' list is non-empty the opportunity is CONDITIONAL, "
        "not disqualified: a resolvable blocker stands in the way; frame it as conditional, lead "
        "with the blocker and the step that would resolve it, and never call it disqualified.")
    payload = {"parsed": parsed, "dimensions": scored.get("dimensions", {}),
               "overall_score": overall, "tier": tier, "hard_filter_result": hard_filter_result}
    return _call_text(settings.strong_model, system, json.dumps(payload, indent=2), max_tokens=2400)


# ---------------------------------------------------------------------------
# 4. Recalibration
# ---------------------------------------------------------------------------
_RECAL_SCHEMA = {
    "type": "object",
    "properties": {
        "proposed_dimension_weights": {"type": "object"},
        "proposed_threshold_changes": {"type": "object"},
        "proposed_filter_changes": {"type": "object"},
        "rationale": {"type": "string"},
        "expected_effect": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["proposed_dimension_weights", "rationale", "expected_effect", "confidence"],
}


def analyze_for_recalibration(profile, evidence) -> Dict[str, Any]:
    if settings.mock_mode:
        return {"proposed_dimension_weights": {d["key"]: d["weight"] for d in profile.get("dimensions", [])},
                "proposed_threshold_changes": {}, "proposed_filter_changes": {},
                "rationale": "Mock mode: add ANTHROPIC_API_KEY and accumulate outcomes for a real proposal.",
                "expected_effect": "No change.", "confidence": "low"}
    system = (
        "You review scoring feedback and real funding outcomes and propose a recalibration of the "
        "scoring profile. Compare model scores against staff overrides and won/lost outcomes to "
        "find where the model is systematically high or low and on which dimensions. Propose "
        "adjusted dimension weights (they must sum to 100), threshold changes, and filter changes "
        "only where the evidence supports them. Be conservative when the sample is small.")
    user = "PROFILE:\n" + json.dumps(profile, indent=2) + "\n\nEVIDENCE:\n" + json.dumps(evidence, indent=2)
    return _call_json(settings.recal_model, system, user, _RECAL_SCHEMA, "recalibration_proposal", max_tokens=2000)


# ---------------------------------------------------------------------------
# 5. Bootstrap: draft a full profile from an org description + strategic plan
# ---------------------------------------------------------------------------
_BOOTSTRAP_SCHEMA = {
    "type": "object",
    "properties": {
        "profile_doc": {
            "type": "object",
            "properties": {"mission": {"type": "string"}, "priorities": {"type": "string"},
                           "funding_preference": {"type": "string"}, "values_guardrails": {"type": "string"}},
            "required": ["mission", "priorities"],
        },
        "dimensions": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"key": {"type": "string"}, "label": {"type": "string"},
                                     "description": {"type": "string"}, "weight": {"type": "number"}},
                      "required": ["key", "label", "description", "weight"]},
        },
        "hard_filters": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"key": {"type": "string"}, "label": {"type": "string"},
                                     "description": {"type": "string"}, "enabled": {"type": "boolean"},
                                     "mode": {"type": "string", "enum": ["hard", "soft"]}},
                      "required": ["key", "label", "description", "enabled", "mode"]},
        },
        "thresholds": {"type": "object"},
        "tiers": {"type": "object"},
        "rationale": {"type": "string"},
    },
    "required": ["profile_doc", "dimensions", "hard_filters", "thresholds", "tiers", "rationale"],
}


def bootstrap_profile(org_name: str, org_description: str, plan_text: str) -> Dict[str, Any]:
    if settings.mock_mode:
        return _mock_bootstrap(org_name)
    system = (
        "You design a funding-fit scoring profile for a nonprofit or mission-driven organization. "
        "From the organization's description and strategic plan, draft a SHARP, opinionated "
        "profile, not a bland generic one. Produce: a concise mission and priorities summary; 5 to "
        "8 scoring dimensions with keys (snake_case), labels, one-line descriptions, and integer "
        "weights that SUM TO 100 and reflect what actually matters most to this org; hard filters "
        "with mode 'hard' (zeroes the score) for truly binary disqualifiers and mode 'soft' (caps "
        "the tier, for resolvable blockers like org-type eligibility); thresholds (currency, a "
        "grant_floor and strategic_tier in that currency if the plan implies them, and a "
        "restricted_penalty of mild/moderate/strong); and tier cutoffs (default pursue 80, "
        "pursue_review 60, watch 40). Make the weights and filters specific to this org's strategy. "
        "Explain your choices in 'rationale'.")
    user = (f"ORGANIZATION: {org_name}\n\nDESCRIPTION:\n{org_description}\n\n"
            f"STRATEGIC PLAN / SOURCE MATERIAL:\n{plan_text[:40000]}")
    return _call_json(settings.recal_model, system, user, _BOOTSTRAP_SCHEMA,
                      "profile_draft", max_tokens=3000)


# ===========================================================================
# MOCK implementations
# ===========================================================================
_MONEY_RE = re.compile(r"\$?\s?([0-9][0-9,\.]*)\s*(k|thousand|m|mn|million|bn|billion)?", re.I)
_STOP = set("the a an and or of to for in on with by from is are be this that funding grant "
            "support project program organization organisation will our your their".split())


def _guess_amount(text: str):
    best = None
    for m in _MONEY_RE.finditer(text):
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        val *= {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
                "bn": 1e9, "billion": 1e9}.get(unit, 1)
        if val >= 1000 and (best is None or val > best):
            best = val
    return best


def _mock_parse(text: str) -> Dict[str, Any]:
    t = text.lower()
    ftype = ("unrestricted" if ("unrestricted" in t or "general operating" in t or "core support" in t)
             else "fully_restricted" if ("restricted" in t or "project-specific" in t) else "unknown")
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "Untitled opportunity")
    amt = _guess_amount(text)
    return {"title": first[:120], "funder": "Unknown funder", "program": "", "purpose": first[:300],
            "geographies": [], "amount": amt, "amount_text": f"{amt:,.0f}" if amt else "",
            "funding_type": ftype, "duration": "", "deadline": "", "eligibility_requirements": [],
            "reporting_burden": "unknown", "parse_confidence": "low"}


def _words(s: str):
    return {w for w in re.findall(r"[a-z]{4,}", (s or "").lower()) if w not in _STOP}


def _mock_score(parsed: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    opp_words = _words(json.dumps(parsed))
    dims = {}
    for d in profile.get("dimensions", []):
        overlap = len(opp_words & _words(d["description"] + " " + d.get("label", "")))
        score = max(20, min(90, 45 + 10 * overlap))
        dims[d["key"]] = {"score": score, "justification": "Mock keyword-overlap heuristic.",
                          "evidence": "(mock)"}
    flags = {f["key"]: {"tripped": False, "reason": ""} for f in enabled_filters(profile)}
    return {"dimensions": dims, "hard_filter_flags": flags}


def _mock_memo(parsed, scored, overall, tier, hfr) -> str:
    dims = scored.get("dimensions", {})
    line = " · ".join(f"{k} {int(v['score'])}" for k, v in dims.items())
    if hfr.get("disqualified"):
        return (f"## Recommendation: Disqualified (tripped {', '.join(hfr.get('tripped', []))})\n\n"
                "Knocked out by a hard filter. Nothing else scored.\n")
    soft = ""
    if hfr.get("soft"):
        soft = ("\n\n**Conditional (" + ", ".join(s["key"] for s in hfr["soft"]) +
                "):** resolvable blocker; tier capped at Watch until it clears.")
    return (f"## Recommendation: {tier} - Score {overall:.0f}/100\n\n"
            f"**Opportunity:** {parsed.get('title', 'Untitled')} · Funder: {parsed.get('funder', 'unknown')}\n\n"
            f"**Dimensions:** {line}{soft}\n\n"
            "**Read:** Mock-mode memo. Add ANTHROPIC_API_KEY for a real argument-driven memo.\n")


def _mock_bootstrap(org_name: str) -> Dict[str, Any]:
    from .starter_profile import STARTER_PROFILE
    return {"profile_doc": {"mission": f"REPLACE with {org_name}'s mission.",
                            "priorities": "REPLACE with priorities.",
                            "funding_preference": "REPLACE.", "values_guardrails": "REPLACE."},
            "dimensions": STARTER_PROFILE["dimensions"], "hard_filters": STARTER_PROFILE["hard_filters"],
            "thresholds": STARTER_PROFILE["thresholds"], "tiers": STARTER_PROFILE["tiers"],
            "rationale": "Mock mode: add ANTHROPIC_API_KEY to draft a real profile from your plan."}
