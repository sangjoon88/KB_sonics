# 농구 동아리 서비스 – 개발 명세서 (MVP v2)

> 회사 농구 동아리의 **참석 투표 → 자동 팀 나누기 → 경기 결과 입력 → 레이팅 갱신** 흐름을 하나의 모바일 웹으로 제공한다.
> 경기 결과가 쌓일수록 팀 밸런싱이 정확해지는 구조가 핵심.

---

## 0. 운영 방식 (확정)

| 항목 | 내용 |
|---|---|
| 모임 | 매주 **일요일** |
| 참석 인원 | 평균 **12명** (변동 있음: 10~14명 대응) |
| 팀 구성 | **2팀 × 6명** (5대5 + 교체 1명) |
| 경기 수 | 하루 **2게임** |
| 게임 2 팀 | 게임 1이 일방적이면 **팀 재편성**, 아니면 **게임 1 팀 그대로** |
| 인프라 | **Vercel**(FastAPI 배포) + **Neon**(PostgreSQL) |
| 로그인 | 없음. 이름 선택 방식 + 운영진 PIN |

---

## 1. 목표와 범위

### 1.1 해결하려는 문제
- 매주 카톡방에서 참석 투표를 받고 인원을 세는 번거로움
- 현장에서 팀을 나누느라 시간을 쓰고, 그래도 한쪽으로 쏠리는 문제
- 게임 1이 일방적일 때 "누구를 바꿔야 하나" 즉석에서 고민하는 문제
- 경기 기록이 남지 않아 시즌 단위의 재미(기록, 랭킹)가 없음

### 1.2 MVP 범위 (In)
1. 멤버 관리 (이름, 포지션, 초기 등급)
2. 일요일 모임 생성 + 참석 투표 (링크 공유)
3. 게임 1 자동 팀 밸런싱
4. 게임 1 결과 입력 → 레이팅 갱신 → **게임 2 팀 유지 / 재편성 선택**
5. 게임 2 결과 입력 → 레이팅 갱신
6. 공개 기록 페이지 (출석, 승률, 연승 등)

### 1.3 MVP 제외 (Out, 추후 확장)
- 회비/대관비 정산
- 경기 영상 하이라이트
- 카카오 로그인, 카카오톡 알림
- 시즌 리포트 LLM 생성

---

## 2. 기술 스택과 인프라

| 영역 | 선택 | 비고 |
|---|---|---|
| Backend | Python 3.12, FastAPI | Vercel Python 런타임으로 배포 |
| Frontend | Jinja2 템플릿 + HTMX + Tailwind(CDN) | FastAPI가 HTML까지 렌더링 → **Vercel 프로젝트 1개로 끝** |
| DB | **Neon PostgreSQL** | 반드시 **pooled 연결 문자열**(`-pooler` 호스트) 사용 |
| ORM / 마이그레이션 | SQLAlchemy 2.0 + Alembic | 마이그레이션은 로컬에서 Neon으로 실행 |
| DB 드라이버 | `psycopg[binary]` (v3) | |
| 레이팅 | `openskill` (PlackettLuce 모델) | 팀 게임용 |
| 테스트 | pytest | 밸런싱·레이팅 로직은 반드시 단위 테스트 |

### 2.1 서버리스 환경 주의사항 (Vercel)
- 요청마다 함수가 뜨고 내려가므로 **로컬 파일 저장 불가** → 모든 상태는 Neon에 저장
- SQLAlchemy 엔진은 `poolclass=NullPool`로 생성 (커넥션 풀은 Neon pooler가 담당)
  ```python
  from sqlalchemy import create_engine
  from sqlalchemy.pool import NullPool
  engine = create_engine(settings.DATABASE_URL, poolclass=NullPool, pool_pre_ping=True)
  ```
- 백그라운드 작업(BackgroundTasks, 스레드) 의존 금지. 계산은 요청 안에서 끝낸다 (12명 기준 모두 수십 ms 이내)
- 정적 파일(CSS, 아이콘)은 `public/` 또는 CDN 사용

### 2.2 Neon 브랜치 활용
- `main` 브랜치 = 운영 DB
- `dev` 브랜치 = 로컬 개발/테스트용 (운영 데이터 복사본으로 안전하게 실험)
- 환경변수: 로컬 `.env`는 dev 브랜치, Vercel Production은 main 브랜치 URL

### 2.3 환경변수
```text
DATABASE_URL=postgresql+psycopg://...-pooler.../neondb?sslmode=require
SECRET_KEY=랜덤 문자열 (쿠키 서명용, openssl rand -hex 32)
SETUP_TOKEN=랜덤 문자열 (첫 운영진 생성용, 운영진 생성 후에는 사용 안 됨)
SEASON=2026
# 운영진 PIN은 환경변수가 아니라 DB(Member.admin_pin_hash)에 해시로 저장
```

### 2.4 접속 환경
- 개인 휴대폰 사용을 기준으로 한다. (사내망/회사 PC에서는 외부 사이트 접속이 제한될 수 있음)
- 개발과 배포도 개인 장비/개인 계정에서 진행한다.

---

## 3. 사용자와 권한

| 역할 | 할 수 있는 것 |
|---|---|
| 멤버 | 참석 투표, 팀 결과 보기, 공개 기록 보기 |
| 운영진(admin) | 멤버 관리, 모임 생성/마감, 현장 출석 체크, 팀 생성/재편성, 경기 결과 입력/수정, 레이팅(비공개) 열람 |

- **멤버**: 로그인 없이 목록에서 본인 이름 선택 → 쿠키에 `member_id` 저장 (다음부터 자동)
- **운영진**: 별도 아이디 없이 **멤버 레코드 + 개인 PIN**으로 식별

### 3.1 운영진 식별 방식
아이디/비밀번호 회원가입 없이, 멤버 중 일부에게 운영진 권한을 주고 **각자 4~6자리 PIN**을 부여한다.

```text
1. 이름 선택 (일반 멤버와 동일)
2. 선택한 멤버가 is_admin = true 이면 → 운영진 메뉴 진입 시 PIN 입력창
3. PIN 일치 → 서명된 쿠키(itsdangerous)에 {member_id, role: admin} 저장
4. 쿠키 유효기간 90일 → 같은 폰에서는 다시 입력할 필요 없음
```

- PIN은 평문 저장 금지 → `bcrypt` 해시로 `Member.admin_pin_hash`에 저장
- 공용 PIN 하나를 돌려쓰지 않고 **개인 PIN**을 쓰는 이유
  - 누가 점수를 입력/수정했는지 기록 가능 (`AdminLog`)
  - 운영진이 바뀌면 그 사람 권한만 끄면 됨 (PIN 전체 교체 불필요)
- PIN 5회 연속 실패 시 해당 멤버 운영진 로그인 10분 잠금 (실패 횟수는 DB에 저장 — 서버리스라 메모리 사용 불가)
- 최초 운영진 지정: 배포 직후 `/setup` 화면에서 생성 (5.1 참고)
- 이후 운영진 추가/해제와 PIN 재설정은 기존 운영진이 관리자 화면에서 처리

### 3.2 일반 멤버 화면 가림
- 일반 멤버 화면에는 운영진 메뉴 자체를 노출하지 않는다.
- 운영진 API는 모두 쿠키의 `role: admin` 검증 의존성(`require_admin`)을 거친다.
- 개인정보는 이름(닉네임), 포지션, 키 정도만 저장. 사번·연락처 등은 저장하지 않는다.
- (선택, 추후) 사칭이 문제되면 **멤버별 개인 링크** `/m/{token}` 도입. 비밀번호 없이 본인 식별.

---

## 4. 핵심 원칙: 레이팅 비공개

사내 동아리 특성상 개인 실력 점수가 공개되면 하위권 멤버가 위축되어 참석이 줄 수 있다.

- **레이팅(mu, sigma)은 운영진 화면과 팀 밸런싱 내부 계산에만 사용**한다.
- 공개 페이지에는 긍정 지표만 노출: 출석 횟수, 출석률, 경기 수, 승률, 최장 연승.
- 팀 결과 화면에 팀 전력 합계 숫자를 노출하지 않는다. (대신 "밸런스 양호/보통" 표시)

---

## 5. 하루 흐름 (일요일 기준)

```text
[월~토] 운영진이 일요일 모임 생성 → 투표 링크 카톡 공유 → 멤버 투표
   │
[일요일 현장]
   ├─ 1. 운영진: 현장 출석 체크 (투표 안 하고 온 사람/빠진 사람 반영)
   ├─ 2. "게임 1 팀 짜기" → 2팀 × 6명 자동 생성 (필요 시 다시 섞기/수동 이동)
   ├─ 3. 게임 1 종료 → 점수 입력 → 레이팅 즉시 갱신
   ├─ 4. 앱이 일방성 판정 → "팀 유지" / "팀 재편성" 선택 화면
   │      · 일방적이면 "재편성 권장" 배지 표시 (최종 결정은 운영진)
   │      · 재편성 시 게임 1 결과가 반영된 레이팅으로 다시 밸런싱
   ├─ 5. 게임 2 종료 → 점수 입력 → 레이팅 갱신
   └─ 6. 모임 종료 처리 (status = finished)
```

### 5.1 최초 세팅 흐름 (서비스 시작 시 1회)

터미널 없이 **폰/웹 화면에서 끝나도록** 한다.

```text
STEP 1. 첫 운영진 생성  (/setup)
  · Vercel 환경변수 SETUP_TOKEN 설정 후 배포
  · /setup?token=SETUP_TOKEN 접속 → 내 이름·포지션·키·PIN 입력 → 첫 운영진 생성
  · DB에 운영진이 1명이라도 생기면 /setup은 자동으로 닫힘 (404)

STEP 2. 멤버 일괄 등록  (/admin/members/import)
  · 카톡방 멤버 이름을 엑셀/메모장에서 복사 → 텍스트 박스에 붙여넣기
      김OO,G,175
      이OO,C,188
      박OO          ← 이름만 있어도 등록 가능 (포지션·키는 나중에)
  · 미리보기 표 확인 → [등록]
  · 중복 이름은 경고 (동명이인은 "김OO(마케팅)"처럼 구분)

STEP 3. 운영진 추가 지정  (/admin/members)
  · 멤버 목록에서 운영진 토글 ON → 임시 PIN 발급 → 카톡으로 전달
  · 해당 운영진은 첫 로그인 시 PIN 변경

STEP 4. 키·포지션 채우기
  · 멤버가 투표 링크로 처음 들어와 이름을 고르면, 키·포지션이 비어 있을 때만 입력창 표시
  · 본인이 입력 → 운영진이 관리자 화면에서 수정 가능
  · 첫 팀 짜기 전까지 키가 빈 멤버가 있으면 운영진 화면에 "키 미입력 n명" 경고

STEP 5. 초기 등급 평가  (/admin/rating-setup)
  · 운영진 각자 자기 폰에서 전체 멤버에게 1~5등급 입력 (다른 운영진 평가는 안 보임)
  · 운영진 전원 제출 → 평균 등급 계산, 평가 차이 2등급 이상 멤버 강조 표시
  · 운영진이 조정 후 [확정] → 각 멤버 mu/sigma 초기화
  · 확정 전에는 첫 팀 짜기 버튼 비활성화

STEP 6. 첫 모임 생성 → 투표 링크 카톡 공유 → 운영 시작
```

신규 멤버가 중간에 들어오면 STEP 2(1명 추가) → STEP 4 → STEP 5(신규 멤버만 평가)를 반복한다.

> 개발/테스트 단계에서는 `scripts/seed_members.py`로 CSV를 한 번에 넣는 방법도 유지한다 (Neon dev 브랜치용).

---

## 6. 데이터 모델

> 하루 2게임이고 게임 2에서 팀이 바뀔 수 있으므로 **팀 명단은 게임 단위로 저장**한다.

```text
Member
- id: int (PK)
- name: str (unique)
- position: enum(G, F, C) | null   # 가드/포워드/센터 (등록 후 본인 입력 가능)
- height_cm: int | null           # 팀 짜기 전까지 필수 (키 매치업 밸런싱)
- initial_grade: float | null     # 운영진 평가 평균, 확정 전 null (9.2 참고)
- mu: float                     # 현재 레이팅 평균
- sigma: float                  # 현재 레이팅 불확실성
- is_active: bool
- is_admin: bool                # 운영진 여부
- admin_pin_hash: str | null    # bcrypt 해시 (운영진만)
- pin_fail_count: int           # 연속 실패 횟수
- pin_locked_until: datetime | null
- created_at: datetime

AdminLog   (운영진 작업 기록)
- id: int (PK)
- admin_id: FK -> Member
- action: str                   # 예: "game.result.update", "lineup.move", "member.update"
- target: str                   # 예: "game:12"
- detail: json                  # 변경 전/후 값
- created_at: datetime

InitialRating   (초기 등급 평가, 운영진별)
- rater_id: FK -> Member        # 평가한 운영진
- member_id: FK -> Member       # 평가 대상
- grade: int (1~5)
- created_at: datetime
- PK(rater_id, member_id)

Session  (일요일 모임 1회)
- id: int (PK)
- date: date                    # 일요일
- location: str | null
- vote_deadline: datetime | null   # 기본: 토요일 22:00
- status: enum(open, closed, finished)
- created_at: datetime

Attendance
- id: int (PK)
- session_id: FK -> Session
- member_id: FK -> Member
- vote: enum(yes, no, maybe)
- checked_in: bool              # 현장 실제 출석 (팀 짜기는 이 값 기준)
- voted_at: datetime
- UNIQUE(session_id, member_id)

Game
- id: int (PK)
- session_id: FK -> Session
- game_no: int (1 | 2)
- lineup_mode: enum(balanced, kept, reshuffled)
     # 게임1 = balanced, 게임2 = kept(유지) 또는 reshuffled(재편성)
- score_a: int | null
- score_b: int | null
- winner: enum(A, B, draw) | null
- status: enum(lineup_ready, finished)
- rated: bool
- played_at: datetime | null
- UNIQUE(session_id, game_no)

GameRoster   (게임별 팀 명단)
- game_id: FK -> Game
- member_id: FK -> Member
- side: enum(A, B)
- PK(game_id, member_id)

RatingHistory
- id: int (PK)
- member_id: FK -> Member
- game_id: FK -> Game
- mu_before, sigma_before: float
- mu_after, sigma_after: float
- created_at: datetime
```

---

## 7. 팀 밸런싱 알고리즘

### 7.1 전수 탐색
2팀이므로 경우의 수가 작다. **랜덤 탐색 없이 모든 조합을 계산**해 최적을 고른다.

| 인원 | 조합 수 (대칭 제거) |
|---|---|
| 10명 (5:5) | 126 |
| 12명 (6:6) | 462 |
| 13명 (7:6) | 1,716 |
| 14명 (7:7) | 1,716 |
| 16명 (8:8) | 6,435 |

- 대칭 제거: 첫 번째 멤버를 항상 A팀에 고정하고 `itertools.combinations`로 나머지를 뽑는다.
- 홀수 인원이면 한 팀이 1명 많다 (전력 비교는 **평균** 기준).
- 18명 이상이 오면 그때 hill climbing으로 전환 (MVP에서는 경고만 표시).

### 7.2 비용 함수 (낮을수록 좋음)

```text
cost = w_strength * strength_gap
     + w_position * position_gap
     + w_height   * height_matchup_gap
     + w_repeat   * repeat_penalty

(하드 제약) 키 상위 2명은 반드시 다른 팀 → 위반 조합은 후보에서 제외

strength(team)      = 팀원 mu 평균
strength_gap        = |strength(A) - strength(B)|
position_gap        = Σ_pos |count_pos(A) - count_pos(B)|     # G/F/C 각각
height_matchup_gap  = 아래 7.2.1 참고
repeat_penalty      = 아래 7.3 참고
```

#### 7.2.1 키 매치업 밸런싱
평균 키만 맞추면 "190 + 165" 팀과 "178 + 178" 팀이 같게 계산되어, 실제로는 큰 선수를 막을 사람이 없는 문제가 생긴다.
그래서 **키 순서대로 1:1 매치업을 만들어 그 차이를 줄인다.**

```text
A팀 키를 내림차순 정렬: a1 ≥ a2 ≥ ... ≥ a6
B팀 키를 내림차순 정렬: b1 ≥ b2 ≥ ... ≥ b6

height_matchup_gap = Σ_i  r_i × |a_i - b_i|  /  HEIGHT_SCALE

r_i      = 순위 가중치. 골밑 매치업이 중요하므로 위쪽 순위에 더 큰 가중치
           예) [1.5, 1.3, 1.0, 0.8, 0.7, 0.7]
HEIGHT_SCALE = 5   # 5cm 차이 ≈ mu 1점 차이 정도로 취급 (cm와 레이팅 단위 맞추기)
```

- 홀수 인원(7:6)이면 많은 팀의 가장 작은 1명을 빼고 6쌍만 비교
- 키 상위 2명 분리는 하드 제약으로 처리 (이 조건만으로 체감 불만이 대부분 해소됨)
- 운영진 설정에 **밸런스 모드** 제공
  - `실력 우선`: w_height = 0.5
  - `균형` (기본): w_height = 1.0
  - `키 우선`: w_height = 2.0

```python
def height_matchup_gap(heights_a, heights_b, weights=RANK_WEIGHTS, scale=HEIGHT_SCALE):
    a = sorted(heights_a, reverse=True)
    b = sorted(heights_b, reverse=True)
    n = min(len(a), len(b))
    return sum(w * abs(x - y) for w, x, y in zip(weights, a[:n], b[:n])) / scale
```

### 7.3 반복 조합 페널티
"매번 같은 사람끼리 한 팀" 방지.

- **지난 주들**: 최근 3주간 같은 팀이었던 멤버 쌍이 이번에도 같은 팀이면 쌍마다 가산 (최근일수록 가중: 1주 전 1.0, 2주 전 0.6, 3주 전 0.3)
- **게임 2 재편성 시**: 게임 1과 같은 팀 쌍에 강한 페널티를 주어 실제로 팀이 바뀌도록 한다. 추가로 **최소 2명 이상 맞교환**을 제약 조건으로 둔다 (재편성했는데 거의 그대로인 상황 방지).

### 7.4 가중치 초기값
```python
WEIGHTS = {
    "strength": 1.0,
    "position": 2.0,
    "height": 1.0,         # 밸런스 모드로 0.5 / 1.0 / 2.0 전환
    "repeat_weekly": 0.8,
    "repeat_game1": 3.0,   # 게임 2 재편성 때만 적용
}
RANK_WEIGHTS = [1.5, 1.3, 1.0, 0.8, 0.7, 0.7]
HEIGHT_SCALE = 5
SPLIT_TALLEST_N = 2        # 키 상위 N명은 반드시 다른 팀
MIN_SWAPS_ON_RESHUFFLE = 2
```

> 초기 1~2주는 실제 결과를 보고 가중치를 조정한다. 팀 결과 화면(운영진용)에 항목별 cost를 같이 보여주면 "왜 이렇게 나눴는지" 설명하기 쉽다.

### 7.5 결과 선택
- 최저 cost 조합을 기본안으로 보여준다.
- "다시 섞기" 버튼: 상위 5개 조합 중 다음 안을 보여준다 (매번 같은 결과가 나오는 문제 방지).
- 운영진은 멤버를 탭해서 반대 팀으로 옮길 수 있다 (옮긴 뒤 밸런스 표시 갱신).

---

## 8. 게임 1 일방성 판정

게임 1 점수 입력 후 아래 기준으로 **재편성 권장** 여부를 표시한다. 최종 선택은 운영진.

```text
margin = |score_a - score_b|
ratio  = min(score) / max(score)

재편성 권장 if  margin >= LOPSIDED_MARGIN  or  ratio <= LOPSIDED_RATIO
```

```python
LOPSIDED_MARGIN = 15     # TBD: 실제 경기 점수대 보고 조정
LOPSIDED_RATIO  = 0.6
```

선택 화면
- **팀 유지**: 게임 1 명단을 그대로 게임 2 `GameRoster`로 복사 (`lineup_mode = kept`)
- **팀 재편성**: 갱신된 레이팅 + 게임 1 페널티로 밸런싱 (`lineup_mode = reshuffled`)

> 판정 결과와 실제 선택을 함께 저장해두면, 나중에 기준값(15점, 0.6)이 적절했는지 검증할 수 있다.

---

## 9. 레이팅 설계

### 9.1 라이브러리
```python
from openskill.models import PlackettLuce
model = PlackettLuce()  # 기본 mu=25, sigma=25/3
```

### 9.2 초기값 (콜드 스타트)

처음에는 경기 기록이 없으므로 **운영진 평가로 시작하고, 경기 결과로 보정**한다.

#### 1단계: 운영진 2~3명이 각자 등급 매기기
- 한 사람이 매기면 친분·포지션 편향이 생기므로 **2~3명이 따로 매긴 뒤 평균**을 낸다.
- 앱의 초기 등급 평가 화면(5.1 STEP 5)에서 각자 입력 → `InitialRating`에 저장
- 다른 운영진의 평가는 제출 전까지 보이지 않음

| 등급 | 기준 (예시) |
|---|---|
| 1 | 입문. 기본기 연습 중 |
| 2 | 초급. 경기 흐름은 따라감 |
| 3 | 중급. 동아리 평균 |
| 4 | 중상급. 경기에 영향을 줌 |
| 5 | 상급. 혼자 경기를 바꿀 수 있음 |

- 평가자 간 차이가 2등급 이상 나는 멤버는 화면에 강조 → 운영진끼리 짧게 이야기해서 조정
- [확정] 시 평균 등급(예: 3.67)을 `Member.initial_grade`에 저장

#### 2단계: 등급 → 레이팅 변환
```python
mu    = 13 + 4 * grade      # 1.0 → 17, 3.0 → 25, 5.0 → 33 (소수 등급도 그대로 변환)
sigma = 25 / 3              # 8.333, 크게 둬서 초반 결과로 빠르게 보정
```

#### 3단계: 초반 4주 운영 (보정 기간)
- 주 2게임 × 4주 = 8게임이면 대부분 멤버의 레이팅이 자리를 잡는다.
- 이 기간에는 운영진이 팀 결과를 보고 **수동 이동을 적극 사용** (레이팅이 아직 부정확하므로)
- 4주 후 운영진 화면에서 "초기 등급 vs 현재 레이팅" 비교표를 보고 크게 어긋난 사람 확인
- 신규 멤버는 같은 방식으로 운영진 2명이 등급을 매겨 추가

> 한 시즌 약 100게임이 쌓이므로, 시즌 중반부터는 초기 등급의 영향은 거의 사라진다.

### 9.3 경기 후 갱신
```python
team_a = [model.create_rating([m.mu, m.sigma], name=str(m.id)) for m in roster_a]
team_b = [model.create_rating([m.mu, m.sigma], name=str(m.id)) for m in roster_b]

new_a, new_b = model.rate([team_a, team_b], scores=[score_a, score_b])
```
- 갱신 전/후 값을 `RatingHistory`에 저장하고 `Member.mu/sigma` 업데이트
- 게임 1 갱신 결과가 **게임 2 재편성에 바로 반영**된다
- 교체 인원(6명 중 1명이 쉬는 시간)은 MVP에서는 구분하지 않고 팀원 전원 동일 반영

### 9.4 결과 수정/삭제
- `recalculate_from(game_id)`: 해당 게임 이후 모든 게임을 시간순으로 재계산
- 수정 대상 게임 이후의 `RatingHistory`를 삭제하고 각 멤버의 직전 값에서 다시 계산

### 9.5 비활성 멤버 (선택)
- 8주 이상 미출석 후 복귀 시 sigma를 초기값 쪽으로 일부 되돌려 빠르게 재보정

---

## 10. 화면 구성 (모바일 우선)

| 화면 | 경로 | 내용 |
|---|---|---|
| 홈 | `/` | 이번 주 일요일 모임 카드 (날짜, 장소, 참석 n명), 투표 버튼 |
| 참석 투표 | `/s/{session_id}` | 이름 선택(최초 1회) → 참석/불참/미정. 현재 참석자 명단 |
| 오늘 경기 | `/s/{session_id}/day` | 게임 1·2 팀 명단, 점수, 진행 상태를 한 화면에 |
| 출석 체크 | `/admin/s/{id}/checkin` | (운영진) 실제 온 사람 탭으로 체크 |
| 팀 짜기 | `/admin/s/{id}/game/{no}/lineup` | (운영진) 자동 생성, 다시 섞기, 수동 이동 |
| 점수 입력 | `/admin/s/{id}/game/{no}/score` | (운영진) A/B 점수 입력 → 저장 |
| 게임 2 선택 | `/admin/s/{id}/game/2/choose` | 일방성 판정 배지 + [팀 유지] [팀 재편성] |
| 기록 | `/stats` | 출석왕, 승률, 연승, 경기 수 (레이팅 미노출) |
| 내 기록 | `/me` | 내 출석률, 승률, 최근 경기 |
| 관리자 | `/admin` | 멤버 관리, 모임 생성, 레이팅 열람, 설정 |

UX 원칙
- 현장 조작은 **한 손으로 10초 이내** (점수 입력: 숫자 두 개 → 저장)
- 투표 링크는 카톡 미리보기용 OG 태그 설정 (제목: "10/19(일) 농구 참석 투표")
- "오늘 경기" 화면은 HTMX로 주기적 갱신(30초) → 다른 사람 폰에서도 팀 결과 확인

---

## 11. API 엔드포인트

> HTML 라우트와 별개로 JSON API를 유지해 테스트와 확장을 쉽게 한다.

```text
# 멤버
GET    /api/members
POST   /api/members                          (admin)
PATCH  /api/members/{id}                     (admin)

# 모임
GET    /api/sessions/upcoming
POST   /api/sessions                         (admin)   # 기본 다음 일요일
PATCH  /api/sessions/{id}                    (admin)   # 마감/종료

# 참석
GET    /api/sessions/{id}/attendance
PUT    /api/sessions/{id}/vote               body: {member_id, vote}
PATCH  /api/sessions/{id}/checkin            (admin) body: {member_id, checked_in}

# 게임 / 라인업
POST   /api/sessions/{id}/games/1/lineup     (admin)   # 자동 밸런싱
POST   /api/sessions/{id}/games/2/lineup     (admin) body: {mode: "kept" | "reshuffled"}
POST   /api/games/{id}/lineup/next           (admin)   # 다시 섞기 (다음 후보안)
PATCH  /api/games/{id}/lineup/move           (admin) body: {member_id}
GET    /api/sessions/{id}/games

# 결과
POST   /api/games/{id}/result                (admin) body: {score_a, score_b}
       → 응답에 game_no=1이면 {lopsided: bool, margin, ratio} 포함
PATCH  /api/games/{id}/result                (admin)   # 수정 → 재계산

# 기록
GET    /api/stats?season=2026
GET    /api/members/{id}/stats
GET    /api/admin/ratings                    (admin)
```

---

## 12. 프로젝트 구조

```text
basketball-club/
├── api/
│   └── index.py             # Vercel 진입점: from app.main import app
├── app/
│   ├── main.py              # FastAPI 앱, 라우터 등록
│   ├── config.py            # 설정 (환경변수, 가중치, 기준값)
│   ├── db.py                # NullPool 엔진, 세션 의존성
│   ├── models.py
│   ├── schemas.py
│   ├── auth.py              # 멤버 쿠키, 운영진 PIN
│   ├── routers/
│   │   ├── pages.py         # HTML 화면
│   │   ├── members.py
│   │   ├── sessions.py
│   │   ├── games.py
│   │   └── stats.py
│   ├── services/
│   │   ├── balancer.py      # 전수 탐색 밸런싱 (순수 함수, DB 의존 없음)
│   │   ├── lopsided.py      # 일방성 판정
│   │   ├── rating.py        # openskill 래퍼, 재계산
│   │   └── stats.py         # 출석/승률/연승 집계
│   └── templates/
├── public/                  # 정적 파일
├── alembic/
├── scripts/
│   └── seed_members.py      # 동아리 멤버 + 초기 등급 입력
├── tests/
│   ├── test_balancer.py
│   ├── test_lopsided.py
│   └── test_rating.py
├── vercel.json
├── requirements.txt
├── .env.example
└── README.md
```

`vercel.json` 예시
```json
{
  "rewrites": [{ "source": "/(.*)", "destination": "/api/index" }]
}
```

---

## 13. 설정값 (config.py)

```python
TEAM_COUNT = 2
SESSION_WEEKDAY = 6               # 일요일 (월=0)
VOTE_DEADLINE = "SAT 22:00"
GAMES_PER_SESSION = 2

REPEAT_LOOKBACK_WEEKS = 3
REPEAT_DECAY = [1.0, 0.6, 0.3]
WEIGHTS = {"strength": 1.0, "position": 2.0, "height": 1.0,
           "repeat_weekly": 0.8, "repeat_game1": 3.0}
BALANCE_MODES = {"skill": 0.5, "balanced": 1.0, "height": 2.0}   # w_height
RANK_WEIGHTS = [1.5, 1.3, 1.0, 0.8, 0.7, 0.7]
HEIGHT_SCALE = 5
SPLIT_TALLEST_N = 2
MIN_SWAPS_ON_RESHUFFLE = 2
TOP_K_CANDIDATES = 5
EXHAUSTIVE_MAX_PLAYERS = 17

LOPSIDED_MARGIN = 15
LOPSIDED_RATIO = 0.6

GRADE_TO_MU = lambda g: 13 + 4 * g    # 1.0~5.0 소수 등급 지원
INITIAL_SIGMA = 25 / 3
CALIBRATION_WEEKS = 4
INACTIVE_WEEKS = 8
```

---

## 14. 개발 단계

### Phase 1 – 뼈대 + 배포 (1주차)
- [ ] FastAPI 프로젝트 생성, `api/index.py` + `vercel.json`
- [ ] Neon `main`/`dev` 브랜치 생성, SQLAlchemy(NullPool) + Alembic 설정
- [ ] 모델 정의 및 마이그레이션
- [ ] "Hello" 페이지를 Vercel에 먼저 배포해 Neon 연결 확인 (초기에 배포 문제를 털고 간다)
- [ ] `/setup` 첫 운영진 생성 + 운영진 PIN 로그인
- [ ] 멤버 일괄 등록(붙여넣기), 멤버 CRUD, 운영진 지정
- [ ] 첫 방문 시 키·포지션 입력
- [ ] 초기 등급 평가 화면 + 확정
- [ ] 개발용 시드 스크립트 (dev 브랜치)

### Phase 2 – 투표 + 게임 1 팀 (2주차)
- [ ] 모임 생성 / 참석 투표 / 출석 체크 화면
- [ ] `balancer.py` 전수 탐색 + 단위 테스트
- [ ] 팀 짜기 화면 (다시 섞기, 수동 이동)

### Phase 3 – 결과 + 레이팅 + 게임 2 (3주차)
- [ ] 점수 입력, `rating.py` (갱신, 이력, 재계산) + 테스트
- [ ] `lopsided.py` 일방성 판정 + 게임 2 선택 화면 (유지/재편성)
- [ ] "오늘 경기" 통합 화면

### Phase 4 – 기록 + 실전 투입 (4주차)
- [ ] 공개 기록 페이지, 내 기록
- [ ] OG 태그, 모바일 UI 다듬기
- [ ] 실제 일요일 모임에서 테스트 운영 → 가중치·일방성 기준 조정

---

## 15. 테스트 기준

- `balancer`: 12명 입력 시 6:6, 13명 입력 시 7:6
- `balancer`: G/F/C가 한 팀에 몰리지 않음 (position_gap ≤ 1이 가능한 입력에서)
- `balancer`: 재편성 모드에서 게임 1 대비 최소 2명 이상 교체
- `balancer`: 키 상위 2명은 항상 다른 팀
- `balancer`: "190+165" vs "178+178" 같은 입력에서 평균은 같아도 `height_matchup_gap`이 크게 나옴
- `setup`: 운영진이 1명이라도 있으면 `/setup` 접근 시 404
- `import`: 이름만 있는 줄, 이름·포지션·키가 있는 줄 모두 등록되고 중복 이름은 경고
- `rating-setup`: 운영진 3명 평가 평균이 올바르게 계산되고, 2등급 이상 차이 나는 멤버가 강조됨
- `rating-setup`: 확정 전에는 팀 짜기 API가 거부됨
- `balancer`: 16명 기준 응답 0.5초 이내 (서버리스 콜드스타트 제외)
- `lopsided`: 경계값(14점/15점, 0.6) 테스트
- `rating`: 이긴 팀 전원 mu 증가, 진 팀 전원 mu 감소
- `rating`: 게임 결과 수정 후 재계산 결과가 처음부터 올바르게 입력한 경우와 동일

---

## 16. 미정 사항 (운영하면서 확정)

- [ ] 일방성 판정 기준값 (평소 경기 점수대 확인 후 조정)
- [ ] 시즌 단위 (연 단위 / 반기 단위)
- [ ] 공개 랭킹 지표 최종 선정
- [ ] 레이팅을 본인에게만 보여줄지 여부
- [ ] 교체 인원(쉬는 시간) 레이팅 반영 방식 개선 여부

---

## 17. 확장 아이디어

- Vercel Cron으로 매주 월요일 다음 일요일 모임 자동 생성
- 회비·대관비 n분의 1 정산 및 미납 알림
- 시즌 종료 시 LLM으로 "올해의 시상식" 리포트 생성
- 멤버별 개인 링크 / 카카오 로그인
- 경기 영상 업로드 및 득점 장면 자동 클립
