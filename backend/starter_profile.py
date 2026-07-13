"""Neutral starter profile for the template.

This is a deliberately generic placeholder so the app runs on first boot. It is
NOT a good scoring profile for any specific organization. Replace it via the
Setup screen (bootstrap from your strategic plan) or edit it in Admin.

See PROFILE_GUIDE.md for how and why to define a sharp profile.
"""
from __future__ import annotations

STARTER_PROFILE = {
    "version": 1,
    "name": "Starter profile (PLACEHOLDER - replace me)",
    "is_placeholder": True,
    "profile_doc": {
        "mission": "REPLACE: one or two sentences on your organization's mission and who you serve.",
        "priorities": "REPLACE: your current strategic priorities, programs, and geographies.",
        "funding_preference": "REPLACE: what kind of funding you prefer (e.g. unrestricted over restricted).",
        "values_guardrails": "REPLACE: any terms or conditions you will not accept.",
    },
    # Data-driven scoring dimensions. Weights must sum to 100. Rename, add, or
    # drop these to match how YOUR organization judges fit.
    "dimensions": [
        {"key": "mission", "label": "Mission fit", "weight": 25,
         "description": "How directly the funded work advances your core mission and the people you serve."},
        {"key": "program", "label": "Program & approach fit", "weight": 20,
         "description": "Alignment with your programs, methods, and technical approach."},
        {"key": "geography", "label": "Geographic fit", "weight": 15,
         "description": "Alignment with the places you work or prioritize."},
        {"key": "funding", "label": "Funding characteristics", "weight": 15,
         "description": "Size versus your thresholds, restricted versus unrestricted, duration, flexibility."},
        {"key": "funder", "label": "Funder fit & win likelihood", "weight": 15,
         "description": "The funder's track record with organizations like yours and a realistic probability."},
        {"key": "effort", "label": "Effort & feasibility", "weight": 10,
         "description": "Deadline runway, proposal burden, reporting and compliance load, capacity."},
    ],
    # Data-driven knockouts. mode 'hard' zeroes the score and disqualifies;
    # mode 'soft' caps the tier at Watch and flags a resolvable blocker.
    "hard_filters": [
        {"key": "ineligible_org_type", "label": "Ineligible organization type", "enabled": True, "mode": "soft",
         "description": "Eligibility rules exclude an organization like yours. Soft because it is often "
                        "resolvable through a partner, co-applicant, or fiscal sponsor."},
        {"key": "out_of_mission", "label": "Out of mission", "enabled": True, "mode": "hard",
         "description": "The funded work is definitively outside your mission."},
        {"key": "values_conflict", "label": "Values conflict", "enabled": True, "mode": "hard",
         "description": "Terms conflict with a requirement your organization will not compromise on."},
        {"key": "prohibited_geography", "label": "Prohibited geography", "enabled": True, "mode": "hard",
         "description": "Requires operating in a place your organization will not work."},
    ],
    "thresholds": {
        "currency": "USD",
        "grant_floor": 0,          # 0 = no floor until you set one
        "strategic_tier": 0,       # 0 = no strategic tier until you set one
        "restricted_penalty": "moderate",   # mild | moderate | strong
        "small_and_fully_restricted_knockout": False,
    },
    "tiers": {"pursue": 80, "pursue_review": 60, "watch": 40},
}
