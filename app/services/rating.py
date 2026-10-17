"""openskill 래퍼 + 재계산 (명세서 9장)."""
from __future__ import annotations

from openskill.models import PlackettLuce
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import GRADE_TO_MU, INITIAL_SIGMA
from app.models import ClubSession, Game, Member, RatingHistory

model = PlackettLuce()


def grade_to_rating(grade: float) -> tuple[float, float]:
    return GRADE_TO_MU(grade), INITIAL_SIGMA


def mu_to_grade(mu: float) -> float:
    """화면 표시용: 레이팅(mu)을 초기 등급과 같은 1~5 단위로 환산 (GRADE_TO_MU 의 역함수)."""
    return (mu - GRADE_TO_MU(0)) / (GRADE_TO_MU(1) - GRADE_TO_MU(0))


CONFIDENCE_LEVELS = [(12, "안정", "emerald"), (4, "보통", "sky"), (0, "보정 중", "amber")]


def confidence(games: int) -> tuple[str, str]:
    """화면 표시용 신뢰도. 팀 경기에서는 sigma가 아주 천천히 줄어 숫자로는 의미가 약해서 경기 수로 표현한다."""
    for min_games, label, color in CONFIDENCE_LEVELS:
        if games >= min_games:
            return label, color
    return CONFIDENCE_LEVELS[-1][1:]


def rate_teams(team_a: list[tuple[float, float]], team_b: list[tuple[float, float]],
               score_a: int, score_b: int):
    """[(mu, sigma), ...] 두 팀 → 갱신된 [(mu, sigma), ...] 두 팀."""
    ra = [model.create_rating([mu, sg]) for mu, sg in team_a]
    rb = [model.create_rating([mu, sg]) for mu, sg in team_b]
    new_a, new_b = model.rate([ra, rb], scores=[score_a, score_b])
    return [(r.mu, r.sigma) for r in new_a], [(r.mu, r.sigma) for r in new_b]


def winner_of(score_a: int, score_b: int) -> str:
    return "A" if score_a > score_b else "B" if score_b > score_a else "draw"


def _order_key(game: Game):
    return (game.session.date, game.game_no, game.id)


def rate_game(db: Session, game: Game) -> None:
    """한 게임의 결과로 레이팅 갱신 + RatingHistory 기록."""
    if game.score_a is None or game.score_b is None:
        raise ValueError("점수가 없습니다.")
    roster_a = [r.member for r in game.roster if r.side == "A"]
    roster_b = [r.member for r in game.roster if r.side == "B"]
    if not roster_a or not roster_b:
        raise ValueError("팀 명단이 비어 있습니다.")
    new_a, new_b = rate_teams([(m.mu, m.sigma) for m in roster_a],
                              [(m.mu, m.sigma) for m in roster_b],
                              game.score_a, game.score_b)
    for members, new in ((roster_a, new_a), (roster_b, new_b)):
        for m, (mu, sg) in zip(members, new):
            db.add(RatingHistory(member_id=m.id, game_id=game.id, mu_before=m.mu,
                                 sigma_before=m.sigma, mu_after=mu, sigma_after=sg))
            m.mu, m.sigma = mu, sg
    game.rated = True


def recalculate_from(db: Session, game: Game) -> None:
    """해당 게임 이후(포함) 모든 rated 게임을 시간순으로 재계산."""
    db.flush()
    target_key = _order_key(game)
    games = db.scalars(select(Game).join(ClubSession).where(Game.rated.is_(True))).all()
    affected = sorted([g for g in games if _order_key(g) >= target_key], key=_order_key)
    if game not in affected and game.status == "finished":
        affected = sorted([*affected, game], key=_order_key)
    affected_ids = [g.id for g in affected]
    if not affected_ids:
        return

    histories = db.scalars(select(RatingHistory).where(RatingHistory.game_id.in_(affected_ids))).all()
    order_of = {gid: i for i, gid in enumerate(affected_ids)}
    earliest: dict[int, RatingHistory] = {}
    for h in histories:
        cur = earliest.get(h.member_id)
        if cur is None or order_of[h.game_id] < order_of[cur.game_id]:
            earliest[h.member_id] = h
    for member_id, h in earliest.items():
        m = db.get(Member, member_id)
        m.mu, m.sigma = h.mu_before, h.sigma_before
    for h in histories:
        db.delete(h)
    for g in affected:
        g.rated = False
    db.flush()

    for g in affected:
        if g.status == "finished" and g.score_a is not None:
            rate_game(db, g)
    db.flush()
