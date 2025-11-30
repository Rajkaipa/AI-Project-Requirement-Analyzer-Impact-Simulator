# web_app.py

import json
from typing import Any, Dict, List
from collections import defaultdict

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# Ensure this import path is correct for your project
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
    baseline_label: str = "Estimated timeline",
) -> Dict[str, List[Any]]:
    """Build bar labels/values for baseline + scenarios."""
    labels = [baseline_label]
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


def _recompute_timeline_for_team(
    baseline_weeks: float,
    original_team_size: int,
    new_team_size: int,
) -> float:
    """Deterministic what-if timeline recompute based purely on team size ratio."""
    if new_team_size <= 0 or original_team_size <= 0:
        return float(baseline_weeks)
    return round(float(baseline_weeks) * float(original_team_size) / float(new_team_size), 2)


def _build_risk_heatmap_matrix(raid_log: List[Dict[str, Any]]):
    """
    Build a Likelihood × Impact heat map matrix from the RAID log.

    If 'likelihood'/'impact' are missing for a risk, we heuristically
    derive them from 'severity':
      - low      -> likelihood=Low,       impact=Low
      - medium   -> likelihood=Medium,    impact=Medium
      - high     -> likelihood=High,      impact=High
      - critical -> likelihood=Very High, impact=Very High

    Returns:
        likelihood_labels, impact_labels, matrix, cell_to_risks
        or (None, None, None, {}) if no data.
    """
    likelihood_labels = ["Low", "Medium", "High", "Very High"]
    impact_labels = ["Low", "Medium", "High", "Very High"]
    size = len(likelihood_labels)

    matrix = [[0 for _ in range(size)] for _ in range(size)]
    cell_to_risks: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    any_point = False

    def _to_index(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            idx = int(value) - 1
            if idx < 0:
                idx = 0
            if idx >= size:
                idx = size - 1
            return idx
        if isinstance(value, str):
            t = value.strip().lower()
            mapping = {
                "very low": 0,
                "low": 0,
                "medium": 1,
                "moderate": 1,
                "high": 2,
                "very high": 3,
                "critical": 3,
                "severe": 3,
            }
            return mapping.get(t)
        return None

    for entry in raid_log:
        for risk in entry.get("risks") or []:
            like = (
                risk.get("likelihood")
                or risk.get("probability")
                or risk.get("likelihood_level")
            )
            imp = (
                risk.get("impact")
                or risk.get("impact_level")
                or risk.get("severity_impact")
            )

            # Fallback from severity, as we did before
            sev = str(risk.get("severity", "")).lower()
            if sev and (not like):
                like = sev
            if sev and (not imp):
                imp = sev

            li = _to_index(like)
            ii = _to_index(imp)
            if li is None or ii is None:
                continue

            if 0 <= li < size and 0 <= ii < size:
                matrix[li][ii] += 1
                any_point = True
                lh_label = likelihood_labels[li]
                im_label = impact_labels[ii]
                cell_to_risks[(lh_label, im_label)].append(risk)

    if not any_point:
        return None, None, None, {}

    return likelihood_labels, impact_labels, matrix, cell_to_risks


# -------------------------------------------------------------------
# Streamlit UI
# -------------------------------------------------------------------
# Global CSS tweaks
st.markdown(
    """
    <style>
    
    /* GLOBAL TYPOGRAPHY & LAYOUT */

    html, body, [data-testid="stAppViewContainer"] * {
        font-size: 1.1rem !important; 
    }

    [data-testid="stAppViewContainer"] .block-container {
        max-width: 90% !important; 
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        padding-top: 1.5rem !important;
    }
    
    h2, h3 {
        font-size: 2.0rem !important;
        font-weight: 800 !important;
        color: #1f2937;
        border-bottom: 2px solid #e5e7eb;
        padding-bottom: 0.5rem;
        margin-top: 2rem !important;
        margin-bottom: 1rem !important;
    }
    
    h4 {
        font-size: 1.5rem !important;
        font-weight: 700 !important;
    }
    
    /* METRICS */

    div[data-testid="stMetric"] {
        border-radius: 0.5rem;
        padding: 0.5rem;
        background-color: #f9fafb;
        min-height: 100px;
    }

    div[data-testid="stMetricLabel"] {
        font-size: 3.5rem !important;
        font-weight: 700 !important;
        line-height: 1.1 !important;
        color: #1f2937 !important;
    }

    div[data-testid="stMetricLabel"] > div > p {
        font-size: 3.5rem !important; 
        font-weight: 700 !important;
    }
    
    div[data-testid="stMetricValue"] {
        font-size: 2.5rem !important;
        font-weight: 900 !important;
        line-height: 1.0 !important;
        color: #4f46e5 !important;
    }

    /* PLOTLY TITLES */

    .plot-container .plotly .js-plotly-plot .plotly-title {
        font-size: 1.2rem !important; 
        font-weight: 600 !important;
    }
    
    /* TABS */

    .stTabs [data-baseweb="tab"] {
        padding: 0.6rem 1.2rem;
        font-size: 1.2rem !important;
        font-weight: 700;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        color: #4f46e5;
        border-bottom: 3px solid #4f46e5;
        background-color: #f0f2f6;
    }
    
    </style>
    """,
    unsafe_allow_html=True,
)


# Header
st.markdown(
    """
<div style="display:flex; align-items:center; gap:1.25rem; margin-bottom: 1.0rem;">
  <div style="
      width:100px; height:100px; border-radius:25px;
      background:linear-gradient(135deg,#4f46e5,#06b6d4);
      display:flex; align-items:center; justify-content:center;
      color:white; 
      font-size:4.0rem !important;
      font-weight:900;
  ">
    AI
  </div>
  <div>
    <div style="font-size:1.0rem; text-transform:uppercase; letter-spacing:0.16em; color:#6b7280; font-weight:600;">
      Project Intelligence Studio
    </div>
    <div style="font-size:3.5rem !important; font-weight:900; color:#111827;">
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
    extraction = result.get("extraction") or {}

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

        sev_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        raid_log_global: List[Dict[str, Any]] = []
        if not manual_mode:
            raid_log_global = (result.get("risk_analysis") or {}).get("raid_log") or []
            for entry in raid_log_global:
                for risk in entry.get("risks") or []:
                    sev = str(risk.get("severity", "")).lower()
                    if sev in sev_counts:
                        sev_counts[sev] += 1

        if manual_mode:
            status_display = "⏸️ Pending manual approval"
            risk_exposure_val = None
        else:
            complexity_score = counts["complexity_score"]
            risk_exposure_val = (
                sev_counts["critical"] * 3
                + sev_counts["high"] * 2
                + sev_counts["medium"] * 1
            )
            risk_exposure_val = float(min(10, risk_exposure_val))

            timeline_ok = baseline_weeks <= float(deadline_weeks)

            if timeline_ok and complexity_score < 6 and risk_exposure_val < 4:
                status_display = "🟢 On track"
            elif not timeline_ok:
                status_display = "🔴 Off track"
            else:
                status_display = "🟡 At risk"

        st.markdown(f"### Overall project status: {status_display}")

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Team size", f"{summary.get('team_size', team_size)}")
        m2.metric("Target deadline (weeks)", f"{summary.get('deadline_weeks', deadline_weeks):.1f}")
        m3.metric("Estimated timeline (weeks)", f"{summary.get('baseline_timeline_weeks', baseline_weeks):.1f}")

        if manual_mode:
            m4.metric("Complexity score (0–10)", "—", "Manual review pending")
            m5.metric("Risk exposure (0–10)", "—", "Run in auto mode")
        else:
            m4.metric(
                "Complexity score (0-10)",
                f"{counts['complexity_score']:.1f}",
                counts["complexity_level"],
            )
            m5.metric("Risk exposure (0–10)", f"{risk_exposure_val:.1f}")

        st.markdown("---")

        c_left, c_middle, c_right = st.columns((1.2, 1.0, 1.2))

        # Requirements overview
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

            st.markdown("#### Requirements Breakdown")

            if req_values:
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

                fig_pie = px.pie(
                    values=req_values,
                    names=req_labels,
                    title="",
                )
                fig_pie.update_layout(
                    showlegend=False,
                    margin=dict(l=10, r=10, t=10, b=10),
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("No requirements extracted yet (0 functional / 0 non-functional / 0 constraints).")

        # Complexity gauge
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
                        title={"text": "Complexity (0-10)"},
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

        # Risk overview
        with c_right:
            st.markdown("#### Risk Overview")
            if manual_mode:
                st.info("Risk analysis will be available after you approve requirements and re-run in auto mode.")
            else:
                if any(sev_counts.values()):
                    fig_bar = px.bar(
                        x=list(sev_counts.keys()),
                        y=list(sev_counts.values()),
                        title="Risks by Severity",
                        labels={"x": "Severity", "y": "Count"},
                    )
                    fig_bar.update_layout(
                        xaxis_title_font_size=12,
                        yaxis_title_font_size=12,
                        xaxis_tickfont_size=11,
                        yaxis_tickfont_size=11,
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
                else:
                    st.info("No risks recorded yet.")

        st.markdown("---")

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
                    title="Estimated vs Scenario Timelines (weeks)",
                    labels={"x": "Scenario", "y": "Estimated duration (weeks)"},
                )
                fig_timeline.update_layout(
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

            st.markdown("#### Download PM Pack")
            pm_pack_sections: List[str] = []

            pm_pack_sections.append("# PM Pack")
            pm_pack_sections.append("## Normalized Project Brief")
            pm_pack_sections.append(
                "```json\n" + json.dumps(result.get("normalized_project_brief") or {}, indent=2) + "\n```"
            )

            pm_pack_sections.append("## Complexity & Timeline")
            pm_pack_sections.append(
                f"- Team size: {summary.get('team_size', team_size)}\n"
                f"- Target deadline (weeks): {summary.get('deadline_weeks', deadline_weeks):.1f}\n"
                f"- Estimated timeline (weeks): {summary.get('baseline_timeline_weeks', baseline_weeks):.1f}\n"
                f"- Complexity score (0–10): {counts['complexity_score']:.1f}\n"
                f"- Complexity level: {counts['complexity_level']}\n"
            )

            pm_pack_sections.append("## Top Risks (from RAID log)")
            if raid_log_global:
                for entry in raid_log_global:
                    for risk in entry.get("risks") or []:
                        pm_pack_sections.append(
                            f"- **[{risk.get('severity','?').upper()}]** "
                            f"{risk.get('id', 'RISK')} – {risk.get('title') or risk.get('description','')}"
                        )
            else:
                pm_pack_sections.append("_No risks available in this run._")

            pm_pack_sections.append("## Simulation Scenarios")
            if scenario_results:
                for s in scenario_results:
                    pm_pack_sections.append(
                        f"- **{s.get('scenario','Scenario')}** — "
                        f"Timeline impact: {s.get('timeline_impact','0%')}, "
                        f"Key note: {s.get('note') or s.get('description','')}"
                    )
            else:
                pm_pack_sections.append("_No scenarios returned in this run._")

            pm_pack_md = "\n\n".join(pm_pack_sections)

            st.download_button(
                "📥 Download PM Pack (Markdown)",
                pm_pack_md,
                file_name="pm_pack.md",
                mime="text/markdown",
            )

        st.markdown("#### Normalized Project Brief (for debugging)")
        st.json(result.get("normalized_project_brief") or {})

    # ---------------- Extracted Requirements ----------------
    with tab_requirements:
        st.subheader("3. Extracted Requirements & User Stories")

        requirements_list = extraction.get("requirements") or []

        if not isinstance(requirements_list, list):
            requirements_list = []
        else:
            requirements_list = [r for r in requirements_list if isinstance(r, dict)]

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

                    next_id_value = generate_next_id(edited_requirements)
                    try:
                        current_num = int(next_id_value.replace("REQ-", ""))
                    except ValueError:
                        current_num = 1

                    for r in edited_requirements:
                        if not isinstance(r, dict):
                            continue
                        rc = dict(r)

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

    # ---------------- Structured Backlog ----------------
    with tab_structured:
        st.subheader("4. Structured Backlog & RAID Log (Raw JSON)")
        st.json(result.get("structuring") or {})

    # ---------------- Risk Analysis + Heat Map ----------------
    with tab_risk:
        st.subheader("5. Risk Analysis (RAID + Complexity)")
        if manual_mode:
            st.info("Risk analysis is not available in manual-approval mode. Re-run with auto-approval enabled.")
        else:
            risk_analysis = result.get("risk_analysis") or {}
            raid_log = risk_analysis.get("raid_log") or []

            if raid_log:
                st.markdown("#### Risk Heat Map (Likelihood × Impact)")
                lh_labels, im_labels, matrix, cell_to_risks = _build_risk_heatmap_matrix(raid_log)

                if matrix is not None:
                    fig_heat = px.imshow(
                        matrix,
                        x=im_labels,
                        y=lh_labels,
                        labels=dict(x="Impact", y="Likelihood", color="Risk count"),
                        text_auto=True,
                    )
                    fig_heat.update_layout(
                        xaxis_title="Impact",
                        yaxis_title="Likelihood",
                    )
                    st.plotly_chart(fig_heat, use_container_width=True)

                    # Simple "click" behaviour via dropdowns
                    st.markdown("##### View risks for a specific cell")
                    sel_lh = st.selectbox("Likelihood bucket", lh_labels, key="heatmap_likelihood")
                    sel_im = st.selectbox("Impact bucket", im_labels, key="heatmap_impact")

                    risks_here = cell_to_risks.get((sel_lh, sel_im), [])
                    if risks_here:
                        st.markdown(
                            f"**Risks in cell:** Likelihood = `{sel_lh}`, Impact = `{sel_im}`"
                        )
                        for r in risks_here:
                            rid = r.get("id", "RISK")
                            title = r.get("title") or r.get("description", "")
                            sev = r.get("severity", "unknown")
                            st.markdown(f"- **{rid}** (_severity: {sev}_): {title}")
                    else:
                        st.info(
                            "No risks were mapped to this combination. Try a different likelihood/impact cell."
                        )

                else:
                    st.info(
                        "Risk heat map could not be generated because no structured risk "
                        "data was available in the RAID log."
                    )
            else:
                st.info("No RAID log entries available to build a risk heat map.")

            st.markdown("---")
            with st.expander("RAID Analysis (Raw JSON)", expanded=False):
                st.json(risk_analysis or {})

    # ---------------- Mitigation Plans ----------------
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

    # ---------------- Simulation ----------------
    with tab_simulation:
        st.subheader("7. Simulation Results")
        if manual_mode:
            st.info("Simulation results appear only after you run with auto-approval enabled.")
        else:
            st.markdown("#### What-if: Team Size vs Timeline")
            original_team_size = int(summary.get("team_size", team_size))
            sim_team_size = st.slider(
                "Simulate team size (developers)",
                min_value=1,
                max_value=50,
                value=original_team_size,
                key="sim_team_size_slider",
            )

            simulated_baseline_weeks = _recompute_timeline_for_team(
                baseline_weeks=baseline_weeks,
                original_team_size=original_team_size,
                new_team_size=sim_team_size,
            )

            s1, s2 = st.columns(2)
            s1.metric(
                "Estimated timeline (weeks)",
                f"{baseline_weeks:.1f}",
                help="Original estimated timeline from the simulation agent for the given team size.",
            )
            s2.metric(
                f"Simulated timeline (weeks) for team size {sim_team_size}",
                f"{simulated_baseline_weeks:.1f}",
            )

            st.markdown("#### Estimated vs Scenario Timelines (Simulated Team Size)")
            tp_sim = _timeline_points(
                simulated_baseline_weeks,
                scenario_results,
                baseline_label="Simulated baseline",
            )
            if tp_sim["labels"]:
                fig_sim_timeline = px.bar(
                    x=tp_sim["labels"],
                    y=tp_sim["values"],
                    title="Estimated vs Scenario Timelines (weeks, simulated team size)",
                    labels={"x": "Scenario", "y": "Estimated duration (weeks)"},
                )
                fig_sim_timeline.update_layout(
                    xaxis_title_font_size=12,
                    yaxis_title_font_size=12,
                    xaxis_tickfont_size=11,
                    yaxis_tickfont_size=11,
                )
                st.plotly_chart(fig_sim_timeline, use_container_width=True)
            else:
                st.info("No simulation scenarios available to visualize.")

            st.markdown("#### Scope-cut suggestions to hit target")
            if simulated_baseline_weeks <= float(deadline_weeks):
                st.success(
                    "With this team size, the simulated timeline is within the target deadline. "
                    "Scope-cut is not strictly required."
                )
            else:
                all_reqs = extraction.get("requirements") or []
                low_med_reqs = [
                    r
                    for r in all_reqs
                    if str(r.get("priority", "medium")).lower() in ("low", "medium")
                ]

                overshoot_weeks = simulated_baseline_weeks - float(deadline_weeks)

                if not low_med_reqs:
                    st.warning(
                        "Timeline exceeds target, but there are no LOW/MED priority requirements to drop. "
                        "You may need to revisit priorities or increase team size."
                    )
                else:
                    approx_drop_count = int(round(overshoot_weeks))
                    approx_drop_count = max(1, approx_drop_count)
                    approx_drop_count = min(approx_drop_count, len(low_med_reqs))

                    suggested_to_drop = low_med_reqs[:approx_drop_count]

                    st.warning(
                        f"To hit the **{deadline_weeks:.1f} week** target with team size **{sim_team_size}**, "
                        f"you likely need to drop or defer **~{approx_drop_count}** lower-priority requirements."
                    )

                    for r in suggested_to_drop:
                        rid = r.get("id", "REQ")
                        rtext = r.get("text", "")
                        rprio = r.get("priority", "medium")
                        st.markdown(f"- **{rid}** (_priority: {rprio}_): {rtext}")

            st.markdown("---")
            st.markdown("#### Raw Simulation JSON")
            st.json(result.get("simulation") or {})

    # ---------------- Validation Loop ----------------
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

    # ---------------- Final JSON & Downloads ----------------
    with tab_final_json:
        st.subheader("9. Final Impact & Recommendation Report (Full JSON)")
        if manual_mode:
            st.info("Final report is generated after risk & simulation in auto-approval mode.")
        else:
            st.json(result.get("final_report") or {})

            st.markdown("---")
            st.markdown("### Download per-agent JSON outputs")

            st.download_button(
                "Download ingestion_output.json",
                json.dumps(result.get("ingestion") or {}, indent=2),
                "ingestion_output.json",
                mime="application/json",
            )
            st.download_button(
                "Download requirements.json",
                json.dumps(result.get("extraction") or {}, indent=2),
                "requirements.json",
                mime="application/json",
            )
            st.download_button(
                "Download raid_log.json",
                json.dumps(
                    (result.get("risk_analysis") or {}).get("raid_log") or [],
                    indent=2,
                ),
                "raid_log.json",
                mime="application/json",
            )
            st.download_button(
                "Download simulation.json",
                json.dumps(result.get("simulation") or {}, indent=2),
                "simulation.json",
                mime="application/json",
            )
            st.download_button(
                "Download final_report.json",
                json.dumps(result.get("final_report") or {}, indent=2),
                "final_report.json",
                mime="application/json",
            )
