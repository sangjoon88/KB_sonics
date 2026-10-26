"""미니게임: 3점슛 콘테스트 기록·랭킹.

게임은 폰 안(브라우저)에서 돌기 때문에 점수 조작을 완전히 막을 수는 없다.
대신 서버가 판을 시작시키고(run), 끝날 때 한 번만, 말이 되는 점수만 받는다.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ArcadeChallenge, ArcadeRun, Member
from app.timeutil import now_kst

GAME = "three_pt"
RACKS, BALLS_PER_RACK = 5, 5
MAX_MADE = RACKS * BALLS_PER_RACK                 # 25개
MAX_MONEY = RACKS                                 # 랙마다 마지막 공 1개 = 머니볼(2점)
SHOTS = MAX_MADE + 1                              # 26번째 = 로고샷 (5지점을 다 던지고 시간이 남으면)
DEEP_POINTS = 3
SWISH_COMBO = 3                                   # 스위시가 3번 이어질 때마다 +1
MAX_SCORE = MAX_MADE + MAX_MONEY + DEEP_POINTS + SHOTS // SWISH_COMBO   # 41점
SHOT_CODES = "SMRX-"                              # 스위시 / 골 / 림 맞고 골 / 실패 / 못 던짐
SPOT_LABELS = ["좌 코너", "좌 45°", "탑", "우 45°", "우 코너", "로고샷"]
CHALLENGE_DAYS = 7                                # 도전장 유효 기간
GAME_SECONDS = 45                                 # 2026-10 난이도 상향 (예전 60초)
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


def score_shots(shots: str) -> tuple[int, int, int]:
    """슛 기록 → (점수, 성공 수, 머니볼 성공 수). 화면(arcade.js)과 같은 계산."""
    score = made = money = run = 0
    for i, c in enumerate(shots):
        if c not in "SMR":
            run = 0
            continue
        made += 1
        if i == SHOTS - 1:
            score += DEEP_POINTS
        elif i % BALLS_PER_RACK == BALLS_PER_RACK - 1:
            score += 2
            money += 1
        else:
            score += 1
        run = run + 1 if c == "S" else 0
        if run and run % SWISH_COMBO == 0:
            score += 1
    return score, made, money


def _valid_shots(shots) -> bool:
    if not isinstance(shots, str) or len(shots) != SHOTS or any(c not in SHOT_CODES for c in shots):
        return False
    return "-" not in shots.rstrip("-")          # 못 던진 공은 맨 뒤에만


def _clean_events(ev, score: int) -> list | None:
    """점수 흐름 [[ms, 누적점수], …] — 말이 안 되면 버린다 (기록 자체는 인정)."""
    if not isinstance(ev, list) or len(ev) > SHOTS:
        return None
    out, last_t, last_s = [], -1, 0
    for e in ev:
        if not (isinstance(e, list) and len(e) == 2 and all(isinstance(x, int) for x in e)):
            return None
        t, sc = e
        if t < last_t or sc <= last_s or t > (GAME_SECONDS + 10) * 1000:
            return None
        out.append([t, sc])
        last_t, last_s = t, sc
    return out if last_s == score else None


def finish_run(db: Session, member: Member, run_id: int, made: int | None = None, money: int | None = None,
               now: datetime | None = None, shots: str | None = None, events: list | None = None) -> ArcadeRun:
    now = now or now_kst()
    run = db.get(ArcadeRun, run_id)
    if run is None or run.member_id != member.id:
        raise ArcadeError("게임 기록을 찾을 수 없어요.")
    if run.finished_at is not None:
        raise ArcadeError("이미 저장된 게임이에요.")
    elapsed = (now - run.started_at).total_seconds()
    if not (MIN_SECONDS <= elapsed <= MAX_SECONDS):
        raise ArcadeError("게임 시간이 올바르지 않아 기록하지 않았어요. 다시 시작해 주세요.")
    if shots is not None:
        if not _valid_shots(shots):
            raise ArcadeError("점수가 올바르지 않아요.")
        score, made, _ = score_shots(shots)
        run.detail = {"shots": shots, "ev": _clean_events(events, score)}
    else:                                       # 예전 화면(캐시된 arcade.js): 성공 수·머니볼 수만
        if not (isinstance(made, int) and isinstance(money, int)):
            raise ArcadeError("점수가 올바르지 않아요.")
        if not (0 <= made <= MAX_MADE and 0 <= money <= min(MAX_MONEY, made)):
            raise ArcadeError("점수가 올바르지 않아요.")
        score = made + money
    run.made = made
    run.score = score
    run.finished_at = now
    beaten = _resolve_challenges(db, member, score, now)
    db.commit()
    run.beaten = beaten                         # 이번 판으로 깬 도전장 (화면 메시지용, 저장 안 함)
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


# ---------------------------------------------------------------- 고스트 (점수 흐름 비교)
def best_run(db: Session, member_id: int, since: datetime, until: datetime) -> ArcadeRun | None:
    """기간 내 최고 점수 판 (같은 점수면 먼저 한 판)."""
    return db.scalars(select(ArcadeRun).where(
        ArcadeRun.member_id == member_id, ArcadeRun.game == GAME, ArcadeRun.finished_at.is_not(None),
        ArcadeRun.finished_at >= since, ArcadeRun.finished_at < until,
    ).order_by(ArcadeRun.score.desc(), ArcadeRun.finished_at).limit(1)).first()


def _ghost(label: str, run: ArcadeRun | None) -> dict | None:
    ev = (run.detail or {}).get("ev") if run else None
    return {"label": label, "score": run.score, "ev": ev} if ev is not None else None


def ghosts(db: Session, me: Member, season: int) -> list[dict]:
    """플레이 중 비교할 기록: 내 시즌 최고, 이번 주 1위(내가 1위가 아닐 때). 점수 흐름이 남은 판만."""
    out = [_ghost("내 최고", best_run(db, me.id, *season_range(season)))]
    week = leaderboard(db, *week_range())
    if week and not any(r.rank == 1 and r.member.id == me.id for r in week):
        top = week[0]
        out.append(_ghost(f"주간 1위 {top.member.name}", best_run(db, top.member.id, *week_range())))
    return [g for g in out if g]


# ---------------------------------------------------------------- 도전장
def _open_challenges(now: datetime):
    return select(ArcadeChallenge).where(ArcadeChallenge.beaten_at.is_(None),
                                         ArcadeChallenge.created_at >= now - timedelta(days=CHALLENGE_DAYS))


def send_challenge(db: Session, me: Member, to_id: int, season: int, now: datetime | None = None) -> ArcadeChallenge:
    now = now or now_kst()
    if to_id == me.id:
        raise ArcadeError("나에게는 도전장을 보낼 수 없어요.")
    to = db.get(Member, to_id)
    if to is None or to.is_guest:
        raise ArcadeError("받는 사람을 찾을 수 없어요.")
    mine = find(leaderboard(db, *season_range(season)), me.id)
    if mine is None or mine.score <= 0:
        raise ArcadeError("먼저 한 판 해서 기록을 남겨야 도전장을 보낼 수 있어요.")
    if db.scalar(_open_challenges(now).where(ArcadeChallenge.from_id == me.id, ArcadeChallenge.to_id == to_id)):
        raise ArcadeError(f"{to.name}님에게 보낸 도전장이 아직 진행 중이에요.")
    ch = ArcadeChallenge(from_id=me.id, to_id=to_id, target=mine.score, created_at=now)
    db.add(ch)
    db.commit()
    return ch


def _resolve_challenges(db: Session, me: Member, score: int, now: datetime) -> list[ArcadeChallenge]:
    beaten = db.scalars(_open_challenges(now).where(ArcadeChallenge.to_id == me.id,
                                                    ArcadeChallenge.target < score)).all()
    for ch in beaten:
        ch.beaten_at, ch.beaten_score = now, score
    return list(beaten)


@dataclass
class Challenges:
    incoming: list[ArcadeChallenge]     # 받은 도전장 (진행 중)
    outgoing: list[ArcadeChallenge]     # 보낸 도전장 (최근에 깨진 것 + 진행 중)
    sent_to: set[int]                   # 진행 중인 도전장을 보낸 상대
    now: datetime

    def days_left(self, ch: ArcadeChallenge) -> int:
        return max(1, CHALLENGE_DAYS - (self.now - ch.created_at).days)


def challenges(db: Session, me: Member, now: datetime | None = None) -> Challenges:
    now = now or now_kst()
    incoming = db.scalars(_open_challenges(now).where(ArcadeChallenge.to_id == me.id)
                          .order_by(ArcadeChallenge.created_at.desc())).all()
    pending_out = db.scalars(_open_challenges(now).where(ArcadeChallenge.from_id == me.id)
                             .order_by(ArcadeChallenge.created_at.desc())).all()
    beaten_out = db.scalars(select(ArcadeChallenge).where(
        ArcadeChallenge.from_id == me.id, ArcadeChallenge.beaten_at >= now - timedelta(days=CHALLENGE_DAYS))
        .order_by(ArcadeChallenge.beaten_at.desc())).all()
    return Challenges(list(incoming), list(beaten_out) + list(pending_out), {c.to_id for c in pending_out}, now)


# ---------------------------------------------------------------- 내 슛 분석
@dataclass
class SpotStat:
    label: str
    made: int = 0
    att: int = 0

    @property
    def rate(self) -> float:
        return self.made / self.att if self.att else 0.0


@dataclass
class MyStats:
    plays: int
    avg: float
    best: int
    spots: list[SpotStat]               # 5지점 + 로고샷
    recent: list[int]                   # 최근 판 점수 (오래된 것 → 최근)
    tracked: int                        # 슛 기록이 남은 판 수 (지점별 성공률 기준)


def my_stats(db: Session, me: Member, season: int, recent_n: int = 20) -> MyStats | None:
    since, until = season_range(season)
    runs = db.scalars(select(ArcadeRun).where(
        ArcadeRun.member_id == me.id, ArcadeRun.game == GAME, ArcadeRun.finished_at.is_not(None),
        ArcadeRun.finished_at >= since, ArcadeRun.finished_at < until,
    ).order_by(ArcadeRun.finished_at)).all()
    if not runs:
        return None
    spots = [SpotStat(label) for label in SPOT_LABELS]
    tracked = 0
    for r in runs:
        shots = (r.detail or {}).get("shots")
        if not shots:
            continue
        tracked += 1
        for i, c in enumerate(shots):
            if c == "-":
                continue
            sp = spots[min(i // BALLS_PER_RACK, len(spots) - 1)]
            sp.att += 1
            sp.made += c in "SMR"
    scores = [r.score for r in runs]
    return MyStats(plays=len(runs), avg=sum(scores) / len(scores), best=max(scores), spots=spots,
                   recent=scores[-recent_n:], tracked=tracked)
