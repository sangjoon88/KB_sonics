"""운영진 HTML 화면 (/admin)."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import (PinResult, current_admin, current_member,
                      pin_error, set_admin_cookie, set_member_cookie, verify_pin)
from app.config import (BALANCE_MODES, CALIBRATION_WEEKS, DEFAULT_LOCATION, DEFAULT_PIN,
                        SESSION_START_TIME, LOPSIDED_MARGIN, LOPSIDED_RATIO)
from app.db import get_db
from app.models import AdminLog, ClubSession, Game, Member, RatingHistory
from app.routers.common import admin_page, redirect, render
from app.services import lopsided, ops
from app.services.balancer import balance_label
from app.services.rating import grade_to_rating
from app.services.stats import member_summary
from app.timeutil import next_session_date, today_kst

router = APIRouter(prefix="/admin")


def _session(db: Session, sid: int) -> ClubSession:
    s = db.get(ClubSession, sid)
    if s is None:
        raise HTTPException(404, "모임이 없습니다.")
    return s


def _game(db: Session, s: ClubSession, no: int) -> Game | None:
    if no not in (1, 2):
        raise HTTPException(404)
    return ops.get_game(db, s, no)


def _member(db: Session, mid: int) -> Member:
    m = db.get(Member, mid)
    if m is None:
        raise HTTPException(404, "멤버가 없습니다.")
    return m


# ---------------------------------------------------------------- 로그인 / PIN

@router.get("/login")
def login_page(request: Request, next: str = "/admin", db: Session = Depends(get_db),
               me=Depends(current_member), admin=Depends(current_admin)):
    if admin:
        return redirect(next if next.startswith("/") else "/admin")
    admins = db.scalars(select(Member).where(Member.is_admin.is_(True), Member.is_active.is_(True))
                        .order_by(Member.name)).all()
    return render(request, "admin/login.html", {"admins": admins, "next": next}, member=me)


@router.post("/login")
def login_post(request: Request, member_id: int = Form(...), pin: str = Form(...),
               next: str = Form("/admin"), db: Session = Depends(get_db)):
    m = db.get(Member, member_id)
    nxt = next if next.startswith("/") and not next.startswith("//") else "/admin"
    if m is None or not m.is_admin:
        return redirect(f"/admin/login?next={nxt}", err="운영진이 아닙니다.")
    result, n = verify_pin(db, m, pin)
    if result == PinResult.OK:
        resp = redirect(f"/pin?next={nxt}" if m.pin_must_change else nxt)
        set_member_cookie(resp, m.id)
        set_admin_cookie(resp, m.id)
        return resp
    return redirect(f"/admin/login?next={nxt}", err=pin_error(result, n))


@router.get("/pin")
def pin_page_legacy():
    return redirect("/pin?next=/admin")


# ---------------------------------------------------------------- 대시보드 / 모임

@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db), admin=Depends(admin_page)):
    sessions = db.scalars(select(ClubSession).order_by(ClubSession.date.desc()).limit(12)
                          .options(selectinload(ClubSession.attendances))).all()
    active = db.scalars(select(Member).where(Member.is_active.is_(True))).all()
    warnings = []
    no_height = [m for m in active if not m.height_cm]
    unrated = [m for m in active if m.initial_grade is None]
    if no_height:
        warnings.append(f"키 미입력 {len(no_height)}명")
    if unrated:
        warnings.append(f"초기 등급 미확정 {len(unrated)}명 — 확정 전에는 팀 짜기 불가")
    if not active or len(active) <= 1:
        warnings.append("멤버가 없습니다. 멤버 일괄 등록부터 하세요.")
    # 기본 날짜: 아직 경기가 등록되지 않은 가장 가까운 일요일
    taken = set(db.scalars(select(ClubSession.date).where(ClubSession.date >= today_kst())).all())
    nxt = next_session_date()
    while nxt in taken:
        nxt += timedelta(days=7)
    return render(request, "admin/dashboard.html",
                  {"sessions": sessions, "warnings": warnings, "next_date": nxt,
                   "default_time": SESSION_START_TIME, "default_location": DEFAULT_LOCATION,
                   "member_count": len(active)}, member=admin, admin=admin)


@router.post("/sessions")
def create_session(session_date: date = Form(...), location: str = Form(""), start_time: str = Form(""),
                   vote_deadline: str = Form(""), db: Session = Depends(get_db), admin=Depends(admin_page)):
    deadline = None
    if vote_deadline:
        try:
            deadline = datetime.fromisoformat(vote_deadline)
        except ValueError:
            return redirect("/admin", err="마감 시각 형식 오류")
    try:
        s = ops.create_session(db, admin, session_date, location, deadline, start_time or None)
    except ops.OpError as e:
        return redirect("/admin", err=str(e))
    return redirect(f"/admin/s/{s.id}", msg="경기를 등록했습니다. 투표가 열렸어요 — 링크를 카톡에 공유하세요.")


@router.get("/s/{sid}")
def session_detail(request: Request, sid: int, db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    counts = {"yes": 0, "early": 0, "no": 0, "checked": 0}
    for a in s.attendances:
        if a.vote in counts:
            counts[a.vote] += 1
        counts["checked"] += a.checked_in
    vote_url = str(request.base_url).rstrip("/") + f"/s/{s.id}"
    return render(request, "admin/session.html", {"s": s, "counts": counts, "vote_url": vote_url,
                                                  "g1": ops.get_game(db, s, 1), "g2": ops.get_game(db, s, 2)},
                  member=admin, admin=admin)


@router.post("/s/{sid}/info")
def session_info(sid: int, start_time: str = Form(...), location: str = Form(""),
                 db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    try:
        ops.update_session_info(db, admin, s, start_time=start_time, location=location)
    except ops.OpError as e:
        return redirect(f"/admin/s/{sid}", err=str(e))
    return redirect(f"/admin/s/{sid}", msg="시간·장소를 수정했습니다.")


@router.post("/s/{sid}/status")
def session_status(sid: int, status: str = Form(...), db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    try:
        ops.set_session_status(db, admin, s, status)
    except ops.OpError as e:
        return redirect(f"/admin/s/{sid}", err=str(e))
    return redirect(f"/admin/s/{sid}", msg="상태를 변경했습니다.")


@router.get("/s/{sid}/checkin")
def checkin_page(request: Request, sid: int, db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    members = db.scalars(select(Member).where(Member.is_active.is_(True)).order_by(Member.name)).all()
    members = [*members, *(a.member for a in ops.session_guests(s))]
    att = {a.member_id: a for a in s.attendances}
    order = {"yes": 0, "early": 1, None: 2, "no": 3}
    members = sorted(members, key=lambda m: (order.get(att[m.id].vote if m.id in att else None, 2), m.name))
    return render(request, "admin/checkin.html", {"s": s, "members": members, "att": att,
                                                  "checked": sum(1 for a in att.values() if a.checked_in)},
                  member=admin, admin=admin)


@router.post("/s/{sid}/checkin/{mid}")
def checkin_toggle(request: Request, sid: int, mid: int, db: Session = Depends(get_db),
                   admin=Depends(admin_page)):
    s = _session(db, sid)
    a = ops.get_attendance(db, s, mid)
    a = ops.set_checkin(db, admin, s, mid, not (a and a.checked_in))
    checked = sum(1 for x in s.attendances if x.checked_in)
    return render(request, "admin/_checkin_row.html",
                  {"s": s, "m": _member(db, mid), "a": a, "checked": checked, "oob": True},
                  member=admin, admin=admin)


@router.post("/s/{sid}/guests")
def checkin_add_guest(sid: int, name: str = Form(...), grade: str = Form("3"), height: str = Form(""),
                      position: str = Form(""), position2: str = Form(""),
                      db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    try:
        ops.add_guest(db, s, None, name, grade=float(grade or 3), height=ops.parse_height(height),
                      position=position or None, position2=position2 or None,
                      checked_in=True, by_admin=admin)
    except (ValueError, ops.OpError) as e:
        return redirect(f"/admin/s/{sid}/checkin", err=str(e))
    return redirect(f"/admin/s/{sid}/checkin", msg=f"게스트 {name.strip()} 출석 처리")


@router.post("/s/{sid}/guests/{gid}/remove")
def checkin_remove_guest(sid: int, gid: int, db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    try:
        ops.remove_guest(db, s, gid, actor=admin, by_admin=admin)
    except ops.OpError as e:
        return redirect(f"/admin/s/{sid}/checkin", err=str(e))
    return redirect(f"/admin/s/{sid}/checkin", msg="게스트를 뺐습니다.")


# ---------------------------------------------------------------- 팀 짜기

def _lineup_ctx(db: Session, s: ClubSession, no: int, game: Game | None) -> dict:
    members = ops.checked_in_members(db, s)
    errors, warnings = ops.team_readiness(members)
    early = {a.member_id: a.leave_time for a in s.attendances if a.vote == "early" and a.leave_time}
    ctx = {"s": s, "no": no, "game": game, "errors": errors, "warnings": warnings,
           "checked": members, "mode": ops.balance_mode(db), "early": early}
    if game:
        ev = ops.evaluate_game(db, game)
        on_roster = {r.member_id for r in game.roster}
        ctx.update({
            "team_a": sorted([r.member for r in game.roster if r.side == "A"], key=lambda m: -(m.height_cm or 0)),
            "team_b": sorted([r.member for r in game.roster if r.side == "B"], key=lambda m: -(m.height_cm or 0)),
            "ev": ev, "label": balance_label(ev.breakdown) if ev else None,
            "not_in": [m for m in members if m.id not in on_roster],
            "absent": [r.member for r in game.roster if r.member_id not in {m.id for m in members}],
        })
        if game.game_no == 2 and game.lineup_mode == "reshuffled":
            g1 = ops.get_game(db, s, 1)
            sides1 = {r.member_id: r.side for r in g1.roster} if g1 else {}
            ctx["moved"] = {r.member_id for r in game.roster if sides1.get(r.member_id) not in (None, r.side)}
    return ctx


@router.get("/s/{sid}/game/{no}/lineup")
def lineup_page(request: Request, sid: int, no: int, db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    game = _game(db, s, no)
    if no == 2 and game is None:
        return redirect(f"/admin/s/{sid}/game/2/choose")
    return render(request, "admin/lineup.html", _lineup_ctx(db, s, no, game), member=admin, admin=admin)


def _lineup_response(request: Request, db: Session, s: ClubSession, no: int, admin):
    db.expire_all()
    s = _session(db, s.id)
    game = _game(db, s, no)
    if request.headers.get("HX-Request"):
        return render(request, "admin/_lineup_board.html", _lineup_ctx(db, s, no, game), member=admin, admin=admin)
    return redirect(f"/admin/s/{s.id}/game/{no}/lineup")


@router.post("/s/{sid}/game/1/generate")
def lineup_generate(sid: int, db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    try:
        ops.generate_game1(db, admin, s)
    except ops.OpError as e:
        return redirect(f"/admin/s/{sid}/game/1/lineup", err=str(e))
    return redirect(f"/admin/s/{sid}/game/1/lineup", msg="팀을 생성했습니다.")


@router.post("/s/{sid}/game/{no}/next")
def lineup_next(request: Request, sid: int, no: int, db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    game = _game(db, s, no)
    if game is None:
        raise HTTPException(404)
    try:
        ops.next_candidate(db, admin, game)
    except ops.OpError as e:
        return redirect(f"/admin/s/{sid}/game/{no}/lineup", err=str(e))
    return _lineup_response(request, db, s, no, admin)


@router.post("/s/{sid}/game/{no}/{action}/{mid}")
def lineup_member_action(request: Request, sid: int, no: int, action: str, mid: int,
                         db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    game = _game(db, s, no)
    if game is None:
        raise HTTPException(404)
    fn = {"move": ops.move_member, "add": ops.add_to_lineup, "remove": ops.remove_from_lineup}.get(action)
    if fn is None:
        raise HTTPException(404)
    try:
        fn(db, admin, game, mid)
    except ops.OpError as e:
        return redirect(f"/admin/s/{sid}/game/{no}/lineup", err=str(e))
    return _lineup_response(request, db, s, no, admin)


# ---------------------------------------------------------------- 점수 / 게임 2 선택

@router.get("/s/{sid}/game/{no}/score")
def score_page(request: Request, sid: int, no: int, db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    game = _game(db, s, no)
    if game is None:
        return redirect(f"/admin/s/{sid}/game/{no}/lineup", err="팀 명단을 먼저 만드세요.")
    return render(request, "admin/score.html", {
        "s": s, "game": game,
        "team_a": [r.member.name for r in game.roster if r.side == "A"],
        "team_b": [r.member.name for r in game.roster if r.side == "B"],
    }, member=admin, admin=admin)


@router.post("/s/{sid}/game/{no}/score")
def score_post(sid: int, no: int, score_a: int = Form(...), score_b: int = Form(...),
               db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    game = _game(db, s, no)
    if game is None:
        raise HTTPException(404)
    try:
        ops.submit_result(db, admin, game, score_a, score_b)
    except ops.OpError as e:
        return redirect(f"/admin/s/{sid}/game/{no}/score", err=str(e))
    if no == 1:
        g2 = ops.get_game(db, s, 2)
        if g2 is None:
            return redirect(f"/admin/s/{sid}/game/2/choose", msg="게임 1 결과 저장 · 레이팅 갱신 완료")
        return redirect(f"/admin/s/{sid}", msg="게임 1 결과를 수정했습니다. (레이팅 재계산 완료)")
    return redirect(f"/admin/s/{sid}", msg="게임 2 결과 저장 · 레이팅 갱신 완료")


@router.get("/s/{sid}/game/2/choose")
def choose_page(request: Request, sid: int, db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    g1 = ops.get_game(db, s, 1)
    if g1 is None or g1.status != "finished":
        return redirect(f"/admin/s/{sid}", err="게임 1 결과를 먼저 입력하세요.")
    judged = lopsided.judge(g1.score_a, g1.score_b)
    return render(request, "admin/choose.html", {
        "s": s, "g1": g1, "judged": judged, "g2": ops.get_game(db, s, 2),
        "margin_limit": LOPSIDED_MARGIN, "ratio_limit": LOPSIDED_RATIO,
    }, member=admin, admin=admin)


@router.post("/s/{sid}/game/2/choose")
def choose_post(sid: int, mode: str = Form(...), db: Session = Depends(get_db), admin=Depends(admin_page)):
    s = _session(db, sid)
    try:
        ops.create_game2(db, admin, s, mode)
    except ops.OpError as e:
        return redirect(f"/admin/s/{sid}/game/2/choose", err=str(e))
    return redirect(f"/admin/s/{sid}/game/2/lineup",
                    msg="게임 1 팀 그대로 진행합니다." if mode == "kept" else "팀을 재편성했습니다.")


# ---------------------------------------------------------------- 멤버 관리

@router.get("/members")
def members_page(request: Request, db: Session = Depends(get_db), admin=Depends(admin_page)):
    members = db.scalars(select(Member).where(Member.is_guest.is_(False))
                          .order_by(Member.is_active.desc(), Member.name)).all()
    return render(request, "admin/members.html", {"members": members, "default_pin": DEFAULT_PIN,
                                                  "member_summary": member_summary(db, today_kst()),
                                                  "show_admin_summary": True},
                  member=admin, admin=admin)


@router.post("/members/new")
def member_new(name: str = Form(...), position: str = Form(""), position2: str = Form(""),
               height: str = Form(""), db: Session = Depends(get_db), admin=Depends(admin_page)):
    try:
        ops.create_member(db, admin, name, position or None, ops.parse_height(height), position2 or None)
    except (ValueError, ops.OpError) as e:
        return redirect("/admin/members", err=str(e))
    return redirect("/admin/members", msg=f"{name.strip()} 추가 — 초기 PIN {DEFAULT_PIN} (첫 로그인 때 본인이 변경). 초기 등급 평가도 해주세요.")


@router.post("/members/{mid:int}")
def member_edit(mid: int, name: str = Form(...), position: str = Form(""), position2: str = Form(""),
                height: str = Form(""), weight: str = Form(""), back_number: str = Form(""),
                is_active: str = Form(""), db: Session = Depends(get_db), admin=Depends(admin_page)):
    m = _member(db, mid)
    try:
        h = ops.parse_height(height)
        ops.update_member(db, admin, m, name=name, position=position, height=h,
                          is_active=bool(is_active), position2=position2 or None,
                          weight=ops.parse_weight(weight), back_number=ops.parse_back_number(back_number))
        if h is None and m.height_cm is not None:
            m.height_cm = None
            db.commit()
    except (ValueError, ops.OpError) as e:
        return redirect("/admin/members", err=str(e))
    return redirect("/admin/members", msg=f"{m.name} 저장")


@router.post("/members/{mid:int}/admin")
def member_admin_toggle(mid: int, on: str = Form(""), db: Session = Depends(get_db), admin=Depends(admin_page)):
    m = _member(db, mid)
    try:
        ops.set_admin_role(db, admin, m, bool(on))
    except ops.OpError as e:
        return redirect("/admin/members", err=str(e))
    return redirect("/admin/members", msg=f"{m.name} 운영진 {'지정 — 본인 PIN으로 운영진 메뉴를 쓸 수 있어요' if on else '해제'}")


@router.post("/members/{mid:int}/reset-pin")
def member_reset_pin(mid: int, db: Session = Depends(get_db), admin=Depends(admin_page)):
    m = _member(db, mid)
    try:
        pin = ops.reset_pin(db, admin, m)
    except ops.OpError as e:
        return redirect("/admin/members", err=str(e))
    return redirect("/admin/members", msg=f"{m.name} PIN을 {pin}(으)로 초기화했습니다. 다음 로그인 때 본인이 변경합니다.")


# ---------------------------------------------------------------- 초기 등급 평가

@router.get("/rating-setup")
def rating_setup(request: Request, db: Session = Depends(get_db), admin=Depends(admin_page)):
    rows = ops.grade_rows(db, admin)
    submitted = any(r.my_grade is not None for r in rows)
    return render(request, "admin/rating_setup.html",
                  {"rows": rows, "submitted": submitted, "raters": ops.raters_status(db)},
                  member=admin, admin=admin)


async def _int_fields(request: Request, prefix: str, cast=int) -> dict:
    form = await request.form()
    out = {}
    for k, v in form.items():
        if k.startswith(prefix) and str(v).strip():
            out[int(k[len(prefix):])] = cast(str(v))
    return out


@router.post("/rating-setup/mine")
async def rating_setup_mine(request: Request, db: Session = Depends(get_db), admin=Depends(admin_page)):
    try:
        grades = await _int_fields(request, "g_")
        n = ops.save_my_grades(db, admin, grades)
    except (ValueError, ops.OpError) as e:
        return redirect("/admin/rating-setup", err=str(e))
    return redirect("/admin/rating-setup", msg=f"내 평가 {n}명 제출")


@router.post("/rating-setup/confirm")
async def rating_setup_confirm(request: Request, db: Session = Depends(get_db), admin=Depends(admin_page)):
    try:
        grades = await _int_fields(request, "c_", float)
        n = ops.confirm_grades(db, admin, grades)
    except (ValueError, ops.OpError) as e:
        return redirect("/admin/rating-setup", err=str(e))
    return redirect("/admin/rating-setup", msg=f"{n}명 초기 레이팅 확정")


# ---------------------------------------------------------------- 레이팅 / 설정 / 로그

@router.get("/ratings")
def ratings_page(request: Request, db: Session = Depends(get_db), admin=Depends(admin_page)):
    members = db.scalars(select(Member).where(Member.is_active.is_(True))).all()
    counts: dict[int, int] = {}
    for (mid,) in db.execute(select(RatingHistory.member_id)).all():
        counts[mid] = counts.get(mid, 0) + 1
    rows = []
    for m in members:
        init_mu = grade_to_rating(m.initial_grade)[0] if m.initial_grade is not None else None
        rows.append({"m": m, "games": counts.get(m.id, 0), "init_mu": init_mu,
                     "delta": (m.mu - init_mu) if init_mu is not None else None})
    rows.sort(key=lambda r: -r["m"].mu)
    return render(request, "admin/ratings.html", {"rows": rows, "calib_weeks": CALIBRATION_WEEKS},
                  member=admin, admin=admin)


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), admin=Depends(admin_page)):
    return render(request, "admin/settings.html", {"mode": ops.balance_mode(db), "modes": BALANCE_MODES},
                  member=admin, admin=admin)


@router.post("/settings")
def settings_post(balance_mode: str = Form(...), db: Session = Depends(get_db), admin=Depends(admin_page)):
    if balance_mode not in BALANCE_MODES:
        return redirect("/admin/settings", err="잘못된 모드")
    ops.set_setting(db, "balance_mode", balance_mode)
    ops.log(db, admin, "settings.balance_mode", "settings", {"value": balance_mode})
    db.commit()
    return redirect("/admin/settings", msg="저장했습니다.")


@router.get("/logs")
def logs_page(request: Request, db: Session = Depends(get_db), admin=Depends(admin_page)):
    logs = db.scalars(select(AdminLog).order_by(AdminLog.id.desc()).limit(100)
                      .options(selectinload(AdminLog.admin))).all()
    return render(request, "admin/logs.html", {"logs": logs}, member=admin, admin=admin)


