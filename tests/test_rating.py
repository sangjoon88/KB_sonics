from datetime import date

import pytest

from app.models import ClubSession, Game, GameRoster, Member, RatingHistory
from app.services import rating
from app.services.ops import submit_result


def _setup(db, n=12):
    members = [Member(name=f"m{i}", mu=rating.grade_to_rating(1 + i % 5)[0], sigma=25 / 3,
                      initial_grade=1 + i % 5) for i in range(n)]
    admin = Member(name="admin", is_admin=True)
    db.add_all(members + [admin])
    db.flush()
    return members, admin


def _game(db, d, no, members):
    s = db.query(ClubSession).filter_by(date=d).first()
    if s is None:
        s = ClubSession(date=d, status="closed")
        db.add(s)
        db.flush()
    g = Game(session_id=s.id, game_no=no, lineup_mode="balanced", status="lineup_ready")
    db.add(g)
    db.flush()
    half = len(members) // 2
    for i, m in enumerate(members):
        g.roster.append(GameRoster(member_id=m.id, side="A" if i < half else "B"))
    db.flush()
    db.refresh(g)
    return g


def test_mu_to_grade_roundtrip():
    for g in (1.0, 2.5, 3.67, 5.0):
        assert rating.mu_to_grade(rating.grade_to_rating(g)[0]) == pytest.approx(g)
    assert rating.confidence(0)[0] == "보정 중"
    assert rating.confidence(4)[0] == "보통"
    assert rating.confidence(12)[0] == "안정"


def test_grade_to_rating():
    assert rating.grade_to_rating(1.0)[0] == 17
    assert rating.grade_to_rating(3.0)[0] == 25
    assert rating.grade_to_rating(5.0)[0] == 33
    assert rating.grade_to_rating(3.67)[0] == pytest.approx(27.68)


def test_winners_up_losers_down(db):
    members, admin = _setup(db)
    g = _game(db, date(2026, 3, 1), 1, members)
    before = {m.id: m.mu for m in members}
    submit_result(db, admin, g, 40, 30)
    for r in g.roster:
        if r.side == "A":
            assert r.member.mu > before[r.member_id]
        else:
            assert r.member.mu < before[r.member_id]
    assert db.query(RatingHistory).count() == 12
    assert g.winner == "A" and g.rated


def test_game1_returns_lopsided(db):
    members, admin = _setup(db)
    g = _game(db, date(2026, 3, 1), 1, members)
    res = submit_result(db, admin, g, 50, 20)
    assert res.lopsided and res.margin == 30
    assert g.lopsided is True


def _play_season(db, members, admin, scores):
    games = []
    for i, (a, b) in enumerate(scores):
        d = date(2026, 3, 1 + 7 * (i // 2))
        rotated = members[i:] + members[:i]
        g = _game(db, d, 1 + i % 2, rotated)
        submit_result(db, admin, g, a, b)
        games.append(g)
    return games


def test_recalculate_matches_correct_entry(db):
    members, admin = _setup(db)
    correct = [(40, 30), (35, 38), (50, 20), (33, 33), (41, 39)]
    # 1) 두 번째 게임을 잘못 입력 후 수정
    wrong = list(correct)
    wrong[1] = (38, 35)
    games = _play_season(db, members, admin, wrong)
    submit_result(db, admin, games[1], *correct[1])
    db.commit()
    after_fix = {m.name: (m.mu, m.sigma) for m in members}
    hist_count = db.query(RatingHistory).count()

    # 2) 처음부터 올바르게 입력한 경우 (새 DB 대신 동일 초기값으로 재구성)
    for m in members:
        m.mu, m.sigma = rating.grade_to_rating(m.initial_grade)
    db.query(RatingHistory).delete()
    for g in games:
        g.rated = False
        g.status = "lineup_ready"
    db.flush()
    for g, (a, b) in zip(games, correct):
        submit_result(db, admin, g, a, b)
    clean = {m.name: (m.mu, m.sigma) for m in members}

    assert hist_count == 12 * len(correct)
    for name in clean:
        assert after_fix[name][0] == pytest.approx(clean[name][0])
        assert after_fix[name][1] == pytest.approx(clean[name][1])


def test_draw_keeps_equal_teams(db):
    members, admin = _setup(db, 4)
    for m in members:
        m.mu = 25.0
    g = _game(db, date(2026, 3, 1), 1, members)
    submit_result(db, admin, g, 30, 30)
    assert g.winner == "draw"
    assert all(m.mu == pytest.approx(25.0) for m in members)
