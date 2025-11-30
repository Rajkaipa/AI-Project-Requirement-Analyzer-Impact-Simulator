from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google import genai

from src.agents.ingestion_agent import ingestion_agent
from src.agents.requirement_extractor_agent import requirement_extractor_agent
from src.agents.structuring_agent import structuring_agent
from src.agents.risk_estimator_agent import risk_estimator_agent
from src.agents.simulation_agent import simulation_agent
from src.agents.artifact_generator_agent import artifact_generator_agent
from src.agents.validation_agent import validation_agent
from src.tools.file_parsers import extract_text_from_files

# Load .env once
load_dotenv()


# -------------------------------------------------------------------
# Low-level helpers
# -------------------------------------------------------------------

def _get_genai_client() -> genai.Client:
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing GOOGLE_API_KEY (or GENAI_API_KEY) in environment. "
            "Set it before running the pipeline."
        )
    return genai.Client(api_key=api_key)


def _safe_json_loads(text: str) -> Dict[str, Any]:
    """Best-effort JSON parsing with fallback."""
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def _call_llm_with_instruction(
    instruction: str,
    user_payload: Dict[str, Any],
    expect_json: bool = True,
) -> Dict[str, Any]:
    """
    Call gemini-2.0-flash using a plain text prompt (no system role),
    optionally expecting JSON.

    IMPORTANT: we use `config=` (not `generation_config=`) to match
    the google-genai version in your environment.
    """
    client = _get_genai_client()

    prompt = (
        instruction.strip()
        + "\n\nHere is the input JSON you must process:\n```json\n"
        + json.dumps(user_payload, indent=2)
        + "\n```"
    )

    if expect_json:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt],
            config={
                "response_mime_type": "application/json",
                "temperature": 0.0,
            },
        )
        text = response.text or ""
        return _safe_json_loads(text)

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[prompt],
    )
    return {"raw": response.text or ""}


def _generate_risk_mitigation_plans(
    raid_log: List[Dict[str, Any]],
    team_size: int,
    deadline_weeks: float,
) -> List[Dict[str, Any]]:
    """
    Generate structured risk mitigation action plans from the RAID log.
    Soft-fails to [] on any error.
    """
    if not raid_log:
        return []

    mitigation_instruction = """
You are a senior project manager creating a Risk Mitigation Action Plan.

Given a RAID log for a software project, return JSON ONLY in this shape:

{
  "mitigation_plans": [
    {
      "risk_id": "RISK-1",
      "risk_summary": "short sentence describing the risk",
      "mitigation_actions": [
        "first concrete mitigation action",
        "second concrete mitigation action"
      ],
      "owner_role": "Tech Lead or PM or Security, etc.",
      "target_timeline": "Before sprint 2 / Within 2 weeks / etc.",
      "status": "planned / in_progress / blocked / done"
    }
  ]
}

Focus on the highest severity or most impactful risks first.
Keep actions practical and implementable by a typical product team.
"""

    payload = {
        "raid_log": raid_log,
        "team_size": team_size,
        "deadline_weeks": deadline_weeks,
    }

    try:
        data = _call_llm_with_instruction(
            mitigation_instruction,
            payload,
            expect_json=True,
        )
    except Exception:
        return []

    if not isinstance(data, dict):
        return []

    plans = data.get("mitigation_plans")
    if isinstance(plans, list):
        return plans

    if isinstance(data, list):
        return data

    return []


# -------------------------------------------------------------------
# Complexity + baseline helpers
# -------------------------------------------------------------------

def _infer_complexity(
    requirements: List[Dict[str, Any]],
    raid_log: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Heuristic complexity calculator used instead of the LLM for
    deterministic scoring.
    """
    req_count = len(requirements)

    deps_count = 0
    for entry in raid_log:
        deps = entry.get("dependencies") or []
        if isinstance(deps, list):
            deps_count += len(deps)

    text_blob = " ".join(r.get("text", "") for r in requirements).lower()

    def has_any(keywords: List[str]) -> bool:
        return any(k in text_blob for k in keywords)

    has_realtime = has_any(
        ["real-time", "realtime", "real time", "live", "gps", "stream"]
    )
    has_ai = has_any(["ai", "machine learning", "ml", "recommendation"])
    has_payments = has_any(["payment", "credit card", "stripe", "paypal", "billing"])

    base_score = min(req_count * 0.3, 4)
    dependency_score = min(deps_count * 0.5, 3)

    complexity_bonus = 0.0
    if has_realtime:
        complexity_bonus += 1.5
    if has_ai:
        complexity_bonus += 1.0
    if has_payments:
        complexity_bonus += 0.5

    total = min(base_score + dependency_score + complexity_bonus, 10.0)

    if total < 4:
        level = "Low"
    elif total < 7:
        level = "Medium"
    else:
        level = "High"

    return {
        "complexity_score": round(total, 1),
        "level": level,
        "drivers": {
            "requirements_count": req_count,
            "dependencies_count": deps_count,
            "has_realtime": has_realtime,
            "has_ai": has_ai,
            "has_payments": has_payments,
        },
    }


def _compute_baseline_timeline(
    deadline_weeks: float,
    complexity_block: Dict[str, Any],
    team_size: int,
) -> float:
    """
    Compute an **estimated** timeline in weeks.

    It now reacts to:
      - Target deadline
      - Complexity score (driven by requirements & RAID)
      - Team size (more developers → shorter estimate, fewer → longer)

    Heuristic (two factors multiplied):
      1) Complexity factor:
            score < 4   → 0.9x target (a bit faster)
            4–7         → 1.1x target (slightly longer)
            >= 7        → 1.3x target (significantly longer)
      2) Team factor (relative to a reference team of 3 devs):
            team_factor = 3 / team_size, clamped between 0.2 and 1.8

         So roughly:
            - team_size = 1  → ~1.8x longer
            - team_size = 3  → 1.0x
            - team_size = 5  → 0.6x
            - team_size = 10 → 0.3x
            - team_size = 15 → 0.2x
    """
    try:
        score = float(complexity_block.get("complexity_score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0

    # Complexity factor
    if score < 4:
        complexity_factor = 0.9
    elif score < 7:
        complexity_factor = 1.1
    else:
        complexity_factor = 1.3

    # Team size factor (reference team size = 3)
    ref_team = 3
    safe_team_size = max(int(team_size), 1)
    team_factor = ref_team / safe_team_size

    # Clamp to avoid extreme values, but still allow 5 / 10 / 15 to differ
    if team_factor < 0.2:
        team_factor = 0.2
    elif team_factor > 1.8:
        team_factor = 1.8

    estimated = float(deadline_weeks) * complexity_factor * team_factor
    return round(estimated, 1)


# -------------------------------------------------------------------
# Public pipeline entrypoint
# -------------------------------------------------------------------

def run_full_pipeline(
    raw_text_input: str,
    team_size: int = 3,
    deadline_weeks: float = 4.0,
    auto_approve: bool = True,
    uploaded_files: Optional[List[Any]] = None,
    file_paths: Optional[List[str]] = None,
    approved_requirements: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Orchestrates the full analysis pipeline in SYNC mode.

    auto_approve=True  -> full pipeline (risk, simulation, validation, artifact)
    auto_approve=False -> stop after requirement extraction/structuring
                          and return a bundle for manual approval.

    approved_requirements (optional) -> if provided, skip the extraction
    agent and use these human-edited requirements instead.
    """

    # ---------------------------------------------------------------
    # 0. Merge text from uploaded files (best-effort parsing)
    # ---------------------------------------------------------------
    uploaded_files_text = ""
    if uploaded_files:
        try:
            uploaded_files_text = extract_text_from_files(uploaded_files)
        except TypeError:
            uploaded_files_text = extract_text_from_files(uploaded_files)  # type: ignore

    if file_paths:
        # reserved for future – currently unused
        pass

    # Keep raw text and uploaded text separate for ingestion agent
    ingestion_input = {
        "raw_text": raw_text_input,
        "uploaded_files_text": uploaded_files_text,
        "team_size": team_size,
        "deadline_weeks": deadline_weeks,
    }

    # ---------------------------------------------------------------
    # 1. Ingestion / normalization
    # ---------------------------------------------------------------
    ingestion_raw = _call_llm_with_instruction(
        ingestion_agent.instruction,
        ingestion_input,
        expect_json=True,
    )
    normalized_brief = ingestion_raw or {}

    # ---------------------------------------------------------------
    # 2. Requirement extraction (or use human-edited requirements)
    # ---------------------------------------------------------------
    if approved_requirements:
        requirements: List[Dict[str, Any]] = approved_requirements
        metadata: Dict[str, Any] = {}
        extraction: Dict[str, Any] = {
            "requirements": requirements,
            "metadata": metadata,
            "source": "human_approved",
            "note": "Using human-edited requirements from UI; extraction agent skipped.",
        }
    else:
        extraction_input = {
            "normalized_brief": normalized_brief,
            "raw_text": raw_text_input,
        }

        extraction = _call_llm_with_instruction(
            requirement_extractor_agent.instruction,
            extraction_input,
            expect_json=True,
        )

        requirements: List[Dict[str, Any]] = extraction.get("requirements") or []
        metadata = extraction.get("metadata") or {}

    # ---------------------------------------------------------------
    # 3. Structuring (user stories + initial RAID skeleton)
    # ---------------------------------------------------------------
    structuring_input = {
        "requirements": requirements,
        "metadata": metadata,
    }

    structuring_output = _call_llm_with_instruction(
        structuring_agent.instruction,
        structuring_input,
        expect_json=True,
    )

    user_stories: List[Dict[str, Any]] = structuring_output.get("user_stories") or []
    raid_log: List[Dict[str, Any]] = structuring_output.get("raid_log") or []

    # ---------------------------------------------------------------
    # SHORT-CIRCUIT PATH: manual approval required
    # ---------------------------------------------------------------
    if not auto_approve:
        # Count requirement types for the dashboard
        functional = sum(
            1 for r in requirements if (r.get("type") == "functional")
        )
        non_functional = sum(
            1 for r in requirements if (r.get("type") == "non_functional")
        )
        constraints = sum(
            1 for r in requirements if (r.get("type") == "constraint")
        )

        summary = {
            "team_size": team_size,
            "deadline_weeks": deadline_weeks,
            # In manual mode we still just show the target as the initial estimate
            "baseline_timeline_weeks": deadline_weeks,
            "requirements": {
                "total": len(requirements),
                "functional": functional,
                "non_functional": non_functional,
                "constraints": constraints,
            },
            # No risks / complexity yet – those require PM approval
            "risks": {
                "total": 0,
                "high_severity": 0,
            },
            "complexity": {
                "score": 0.0,
                "level": "Pending approval",
            },
            "validation": {
                "iterations": 0,
                "final_quality_score": 0.0,
                "status": "manual_approval_required",
            },
        }

        return {
            "summary": summary,
            "normalized_project_brief": normalized_brief,
            "extraction": extraction,
            "structuring": structuring_output,
            "risk_analysis": {},
            "risk_mitigation_plans": [],
            "simulation": {},
            "validation_history": [],
            "final_report": {},
            "manual_approval_required": True,
        }

    # ----------------------------------------------------------------
    # From here on: FULL PIPELINE (auto_approve=True)
    # ----------------------------------------------------------------

    # 4. Risk / RAID enrichment
    risk_input = {
        "requirements": requirements,
        "user_stories": user_stories,
        "raid_log": raid_log,
        "team_size": team_size,
        "deadline_weeks": deadline_weeks,
    }

    risk_output = _call_llm_with_instruction(
        risk_estimator_agent.instruction,
        risk_input,
        expect_json=True,
    )

    raid_log = risk_output.get("raid_log") or raid_log

    # COMPLEXITY: use deterministic heuristic instead of LLM output
    complexity_block = _infer_complexity(requirements, raid_log)

    # Risk mitigation plans
    try:
        risk_mitigation_plans = _generate_risk_mitigation_plans(
            raid_log=raid_log,
            team_size=team_size,
            deadline_weeks=deadline_weeks,
        )
    except Exception:
        risk_mitigation_plans = []

    # 5. Simulation
    simulation_output: Dict[str, Any] = {
        "baseline_timeline_weeks": None,
        "complexity": complexity_block,
        "scenarios": [],
        "scenario_results": [],
    }

    simulation_input = {
        "requirements": requirements,
        "user_stories": user_stories,
        "raid_log": raid_log,
        "complexity": complexity_block,
        "team_size": team_size,
        "deadline_weeks": deadline_weeks,
    }

    simulation_output = _call_llm_with_instruction(
        simulation_agent.instruction,
        simulation_input,
        expect_json=True,
    ) or simulation_output

    # Stick with deterministic complexity (ignore any LLM override)
    sim_complexity = complexity_block
    simulation_output["complexity"] = sim_complexity

    # Compute estimated timeline from deadline + complexity + team size
    baseline_timeline_weeks = _compute_baseline_timeline(
        deadline_weeks=deadline_weeks,
        complexity_block=sim_complexity,
        team_size=team_size,
    )
    simulation_output["baseline_timeline_weeks"] = baseline_timeline_weeks

    # 6. Validation loop
    validation_history: List[Dict[str, Any]] = []
    final_validation_status = "not_run"
    final_quality_score = 0.0

    max_iterations = 3
    current_simulation = simulation_output

    for _ in range(max_iterations):
        validation_input = {
            "requirements": requirements,
            "raid_log": raid_log,
            "simulation": current_simulation,
            "team_size": team_size,
            "deadline_weeks": deadline_weeks,
        }

        validation_result = _call_llm_with_instruction(
            validation_agent.instruction,
            validation_input,
            expect_json=True,
        ) or {}

        validation_history.append(validation_result)

        approved = bool(validation_result.get("approved"))
        quality_score = float(validation_result.get("quality_score", 0.0))
        final_quality_score = quality_score

        if approved:
            final_validation_status = (
                "fully_approved" if quality_score >= 8.0 else "conditional"
            )
            break

        if quality_score >= 6.0:
            final_validation_status = "conditional"
            break

        refinement_input = {
            "requirements": requirements,
            "raid_log": raid_log,
            "previous_simulation": current_simulation,
            "validation_feedback": validation_result,
            "team_size": team_size,
            "deadline_weeks": deadline_weeks,
        }

        current_simulation = _call_llm_with_instruction(
            simulation_agent.instruction,
            refinement_input,
            expect_json=True,
        ) or current_simulation

    else:
        if final_quality_score >= 6.0:
            final_validation_status = "conditional"
        elif validation_history:
            final_validation_status = "not_approved_max_iterations"
        else:
            final_validation_status = "not_run"

    simulation_output = current_simulation

    # 7. Artifact / PM-ready report
    artifact_input = {
        "requirements": requirements,
        "user_stories": user_stories,
        "raid_log": raid_log,
        "simulation": simulation_output,
        "normalized_brief": normalized_brief,
        "team_size": team_size,
        "deadline_weeks": deadline_weeks,
        "risk_mitigation_plans": risk_mitigation_plans,
        "validation": {
            "status": final_validation_status,
            "iterations": len(validation_history),
            "final_quality_score": final_quality_score,
        },
    }

    artifact_output = _call_llm_with_instruction(
        artifact_generator_agent.instruction,
        artifact_input,
        expect_json=True,
    )

    final_report = artifact_output.get("final_report") or artifact_output

    # 8. Build summary for the dashboard
    functional = sum(
        1 for r in requirements if (r.get("type") == "functional")
    )
    non_functional = sum(
        1 for r in requirements if (r.get("type") == "non_functional")
    )
    constraints = sum(
        1 for r in requirements if (r.get("type") == "constraint")
    )

    total_risks = 0
    high_severity_risks = 0
    for entry in raid_log:
        for risk in entry.get("risks") or []:
            total_risks += 1
            sev = str(risk.get("severity", "")).lower()
            if sev in {"high", "critical"}:
                high_severity_risks += 1

    complexity_score = float(sim_complexity.get("complexity_score") or 0.0)
    complexity_level = sim_complexity.get("level") or "Unknown"

    summary = {
        "team_size": team_size,
        "deadline_weeks": deadline_weeks,
        "baseline_timeline_weeks": baseline_timeline_weeks,
        "requirements": {
            "total": len(requirements),
            "functional": functional,
            "non_functional": non_functional,
            "constraints": constraints,
        },
        "risks": {
            "total": total_risks,
            "high_severity": high_severity_risks,
        },
        "complexity": {
            "score": complexity_score,
            "level": complexity_level,
        },
        "validation": {
            "iterations": len(validation_history),
            "final_quality_score": final_quality_score,
            "status": final_validation_status,
        },
    }

    return {
        "summary": summary,
        "normalized_project_brief": normalized_brief,
        "extraction": extraction,
        "structuring": structuring_output,
        "risk_analysis": risk_output,
        "risk_mitigation_plans": risk_mitigation_plans,
        "simulation": simulation_output,
        "validation_history": validation_history,
        "final_report": final_report,
        "manual_approval_required": False,
    }
