"""출석/승률/연승 집계 (공개 지표만, 레이팅 미노출)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import extract, select
from sqlalchemy.orm import Session, selectinload

from app.models import Attendance, ClubSession, Game, GameRoster, Member

WINRATE_MIN_SHARE = 0.3   # 승률 순위: 시즌에 열린 경기의 30% 이상 뛴 멤버만


def winrate_min_games(season_games: int) -> int:
    """시즌 진행에 따라 올라가는 승률 순위 최소 경기 수 (최소 1경기)."""
    return max(1, math.ceil(season_games * WINRATE_MIN_SHARE))


@dataclass
class MemberStats:
    member_id: int
    name: str
    back_number: str | None = None
    attended: int = 0
    sessions_total: int = 0
    games: int = 0
    season_games: int = 0   # 이번 시즌에 결과가 입력된 전체 게임 수 (모든 멤버 공통)
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
            "member_id": self.member_id, "name": self.name, "back_number": self.back_number, "attended": self.attended,
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
    stats = {m.id: MemberStats(member_id=m.id, name=m.name, back_number=m.back_number) for m in members}
    sessions = _season_sessions(db, season)
    # 출석 = 그날 결과가 입력된 게임을 1게임 이상 실제로 뛴 경우 (투표·출석 체크만으로는 세지 않음)
    # 출석률 분모 = 결과가 입력된 게임이 있는 모임 수
    held = [s for s in sessions if any(g.status == "finished" for g in s.games)]
    for s in held:
        played = {r.member_id for g in s.games if g.status == "finished" for r in g.roster}
        for mid in played:
            if mid in stats:
                stats[mid].attended += 1
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
    season_games = sum(1 for s in sessions for g in s.games if g.status == "finished" and g.winner is not None)
    for st in stats.values():
        st.recent.reverse()
        st.season_games = season_games
    return stats


def leaderboard(stats: dict[int, MemberStats], sort: str) -> list[MemberStats]:
    rows = [s for s in stats.values() if s.attended or s.games]
    if sort == "winrate":
        need = winrate_min_games(max((s.season_games for s in stats.values()), default=0))
        rows = [s for s in rows if s.games >= need]
        return sorted(rows, key=lambda s: (-s.win_rate, -s.games, s.name))
    if sort == "streak":
        return sorted(rows, key=lambda s: (-s.best_streak, -s.current_streak, s.name))
    if sort == "games":
        return sorted(rows, key=lambda s: (-s.games, s.name))
    return sorted(rows, key=lambda s: (-s.attended, -s.games, s.name))  # 출석 같으면 경기 수


def member_game_count(db: Session, member_id: int) -> int:
    return len(db.scalars(select(GameRoster).join(Game).where(
        GameRoster.member_id == member_id, Game.status == "finished")).all())


def last_attended(db: Session, member_id: int) -> date | None:
    return db.scalar(select(ClubSession.date).join(Attendance).where(
        Attendance.member_id == member_id, Attendance.checked_in.is_(True))
        .order_by(ClubSession.date.desc()).limit(1))


def member_summary(db: Session, today: date) -> dict:
    """멤버 집계 (홈·멤버 관리 공용). 정회원(활동 중, 게스트 제외) 기준."""
    from datetime import timedelta
    members = db.scalars(select(Member).where(Member.is_guest.is_(False), Member.is_active.is_(True))).all()
    heights = [m.height_cm for m in members if m.height_cm]
    main = {p: sum(1 for m in members if m.position == p) for p in ("G", "F", "C")}
    able = {p: sum(1 for m in members if p in (m.position, m.position2)) for p in ("G", "F", "C")}

    # 최근 4주 경기당 평균 참가 인원 (게스트 포함, 결과가 입력된 게임 기준)
    since = today - timedelta(days=28)
    recent = db.scalars(select(ClubSession).where(ClubSession.date >= since, ClubSession.date <= today)
                        .options(selectinload(ClubSession.games).selectinload(Game.roster))).all()
    per_day = [len({r.member_id for g in s.games if g.status == "finished" for r in g.roster}) for s in recent]
    per_day = [n for n in per_day if n]
    return {
        "total": len(members),
        "staff": sum(1 for m in members if m.is_admin),
        "avg_height": round(sum(heights) / len(heights), 1) if heights else None,
        "height_n": len(heights),
        "main": main, "able": able, "pos_n": sum(main.values()),
        "recent_avg": round(sum(per_day) / len(per_day), 1) if per_day else None,
        "recent_days": len(per_day),
        # 운영진 화면 전용
        "not_logged_in": sum(1 for m in members if m.pin_must_change),
        "no_height": sum(1 for m in members if not m.height_cm),
        "unrated": sum(1 for m in members if m.initial_grade is None),
    }


# ---------------------------------------------------------------- 운영진 전용: 승패 분석

CLOSE_MARGIN = 5   # 이 점수차 이내면 '접전'


@dataclass
class ResultRow:
    member: Member
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    margin_sum: int = 0
    seq: list[str] = field(default_factory=list)   # 'W'/'L'/'D' (오래된 → 최근)

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def avg_margin(self) -> float:
        return self.margin_sum / self.games if self.games else 0.0

    @property
    def last5(self) -> list[str]:
        return self.seq[-5:]

    @property
    def current_streak(self) -> int:
        n = 0
        for r in reversed(self.seq):
            if r != "W":
                break
            n += 1
        return n

    @property
    def best_streak(self) -> int:
        best = cur = 0
        for r in self.seq:
            cur = cur + 1 if r == "W" else 0
            best = max(best, cur)
        return best

    @property
    def back_number(self):   # bn 매크로용
        return self.member.back_number


def results_overview(db: Session, season: int | None) -> dict:
    """멤버별 승패표(게스트 포함) + 경기별 결과 목록 + 요약. season=None 이면 전체 기간."""
    from app.services import lopsided
    q = select(ClubSession).options(selectinload(ClubSession.games).selectinload(Game.roster)
                                    .selectinload(GameRoster.member)).order_by(ClubSession.date)
    if season is not None:
        q = q.where(extract("year", ClubSession.date) == season)
    sessions = db.scalars(q).all()

    rows: dict[int, ResultRow] = {}
    games_out = []
    for s in sessions:
        for g in sorted(s.games, key=lambda g: g.game_no):
            if g.status != "finished" or g.winner is None or g.score_a is None:
                continue
            diff = g.score_a - g.score_b
            games_out.append({"s": s, "g": g, "diff": diff, "lopsided": lopsided.judge(g.score_a, g.score_b).lopsided,
                              "n_a": sum(1 for r in g.roster if r.side == "A"),
                              "n_b": sum(1 for r in g.roster if r.side == "B")})
            for r in g.roster:
                row = rows.setdefault(r.member_id, ResultRow(member=r.member))
                row.games += 1
                my = diff if r.side == "A" else -diff
                row.margin_sum += my
                if g.winner == "draw":
                    row.draws += 1
                    row.seq.append("D")
                elif g.winner == r.side:
                    row.wins += 1
                    row.seq.append("W")
                else:
                    row.losses += 1
                    row.seq.append("L")

    n = len(games_out)
    margins = [abs(x["diff"]) for x in games_out]
    summary = {
        "games": n,
        "avg_margin": round(sum(margins) / n, 1) if n else None,
        "close_pct": round(100 * sum(1 for m in margins if m <= CLOSE_MARGIN) / n) if n else None,
        "lopsided_pct": round(100 * sum(1 for x in games_out if x["lopsided"]) / n) if n else None,
        "red_wins": sum(1 for x in games_out if x["g"].winner == "A"),
        "white_wins": sum(1 for x in games_out if x["g"].winner == "B"),
    }
    games_out.reverse()   # 최근 경기가 위
    return {"rows": list(rows.values()), "games": games_out, "summary": summary}


RESULT_SORTS = {
    "winrate": lambda r: (-r.win_rate, -r.games, r.member.name),
    "games": lambda r: (-r.games, -r.win_rate, r.member.name),
    "margin": lambda r: (-r.avg_margin, -r.games, r.member.name),
    "streak": lambda r: (-r.current_streak, -r.best_streak, r.member.name),
    "name": lambda r: (r.member.name,),
}
