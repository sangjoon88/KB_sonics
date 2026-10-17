"""출석/승률/연승 집계 (공개 지표만, 레이팅 미노출)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import extract, select
from sqlalchemy.orm import Session, selectinload

from app.models import Attendance, ClubSession, Game, GameRoster, Member

MIN_GAMES_FOR_WINRATE = 4


@dataclass
class MemberStats:
    member_id: int
    name: str
    attended: int = 0
    sessions_total: int = 0
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    best_streak: int = 0
    current_streak: int = 0
    recent: list[dict] = field(default_factory=list)

    @property
    def attendance_rate(self) -> float:
        return self.attended / self.sessions_total if self.sessions_total else 0.0

    @property
    def win_rate(self) -> float:
        decided = self.wins + self.losses + self.draws
        return self.wins / decided if decided else 0.0

    def as_dict(self) -> dict:
        return {
            "member_id": self.member_id, "name": self.name, "attended": self.attended,
            "sessions_total": self.sessions_total, "attendance_rate": round(self.attendance_rate, 3),
            "games": self.games, "wins": self.wins, "losses": self.losses, "draws": self.draws,
            "win_rate": round(self.win_rate, 3), "best_streak": self.best_streak,
            "current_streak": self.current_streak,
        }


def _season_sessions(db: Session, season: int) -> list[ClubSession]:
    return db.scalars(
        select(ClubSession)
        .where(extract("year", ClubSession.date) == season)
        .options(selectinload(ClubSession.attendances),
                 selectinload(ClubSession.games).selectinload(Game.roster))
        .order_by(ClubSession.date)
    ).all()


def compute_stats(db: Session, season: int, today: date | None = None) -> dict[int, MemberStats]:
    members = db.scalars(select(Member).where(Member.is_guest.is_(False))).all()
    stats = {m.id: MemberStats(member_id=m.id, name=m.name) for m in members}
    sessions = _season_sessions(db, season)
    # 출석률 분모: 실제로 열린(현장 출석 체크가 있었던) 모임 수
    held = [s for s in sessions if any(a.checked_in for a in s.attendances)]
    for s in held:
        for a in s.attendances:
            if a.checked_in and a.member_id in stats:
                stats[a.member_id].attended += 1
    for st in stats.values():
        st.sessions_total = len(held)

    for s in sessions:
        for g in s.games:
            if g.status != "finished" or g.winner is None:
                continue
            for r in g.roster:
                st = stats.get(r.member_id)
                if st is None:
                    continue
                st.games += 1
                if g.winner == "draw":
                    st.draws += 1
                    result = "D"
                    st.current_streak = 0
                elif g.winner == r.side:
                    st.wins += 1
                    result = "W"
                    st.current_streak += 1
                    st.best_streak = max(st.best_streak, st.current_streak)
                else:
                    st.losses += 1
                    result = "L"
                    st.current_streak = 0
                my = g.score_a if r.side == "A" else g.score_b
                opp = g.score_b if r.side == "A" else g.score_a
                st.recent.append({"date": s.date, "session_id": s.id, "game_no": g.game_no,
                                  "side": r.side, "result": result, "my": my, "opp": opp})
    for st in stats.values():
        st.recent.reverse()
    return stats


def leaderboard(stats: dict[int, MemberStats], sort: str) -> list[MemberStats]:
    rows = [s for s in stats.values() if s.attended or s.games]
    if sort == "winrate":
        rows = [s for s in rows if s.games >= MIN_GAMES_FOR_WINRATE]
        return sorted(rows, key=lambda s: (-s.win_rate, -s.games, s.name))
    if sort == "streak":
        return sorted(rows, key=lambda s: (-s.best_streak, -s.current_streak, s.name))
    if sort == "games":
        return sorted(rows, key=lambda s: (-s.games, s.name))
    return sorted(rows, key=lambda s: (-s.attended, -s.attendance_rate, s.name))


def member_game_count(db: Session, member_id: int) -> int:
    return len(db.scalars(select(GameRoster).join(Game).where(
        GameRoster.member_id == member_id, Game.status == "finished")).all())


def last_attended(db: Session, member_id: int) -> date | None:
    return db.scalar(select(ClubSession.date).join(Attendance).where(
        Attendance.member_id == member_id, Attendance.checked_in.is_(True))
        .order_by(ClubSession.date.desc()).limit(1))
