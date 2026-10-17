"""HTML 화면과 JSON API가 함께 쓰는 운영 로직."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import default_pin_hash
from app.config import (BALANCE_MODES, DEFAULT_LOCATION, DEFAULT_PIN, SESSION_START_TIME, EXHAUSTIVE_MAX_PLAYERS, GRADE_DISAGREE_THRESHOLD,
                        INACTIVE_WEEKS, INITIAL_SIGMA, REPEAT_LOOKBACK_WEEKS, TOP_K_CANDIDATES,
                        WEIGHTS)
from app.models import (POSITIONS, VOTES, AdminLog, AppSetting, Attendance, ClubSession, Game,
                        GameRoster, InitialRating, Member, RatingHistory)
from app.services import balancer, lopsided, rating
from app.services.stats import last_attended
from app.timeutil import now_kst


class OpError(Exception):
    """사용자에게 보여줄 수 있는 업무 오류."""


# ---------------------------------------------------------------- 공통

def log(db: Session, admin: Member, action: str, target: str, detail: dict | None = None) -> None:
    db.add(AdminLog(admin_id=admin.id, action=action, target=target, detail=detail or {}))


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def balance_mode(db: Session) -> str:
    mode = get_setting(db, "balance_mode", "balanced")
    return mode if mode in BALANCE_MODES else "balanced"


def current_weights(db: Session) -> dict:
    return {**WEIGHTS, "height": BALANCE_MODES[balance_mode(db)]}


def admin_exists(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(Member).where(Member.is_admin.is_(True))) > 0


# ---------------------------------------------------------------- 멤버

POSITION_ALIASES = {"G": "G", "F": "F", "C": "C", "가드": "G", "포워드": "F", "센터": "C",
                    "PG": "G", "SG": "G", "SF": "F", "PF": "F"}


def normalize_position(raw: str | None) -> str | None:
    if not raw:
        return None
    return POSITION_ALIASES.get(raw.strip().upper()) or POSITION_ALIASES.get(raw.strip())


def parse_positions(raw: str | None) -> tuple[str | None, str | None]:
    """'G' / 'G/F' / '가드,포워드' → (주, 부)."""
    if not raw or not raw.strip():
        return None, None
    parts = [x for x in re.split(r"[/|·]", raw) if x.strip()]
    main = normalize_position(parts[0])
    sub_ = normalize_position(parts[1]) if len(parts) > 1 else None
    if main is None or (len(parts) > 1 and sub_ is None):
        raise ValueError(f"포지션 '{raw}' 인식 불가 (G/F/C, 두 개면 G/F)")
    return main, (sub_ if sub_ != main else None)


def parse_weight(raw: str | None) -> int | None:
    if raw is None or str(raw).strip() == "":
        return None
    m = re.fullmatch(r"\s*(\d{2,3})(?:\s*kg)?\s*", str(raw), re.I)
    if not m or not (30 <= int(m.group(1)) <= 200):
        raise ValueError("몸무게는 30~200 사이 숫자")
    return int(m.group(1))


def parse_height(raw: str | None) -> int | None:
    if raw is None or str(raw).strip() == "":
        return None
    m = re.fullmatch(r"\s*(\d{3})(?:\s*cm)?\s*", str(raw), re.I)
    if not m or not (130 <= int(m.group(1)) <= 230):
        raise ValueError("키는 130~230 사이 숫자")
    return int(m.group(1))


@dataclass
class ImportRow:
    line_no: int
    raw: str
    name: str
    position: str | None = None
    position2: str | None = None
    height: int | None = None
    error: str | None = None
    duplicate: bool = False

    @property
    def ok(self) -> bool:
        return not self.error and not self.duplicate


def parse_import(text: str, existing_names: set[str]) -> list[ImportRow]:
    """'이름[,포지션[,키]]' 줄 단위 파싱. 쉼표/탭 구분, 포지션 두 개는 'G/F'. 중복 이름은 경고."""
    rows: list[ImportRow] = []
    seen: set[str] = set()
    for i, line in enumerate(text.splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        parts = [p.strip() for p in re.split(r"[,\t]", raw)]
        row = ImportRow(line_no=i, raw=raw, name=parts[0])
        if not row.name:
            row.error = "이름 없음"
        elif len(row.name) > 50:
            row.error = "이름이 너무 김"
        if len(parts) > 1 and parts[1]:
            try:
                row.position, row.position2 = parse_positions(parts[1])
            except ValueError as e:
                row.error = str(e)
        if len(parts) > 2 and parts[2]:
            try:
                row.height = parse_height(parts[2])
            except ValueError as e:
                row.error = str(e)
        if row.name and (row.name in existing_names or row.name in seen):
            row.duplicate = True
        seen.add(row.name)
        rows.append(row)
    return rows


def import_members(db: Session, admin: Member, text: str) -> list[ImportRow]:
    existing = set(db.scalars(select(Member.name)).all())
    rows = parse_import(text, existing)
    added = []
    pin = default_pin_hash()
    for r in rows:
        if r.ok:
            db.add(Member(name=r.name, position=r.position, position2=r.position2, height_cm=r.height,
                          mu=25.0, sigma=INITIAL_SIGMA, pin_hash=pin, pin_must_change=True))
            added.append(r.name)
    if added:
        log(db, admin, "member.import", f"count:{len(added)}", {"names": added})
    db.commit()
    return rows


def create_member(db: Session, admin: Member, name: str, position: str | None = None,
                  height: int | None = None, position2: str | None = None) -> Member:
    """운영진이 멤버 등록. 초기 PIN은 DEFAULT_PIN, 첫 로그인 때 본인이 변경."""
    name = name.strip()
    if not name:
        raise OpError("이름을 입력하세요.")
    existing = db.scalar(select(Member).where(Member.name == name))
    if existing and existing.is_guest:
        # 게스트로 오던 사람이 정식 가입: 기록·레이팅을 이어서 멤버로 전환
        existing.is_guest = False
        existing.is_active = True
        existing.pin_hash = existing.pin_hash or default_pin_hash()
        existing.pin_must_change = True
        existing.position = normalize_position(position) or existing.position
        existing.height_cm = height or existing.height_cm
        log(db, admin, "member.promote_guest", f"member:{existing.id}", {"name": name})
        db.commit()
        return existing
    if existing:
        raise OpError(f"이미 있는 이름입니다: {name} (동명이인은 '{name}(부서)'처럼 구분)")
    main = normalize_position(position)
    sub_ = normalize_position(position2)
    m = Member(name=name, position=main, position2=sub_ if sub_ != main else None, height_cm=height,
               mu=25.0, sigma=INITIAL_SIGMA, pin_hash=default_pin_hash(), pin_must_change=True)
    db.add(m)
    db.flush()
    log(db, admin, "member.create", f"member:{m.id}", {"name": name})
    db.commit()
    return m


_UNSET = object()


def update_member(db: Session, admin: Member | None, m: Member, *, name: str | None = None,
                  position: str | None = None, height: int | None = None,
                  is_active: bool | None = None, position2=_UNSET, weight=_UNSET) -> None:
    """None 은 '변경 안 함'. position="" 은 지우기. position2/weight 는 명시하면 None 으로도 설정."""
    def snap():
        return {"name": m.name, "position": m.position, "position2": m.position2, "height_cm": m.height_cm,
                "weight_kg": m.weight_kg, "is_active": m.is_active}
    before = snap()
    if name is not None and name.strip() and name.strip() != m.name:
        if db.scalar(select(Member).where(Member.name == name.strip(), Member.id != m.id)):
            raise OpError("이미 있는 이름입니다.")
        m.name = name.strip()
    if position is not None:
        if position == "":
            m.position = None
        else:
            p = normalize_position(position)
            if p not in POSITIONS:
                raise OpError("포지션은 G/F/C 중 하나")
            m.position = p
    if position2 is not _UNSET:
        p2 = normalize_position(position2) if position2 else None
        if position2 and p2 is None:
            raise OpError("부 포지션은 G/F/C 중 하나")
        m.position2 = p2 if p2 != m.position else None
    if height is not None:
        m.height_cm = height
    if weight is not _UNSET:
        m.weight_kg = weight
    if is_active is not None:
        m.is_active = is_active
    after = snap()
    if admin and before != after:
        log(db, admin, "member.update", f"member:{m.id}", {"before": before, "after": after})
    db.commit()


def _require_owner(admin: Member) -> None:
    if not admin.is_owner:
        raise OpError("관리자만 운영진 권한을 관리할 수 있습니다.")


def set_admin_role(db: Session, admin: Member, m: Member, on: bool) -> None:
    """운영진 지정/해제 (관리자 전용). 본인 PIN은 그대로 유지된다."""
    _require_owner(admin)
    if m.is_owner:
        raise OpError("관리자의 권한은 바꿀 수 없습니다.")
    m.is_admin = on
    if on and not m.pin_hash:
        m.pin_hash = default_pin_hash()
        m.pin_must_change = True
    log(db, admin, "member.admin_on" if on else "member.admin_off", f"member:{m.id}")
    db.commit()


def reset_pin(db: Session, admin: Member, m: Member) -> str:
    """PIN을 초기값으로 되돌린다 (본인이 다음 로그인 때 변경). 운영진 PIN은 관리자만."""
    if m.is_owner:
        raise OpError("관리자 PIN은 'PIN 변경' 화면에서 직접 바꾸세요.")
    if m.is_admin and not admin.is_owner:
        raise OpError("운영진의 PIN은 관리자만 초기화할 수 있습니다.")
    if m.is_guest:
        raise OpError("게스트는 PIN이 없습니다.")
    m.pin_hash = default_pin_hash()
    m.pin_must_change = True
    m.pin_fail_count = 0
    m.pin_locked_until = None
    log(db, admin, "member.pin_reset", f"member:{m.id}")
    db.commit()
    return DEFAULT_PIN


# ---------------------------------------------------------------- 초기 등급 평가

@dataclass
class GradeRow:
    member: Member
    my_grade: int | None
    grades: list[int]
    avg: float | None
    disagree: bool


def grade_rows(db: Session, admin: Member) -> list[GradeRow]:
    members = db.scalars(select(Member).where(Member.is_active.is_(True)).order_by(Member.name)).all()
    all_ratings = db.scalars(select(InitialRating)).all()
    by_member: dict[int, list[InitialRating]] = {}
    for r in all_ratings:
        by_member.setdefault(r.member_id, []).append(r)
    rows = []
    for m in members:
        rs = by_member.get(m.id, [])
        grades = [r.grade for r in rs]
        mine = next((r.grade for r in rs if r.rater_id == admin.id), None)
        avg = round(sum(grades) / len(grades), 2) if grades else None
        disagree = len(grades) >= 2 and max(grades) - min(grades) >= GRADE_DISAGREE_THRESHOLD
        rows.append(GradeRow(m, mine, grades, avg, disagree))
    # 미확정 멤버를 위로
    rows.sort(key=lambda r: (r.member.initial_grade is not None, r.member.name))
    return rows


def raters_status(db: Session) -> list[tuple[Member, int]]:
    admins = db.scalars(select(Member).where(Member.is_admin.is_(True)).order_by(Member.name)).all()
    counts = dict(db.execute(select(InitialRating.rater_id, func.count())
                             .group_by(InitialRating.rater_id)).all())
    return [(a, counts.get(a.id, 0)) for a in admins]


def save_my_grades(db: Session, admin: Member, grades: dict[int, int]) -> int:
    n = 0
    for member_id, g in grades.items():
        if g not in (1, 2, 3, 4, 5):
            raise OpError("등급은 1~5")
        row = db.get(InitialRating, (admin.id, member_id))
        if row:
            row.grade = g
            row.created_at = now_kst()
        else:
            db.add(InitialRating(rater_id=admin.id, member_id=member_id, grade=g))
        n += 1
    db.commit()
    return n


def confirm_grades(db: Session, admin: Member, grades: dict[int, float]) -> int:
    """평균(조정값) 확정 → initial_grade 저장, 경기 기록이 없는 멤버는 mu/sigma 초기화."""
    n = 0
    for member_id, g in grades.items():
        if not (1.0 <= g <= 5.0):
            raise OpError("등급은 1.0~5.0")
        m = db.get(Member, member_id)
        if m is None:
            continue
        m.initial_grade = round(g, 2)
        has_history = db.scalar(select(func.count()).select_from(RatingHistory)
                                .where(RatingHistory.member_id == m.id)) > 0
        if not has_history:
            m.mu, m.sigma = rating.grade_to_rating(m.initial_grade)
        n += 1
    log(db, admin, "rating.confirm", f"count:{n}", {str(k): v for k, v in grades.items()})
    db.commit()
    return n


# ---------------------------------------------------------------- 모임 / 투표 / 출석

def parse_hhmm(raw: str | None, label: str = "시간") -> str:
    m = re.fullmatch(r"\s*([01]?\d|2[0-3]):([0-5]\d)(?::\d\d)?\s*", raw or "")
    if not m:
        raise OpError(f"{label}을 입력하세요. (예: 08:00)")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def create_session(db: Session, admin: Member, d: date, location: str | None = None,
                   deadline: datetime | None = None, start_time: str | None = None) -> ClubSession:
    """경기 등록 → 바로 투표 열림. 기본: 08:00, 기본 장소, 투표 마감 없음."""
    if db.scalar(select(ClubSession).where(ClubSession.date == d)):
        raise OpError("해당 날짜 경기가 이미 있습니다.")
    loc = DEFAULT_LOCATION if location is None else (location.strip() or None)
    s = ClubSession(date=d, location=loc, start_time=parse_hhmm(start_time or SESSION_START_TIME, "시작 시간"),
                    vote_deadline=deadline, status="open")
    db.add(s)
    db.flush()
    log(db, admin, "session.create", f"session:{s.id}", {"date": d.isoformat(), "start_time": s.start_time})
    db.commit()
    return s


def update_session_info(db: Session, admin: Member, s: ClubSession, *, start_time: str | None = None,
                        location: str | None = None) -> None:
    before = {"start_time": s.start_time, "location": s.location}
    if start_time is not None:
        s.start_time = parse_hhmm(start_time, "시작 시간")
    if location is not None:
        s.location = location.strip() or None
    log(db, admin, "session.update", f"session:{s.id}", {"before": before,
                                                         "after": {"start_time": s.start_time, "location": s.location}})
    db.commit()


def upcoming_session(db: Session, today: date) -> ClubSession | None:
    s = db.scalar(select(ClubSession).where(ClubSession.date >= today, ClubSession.status != "finished")
                  .order_by(ClubSession.date).limit(1))
    return s or db.scalar(select(ClubSession).order_by(ClubSession.date.desc()).limit(1))


def voting_open(s: ClubSession) -> bool:
    if s.status != "open":
        return False
    return not (s.vote_deadline and now_kst() > s.vote_deadline)


def get_attendance(db: Session, s: ClubSession, member_id: int) -> Attendance | None:
    return db.scalar(select(Attendance).where(Attendance.session_id == s.id,
                                              Attendance.member_id == member_id))


def parse_leave_time(raw: str | None) -> str:
    return parse_hhmm(raw, "조퇴 시간")


def vote(db: Session, s: ClubSession, member: Member, v: str, leave_time: str | None = None) -> Attendance:
    if v not in VOTES:
        raise OpError("투표 값은 yes/no/early")
    leave = parse_leave_time(leave_time) if v == "early" else None
    if not voting_open(s):
        raise OpError("투표가 마감되었습니다. 운영진에게 말해주세요.")
    a = get_attendance(db, s, member.id)
    if a is None:
        a = Attendance(session_id=s.id, member_id=member.id, checked_in=False)
        db.add(a)
    a.vote = v
    a.leave_time = leave
    a.voted_at = now_kst()
    a.proxy_by = None  # 본인이 직접 투표하면 대리 표시 해제
    db.commit()
    db.expire(s, ["attendances"])  # expire_on_commit=False 라서 목록을 다시 읽게 한다
    return a


def set_checkin(db: Session, admin: Member, s: ClubSession, member_id: int, checked_in: bool) -> Attendance:
    m = db.get(Member, member_id)
    if m is None:
        raise OpError("멤버가 없습니다.")
    a = get_attendance(db, s, member_id)
    if a is None:
        a = Attendance(session_id=s.id, member_id=member_id, vote=None, checked_in=False)
        db.add(a)
    if checked_in and not a.checked_in:
        # 9.5 장기 미출석 복귀: sigma를 초기값 쪽으로 절반 되돌려 빠르게 재보정
        last = last_attended(db, member_id)
        if last and (s.date - last).days >= INACTIVE_WEEKS * 7:
            m.sigma = max(m.sigma, (m.sigma + INITIAL_SIGMA) / 2)
    a.checked_in = checked_in
    if s.status == "open":
        s.status = "closed"  # 현장 체크가 시작되면 투표 마감
    db.commit()
    db.expire(s, ["attendances"])
    return a


def proxy_vote(db: Session, admin: Member, s: ClubSession, member_id: int, v: str,
               leave_time: str | None = None) -> Attendance | None:
    """운영진 대리 투표 (구두로 참석 의사를 밝힌 경우). 마감 후에도 가능. v='clear' 면 투표 삭제."""
    m = db.get(Member, member_id)
    if m is None or not m.is_active or m.is_guest:
        raise OpError("멤버를 선택하세요.")
    if v != "clear" and v not in VOTES:
        raise OpError("투표 값은 yes/no/early")
    leave = parse_leave_time(leave_time) if v == "early" else None
    a = get_attendance(db, s, member_id)
    if v == "clear":
        if a is not None:
            a.vote, a.leave_time, a.voted_at, a.proxy_by = None, None, None, None
    else:
        if a is None:
            a = Attendance(session_id=s.id, member_id=member_id, checked_in=False)
            db.add(a)
        a.vote, a.leave_time, a.voted_at, a.proxy_by = v, leave, now_kst(), admin.id
    log(db, admin, "vote.proxy", f"session:{s.id}", {"member": m.name, "vote": v, "leave_time": leave})
    db.commit()
    db.expire(s, ["attendances"])
    return a


def preview_teams(db: Session, s: ClubSession) -> dict:
    """투표 기준 예상 팀 (참석 + 조퇴 + 게스트). 레이팅 숫자는 노출하지 않는다."""
    atts = [a for a in s.attendances if a.vote in ("yes", "early")]
    members = [a.member for a in atts]
    early = {a.member_id: a.leave_time for a in atts if a.vote == "early" and a.leave_time}
    n = len(members)
    if n < 4:
        return {"status": "few", "n": n}
    if n > EXHAUSTIVE_MAX_PLAYERS:
        return {"status": "many", "n": n}
    try:
        c = balancer.balance(_players(members), weights=current_weights(db),
                             weekly_pairs=weekly_history(db, s), top_k=1)[0]
    except balancer.BalanceError:
        return {"status": "few", "n": n}
    by_id = {m.id: m for m in members}
    return {"status": "ok", "n": n, "a": [by_id[i] for i in c.team_a], "b": [by_id[i] for i in c.team_b],
            "label": balancer.balance_label(c.breakdown), "early": early}


GUEST_DEFAULT_GRADE = 3


def add_guest(db: Session, s: ClubSession, inviter: Member | None, name: str, *, grade: float | None = None,
              height: int | None = None, position: str | None = None, checked_in: bool = False,
              by_admin: Member | None = None) -> Attendance:
    """게스트 참석 등록. 같은 이름의 게스트가 예전에 왔으면 그 기록(레이팅)을 이어서 쓴다."""
    name = (name or "").strip()
    if not name:
        raise OpError("게스트 이름을 입력하세요.")
    if len(name) > 50:
        raise OpError("이름이 너무 깁니다.")
    if by_admin is None and not voting_open(s):
        raise OpError("투표가 마감되어 게스트를 추가할 수 없습니다. 운영진에게 말해주세요.")
    grade = float(grade or GUEST_DEFAULT_GRADE)
    if not (1 <= grade <= 5):
        raise OpError("실력은 1~5")
    g = db.scalar(select(Member).where(Member.name == name))
    if g is not None and not g.is_guest:
        raise OpError(f"'{name}'은(는) 이미 멤버입니다. 본인이 직접 투표하거나, 다른 이름으로 구분하세요. (예: {name}(게스트))")
    if g is None:
        g = Member(name=name, is_guest=True, is_active=False)
        db.add(g)
    has_history = g.id is not None and db.scalar(
        select(func.count()).select_from(RatingHistory).where(RatingHistory.member_id == g.id)) > 0
    if not has_history:
        g.initial_grade = grade
        g.mu, g.sigma = rating.grade_to_rating(grade)
    if height:
        g.height_cm = height
    if position:
        g.position = normalize_position(position)
    db.flush()
    a = get_attendance(db, s, g.id)
    if a is None:
        a = Attendance(session_id=s.id, member_id=g.id, checked_in=False)
        db.add(a)
    a.vote = "yes"
    a.leave_time = None
    a.voted_at = now_kst()
    a.guest_of = inviter.id if inviter else None
    if checked_in:
        a.checked_in = True
    if by_admin:
        log(db, by_admin, "guest.add", f"session:{s.id}", {"guest": name, "grade": grade})
    db.commit()
    db.expire(s, ["attendances"])
    return a


def remove_guest(db: Session, s: ClubSession, guest_id: int, *, actor: Member | None,
                 by_admin: Member | None = None) -> None:
    a = get_attendance(db, s, guest_id)
    if a is None or not a.member.is_guest:
        raise OpError("게스트 참석 기록이 없습니다.")
    if by_admin is None:
        if actor is None or a.guest_of != actor.id:
            raise OpError("본인이 데려온 게스트만 취소할 수 있습니다.")
        if not voting_open(s):
            raise OpError("투표가 마감되었습니다. 운영진에게 말해주세요.")
    in_roster = db.scalar(select(func.count()).select_from(GameRoster).join(Game).where(
        Game.session_id == s.id, GameRoster.member_id == guest_id)) > 0
    if in_roster:
        raise OpError("이미 팀 명단에 있는 게스트입니다. 팀 짜기 화면에서 먼저 빼주세요.")
    db.delete(a)
    if by_admin:
        log(db, by_admin, "guest.remove", f"session:{s.id}", {"guest": a.member.name})
    db.commit()
    db.expire(s, ["attendances"])


def session_guests(s: ClubSession) -> list[Attendance]:
    return [a for a in s.attendances if a.member.is_guest]


def checked_in_members(db: Session, s: ClubSession) -> list[Member]:
    return db.scalars(select(Member).join(Attendance, Attendance.member_id == Member.id).where(
        Attendance.session_id == s.id, Attendance.checked_in.is_(True)).order_by(Member.name)).all()


def set_session_status(db: Session, admin: Member, s: ClubSession, status: str) -> None:
    if status not in ("open", "closed", "finished"):
        raise OpError("잘못된 상태")
    s.status = status
    log(db, admin, "session.status", f"session:{s.id}", {"status": status})
    db.commit()


# ---------------------------------------------------------------- 팀 짜기

def team_readiness(members: list[Member]) -> tuple[list[str], list[str]]:
    """(차단 사유, 경고). 등급 미확정이면 팀 짜기 불가, 키 미입력은 경고."""
    errors, warnings = [], []
    unrated = [m.name for m in members if m.initial_grade is None]
    if unrated:
        errors.append("초기 등급 미확정: " + ", ".join(unrated))
    if len(members) < 2:
        errors.append("출석 체크된 인원이 2명 이상이어야 합니다.")
    if len(members) > EXHAUSTIVE_MAX_PLAYERS:
        errors.append(f"{len(members)}명: 전수 탐색 한도({EXHAUSTIVE_MAX_PLAYERS}명) 초과 — 팀 수동 구성 필요")
    no_height = [m.name for m in members if not m.height_cm]
    if no_height:
        warnings.append(f"키 미입력 {len(no_height)}명 ({', '.join(no_height)}) — 참가자 중앙값으로 계산")
    no_pos = [m.name for m in members if not m.position]
    if no_pos:
        warnings.append(f"포지션 미입력 {len(no_pos)}명")
    return errors, warnings


def _players(members: list[Member]) -> list[balancer.Player]:
    return [balancer.Player(id=m.id, mu=m.mu, position=m.position, height=m.height_cm) for m in members]


def weekly_history(db: Session, s: ClubSession) -> dict[tuple[int, int], float]:
    since = s.date - timedelta(days=7 * REPEAT_LOOKBACK_WEEKS)
    past = db.scalars(select(ClubSession).where(ClubSession.date < s.date, ClubSession.date >= since)
                      .options(selectinload(ClubSession.games).selectinload(Game.roster))).all()
    weeks: list[list[dict[int, str]]] = [[] for _ in range(REPEAT_LOOKBACK_WEEKS)]
    for ps in past:
        idx = max(0, min(REPEAT_LOOKBACK_WEEKS - 1, round((s.date - ps.date).days / 7) - 1))
        for g in ps.games:
            weeks[idx].append({r.member_id: r.side for r in g.roster})
    return balancer.weekly_pair_weights(weeks)


def get_game(db: Session, s: ClubSession, game_no: int) -> Game | None:
    return db.scalar(select(Game).where(Game.session_id == s.id, Game.game_no == game_no))


def _write_roster(db: Session, game: Game, team_a: list[int], team_b: list[int]) -> None:
    game.roster.clear()
    db.flush()
    for mid in team_a:
        game.roster.append(GameRoster(member_id=mid, side="A"))
    for mid in team_b:
        game.roster.append(GameRoster(member_id=mid, side="B"))


def _sides(game: Game) -> dict[int, str]:
    return {r.member_id: r.side for r in game.roster}


def _ensure_editable(game: Game) -> None:
    if game.status == "finished":
        raise OpError("이미 결과가 입력된 게임은 명단을 바꿀 수 없습니다.")


def generate_game1(db: Session, admin: Member, s: ClubSession) -> Game:
    members = checked_in_members(db, s)
    errors, _ = team_readiness(members)
    if errors:
        raise OpError(" / ".join(errors))
    g1 = get_game(db, s, 1)
    if g1:
        _ensure_editable(g1)
    try:
        cands = balancer.balance(_players(members), weights=current_weights(db),
                                 weekly_pairs=weekly_history(db, s), top_k=TOP_K_CANDIDATES)
    except balancer.BalanceError as e:
        raise OpError(str(e)) from e
    if g1 is None:
        g1 = Game(session_id=s.id, game_no=1, lineup_mode="balanced", status="lineup_ready")
        db.add(g1)
        db.flush()
    g1.candidates = [[c.team_a, c.team_b] for c in cands]
    g1.candidate_idx = 0
    _write_roster(db, g1, cands[0].team_a, cands[0].team_b)
    if s.status == "open":
        s.status = "closed"
    log(db, admin, "lineup.generate", f"game:{g1.id}", {"game_no": 1, "n": len(members)})
    db.commit()
    return g1


def next_candidate(db: Session, admin: Member, game: Game) -> Game:
    _ensure_editable(game)
    if not game.candidates:
        raise OpError("후보안이 없습니다. 팀을 다시 생성하세요.")
    game.candidate_idx = (game.candidate_idx + 1) % len(game.candidates)
    a, b = game.candidates[game.candidate_idx]
    _write_roster(db, game, a, b)
    log(db, admin, "lineup.next", f"game:{game.id}", {"idx": game.candidate_idx})
    db.commit()
    return game


def move_member(db: Session, admin: Member, game: Game, member_id: int) -> Game:
    _ensure_editable(game)
    row = next((r for r in game.roster if r.member_id == member_id), None)
    if row is None:
        raise OpError("이 게임 명단에 없는 멤버입니다.")
    before = row.side
    row.side = "B" if before == "A" else "A"
    log(db, admin, "lineup.move", f"game:{game.id}", {"member_id": member_id, "from": before, "to": row.side})
    db.commit()
    return game


def add_to_lineup(db: Session, admin: Member, game: Game, member_id: int) -> Game:
    """늦게 온 사람을 인원이 적은 팀에 추가."""
    _ensure_editable(game)
    if any(r.member_id == member_id for r in game.roster):
        return game
    na = sum(1 for r in game.roster if r.side == "A")
    nb = len(game.roster) - na
    game.roster.append(GameRoster(member_id=member_id, side="A" if na <= nb else "B"))
    log(db, admin, "lineup.add", f"game:{game.id}", {"member_id": member_id})
    db.commit()
    return game


def remove_from_lineup(db: Session, admin: Member, game: Game, member_id: int) -> Game:
    _ensure_editable(game)
    row = next((r for r in game.roster if r.member_id == member_id), None)
    if row:
        game.roster.remove(row)
        log(db, admin, "lineup.remove", f"game:{game.id}", {"member_id": member_id})
        db.commit()
    return game


def evaluate_game(db: Session, game: Game) -> balancer.Candidate | None:
    team_a = [r.member for r in game.roster if r.side == "A"]
    team_b = [r.member for r in game.roster if r.side == "B"]
    if not team_a or not team_b:
        return None
    game1_sides = None
    if game.game_no == 2 and game.lineup_mode == "reshuffled":
        g1 = get_game(db, game.session, 1)
        game1_sides = _sides(g1) if g1 else None
    return balancer.evaluate(_players(team_a), _players(team_b), weights=current_weights(db),
                             weekly_pairs=weekly_history(db, game.session), game1_sides=game1_sides)


def create_game2(db: Session, admin: Member, s: ClubSession, mode: str) -> Game:
    if mode not in ("kept", "reshuffled"):
        raise OpError("mode는 kept 또는 reshuffled")
    g1 = get_game(db, s, 1)
    if g1 is None or g1.status != "finished":
        raise OpError("게임 1 결과를 먼저 입력하세요.")
    g2 = get_game(db, s, 2)
    if g2:
        _ensure_editable(g2)
    members = checked_in_members(db, s)
    g1_sides = _sides(g1)

    if mode == "kept":
        present = {m.id for m in members}
        team_a = [mid for mid, side in g1_sides.items() if side == "A" and mid in present]
        team_b = [mid for mid, side in g1_sides.items() if side == "B" and mid in present]
        # 게임 1 이후 도착한 사람은 인원이 적은 팀(같으면 평균 전력이 낮은 팀)에 배정
        mu = {m.id: m.mu for m in members}
        for m in members:
            if m.id in g1_sides:
                continue
            avg_a = sum(mu[i] for i in team_a) / len(team_a) if team_a else 0
            avg_b = sum(mu[i] for i in team_b) / len(team_b) if team_b else 0
            if len(team_a) < len(team_b) or (len(team_a) == len(team_b) and avg_a <= avg_b):
                team_a.append(m.id)
            else:
                team_b.append(m.id)
        cands_store = None
    else:
        errors, _ = team_readiness(members)
        if errors:
            raise OpError(" / ".join(errors))
        try:
            cands = balancer.balance(_players(members), weights=current_weights(db),
                                     weekly_pairs=weekly_history(db, s), game1_sides=g1_sides,
                                     top_k=TOP_K_CANDIDATES)
        except balancer.BalanceError as e:
            raise OpError(str(e)) from e
        team_a, team_b = cands[0].team_a, cands[0].team_b
        cands_store = [[c.team_a, c.team_b] for c in cands]

    if g2 is None:
        g2 = Game(session_id=s.id, game_no=2, lineup_mode=mode, status="lineup_ready")
        db.add(g2)
        db.flush()
    g2.lineup_mode = mode
    g2.candidates = cands_store
    g2.candidate_idx = 0
    _write_roster(db, g2, team_a, team_b)
    log(db, admin, "lineup.game2", f"game:{g2.id}",
        {"mode": mode, "lopsided_recommended": bool(g1.lopsided)})
    db.commit()
    return g2


# ---------------------------------------------------------------- 결과

def submit_result(db: Session, admin: Member, game: Game, score_a: int, score_b: int):
    """결과 입력(최초) 또는 수정. 게임 1이면 일방성 판정 결과를 반환."""
    if score_a < 0 or score_b < 0 or score_a > 300 or score_b > 300:
        raise OpError("점수가 올바르지 않습니다.")
    if not any(r.side == "A" for r in game.roster) or not any(r.side == "B" for r in game.roster):
        raise OpError("두 팀 명단이 모두 있어야 합니다.")
    was_finished = game.status == "finished"
    before = {"score_a": game.score_a, "score_b": game.score_b}
    game.score_a, game.score_b = score_a, score_b
    game.winner = rating.winner_of(score_a, score_b)
    game.status = "finished"
    game.played_at = game.played_at or now_kst()
    judged = None
    if game.game_no == 1:
        judged = lopsided.judge(score_a, score_b)
        game.lopsided = judged.lopsided
    db.flush()

    later_rated = any(g.rated and g.game_no > game.game_no for g in game.session.games)
    if was_finished or later_rated or _has_later_rated(db, game):
        rating.recalculate_from(db, game)
    else:
        rating.rate_game(db, game)
    log(db, admin, "game.result.update" if was_finished else "game.result.create", f"game:{game.id}",
        {"before": before, "after": {"score_a": score_a, "score_b": score_b}})
    db.commit()
    return judged


def _has_later_rated(db: Session, game: Game) -> bool:
    return db.scalar(select(func.count()).select_from(Game).join(ClubSession).where(
        Game.rated.is_(True), ClubSession.date > game.session.date)) > 0
