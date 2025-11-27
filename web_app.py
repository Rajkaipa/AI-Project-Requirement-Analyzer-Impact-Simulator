# web_app.py

import json
from typing import Any, Dict, List

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from src.main_agent import run_full_pipeline


# -------------------------------------------------------------------
# Small helpers
# -------------------------------------------------------------------

def _extract_counts_from_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    req = summary.get("requirements") or {}
    risks = summary.get("risks") or {}
    complexity = summary.get("complexity") or {}
    validation = summary.get("validation") or {}

    return {
        "total_requirements": req.get("total", 0),
        "functional": req.get("functional", 0),
        "non_functional": req.get("non_functional", 0),
        "constraints": req.get("constraints", 0),
        "total_risks": risks.get("total", 0),
        "high_risks": risks.get("high_severity", 0),
        "complexity_score": complexity.get("score", 0.0),
        "complexity_level": complexity.get("level", "Unknown"),
        "validation_iterations": validation.get("iterations", 0),
        "validation_score": validation.get("final_quality_score", 0.0),
        "validation_status": validation.get("status", "not_run"),
    }


def _timeline_points(
    baseline_weeks: float,
    scenario_results: List[Dict[str, Any]],
) -> Dict[str, List[Any]]:
    labels = ["Baseline"]
    values = [baseline_weeks]

    for s in scenario_results:
        name = s.get("scenario", "scenario")
        impact_str = str(s.get("timeline_impact", "0%")).strip()
        try:
            number = float(impact_str.replace("%", "").replace("+", "").strip())
        except Exception:
            continue
        factor = 1.0 + (number / 100.0)
        labels.append(name)
        values.append(round(baseline_weeks * factor, 2))

    return {"labels": labels, "values": values}


# -------------------------------------------------------------------
# Streamlit UI
# -------------------------------------------------------------------

st.set_page_config(
    page_title="AI Project Requirement Analyzer & Impact Simulator",
    layout="wide",
)

# Session-level store for human-edited requirements
if "approved_requirements" not in st.session_state:
    st.session_state["approved_requirements"] = None

# Session-level store for last pipeline result
if "pipeline_result" not in st.session_state:
    st.session_state["pipeline_result"] = None

# Global CSS tweaks
st.markdown(
    """
    <style>

    /* ----------------------------------------------------
       GLOBAL TEXT (1.5× larger)
       ---------------------------------------------------- */
    html, body, [data-testid="stAppViewContainer"] * {
        font-size: 1.4rem !important;     /* core text */
    }

    /* ----------------------------------------------------
       METRIC NUMBERS (Team size = 3)
       ---------------------------------------------------- */
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
        font-size: 2.4rem !important;     /* bigger but not huge */
        font-weight: 800 !important;
        line-height: 1.1;
    }

    /* ----------------------------------------------------
       METRIC LABELS (Team size, Baseline timeline)
       ---------------------------------------------------- */
    div[data-testid="metric-container"] p,
    div[data-testid="metric-container"] label {
        font-size: 1.3rem !important;
        font-weight: 600 !important;
    }

    /* ----------------------------------------------------
       TAB LABELS (Executive Summary, Risk Analysis, etc.)
       ---------------------------------------------------- */
    button[data-baseweb="tab"] > div {
        font-size: 1.45rem !important;
        font-weight: 700 !important;
        padding-top: 0.4rem !important;
        padding-bottom: 0.4rem !important;
    }

    /* ----------------------------------------------------
       SECTION HEADERS (H1, H2, H3)
       ---------------------------------------------------- */
    h1, h2, h3, h4 {
        font-size: 1.9rem !important;
        font-weight: 800 !important;
        margin-top: 0.5rem !important;
        margin-bottom: 0.5rem !important;
    }

    /* ----------------------------------------------------
       JSON text & expander content
       ---------------------------------------------------- */
    .stJson, .stExpander {
        font-size: 1.3rem !important;
    }

    </style>
    """,
    unsafe_allow_html=True,
)



# Header
st.markdown(
    """
    <div style="display:flex; align-items:center; gap:0.75rem; margin-bottom: 0.5rem;">
      <div style="
          width:44px; height:44px; border-radius:14px;
          background:linear-gradient(135deg,#4f46e5,#06b6d4);
          display:flex; align-items:center; justify-content:center;
          color:white; font-size:1.5rem; font-weight:700;
      ">
        AI
      </div>
      <div>
        <div style="font-size:0.8rem; text-transform:uppercase; letter-spacing:0.14em; color:#6b7280; font-weight:600;">
          Project Intelligence Studio
        </div>
        <div style="font-size:1.5rem; font-weight:800; color:#111827;">
          Requirement Analyzer &amp; Impact Simulator
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.caption(
    "Ingest messy inputs → extract & structure requirements → run risk & timeline simulations → "
    "generate a PM-ready recommendation report."
)

# Sidebar
with st.sidebar:
    st.header("⚙️ Project Parameters")
    team_size = st.number_input("Team size (developers)", min_value=1, max_value=50, value=3, step=1)
    deadline_weeks = st.number_input("Target deadline (weeks)", min_value=1.0, max_value=52.0, value=4.0, step=0.5)

    st.markdown("---")
    st.subheader("📎 Upload Raw Requirement Files")
    uploaded_files = st.file_uploader(
        "Upload requirements docs, logs, screenshots, whiteboard photos, etc. (best-effort parsing)",
        type=["txt", "md", "json", "log", "pdf", "docx", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
    )
    if uploaded_files:
        st.info(
            "Uploaded files are parsed on a best-effort basis. Extracted text is merged with the "
            "raw project input before analysis."
        )
    else:
        st.caption("You can still run the pipeline with just pasted text below.")

    st.markdown("---")
    auto_approve = st.checkbox(
        "Skip manual approval and run full simulation automatically",
        value=True,
    )

st.markdown("### 1. Paste raw project inputs")

raw_text = st.text_area(
    "Raw project text (emails, meeting notes, chat logs, etc.)",
    height=160,
    placeholder="",
)

run_clicked = st.button("🚀 Run Analysis & Simulation", type="primary")

# -------------------------------------------------
# Use last result from session_state by default
# -------------------------------------------------
result: Dict[str, Any] = st.session_state.get("pipeline_result") or {}

if run_clicked:
    if not raw_text.strip() and not uploaded_files:
        st.error(
            "Please paste some project input text or upload at least one file before running the analysis."
        )
    else:
        with st.spinner("Running multi-agent pipeline with Gemini 2.0 Flash..."):
            try:
                # Only use previously approved requirements when auto-approval is ON
                approved_requirements = (
                    st.session_state.get("approved_requirements")
                    if auto_approve
                    else None
                )

                result = run_full_pipeline(
                    raw_text_input=raw_text,
                    team_size=team_size,
                    deadline_weeks=float(deadline_weeks),
                    auto_approve=auto_approve,
                    uploaded_files=uploaded_files,
                    approved_requirements=approved_requirements,
                )
                st.session_state["pipeline_result"] = result
                st.success("Pipeline completed!")
            except Exception as e:
                st.error(f"Pipeline failed: {e}")

# Show content only if we have a result
if result:
    summary = result.get("summary") or {}
    manual_mode = result.get("manual_approval_required", False)
    counts = _extract_counts_from_summary(summary)

    baseline_weeks = float(summary.get("baseline_timeline_weeks") or deadline_weeks)
    simulation = result.get("simulation") or {}
    scenario_results = simulation.get("scenario_results") or []

    # Tabs
    (
        tab_exec,
        tab_requirements,
        tab_structured,
        tab_risk,
        tab_mitigation,
        tab_simulation,
        tab_validation,
        tab_final_json,
    ) = st.tabs(
        [
            "Executive Summary",
            "Extracted Requirements",
            "Structured Backlog & RAID",
            "Risk Analysis",
            "Risk Mitigation Plan",
            "Simulation",
            "Validation Loop",
            "Final Report (JSON)",
        ]
    )

    # ---------------- Executive Summary ----------------
    with tab_exec:
        st.subheader("Executive Summary (Management View)")

        if manual_mode:
            st.warning(
                "Manual approval mode is **ON**. Only ingestion & requirement extraction have been run.\n\n"
                "👉 Review and **edit** the **Extracted Requirements** tab. When you're happy, enable "
                "“Skip manual approval and run full simulation automatically” in the sidebar and run again "
                "to generate risk analysis, complexity scoring, and simulations."
            )

        # Metric cards
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Team size", f"{summary.get('team_size', team_size)}")
        m2.metric("Target deadline (weeks)", f"{summary.get('deadline_weeks', deadline_weeks):.1f}")
        m3.metric("Baseline timeline (weeks)", f"{summary.get('baseline_timeline_weeks', baseline_weeks):.1f}")

        if manual_mode:
            m4.metric("Complexity score (0-10)", "—", "Manual review pending")
        else:
            m4.metric(
                "Complexity score (0-10)",
                f"{counts['complexity_score']:.1f}",
                counts["complexity_level"],
            )

        st.markdown("---")

        # Layout: charts
        c_left, c_middle, c_right = st.columns((1.2, 1.0, 1.2))

        # Requirements Overview (same in both modes)
        with c_left:
            st.markdown("#### Requirements Overview")
            st.markdown(
                f"""
                <div style="font-size:1.25rem;font-weight:700;margin-bottom:0.3rem;">
                    Total requirements:
                    <span style="
                        color:#111827;
                        font-size:2.0rem;
                        font-weight:900;
                        margin-left:0.3rem;
                    ">
                        {counts['total_requirements']}
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            req_labels = []
            req_values = []
            if counts["functional"]:
                req_labels.append("Functional")
                req_values.append(counts["functional"])
            if counts["non_functional"]:
                req_labels.append("Non-functional")
                req_values.append(counts["non_functional"])
            if counts["constraints"]:
                req_labels.append("Constraints")
                req_values.append(counts["constraints"])

            # Heading for the breakdown
            st.markdown("#### Requirements Breakdown")

            if req_values:
                # Simple vertical legend rendered with Streamlit
                legend_lines = []
                if counts["functional"]:
                    legend_lines.append("🟦 Functional")
                if counts["non_functional"]:
                    legend_lines.append("🟦 Non-functional")
                if counts["constraints"]:
                    legend_lines.append("🟥 Constraints")

                if legend_lines:
                    st.markdown(
                        "<div style='font-size:0.85rem; line-height:1.3; "
                        "margin-bottom:0.4rem;'>"
                        + "<br>".join(legend_lines) +
                        "</div>",
                        unsafe_allow_html=True,
                    )

                # Pie chart without internal legend (just the slices + %)
                fig_pie = px.pie(
                    values=req_values,
                    names=req_labels,
                    title="",  # title handled by Streamlit heading above
                )
                fig_pie.update_layout(
                    showlegend=False,
                    margin=dict(l=10, r=10, t=10, b=10),
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("No requirements extracted yet (0 functional / 0 non-functional / 0 constraints).")

        # Complexity Gauge
        with c_middle:
            st.markdown("#### Complexity Gauge")
            if manual_mode:
                st.info("Run again with auto-approval enabled to estimate complexity.")
            else:
                comp_score = counts["complexity_score"]
                gauge_fig = go.Figure(
                    go.Indicator(
                        mode="gauge+number",
                        value=comp_score,
                        title={"text": "Complexity (0-10)", "font": {"size": 18}},
                        gauge={
                            "axis": {"range": [0, 10]},
                            "steps": [
                                {"range": [0, 4], "color": "#bbf7d0"},
                                {"range": [4, 7], "color": "#facc15"},
                                {"range": [7, 10], "color": "#fecaca"},
                            ],
                        },
                    )
                )
                gauge_fig.update_layout(margin=dict(l=20, r=20, t=50, b=10))
                st.plotly_chart(gauge_fig, use_container_width=True)

        # Risk Overview
        with c_right:
            st.markdown("#### Risk Overview")
            if manual_mode:
                st.info("Risk analysis will be available after you approve requirements and re-run in auto mode.")
            else:
                raid_log = (result.get("risk_analysis") or {}).get("raid_log") or []
                sev_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
                for entry in raid_log:
                    for risk in entry.get("risks") or []:
                        sev = str(risk.get("severity", "")).lower()
                        if sev in sev_counts:
                            sev_counts[sev] += 1

                if any(sev_counts.values()):
                    fig_bar = px.bar(
                        x=list(sev_counts.keys()),
                        y=list(sev_counts.values()),
                        title="Risks by Severity",
                        labels={"x": "Severity", "y": "Count"},
                    )
                    fig_bar.update_layout(
                        title_font_size=18,
                        xaxis_title_font_size=12,
                        yaxis_title_font_size=12,
                        xaxis_tickfont_size=11,
                        yaxis_tickfont_size=11,
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
                else:
                    st.info("No risks recorded yet.")

        st.markdown("---")

        # Timeline & validation
        if manual_mode:
            st.info(
                "Timeline impact scenarios and validation metrics will appear after you turn on "
                "auto-approval and re-run the analysis."
            )
        else:
            st.markdown("#### Timeline Impact Scenarios")
            tp = _timeline_points(baseline_weeks, scenario_results)
            if tp["labels"]:
                fig_timeline = px.bar(
                    x=tp["labels"],
                    y=tp["values"],
                    title="Baseline vs Scenario Timelines (weeks)",
                    labels={"x": "Scenario", "y": "Estimated duration (weeks)"},
                )
                fig_timeline.update_layout(
                    title_font_size=18,
                    xaxis_title_font_size=12,
                    yaxis_title_font_size=12,
                    xaxis_tickfont_size=11,
                    yaxis_tickfont_size=11,
                )
                st.plotly_chart(fig_timeline, use_container_width=True)
            else:
                st.info("No simulation scenarios available yet.")

            st.markdown("---")

            st.markdown("#### Validation Loop Metrics")
            v1, v2, v3 = st.columns(3)
            v1.metric("Iterations", f"{counts['validation_iterations']}")
            v2.metric("Final Quality Score", f"{counts['validation_score']:.1f}/10")
            status_label = counts["validation_status"]
            if status_label.startswith("full"):
                status_text = "✅ Fully Approved"
            elif status_label.startswith("conditional"):
                status_text = "⚠️ Conditionally Approved"
            elif status_label.startswith("not_approved"):
                status_text = "⚠️ Max Iterations / Not Approved"
            elif status_label == "not_run":
                status_text = "⏸️ Not Run"
            else:
                status_text = status_label
            v3.metric("Status", status_text)

            st.markdown("#### Overall Recommendation (from Artifact Agent)")
            st.json(result.get("final_report") or {})

        st.markdown("#### Normalized Project Brief (for debugging)")
        st.json(result.get("normalized_project_brief") or {})

    # ---------------- Extracted Requirements (now editable in manual mode) ----------------
    with tab_requirements:
        st.subheader("3. Extracted Requirements & User Stories")

        extraction = result.get("extraction") or {}
        requirements_list = extraction.get("requirements") or []

        # Ensure it's a list of dicts for data_editor
        if not isinstance(requirements_list, list):
            requirements_list = []
        else:
            tmp = []
            for r in requirements_list:
                if isinstance(r, dict):
                    tmp.append(r)
            requirements_list = tmp

        # Helper to generate next REQ id
        def generate_next_id(reqs: List[Dict[str, Any]]) -> str:
            numbers = []
            for r in reqs:
                rid = r.get("id")
                if not rid:
                    continue
                if isinstance(rid, str) and rid.startswith("REQ-"):
                    try:
                        num = int(rid.replace("REQ-", ""))
                        numbers.append(num)
                    except ValueError:
                        continue
            next_num = max(numbers) + 1 if numbers else 1
            return f"REQ-{next_num:03d}"

        if manual_mode:
            st.markdown(
                """
                **Manual approval mode is active.**

                - Review and edit the extracted requirements below  
                - You can add new rows or delete existing ones  
                - Click **Save edited requirements for next run**  
                - Then toggle **Skip manual approval and run full simulation automatically** and run again
                """
            )

            # Editable table with dropdowns
            edited_requirements = st.data_editor(
                requirements_list,
                num_rows="dynamic",
                use_container_width=True,
                key="requirements_editor",
                column_config={
                    "id": st.column_config.TextColumn(
                        "ID",
                        help="Requirement identifier (auto-assigned if empty)",
                    ),
                    "text": st.column_config.TextColumn(
                        "Text",
                        help="Requirement description",
                    ),
                    "type": st.column_config.SelectboxColumn(
                        "Type",
                        options=["functional", "non_functional", "constraint"],
                        help="Requirement type",
                    ),
                    "priority": st.column_config.SelectboxColumn(
                        "Priority",
                        options=["low", "medium", "high", "critical"],
                        help="Priority / impact level",
                    ),
                },
            )

            col_save, col_clear = st.columns(2)

            with col_save:
                if st.button("💾 Save edited requirements for next run", key="save_reqs"):
                    cleaned_reqs: List[Dict[str, Any]] = []

                    # Start ID counter from existing requirements
                    next_id_value = generate_next_id(edited_requirements)

                    # Extract numeric part once
                    try:
                        current_num = int(next_id_value.replace("REQ-", ""))
                    except ValueError:
                        current_num = 1

                    for r in edited_requirements:
                        if not isinstance(r, dict):
                            continue
                        rc = dict(r)

                        # Skip completely empty rows (no text and no id)
                        if not (rc.get("id") or rc.get("text")):
                            continue

                        if not rc.get("id") or str(rc.get("id")).lower() == "none":
                            rc["id"] = f"REQ-{current_num:03d}"
                            current_num += 1

                        rc["text"] = rc.get("text") or ""
                        rc["type"] = rc.get("type") or "functional"
                        rc["priority"] = rc.get("priority") or "medium"

                        cleaned_reqs.append(rc)

                    st.session_state["approved_requirements"] = cleaned_reqs
                    st.success(
                        "Edited requirements saved. Turn on auto-approval in the sidebar and run the pipeline again."
                    )

            with col_clear:
                if st.button("🧹 Clear saved edits", key="clear_reqs"):
                    st.session_state["approved_requirements"] = None
                    st.info("Cleared saved edited requirements. The next run will use fresh LLM extraction.")

            st.markdown("---")
            with st.expander("Raw extraction JSON (read-only)", expanded=False):
                st.json(extraction or {})
        else:
            if st.session_state.get("approved_requirements"):
                st.info(
                    "This run used **human-edited requirements** saved from manual approval mode."
                )

            st.markdown("**Requirements & user stories (read-only)**")
            st.json(extraction or {})

    # ---------------- Other tabs ----------------
    with tab_structured:
        st.subheader("4. Structured Backlog & RAID Log (Raw JSON)")
        st.json(result.get("structuring") or {})

    with tab_risk:
        st.subheader("5. Risk Analysis (RAID + Complexity)")
        if manual_mode:
            st.info("Risk analysis is not available in manual-approval mode. Re-run with auto-approval enabled.")
        else:
            st.json(result.get("risk_analysis") or {})

    with tab_mitigation:
        st.subheader("6. Risk Mitigation Action Plans")
        if manual_mode:
            st.info("Mitigation plans are generated only in auto-approval mode after risk analysis.")
        else:
            mitigation_plans = result.get("risk_mitigation_plans") or (
                (result.get("risk_analysis") or {}).get("mitigation_plans") or []
            )
            if not mitigation_plans:
                st.info(
                    "No structured mitigation plan was returned. "
                    "You can still review the RAID log in the Risk Analysis tab."
                )
            else:
                for idx, plan in enumerate(mitigation_plans, start=1):
                    title = plan.get("risk_summary") or plan.get("risk_id") or f"Risk {idx}"
                    owner = plan.get("owner_role", "Owner not specified")
                    status = plan.get("status", "status unknown")
                    timeline = plan.get("target_timeline", "timeline not specified")
                    actions = plan.get("mitigation_actions") or []

                    with st.expander(f"{idx}. {title}"):
                        st.markdown(f"**Owner:** {owner}")
                        st.markdown(f"**Target timeline:** {timeline}")
                        st.markdown(f"**Status:** {status}")
                        if actions:
                            st.markdown("**Mitigation actions:**")
                            for action in actions:
                                st.markdown(f"- {action}")

    with tab_simulation:
        st.subheader("7. Simulation Results")
        if manual_mode:
            st.info("Simulation results appear only after you run with auto-approval enabled.")
        else:
            st.json(result.get("simulation") or {})

    with tab_validation:
        st.subheader("8. Validation History")
        if manual_mode:
            st.info("Validation loop runs only in auto-approval mode.")
        else:
            history = result.get("validation_history") or []
            if not history:
                st.info("Validation loop did not run or returned no history.")
            else:
                for i, item in enumerate(history, start=1):
                    with st.expander(
                        f"Iteration {i} – Score: {item.get('quality_score','?')}/10 – Approved: {item.get('approved')}"
                    ):
                        st.json(item)

    with tab_final_json:
        st.subheader("9. Final Impact & Recommendation Report (Full JSON)")
        if manual_mode:
            st.info("Final report is generated after risk & simulation in auto-approval mode.")
        else:
            st.json(result.get("final_report") or {})
