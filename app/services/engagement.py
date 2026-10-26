"""참여 지표 (승패와 무관, 모든 멤버에게 공개): 연속 출석, 월간 개근상, 투표 1등, 마일스톤 배지.

출석 = 그날 결과가 입력된 게임을 1게임 이상 뛴 것 (stats.compute_stats 와 같은 기준).
연속 출석은 '경기가 열린 날' 기준으로 센다 — 경기가 없는 주는 연속을 끊지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import ClubSession, Game, Member

PERFECT_MONTH_MIN_SESSIONS = 2   # 개근상: 그달 경기가 2번 이상 열린 달만
RATE_BADGE_MIN_SESSIONS = 5      # 시즌 출석률 배지: 시즌 경기가 5번 이상 열린 뒤부터
FIRST_VOTE_FROM = date(2026, 11, 8)   # 투표 1등: 이 날짜 경기부터 집계 (그 전 경기는 기능 도입 전에 투표가 시작됨)


@dataclass(frozen=True)
class BadgeDef:
    key: str
    emoji: str
    title: str
    desc: str


BADGES = [
    BadgeDef("first", "🏀", "첫 출석", "처음으로 경기를 뛰었어요"),
    BadgeDef("g10", "🎽", "10경기", "누적 10경기"),
    BadgeDef("g50", "🏅", "50경기", "누적 50경기"),
    BadgeDef("g100", "💎", "100경기", "누적 100경기"),
    BadgeDef("s4", "🔥", "4연속 출석", "경기 4번 연속 출석"),
    BadgeDef("s8", "💥", "8연속 출석", "경기 8번 연속 출석"),
    BadgeDef("s12", "☄️", "12연속 출석", "경기 12번 연속 출석"),
    BadgeDef("perfect", "📅", "개근상", "한 달 경기에 모두 출석"),
    BadgeDef("rate80", "💯", "출석률 80%", "시즌 출석률 80% 이상"),
    BadgeDef("eb1", "⚡", "투표 1등", "경기 투표를 가장 먼저 했어요"),
    BadgeDef("eb5", "🚀", "투표 1등 5회", "투표 1등 5번"),
]


@dataclass
class Engagement:
    member_id: int
    cur_streak: int = 0            # 지금 이어지고 있는 연속 출석
    best_streak: int = 0           # 전체 기간 최장 연속 출석
    attended_all: int = 0
    games_all: int = 0
    season_attended: int = 0
    season_held: int = 0
    early_birds: int = 0           # 이번 시즌 투표 1등 횟수
    early_birds_all: int = 0
    perfect_months: list[tuple[int, int]] = field(default_factory=list)   # 전체 기간 (년, 월)
    month_progress: tuple[int, int] | None = None    # 이번 달 (출석, 열린 경기)
    earned: set[str] = field(default_factory=set)

    @property
    def season_rate(self) -> float:
        return self.season_attended / self.season_held if self.season_held else 0.0

    def badges(self) -> list[tuple[BadgeDef, bool]]:
        return [(b, b.key in self.earned) for b in BADGES]


@dataclass
class MonthAward:
    year: int
    month: int
    held: int
    done: bool                     # 지난 달(확정) / 이번 달(도전 중)
    members: list[Member]


@dataclass
class EngagementData:
    by_member: dict[int, Engagement]
    months: list[MonthAward]       # 이번 시즌, 최근 달이 앞
    early_bird_of: dict[int, Member]   # session_id → 그 경기 투표 1등


def compute_engagement(db: Session, season: int, today: date) -> EngagementData:
    members = {m.id: m for m in db.scalars(select(Member).where(Member.is_guest.is_(False))).all()}
    sessions = db.scalars(select(ClubSession).options(
        selectinload(ClubSession.games).selectinload(Game.roster),
        selectinload(ClubSession.attendances)).order_by(ClubSession.date)).all()

    played: dict[int, set[int]] = {}
    games_count: dict[int, int] = {}
    held: list[ClubSession] = []
    for s in sessions:
        ids: set[int] = set()
        for g in s.games:
            if g.status != "finished":
                continue
            for r in g.roster:
                ids.add(r.member_id)
                games_count[r.member_id] = games_count.get(r.member_id, 0) + 1
        if ids:
            held.append(s)
            played[s.id] = ids

    eng = {mid: Engagement(member_id=mid, games_all=games_count.get(mid, 0)) for mid in members}
    season_held = [s for s in held if s.date.year == season]

    # 연속 출석 / 출석 수
    for mid, e in eng.items():
        run = 0
        for s in held:
            if mid in played[s.id]:
                run += 1
                e.attended_all += 1
                e.best_streak = max(e.best_streak, run)
            else:
                run = 0
        e.cur_streak = run
        e.season_held = len(season_held)
        e.season_attended = sum(1 for s in season_held if mid in played[s.id])

    # 월간 개근상 (전체 기간 계산, 화면에는 이번 시즌 달만)
    by_month: dict[tuple[int, int], list[ClubSession]] = {}
    for s in held:
        by_month.setdefault((s.date.year, s.date.month), []).append(s)
    months: list[MonthAward] = []
    this_month = (today.year, today.month)
    for ym, ss in sorted(by_month.items()):
        done = ym < this_month
        perfect = [mid for mid in eng if all(mid in played[s.id] for s in ss)]
        if done and len(ss) >= PERFECT_MONTH_MIN_SESSIONS:
            for mid in perfect:
                eng[mid].perfect_months.append(ym)
        if ym == this_month:
            for mid, e in eng.items():
                e.month_progress = (sum(1 for s in ss if mid in played[s.id]), len(ss))
        if ym[0] == season and (not done or len(ss) >= PERFECT_MONTH_MIN_SESSIONS):
            months.append(MonthAward(ym[0], ym[1], len(ss), done, [members[mid] for mid in perfect]))
    months.reverse()

    # 투표 1등: 그 경기에 가장 먼저 투표한 멤버 (대리 투표·게스트 제외, 처음 투표 시각 기준)
    early_bird_of: dict[int, Member] = {}
    for s in sessions:
        if s.date < FIRST_VOTE_FROM:
            continue
        cands = [a for a in s.attendances
                 if a.first_voted_at is not None and a.proxy_by is None and a.member_id in members]
        if not cands:
            continue
        first = min(cands, key=lambda a: (a.first_voted_at, a.id))
        early_bird_of[s.id] = members[first.member_id]
        e = eng[first.member_id]
        e.early_birds_all += 1
        if s.date.year == season:
            e.early_birds += 1

    # 마일스톤 배지
    for e in eng.values():
        checks = {
            "first": e.attended_all >= 1, "g10": e.games_all >= 10, "g50": e.games_all >= 50,
            "g100": e.games_all >= 100, "s4": e.best_streak >= 4, "s8": e.best_streak >= 8,
            "s12": e.best_streak >= 12, "perfect": bool(e.perfect_months),
            "rate80": e.season_held >= RATE_BADGE_MIN_SESSIONS and e.season_rate >= 0.8,
            "eb1": e.early_birds_all >= 1, "eb5": e.early_birds_all >= 5,
        }
        e.earned = {k for k, ok in checks.items() if ok}

    return EngagementData(by_member=eng, months=months, early_bird_of=early_bird_of)


def top_streaks(data: EngagementData, members: dict[int, Member], n: int = 3) -> list[tuple[Member, Engagement]]:
    rows = [(members[mid], e) for mid, e in data.by_member.items() if e.cur_streak > 0 and mid in members]
    return sorted(rows, key=lambda x: (-x[1].cur_streak, -x[1].best_streak, x[0].name))[:n]


def top_early_birds(data: EngagementData, members: dict[int, Member], n: int = 3) -> list[tuple[Member, Engagement]]:
    rows = [(members[mid], e) for mid, e in data.by_member.items() if e.early_birds > 0 and mid in members]
    return sorted(rows, key=lambda x: (-x[1].early_birds, x[0].name))[:n]
