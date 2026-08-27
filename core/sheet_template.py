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


def find_header_row(values: list[list[str]]) -> int | None:
    """Return the 1-based row containing the main department header."""
    for row_index, row in enumerate(values, start=1):
        if row and str(row[0]).strip().upper() == "INTERVIEW TIME":
            return row_index
    return None


def header_repair_insertions(values: list[list[str]]) -> list[tuple[int, list[list[str]]]]:
    """Describe non-destructive row insertions needed for the canonical header."""
    if is_template_formatted(values):
        return []

    header_row = find_header_row(values)
    canonical = template_value_rows()
    if header_row is None or header_row > 3:
        return [(1, canonical)]

    insertions: list[tuple[int, list[list[str]]]] = []
    leading_rows = 3 - header_row
    if leading_rows:
        insertions.append((1, canonical[:leading_rows]))

    subheader_index = header_row  # zero-based index of the row after the header
    has_subheader = (
        subheader_index < len(values)
        and len(values[subheader_index]) > 2
        and str(values[subheader_index][2]).strip() == "1st Choice"
    )
    if not has_subheader:
        insertions.append((4, [list(ROW4_VALUES)]))
    return insertions


def find_data_start_row(values: list[list[str]]) -> int:
    """Return 1-based row index where candidate data begins."""
    header_row = find_header_row(values)
    if header_row is not None:
        next_index = header_row
        if next_index < len(values):
            next_row = values[next_index]
            if len(next_row) > 2 and str(next_row[2]).strip() == "1st Choice":
                return header_row + 2
        return header_row + 1
    return TEMPLATE_DATA_START_ROW


def find_next_data_row(values: list[list[str]]) -> int:
    """Return 1-based row index for the next candidate (below header block)."""
    data_start = find_data_start_row(values)
    if len(values) < data_start:
        return data_start
    last_occupied = data_start - 1
    for sheet_row_idx, row in enumerate(values[data_start - 1 :], start=data_start):
        padded = row + [""] * max(0, 7 - len(row))
        if padded[0].strip() or padded[1].strip():
            last_occupied = sheet_row_idx
    return last_occupied + 1


def is_data_row(row: list[str]) -> bool:
    """True if row looks like a candidate record (has interview time or name)."""
    padded = row + [""] * max(0, 7 - len(row))
    return bool(padded[0].strip() or padded[1].strip())

def is_template_formatted(values: list[list[str]]) -> bool:
    """True when rows 3–4 contain the canonical two-level header."""
    if len(values) < 4:
        return False
    row3 = values[2]
    row4 = values[3]
    return bool(
        row3
        and str(row3[0]).strip().upper() == "INTERVIEW TIME"
        and len(row4) > 2
        and str(row4[2]).strip() == "1st Choice"
    )


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
