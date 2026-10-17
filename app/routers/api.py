"""JSON API (명세서 11장). 화면과 같은 services.ops 로직을 사용한다."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_admin, current_member, require_admin
from app.config import settings
from app.db import get_db
from app.models import ClubSession, Game, Member, RatingHistory
from app.schemas import (CheckinIn, Game2LineupIn, MemberCreate, MemberOut, MemberPatch, MoveIn,
                         ResultIn, SessionCreate, SessionOut, SessionPatch, VoteIn)
from app.services import ops
from app.services.balancer import balance_label
from app.services.rating import confidence, mu_to_grade
from app.services.stats import compute_stats, leaderboard
from app.timeutil import next_session_date, today_kst

router = APIRouter(prefix="/api")


def _session(db: Session, sid: int) -> ClubSession:
    s = db.get(ClubSession, sid)
    if s is None:
        raise HTTPException(404, "모임이 없습니다.")
    return s


def _game_by_id(db: Session, gid: int) -> Game:
    g = db.get(Game, gid)
    if g is None:
        raise HTTPException(404, "게임이 없습니다.")
    return g


def _game_out(db: Session, g: Game, *, admin: bool = False) -> dict:
    ev = ops.evaluate_game(db, g)
    out = {
        "id": g.id, "game_no": g.game_no, "lineup_mode": g.lineup_mode, "status": g.status,
        "score_a": g.score_a, "score_b": g.score_b, "winner": g.winner,
        "team_a": [{"id": r.member_id, "name": r.member.name} for r in g.roster if r.side == "A"],
        "team_b": [{"id": r.member_id, "name": r.member.name} for r in g.roster if r.side == "B"],
        "balance": balance_label(ev.breakdown) if ev else None,
    }
    if admin and ev:
        out["cost"] = round(ev.cost, 3)
        out["breakdown"] = {k: round(v, 3) for k, v in ev.breakdown.items()}
        out["candidate_idx"] = g.candidate_idx
        out["candidates"] = len(g.candidates or [])
    return out


# ---------------------------------------------------------------- 멤버

@router.get("/members", response_model=list[MemberOut])
def list_members(db: Session = Depends(get_db)):
    return db.scalars(select(Member).where(Member.is_active.is_(True)).order_by(Member.name)).all()


@router.post("/members", response_model=MemberOut, status_code=201)
def create_member(body: MemberCreate, db: Session = Depends(get_db), admin=Depends(require_admin)):
    return ops.create_member(db, admin, body.name, body.position, body.height_cm, body.position2)


@router.patch("/members/{mid}", response_model=MemberOut)
def patch_member(mid: int, body: MemberPatch, db: Session = Depends(get_db), admin=Depends(require_admin)):
    m = db.get(Member, mid)
    if m is None:
        raise HTTPException(404)
    extra = body.model_dump(exclude_unset=True)
    kw = {}
    if "position2" in extra:
        kw["position2"] = body.position2 or None
    if "weight_kg" in extra:
        kw["weight"] = body.weight_kg
    ops.update_member(db, admin, m, name=body.name, position=body.position, height=body.height_cm,
                      is_active=body.is_active, **kw)
    return m


@router.get("/members/{mid}/stats")
def member_stats(mid: int, season: int | None = None, db: Session = Depends(get_db)):
    st = compute_stats(db, season or settings.SEASON).get(mid)
    if st is None:
        raise HTTPException(404)
    return {**st.as_dict(), "recent": [{**r, "date": r["date"].isoformat()} for r in st.recent[:10]]}


# ---------------------------------------------------------------- 모임 / 참석

@router.get("/sessions/upcoming", response_model=SessionOut | None)
def upcoming(db: Session = Depends(get_db)):
    return ops.upcoming_session(db, today_kst())


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionCreate, db: Session = Depends(get_db), admin=Depends(require_admin)):
    return ops.create_session(db, admin, body.date or next_session_date(), body.location, body.vote_deadline,
                              body.start_time)


@router.patch("/sessions/{sid}", response_model=SessionOut)
def patch_session(sid: int, body: SessionPatch, db: Session = Depends(get_db), admin=Depends(require_admin)):
    s = _session(db, sid)
    if body.location is not None or body.start_time is not None:
        ops.update_session_info(db, admin, s, start_time=body.start_time, location=body.location)
    if body.status:
        ops.set_session_status(db, admin, s, body.status)
    return s


@router.get("/sessions/{sid}/attendance")
def attendance(sid: int, db: Session = Depends(get_db)):
    s = _session(db, sid)
    return [{"member_id": a.member_id, "name": a.member.name, "vote": a.vote,
             "leave_time": a.leave_time, "checked_in": a.checked_in}
            for a in s.attendances]


@router.put("/sessions/{sid}/vote")
def put_vote(sid: int, body: VoteIn, db: Session = Depends(get_db), me=Depends(current_member),
             admin=Depends(current_admin)):
    s = _session(db, sid)
    # 로그인이 없으므로 본인 쿠키의 멤버와 일치할 때만 허용 (사칭 방지 최소 장치). 운영진은 대리 투표 가능
    if admin is not None and (me is None or me.id != body.member_id):
        a = ops.proxy_vote(db, admin, s, body.member_id, body.vote, body.leave_time)
        return {"member_id": a.member_id, "vote": a.vote, "leave_time": a.leave_time, "proxy": True}
    if me is None or me.id != body.member_id:
        raise HTTPException(403, "본인 이름을 먼저 선택하세요.")
    a = ops.vote(db, s, me, body.vote, body.leave_time)
    return {"member_id": a.member_id, "vote": a.vote, "leave_time": a.leave_time}


@router.patch("/sessions/{sid}/checkin")
def patch_checkin(sid: int, body: CheckinIn, db: Session = Depends(get_db), admin=Depends(require_admin)):
    s = _session(db, sid)
    a = ops.set_checkin(db, admin, s, body.member_id, body.checked_in)
    return {"member_id": a.member_id, "checked_in": a.checked_in}


# ---------------------------------------------------------------- 게임 / 라인업

@router.post("/sessions/{sid}/games/1/lineup")
def lineup_game1(sid: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    g = ops.generate_game1(db, admin, _session(db, sid))
    return _game_out(db, g, admin=True)


@router.post("/sessions/{sid}/games/2/lineup")
def lineup_game2(sid: int, body: Game2LineupIn, db: Session = Depends(get_db), admin=Depends(require_admin)):
    g = ops.create_game2(db, admin, _session(db, sid), body.mode)
    return _game_out(db, g, admin=True)


@router.post("/games/{gid}/lineup/next")
def lineup_next(gid: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    g = ops.next_candidate(db, admin, _game_by_id(db, gid))
    return _game_out(db, g, admin=True)


@router.patch("/games/{gid}/lineup/move")
def lineup_move(gid: int, body: MoveIn, db: Session = Depends(get_db), admin=Depends(require_admin)):
    g = ops.move_member(db, admin, _game_by_id(db, gid), body.member_id)
    return _game_out(db, g, admin=True)


@router.get("/sessions/{sid}/games")
def list_games(sid: int, db: Session = Depends(get_db)):
    s = _session(db, sid)
    return [_game_out(db, g) for g in s.games]


# ---------------------------------------------------------------- 결과

def _result(db: Session, admin: Member, gid: int, body: ResultIn) -> dict:
    g = _game_by_id(db, gid)
    judged = ops.submit_result(db, admin, g, body.score_a, body.score_b)
    out = _game_out(db, g)
    if judged is not None:
        out.update({"lopsided": judged.lopsided, "margin": judged.margin, "ratio": judged.ratio})
    return out


@router.post("/games/{gid}/result")
def post_result(gid: int, body: ResultIn, db: Session = Depends(get_db), admin=Depends(require_admin)):
    if _game_by_id(db, gid).status == "finished":
        raise HTTPException(409, "이미 결과가 있습니다. PATCH로 수정하세요.")
    return _result(db, admin, gid, body)


@router.patch("/games/{gid}/result")
def patch_result(gid: int, body: ResultIn, db: Session = Depends(get_db), admin=Depends(require_admin)):
    return _result(db, admin, gid, body)


# ---------------------------------------------------------------- 기록

@router.get("/stats")
def stats(season: int | None = None, sort: str = "attendance", db: Session = Depends(get_db)):
    st = compute_stats(db, season or settings.SEASON)
    return [s.as_dict() for s in leaderboard(st, sort)]


@router.get("/admin/ratings")
def admin_ratings(db: Session = Depends(get_db), admin=Depends(require_admin)):
    members = db.scalars(select(Member).order_by(Member.mu.desc())).all()
    counts: dict[int, int] = {}
    for (mid,) in db.execute(select(RatingHistory.member_id)).all():
        counts[mid] = counts.get(mid, 0) + 1
    return [{"id": m.id, "name": m.name, "grade": round(mu_to_grade(m.mu), 2),
             "confidence": confidence(counts.get(m.id, 0))[0], "mu": round(m.mu, 3), "sigma": round(m.sigma, 3),
             "initial_grade": m.initial_grade, "games": counts.get(m.id, 0), "is_active": m.is_active}
            for m in members]
