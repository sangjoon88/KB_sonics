# KB SONICS — 농구 동아리 서비스 (MVP v2)

참석 투표 → 자동 팀 나누기 → 경기 결과 입력 → 레이팅 갱신을 하나의 모바일 웹으로 제공한다.
명세: [basketball-club-app-spec.md](basketball-club-app-spec.md)

- FastAPI + Jinja2 + HTMX + Tailwind(CDN) — Vercel 프로젝트 1개
- Neon PostgreSQL (pooled URL) / 로컬은 SQLite로도 동작
- openskill PlackettLuce 레이팅, 전수 탐색 팀 밸런싱

## 로컬 실행

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt      # macOS/Linux: .venv/bin/pip
cp .env.example .env                                    # DATABASE_URL 비우면 sqlite:///./local.db

alembic upgrade head                                    # Windows는 PYTHONUTF8=1 권장
python scripts/seed_members.py --demo                   # 데모: 운영진 김민수 / PIN 1234
uvicorn app.main:app --reload
```

- 데모 없이 처음부터: `.env`에 `SETUP_TOKEN` 설정 → `http://localhost:8000/setup?token=...`
- 테스트: `pytest`

## 배포 (Vercel + Neon)

1. Neon 프로젝트 생성, `main`(운영) / `dev`(개발) 브랜치. **`-pooler` 호스트 연결 문자열** 사용
2. 로컬에서 운영 DB로 마이그레이션: `DATABASE_URL=<main pooled url> alembic upgrade head`
3. Vercel 프로젝트 생성 후 환경변수: `DATABASE_URL`, `SECRET_KEY`(`openssl rand -hex 32`), `SETUP_TOKEN`, `SEASON`
4. 배포 → `https://<도메인>/setup?token=<SETUP_TOKEN>` 에서 첫 운영진 생성 (이후 `/setup`은 404)
5. `/admin/members/import` 멤버 붙여넣기 → 운영진 지정 → `/admin/rating-setup` 초기 등급 → 첫 모임 생성

## 운영 배포 현황

- 사이트: https://kb-sonics.vercel.app (Vercel 프로젝트 `kb-sonics`, 리전 `sin1` = Neon `ap-southeast-1` 과 같은 싱가포르)
- GitHub `main` 에 push 하면 Vercel 이 자동 배포
- DB 스키마 변경 시: 로컬에서 `DATABASE_URL=<운영 pooled url> alembic upgrade head` 먼저 실행 후 push
- PostgreSQL 에서 테스트: `TEST_DATABASE_URL=<테스트 전용 DB url> pytest` (테스트마다 테이블을 지우므로 운영 DB 금지)

## 구조

```text
api/index.py            Vercel 진입점
app/config.py           환경변수 + 가중치/기준값 (명세 13장)
app/db.py               NullPool 엔진 (서버리스)
app/models.py           데이터 모델 (명세 6장)
app/auth.py             멤버 쿠키 / 운영진 개인 PIN (bcrypt, 5회 실패 10분 잠금)
app/routers/pages.py    멤버 화면: 홈, 투표, 오늘 경기, 기록, 내 기록, /setup
app/routers/admin.py    운영진 화면: 모임, 출석, 팀 짜기, 점수, 게임2 선택, 멤버, 초기 등급, 레이팅, 설정, 작업 기록
app/routers/api.py      JSON API (명세 11장, /api/docs)
app/services/balancer.py  전수 탐색 밸런싱 (순수 함수)
app/services/lopsided.py  게임1 일방성 판정
app/services/rating.py    openskill 래퍼 + recalculate_from
app/services/stats.py     출석/승률/연승 집계
app/services/ops.py       화면·API 공용 업무 로직
```

## 명세 대비 구현 메모

- **반복 조합 페널티 정규화**: 같은 팀 쌍 개수로 나눠 0~1 범위로 만든 뒤 가중치(0.8 / 3.0)를 곱한다.
  정규화하지 않으면 12명 기준 쌍이 30개라 페널티가 전력 차를 압도한다.
- **최소 맞교환**: 게임1 A팀→B팀, B팀→A팀으로 넘어간 인원 중 작은 값 ≥ 2.
- **키 미입력자**: 팀 짜기는 막지 않고 참가자 키 중앙값으로 계산 + 경고 표시.
- **팀 짜기 차단**: 출석자 중 초기 등급 미확정자가 있으면 거부.
- **게임 2 팀 유지 시 늦게 온 사람**: 인원이 적은(같으면 평균 전력이 낮은) 팀에 배정.
- **Game 테이블 추가 컬럼**: `candidates`(다시 섞기 후보 5개), `candidate_idx`, `lopsided`(판정 결과 — 실제 선택은 game2의 `lineup_mode`).
- **Member 추가 컬럼**: `pin_must_change` (임시 PIN 첫 로그인 시 변경 강제), `is_owner` (관리자).
- **관리자 / 운영진 2단계**: `/setup`으로 만든 계정이 관리자. 운영진 지정·해제와 PIN 재설정은 관리자만 가능. 그 외 운영 기능은 운영진과 동일.
- **로그인 (모든 멤버 PIN)**: 이름 선택 후 본인 PIN 확인. 운영진이 등록한 멤버는 초기 PIN `1234`(`DEFAULT_PIN`)로 시작하고, 첫 로그인 때 PIN 변경(1234 재사용 불가) → 내 정보(주/부 포지션·키·몸무게) 확인을 거쳐야 다른 화면 사용 가능. 운영진은 일반 멤버 PIN을 1234로 초기화 가능(운영진 PIN 초기화는 관리자만). 운영진·관리자는 같은 PIN으로 운영진 로그인까지 한 번에 처리. `Member.admin_pin_hash` → `pin_hash` 로 변경.
- **포지션 2개 · 몸무게**: `position`(주, 밸런싱 기준) / `position2`(부, 선택) / `weight_kg`(선택, 본인·운영진만 열람, 공개 API 미포함). 일괄 등록은 `G/F` 형식 지원.
- **AppSetting 테이블**: 밸런스 모드(실력 우선 / 균형 / 키 우선).
- **투표 API**: 로그인이 없으므로 쿠키의 본인 `member_id`와 같을 때만 허용.
- 레이팅(mu/sigma)은 `/admin/ratings`, 팀 짜기 화면의 "왜 이렇게 나눴나"(운영진 전용)에서만 노출.
- **투표 선택지**: 참석 / 불참 / 조퇴 (명세의 미정 대신). 조퇴는 시간(`Attendance.leave_time`, "HH:MM") 필수이며 참석 인원에 포함. 출석 체크·팀 짜기·오늘 경기 화면에 ⏰시간 표시.
- **게스트**: 투표 화면의 "게스트 데려오기"(투표 마감 전) 또는 운영진 출석 체크 화면에서 추가. `Member.is_guest=True, is_active=False` 로 저장되어 이름 선택·멤버 관리·기록에서 제외되고, 실력(1~5, 기본 3)으로 밸런싱에 참여. 같은 이름으로 다시 오면 기록을 이어 쓰고, 운영진이 같은 이름으로 멤버를 추가하면 정식 멤버로 전환.
- **예상 팀**: 투표 화면·홈에서 참석+조퇴+게스트 기준으로 밸런싱한 예상 팀을 표시 (투표 시 즉시, 그 외 20~30초 주기 갱신). 게임 1 팀이 생기면 확정 팀 안내로 바뀜.
- **대리 투표**: 운영진은 투표 화면에서 다른 멤버의 참석/조퇴/불참을 입력 가능 (마감 후 포함, `Attendance.proxy_by`). 본인이 직접 투표하면 대리 표시 해제. API `PUT /api/sessions/{id}/vote` 도 운영진이면 대리 처리.
