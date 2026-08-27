"""Google Sheets department-tab layout helpers (master tab is Sheet1 by default)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.departments import department_display_names

DEFAULT_MASTER_TAB = "Sheet1"

# Row 1 = spacer, row 2 = date banner, rows 3–4 = column headers, row 5+ = data
TEMPLATE_DATA_START_ROW = 5  # 1-based
TEMPLATE_HEADER_ROWS = 4

NAVY = "#1F497D"
DARK_BAR = "#2C333F"
STATUS_OPTIONS = ["Top-K Pass", "Review", "Fail", "Pending"]

ROW3_VALUES = [
    "INTERVIEW TIME",
    "NAME",
    "POSITION APPLICATIONS",
    "",
    "Meeting Link",
    "Notes",
    "STATUS",
]
ROW4_VALUES = ["", "", "1st Choice", "2nd Choice", "", "", ""]


def _rgb_hex(hex_color: str) -> dict[str, float]:
    h = hex_color.lstrip("#")
    return {
        "red": int(h[0:2], 16) / 255,
        "green": int(h[2:4], 16) / 255,
        "blue": int(h[4:6], 16) / 255,
    }


def format_date_banner(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return f"_{dt.strftime('%B')} {dt.day}, {dt.year}_"


def template_value_rows(term_label: str | None = None) -> list[list[str]]:
    """Four header rows written before formatting merges."""
    date_label = term_label or format_date_banner()
    return [
        [""] * 7,
        [date_label] + [""] * 6,
        list(ROW3_VALUES),
        list(ROW4_VALUES),
    ]


def find_data_start_row(values: list[list[str]]) -> int:
    """Return 1-based row index where candidate data begins."""
    for i, row in enumerate(values):
        if not row:
            continue
        if row[0].strip().upper() == "INTERVIEW TIME":
            if i + 1 < len(values):
                next_row = values[i + 1]
                if len(next_row) > 2 and str(next_row[2]).strip() == "1st Choice":
                    return i + 3  # 1-based: header at i+1, sub at i+2, data at i+3
            return i + 2
    return TEMPLATE_DATA_START_ROW


def is_template_formatted(values: list[list[str]]) -> bool:
    """Heuristic: row 3 has INTERVIEW TIME (4-row template layout)."""
    if len(values) < 3:
        return False
    row3 = values[2]
    return bool(row3 and row3[0].strip().upper() == "INTERVIEW TIME")


def build_format_requests(sheet_id: int, departments: list[str] | None = None) -> list[dict[str, Any]]:
    """Sheets API batchUpdate requests for template styling and validation."""
    departments = departments or department_display_names()
    navy = _rgb_hex(NAVY)
    dark = _rgb_hex(DARK_BAR)
    white = {"red": 1, "green": 1, "blue": 1}
    requests: list[dict[str, Any]] = []

    def repeat_cell(
        r0: int,
        r1: int,
        c0: int,
        c1: int,
        *,
        bg: dict | None = None,
        fg: dict | None = None,
        bold: bool = False,
        italic: bool = False,
        halign: str = "CENTER",
    ) -> dict:
        fields = []
        cell: dict[str, Any] = {}
        if bg:
            cell["userEnteredFormat"] = cell.get("userEnteredFormat", {})
            cell["userEnteredFormat"]["backgroundColor"] = bg
            fields.append("userEnteredFormat.backgroundColor")
        fmt: dict[str, Any] = {}
        if fg or bold or italic:
            fmt["textFormat"] = {}
            if fg:
                fmt["textFormat"]["foregroundColor"] = fg
            if bold:
                fmt["textFormat"]["bold"] = True
            if italic:
                fmt["textFormat"]["italic"] = True
            fields.append("userEnteredFormat.textFormat")
        if halign:
            fmt["horizontalAlignment"] = halign
            fields.append("userEnteredFormat.horizontalAlignment")
        if fmt:
            cell.setdefault("userEnteredFormat", {}).update(fmt)
        return {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": r0,
                    "endRowIndex": r1,
                    "startColumnIndex": c0,
                    "endColumnIndex": c1,
                },
                "cell": cell,
                "fields": ",".join(fields),
            }
        }

    # Row 1 spacer — dark bar
    requests.append(repeat_cell(0, 1, 0, 7, bg=dark))

    # Row 2 date banner
    requests.append(repeat_cell(1, 2, 0, 7, bg=dark, fg=white, bold=True, italic=True, halign="LEFT"))

    # Row 3–4 header block — navy
    requests.append(repeat_cell(2, 4, 0, 7, bg=navy, fg=white, bold=True))

    merges = [
        (2, 4, 0, 1),  # A3:A4
        (2, 4, 1, 2),  # B3:B4
        (2, 3, 2, 4),  # C3:D3 POSITION APPLICATIONS
        (2, 4, 4, 5),  # E3:E4
        (2, 4, 5, 6),  # F3:F4
        (2, 4, 6, 7),  # G3:G4
        (1, 2, 0, 7),  # A2:G2 date
    ]
    for r0, r1, c0, c1 in merges:
        requests.append(
            {
                "mergeCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": r0,
                        "endRowIndex": r1,
                        "startColumnIndex": c0,
                        "endColumnIndex": c1,
                    },
                    "mergeType": "MERGE_ALL",
                }
            }
        )

    dept_values = [{"userEnteredValue": d} for d in departments]
    status_values = [{"userEnteredValue": s} for s in STATUS_OPTIONS]

    # Data validation from row 5 (index 4) downward
    for col_index, options in ((2, dept_values), (3, dept_values), (6, status_values)):
        requests.append(
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 4,
                        "endRowIndex": 2000,
                        "startColumnIndex": col_index,
                        "endColumnIndex": col_index + 1,
                    },
                    "rule": {
                        "condition": {"type": "ONE_OF_LIST", "values": options},
                        "showCustomUi": True,
                        "strict": False,
                    },
                }
            }
        )

    # Column widths (approximate)
    widths = [140, 160, 130, 130, 180, 280, 110]
    for i, px in enumerate(widths):
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": i,
                        "endIndex": i + 1,
                    },
                    "properties": {"pixelSize": px},
                    "fields": "pixelSize",
                }
            }
        )

    return requests
