"""멤버/공개 HTML 화면."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (ADMIN_COOKIE, PinResult, clear_cookies, current_admin, current_member, hash_pin,
                      pin_error, set_admin_cookie, set_member_cookie, valid_pin_format, verify_pin)
from app.config import DEFAULT_PIN
from app.config import settings
from app.db import get_db
from app.models import ClubSession, Game, Member, SessionComment
from app.routers.common import redirect, render
from app.services import ops
from app.services.balancer import balance_label
from app.services.stats import compute_stats, leaderboard, member_summary, winrate_min_games
from app.timeutil import today_kst

router = APIRouter()


def _safe_next(nxt: str | None) -> str:
    return nxt if nxt and nxt.startswith("/") and not nxt.startswith("//") else "/"


def _session_or_404(db: Session, session_id: int) -> ClubSession:
    s = db.get(ClubSession, session_id)
    if s is None:
        raise HTTPException(404, "모임이 없습니다.")
    return s


def _attendance_lists(s: ClubSession) -> dict:
    out = {"yes": [], "early": [], "no": [], "walkin": []}
    for a in sorted(s.attendances, key=lambda a: (a.voted_at is None, a.voted_at or 0)):
        if a.vote in out:
            out[a.vote].append(a)
        elif a.checked_in:
            out["walkin"].append(a)
    out["early"].sort(key=lambda a: a.leave_time or "")
    out["guests"] = [a for a in out["yes"] if a.member.is_guest]
    out["coming"] = len(out["yes"]) + len(out["early"])  # 조퇴도 참석 인원에 포함
    # 화면용: 조퇴는 예상 팀에서 시간으로 보여주므로 참석 명단에서는 구분하지 않는다
    out["attending"] = sorted(out["yes"] + out["early"], key=lambda a: (a.voted_at is None, a.voted_at or 0))
    return out


def _pending_voters(db: Session, s: ClubSession) -> list[Member]:
    """아직 투표하지 않은 활동 멤버 (게스트 제외, 현장 출석 체크된 사람 제외)."""
    responded = {a.member_id for a in s.attendances if a.vote is not None or a.checked_in}
    members = db.scalars(select(Member).where(Member.is_active.is_(True), Member.is_guest.is_(False))
                         .order_by(Member.name)).all()
    return [m for m in members if m.id not in responded]


@router.get("/")
def home(request: Request, db: Session = Depends(get_db), me=Depends(current_member),
         admin=Depends(current_admin)):
    if not ops.admin_exists(db):
        return render(request, "setup_needed.html", member=me)
    if me is None:
        # 첫 접속: 내가 누구인지부터 선택
        return redirect("/pick")
    if (gate := _gate(me, "/")) is not None:
        return gate
    s = ops.upcoming_session(db, today_kst())
    ctx = {"s": s, "my_vote": ops.get_attendance(db, s, me.id) if s else None,
           "voting_open": bool(s and ops.voting_open(s))}
    if s:
        ctx.update(_live_ctx(db, s))
        ctx["comment_count"] = db.scalar(select(func.count()).select_from(SessionComment)
                                         .where(SessionComment.session_id == s.id))
    # 지난 경기 결과: 결과가 입력된 가장 최근 모임 (이번 모임 제외)
    last = db.scalar(select(ClubSession).join(Game).where(Game.status == "finished",
                                                         ClubSession.id != (s.id if s else -1))
                     .order_by(ClubSession.date.desc()).limit(1))
    stats = compute_stats(db, settings.SEASON)
    ctx.update({
        "last": last, "my_st": stats.get(me.id),
        "top_att": leaderboard(stats, "attendance")[:3],
        "top_streak": [x for x in leaderboard(stats, "streak") if x.best_streak > 0][:3],
        "member_summary": member_summary(db, today_kst()),
    })
    return render(request, "home.html", ctx, member=me, admin=admin)


@router.get("/pick")
def pick_name(request: Request, next: str = "/", db: Session = Depends(get_db), me=Depends(current_member)):
    members = db.scalars(select(Member).where(Member.is_active.is_(True)).order_by(Member.name)).all()
    return render(request, "pick.html", {"members": members, "next": _safe_next(next)}, member=me)


def _profile_incomplete(m: Member) -> bool:
    return m.height_cm is None or m.position is None


def _after_pick(m: Member, nxt: str) -> str:
    if m.pin_must_change:
        return f"/pin?next={nxt}"
    return f"/profile?next={nxt}" if _profile_incomplete(m) else nxt


def _gate(me: Member, here: str):
    """초기 PIN 변경 → 프로필 입력이 끝나야 다른 화면을 쓸 수 있다."""
    if me.pin_must_change:
        return redirect(f"/pin?next={here}")
    if _profile_incomplete(me):
        return redirect(f"/profile?next={here}")
    return None


@router.post("/pick")
def pick_name_post(request: Request, member_id: int = Form(...), next: str = Form("/"),
                   db: Session = Depends(get_db)):
    m = db.get(Member, member_id)
    if not m or not m.is_active or m.is_guest:
        return redirect("/pick", err="멤버를 찾을 수 없습니다.")
    # 모든 멤버는 본인 PIN 확인 후에 선택된다 (운영진은 운영진 로그인까지 한 번에)
    return render(request, "pick_pin.html", {"m": m, "next": _safe_next(next), "default_pin": DEFAULT_PIN})


@router.post("/pick/pin")
def pick_pin_post(request: Request, member_id: int = Form(...), pin: str = Form(...), next: str = Form("/"),
                  db: Session = Depends(get_db)):
    m = db.get(Member, member_id)
    nxt = _safe_next(next)
    if not m or not m.is_active or m.is_guest:
        return redirect("/pick", err="멤버를 찾을 수 없습니다.")
    result, n = verify_pin(db, m, pin)
    if result != PinResult.OK:
        return render(request, "pick_pin.html", {"m": m, "next": nxt, "default_pin": DEFAULT_PIN,
                                                 "err": pin_error(result, n)}, status_code=400)
    resp = redirect(_after_pick(m, nxt))
    set_member_cookie(resp, m.id)
    if m.is_admin:
        set_admin_cookie(resp, m.id)
    else:
        resp.delete_cookie(ADMIN_COOKIE)  # 다른 사람으로 바꾸면 이 폰의 운영진 로그인도 해제
    return resp


@router.get("/pin")
def pin_page(request: Request, next: str = "/", me=Depends(current_member), admin=Depends(current_admin)):
    if me is None:
        return redirect("/pick")
    return render(request, "pin.html", {"next": _safe_next(next), "default_pin": DEFAULT_PIN},
                  member=me, admin=admin)


@router.post("/pin")
def pin_post(request: Request, pin: str = Form(...), pin2: str = Form(...), next: str = Form("/"),
             db: Session = Depends(get_db), me=Depends(current_member), admin=Depends(current_admin)):
    if me is None:
        return redirect("/pick")
    nxt = _safe_next(next)
    err = None
    if not valid_pin_format(pin):
        err = "PIN은 숫자 4~6자리"
    elif pin != pin2:
        err = "PIN 확인이 일치하지 않습니다."
    elif pin == DEFAULT_PIN:
        err = f"초기 PIN({DEFAULT_PIN})과 다른 번호로 정해주세요."
    if err:
        return render(request, "pin.html", {"next": nxt, "default_pin": DEFAULT_PIN, "err": err},
                      member=me, admin=admin, status_code=400)
    first_login = me.pin_must_change
    me.pin_hash = hash_pin(pin)
    me.pin_must_change = False
    if admin:
        ops.log(db, admin, "member.pin_change", f"member:{me.id}")
    db.commit()
    # 첫 로그인이면 포지션(주/부)·키·몸무게 확인 화면으로 (운영진이 미리 넣은 값은 채워져 있음)
    target = f"/profile?next={nxt}&first=1" if (first_login or _profile_incomplete(me)) else nxt
    return redirect(target, msg="PIN을 변경했습니다.")


@router.get("/profile")
def profile(request: Request, next: str = "/", first: int = 0, me=Depends(current_member),
            admin=Depends(current_admin)):
    if me is None:
        return redirect("/pick?next=/profile")
    if me.pin_must_change:
        return redirect(f"/pin?next=/profile")
    return render(request, "profile.html", {"next": _safe_next(next),
                                            "first": bool(first) or _profile_incomplete(me)},
                  member=me, admin=admin)


@router.post("/profile")
def profile_post(position: str = Form(""), position2: str = Form(""), height: str = Form(""),
                 weight: str = Form(""), next: str = Form("/"),
                 db: Session = Depends(get_db), me=Depends(current_member)):
    if me is None:
        return redirect("/pick")
    nxt = _safe_next(next)
    try:
        if not position:
            raise ValueError("주 포지션을 선택하세요.")
        h = ops.parse_height(height)
        if h is None:
            raise ValueError("키를 입력하세요.")
        ops.update_member(db, None, me, position=position, height=h,
                          position2=position2 or None, weight=ops.parse_weight(weight))
    except (ValueError, ops.OpError) as e:
        return redirect(f"/profile?next={nxt}", err=str(e))
    return redirect(nxt, msg="내 정보를 저장했습니다.")


@router.get("/logout")
def logout():
    resp = redirect("/", msg="이름 선택을 초기화했습니다.")
    clear_cookies(resp)
    return resp


# ---------------------------------------------------------------- 투표

@router.get("/s/{session_id}")
def vote_page(request: Request, session_id: int, db: Session = Depends(get_db),
              me=Depends(current_member), admin=Depends(current_admin)):
    s = _session_or_404(db, session_id)
    if me is None:
        members = db.scalars(select(Member).where(Member.is_active.is_(True)).order_by(Member.name)).all()
        return render(request, "pick.html", {"members": members, "next": f"/s/{s.id}", "s": s,
                                             "og_session": s})
    if (gate := _gate(me, f"/s/{s.id}")) is not None:
        return gate
    ctx = {"s": s, "my_vote": ops.get_attendance(db, s, me.id), "lists": _attendance_lists(s),
           "voting_open": ops.voting_open(s), "og_session": s, **_live_ctx(db, s),
           "comments": ops.list_comments(db, s)}
    if admin:
        ctx.update(_proxy_ctx(db, s))
    return render(request, "vote.html", ctx, member=me, admin=admin)


def _live_ctx(db: Session, s: ClubSession) -> dict:
    """투표 현황 + 예상 팀 (팀이 이미 짜였으면 확정 팀 안내)."""
    g1 = ops.get_game(db, s, 1)
    lists = _attendance_lists(s)
    lists["pending"] = _pending_voters(db, s)
    return {"lists": lists, "pv": None if g1 else ops.preview_teams(db, s), "g1": g1}


def _proxy_ctx(db: Session, s: ClubSession) -> dict:
    members = db.scalars(select(Member).where(Member.is_active.is_(True)).order_by(Member.name)).all()
    att = {a.member_id: a for a in s.attendances}
    members = sorted(members, key=lambda m: (m.id in att and att[m.id].vote is not None, m.name))
    return {"proxy_members": members, "proxy_att": att}


def _triggered(resp, event: str = "voteChanged"):
    resp.headers["HX-Trigger"] = event
    return resp


@router.get("/s/{session_id}/live")
def live_partial(request: Request, session_id: int, db: Session = Depends(get_db),
                 me=Depends(current_member), admin=Depends(current_admin)):
    s = _session_or_404(db, session_id)
    return render(request, "_live.html", {"s": s, **_live_ctx(db, s)}, member=me, admin=admin)


@router.get("/s/{session_id}/preview")
def preview_partial(request: Request, session_id: int, db: Session = Depends(get_db),
                    me=Depends(current_member), admin=Depends(current_admin)):
    s = _session_or_404(db, session_id)
    return render(request, "_preview.html", {"s": s, **_live_ctx(db, s)}, member=me, admin=admin)


@router.post("/s/{session_id}/proxy")
def proxy_vote_post(request: Request, session_id: int, member_id: int = Form(...), vote: str = Form(...),
                    leave_time: str = Form(""), db: Session = Depends(get_db),
                    me=Depends(current_member), admin=Depends(current_admin)):
    s = _session_or_404(db, session_id)
    if admin is None:
        raise HTTPException(403, "운영진만 대리 투표할 수 있습니다.")
    err = msg = None
    try:
        ops.proxy_vote(db, admin, s, member_id, vote, leave_time)
        m = db.get(Member, member_id)
        msg = f"{m.name}: {'투표 삭제' if vote == 'clear' else {'yes': '참석', 'no': '불참', 'early': '조퇴'}[vote]}"
    except ops.OpError as e:
        err = str(e)
    if request.headers.get("HX-Request"):
        db.refresh(s)
        resp = render(request, "_proxy_box.html", {"s": s, "proxy_msg": msg, "proxy_err": err,
                                                   "last_member_id": member_id, **_proxy_ctx(db, s)},
                      member=me, admin=admin)
        return _triggered(resp) if not err else resp
    return redirect(f"/s/{s.id}", err=err) if err else redirect(f"/s/{s.id}", msg=msg)


@router.post("/s/{session_id}/vote")
def vote_post(request: Request, session_id: int, vote: str = Form(...), leave_time: str = Form(""),
              db: Session = Depends(get_db), me=Depends(current_member)):
    s = _session_or_404(db, session_id)
    if me is None:
        return redirect(f"/s/{s.id}")
    err = None
    try:
        ops.vote(db, s, me, vote, leave_time)
    except ops.OpError as e:
        err = str(e)
    if request.headers.get("HX-Request"):
        return _vote_box(request, db, s, me, err)
    if err:
        return redirect(f"/s/{s.id}", err=err)
    return redirect(f"/s/{s.id}", msg="투표했습니다.")


def _vote_box(request: Request, db: Session, s: ClubSession, me: Member, err: str | None = None):
    db.refresh(s)
    resp = render(request, "_vote_box.html", {"s": s, "my_vote": ops.get_attendance(db, s, me.id),
                                              "lists": _attendance_lists(s), "vote_err": err,
                                              "voting_open": ops.voting_open(s)}, member=me)
    return _triggered(resp) if not err else resp


@router.post("/s/{session_id}/guests")
def guest_add(request: Request, session_id: int, name: str = Form(...), grade: str = Form("3"),
              height: str = Form(""), position: str = Form(""), position2: str = Form(""),
              db: Session = Depends(get_db), me=Depends(current_member)):
    s = _session_or_404(db, session_id)
    if me is None:
        return redirect(f"/s/{s.id}")
    err = None
    try:
        ops.add_guest(db, s, me, name, grade=float(grade or 3), height=ops.parse_height(height),
                      position=position or None, position2=position2 or None)
    except (ValueError, ops.OpError) as e:
        err = str(e)
    if request.headers.get("HX-Request"):
        return _vote_box(request, db, s, me, err)
    return redirect(f"/s/{s.id}", err=err) if err else redirect(f"/s/{s.id}", msg="게스트를 추가했습니다.")


@router.post("/s/{session_id}/guests/{guest_id}/remove")
def guest_remove(request: Request, session_id: int, guest_id: int, db: Session = Depends(get_db),
                 me=Depends(current_member), admin=Depends(current_admin)):
    s = _session_or_404(db, session_id)
    if me is None:
        return redirect(f"/s/{s.id}")
    err = None
    try:
        ops.remove_guest(db, s, guest_id, actor=me, by_admin=admin)
    except ops.OpError as e:
        err = str(e)
    if request.headers.get("HX-Request"):
        return _vote_box(request, db, s, me, err)
    return redirect(f"/s/{s.id}", err=err) if err else redirect(f"/s/{s.id}", msg="게스트를 취소했습니다.")


# ---------------------------------------------------------------- 한마디 (댓글)

def _comments(request: Request, db: Session, s: ClubSession, me, admin, err: str | None = None):
    return render(request, "_comment_list.html", {"s": s, "comments": ops.list_comments(db, s),
                                                  "comment_err": err}, member=me, admin=admin)


@router.get("/s/{session_id}/comments")
def comments_partial(request: Request, session_id: int, db: Session = Depends(get_db),
                     me=Depends(current_member), admin=Depends(current_admin)):
    return _comments(request, db, _session_or_404(db, session_id), me, admin)


@router.post("/s/{session_id}/comments")
def comment_add(request: Request, session_id: int, body: str = Form(""), db: Session = Depends(get_db),
                me=Depends(current_member), admin=Depends(current_admin)):
    s = _session_or_404(db, session_id)
    if me is None:
        return redirect(f"/s/{s.id}")
    err = None
    try:
        ops.add_comment(db, s, me, body)
    except ops.OpError as e:
        err = str(e)
    if request.headers.get("HX-Request"):
        return _comments(request, db, s, me, admin, err)
    return redirect(f"/s/{s.id}#comments", err=err) if err else redirect(f"/s/{s.id}#comments")


@router.post("/s/{session_id}/comments/{comment_id}/delete")
def comment_delete(request: Request, session_id: int, comment_id: int, db: Session = Depends(get_db),
                   me=Depends(current_member), admin=Depends(current_admin)):
    s = _session_or_404(db, session_id)
    if me is None:
        return redirect(f"/s/{s.id}")
    err = None
    try:
        ops.delete_comment(db, s, comment_id, actor=me, admin=admin)
    except ops.OpError as e:
        err = str(e)
    if request.headers.get("HX-Request"):
        return _comments(request, db, s, me, admin, err)
    return redirect(f"/s/{s.id}#comments", err=err) if err else redirect(f"/s/{s.id}#comments")


# ---------------------------------------------------------------- 오늘 경기

def _day_context(db: Session, s: ClubSession, admin) -> dict:
    games = []
    for g in s.games:
        ev = ops.evaluate_game(db, g)
        games.append({
            "g": g,
            "a": sorted([r.member for r in g.roster if r.side == "A"], key=lambda m: -(m.height_cm or 0)),
            "b": sorted([r.member for r in g.roster if r.side == "B"], key=lambda m: -(m.height_cm or 0)),
            "label": balance_label(ev.breakdown) if ev else None,
        })
    checked = sum(1 for a in s.attendances if a.checked_in)
    early = {a.member_id: a.leave_time for a in s.attendances if a.vote == "early" and a.leave_time}
    return {"s": s, "games": games, "checked": checked, "admin": admin, "early": early}


@router.get("/s/{session_id}/day")
def day_page(request: Request, session_id: int, db: Session = Depends(get_db),
             me=Depends(current_member), admin=Depends(current_admin)):
    s = _session_or_404(db, session_id)
    return render(request, "day.html", _day_context(db, s, admin), member=me, admin=admin)


@router.get("/s/{session_id}/day/partial")
def day_partial(request: Request, session_id: int, db: Session = Depends(get_db),
                me=Depends(current_member), admin=Depends(current_admin)):
    s = _session_or_404(db, session_id)
    return render(request, "_day_games.html", _day_context(db, s, admin), member=me, admin=admin)


# ---------------------------------------------------------------- 기록

@router.get("/stats")
def stats_page(request: Request, sort: str = "attendance", season: int | None = None,
               db: Session = Depends(get_db), me=Depends(current_member), admin=Depends(current_admin)):
    season = season or settings.SEASON
    stats = compute_stats(db, season)
    rows = leaderboard(stats, sort)
    return render(request, "stats.html", {"rows": rows, "sort": sort, "season": season,
                                          "min_games": winrate_min_games(next(iter(stats.values())).season_games if stats else 0)},
                  member=me, admin=admin)


@router.get("/me")
def my_page(request: Request, db: Session = Depends(get_db), me=Depends(current_member),
            admin=Depends(current_admin)):
    if me is None:
        return redirect("/pick?next=/me")
    if (gate := _gate(me, "/me")) is not None:
        return gate
    st = compute_stats(db, settings.SEASON).get(me.id)
    return render(request, "me.html", {"st": st}, member=me, admin=admin)


# ---------------------------------------------------------------- 최초 세팅

def _setup_allowed(db: Session, token: str) -> bool:
    return bool(settings.SETUP_TOKEN) and token == settings.SETUP_TOKEN and not ops.admin_exists(db)


@router.get("/setup")
def setup_page(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not _setup_allowed(db, token):
        raise HTTPException(404)
    return render(request, "setup.html", {"token": token})


@router.post("/setup")
def setup_post(request: Request, token: str = Form(""), name: str = Form(...), position: str = Form(""),
               position2: str = Form(""), height: str = Form(""), weight: str = Form(""),
               pin: str = Form(...), pin2: str = Form(...), db: Session = Depends(get_db)):
    if not _setup_allowed(db, token):
        raise HTTPException(404)
    err = None
    if not valid_pin_format(pin):
        err = "PIN은 숫자 4~6자리"
    elif pin != pin2:
        err = "PIN 확인이 일치하지 않습니다."
    h = w = None
    try:
        h = ops.parse_height(height)
        w = ops.parse_weight(weight)
    except ValueError as e:
        err = str(e)
    if err:
        return render(request, "setup.html", {"token": token, "err": err}, status_code=400)
    m = db.scalar(select(Member).where(Member.name == name.strip()))
    if m is None:
        m = Member(name=name.strip(), mu=25.0)
        db.add(m)
    m.position = ops.normalize_position(position)
    p2 = ops.normalize_position(position2)
    m.position2 = p2 if p2 != m.position else None
    m.height_cm = h
    m.weight_kg = w
    m.is_admin = True
    m.is_owner = True
    m.pin_hash = hash_pin(pin)
    m.pin_must_change = False
    db.commit()
    resp = redirect("/admin", msg="관리자 계정이 생성되었습니다. 이제 멤버를 등록하세요.")
    set_member_cookie(resp, m.id)
    set_admin_cookie(resp, m.id)
    return resp


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"ok": True}


