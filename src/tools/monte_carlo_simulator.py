# src/tools/monte_carlo_simulator.py

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Sequence


@dataclass
class EstimationTask:
    """Represents a single work-stream or feature estimation."""
    name: str
    optimistic_weeks: float
    likely_weeks: float
    pessimistic_weeks: float


def _sample_task_duration(task: EstimationTask) -> float:
    """
    Sample a duration using a simple PERT / triangular distribution.
    This is not hyper-accurate, but good enough for a PM-style Monte Carlo.
    """
    low = task.optimistic_weeks
    high = task.pessimistic_weeks
    mode = task.likely_weeks

    # Triangular distribution
    return random.triangular(low, high, mode)


def run_monte_carlo(
    tasks: Sequence[EstimationTask],
    iterations: int = 2000,
    buffer_multiplier: float = 1.1,
) -> Dict[str, object]:
    """
    Run a Monte Carlo simulation over the supplied tasks.

    Args:
        tasks: list of EstimationTask objects.
        iterations: number of simulation runs.
        buffer_multiplier:
            Safety factor to apply to the median estimate to get the
            baseline timeline (e.g., 1.1 → +10% buffer).

    Returns:
        {
          "baseline_timeline_weeks": float,
          "p10_weeks": float,
          "p50_weeks": float,
          "p90_weeks": float,
          "raw_samples": [float, ...]   # optional, can be large
        }
    """
    if not tasks:
        return {
            "baseline_timeline_weeks": 0.0,
            "p10_weeks": 0.0,
            "p50_weeks": 0.0,
            "p90_weeks": 0.0,
            "raw_samples": [],
        }

    samples: List[float] = []

    for _ in range(iterations):
        total = 0.0
        for task in tasks:
            total += _sample_task_duration(task)
        samples.append(total)

    samples.sort()
    n = len(samples)

    def percentile(p: float) -> float:
        if n == 0:
            return 0.0
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return samples[int(k)]
        d0 = samples[f] * (c - k)
        d1 = samples[c] * (k - f)
        return float(d0 + d1)

    p10 = percentile(0.10)
    p50 = percentile(0.50)
    p90 = percentile(0.90)

    baseline = float(round(p50 * buffer_multiplier, 1))

    return {
        "baseline_timeline_weeks": baseline,
        "p10_weeks": round(p10, 1),
        "p50_weeks": round(p50, 1),
        "p90_weeks": round(p90, 1),
        "raw_samples": samples,
    }
