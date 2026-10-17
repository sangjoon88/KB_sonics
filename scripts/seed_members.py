"""개발용 시드 스크립트 (Neon dev 브랜치 / 로컬 SQLite).

사용법:
  python scripts/seed_members.py members.csv           # CSV: 이름,포지션,키,등급  (헤더 없음, 포지션/키/등급 생략 가능)
  python scripts/seed_members.py --demo                # 데모 데이터: 운영진(PIN 1234) + 멤버 14명 + 다음 일요일 모임
  python scripts/seed_members.py --create-tables       # 마이그레이션 없이 테이블 생성 (로컬 SQLite 빠른 시작용)

운영(main) DB에는 실행하지 말 것. 운영은 /setup → /admin/members/import 화면을 사용한다.
"""
import argparse
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.auth import hash_pin  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Attendance, ClubSession, Member  # noqa: E402
from app.services.ops import normalize_position  # noqa: E402
from app.services.rating import grade_to_rating  # noqa: E402
from app.config import DEFAULT_LOCATION, SESSION_START_TIME  # noqa: E402
from app.timeutil import next_session_date, now_kst  # noqa: E402

DEMO = [
    ("김민수", "G", 176, 4), ("이준호", "C", 189, 4), ("박성훈", "F", 183, 3), ("최영재", "G", 172, 3),
    ("정우진", "F", 180, 5), ("강태현", "C", 191, 3), ("조현우", "G", 170, 2), ("윤재석", "F", 178, 3),
    ("장동건", "G", 174, 2), ("임재원", "F", 185, 4), ("한승우", "C", 186, 2), ("오세훈", "G", 168, 1),
    ("서지훈", "F", 181, 3), ("신동욱", "G", 177, 3),
]


def upsert(db, name, position=None, height=None, grade=None) -> Member:
    m = db.scalar(select(Member).where(Member.name == name))
    if m is None:
        m = Member(name=name, mu=25.0)
        db.add(m)
    m.position = normalize_position(position) or m.position
    m.height_cm = height or m.height_cm
    if grade is not None:
        m.initial_grade = float(grade)
        m.mu, m.sigma = grade_to_rating(m.initial_grade)
    return m


def seed_csv(path: str) -> None:
    with SessionLocal() as db, open(path, encoding="utf-8-sig", newline="") as f:
        n = 0
        for row in csv.reader(f):
            if not row or not row[0].strip():
                continue
            row += [""] * (4 - len(row))
            name, pos, h, g = (c.strip() for c in row[:4])
            upsert(db, name, pos or None, int(h) if h else None, float(g) if g else None)
            db.flush()
            n += 1
        db.commit()
    print(f"{n}명 반영")


def seed_demo() -> None:
    with SessionLocal() as db:
        for name, pos, h, g in DEMO:
            upsert(db, name, pos, h, g)
        db.flush()
        admin = db.scalar(select(Member).where(Member.name == DEMO[0][0]))
        default_hash = hash_pin("1234")
        for m in db.scalars(select(Member).where(Member.pin_hash.is_(None))).all():
            m.pin_hash = default_hash      # 일반 멤버: 초기 PIN 1234, 첫 로그인 때 변경
            m.pin_must_change = True
        admin.is_admin = True
        admin.is_owner = True
        admin.pin_must_change = False
        db.flush()
        d = next_session_date()
        s = db.scalar(select(ClubSession).where(ClubSession.date == d))
        if s is None:
            s = ClubSession(date=d, location=DEFAULT_LOCATION, start_time=SESSION_START_TIME, status="open")
            db.add(s)
            db.flush()
            members = db.scalars(select(Member)).all()
            rnd = random.Random(7)
            for m in members:
                v = rnd.choices(["yes", "early", "no"], weights=[7, 2, 1])[0]
                leave = rnd.choice(["11:00", "11:30"]) if v == "early" else None
                db.add(Attendance(session_id=s.id, member_id=m.id, vote=v, leave_time=leave,
                                  checked_in=False, voted_at=now_kst()))
        db.commit()
    print(f"데모 데이터 준비 완료 — 관리자: {DEMO[0][0]} / PIN 1234, 다른 멤버는 초기 PIN 1234 (첫 로그인 때 변경)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--create-tables", action="store_true")
    args = ap.parse_args()
    print(f"DB: {settings.DATABASE_URL.split('@')[-1]}")
    if args.create_tables:
        Base.metadata.create_all(engine)
        print("테이블 생성 완료")
    if args.csv:
        seed_csv(args.csv)
    if args.demo:
        seed_demo()
    if not (args.csv or args.demo or args.create_tables):
        ap.print_help()


if __name__ == "__main__":
    main()
