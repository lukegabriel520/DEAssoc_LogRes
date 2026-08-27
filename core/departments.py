"""Department registry helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
RUBRICS_DIR = CONFIG_DIR / "rubrics"
DEPARTMENTS_PATH = CONFIG_DIR / "departments.json"


@dataclass(frozen=True)
class Department:
    id: str
    display_name: str
    sheet_name: str
    rubric_file: str

    @property
    def rubric_path(self) -> Path:
        return RUBRICS_DIR / self.rubric_file


@lru_cache(maxsize=1)
def load_departments() -> list[Department]:
    raw = json.loads(DEPARTMENTS_PATH.read_text(encoding="utf-8"))
    departments = [
        Department(
            id=item["id"],
            display_name=item["display_name"],
            sheet_name=item["sheet_name"],
            rubric_file=item["rubric_file"],
        )
        for item in raw["departments"]
    ]
    validate_departments(departments)
    return departments


def validate_departments(
    departments: list[Department],
    *,
    master_tab_name: str | None = None,
) -> None:
    """Validate identifiers and files that control Google worksheet routing."""
    errors: list[str] = []
    for field_name in ("id", "display_name", "sheet_name"):
        values = [str(getattr(dept, field_name)).strip() for dept in departments]
        blanks = [index + 1 for index, value in enumerate(values) if not value]
        if blanks:
            errors.append(f"blank {field_name} at department entries {blanks}")
        if len(values) != len({value.casefold() for value in values}):
            errors.append(f"duplicate department {field_name}")

    missing_rubrics = [
        dept.rubric_file for dept in departments if not dept.rubric_path.is_file()
    ]
    if missing_rubrics:
        errors.append(f"missing rubric files: {', '.join(sorted(missing_rubrics))}")

    if master_tab_name:
        conflicts = [
            dept.display_name
            for dept in departments
            if dept.sheet_name.strip().casefold() == master_tab_name.strip().casefold()
        ]
        if conflicts:
            errors.append(
                f"template_tab conflicts with department sheet: {', '.join(conflicts)}"
            )

    if errors:
        raise ValueError("Invalid config/departments.json: " + "; ".join(errors))


def get_department(dept_id: str) -> Department:
    for dept in load_departments():
        if dept.id == dept_id:
            return dept
    raise KeyError(f"Unknown department id: {dept_id}")


def get_department_by_sheet_name(sheet_name: str) -> Department | None:
    for dept in load_departments():
        if dept.sheet_name == sheet_name:
            return dept
    return None


def department_display_names() -> list[str]:
    return [d.display_name for d in load_departments()]
