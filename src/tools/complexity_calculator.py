# src/tools/complexity_calculator.py

from typing import Dict


def _compute_complexity_score(
    requirements_count: int,
    dependencies_count: int,
    has_realtime: bool,
    has_ai: bool,
    has_payments: bool,
) -> float:
    """
    Internal helper that mirrors the scoring model described in the
    risk_estimator_agent instructions.
    """
    base_score = min(requirements_count * 0.3, 4.0)
    dependency_score = min(dependencies_count * 0.5, 3.0)

    bonus = 0.0
    if has_realtime:
        bonus += 1.5
    if has_ai:
        bonus += 1.0
    if has_payments:
        bonus += 0.5

    total = base_score + dependency_score + bonus
    return float(round(min(total, 10.0), 1))


def calculate_complexity(
    requirements_count: int,
    dependencies_count: int,
    has_realtime: bool,
    has_ai: bool,
    has_payments: bool,
) -> Dict[str, object]:
    """
    Main function to be used by the pipeline.

    Returns a dict of the form:
    {
        "complexity_score": 7.5,
        "level": "High"
    }
    """
    score = _compute_complexity_score(
        requirements_count=requirements_count,
        dependencies_count=dependencies_count,
        has_realtime=has_realtime,
        has_ai=has_ai,
        has_payments=has_payments,
    )

    if score < 4.0:
        level = "Low"
    elif score < 7.0:
        level = "Medium"
    else:
        level = "High"

    return {
        "complexity_score": score,
        "level": level,
    }


# Backwards-compatible alias in case other code imports this name.
def complexity_calculator(
    requirements_count: int,
    dependencies_count: int,
    has_realtime: bool,
    has_ai: bool,
    has_payments: bool,
) -> Dict[str, object]:
    """
    Alias wrapper around calculate_complexity() for compatibility.
    """
    return calculate_complexity(
        requirements_count=requirements_count,
        dependencies_count=dependencies_count,
        has_realtime=has_realtime,
        has_ai=has_ai,
        has_payments=has_payments,
    )
