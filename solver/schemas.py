"""Shared question and answer shapes used by the reader, answer helper, click planner, and checker."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    SINGLE_SELECT = "single_select"
    TEXT_ENTRY = "text_entry"
    UNSUPPORTED = "unsupported"


class QuestionSource(str, Enum):
    DOM = "dom"
    VISION = "vision"


class AnswerOption(BaseModel):
    option_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    # Hint for finding the control on the page (visible name / value / number).
    control_hint: str = ""


class Question(BaseModel):
    question_id: Optional[str] = None
    text: str = Field(..., min_length=1)
    options: list[AnswerOption] = Field(default_factory=list)
    question_type: QuestionType = QuestionType.MULTIPLE_CHOICE
    # True when the question needs MORE than one choice picked
    # ("choose three", "select all that apply"). Answered by picking each
    # choice in turn, then submitting once.
    multi_answer: bool = False
    # Exact number to pick when stated ("choose two" -> 2). None when the
    # question leaves the count open ("select all that apply").
    required_count: Optional[int] = None
    context: Optional[str] = None
    source: QuestionSource = QuestionSource.DOM
    page_url: str = ""


class AnswerStatus(str, Enum):
    ANSWERED = "answered"
    UNRESOLVED = "unresolved"


class AnswerCandidate(BaseModel):
    selected_option_id: Optional[str] = None
    # Questions needing several answers ("choose two"): two or more choice names.
    selected_option_ids: list[str] = Field(default_factory=list)
    text_answer: Optional[str] = None
    explanation: Optional[str] = None
    confidence: Optional[float] = None
    status: AnswerStatus = AnswerStatus.ANSWERED

    @field_validator("selected_option_ids", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        # Models often send an explicit empty value for unused fields.
        return v or []

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v):
        if v is None:
            return v
        return max(0.0, min(1.0, float(v)))


class PageState(str, Enum):
    LOADING = "loading"
    QUESTION = "question"
    FEEDBACK = "feedback"
    COMPLETION = "completion"
    LESSON = "lesson"  # course theory page with a forward button (Save and Continue)
    LOBBY = "lobby"    # quiz start page with a Take an Assessment button
    OUTLINE = "outline"  # course outline listing sections with progress percents
    HOME = "home"  # Oracle Academy landing with My Classes entry
    CLASSES = "classes"  # My Classes hub listing Take Class buttons (one per course)
    AMBIGUOUS = "ambiguous"


class ControlInfo(BaseModel):
    kind: Literal["radio", "checkbox", "text", "button", "submit", "link", "other"] = "other"
    name: str = ""
    selector_hint: str = ""
    visible: bool = True
    enabled: bool = True


class PageSnapshot(BaseModel):
    url: str = ""
    title: str = ""
    visible_text: str = ""
    question_id: Optional[str] = None
    question_text: str = ""
    options: list[AnswerOption] = Field(default_factory=list)
    controls: list[ControlInfo] = Field(default_factory=list)
    is_loading: bool = False
    feedback_text: str = ""
    is_completion: bool = False
    screenshot_path: Optional[str] = None
