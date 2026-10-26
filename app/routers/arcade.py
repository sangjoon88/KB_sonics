"""미니게임 화면·API: 3점슛 콘테스트."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import current_admin, current_member
from app.config import settings
from app.db import get_db
from app.models import Member
from app.routers.common import redirect, render
from app.services import arcade
from app.timeutil import now_kst

router = APIRouter()

TOP_N = 10


def ranking_ctx(db: Session, me) -> dict:
    week = arcade.leaderboard(db, *arcade.week_range())
    season = arcade.leaderboard(db, *arcade.season_range(settings.SEASON))
    return {"week_rows": week, "season_rows": season,
            "my_week": arcade.find(week, me.id) if me else None,
            "my_season": arcade.find(season, me.id) if me else None,
            "sent_to": arcade.challenges(db, me).sent_to if me else set(),
            "top_n": TOP_N, "max_score": arcade.MAX_SCORE}


@router.get("/arcade")
def arcade_page(request: Request, db: Session = Depends(get_db), me=Depends(current_member),
                admin=Depends(current_admin)):
    if me is None:
        return redirect("/pick?next=/arcade")
    from app.routers.pages import _gate  # 순환 import 방지
    if (gate := _gate(me, "/arcade")) is not None:
        return gate
    ctx = ranking_ctx(db, me)
    ctx["ch"] = arcade.challenges(db, me)
    ctx.update({"game_seconds": arcade.GAME_SECONDS, "racks": arcade.RACKS, "balls": arcade.BALLS_PER_RACK,
                "ghosts": arcade.ghosts(db, me, settings.SEASON),
                "my_stats": arcade.my_stats(db, me, settings.SEASON)})
    return render(request, "arcade.html", ctx, member=me, admin=admin)


@router.get("/arcade/ranking")
def arcade_ranking(request: Request, tab: str = "week", db: Session = Depends(get_db),
                   me=Depends(current_member)):
    ctx = ranking_ctx(db, me)
    ctx["tab"] = "season" if tab == "season" else "week"
    return render(request, "_arcade_ranking.html", ctx, member=me)


@router.get("/arcade/stats")
def arcade_stats(request: Request, db: Session = Depends(get_db), me=Depends(current_member)):
    if me is None:
        return redirect("/pick?next=/arcade")
    return render(request, "_arcade_stats.html", {"my_stats": arcade.my_stats(db, me, settings.SEASON)}, member=me)


@router.get("/arcade/challenges")
def arcade_challenges(request: Request, db: Session = Depends(get_db), me=Depends(current_member)):
    if me is None:
        return redirect("/pick?next=/arcade")
    return render(request, "_arcade_challenges.html", {"ch": arcade.challenges(db, me)}, member=me)


def _challenge_dialog(request: Request, db: Session, me, to_id: int, **extra):
    to = db.get(Member, to_id)
    mine = arcade.find(arcade.leaderboard(db, *arcade.season_range(settings.SEASON)), me.id)
    ctx = {"to": to, "target": mine.score if mine else 0, "done": False, "error": ""}
    if to is None or to.is_guest or to.id == me.id:
        ctx["error"] = "도전장을 보낼 수 없는 상대예요."
    elif mine is None or mine.score <= 0:
        ctx["error"] = "먼저 한 판 해서 기록을 남겨야 도전장을 보낼 수 있어요."
    ctx.update(extra)
    return render(request, "_arcade_challenge_dialog.html", ctx, member=me)


@router.get("/arcade/challenge/{to_id}")
def arcade_challenge_confirm(request: Request, to_id: int, db: Session = Depends(get_db),
                             me=Depends(current_member)):
    if me is None:
        return redirect("/pick?next=/arcade")
    return _challenge_dialog(request, db, me, to_id)


@router.post("/arcade/challenges")
def arcade_challenge(request: Request, to_id: int = Form(...), db: Session = Depends(get_db),
                     me=Depends(current_member)):
    if me is None:
        return _err("이름을 먼저 선택하세요.", 401)
    try:
        ch = arcade.send_challenge(db, me, to_id, settings.SEASON)
    except arcade.ArcadeError as e:
        return _challenge_dialog(request, db, me, to_id, error=str(e))
    resp = _challenge_dialog(request, db, me, to_id, done=True, target=ch.target)
    resp.headers["HX-Trigger"] = "arcadeChanged"        # 도전장 목록·랭킹 버튼 새로고침
    return resp


class FinishBody(BaseModel):
    made: int | None = None
    money: int | None = None
    shots: str | None = None
    events: list | None = None


def _err(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"detail": msg}, status_code=code)


@router.post("/arcade/runs")
def arcade_start(db: Session = Depends(get_db), me=Depends(current_member)):
    if me is None:
        return _err("이름을 먼저 선택하세요.", 401)
    try:
        run = arcade.start_run(db, me)
    except arcade.ArcadeError as e:
        return _err(str(e), 429)
    return {"run_id": run.id, "seconds": arcade.GAME_SECONDS}


@router.post("/arcade/runs/{run_id}/finish")
def arcade_finish(run_id: int, body: FinishBody, db: Session = Depends(get_db), me=Depends(current_member)):
    if me is None:
        return _err("이름을 먼저 선택하세요.", 401)
    week_rows = arcade.leaderboard(db, *arcade.week_range())
    before = arcade.find(week_rows, me.id)
    season_before = arcade.find(arcade.leaderboard(db, *arcade.season_range(settings.SEASON)), me.id)
    try:
        run = arcade.finish_run(db, me, run_id, body.made, body.money, shots=body.shots, events=body.events)
    except arcade.ArcadeError as e:
        return _err(str(e))
    week_after = arcade.find(arcade.leaderboard(db, *arcade.week_range()), me.id)
    return {
        "score": run.score, "made": run.made,
        "week_best": week_after.score if week_after else run.score,
        "week_rank": week_after.rank if week_after else None,
        "new_week_best": before is None or run.score > before.score,
        "new_season_best": season_before is None or run.score > season_before.score,
        "beaten": [{"name": ch.sender.name, "target": ch.target} for ch in run.beaten],
        "at": now_kst().isoformat(),
    }
