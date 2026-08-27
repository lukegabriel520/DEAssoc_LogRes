"""Google Sheets source-of-truth store for SCHEMA."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from core.config_loader import TrackConfig, config_hash, parse_config
from core.scoring_engine import assign_statuses, compute_candidate_score, generate_attribution_notes

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

FEATURES_TAB = "_SCHEMA_FEATURES"
RUBRICS_TAB = "_SCHEMA_RUBRICS"

DEPT_HEADER_ROW1 = [
    "INTERVIEW TIME",
    "NAME",
    "POSITION APPLICATIONS",
    "",
    "Meeting Link",
    "Notes",
    "STATUS",
]
DEPT_HEADER_ROW2 = ["", "", "1st Choice", "2nd Choice", "", "", ""]

FEATURES_HEADER = [
    "department",
    "candidate_key",
    "interview_time",
    "name",
    "first_choice",
    "second_choice",
    "meeting_link",
    "features_json",
    "logit",
    "probability",
    "status",
    "rubric_hash",
    "qualitative_notes",
]

RUBRICS_HEADER = ["department", "updated_at", "rubric_json"]


class SheetsStoreError(Exception):
    pass


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def credentials_from_secrets(secrets: Any) -> Credentials:
    """Build credentials from Streamlit secrets or mapping."""
    if "google_service_account" in secrets:
        info = dict(secrets["google_service_account"])
        # private_key may contain literal \n in TOML
        if "private_key" in info and isinstance(info["private_key"], str):
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        return Credentials.from_service_account_info(info, scopes=SCOPES)

    path = secrets.get("google_sheets", {}).get("service_account_file")
    if path:
        return Credentials.from_service_account_file(path, scopes=SCOPES)

    raise SheetsStoreError(
        "Missing Google credentials. Set [google_service_account] in secrets "
        "or google_sheets.service_account_file."
    )


def spreadsheet_id_from_secrets(secrets: Any) -> str:
    if "spreadsheet_id" in secrets:
        return str(secrets["spreadsheet_id"])
    if "google_sheets" in secrets and "spreadsheet_id" in secrets["google_sheets"]:
        return str(secrets["google_sheets"]["spreadsheet_id"])
    raise SheetsStoreError("Missing spreadsheet_id in secrets.")


class SheetsStore:
    def __init__(self, spreadsheet_id: str, credentials: Credentials):
        self.spreadsheet_id = spreadsheet_id
        self._gc = gspread.authorize(credentials)
        self._ss = self._gc.open_by_key(spreadsheet_id)

    @classmethod
    def from_secrets(cls, secrets: Any) -> SheetsStore:
        creds = credentials_from_secrets(secrets)
        sid = spreadsheet_id_from_secrets(secrets)
        return cls(sid, creds)

    # ---- worksheet helpers ----

    def _get_or_create_ws(self, title: str, rows: int = 1000, cols: int = 20):
        try:
            return self._ss.worksheet(title)
        except gspread.WorksheetNotFound:
            return self._ss.add_worksheet(title=title, rows=rows, cols=cols)

    def ensure_department_tab(self, sheet_name: str):
        """Create/rename tab and stamp exact 2-row header if missing."""
        existing_titles = [ws.title for ws in self._ss.worksheets()]

        if sheet_name in existing_titles:
            ws = self._ss.worksheet(sheet_name)
        else:
            # Prefer renaming a blank default Sheet1 when it is unused
            default_candidates = [t for t in existing_titles if re.fullmatch(r"Sheet\d*", t)]
            renamed = False
            for title in default_candidates:
                ws = self._ss.worksheet(title)
                values = ws.get_all_values()
                nonempty = any(any(cell.strip() for cell in row) for row in values)
                if not nonempty:
                    ws.update_title(sheet_name)
                    renamed = True
                    break
            if not renamed:
                ws = self._ss.add_worksheet(title=sheet_name, rows=1000, cols=10)

        self._ensure_dept_header(ws)
        return ws

    def _ensure_dept_header(self, ws) -> None:
        values = ws.get_all_values()
        needs_header = True
        if len(values) >= 2:
            r1 = values[0]
            if r1 and r1[0].strip().upper() == "INTERVIEW TIME":
                needs_header = False
        if needs_header:
            # Prepend header by inserting rows if data already exists without header
            if values and any(any(c.strip() for c in row) for row in values):
                ws.insert_rows([[], []], row=1)
            ws.update("A1:G2", [DEPT_HEADER_ROW1, DEPT_HEADER_ROW2], raw=False)
            try:
                ws.merge_cells("C1:D1")
                ws.merge_cells("A1:A2")
                ws.merge_cells("B1:B2")
                ws.merge_cells("E1:E2")
                ws.merge_cells("F1:F2")
                ws.merge_cells("G1:G2")
            except Exception:
                pass

    def ensure_features_tab(self):
        ws = self._get_or_create_ws(FEATURES_TAB, cols=len(FEATURES_HEADER))
        values = ws.get_all_values()
        if not values or values[0][: len(FEATURES_HEADER)] != FEATURES_HEADER:
            if not values:
                ws.update("A1", [FEATURES_HEADER], raw=False)
            elif values[0][0] != FEATURES_HEADER[0]:
                ws.insert_row(FEATURES_HEADER, index=1)
        return ws

    def ensure_rubrics_tab(self):
        ws = self._get_or_create_ws(RUBRICS_TAB, cols=len(RUBRICS_HEADER))
        values = ws.get_all_values()
        if not values or values[0][: len(RUBRICS_HEADER)] != RUBRICS_HEADER:
            if not values:
                ws.update("A1", [RUBRICS_HEADER], raw=False)
            elif values[0][0] != RUBRICS_HEADER[0]:
                ws.insert_row(RUBRICS_HEADER, index=1)
        return ws

    # ---- rubrics ----

    def load_rubric_override(self, department_display: str) -> TrackConfig | None:
        ws = self.ensure_rubrics_tab()
        records = ws.get_all_records()
        for row in records:
            if str(row.get("department", "")).strip() == department_display:
                raw = row.get("rubric_json", "")
                if raw:
                    return parse_config(raw if isinstance(raw, dict) else json.loads(raw))
        return None

    def save_rubric_override(self, department_display: str, config: TrackConfig) -> None:
        ws = self.ensure_rubrics_tab()
        records = ws.get_all_records()
        payload = json.dumps(config.to_dict())
        updated_at = _utcnow_iso()
        for idx, row in enumerate(records, start=2):
            if str(row.get("department", "")).strip() == department_display:
                ws.update(
                    f"A{idx}:C{idx}",
                    [[department_display, updated_at, payload]],
                    raw=False,
                )
                return
        ws.append_row([department_display, updated_at, payload], value_input_option="USER_ENTERED")

    # ---- candidates ----

    def next_candidate_number(self, department_display: str) -> str:
        rows = self.list_feature_rows(department_display)
        return f"Candidate #{len(rows) + 1:02d}"

    def list_feature_rows(self, department_display: str) -> list[dict[str, Any]]:
        ws = self.ensure_features_tab()
        records = ws.get_all_records()
        out = []
        for row in records:
            if str(row.get("department", "")).strip() == department_display:
                out.append(row)
        return out

    def list_cohort(self, department_display: str) -> list[dict[str, Any]]:
        """Merge dept-facing fields with feature meta, sorted by probability desc."""
        feat_rows = self.list_feature_rows(department_display)
        cohort = []
        for row in feat_rows:
            try:
                prob = float(row.get("probability") or 0)
            except (TypeError, ValueError):
                prob = 0.0
            try:
                logit = float(row.get("logit") or 0)
            except (TypeError, ValueError):
                logit = 0.0
            cohort.append(
                {
                    "candidate_key": row.get("candidate_key", ""),
                    "interview_time": row.get("interview_time", ""),
                    "name": row.get("name", ""),
                    "first_choice": row.get("first_choice", ""),
                    "second_choice": row.get("second_choice", ""),
                    "meeting_link": row.get("meeting_link", "N/A"),
                    "notes": "",  # filled from dept tab when available
                    "status": row.get("status", ""),
                    "logit": logit,
                    "probability": prob,
                    "features_json": row.get("features_json", "{}"),
                    "qualitative_notes": row.get("qualitative_notes", ""),
                    "rubric_hash": row.get("rubric_hash", ""),
                }
            )

        # Overlay Notes from department tab by matching name+time when possible
        try:
            dept_ws = self.ensure_department_tab(department_display)
            dept_values = dept_ws.get_all_values()
            data_rows = dept_values[2:] if len(dept_values) >= 2 else []
            note_by_key: dict[tuple[str, str], str] = {}
            status_by_key: dict[tuple[str, str], str] = {}
            for r in data_rows:
                if len(r) < 7:
                    r = r + [""] * (7 - len(r))
                note_by_key[(r[0], r[1])] = r[5]
                status_by_key[(r[0], r[1])] = r[6]
            for item in cohort:
                key = (item["interview_time"], item["name"])
                if key in note_by_key:
                    item["notes"] = note_by_key[key]
                if key in status_by_key and status_by_key[key]:
                    item["status"] = status_by_key[key]
        except Exception:
            pass

        cohort.sort(key=lambda x: x["probability"], reverse=True)
        return cohort

    def submit_candidate(
        self,
        *,
        department_display: str,
        name: str,
        first_choice: str,
        second_choice: str,
        meeting_link: str,
        qualitative_notes: str,
        features: dict[str, int],
        config: TrackConfig,
        notes_text: str,
        score_logit: float,
        score_probability: float,
    ) -> dict[str, Any]:
        """Append to dept tab + features tab, then re-rank STATUS. Returns candidate record."""
        interview_time = _utcnow_iso()
        candidate_key = str(uuid.uuid4())
        r_hash = config_hash(config)

        dept_ws = self.ensure_department_tab(department_display)
        feat_ws = self.ensure_features_tab()

        # Temporary status; re-rank overwrites
        temp_status = "Pending"

        dept_ws.append_row(
            [
                interview_time,
                name,
                first_choice,
                second_choice,
                meeting_link,
                notes_text,
                temp_status,
            ],
            value_input_option="USER_ENTERED",
        )

        feat_ws.append_row(
            [
                department_display,
                candidate_key,
                interview_time,
                name,
                first_choice,
                second_choice,
                meeting_link,
                json.dumps(features),
                f"{score_logit:.6f}",
                f"{score_probability:.6f}",
                temp_status,
                r_hash,
                qualitative_notes,
            ],
            value_input_option="USER_ENTERED",
        )

        statuses = self.recalculate_ranks(
            department_display,
            top_k=config.model_parameters.top_k_slots,
            pass_threshold=config.model_parameters.pass_threshold_probability,
        )

        # Find this candidate's final status
        final_status = statuses.get(candidate_key, temp_status)
        return {
            "candidate_key": candidate_key,
            "interview_time": interview_time,
            "name": name,
            "status": final_status,
            "probability": score_probability,
            "logit": score_logit,
        }

    def recalculate_ranks(
        self,
        department_display: str,
        top_k: int,
        pass_threshold: float,
    ) -> dict[str, str]:
        """Recompute STATUS for all candidates in department. Returns key->status map."""
        feat_ws = self.ensure_features_tab()
        all_values = feat_ws.get_all_values()
        if len(all_values) < 2:
            return {}

        header = all_values[0]
        rows = all_values[1:]

        def col(name: str) -> int:
            return header.index(name)

        dept_indices = [
            i
            for i, r in enumerate(rows)
            if len(r) > col("department") and r[col("department")].strip() == department_display
        ]
        if not dept_indices:
            return {}

        probs: list[float] = []
        keys: list[str] = []
        for i in dept_indices:
            r = rows[i]
            try:
                probs.append(float(r[col("probability")]))
            except (ValueError, IndexError):
                probs.append(0.0)
            keys.append(r[col("candidate_key")] if len(r) > col("candidate_key") else "")

        new_statuses = assign_statuses(probs, top_k=top_k, pass_threshold=pass_threshold)
        key_to_status = {keys[j]: new_statuses[j] for j in range(len(keys))}

        # Batch update STATUS in features tab
        status_col = col("status") + 1  # 1-based
        cells = []
        for j, i in enumerate(dept_indices):
            sheet_row = i + 2  # header offset
            cells.append(gspread.Cell(sheet_row, status_col, new_statuses[j]))
        if cells:
            feat_ws.update_cells(cells)

        # Update STATUS column on department human tab (match by interview_time + name)
        dept_ws = self.ensure_department_tab(department_display)
        dept_vals = dept_ws.get_all_values()
        if len(dept_vals) >= 3:
            # Build lookup from features
            lookup: dict[tuple[str, str], str] = {}
            for j, i in enumerate(dept_indices):
                r = rows[i]
                t = r[col("interview_time")]
                n = r[col("name")]
                lookup[(t, n)] = new_statuses[j]

            updates = []
            for sheet_row_idx, r in enumerate(dept_vals[2:], start=3):
                if len(r) < 2:
                    continue
                key = (r[0], r[1])
                if key in lookup:
                    updates.append(gspread.Cell(sheet_row_idx, 7, lookup[key]))
            if updates:
                dept_ws.update_cells(updates)

        return key_to_status

    def rescore_department(self, department_display: str, config: TrackConfig) -> int:
        """Recompute logit/probability/notes from stored features; then re-rank. Returns count."""
        feat_ws = self.ensure_features_tab()
        all_values = feat_ws.get_all_values()
        if len(all_values) < 2:
            return 0

        header = all_values[0]
        rows = all_values[1:]

        def col(name: str) -> int:
            return header.index(name)

        count = 0
        r_hash = config_hash(config)
        cells: list[gspread.Cell] = []
        note_updates: dict[tuple[str, str], str] = {}

        for i, r in enumerate(rows):
            if len(r) <= col("department") or r[col("department")].strip() != department_display:
                continue
            try:
                features = json.loads(r[col("features_json")] or "{}")
            except json.JSONDecodeError:
                features = {}
            qualitative = r[col("qualitative_notes")] if len(r) > col("qualitative_notes") else ""
            score = compute_candidate_score(features, config)
            notes = generate_attribution_notes(features, qualitative, config, score=score)
            sheet_row = i + 2
            cells.append(gspread.Cell(sheet_row, col("logit") + 1, f"{score.logit:.6f}"))
            cells.append(gspread.Cell(sheet_row, col("probability") + 1, f"{score.probability:.6f}"))
            cells.append(gspread.Cell(sheet_row, col("rubric_hash") + 1, r_hash))
            note_updates[(r[col("interview_time")], r[col("name")])] = notes
            count += 1

        if cells:
            feat_ws.update_cells(cells)

        # Update Notes on dept tab
        dept_ws = self.ensure_department_tab(department_display)
        dept_vals = dept_ws.get_all_values()
        note_cells = []
        for sheet_row_idx, r in enumerate(dept_vals[2:], start=3):
            if len(r) < 2:
                continue
            key = (r[0], r[1])
            if key in note_updates:
                note_cells.append(gspread.Cell(sheet_row_idx, 6, note_updates[key]))
        if note_cells:
            dept_ws.update_cells(note_cells)

        self.recalculate_ranks(
            department_display,
            top_k=config.model_parameters.top_k_slots,
            pass_threshold=config.model_parameters.pass_threshold_probability,
        )
        return count
