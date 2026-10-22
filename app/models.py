"""데이터 모델 (명세서 6장).

enum 값은 마이그레이션 단순화를 위해 문자열 컬럼으로 저장하고 앱에서 검증한다.
모든 datetime은 KST 기준 naive 값이다 (단일 시간대 서비스).
"""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.timeutil import now_kst

POSITIONS = ("G", "F", "C")
VOTES = ("yes", "no", "early")  # 참석 / 불참 / 조퇴


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    position: Mapped[str | None] = mapped_column(String(1))          # 주 포지션 (밸런싱 기준)
    position2: Mapped[str | None] = mapped_column(String(1))         # 부 포지션 (선택)
    height_cm: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[int | None] = mapped_column(Integer)           # 선택, 본인·운영진만 열람
    back_number: Mapped[str | None] = mapped_column(String(2))       # 백넘버 "0"~"99", "00" (중복 허용, 없으면 화면에 '-')
    initial_grade: Mapped[float | None] = mapped_column(Float)
    mu: Mapped[float] = mapped_column(Float, default=25.0)
    sigma: Mapped[float] = mapped_column(Float, default=25 / 3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)  # 관리자(서버 운영자): 운영진 지정 권한
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)  # 게스트 (is_active=False 로 목록/기록에서 제외)
    pin_hash: Mapped[str | None] = mapped_column(String(100))  # 모든 멤버의 PIN (bcrypt)
    pin_must_change: Mapped[bool] = mapped_column(Boolean, default=False)
    pin_fail_count: Mapped[int] = mapped_column(Integer, default=0)
    pin_locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)


class AdminLog(Base):
    __tablename__ = "admin_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    action: Mapped[str] = mapped_column(String(50))
    target: Mapped[str] = mapped_column(String(50))
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    admin: Mapped[Member] = relationship()


class InitialRating(Base):
    __tablename__ = "initial_ratings"

    rater_id: Mapped[int] = mapped_column(ForeignKey("members.id"), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), primary_key=True)
    grade: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)


class ClubSession(Base):
    """일요일 모임 1회 (명세서의 Session)."""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[str | None] = mapped_column(String(5))   # "HH:MM"
    location: Mapped[str | None] = mapped_column(String(100))
    vote_deadline: Mapped[datetime | None] = mapped_column(DateTime)  # 기본 없음 (현장 출석 체크/운영진이 마감)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed | finished
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    attendances: Mapped[list["Attendance"]] = relationship(back_populates="session",
                                                           cascade="all, delete-orphan")
    games: Mapped[list["Game"]] = relationship(back_populates="session", order_by="Game.game_no",
                                               cascade="all, delete-orphan")


class Attendance(Base):
    __tablename__ = "attendances"
    __table_args__ = (UniqueConstraint("session_id", "member_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    vote: Mapped[str | None] = mapped_column(String(5))  # yes | no | early (현장 추가는 null)
    leave_time: Mapped[str | None] = mapped_column(String(5))  # 조퇴 시각 "HH:MM" (vote=early 일 때만)
    guest_of: Mapped[int | None] = mapped_column(ForeignKey("members.id"))  # 게스트를 데려온 멤버
    proxy_by: Mapped[int | None] = mapped_column(ForeignKey("members.id"))  # 대리 투표한 운영진
    checked_in: Mapped[bool] = mapped_column(Boolean, default=False)
    voted_at: Mapped[datetime | None] = mapped_column(DateTime)

    session: Mapped[ClubSession] = relationship(back_populates="attendances")
    member: Mapped[Member] = relationship(foreign_keys=[member_id])
    inviter: Mapped[Member | None] = relationship(foreign_keys=[guest_of])
    proxy: Mapped[Member | None] = relationship(foreign_keys=[proxy_by])


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (UniqueConstraint("session_id", "game_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    game_no: Mapped[int] = mapped_column(Integer)
    lineup_mode: Mapped[str] = mapped_column(String(12))  # balanced | kept | reshuffled
    score_a: Mapped[int | None] = mapped_column(Integer)
    score_b: Mapped[int | None] = mapped_column(Integer)
    winner: Mapped[str | None] = mapped_column(String(4))  # A | B | draw
    status: Mapped[str] = mapped_column(String(14), default="lineup_ready")  # lineup_ready | finished
    rated: Mapped[bool] = mapped_column(Boolean, default=False)
    played_at: Mapped[datetime | None] = mapped_column(DateTime)
    # 운영 보조 필드 (명세서 7.5 다시 섞기, 8장 판정 기록)
    candidates: Mapped[list | None] = mapped_column(JSON)       # 상위 K개 후보안 [[a_ids],[b_ids]]
    candidate_idx: Mapped[int] = mapped_column(Integer, default=0)
    lopsided: Mapped[bool | None] = mapped_column(Boolean)      # 게임1 일방성 판정 결과

    session: Mapped[ClubSession] = relationship(back_populates="games")
    roster: Mapped[list["GameRoster"]] = relationship(back_populates="game",
                                                      cascade="all, delete-orphan")


class GameRoster(Base):
    __tablename__ = "game_rosters"

    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), primary_key=True)
    side: Mapped[str] = mapped_column(String(1))  # A | B

    game: Mapped[Game] = relationship(back_populates="roster")
    member: Mapped[Member] = relationship()


class RatingHistory(Base):
    __tablename__ = "rating_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    mu_before: Mapped[float] = mapped_column(Float)
    sigma_before: Mapped[float] = mapped_column(Float)
    mu_after: Mapped[float] = mapped_column(Float)
    sigma_after: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)


class SessionComment(Base):
    """경기(투표)별 한마디."""
    __tablename__ = "session_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    body: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    member: Mapped[Member] = relationship()


class AppSetting(Base):
    """운영진 설정 (밸런스 모드 등)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class ArcadeRun(Base):
    """미니게임 한 판 (3점슛 콘테스트). 시작할 때 만들고, 끝나면 점수를 한 번만 기록한다."""
    __tablename__ = "arcade_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    game: Mapped[str] = mapped_column(String(20), default="three_pt")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    score: Mapped[int | None] = mapped_column(Integer)
    made: Mapped[int | None] = mapped_column(Integer)      # 성공한 공 수 (머니볼 포함)

    member: Mapped[Member] = relationship()

