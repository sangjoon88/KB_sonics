import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MemberOut(BaseModel):
    """공개용: 레이팅 미포함."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    position: str | None
    position2: str | None
    height_cm: int | None
    is_active: bool


class MemberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    position: Literal["G", "F", "C"] | None = None
    position2: Literal["G", "F", "C"] | None = None
    height_cm: int | None = Field(default=None, ge=130, le=230)


class MemberPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    position: Literal["G", "F", "C", ""] | None = None
    position2: Literal["G", "F", "C", ""] | None = None
    height_cm: int | None = Field(default=None, ge=130, le=230)
    weight_kg: int | None = Field(default=None, ge=30, le=200)
    is_active: bool | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    date: dt.date
    start_time: str | None
    location: str | None
    vote_deadline: dt.datetime | None
    status: str


class SessionCreate(BaseModel):
    date: dt.date | None = None  # 기본: 다음 일요일
    start_time: str | None = None  # 기본: 08:00
    location: str | None = None    # 기본: DEFAULT_LOCATION
    vote_deadline: dt.datetime | None = None


class SessionPatch(BaseModel):
    status: Literal["open", "closed", "finished"] | None = None
    start_time: str | None = None
    location: str | None = None


class VoteIn(BaseModel):
    member_id: int
    vote: Literal["yes", "no", "early"]
    leave_time: str | None = None  # vote=early 일 때 필수 ("HH:MM")


class CheckinIn(BaseModel):
    member_id: int
    checked_in: bool


class Game2LineupIn(BaseModel):
    mode: Literal["kept", "reshuffled"]


class MoveIn(BaseModel):
    member_id: int


class ResultIn(BaseModel):
    score_a: int = Field(ge=0, le=300)
    score_b: int = Field(ge=0, le=300)
