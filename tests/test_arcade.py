"""미니게임(3점슛 콘테스트): 판 시작/종료 검증, 주간·시즌 랭킹, 화면."""
import datetime as dt
from datetime import timedelta

import pytest

from app.models import ArcadeRun, Member
from app.services import arcade
from test_flow import _login_admin, _login_as


def _members(db, n=3):
    ms = [Member(name=f"슈터{i}", position="GFC"[i % 3], height_cm=175 + i, back_number=str(10 + i)) for i in range(n)]
    db.add_all(ms)
    db.commit()
    return ms


def _played(db, m, score, at, made=None):
    db.add(ArcadeRun(member_id=m.id, game=arcade.GAME, started_at=at - timedelta(seconds=60), finished_at=at,
                     score=score, made=made if made is not None else score))
    db.commit()


def test_week_range_is_monday_to_sunday():
    sun = dt.datetime(2026, 10, 25, 9, 0)          # 일요일 경기 날
    start, end = arcade.week_range(sun)
    assert start == dt.datetime(2026, 10, 19) and end == dt.datetime(2026, 10, 26)
    mon = dt.datetime(2026, 10, 26, 0, 1)
    assert arcade.week_range(mon)[0] == dt.datetime(2026, 10, 26)


def test_finish_validation(db):
    m, other = _members(db, 2)
    t0 = dt.datetime(2026, 10, 22, 12, 0, 0)
    run = arcade.start_run(db, m, now=t0)
    with pytest.raises(arcade.ArcadeError):                       # 너무 빨리 끝남
        arcade.finish_run(db, m, run.id, 10, 2, now=t0 + timedelta(seconds=5))
    with pytest.raises(arcade.ArcadeError):                       # 남의 판
        arcade.finish_run(db, other, run.id, 10, 2, now=t0 + timedelta(seconds=61))
    for made, money in [(26, 0), (5, 6), (3, 4), (-1, 0)]:        # 불가능한 점수
        with pytest.raises(arcade.ArcadeError):
            arcade.finish_run(db, m, run.id, made, money, now=t0 + timedelta(seconds=61))
    with pytest.raises(arcade.ArcadeError):                       # 너무 오래 (방치)
        arcade.finish_run(db, m, run.id, 10, 2, now=t0 + timedelta(seconds=arcade.MAX_SECONDS + 1))
    done = arcade.finish_run(db, m, run.id, 25, 5, now=t0 + timedelta(seconds=61))
    assert done.score == 30 == arcade.MAX_SCORE
    with pytest.raises(arcade.ArcadeError):                       # 한 번만 저장
        arcade.finish_run(db, m, run.id, 1, 0, now=t0 + timedelta(seconds=62))


def test_daily_limit(db, monkeypatch):
    (m,) = _members(db, 1)
    monkeypatch.setattr(arcade, "DAILY_LIMIT", 2)
    t0 = dt.datetime(2026, 10, 22, 12, 0)
    arcade.start_run(db, m, now=t0)
    arcade.start_run(db, m, now=t0)
    with pytest.raises(arcade.ArcadeError):
        arcade.start_run(db, m, now=t0)
    arcade.start_run(db, m, now=t0 + timedelta(days=1))           # 다음 날은 다시 가능


def test_leaderboard_best_per_member_and_ties(db):
    a, b, c = _members(db, 3)
    now = arcade.now_kst()
    _played(db, a, 12, now - timedelta(minutes=30))
    _played(db, a, 20, now - timedelta(minutes=20))                # a 최고 20
    _played(db, b, 20, now - timedelta(minutes=10))                # b 도 20 (나중에 달성)
    _played(db, c, 7, now - timedelta(minutes=5))
    _played(db, c, 29, now - timedelta(days=400))                  # 다른 시즌·다른 주 → 제외
    rows = arcade.leaderboard(db, *arcade.week_range())
    assert [(r.member.name, r.score, r.rank) for r in rows] == [("슈터0", 20, 1), ("슈터1", 20, 1), ("슈터2", 7, 3)]


def test_arcade_api_and_pages(client, db):
    admin = _login_admin(client, db)
    (m,) = _members(db, 1)
    _played(db, admin, 18, arcade.now_kst() - timedelta(minutes=3))
    _login_as(client, db, m)

    page = client.get("/arcade")
    assert page.status_code == 200 and "3점슛 콘테스트" in page.text and '"num": "10"' in page.text
    assert "운영자" in page.text and "18" in page.text                 # 랭킹에 다른 사람 기록
    assert client.get("/arcade.js").status_code == 200

    r = client.post("/arcade/runs")
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    # 바로 끝내면 거부
    assert client.post(f"/arcade/runs/{run_id}/finish", json={"made": 9, "money": 1}).status_code == 400
    run = db.get(ArcadeRun, run_id)
    run.started_at -= timedelta(seconds=61)
    db.commit()
    r = client.post(f"/arcade/runs/{run_id}/finish", json={"made": 19, "money": 3})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["score"] == 22 and d["week_rank"] == 1 and d["new_week_best"] and d["new_season_best"]
    assert client.post(f"/arcade/runs/{run_id}/finish", json={"made": 19, "money": 3}).status_code == 400

    rank = client.get("/arcade/ranking?tab=season").text
    assert rank.index("슈터0") < rank.index("운영자") and "#10" in rank
    home = client.get("/").text
    assert "이번 주 슛왕" in home and "슈터0" in home and "22점" in home and 'href="/arcade"' in home

    client.cookies.clear()
    assert client.post("/arcade/runs").status_code == 401
    assert client.get("/arcade", follow_redirects=False).status_code == 303
