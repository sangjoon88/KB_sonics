"""화면/API 통합 테스트: setup, rating-setup, 팀 짜기 차단, 하루 흐름."""
from sqlalchemy import select

from app.auth import hash_pin
from app.models import Game, Member
from app.services import ops

TOKEN = "test-setup-token"


def _login_as(client, db, m, pin="1234"):
    """테스트용: PIN이 없는 멤버는 PIN을 부여(변경 완료 상태)하고 이름+PIN으로 로그인."""
    if not m.pin_hash:
        m.pin_hash = hash_pin(pin)
        m.pin_must_change = False
        db.commit()
    client.cookies.clear()
    r = client.post("/pick/pin", data={"member_id": m.id, "pin": pin}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r


def _setup_admin(client, name="운영자", pin="1234"):
    r = client.post("/setup", data={"token": TOKEN, "name": name, "position": "G", "height": "180",
                                    "pin": pin, "pin2": pin}, follow_redirects=False)
    assert r.status_code == 303
    return r


def test_setup_closes_after_first_admin(client):
    assert client.get(f"/setup?token={TOKEN}").status_code == 200
    assert client.get("/setup?token=wrong").status_code == 404
    _setup_admin(client)
    assert client.get(f"/setup?token={TOKEN}").status_code == 404
    r = client.post("/setup", data={"token": TOKEN, "name": "x", "pin": "1111", "pin2": "1111"})
    assert r.status_code == 404


def test_rating_setup_average_and_disagree(db):
    admins = [Member(name=f"a{i}", is_admin=True) for i in range(3)]
    target = [Member(name="t1"), Member(name="t2")]
    db.add_all(admins + target)
    db.commit()
    ops.save_my_grades(db, admins[0], {target[0].id: 3, target[1].id: 2})
    ops.save_my_grades(db, admins[1], {target[0].id: 4, target[1].id: 4})
    ops.save_my_grades(db, admins[2], {target[0].id: 4, target[1].id: 3})
    rows = {r.member.name: r for r in ops.grade_rows(db, admins[0])}
    assert rows["t1"].avg == round(11 / 3, 2) and rows["t1"].disagree is False
    assert rows["t2"].avg == 3.0 and rows["t2"].disagree is True
    ops.confirm_grades(db, admins[0], {target[0].id: rows["t1"].avg})
    assert target[0].initial_grade == 3.67
    assert target[0].mu == 13 + 4 * 3.67


def _login_admin(client, db):
    _setup_admin(client)
    return db.scalar(select(Member).where(Member.name == "운영자"))


def test_team_api_rejected_before_confirm(client, db):
    admin = _login_admin(client, db)
    members = [Member(name=f"p{i}", position="GFC"[i % 3], height_cm=170 + i) for i in range(11)]
    db.add_all(members)
    db.commit()
    s = ops.create_session(db, admin, __import__("datetime").date(2026, 10, 18))
    for m in [admin, *members]:
        ops.set_checkin(db, admin, s, m.id, True)
    r = client.post(f"/api/sessions/{s.id}/games/1/lineup")
    assert r.status_code == 400 and "미확정" in r.json()["detail"]
    ops.confirm_grades(db, admin, {m.id: 3.0 for m in [admin, *members]})
    r = client.post(f"/api/sessions/{s.id}/games/1/lineup")
    assert r.status_code == 200
    body = r.json()
    assert sorted([len(body["team_a"]), len(body["team_b"])]) == [6, 6]


def test_api_requires_admin(client):
    assert client.post("/api/sessions", json={}).status_code == 401
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_full_sunday_flow(client, db):
    admin = _login_admin(client, db)
    rnd = __import__("random").Random(3)
    members = [Member(name=f"p{i}", position="GFC"[i % 3], height_cm=rnd.randint(168, 192)) for i in range(11)]
    db.add_all(members)
    db.commit()
    everyone = [admin, *members]
    ops.confirm_grades(db, admin, {m.id: float(1 + i % 5) for i, m in enumerate(everyone)})

    r = client.post("/admin/sessions", data={"session_date": "2026-10-18", "location": "체육관"},
                    follow_redirects=False)
    sid = int(r.headers["location"].split("/admin/s/")[1].split("?")[0])

    # 멤버 투표 (본인 쿠키로)
    voter = members[0]
    from app.auth import set_member_cookie  # noqa: F401
    _login_as(client, db, voter)
    r = client.post(f"/s/{sid}/vote", data={"vote": "yes"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "참석" in r.text
    # 다른 멤버 사칭 API 투표는 거부
    assert client.put(f"/api/sessions/{sid}/vote", json={"member_id": members[1].id, "vote": "yes"}).status_code == 403

    # 다른 사람으로 바꾸면 운영진 로그인도 풀린다 → 관리자 이름 + PIN으로 다시 선택
    assert client.get("/admin", follow_redirects=False).status_code == 303
    client.post("/pick/pin", data={"member_id": admin.id, "pin": "1234", "next": "/"})
    for m in everyone:
        client.post(f"/admin/s/{sid}/checkin/{m.id}")
    assert client.get(f"/admin/s/{sid}/checkin").status_code == 200

    client.post(f"/admin/s/{sid}/game/1/generate")
    page = client.get(f"/admin/s/{sid}/game/1/lineup")
    assert "다시 섞기" in page.text
    client.post(f"/admin/s/{sid}/game/1/next", headers={"HX-Request": "true"})
    g1 = db.scalar(select(Game).where(Game.session_id == sid, Game.game_no == 1))
    assert g1.candidate_idx == 1
    moved_id = g1.roster[0].member_id
    side_before = g1.roster[0].side
    client.post(f"/admin/s/{sid}/game/1/move/{moved_id}", headers={"HX-Request": "true"})
    db.expire_all()
    assert next(r.side for r in g1.roster if r.member_id == moved_id) != side_before
    client.post(f"/admin/s/{sid}/game/1/move/{moved_id}")

    r = client.post(f"/admin/s/{sid}/game/1/score", data={"score_a": 50, "score_b": 20}, follow_redirects=False)
    assert "/game/2/choose" in r.headers["location"]
    assert "재편성 권장" in client.get(f"/admin/s/{sid}/game/2/choose").text

    client.post(f"/admin/s/{sid}/game/2/choose", data={"mode": "reshuffled"})
    g2 = db.scalar(select(Game).where(Game.session_id == sid, Game.game_no == 2))
    assert g2.lineup_mode == "reshuffled"
    from app.services.balancer import swaps_vs
    g1_sides = {r.member_id: r.side for r in g1.roster}
    assert swaps_vs([r.member_id for r in g2.roster if r.side == "A"],
                    [r.member_id for r in g2.roster if r.side == "B"], g1_sides) >= 2

    client.post(f"/admin/s/{sid}/game/2/score", data={"score_a": 33, "score_b": 31})
    # 게임 1 점수 수정 → 재계산
    client.post(f"/admin/s/{sid}/game/1/score", data={"score_a": 40, "score_b": 38})
    db.expire_all()
    assert g1.score_a == 40 and g1.lopsided is False

    day = client.get(f"/s/{sid}/day")
    assert day.status_code == 200 and "게임 2" in day.text
    assert "mu" not in client.get(f"/s/{sid}/day/partial").text

    stats = client.get("/api/stats?season=2026").json()
    assert {s["name"] for s in stats} >= {"운영자", "p0"}
    assert all("mu" not in s for s in stats)
    assert client.get("/stats").status_code == 200
    ratings_page = client.get("/admin/ratings").text
    assert "신뢰도" in ratings_page and "<th>mu</th>" not in ratings_page
    assert "grade" in client.get("/api/admin/ratings").json()[0]
    assert "팀 평균 실력" in client.get(f"/admin/s/{sid}/game/2/lineup").text
    assert client.get("/admin/logs").status_code == 200
    assert client.get("/admin/rating-setup").status_code == 200
    assert client.get("/admin/members").status_code == 200
    assert client.get("/me").status_code == 200


def test_pin_lockout(client, db):
    m = Member(name="관리", is_admin=True, pin_hash=hash_pin("1234"))
    db.add(m)
    db.commit()
    for _ in range(5):
        r = client.post("/admin/login", data={"member_id": m.id, "pin": "0000"}, follow_redirects=False)
    assert m.pin_locked_until is not None
    r = client.post("/admin/login", data={"member_id": m.id, "pin": "1234"}, follow_redirects=False)
    assert "/admin/login" in r.headers["location"]  # 잠금 중에는 올바른 PIN도 거부


def test_new_member_default_pin_flow(client, db):
    admin = _login_admin(client, db)
    m = ops.create_member(db, admin, "신입")
    assert m.pin_must_change and m.position is None
    client.cookies.clear()
    r = client.post("/pick", data={"member_id": m.id, "next": "/"})
    assert "초기 PIN" in r.text and "1234" in r.text
    r = client.post("/pick/pin", data={"member_id": m.id, "pin": "1234"}, follow_redirects=False)
    assert r.headers["location"].startswith("/pin")
    # PIN을 바꾸기 전에는 다른 화면으로 못 간다
    assert client.get("/", follow_redirects=False).headers["location"].startswith("/pin")
    # 1234 그대로는 안 됨
    r = client.post("/pin", data={"pin": "1234", "pin2": "1234", "next": "/"})
    assert r.status_code == 400 and "다른 번호" in r.text
    r = client.post("/pin", data={"pin": "2580", "pin2": "2580", "next": "/"}, follow_redirects=False)
    assert r.headers["location"].startswith("/profile")       # 첫 로그인: 다음은 내 정보 입력
    assert client.get("/", follow_redirects=False).headers["location"].startswith("/profile")
    # 주 포지션·키 필수, 부 포지션·몸무게 선택
    r = client.post("/profile", data={"position2": "F", "height": "180"}, follow_redirects=False)
    assert "err=" in r.headers["location"]
    client.post("/profile", data={"position": "G", "position2": "F", "height": "180", "weight": "72"})
    db.refresh(m)
    assert (m.position, m.position2, m.height_cm, m.weight_kg, m.pin_must_change) == ("G", "F", 180, 72, False)
    assert client.get("/", follow_redirects=False).status_code == 200
    # 이제 1234로는 로그인 불가, 새 PIN으로 가능
    client.cookies.clear()
    assert client.post("/pick/pin", data={"member_id": m.id, "pin": "1234"}).status_code == 400
    assert client.post("/pick/pin", data={"member_id": m.id, "pin": "2580"}, follow_redirects=False).status_code == 303
    # 운영진이 초기화하면 다시 1234 + 변경 강제
    ops.reset_pin(db, admin, m)
    client.cookies.clear()
    r = client.post("/pick/pin", data={"member_id": m.id, "pin": "1234"}, follow_redirects=False)
    assert r.headers["location"].startswith("/pin")


def test_weight_private(client, db):
    admin = _login_admin(client, db)
    m = ops.create_member(db, admin, "몸무게", "G", 175)
    ops.update_member(db, admin, m, weight=80)
    assert all("weight_kg" not in x for x in client.get("/api/members").json())
    assert "80" in client.get("/admin/members").text


def test_first_visit_requires_name(client, db):
    _setup_admin(client)
    client.cookies.clear()
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/pick")


def test_picking_admin_name_requires_pin(client, db):
    admin = _login_admin(client, db)
    client.cookies.clear()
    r = client.post("/pick", data={"member_id": admin.id, "next": "/"}, follow_redirects=False)
    assert r.status_code == 200 and "PIN" in r.text and "관리자" in r.text   # 쿠키 없이 PIN 화면
    assert "bc_member" not in r.cookies
    r = client.post("/pick/pin", data={"member_id": admin.id, "pin": "9999"}, follow_redirects=False)
    assert r.status_code == 400 and "틀렸습니다" in r.text
    r = client.post("/pick/pin", data={"member_id": admin.id, "pin": "1234"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/admin", follow_redirects=False).status_code == 200  # 운영진 로그인까지 한 번에


def test_only_owner_manages_staff(client, db):
    owner = _login_admin(client, db)
    assert owner.is_owner
    staff, other = Member(name="스태프"), Member(name="일반")
    db.add_all([staff, other])
    db.commit()
    ops.set_admin_role(db, owner, staff, True)
    assert staff.is_admin and not staff.is_owner and staff.pin_must_change
    import pytest
    with pytest.raises(ops.OpError):
        ops.set_admin_role(db, staff, other, True)       # 운영진은 지정 불가
    with pytest.raises(ops.OpError):
        ops.reset_pin(db, staff, staff)                  # 운영진 PIN 초기화는 관리자만
    with pytest.raises(ops.OpError):
        ops.reset_pin(db, staff, owner)
    ops.reset_pin(db, staff, other)                      # 일반 멤버는 운영진도 초기화 가능
    with pytest.raises(ops.OpError):
        ops.set_admin_role(db, owner, owner, False)      # 관리자 권한은 못 바꿈
    # 운영진 화면에서는 지정 버튼이 안 보인다
    client.cookies.clear()
    client.post("/pick/pin", data={"member_id": staff.id, "pin": "1234"})
    client.post("/pin", data={"pin": "4321", "pin2": "4321"})
    page = client.get("/admin/members").text
    assert "🛡️ 운영진 지정" not in page and "관리자만" in page
    ops.set_admin_role(db, owner, staff, False)
    assert not staff.is_admin and staff.pin_hash   # 운영진 해제돼도 본인 PIN은 유지


def test_early_leave_vote(client, db):
    admin = _login_admin(client, db)
    m = Member(name="조퇴맨", position="G", height_cm=175)
    db.add(m)
    db.commit()
    import datetime as _dt
    s = ops.create_session(db, admin, _dt.date(2099, 1, 4))
    _login_as(client, db, m)
    hx = {"HX-Request": "true"}
    # 시간 없이 조퇴 → 오류 메시지, 저장 안 됨
    r = client.post(f"/s/{s.id}/vote", data={"vote": "early", "leave_time": ""}, headers=hx)
    assert "조퇴 시간을 입력" in r.text
    assert ops.get_attendance(db, s, m.id) is None
    r = client.post(f"/s/{s.id}/vote", data={"vote": "early", "leave_time": "15:30"}, headers=hx)
    a = ops.get_attendance(db, s, m.id)
    assert a.vote == "early" and a.leave_time == "15:30"
    assert r.headers.get("HX-Trigger") == "voteChanged"
    live = client.get(f"/s/{s.id}/live").text
    assert "조퇴맨" in live.split("참석", 1)[1]          # 조퇴도 참석 명단에 (시간은 예상 팀에서 표시)
    a_after = ops.get_attendance(db, s, m.id)
    assert a_after.leave_time == "15:30"
    # 참석으로 바꾸면 조퇴 시간은 지워진다
    client.post(f"/s/{s.id}/vote", data={"vote": "yes", "leave_time": "15:30"}, headers=hx)
    db.refresh(a)
    assert a.vote == "yes" and a.leave_time is None
    # 미정은 더 이상 받지 않는다
    r = client.post(f"/s/{s.id}/vote", data={"vote": "maybe"}, headers=hx)
    assert "투표 값" in r.text
    # API
    assert client.put(f"/api/sessions/{s.id}/vote", json={"member_id": m.id, "vote": "early"}).status_code == 400
    r = client.put(f"/api/sessions/{s.id}/vote", json={"member_id": m.id, "vote": "early", "leave_time": "9:05"})
    assert r.json()["leave_time"] == "09:05"


def test_guest_flow(client, db):
    import datetime as _dt
    admin = _login_admin(client, db)
    members = [Member(name=f"g{i}", position="GFC"[i % 3], height_cm=170 + i) for i in range(10)]
    db.add_all(members)
    db.commit()
    ops.confirm_grades(db, admin, {m.id: 3.0 for m in [admin, *members]})
    s = ops.create_session(db, admin, _dt.date(2099, 1, 4))
    host = members[0]
    _login_as(client, db, host)
    hx = {"HX-Request": "true"}

    r = client.post(f"/s/{s.id}/guests", data={"name": "친구A", "grade": "4", "height": "185", "position": "C"}, headers=hx)
    assert "친구A" in r.text  # 내가 데려오는 게스트
    assert "게스트 1 포함" in client.get(f"/s/{s.id}/live").text
    guest = db.scalar(select(Member).where(Member.name == "친구A"))
    assert guest.is_guest and not guest.is_active and guest.mu == 13 + 4 * 4
    # 기존 멤버 이름으로는 게스트 등록 불가
    r = client.post(f"/s/{s.id}/guests", data={"name": "g1"}, headers=hx)
    assert "이미 멤버" in r.text
    # 게스트는 이름 선택·멤버 API·기록에서 제외
    assert "친구A" not in client.get("/pick").text
    assert all(m["name"] != "친구A" for m in client.get("/api/members").json())

    # 운영진: 현장 게스트 추가 + 팀 짜기에 포함
    client.cookies.clear()
    client.post("/pick/pin", data={"member_id": admin.id, "pin": "1234"})
    client.post(f"/admin/s/{s.id}/guests", data={"name": "현장손님", "grade": "2"})
    for m in [admin, *members]:
        ops.set_checkin(db, admin, s, m.id, True)
    ops.set_checkin(db, admin, s, guest.id, True)
    assert "현장손님" in client.get(f"/admin/s/{s.id}/checkin").text
    r = client.post(f"/api/sessions/{s.id}/games/1/lineup")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()["team_a"] + r.json()["team_b"]}
    assert {"친구A", "현장손님"} <= names and len(names) == 13
    # 명단에 들어간 게스트는 빼기 전 오류
    r = client.post(f"/admin/s/{s.id}/guests/{guest.id}/remove", follow_redirects=False)
    assert "err=" in r.headers["location"]

    # 경기 후 기록에는 게스트 제외
    g1 = db.scalar(select(Game).where(Game.session_id == s.id))
    ops.submit_result(db, admin, g1, 40, 30)
    assert all(row["name"] not in ("친구A", "현장손님") for row in client.get("/api/stats?season=2099").json())

    # 운영진이 같은 이름으로 멤버 추가 → 정식 멤버로 전환 (레이팅 유지)
    mu = guest.mu
    promoted = ops.create_member(db, admin, "친구A")
    assert promoted.id == guest.id and not promoted.is_guest and promoted.is_active and promoted.mu == mu


def test_guest_cancel_only_by_inviter(client, db):
    import datetime as _dt
    admin = _login_admin(client, db)
    a, b = Member(name="초대자"), Member(name="남")
    db.add_all([a, b])
    db.commit()
    s = ops.create_session(db, admin, _dt.date(2099, 1, 11))
    att = ops.add_guest(db, s, a, "손님")
    with __import__("pytest").raises(ops.OpError):
        ops.remove_guest(db, s, att.member_id, actor=b)
    ops.remove_guest(db, s, att.member_id, actor=a)
    assert ops.get_attendance(db, s, att.member_id) is None


def test_preview_and_proxy_vote(client, db):
    import datetime as _dt
    admin = _login_admin(client, db)
    members = [Member(name=f"v{i}", position="GFC"[i % 3], height_cm=170 + i) for i in range(9)]
    db.add_all(members)
    db.commit()
    ops.confirm_grades(db, admin, {m.id: 3.0 for m in [admin, *members]})
    s = ops.create_session(db, admin, _dt.date(2099, 2, 1))
    for m in members[:3]:
        ops.vote(db, s, m, "yes")
    assert ops.preview_teams(db, s)["status"] == "few"

    # 운영진 대리 투표 (마감 후에도 가능)
    s.status = "closed"
    db.commit()
    hx = {"HX-Request": "true"}
    r = client.post(f"/s/{s.id}/proxy", data={"member_id": members[3].id, "vote": "yes"}, headers=hx)
    assert r.status_code == 200 and r.headers.get("HX-Trigger") == "voteChanged"
    r = client.post(f"/s/{s.id}/proxy", data={"member_id": members[4].id, "vote": "early", "leave_time": "11:00"}, headers=hx)
    a = ops.get_attendance(db, s, members[4].id)
    assert a.vote == "early" and a.leave_time == "11:00" and a.proxy_by == admin.id
    pv = ops.preview_teams(db, s)
    assert pv["status"] == "ok" and pv["n"] == 5 and len(pv["a"]) + len(pv["b"]) == 5

    live = client.get(f"/s/{s.id}/live").text
    assert "예상 팀" in live and "대리" in live and "mu" not in live
    client.post(f"/s/{s.id}/proxy", data={"member_id": members[3].id, "vote": "clear"}, headers=hx)
    assert ops.get_attendance(db, s, members[3].id).vote is None
    # API 대리 투표
    r = client.put(f"/api/sessions/{s.id}/vote", json={"member_id": members[5].id, "vote": "no"})
    assert r.json()["proxy"] is True

    # 일반 멤버는 대리 투표 불가
    _login_as(client, db, members[0])
    assert client.post(f"/s/{s.id}/proxy", data={"member_id": members[6].id, "vote": "yes"}).status_code == 403
    # 본인이 직접 투표하면 대리 표시 해제
    s.status = "open"
    db.commit()
    _login_as(client, db, members[4])
    client.post(f"/s/{s.id}/vote", data={"vote": "yes"}, headers=hx)
    db.refresh(a)
    assert a.proxy_by is None
    # 홈 화면 렌더
    home = client.get("/").text
    assert "예상 팀" in home and "시즌" in home


def test_rating_setup_lists_only_pending(client, db):
    admin = _login_admin(client, db)
    a, b, c = Member(name="평가A"), Member(name="평가B"), Member(name="평가C")
    db.add_all([a, b, c])
    db.commit()

    def section(html, start, end):
        return html.split(start, 1)[1].split(end, 1)[0]

    page = client.get("/admin/rating-setup").text
    mine = section(page, "① 내 평가", "내 평가 제출")
    assert all(n in mine for n in ("평가A", "평가B", "평가C")) and "이미 평가" not in mine

    # A, B 평가 제출 → ①에서는 C만 남고, ②에 A, B 확정 대기
    client.post("/admin/rating-setup/mine", data={f"g_{a.id}": "3", f"g_{b.id}": "4"})
    page = client.get("/admin/rating-setup").text
    pending = section(page, "① 내 평가", "이미 평가했거나")
    assert "평가C" in pending and "평가A" not in pending and "평가B" not in pending
    confirm = section(page, "② 평균 확인", "명 확정</button>")
    assert "평가A" in confirm and "평가B" in confirm and "평가C" not in confirm

    # A만 확정 → 확정 대기에서 빠지고 '다시 조정'으로
    client.post("/admin/rating-setup/confirm", data={f"c_{a.id}": "3"})
    page = client.get("/admin/rating-setup").text
    confirm = section(page, "② 평균 확인", "확정된 멤버 다시 조정")
    assert "평가B" in confirm and "평가A" not in confirm
    assert "평가A" in page.split("확정된 멤버 다시 조정", 1)[1]


def test_session_defaults(client, db):
    import datetime as _dt
    from app.config import DEFAULT_LOCATION
    admin = _login_admin(client, db)
    r = client.post("/admin/sessions", data={"session_date": "2099-03-01", "start_time": "08:00",
                                             "location": DEFAULT_LOCATION}, follow_redirects=False)
    sid = int(r.headers["location"].split("/admin/s/")[1].split("?")[0])
    s = db.get(__import__("app.models", fromlist=["ClubSession"]).ClubSession, sid)
    assert s.start_time == "08:00" and s.location == DEFAULT_LOCATION and s.vote_deadline is None
    assert ops.voting_open(s)
    # 대시보드 폼에 기본값이 채워져 있다
    page = client.get("/admin").text
    assert 'value="08:00"' in page and DEFAULT_LOCATION in page and "vote_deadline" not in page
    # 투표 화면: 시간·장소·지도 링크
    vote_page = client.get(f"/s/{sid}").text
    assert "08:00 시작" in vote_page and "map.naver.com" in vote_page
    # 시간·장소 수정
    client.post(f"/admin/s/{sid}/info", data={"start_time": "9:30", "location": "다른 체육관"})
    db.refresh(s)
    assert (s.start_time, s.location) == ("09:30", "다른 체육관")
    # API 기본값
    api_s = client.post("/api/sessions", json={"date": "2099-03-08"}).json()
    assert api_s["start_time"] == "08:00" and api_s["location"] == DEFAULT_LOCATION and api_s["vote_deadline"] is None


def test_two_positions_everywhere(client, db):
    import datetime as _dt
    # 관리자 계정 생성
    client.post("/setup", data={"token": TOKEN, "name": "주인", "position": "G", "position2": "F",
                                "height": "180", "weight": "75", "pin": "1234", "pin2": "1234"})
    owner = db.scalar(select(Member).where(Member.name == "주인"))
    assert (owner.position, owner.position2, owner.weight_kg) == ("G", "F", 75)
    # 멤버 1명 추가
    client.post("/admin/members/new", data={"name": "추가1", "position": "C", "position2": "F", "height": "190"})
    m = db.scalar(select(Member).where(Member.name == "추가1"))
    assert (m.position, m.position2, m.height_cm) == ("C", "F", 190)
    # 주/부가 같으면 부 포지션은 비운다
    client.post("/admin/members/new", data={"name": "추가2", "position": "G", "position2": "G"})
    assert db.scalar(select(Member).where(Member.name == "추가2")).position2 is None
    # 게스트 (운영진 출석 체크 화면)
    s = ops.create_session(db, owner, _dt.date(2099, 4, 5))
    client.post(f"/admin/s/{s.id}/guests", data={"name": "손님2", "position": "F", "position2": "C"})
    g = db.scalar(select(Member).where(Member.name == "손님2"))
    assert (g.position, g.position2) == ("F", "C")
    # 화면에 select 두 개가 있다
    for url in ("/admin/members", f"/admin/s/{s.id}/checkin"):
        assert 'name="position2"' in client.get(url).text


def test_checkin_closes_voting_only_on_game_day(client, db):
    import datetime as _dt
    from app.timeutil import today_kst
    admin = _login_admin(client, db)
    future = ops.create_session(db, admin, today_kst() + _dt.timedelta(days=1))
    ops.set_checkin(db, admin, future, admin.id, True)
    assert future.status == "open" and ops.voting_open(future)       # 전날 미리 눌러봐도 투표 유지
    today = ops.create_session(db, admin, today_kst())
    ops.set_checkin(db, admin, today, admin.id, True)
    assert today.status == "closed"                                   # 당일 체크인 → 투표 마감


def test_attendance_counts_only_played_days(client, db):
    import datetime as _dt
    from app.services.stats import compute_stats, leaderboard
    admin = _login_admin(client, db)
    ps = [Member(name=f"a{i}", position="GFC"[i % 3], height_cm=175 + i) for i in range(5)]
    no_show = Member(name="노쇼", position="G", height_cm=170)
    db.add_all([*ps, no_show])
    db.commit()
    ops.confirm_grades(db, admin, {m.id: 3.0 for m in [admin, *ps, no_show]})
    s = ops.create_session(db, admin, _dt.date(2099, 5, 3))
    ops.vote(db, s, no_show, "yes")                           # 투표만 하고 안 옴
    for m in [admin, *ps]:
        ops.set_checkin(db, admin, s, m.id, True)
    g1 = ops.generate_game1(db, admin, s)
    early = ps[0]                                            # 게임 1만 뛰고 감
    ops.submit_result(db, admin, g1, 30, 20)
    ops.set_checkin(db, admin, s, early.id, False)
    g2 = ops.create_game2(db, admin, s, "kept")
    ops.submit_result(db, admin, g2, 25, 30)
    db.expire_all()   # 실제 서비스는 요청마다 새 세션 — 테스트에서는 한 세션을 계속 쓰므로 새로 읽게 한다
    st = compute_stats(db, 2099)
    assert st[no_show.id].attended == 0
    assert st[early.id].attended == 1 and st[early.id].games == 1      # 1게임만 뛰어도 출석 1회
    assert st[ps[1].id].attended == 1 and st[ps[1].id].games == 2
    assert leaderboard(st, "attendance")[0].games == 2                 # 출석 같으면 경기 수 많은 쪽 먼저


def test_member_summary(client, db):
    from app.services.stats import member_summary
    from app.timeutil import today_kst
    admin = _login_admin(client, db)   # G, 180
    ops.create_member(db, admin, "센터1", "C", 190, "F")
    ops.create_member(db, admin, "포워드1", "F", 182)
    ops.create_member(db, admin, "미입력")
    ms = member_summary(db, today_kst())
    assert ms["total"] == 4 and ms["staff"] == 1
    assert ms["avg_height"] == round((180 + 190 + 182) / 3, 1)
    assert ms["main"] == {"G": 1, "F": 1, "C": 1} and ms["able"] == {"G": 1, "F": 2, "C": 1}
    assert ms["not_logged_in"] == 3 and ms["no_height"] == 1
    # 홈(모든 멤버)에는 집계표, 운영진 전용 항목은 멤버 관리 화면에만
    home = client.get("/").text
    assert "소닉스 식구들" in home and "첫 로그인 전" not in home
    assert "출석왕" in home and "첫 경기가 끝나면 순위가 나와요" in home   # 기록이 없어도 랭킹 카드 표시
    page = client.get("/admin/members").text
    assert "소닉스 식구들" in page and "첫 로그인 전 3명" in page and "일괄 등록" not in page
    assert client.get("/admin/members/import").status_code in (404, 405)


def test_winrate_threshold_grows_with_season():
    from app.services.stats import winrate_min_games
    assert winrate_min_games(0) == 1 and winrate_min_games(2) == 1
    assert winrate_min_games(10) == 3 and winrate_min_games(20) == 6 and winrate_min_games(80) == 24


def test_game2_remove_player(client, db):
    """게임 1만 뛰고 가는 사람: 게임 2 명단에서 빼기. 재편성이면 남은 인원으로 다시 밸런싱."""
    import datetime as _dt
    admin = _login_admin(client, db)
    rnd = __import__("random").Random(7)
    ps = [Member(name=f"r{i}", position="GFC"[i % 3], height_cm=rnd.randint(168, 192)) for i in range(9)]
    db.add_all(ps)
    db.commit()
    everyone = [admin, *ps]
    ops.confirm_grades(db, admin, {m.id: float(1 + i % 5) for i, m in enumerate(everyone)})
    s = ops.create_session(db, admin, _dt.date(2099, 6, 7))
    for m in everyone:
        ops.set_checkin(db, admin, s, m.id, True)
    g1 = ops.generate_game1(db, admin, s)
    ops.submit_result(db, admin, g1, 50, 20)
    leaver = ps[0]

    # 재편성: 빼면 9명으로 다시 짜고, 후보안에도 뺀 사람이 없다
    client.post(f"/admin/s/{s.id}/game/2/choose", data={"mode": "reshuffled"})
    page = client.get(f"/admin/s/{s.id}/game/2/lineup").text
    assert f"/game/2/remove/{leaver.id}" in page
    assert "/game/1/remove/" not in client.get(f"/admin/s/{s.id}/game/1/lineup").text
    r = client.post(f"/admin/s/{s.id}/game/2/remove/{leaver.id}", headers={"HX-Request": "true"})
    assert r.status_code == 200
    db.expire_all()
    g2 = ops.get_game(db, s, 2)
    ids = [r.member_id for r in g2.roster]
    assert leaver.id not in ids and len(ids) == 9
    na = sum(1 for r in g2.roster if r.side == "A")
    assert abs(na - (9 - na)) <= 1
    assert g2.candidates and all(leaver.id not in a + b for a, b in g2.candidates)
    client.post(f"/admin/s/{s.id}/game/2/next", headers={"HX-Request": "true"})
    db.expire_all()
    assert leaver.id not in [r.member_id for r in g2.roster]
    assert f"+ {leaver.name}" in client.get(f"/admin/s/{s.id}/game/2/lineup").text   # 실수로 뺐으면 다시 추가 가능

    # 팀 유지: 나머지는 게임 1 팀 그대로, 그 사람만 빠진다
    client.post(f"/admin/s/{s.id}/game/2/choose", data={"mode": "kept"})
    db.expire_all()
    g1_sides = {r.member_id: r.side for r in g1.roster}
    client.post(f"/admin/s/{s.id}/game/2/remove/{leaver.id}", headers={"HX-Request": "true"})
    db.expire_all()
    sides = {r.member_id: r.side for r in g2.roster}
    assert leaver.id not in sides and len(sides) == 9
    assert all(g1_sides[mid] == side for mid, side in sides.items())

    # 결과 입력 후엔 뺄 수 없고, 버튼도 안 보인다
    ops.submit_result(db, admin, g2, 30, 28)
    assert "/game/2/remove/" not in client.get(f"/admin/s/{s.id}/game/2/lineup").text


def test_comments(client, db):
    import datetime as _dt
    admin = _login_admin(client, db)
    a, b = Member(name="댓글A"), Member(name="댓글B")
    db.add_all([a, b])
    db.commit()
    s = ops.create_session(db, admin, _dt.date(2099, 6, 7))
    hx = {"HX-Request": "true"}
    _login_as(client, db, a)
    a.position, a.height_cm = "G", 175
    db.commit()
    r = client.post(f"/s/{s.id}/comments", data={"body": "10분 늦어요 <script>alert(1)</script>"}, headers=hx)
    assert "10분 늦어요" in r.text and "<script>alert" not in r.text        # HTML은 이스케이프
    assert client.post(f"/s/{s.id}/comments", data={"body": "   "}, headers=hx).text.count("내용을 입력") == 1
    home = client.get("/").text
    assert 'id="comment-list"' in home and "10분 늦어요" in home   # 댓글은 홈 화면에
    assert 'id="comment-list"' not in client.get(f"/s/{s.id}").text
    cid = ops.list_comments(db, s)[0].id
    # 다른 멤버는 못 지움
    b.position, b.height_cm = "F", 180
    db.commit()
    _login_as(client, db, b)
    r = client.post(f"/s/{s.id}/comments/{cid}/delete", headers=hx)
    assert "내가 쓴 글만" in r.text and len(ops.list_comments(db, s)) == 1
    # 운영진은 지울 수 있음
    client.cookies.clear()
    client.post("/pick/pin", data={"member_id": admin.id, "pin": "1234"})
    client.post(f"/s/{s.id}/comments/{cid}/delete", headers=hx)
    assert ops.list_comments(db, s) == []


def test_pending_voters_and_merged_early(client, db):
    import datetime as _dt
    admin = _login_admin(client, db)
    x, y, z = Member(name="일찍감", position="G", height_cm=175), Member(name="안옴", position="F", height_cm=180), \
        Member(name="미투표자", position="C", height_cm=190)
    db.add_all([x, y, z])
    db.commit()
    s = ops.create_session(db, admin, _dt.date(2099, 6, 14))
    ops.vote(db, s, x, "early", "09:00")
    ops.vote(db, s, y, "no")
    live = client.get(f"/s/{s.id}/live").text
    assert "아직 투표 안 함 2명" in live and "미투표자" in live            # 관리자 본인 + 미투표자
    assert "조퇴" not in live.split("오는 사람", 1)[1]                      # 참석 현황에는 조퇴 구분 없음
    assert "일찍감" in live
    home = client.get("/").text
    assert "미투표 2명" in home                                    # 홈은 숫자 배지, 누르면 이름 목록
    assert 'id="pending-list"' in home and "미투표자" in home.split('id="pending-list"', 1)[1]


def test_back_number(client, db):
    """백넘버: 본인이 내 정보에서 수정, 없으면 '-', 팀/참석 명단에 이름 앞 표시."""
    import datetime as _dt
    import pytest
    assert ops.parse_back_number("") is None and ops.parse_back_number("-") is None
    assert ops.parse_back_number("07") == "7" and ops.parse_back_number("00") == "00" and ops.parse_back_number("#32") == "32"
    for bad in ("100", "a1", "-3"):
        with pytest.raises(ValueError):
            ops.parse_back_number(bad)

    admin = _login_admin(client, db)
    ps = [Member(name=f"n{i}", position="GFC"[i % 3], position2="GFC"[(i + 1) % 3], height_cm=175 + i) for i in range(4)]
    db.add_all(ps)
    db.commit()
    me = ps[0]
    _login_as(client, db, me)
    r = client.post("/profile", data={"position": "G", "height": "180", "back_number": "23", "next": "/"},
                    follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert me.back_number == "23"
    assert 'value="23"' in client.get("/profile").text
    r = client.post("/profile", data={"position": "G", "height": "180", "back_number": "123", "next": "/"},
                    follow_redirects=False)
    assert "err=" in r.headers["location"]
    db.expire_all()
    assert me.back_number == "23"

    s = ops.create_session(db, admin, _dt.date(2099, 7, 5))
    for m in [admin, *ps]:
        ops.vote(db, s, m, "yes")
    live = client.get(f"/s/{s.id}/live").text
    assert ">#23</span>n0" in live                       # 이름 앞 백넘버
    assert ">-</span>n1" in live                        # 없으면 '-'
    ops.confirm_grades(db, admin, {m.id: 3.0 for m in [admin, *ps]})
    pv = client.get(f"/s/{s.id}/preview").text
    assert ">#23</span>" in pv
    # 예상 팀은 주 포지션만 (부 포지션 뱃지는 opacity-50 으로 붙는다)
    assert "opacity-50" not in pv


def test_guest_height_visible_to_everyone(client, db):
    import datetime as _dt
    admin = _login_admin(client, db)
    host = Member(name="초대한사람", position="G", height_cm=175)
    db.add(host)
    db.commit()
    ops.confirm_grades(db, admin, {m.id: 3.0 for m in (admin, host)})
    s = ops.create_session(db, admin, _dt.date(2099, 7, 5))
    ops.vote(db, s, host, "yes")
    ops.add_guest(db, s, host, "키큰손님", grade=3, height=193, position="C")
    ops.add_guest(db, s, host, "키모름", grade=3)
    for url in (f"/s/{s.id}/live", f"/admin/s/{s.id}/checkin"):
        page = client.get(url).text
        assert "193cm" in page and "키 ?" in page, url       # 운영진: 게스트 키 보임 (미입력은 '키 ?')
    _login_as(client, db, host)
    assert "193cm" in client.get(f"/s/{s.id}/live").text      # 일반 멤버에게도 보임


def test_preview_matches_actual_lineup_when_everyone_shows_up(client, db):
    """투표한 사람이 그대로 출석하면 실제 게임 1 팀 = 예상 팀 (A/B 라벨까지)."""
    import datetime as _dt
    import random as _r
    admin = _login_admin(client, db)
    rnd = _r.Random(11)
    ms = [Member(name=f"동일{i}", position="GFC"[i % 3], height_cm=rnd.randint(168, 194)) for i in range(11)]
    db.add_all(ms)
    db.commit()
    ops.confirm_grades(db, admin, {m.id: float(1 + i % 5) for i, m in enumerate([admin, *ms])})
    s = ops.create_session(db, admin, _dt.date(2099, 8, 2))
    voters = [admin, *ms[:10]]
    for i, m in enumerate(voters):
        ops.vote(db, s, m, "early" if i == 3 else "yes", "09:30" if i == 3 else None)
    ops.add_guest(db, s, ms[0], "같은손님", grade=4, height=186, position="C")
    db.expire_all()
    pv = ops.preview_teams(db, s)
    expect = ({m.id for m in pv["a"]}, {m.id for m in pv["b"]})
    # 투표한 사람 전원(게스트 포함) 그대로 출석 → 팀 짜기
    for a in s.attendances:
        if a.vote in ("yes", "early"):
            ops.set_checkin(db, admin, s, a.member_id, True)
    g1 = ops.generate_game1(db, admin, s)
    actual = ({r.member_id for r in g1.roster if r.side == "A"}, {r.member_id for r in g1.roster if r.side == "B"})
    assert actual == expect
