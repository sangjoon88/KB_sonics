from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import current_admin, current_member, require_admin
from app.config import BALANCE_MODE_LABELS, settings
from app.models import Member
from app.services.rating import confidence, mu_to_grade
from app.timeutil import fmt_date, fmt_dt, fmt_session

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals.update(
    fmt_date=fmt_date, fmt_dt=fmt_dt, fmt_session=fmt_session, season=settings.SEASON,
    POS_LABEL={"G": "가드", "F": "포워드", "C": "센터"},
    VOTE_LABEL={"yes": "참석", "no": "불참", "early": "조퇴"},
    STATUS_LABEL={"open": "투표 중", "closed": "투표 마감", "finished": "종료"},
    MODE_LABEL={"balanced": "자동 밸런싱", "kept": "팀 유지", "reshuffled": "재편성"},
    BALANCE_MODE_LABELS=BALANCE_MODE_LABELS,
    grade_of=mu_to_grade, confidence=confidence,
)


class PinChangeRequired(Exception):
    pass


def render(request: Request, name: str, ctx: dict | None = None, *, member=None, admin=None,
           status_code: int = 200):
    ctx = dict(ctx or {})
    ctx.setdefault("me", member)
    ctx.setdefault("admin", admin)
    ctx.setdefault("msg", request.query_params.get("msg"))
    ctx.setdefault("err", request.query_params.get("err"))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def redirect(url: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    if msg:
        url += f"{sep}msg={quote(msg)}"
        sep = "&"
    if err:
        url += f"{sep}err={quote(err)}"
    return RedirectResponse(url, status_code=303)


def admin_page(admin: Member = Depends(require_admin)) -> Member:
    """운영진 HTML 화면용: 임시 PIN이면 변경부터."""
    if admin.pin_must_change:
        raise PinChangeRequired()
    return admin


__all__ = ["templates", "render", "redirect", "admin_page", "current_member", "current_admin"]
