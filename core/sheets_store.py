"""Google Sheets source-of-truth store for SCHEMA."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

from core.config_loader import TrackConfig, config_hash, parse_config
from core.scoring_engine import assign_statuses, compute_candidate_score, generate_attribution_notes
from core.sheet_template import DEFAULT_MASTER_TAB, find_data_start_row, format_date_banner

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

FEATURES_TAB = "_SCHEMA_FEATURES"
RUBRICS_TAB = "_SCHEMA_RUBRICS"

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

T = TypeVar("T")


class SheetsStoreError(Exception):
    pass


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _row_matches_header(row: list[str], header: list[str]) -> bool:
    if not row:
        return False
    padded = row + [""] * max(0, len(header) - len(row))
    return padded[: len(header)] == header


def _sheet_has_content(values: list[list[str]]) -> bool:
    return bool(values and any(any(cell.strip() for cell in row) for row in values))


def _a1_range(row: int, col_count: int) -> str:
    return f"A1:{rowcol_to_a1(row, col_count)}"


def _ws_update(ws, rows: list[list[Any]], range_name: str) -> None:
    ws.update(rows, range_name=range_name, raw=False)


def _retry_api(fn: Callable[[], T], *, attempts: int = 4) -> T:
    """Retry Google API calls on 429 rate limit."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except gspread.exceptions.APIError as exc:
            last_exc = exc
            msg = str(exc)
            if "429" not in msg and "Quota exceeded" not in msg:
                raise
            if attempt >= attempts - 1:
                raise
            time.sleep(2**attempt + 1)
    raise last_exc  # type: ignore[misc]


def credentials_from_secrets(secrets: Any) -> Credentials:
    if "google_service_account" in secrets:
        info = dict(secrets["google_service_account"])
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


def master_tab_from_secrets(secrets: Any) -> str:
    if "template_tab" in secrets:
        name = str(secrets["template_tab"]).strip()
        if name:
            return name
    gs = secrets.get("google_sheets")
    if isinstance(gs, dict) and gs.get("template_tab"):
        return str(gs["template_tab"]).strip()
    return DEFAULT_MASTER_TAB


class SheetsStore:
    def __init__(
        self,
        spreadsheet_id: str,
        credentials: Credentials,
        *,
        master_tab_name: str = DEFAULT_MASTER_TAB,
    ):
        self.spreadsheet_id = spreadsheet_id
        self._master_tab_name = master_tab_name
        self._gc = gspread.authorize(credentials)
        self._ss = self._gc.open_by_key(spreadsheet_id)
        self._titles_cache: list[str] | None = None
        self._headers_ok: set[str] = set()
        self._features_table: list[list[str]] | None = None
        self._store_version = 3

    @classmethod
    def from_secrets(cls, secrets: Any) -> SheetsStore:
        creds = credentials_from_secrets(secrets)
        sid = spreadsheet_id_from_secrets(secrets)
        master_tab = master_tab_from_secrets(secrets)
        return cls(sid, creds, master_tab_name=master_tab)

    def invalidate_caches(self) -> None:
        self._features_table = None

    def invalidate_titles_cache(self) -> None:
        self._titles_cache = None

    def _sheet_titles(self) -> list[str]:
        if self._titles_cache is None:
            self._titles_cache = [ws.title for ws in _retry_api(lambda: self._ss.worksheets())]
        return self._titles_cache

    def _get_or_create_ws(self, title: str, rows: int = 1000, cols: int = 20):
        try:
            return _retry_api(lambda: self._ss.worksheet(title))
        except gspread.WorksheetNotFound:
            ws = _retry_api(lambda: self._ss.add_worksheet(title=title, rows=rows, cols=cols))
            self.invalidate_titles_cache()
            return ws

    def _get_master_tab(self) -> Any:
        try:
            return _retry_api(lambda: self._ss.worksheet(self._master_tab_name))
        except gspread.WorksheetNotFound as exc:
            raise SheetsStoreError(
                f"Master layout tab '{self._master_tab_name}' not found. "
                "Create it in your spreadsheet or set template_tab in secrets."
            ) from exc

    def _duplicate_department_tab(self, sheet_name: str) -> Any:
        if sheet_name == self._master_tab_name:
            raise SheetsStoreError(
                f"Department tab name cannot match the master layout tab '{self._master_tab_name}'."
            )
        master = self._get_master_tab()
        new_ws = _retry_api(lambda: master.duplicate(new_sheet_name=sheet_name))
        self.invalidate_titles_cache()
        date_label = format_date_banner()
        _retry_api(lambda: new_ws.update([[date_label]], range_name="A2", raw=False))
        return new_ws

    def ensure_department_tab(self, sheet_name: str):
        if sheet_name in self._sheet_titles():
            return _retry_api(lambda: self._ss.worksheet(sheet_name))
        ws = self._duplicate_department_tab(sheet_name)
        self._headers_ok.add(sheet_name)
        return ws

    def _ensure_single_row_header(self, ws, header: list[str], cache_key: str) -> None:
        if cache_key in self._headers_ok:
            return
        values = _retry_api(ws.get_all_values)
        if values and _row_matches_header(values[0], header):
            self._headers_ok.add(cache_key)
            return
        range_name = _a1_range(1, len(header))
        if not _sheet_has_content(values):
            _retry_api(lambda: _ws_update(ws, [header], range_name))
        else:
            _retry_api(lambda: ws.insert_row(header, index=1))
        self._headers_ok.add(cache_key)

    def ensure_features_tab(self):
        ws = self._get_or_create_ws(FEATURES_TAB, cols=len(FEATURES_HEADER))
        self._ensure_single_row_header(ws, FEATURES_HEADER, FEATURES_TAB)
        return ws

    def ensure_rubrics_tab(self):
        ws = self._get_or_create_ws(RUBRICS_TAB, cols=len(RUBRICS_HEADER))
        self._ensure_single_row_header(ws, RUBRICS_HEADER, RUBRICS_TAB)
        return ws

    def _load_features_table(self, *, force: bool = False) -> list[list[str]]:
        if self._features_table is not None and not force:
            return self._features_table
        ws = self.ensure_features_tab()
        self._features_table = _retry_api(ws.get_all_values)
        return self._features_table

    def _parse_feature_records(self, all_values: list[list[str]]) -> list[dict[str, Any]]:
        if len(all_values) < 2:
            return []
        header = all_values[0]
        records = []
        for row in all_values[1:]:
            padded = row + [""] * max(0, len(header) - len(row))
            records.append(dict(zip(header, padded)))
        return records

    # ---- rubrics ----

    def load_rubric_override(self, department_display: str) -> TrackConfig | None:
        ws = self.ensure_rubrics_tab()
        records = _retry_api(ws.get_all_records)
        for row in records:
            if str(row.get("department", "")).strip() == department_display:
                raw = row.get("rubric_json", "")
                if raw:
                    return parse_config(raw if isinstance(raw, dict) else json.loads(raw))
        return None

    def save_rubric_override(self, department_display: str, config: TrackConfig) -> None:
        ws = self.ensure_rubrics_tab()
        records = _retry_api(ws.get_all_records)
        payload = json.dumps(config.to_dict())
        updated_at = _utcnow_iso()
        for idx, row in enumerate(records, start=2):
            if str(row.get("department", "")).strip() == department_display:
                _retry_api(
                    lambda idx=idx: _ws_update(
                        ws,
                        [[department_display, updated_at, payload]],
                        f"A{idx}:C{idx}",
                    )
                )
                return
        _retry_api(
            lambda: ws.append_row(
                [department_display, updated_at, payload],
                value_input_option="USER_ENTERED",
            )
        )

    # ---- candidates ----

    def count_department_candidates(self, department_display: str) -> int:
        all_values = self._load_features_table()
        records = self._parse_feature_records(all_values)
        return sum(1 for r in records if str(r.get("department", "")).strip() == department_display)

    def list_feature_rows(self, department_display: str, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        all_values = self._load_features_table(force=force_refresh)
        records = self._parse_feature_records(all_values)
        return [r for r in records if str(r.get("department", "")).strip() == department_display]

    def list_cohort(self, department_display: str) -> list[dict[str, Any]]:
        feat_rows = self.list_feature_rows(department_display, force_refresh=True)
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
                    "notes": row.get("notes", "") or row.get("qualitative_notes", ""),
                    "status": row.get("status", ""),
                    "logit": logit,
                    "probability": prob,
                    "features_json": row.get("features_json", "{}"),
                    "qualitative_notes": row.get("qualitative_notes", ""),
                    "rubric_hash": row.get("rubric_hash", ""),
                }
            )

        try:
            dept_ws = self.ensure_department_tab(department_display)
            dept_values = _retry_api(dept_ws.get_all_values)
            data_start = find_data_start_row(dept_values)
            note_by_key: dict[tuple[str, str], str] = {}
            status_by_key: dict[tuple[str, str], str] = {}
            for r in dept_values[data_start - 1 :]:
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
        interview_time = _utcnow_iso()
        candidate_key = str(uuid.uuid4())
        r_hash = config_hash(config)
        temp_status = "Pending"

        dept_ws = self.ensure_department_tab(department_display)
        feat_ws = self.ensure_features_tab()

        _retry_api(
            lambda: dept_ws.append_row(
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
        )

        _retry_api(
            lambda: feat_ws.append_row(
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
        )

        self.invalidate_caches()
        all_values = self._load_features_table(force=True)

        statuses = self.recalculate_ranks(
            department_display,
            top_k=config.model_parameters.top_k_slots,
            pass_threshold=config.model_parameters.pass_threshold_probability,
            feat_values=all_values,
        )

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
        feat_values: list[list[str]] | None = None,
    ) -> dict[str, str]:
        feat_ws = self.ensure_features_tab()
        all_values = feat_values if feat_values is not None else self._load_features_table(force=True)
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

        status_col = col("status") + 1
        cells = []
        for j, i in enumerate(dept_indices):
            sheet_row = i + 2
            cells.append(gspread.Cell(sheet_row, status_col, new_statuses[j]))
        if cells:
            _retry_api(lambda: feat_ws.update_cells(cells))

        lookup: dict[tuple[str, str], str] = {}
        for j, i in enumerate(dept_indices):
            r = rows[i]
            lookup[(r[col("interview_time")], r[col("name")])] = new_statuses[j]

        dept_ws = self.ensure_department_tab(department_display)
        dept_vals = _retry_api(dept_ws.get_all_values)
        data_start = find_data_start_row(dept_vals)
        if len(dept_vals) >= data_start:
            updates = []
            for sheet_row_idx, r in enumerate(dept_vals[data_start - 1 :], start=data_start):
                if len(r) < 2:
                    continue
                key = (r[0], r[1])
                if key in lookup:
                    updates.append(gspread.Cell(sheet_row_idx, 7, lookup[key]))
            if updates:
                _retry_api(lambda: dept_ws.update_cells(updates))

        self.invalidate_caches()
        return key_to_status

    def rescore_department(self, department_display: str, config: TrackConfig) -> int:
        feat_ws = self.ensure_features_tab()
        all_values = self._load_features_table(force=True)
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
            _retry_api(lambda: feat_ws.update_cells(cells))

        dept_ws = self.ensure_department_tab(department_display)
        dept_vals = _retry_api(dept_ws.get_all_values)
        data_start = find_data_start_row(dept_vals)
        note_cells = []
        for sheet_row_idx, r in enumerate(dept_vals[data_start - 1 :], start=data_start):
            if len(r) < 2:
                continue
            key = (r[0], r[1])
            if key in note_updates:
                note_cells.append(gspread.Cell(sheet_row_idx, 6, note_updates[key]))
        if note_cells:
            _retry_api(lambda: dept_ws.update_cells(note_cells))

        self.invalidate_caches()
        all_values = self._load_features_table(force=True)
        self.recalculate_ranks(
            department_display,
            top_k=config.model_parameters.top_k_slots,
            pass_threshold=config.model_parameters.pass_threshold_probability,
            feat_values=all_values,
        )
        return count
