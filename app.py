"""SCHEMA Streamlit application — interview evaluation pipeline."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from core.config_loader import TrackConfig, load_department_rubric, parse_config
from core.departments import Department, get_department, load_departments
from core.exporter import export_csv_bytes, export_xlsx_bytes
from core.scoring_engine import (
    compute_candidate_score,
    generate_attribution_notes,
    odds_ratio,
    sanitize_meeting_link,
)
from core.sheets_store import SheetsStore, SheetsStoreError


st.set_page_config(
    page_title="SCHEMA Interview Engine",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _secrets_available() -> bool:
    try:
        _ = st.secrets["app_password"]
        return True
    except Exception:
        return False


def _get_store() -> SheetsStore | None:
    if "sheets_store" in st.session_state and st.session_state.sheets_store is not None:
        return st.session_state.sheets_store
    try:
        store = SheetsStore.from_secrets(st.secrets)
        st.session_state.sheets_store = store
        return store
    except Exception as exc:
        st.session_state.sheets_last_error = str(exc)
        st.session_state.sheets_store = None
        return None


def _load_active_config(dept: Department) -> TrackConfig:
    store = _get_store()
    if store is not None:
        try:
            override = store.load_rubric_override(dept.display_name)
            if override is not None:
                return override
        except Exception:
            pass
    return load_department_rubric(dept)


def _require_auth() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.title("SCHEMA")
    st.caption("Scoring Candidates via Heuristic Evaluation Model Architecture")
    st.markdown("Enter the shared org password to continue.")

    with st.form("auth_form"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Unlock", type="primary")
        if submitted:
            expected = None
            try:
                expected = st.secrets["app_password"]
            except Exception:
                st.error("App password not configured. Admin must set `app_password` in Streamlit secrets.")
                return False
            if password == expected:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


def _department_gate() -> Department | None:
    if st.session_state.get("active_department_id"):
        return get_department(st.session_state.active_department_id)

    st.title("Select department")
    st.markdown("Pick the track you are interviewing for. Your Google Sheet tab matches this name.")

    depts = load_departments()
    labels = [d.display_name for d in depts]
    with st.form("dept_form"):
        choice = st.selectbox("Department", labels, index=labels.index("Data Engineering") if "Data Engineering" in labels else 0)
        ok = st.form_submit_button("Continue", type="primary")
        if ok:
            selected = next(d for d in depts if d.display_name == choice)
            st.session_state.active_department_id = selected.id
            st.session_state.pop("feature_toggles", None)
            st.rerun()
    return None


def _reset_interview_form_state(config: TrackConfig) -> None:
    st.session_state.candidate_name = ""
    st.session_state.first_choice = ""
    st.session_state.second_choice = ""
    st.session_state.meeting_link = ""
    st.session_state.qualitative_notes = ""
    st.session_state.feature_toggles = {q.id: False for q in config.all_questions()}
    # Drop old checkbox widget keys so new nonce starts clean
    old_nonce = st.session_state.get("form_nonce", 0)
    for q in config.all_questions():
        st.session_state.pop(f"feat_{old_nonce}_{q.id}", None)
    st.session_state.form_nonce = old_nonce + 1


def _init_interview_state(config: TrackConfig) -> None:
    if "feature_toggles" not in st.session_state:
        st.session_state.feature_toggles = {q.id: False for q in config.all_questions()}
    else:
        # Keep toggles in sync with rubric question ids
        current = st.session_state.feature_toggles
        for q in config.all_questions():
            current.setdefault(q.id, False)
        st.session_state.feature_toggles = {qid: current.get(qid, False) for qid in [q.id for q in config.all_questions()]}
    for key, default in [
        ("candidate_name", ""),
        ("first_choice", ""),
        ("second_choice", ""),
        ("meeting_link", ""),
        ("qualitative_notes", ""),
        ("form_nonce", 0),
    ]:
        st.session_state.setdefault(key, default)


def render_live_interview(dept: Department, config: TrackConfig) -> None:
    _init_interview_state(config)
    store = _get_store()

    nonce = st.session_state.form_nonce
    st.subheader(f"Live Interview — {dept.display_name}")
    st.caption(config.system_title)
    st.caption(f"Term: {config.term}")

    if store is None:
        st.warning(
            "Google Sheets not connected. Configure secrets to enable submit/sync. "
            f"Last error: {st.session_state.get('sheets_last_error', 'n/a')}"
        )
        next_id = "Candidate #??"
    else:
        try:
            next_id = store.next_candidate_number(dept.display_name)
        except Exception as exc:
            next_id = "Candidate #??"
            st.warning(f"Could not read cohort size: {exc}")

    st.info(f"**{next_id}** (auto-assigned on submit)")

    col_main, col_side = st.columns([2.2, 1], gap="large")

    with col_main:
        st.text_input("Full Name", key="candidate_name")
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("1st Choice (track)", key="first_choice")
        with c2:
            st.text_input("2nd Choice (track)", key="second_choice")
        st.text_input("Meeting Link", key="meeting_link", placeholder="https://...")

        for section in config.sections:
            st.markdown(f"### {section.title}")
            st.caption(f"Allocated time: **{section.allocated_time_minutes} mins**")
            for q in section.questions:
                with st.container(border=True):
                    st.markdown(f"**{q.label}** · weight `{q.weight}` · OR `{odds_ratio(q.weight):.2f}x`")
                    st.write(q.prompt)
                    st.markdown(
                        f"<div style='font-size:0.85rem;color:#555;padding:0.4rem 0.6rem;"
                        f"background:#f6f6f6;border-radius:6px;margin:0.4rem 0;'>"
                        f"<b>Pass:</b> {q.pass_criteria}<br/>"
                        f"<b>Fail:</b> {q.fail_criteria}</div>",
                        unsafe_allow_html=True,
                    )
                    toggle_key = f"feat_{nonce}_{q.id}"
                    if toggle_key not in st.session_state:
                        st.session_state[toggle_key] = bool(
                            st.session_state.feature_toggles.get(q.id, False)
                        )
                    st.checkbox("Criterion met (Pass)", key=toggle_key)

        st.text_area("Qualitative field notes", key="qualitative_notes", height=120)

    # Mirror widget keys into feature_toggles for submit/reset
    for q in config.all_questions():
        toggle_key = f"feat_{nonce}_{q.id}"
        st.session_state.feature_toggles[q.id] = bool(st.session_state.get(toggle_key, False))

    features = {
        q.id: 1 if st.session_state.feature_toggles.get(q.id) else 0
        for q in config.all_questions()
    }
    score = compute_candidate_score(features, config)

    with col_side:
        st.markdown("### Live gauge")
        if score.used_fallback:
            st.error("FALLBACK scoring active (weight defense). Check rubric weights.")
        st.metric("P(Pass)", f"{score.probability * 100:.1f}%")
        st.progress(min(max(score.probability, 0.0), 1.0))
        st.write(f"Logit: `{score.logit:+.2f}`")
        st.write(f"Raw: **{score.raw_score}/{score.total_criteria}**")
        st.markdown("**Top drivers**")
        if score.positive_drivers:
            for label, w in score.positive_drivers[:5]:
                st.write(f"- {label} (+{w:.2f})")
        else:
            st.write("- None yet")
        st.markdown("**Risks**")
        if score.risk_factors:
            for label, w in score.risk_factors[:5]:
                st.write(f"- {label} (+{w:.2f})")
        else:
            st.write("- None")

        preview = generate_attribution_notes(
            features,
            st.session_state.qualitative_notes,
            config,
            score=score,
        )
        st.caption("NOTES preview")
        st.code(preview, language=None)

    if st.button("Submit & Ingest Candidate", type="primary", use_container_width=True):
        name = (st.session_state.candidate_name or "").strip()
        if not name:
            st.error("NAME is required (empty or whitespace rejected).")
            return
        if store is None:
            st.error("Cannot submit: Google Sheets not connected.")
            return

        meeting = sanitize_meeting_link(st.session_state.meeting_link)
        notes = generate_attribution_notes(
            features,
            st.session_state.qualitative_notes,
            config,
            score=score,
        )
        try:
            result = store.submit_candidate(
                department_display=dept.display_name,
                name=name,
                first_choice=(st.session_state.first_choice or "").strip(),
                second_choice=(st.session_state.second_choice or "").strip(),
                meeting_link=meeting,
                qualitative_notes=st.session_state.qualitative_notes or "",
                features=features,
                config=config,
                notes_text=notes,
                score_logit=score.logit,
                score_probability=score.probability,
            )
            _reset_interview_form_state(config)
            st.success(
                f"Ingested **{result['name']}** → status **{result['status']}** "
                f"(P={result['probability'] * 100:.1f}%). Synced to Google Sheet."
            )
            st.balloons()
            st.rerun()
        except Exception as exc:
            st.session_state.sheets_last_error = str(exc)
            st.error(f"Submit failed — form kept. Fix Sheets access and retry. Error: {exc}")


def render_cohort(dept: Department, config: TrackConfig) -> None:
    st.subheader(f"Cohort Ranking — {dept.display_name}")
    store = _get_store()
    if store is None:
        st.error("Google Sheets not connected.")
        return

    top_k = st.slider(
        "Top-K slots",
        min_value=1,
        max_value=20,
        value=int(config.model_parameters.top_k_slots),
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Re-rank STATUS now", use_container_width=True):
            try:
                store.recalculate_ranks(
                    dept.display_name,
                    top_k=top_k,
                    pass_threshold=config.model_parameters.pass_threshold_probability,
                )
                st.success("Statuses updated on Google Sheet.")
            except Exception as exc:
                st.error(f"Re-rank failed: {exc}")
    with c2:
        if st.button("Refresh cohort", use_container_width=True):
            st.rerun()

    try:
        cohort = store.list_cohort(dept.display_name)
    except Exception as exc:
        st.error(f"Could not load cohort: {exc}")
        return

    if not cohort:
        st.info("No candidates yet for this department.")
        return

    df = pd.DataFrame(
        [
            {
                "INTERVIEW TIME": r["interview_time"],
                "NAME": r["name"],
                "1st Choice": r["first_choice"],
                "2nd Choice": r["second_choice"],
                "P(Pass)": round(float(r["probability"]) * 100, 1),
                "Logit": round(float(r["logit"]), 2),
                "Meeting Link": r["meeting_link"],
                "Notes": r.get("notes") or "",
                "STATUS": r["status"],
            }
            for r in cohort
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    xlsx = export_xlsx_bytes(cohort)
    csv = export_csv_bytes(cohort)
    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "Download .xlsx",
            data=xlsx,
            file_name=f"SCHEMA_{dept.id}_cohort.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            "Download .csv",
            data=csv,
            file_name=f"SCHEMA_{dept.id}_cohort.csv",
            mime="text/csv",
            use_container_width=True,
        )

    if st.session_state.get("sheets_last_error"):
        st.caption(f"Last Sheets error: {st.session_state.sheets_last_error}")


def render_rubric_manager(dept: Department, config: TrackConfig) -> None:
    st.subheader(f"Rubric Manager — {dept.display_name}")
    st.markdown(
        "Edit questions and weights with the forms below. "
        "**Save writes to Google Sheets** (`_SCHEMA_RUBRICS`) so changes survive Cloud redeploys. "
        "See [docs/CHANGE_RUBRIC.md](docs/CHANGE_RUBRIC.md)."
    )

    if "rubric_draft_json" not in st.session_state or st.session_state.get("rubric_draft_dept") != dept.id:
        st.session_state.rubric_draft_json = json.dumps(config.to_dict(), indent=2)
        st.session_state.rubric_draft_dept = dept.id

    try:
        draft = parse_config(st.session_state.rubric_draft_json)
    except Exception as exc:
        st.error(f"Draft invalid: {exc}")
        draft = config

    # Meta
    with st.expander("Model parameters", expanded=True):
        beta = st.number_input("beta_0 (baseline log-odds)", value=float(draft.model_parameters.beta_0), step=0.1)
        top_k = st.number_input("top_k_slots", min_value=1, value=int(draft.model_parameters.top_k_slots), step=1)
        thresh = st.number_input(
            "pass_threshold_probability",
            min_value=0.0,
            max_value=1.0,
            value=float(draft.model_parameters.pass_threshold_probability),
            step=0.01,
        )
        term = st.text_input("Term", value=draft.term)

    # Weight chart
    weights = {q.label: q.weight for q in draft.all_questions()}
    if weights:
        st.markdown("### Relative feature weights")
        st.bar_chart(pd.DataFrame({"weight": weights}))

    # Question editors
    edited_sections: list[dict[str, Any]] = []
    for s_idx, section in enumerate(draft.sections):
        st.markdown(f"### Section: {section.title}")
        sec_title = st.text_input(f"Section title ({section.section_id})", value=section.title, key=f"sec_title_{s_idx}")
        sec_time = st.number_input(
            f"Minutes ({section.section_id})",
            min_value=1,
            value=int(section.allocated_time_minutes),
            key=f"sec_time_{s_idx}",
        )
        q_dicts = []
        for q in section.questions:
            with st.container(border=True):
                st.caption(f"id: `{q.id}` (do not rename after candidates exist)")
                label = st.text_input("Label", value=q.label, key=f"label_{q.id}")
                prompt = st.text_area("Prompt", value=q.prompt, key=f"prompt_{q.id}")
                pass_c = st.text_area("Pass criteria", value=q.pass_criteria, key=f"pass_{q.id}")
                fail_c = st.text_area("Fail criteria", value=q.fail_criteria, key=f"fail_{q.id}")
                weight = st.number_input("Weight (must be > 0)", min_value=0.01, value=float(q.weight), step=0.1, key=f"w_{q.id}")
                q_dicts.append(
                    {
                        "id": q.id,
                        "label": label,
                        "prompt": prompt,
                        "pass_criteria": pass_c,
                        "fail_criteria": fail_c,
                        "weight": weight,
                    }
                )
        edited_sections.append(
            {
                "section_id": section.section_id,
                "title": sec_title,
                "allocated_time_minutes": int(sec_time),
                "questions": q_dicts,
            }
        )

    with st.expander("Advanced JSON", expanded=False):
        raw = st.text_area("Rubric JSON", value=st.session_state.rubric_draft_json, height=280)
        if st.button("Validate JSON into draft"):
            try:
                parse_config(raw)
                st.session_state.rubric_draft_json = raw
                st.success("JSON valid — draft updated.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    built = {
        "system_title": draft.system_title,
        "department": dept.display_name,
        "term": term,
        "model_parameters": {
            "beta_0": float(beta),
            "top_k_slots": int(top_k),
            "pass_threshold_probability": float(thresh),
        },
        "sections": edited_sections,
    }

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("Validate form draft", use_container_width=True):
            try:
                parse_config(built)
                st.session_state.rubric_draft_json = json.dumps(built, indent=2)
                st.success("Form draft valid.")
            except Exception as exc:
                st.error(str(exc))
    with b2:
        if st.button("Save to Google Sheets", type="primary", use_container_width=True):
            store = _get_store()
            if store is None:
                st.error("Sheets not connected.")
            else:
                try:
                    validated = parse_config(built)
                    store.save_rubric_override(dept.display_name, validated)
                    st.session_state.rubric_draft_json = json.dumps(validated.to_dict(), indent=2)
                    st.success("Saved to Google (`_SCHEMA_RUBRICS`). Survives redeploy.")
                except Exception as exc:
                    st.error(f"Save failed: {exc}")
    with b3:
        if st.button("Rescore all candidates", use_container_width=True):
            store = _get_store()
            if store is None:
                st.error("Sheets not connected.")
            else:
                try:
                    validated = parse_config(built)
                    n = store.rescore_department(dept.display_name, validated)
                    st.success(f"Rescored {n} candidate(s) and re-ranked.")
                except Exception as exc:
                    st.error(f"Rescore failed: {exc}")


def main() -> None:
    if not _secrets_available():
        st.title("SCHEMA")
        st.error(
            "Streamlit secrets missing. Copy `.streamlit/secrets.toml.example` to "
            "`.streamlit/secrets.toml` (local) or set secrets in Streamlit Cloud. "
            "See docs/ADMIN_SETUP.md."
        )
        return

    if not _require_auth():
        return

    with st.sidebar:
        st.markdown("### SCHEMA")
        if st.session_state.get("active_department_id"):
            dept_preview = get_department(st.session_state.active_department_id)
            st.write(f"Department: **{dept_preview.display_name}**")
            if st.button("Switch department"):
                st.session_state.pop("active_department_id", None)
                st.session_state.pop("feature_toggles", None)
                st.session_state.pop("rubric_draft_json", None)
                st.rerun()
        if st.button("Log out"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    dept = _department_gate()
    if dept is None:
        return

    config = _load_active_config(dept)

    tab_live, tab_cohort, tab_rubric = st.tabs(
        ["Live Interview", "Cohort Ranking", "Rubric Manager"]
    )
    with tab_live:
        render_live_interview(dept, config)
    with tab_cohort:
        render_cohort(dept, config)
    with tab_rubric:
        render_rubric_manager(dept, config)


if __name__ == "__main__":
    main()
