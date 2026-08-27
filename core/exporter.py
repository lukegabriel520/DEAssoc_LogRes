"""Local OpenPyXL / CSV export for department cohorts."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F497D")
HEADER_FONT = Font(color="FFFFFF", bold=True)
STRIPE_FILL = PatternFill("solid", fgColor="F2F2F2")
STATUS_FILLS = {
    "Top-K Pass": PatternFill("solid", fgColor="C6EFCE"),
    "Review": PatternFill("solid", fgColor="FFEB9C"),
    "Fail": PatternFill("solid", fgColor="FFC7CE"),
}


def cohort_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    records = []
    for row in rows:
        records.append(
            {
                "INTERVIEW TIME": row.get("interview_time", ""),
                "NAME": row.get("name", ""),
                "1st Choice": row.get("first_choice", ""),
                "2nd Choice": row.get("second_choice", ""),
                "Meeting Link": row.get("meeting_link", "N/A"),
                "Notes": row.get("notes", ""),
                "STATUS": row.get("status", ""),
            }
        )
    return pd.DataFrame(records)


def export_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    df = cohort_to_dataframe(rows)
    return df.to_csv(index=False).encode("utf-8")


def export_xlsx_bytes(rows: list[dict[str, Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cohort"

    # Two-row header matching Google Sheets layout
    ws.merge_cells("A1:A2")
    ws.merge_cells("B1:B2")
    ws.merge_cells("C1:D1")
    ws.merge_cells("E1:E2")
    ws.merge_cells("F1:F2")
    ws.merge_cells("G1:G2")

    headers_r1 = [
        ("A1", "INTERVIEW TIME"),
        ("B1", "NAME"),
        ("C1", "POSITION APPLICATIONS"),
        ("E1", "Meeting Link"),
        ("F1", "Notes"),
        ("G1", "STATUS"),
    ]
    for cell_ref, value in headers_r1:
        cell = ws[cell_ref]
        cell.value = value
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws["C2"] = "1st Choice"
    ws["D2"] = "2nd Choice"
    for col in ("C", "D"):
        cell = ws[f"{col}2"]
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for idx, row in enumerate(rows, start=3):
        values = [
            row.get("interview_time", ""),
            row.get("name", ""),
            row.get("first_choice", ""),
            row.get("second_choice", ""),
            row.get("meeting_link", "N/A"),
            row.get("notes", ""),
            row.get("status", ""),
        ]
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=idx, column=col_idx, value=value)
            if idx % 2 == 1:
                cell.fill = STRIPE_FILL
            if col_idx == 7:
                status_fill = STATUS_FILLS.get(str(value))
                if status_fill:
                    cell.fill = status_fill

    for col_idx in range(1, 8):
        letter = get_column_letter(col_idx)
        max_len = 12
        for cell in ws[letter]:
            if cell.value is not None:
                max_len = max(max_len, min(len(str(cell.value)), 60))
        ws.column_dimensions[letter].width = max_len + 2

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
