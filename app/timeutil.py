from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import SESSION_WEEKDAY, TIMEZONE, VOTE_DEADLINE_HOUR

KST = ZoneInfo(TIMEZONE)
WEEKDAY_KO = "월화수목금토일"


def now_kst() -> datetime:
    """KST 현재 시각 (naive)."""
    return datetime.now(KST).replace(tzinfo=None, microsecond=0)


def today_kst() -> date:
    return now_kst().date()


def next_session_date(base: date | None = None) -> date:
    """오늘 포함 가장 가까운 일요일."""
    base = base or today_kst()
    return base + timedelta(days=(SESSION_WEEKDAY - base.weekday()) % 7)


def default_vote_deadline(session_date: date) -> datetime:
    """기본: 모임 전날(토) 22:00."""
    d = session_date - timedelta(days=1)
    return datetime(d.year, d.month, d.day, VOTE_DEADLINE_HOUR, 0)


def fmt_date(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAY_KO[d.weekday()]})"


def fmt_session(s) -> str:
    """'10/19(일) 08:00' (시작 시간이 없으면 날짜만)."""
    return f"{fmt_date(s.date)} {s.start_time}" if getattr(s, "start_time", None) else fmt_date(s.date)


def fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "-"
    return f"{fmt_date(dt.date())} {dt.hour:02d}:{dt.minute:02d}"
