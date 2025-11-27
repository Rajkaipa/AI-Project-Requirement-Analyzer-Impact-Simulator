# src/tools/risk_scorer.py

from __future__ import annotations

from typing import List, Dict, Any


SEVERITY_WEIGHTS = {
    "low": 1,
    "medium": 2,
    "high": 3,
}


def compute_risk_score(raid_log: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    raid_log is expected to be a list of entries like:

    {
      "req_id": "REQ-001",
      "risks": [
        { "text": "...", "severity": "high" },
        ...
      ]
    }

    Returns:
        {
          "risk_score": float,
          "priority": "Low" | "Medium" | "High",
          "recommended_action": str,
          "probability_percent": int,
          "impact_level": str
        }
    """
    if not raid_log:
        return {
            "risk_score": 0.0,
            "priority": "Low",
            "recommended_action": "No major risks identified.",
            "probability_percent": 0,
            "impact_level": "Low",
        }

    total_weight = 0
    count = 0

    for entry in raid_log:
        for r in entry.get("risks", []):
            sev = str(r.get("severity", "")).lower()
            weight = SEVERITY_WEIGHTS.get(sev, 1)
            total_weight += weight
            count += 1

    if count == 0:
        avg = 0.0
    else:
        avg = total_weight / count  # between ~1 and 3

    if avg < 1.5:
        priority = "Low"
        action = "Monitor periodically."
        impact = "Low"
        prob = 20
    elif avg < 2.3:
        priority = "Medium"
        action = "Prepare mitigation plan."
        impact = "Medium"
        prob = 50
    else:
        priority = "High"
        action = "Immediate mitigation required."
        impact = "High"
        prob = 75

    return {
        "risk_score": round(avg, 2),
        "priority": priority,
        "recommended_action": action,
        "probability_percent": prob,
        "impact_level": impact,
    }
