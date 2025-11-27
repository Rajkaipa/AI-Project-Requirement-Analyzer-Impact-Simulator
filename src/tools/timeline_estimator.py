# src/tools/timeline_estimator.py

from __future__ import annotations

from typing import List, Dict, Any


def estimate_timeline(
    estimation_tasks: List[Dict[str, Any]],
    team_size: int,
) -> Dict[str, Any]:
    """
    Quick deterministic timeline estimate.

    For simplicity we:
      - sum optimistic / likely / pessimistic durations
      - divide by sqrt(team_size) to give benefit of parallelism
    """
    if not estimation_tasks or team_size <= 0:
        return {
            "timeline_weeks": {
                "optimistic": 0.0,
                "likely": 0.0,
                "pessimistic": 0.0,
            },
            "confidence_80_percent": "0 - 0 weeks",
            "assumptions": [
                "No estimation tasks provided or invalid team size.",
            ],
        }

    opt = sum(float(t["optimistic_weeks"]) for t in estimation_tasks)
    likely = sum(float(t["likely_weeks"]) for t in estimation_tasks)
    pess = sum(float(t["pessimistic_weeks"]) for t in estimation_tasks)

    import math

    parallel_factor = max(1.0, math.sqrt(team_size))

    opt_adj = opt / parallel_factor
    likely_adj = likely / parallel_factor
    pess_adj = pess / parallel_factor

    return {
        "timeline_weeks": {
            "optimistic": round(opt_adj, 1),
            "likely": round(likely_adj, 1),
            "pessimistic": round(pess_adj, 1),
        },
        "confidence_80_percent": f"{round(opt_adj,1)} - {round(pess_adj,1)} weeks",
        "assumptions": [
            f"Team size: {team_size} developers",
            "Parallelism approximated using sqrt(team_size).",
            "Monte Carlo simulation provides the more accurate distribution; "
            "this is only a quick reference estimate.",
        ],
    }
