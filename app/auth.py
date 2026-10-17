"""멤버 쿠키 + 운영진 개인 PIN (명세서 3장)."""
from __future__ import annotations

from datetime import timedelta

import bcrypt
from fastapi import Depends, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import (ADMIN_COOKIE_DAYS, MEMBER_COOKIE_DAYS, PIN_LOCK_MINUTES, PIN_MAX_FAILS,
                        settings)
from app.db import get_db
from app.models import Member
from app.timeutil import now_kst

MEMBER_COOKIE = "bc_member"
ADMIN_COOKIE = "bc_admin"

_signer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="basket-club")


class AdminRequired(Exception):
    """운영진 권한 필요. HTML 경로는 로그인으로 리다이렉트, /api 는 401."""


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def check_pin_hash(pin: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(pin.encode(), hashed.encode())
    except ValueError:
        return False


def valid_pin_format(pin: str) -> bool:
    return pin.isdigit() and 4 <= len(pin) <= 6


_default_hash_cache: list[str] = []


def default_pin_hash() -> str:
    """초기 PIN 해시 (일괄 등록 시 bcrypt를 사람 수만큼 돌리지 않도록 프로세스당 1회 계산)."""
    from app.config import DEFAULT_PIN
    if not _default_hash_cache:
        _default_hash_cache.append(hash_pin(DEFAULT_PIN))
    return _default_hash_cache[0]


def set_member_cookie(response: Response, member_id: int) -> None:
    response.set_cookie(MEMBER_COOKIE, _signer.dumps({"member_id": member_id}),
                        max_age=MEMBER_COOKIE_DAYS * 86400, httponly=True, samesite="lax",
                        secure=settings.COOKIE_SECURE)


def set_admin_cookie(response: Response, member_id: int) -> None:
    response.set_cookie(ADMIN_COOKIE, _signer.dumps({"member_id": member_id, "role": "admin"}),
                        max_age=ADMIN_COOKIE_DAYS * 86400, httponly=True, samesite="lax",
                        secure=settings.COOKIE_SECURE)


def clear_cookies(response: Response) -> None:
    response.delete_cookie(MEMBER_COOKIE)
    response.delete_cookie(ADMIN_COOKIE)


def _load(request: Request, name: str, max_days: int) -> dict | None:
    raw = request.cookies.get(name)
    if not raw:
        return None
    try:
        return _signer.loads(raw, max_age=max_days * 86400)
    except BadSignature:
        return None


def current_member(request: Request, db: Session = Depends(get_db)) -> Member | None:
    data = _load(request, MEMBER_COOKIE, MEMBER_COOKIE_DAYS)
    if not data:
        return None
    m = db.get(Member, data.get("member_id"))
    return m if m and m.is_active else None


def current_admin(request: Request, db: Session = Depends(get_db)) -> Member | None:
    data = _load(request, ADMIN_COOKIE, ADMIN_COOKIE_DAYS)
    if not data or data.get("role") != "admin":
        return None
    m = db.get(Member, data.get("member_id"))
    # 운영진 해제/비활성화되면 쿠키가 남아 있어도 즉시 권한 상실
    return m if m and m.is_admin and m.is_active else None


def require_admin(admin: Member | None = Depends(current_admin)) -> Member:
    if admin is None:
        raise AdminRequired()
    return admin


class PinResult:
    OK = "ok"
    WRONG = "wrong"
    LOCKED = "locked"
    NO_PIN = "no_pin"


PIN_ERRORS = {
    "wrong": "PIN이 틀렸습니다. (남은 시도 {n}회)",
    "locked": "5회 실패로 잠겼습니다. {n}분 후 다시 시도하세요.",
    "no_pin": "PIN이 설정되지 않았습니다. 운영진에게 초기화를 요청하세요.",
}


def pin_error(result: str, n: int) -> str:
    return PIN_ERRORS[result].format(n=n)


def verify_pin(db: Session, member: Member, pin: str) -> tuple[str, int]:
    """PIN 검증. (결과, 남은 시도 or 잠금 남은 분). 실패 횟수는 DB에 저장 (서버리스)."""
    if not member.pin_hash:
        return PinResult.NO_PIN, 0
    now = now_kst()
    if member.pin_locked_until and member.pin_locked_until > now:
        mins = int((member.pin_locked_until - now).total_seconds() // 60) + 1
        return PinResult.LOCKED, mins
    if check_pin_hash(pin, member.pin_hash):
        member.pin_fail_count = 0
        member.pin_locked_until = None
        db.commit()
        return PinResult.OK, 0
    member.pin_fail_count = (member.pin_fail_count or 0) + 1
    if member.pin_fail_count >= PIN_MAX_FAILS:
        member.pin_locked_until = now + timedelta(minutes=PIN_LOCK_MINUTES)
        member.pin_fail_count = 0
        db.commit()
        return PinResult.LOCKED, PIN_LOCK_MINUTES
    db.commit()
    return PinResult.WRONG, PIN_MAX_FAILS - member.pin_fail_count
