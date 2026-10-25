"""설정: 환경변수 + 밸런싱/레이팅 상수 (명세서 13장)."""
import os
from pathlib import Path

try:  # 로컬 개발 편의: .env 파일이 있으면 읽는다 (Vercel에서는 환경변수 사용)
    _env = Path(__file__).resolve().parent.parent / ".env"
    if _env.exists():
        for line in _env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
except OSError:
    pass


def _normalize_db_url(url: str) -> str:
    # Neon이 주는 postgres:// / postgresql:// 를 psycopg v3 드라이버로 고정
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Settings:
    DATABASE_URL: str = _normalize_db_url(os.getenv("DATABASE_URL", "sqlite:///./local.db"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SETUP_TOKEN: str = os.getenv("SETUP_TOKEN", "")
    SEASON: int = int(os.getenv("SEASON", "2026"))
    COOKIE_SECURE: bool = os.getenv("VERCEL", "") == "1"


settings = Settings()

TIMEZONE = "Asia/Seoul"

TEAM_COUNT = 2
SESSION_WEEKDAY = 6               # 일요일 (월=0)
SESSION_START_TIME = "08:00"      # 경기 등록 시 기본 시작 시간
DEFAULT_LOCATION = "경기도 남양주시 와부읍 궁촌로 70"   # 경기 등록 시 기본 장소
VOTE_DEADLINE_HOUR = 22          # (선택) 마감을 둘 때만 사용
GAMES_PER_SESSION = 2

REPEAT_LOOKBACK_WEEKS = 3
REPEAT_DECAY = [1.0, 0.6, 0.3]
WEIGHTS = {"strength": 1.0, "position": 2.0, "height": 1.0,
           "repeat_weekly": 0.8, "repeat_game1": 3.0,
           "early_split": 4.0}   # 게임 2: 조퇴 예정자끼리 같은 팀이면 한 쌍당 (실력 1등급 차이와 같은 무게)
BALANCE_MODES = {"skill": 0.5, "balanced": 1.0, "height": 2.0}   # w_height
BALANCE_MODE_LABELS = {"skill": "실력 우선", "balanced": "균형", "height": "키 우선"}
RANK_WEIGHTS = [1.5, 1.3, 1.0, 0.8, 0.7, 0.7]
HEIGHT_SCALE = 5
SPLIT_TALLEST_N = 2
MIN_SWAPS_ON_RESHUFFLE = 2
TOP_K_CANDIDATES = 5
EXHAUSTIVE_MAX_PLAYERS = 17

LOPSIDED_MARGIN = 15
LOPSIDED_RATIO = 0.6

GRADE_TO_MU = lambda g: 13 + 4 * g    # noqa: E731  1.0~5.0 소수 등급 지원
INITIAL_SIGMA = 25 / 3
CALIBRATION_WEEKS = 4
INACTIVE_WEEKS = 8
GRADE_DISAGREE_THRESHOLD = 2

DEFAULT_PIN = "1234"   # 운영진이 등록한 멤버의 초기 PIN (첫 로그인 때 변경 강제)
PIN_MAX_FAILS = 5
PIN_LOCK_MINUTES = 10
ADMIN_COOKIE_DAYS = 90
MEMBER_COOKIE_DAYS = 365
