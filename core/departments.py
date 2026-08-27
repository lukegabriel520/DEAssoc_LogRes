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
    return [
        Department(
            id=item["id"],
            display_name=item["display_name"],
            sheet_name=item["sheet_name"],
            rubric_file=item["rubric_file"],
        )
        for item in raw["departments"]
    ]


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
