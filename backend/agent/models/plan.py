# backend/agent/models/plan.py
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class SceneModel(BaseModel):
    id: str
    duration_seconds: float
    voiceover_text: str
    code_plan: str | None = None  # per-scene coding notes (replaces "notes")
    language: str | None = None  # ISO-ish code like "en", "es", "fr" (optional)


class PlanModel(BaseModel):
    title: str
    description: str
    contexts: list[str] = Field(default_factory=list)  # RAG hints at top level
    scenes: list[SceneModel]
    code_plan: str | None = None  # global coding notes (replaces "notes")


def validate_plan_obj(plan_obj: Any) -> PlanModel:
    if not isinstance(plan_obj, dict):
        raise ValidationError(
            [{"loc": ("plan",), "msg": "plan must be a dict", "type": "type_error"}],
            PlanModel,
        )
    return PlanModel.parse_obj(plan_obj)


def try_validate_plan(plan_obj: Any) -> dict[str, Any]:
    try:
        model = validate_plan_obj(plan_obj)
        return {"plan": model, "error": None}
    except ValidationError as e:
        return {"plan": None, "error": str(e)}
