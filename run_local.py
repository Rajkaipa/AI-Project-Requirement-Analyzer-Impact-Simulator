# run_local.py

import asyncio
from typing import List, Dict, Any

from src.main_agent import run_full_pipeline


def example_estimation_tasks() -> List[Dict[str, Any]]:
    """
    Example tasks for Monte Carlo / timeline.
    Replace with dynamic extraction later if needed.
    """
    return [
        {
            "name": "Project Tracking Dashboard (REQ-001, REQ-002)",
            "optimistic_weeks": 1.0,
            "likely_weeks": 2.0,
            "pessimistic_weeks": 3.0,
        },
        {
            "name": "Role-Based Access Control (REQ-003)",
            "optimistic_weeks": 1.0,
            "likely_weeks": 2.0,
            "pessimistic_weeks": 3.0,
        },
        {
            "name": "Email Notifications (REQ-004)",
            "optimistic_weeks": 0.5,
            "likely_weeks": 1.0,
            "pessimistic_weeks": 1.5,
        },
        {
            "name": "Jira Integration (REQ-005)",
            "optimistic_weeks": 2.0,
            "likely_weeks": 3.0,
            "pessimistic_weeks": 5.0,
        },
    ]


async def main() -> None:
    print("=== Project Risk & Timeline Simulator (Local Run) ===")
    print("Paste your raw project text (emails, notes, etc.).")
    print("Finish with an empty line.\n")

    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)

    raw_text = "\n".join(lines)

    result = await run_full_pipeline(
        raw_text_input=raw_text,
        file_paths=[],  # manually add local file paths here if running locally
        estimation_tasks=example_estimation_tasks(),
        team_size=3,
        deadline_weeks=4.0,
        auto_approve=True,  # set False to enable human-in-the-loop pause
    )

    import json

    print("\n=== FINAL REPORT (JSON) ===")
    print(json.dumps(result.get("final_report", result), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
