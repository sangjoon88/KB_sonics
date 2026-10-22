"""미니게임: 3점슛 콘테스트 기록·랭킹.

게임은 폰 안(브라우저)에서 돌기 때문에 점수 조작을 완전히 막을 수는 없다.
대신 서버가 판을 시작시키고(run), 끝날 때 한 번만, 말이 되는 점수만 받는다.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ArcadeRun, Member
from app.timeutil import now_kst

GAME = "three_pt"
RACKS, BALLS_PER_RACK = 5, 5
MAX_MADE = RACKS * BALLS_PER_RACK                 # 25개
MAX_MONEY = RACKS                                 # 랙마다 마지막 공 1개 = 머니볼(2점)
MAX_SCORE = MAX_MADE + MAX_MONEY                  # 30점
GAME_SECONDS = 60
MIN_SECONDS = 15                                  # 25개를 아무리 빨리 쏴도 이보다 짧을 수 없음
MAX_SECONDS = GAME_SECONDS + 120                  # 화면 꺼짐·전송 지연 여유
DAILY_LIMIT = 60                                  # 하루 최대 판 수 (도배 방지)


class ArcadeError(ValueError):
    pass


def week_start(d: date) -> date:
    """이번 주 월요일 (주간 랭킹: 월 00:00 ~ 일 24:00, 일요일 경기 날이 마지막 날)."""
    return d - timedelta(days=d.weekday())


def week_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or now_kst()
    start = datetime.combine(week_start(now.date()), datetime.min.time())
    return start, start + timedelta(days=7)


def season_range(season: int) -> tuple[datetime, datetime]:
    return datetime(season, 1, 1), datetime(season + 1, 1, 1)


def start_run(db: Session, member: Member, now: datetime | None = None) -> ArcadeRun:
    now = now or now_kst()
    day0 = datetime.combine(now.date(), datetime.min.time())
    played = db.scalar(select(func.count()).select_from(ArcadeRun).where(
        ArcadeRun.member_id == member.id, ArcadeRun.started_at >= day0))
    if played >= DAILY_LIMIT:
        raise ArcadeError(f"오늘은 {DAILY_LIMIT}판까지예요. 내일 다시 도전하세요!")
    run = ArcadeRun(member_id=member.id, game=GAME, started_at=now)
    db.add(run)
    db.commit()
    return run


def finish_run(db: Session, member: Member, run_id: int, made: int, money: int,
               now: datetime | None = None) -> ArcadeRun:
    now = now or now_kst()
    run = db.get(ArcadeRun, run_id)
    if run is None or run.member_id != member.id:
        raise ArcadeError("게임 기록을 찾을 수 없어요.")
    if run.finished_at is not None:
        raise ArcadeError("이미 저장된 게임이에요.")
    elapsed = (now - run.started_at).total_seconds()
    if not (MIN_SECONDS <= elapsed <= MAX_SECONDS):
        raise ArcadeError("게임 시간이 올바르지 않아 기록하지 않았어요. 다시 시작해 주세요.")
    if not (isinstance(made, int) and isinstance(money, int)):
        raise ArcadeError("점수가 올바르지 않아요.")
    if not (0 <= made <= MAX_MADE and 0 <= money <= min(MAX_MONEY, made)):
        raise ArcadeError("점수가 올바르지 않아요.")
    run.made = made
    run.score = made + money
    run.finished_at = now
    db.commit()
    return run


@dataclass
class Row:
    member: Member
    score: int
    at: datetime
    rank: int = 0

    @property
    def back_number(self):  # bn 매크로가 m.back_number 를 읽는다
        return self.member.back_number


def leaderboard(db: Session, since: datetime, until: datetime) -> list[Row]:
    """기간 내 멤버별 최고 점수. 같은 점수면 먼저 달성한 사람이 위."""
    runs = db.execute(
        select(ArcadeRun.member_id, ArcadeRun.score, ArcadeRun.finished_at)
        .where(ArcadeRun.game == GAME, ArcadeRun.finished_at.is_not(None),
               ArcadeRun.finished_at >= since, ArcadeRun.finished_at < until)
        .order_by(ArcadeRun.score.desc(), ArcadeRun.finished_at)
    ).all()
    best: dict[int, tuple[int, datetime]] = {}
    for mid, score, at in runs:
        best.setdefault(mid, (score, at))
    members = {m.id: m for m in db.scalars(select(Member).where(Member.id.in_(best))).all()} if best else {}
    rows = [Row(members[mid], sc, at) for mid, (sc, at) in best.items() if mid in members]
    rows.sort(key=lambda r: (-r.score, r.at))
    prev, rank = None, 0
    for i, r in enumerate(rows, 1):
        if r.score != prev:
            rank, prev = i, r.score       # 동점은 같은 등수
        r.rank = rank
    return rows


def find(rows: list[Row], member_id: int) -> Row | None:
    return next((r for r in rows if r.member.id == member_id), None)
