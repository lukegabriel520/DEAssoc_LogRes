"""Pydantic v2 rubric configuration loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from core.departments import RUBRICS_DIR, Department, get_department


class ModelParameters(BaseModel):
    beta_0: float = -2.0
    top_k_slots: int = Field(default=5, ge=1)
    pass_threshold_probability: float = Field(default=0.65, ge=0.0, le=1.0)


class Question(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    pass_criteria: str = Field(min_length=1)
    fail_criteria: str = Field(min_length=1)
    weight: float

    @field_validator("weight")
    @classmethod
    def weight_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("weight must be strictly positive (w_i > 0)")
        return value


class Section(BaseModel):
    section_id: str
    title: str
    allocated_time_minutes: int = Field(ge=1)
    questions: list[Question] = Field(min_length=1)


class TrackConfig(BaseModel):
    system_title: str
    department: str
    term: str
    model_parameters: ModelParameters
    sections: list[Section] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_question_ids(self) -> TrackConfig:
        ids = [q.id for s in self.sections for q in s.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("question ids must be unique across the rubric")
        return self

    def all_questions(self) -> list[Question]:
        return [q for section in self.sections for q in section.questions]

    def feature_weight_map(self) -> dict[str, float]:
        return {q.id: q.weight for q in self.all_questions()}

    def label_map(self) -> dict[str, str]:
        return {q.id: q.label for q in self.all_questions()}

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


_DEFAULT_DE_PATH = RUBRICS_DIR / "data_engineering.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_config(data: dict[str, Any] | str) -> TrackConfig:
    if isinstance(data, str):
        data = json.loads(data)
    return TrackConfig.model_validate(data)


def load_config_from_path(path: Path) -> TrackConfig:
    try:
        return parse_config(_read_json(path))
    except Exception:
        if _DEFAULT_DE_PATH.exists():
            return parse_config(_read_json(_DEFAULT_DE_PATH))
        raise


def load_department_rubric(department: Department | str) -> TrackConfig:
    dept = get_department(department) if isinstance(department, str) else department
    path = dept.rubric_path
    if not path.exists():
        return load_config_from_path(_DEFAULT_DE_PATH)
    return load_config_from_path(path)


def config_hash(config: TrackConfig) -> str:
    payload = json.dumps(config.to_dict(), sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
