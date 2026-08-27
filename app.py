"""SCHEMA Streamlit application — interview evaluation pipeline."""

from __future__ import annotations

import json
from typing import Any, Literal

import pandas as pd
import streamlit as st

from core.config_loader import TrackConfig, load_department_rubric, parse_config
from core.departments import Department, department_display_names, get_department, load_departments
from core.exporter import export_csv_bytes, export_xlsx_bytes
from core.scoring_engine import (
    compute_candidate_score,
    generate_attribution_notes,
    sanitize_meeting_link,
)
from core.sheets_store import SheetsStore

NavPage = Literal["Interview", "Cohort", "Configure"]

# Bump when SheetsStore session API changes — forces fresh instance after hot reload
_STORE_VERSION = 3

st.set_page_config(
    page_title="SCHEMA Interview",
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


def _store_is_compatible(store: object) -> bool:
    return (
        isinstance(store, SheetsStore)
        and getattr(store, "_store_version", None) == _STORE_VERSION
        and hasattr(store, "invalidate_caches")
        and hasattr(store, "count_department_candidates")
    )


def _invalidate_store_caches(store: SheetsStore | None) -> None:
    if store is not None and hasattr(store, "invalidate_caches"):
        store.invalidate_caches()


def _get_store(*, force_new: bool = False) -> SheetsStore | None:
    if force_new:
        st.session_state.pop("sheets_store", None)
    store = st.session_state.get("sheets_store")
    if store is not None and not _store_is_compatible(store):
        st.session_state.pop("sheets_store", None)
        store = None
    if store is not None:
        return store
    try:
        store = SheetsStore.from_secrets(st.secrets)
        st.session_state.sheets_store = store
        st.session_state.sheets_last_error = None
        return store
    except Exception as exc:
        st.session_state.sheets_last_error = str(exc)
        st.session_state.sheets_store = None
        return None


def _candidate_count_key(dept: Department) -> str:
    return f"candidate_count_{dept.id}"


def _refresh_candidate_count(dept: Department, store: SheetsStore) -> int:
    count = store.count_department_candidates(dept.display_name)
    st.session_state[_candidate_count_key(dept)] = count
    return count


def _candidate_label(dept: Department) -> str:
    count = st.session_state.get(_candidate_count_key(dept))
    if count is None:
        return "Candidate #??"
    return f"Candidate #{count + 1:02d}"


def _load_active_config(dept: Department) -> TrackConfig:
    cache_key = f"active_rubric_{dept.id}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    store = _get_store()
    config: TrackConfig | None = None
    if store is not None:
        try:
            config = store.load_rubric_override(dept.display_name)
        except Exception:
            config = None
    if config is None:
        config = load_department_rubric(dept)
    st.session_state[cache_key] = config
    return config


def _require_auth() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.title("SCHEMA")
    st.caption("Interview scoring for SBD tech leads")
    with st.form("auth_form"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Continue", type="primary")
        if submitted:
            try:
                expected = st.secrets["app_password"]
            except Exception:
                st.error("App password not configured. See docs/ADMIN_SETUP.md.")
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

    st.title("Which department are you interviewing for?")
    st.caption("Your answers sync to the matching Google Sheet tab.")

    depts = load_departments()
    labels = [d.display_name for d in depts]
    default_idx = labels.index("Data Engineering") if "Data Engineering" in labels else 0

    with st.form("dept_form"):
        choice = st.selectbox("Department", labels, index=default_idx)
        if st.form_submit_button("Start interviewing", type="primary"):
            selected = next(d for d in depts if d.display_name == choice)
            st.session_state.active_department_id = selected.id
            st.session_state.pop("feature_toggles", None)
            st.session_state.pop(f"candidate_count_{selected.id}", None)
            st.session_state.pop(f"active_rubric_{selected.id}", None)
            st.rerun()
    return None


def _reset_interview_form_state(config: TrackConfig, dept: Department) -> None:
    tracks = department_display_names()
    st.session_state.candidate_name = ""
    st.session_state.first_choice = dept.display_name if dept.display_name in tracks else (tracks[0] if tracks else "")
    st.session_state.second_choice = tracks[1] if len(tracks) > 1 else (tracks[0] if tracks else "")
    st.session_state.meeting_link = ""
    st.session_state.qualitative_notes = ""
    st.session_state.feature_toggles = {q.id: False for q in config.all_questions()}
    old_nonce = st.session_state.get("form_nonce", 0)
    for q in config.all_questions():
        st.session_state.pop(f"feat_{old_nonce}_{q.id}", None)
    st.session_state.form_nonce = old_nonce + 1


def _init_interview_state(config: TrackConfig, dept: Department) -> None:
    if "feature_toggles" not in st.session_state:
        st.session_state.feature_toggles = {q.id: False for q in config.all_questions()}
    else:
        current = st.session_state.feature_toggles
        for q in config.all_questions():
            current.setdefault(q.id, False)
        st.session_state.feature_toggles = {
            q.id: current.get(q.id, False) for q in config.all_questions()
        }
    for key, default in [
        ("candidate_name", ""),
        ("first_choice", dept.display_name),
        ("second_choice", ""),
        ("meeting_link", ""),
        ("qualitative_notes", ""),
        ("form_nonce", 0),
    ]:
        st.session_state.setdefault(key, default)

    tracks = department_display_names()
    if st.session_state.get("first_choice") not in tracks and tracks:
        st.session_state.first_choice = dept.display_name if dept.display_name in tracks else tracks[0]
    if st.session_state.get("second_choice") not in tracks and tracks:
        st.session_state.second_choice = tracks[1] if len(tracks) > 1 else tracks[0]


def _sync_features_from_widgets(config: TrackConfig, nonce: int) -> dict[str, int]:
    for q in config.all_questions():
        toggle_key = f"feat_{nonce}_{q.id}"
        st.session_state.feature_toggles[q.id] = bool(st.session_state.get(toggle_key, False))
    return {
        q.id: 1 if st.session_state.feature_toggles.get(q.id) else 0
        for q in config.all_questions()
    }


def _render_score_sidebar(
    score,
    features: dict[str, int],
    config: TrackConfig,
    show_details: bool,
) -> None:
    st.markdown("**Progress**")
    if score.used_fallback:
        st.warning("Scoring fallback active — review weights in Configure.")

    st.metric("Criteria met", f"{score.raw_score} / {score.total_criteria}")
    st.progress(score.raw_score / score.total_criteria if score.total_criteria else 0.0)

    if show_details:
        with st.expander("Scoring details", expanded=True):
            st.write(f"Pass estimate: **{score.probability * 100:.0f}%**")
            if score.positive_drivers:
                st.caption("Strengths")
                for label, _ in score.positive_drivers[:4]:
                    st.write(f"• {label}")
            if score.risk_factors:
                st.caption("Gaps")
                for label, _ in score.risk_factors[:4]:
                    st.write(f"• {label}")
            preview = generate_attribution_notes(
                features,
                st.session_state.get("qualitative_notes", ""),
                config,
                score=score,
            )
            st.caption("Notes sent to sheet")
            st.text(preview[:480] + ("…" if len(preview) > 480 else ""))


def render_live_interview(dept: Department, config: TrackConfig) -> None:
    _init_interview_state(config, dept)
    if st.session_state.pop("_clear_interview_form", False):
        _reset_interview_form_state(config, dept)
    store = _get_store()
    nonce = st.session_state.form_nonce
    show_details = st.session_state.get("show_scoring_details", False)

    st.header("Interview")
    st.caption(f"{dept.display_name} · {config.term}")

    if msg := st.session_state.pop("last_submit_message", None):
        st.success(msg)

    if store is None:
        st.warning("Google Sheets not connected — submit disabled until secrets are configured.")
        next_id = "Candidate #??"
    else:
        count_key = _candidate_count_key(dept)
        if count_key not in st.session_state:
            try:
                _refresh_candidate_count(dept, store)
            except Exception as exc:
                st.session_state.sheets_last_error = str(exc)
        next_id = _candidate_label(dept)
        if st.session_state.get(_candidate_count_key(dept)) is None:
            st.caption("Could not load cohort count from Sheets yet.")

    col_form, col_score = st.columns([2.4, 1], gap="large")

    with col_form:
        st.markdown(f"**{next_id}**")
        st.text_input("Candidate name *", key="candidate_name", placeholder="Full name")
        tracks = department_display_names()
        c1, c2 = st.columns(2)
        with c1:
            st.selectbox("1st choice track *", tracks, key="first_choice")
        with c2:
            st.selectbox("2nd choice track *", tracks, key="second_choice")
        st.text_input("Meeting link", key="meeting_link", placeholder="Optional")

        for section in config.sections:
            with st.expander(
                f"{section.title} · ~{section.allocated_time_minutes} min",
                expanded=(section.section_id == "general"),
            ):
                for q in section.questions:
                    st.markdown(f"**{q.label}**")
                    st.write(q.prompt)
                    st.caption(f"Pass if: {q.pass_criteria}")
                    st.caption(f"Fail if: {q.fail_criteria}")
                    toggle_key = f"feat_{nonce}_{q.id}"
                    if toggle_key not in st.session_state:
                        st.session_state[toggle_key] = bool(
                            st.session_state.feature_toggles.get(q.id, False)
                        )
                    st.checkbox("Met pass criteria", key=toggle_key)

        st.text_area(
            "Your notes (optional)",
            key="qualitative_notes",
            height=100,
            placeholder="Anything not captured by the checkboxes…",
        )

        features = _sync_features_from_widgets(config, nonce)
        score = compute_candidate_score(features, config)

        if st.button("Submit candidate", type="primary", use_container_width=True):
            name = (st.session_state.candidate_name or "").strip()
            if not name:
                st.error("Candidate name is required.")
                return
            first = (st.session_state.first_choice or "").strip()
            second = (st.session_state.second_choice or "").strip()
            if first == second:
                st.error("1st and 2nd choice must be different departments.")
                return
            if store is None:
                st.error("Cannot submit — Google Sheets not connected.")
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
                    first_choice=first,
                    second_choice=second,
                    meeting_link=meeting,
                    qualitative_notes=st.session_state.qualitative_notes or "",
                    features=features,
                    config=config,
                    notes_text=notes,
                    score_logit=score.logit,
                    score_probability=score.probability,
                )
                st.session_state._clear_interview_form = True
                st.session_state.last_submit_message = (
                    f"Saved **{result['name']}** · Status: **{result['status']}**"
                )
                count_key = _candidate_count_key(dept)
                prev = st.session_state.get(count_key)
                st.session_state[count_key] = (prev if prev is not None else 0) + 1
                st.session_state.pop(f"active_rubric_{dept.id}", None)
                st.rerun()
            except Exception as exc:
                st.session_state.sheets_last_error = str(exc)
                # Submit may have succeeded before a post-save step failed
                if "invalidate_caches" in str(exc):
                    st.session_state.pop("sheets_store", None)
                    st.warning("Saved, but session was stale — store refreshed. Check your Google Sheet.")
                else:
                    st.error(f"Submit failed — your answers are still here. {exc}")

    with col_score:
        features = _sync_features_from_widgets(config, nonce)
        score = compute_candidate_score(features, config)
        _render_score_sidebar(score, features, config, show_details)


def render_cohort(dept: Department, config: TrackConfig) -> None:
    st.header("Cohort")
    st.caption("Ranked list for this department")

    store = _get_store()
    if store is None:
        st.error("Google Sheets not connected.")
        return

    show_details = st.session_state.get("show_scoring_details", False)

    with st.expander("Ranking settings", expanded=False):
        top_k = st.slider(
            "Pass slots (Top-K)",
            min_value=1,
            max_value=20,
            value=int(config.model_parameters.top_k_slots),
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Apply ranking", use_container_width=True):
                try:
                    store.recalculate_ranks(
                        dept.display_name,
                        top_k=top_k,
                        pass_threshold=config.model_parameters.pass_threshold_probability,
                    )
                    st.success("Statuses updated.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        with c2:
            if st.button("Refresh", use_container_width=True):
                _invalidate_store_caches(store)
                st.session_state.pop(_candidate_count_key(dept), None)
                st.rerun()

    try:
        cohort = store.list_cohort(dept.display_name)
    except Exception as exc:
        st.error(f"Could not load cohort: {exc}")
        return

    if not cohort:
        st.info("No candidates yet. Complete an interview and submit.")
        return

    rows = []
    for r in cohort:
        row: dict[str, Any] = {
            "Interview time": r["interview_time"],
            "Name": r["name"],
            "1st choice": r["first_choice"],
            "2nd choice": r["second_choice"],
            "Score": f"{float(r['probability']) * 100:.0f}%",
            "Status": r["status"],
        }
        if show_details:
            row["Logit"] = round(float(r["logit"]), 2)
            row["Meeting"] = r["meeting_link"]
        rows.append(row)

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("Export", expanded=False):
        xlsx = export_xlsx_bytes(cohort)
        csv = export_csv_bytes(cohort)
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "Download Excel",
                data=xlsx,
                file_name=f"SCHEMA_{dept.id}_cohort.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with d2:
            st.download_button(
                "Download CSV",
                data=csv,
                file_name=f"SCHEMA_{dept.id}_cohort.csv",
                mime="text/csv",
                use_container_width=True,
            )


def render_configure(dept: Department, config: TrackConfig) -> None:
    st.header("Configure rubric")
    st.caption("Saved changes apply to Google Sheets and future interviews.")

    if "rubric_draft_json" not in st.session_state or st.session_state.get("rubric_draft_dept") != dept.id:
        st.session_state.rubric_draft_json = json.dumps(config.to_dict(), indent=2)
        st.session_state.rubric_draft_dept = dept.id

    try:
        draft = parse_config(st.session_state.rubric_draft_json)
    except Exception as exc:
        st.error(f"Could not load rubric: {exc}")
        draft = config

    with st.expander("Ranking rules", expanded=True):
        top_k = st.number_input(
            "Pass slots (Top-K)",
            min_value=1,
            value=int(draft.model_parameters.top_k_slots),
            step=1,
            help="How many candidates can receive Top-K Pass.",
        )
        thresh_pct = st.slider(
            "Minimum pass score (%)",
            min_value=0,
            max_value=100,
            value=int(round(draft.model_parameters.pass_threshold_probability * 100)),
            help="Below this score, Top-K Pass is not allowed.",
        )
        term = st.text_input("Interview term", value=draft.term)

    beta = float(draft.model_parameters.beta_0)

    st.markdown("### Questions")
    edited_sections: list[dict[str, Any]] = []
    for s_idx, section in enumerate(draft.sections):
        with st.expander(section.title, expanded=False):
            sec_title = st.text_input("Section name", value=section.title, key=f"sec_title_{s_idx}")
            sec_time = st.number_input(
                "Suggested minutes",
                min_value=1,
                value=int(section.allocated_time_minutes),
                key=f"sec_time_{s_idx}",
            )
            q_dicts = []
            for q in section.questions:
                st.markdown(f"**{q.label}**")
                st.caption(f"Internal id: `{q.id}` — do not change after interviews start")
                label = st.text_input("Short label", value=q.label, key=f"label_{q.id}")
                prompt = st.text_area("Question to ask", value=q.prompt, key=f"prompt_{q.id}", height=80)
                pass_c = st.text_area("Pass if…", value=q.pass_criteria, key=f"pass_{q.id}", height=60)
                fail_c = st.text_area("Fail if…", value=q.fail_criteria, key=f"fail_{q.id}", height=60)
                weight = st.number_input(
                    "Importance (weight)",
                    min_value=0.01,
                    value=float(q.weight),
                    step=0.1,
                    key=f"w_{q.id}",
                )
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
                st.divider()
            edited_sections.append(
                {
                    "section_id": section.section_id,
                    "title": sec_title,
                    "allocated_time_minutes": int(sec_time),
                    "questions": q_dicts,
                }
            )

    with st.expander("Advanced scoring settings", expanded=False):
        beta = st.number_input(
            "Baseline difficulty (beta_0)",
            value=float(draft.model_parameters.beta_0),
            step=0.1,
            help="More negative = harder to pass with few criteria met.",
        )
        weights = {q.label: q.weight for q in draft.all_questions()}
        if weights:
            st.caption("Question importance")
            st.bar_chart(pd.DataFrame({"weight": weights}))

        raw_json = st.text_area("Raw JSON", value=st.session_state.rubric_draft_json, height=180)
        if st.button("Load JSON into form"):
            try:
                parse_config(raw_json)
                st.session_state.rubric_draft_json = raw_json
                st.success("JSON loaded.")
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
            "pass_threshold_probability": float(thresh_pct) / 100.0,
        },
        "sections": edited_sections,
    }

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save rubric", type="primary", use_container_width=True):
            store = _get_store()
            if store is None:
                st.error("Google Sheets not connected.")
            else:
                try:
                    validated = parse_config(built)
                    store.save_rubric_override(dept.display_name, validated)
                    st.session_state.rubric_draft_json = json.dumps(validated.to_dict(), indent=2)
                    st.session_state[f"active_rubric_{dept.id}"] = validated
                    st.success("Saved to Google Sheets.")
                except Exception as exc:
                    st.error(str(exc))
    with c2:
        if st.button("Rescore existing candidates", use_container_width=True):
            store = _get_store()
            if store is None:
                st.error("Google Sheets not connected.")
            else:
                try:
                    validated = parse_config(built)
                    n = store.rescore_department(dept.display_name, validated)
                    st.success(f"Rescored {n} candidate(s).")
                except Exception as exc:
                    st.error(str(exc))


def _render_sidebar(dept: Department) -> NavPage:
    st.markdown("### SCHEMA")
    st.caption(dept.display_name)

    page: NavPage = st.radio(
        "Navigate",
        ["Interview", "Cohort", "Configure"],
        index=["Interview", "Cohort", "Configure"].index(
            st.session_state.get("nav_page", "Interview")
        ),
        label_visibility="collapsed",
    )
    st.session_state.nav_page = page

    st.divider()
    st.session_state.show_scoring_details = st.toggle(
        "Show scoring details",
        value=st.session_state.get("show_scoring_details", False),
        help="Logit, pass %, and attribution — for leads who want the math.",
    )

    st.divider()
    if st.button("Switch department", use_container_width=True):
        st.session_state.pop("active_department_id", None)
        st.session_state.pop("feature_toggles", None)
        st.session_state.pop("rubric_draft_json", None)
        _invalidate_store_caches(st.session_state.get("sheets_store"))
        st.rerun()
    if st.button("Log out", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    return page


def main() -> None:
    if not _secrets_available():
        st.title("SCHEMA")
        st.error("Secrets missing. See docs/ADMIN_SETUP.md.")
        return

    if not _require_auth():
        return

    dept = _department_gate()
    if dept is None:
        return

    config = _load_active_config(dept)

    with st.sidebar:
        page = _render_sidebar(dept)

    if page == "Interview":
        render_live_interview(dept, config)
    elif page == "Cohort":
        render_cohort(dept, config)
    else:
        render_configure(dept, config)


if __name__ == "__main__":
    main()
