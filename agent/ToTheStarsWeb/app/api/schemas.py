from typing import Literal
from pydantic import BaseModel, Field

class QuestCreate(BaseModel):
    title: str
    description: str = ""
    difficulty: Literal["A", "B", "C", "D"]
    category: str = "未分类"
    is_required: bool = False
    is_recurring: bool = False
    assigned_date: str | None = None

class QuestUpdate(BaseModel):
    title: str
    description: str = ""
    difficulty: Literal["A", "B", "C", "D"]
    category: str = "未分类"
    is_required: bool = False
    is_recurring: bool = False

class CompleteRequest(BaseModel):
    completed: bool

class QuestBatchRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)

class DateRequest(BaseModel):
    date: str | None = None

class LegendCreate(BaseModel):
    title: str
    content: str = ""
    difficulty: Literal["A", "B", "C", "D"]
    deadline: str
    indicators: list[str] = []

class LegendUpdate(BaseModel):
    title: str
    content: str = ""
    difficulty: Literal["A", "B", "C", "D"]
    deadline: str

class IndicatorCreate(BaseModel):
    title: str
    description: str = ""

class RewardCreate(BaseModel):
    name: str
    content: str = ""
    point_type: Literal["practice", "growth"]
    price: float = Field(gt=0)
    stock: int = Field(ge=0)

class RewardUpdate(RewardCreate):
    pass

class StateSave(BaseModel):
    journal_title: str = Field(min_length=1, max_length=20)
    rating: int = Field(ge=1, le=5)
    emotions: list[str] = []
    social_type: str
    social_feeling: int = Field(ge=-2, le=2)
    energy: int = Field(ge=-2, le=2)
    review_text: str = Field(default="", max_length=10000)

class ImageOrder(BaseModel):
    images: list[str] = Field(max_length=6)

class VacationRange(BaseModel):
    start_date: str
    end_date: str
    reason: str = ""


class SchedulePlanCreate(BaseModel):
    plan_date: str | None = None
    title: str = ""
    content: str = ""
    start: str
    end: str
    quest_id: int | None = None


class SchedulePlanUpdate(BaseModel):
    title: str = ""
    content: str = ""
    start: str
    end: str
    plan_date: str | None = None


class FocusSessionCreate(BaseModel):
    started_at: str
    ended_at: str
    planned_minutes: int = Field(ge=1, le=240)
    duration_seconds: int = Field(gt=0, le=24 * 60 * 60)
    category: str = "未分类"
    description: str = ""
