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
    assert done.score == 30                                       # 예전 화면(성공 수·머니볼 수) 방식도 인정
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


def test_score_shots_rules():
    perfect = "S" * arcade.SHOTS
    assert arcade.score_shots(perfect) == (arcade.MAX_SCORE, 26, 5) and arcade.MAX_SCORE == 41
    assert arcade.score_shots("M" * 25 + "-") == (30, 25, 5)                 # 콤보·로고샷 없음
    assert arcade.score_shots("SSXSSS" + "-" * 20)[0] == 1 + 1 + 1 + 2 + 1 + 1   # 5번째는 머니볼, 끊긴 뒤 다시 3연속 → +1
    assert arcade.score_shots("X" * 25 + "M")[0] == 3                        # 로고샷 3점
    assert arcade.score_shots("SSM" + "-" * 23)[0] == 3                      # 그냥 골은 스위시 콤보를 끊음


def test_finish_with_shots_validates_and_stores(db):
    m, = _members(db, 1)
    t0 = dt.datetime(2026, 10, 22, 12, 0, 0)
    for bad in ["S" * 25, "S" * 27, "SQ" + "-" * 24, "S-S" + "-" * 23]:
        run = arcade.start_run(db, m, now=t0)
        with pytest.raises(arcade.ArcadeError):
            arcade.finish_run(db, m, run.id, now=t0 + timedelta(seconds=50), shots=bad)
    run = arcade.start_run(db, m, now=t0)
    shots = "SSS" + "X" * 22 + "-"
    done = arcade.finish_run(db, m, run.id, made=99, money=99, now=t0 + timedelta(seconds=50),   # made/money 는 무시
                             shots=shots, events=[[1000, 1], [2000, 2], [3000, 4]])
    assert (done.score, done.made) == (4, 3) and done.detail == {"shots": shots, "ev": [[1000, 1], [2000, 2], [3000, 4]]}
    run = arcade.start_run(db, m, now=t0)
    done = arcade.finish_run(db, m, run.id, now=t0 + timedelta(seconds=50), shots=shots, events=[[1000, 9]])
    assert done.score == 4 and done.detail["ev"] is None                     # 말 안 되는 흐름은 버리고 기록은 인정


def test_challenge_flow_and_stats(client, db):
    _login_admin(client, db)
    a, b = _members(db, 2)
    now = arcade.now_kst()
    with pytest.raises(arcade.ArcadeError):                                  # 기록이 없으면 못 보냄
        arcade.send_challenge(db, a, b.id, now.year)
    _played(db, a, 12, now - timedelta(minutes=5))
    ch = arcade.send_challenge(db, a, b.id, now.year)
    assert ch.target == 12
    with pytest.raises(arcade.ArcadeError):                                  # 진행 중이면 또 못 보냄
        arcade.send_challenge(db, a, b.id, now.year)
    assert [c.id for c in arcade.challenges(db, b).incoming] == [ch.id]

    run = arcade.start_run(db, b, now=now - timedelta(seconds=50))
    done = arcade.finish_run(db, b, run.id, now=now, shots="M" * 10 + "X" * 15 + "-")   # 12점 → 못 깸
    assert done.score == 12 and done.beaten == []
    run = arcade.start_run(db, b, now=now - timedelta(seconds=50))
    done = arcade.finish_run(db, b, run.id, now=now, shots="M" * 13 + "X" * 12 + "-",
                             events=[[i * 1000, i + 1] for i in range(13)])
    assert done.score == 15 and [c.id for c in done.beaten] == [ch.id]      # 13개 중 2개가 머니볼
    assert arcade.challenges(db, b).incoming == [] and arcade.challenges(db, a).outgoing[0].beaten_score == 15

    st = arcade.my_stats(db, b, now.year)
    assert st.plays == 2 and st.best == 15 and st.tracked == 2
    assert (st.spots[0].made, st.spots[0].att) == (10, 10) and (st.spots[2].made, st.spots[2].att) == (3, 10)
    assert st.spots[5].att == 0

    _login_as(client, db, a)
    page = client.get("/arcade").text
    assert "⚔️ 도전장" in page and "깨졌어요" in page
    assert "슈터1님이 내 도전장을 깼어요" in client.get("/").text
    dlg = client.get(f"/arcade/challenge/{b.id}").text
    assert "도전장 보내기" in dlg and "12점" in dlg
    r = client.post("/arcade/challenges", data={"to_id": b.id})
    assert "보냈어요" in r.text and r.headers.get("HX-Trigger") == "arcadeChanged"
    assert "진행 중" in client.post("/arcade/challenges", data={"to_id": b.id}).text
    assert "보냄" in client.get("/arcade/ranking?tab=week").text

    _login_as(client, db, b)
    home = client.get("/").text
    assert "슈터0님의 도전장" in home
    stats = client.get("/arcade/stats").text
    assert "지점별 성공률" in stats and "좌 코너" in stats and "100%" in stats


def test_ghosts_need_score_timeline(db):
    a, b = _members(db, 2)
    now = arcade.now_kst()
    _played(db, b, 20, now - timedelta(minutes=9))                           # 예전 판: 흐름 없음 → 고스트 없음
    assert arcade.ghosts(db, a, now.year) == []
    run = arcade.start_run(db, a, now=now - timedelta(seconds=50))
    arcade.finish_run(db, a, run.id, now=now, shots="M" * 3 + "X" * 22 + "-", events=[[500, 1], [900, 2], [1500, 3]])
    gs = arcade.ghosts(db, a, now.year)
    assert [g["label"] for g in gs] == ["내 최고"] and gs[0]["ev"][-1] == [1500, 3]


def test_full_ranking_beyond_top10(client, db):
    ms = _members(db, 13)
    now = arcade.now_kst()
    for i, m in enumerate(ms):
        _played(db, m, 30 - i, now - timedelta(minutes=i + 1))
    _login_as(client, db, ms[12])
    html = client.get("/arcade/ranking").text
    assert "전체 순위 보기 (13명)" in html and "rk-more hidden" in html and "rk-mine" in html
