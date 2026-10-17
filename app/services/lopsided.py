"""게임 1 일방성 판정 (명세서 8장)."""
from dataclasses import dataclass

from app.config import LOPSIDED_MARGIN, LOPSIDED_RATIO


@dataclass
class LopsidedResult:
    lopsided: bool
    margin: int
    ratio: float


def judge(score_a: int, score_b: int, margin_limit: int = LOPSIDED_MARGIN,
          ratio_limit: float = LOPSIDED_RATIO) -> LopsidedResult:
    margin = abs(score_a - score_b)
    hi, lo = max(score_a, score_b), min(score_a, score_b)
    ratio = lo / hi if hi > 0 else 1.0
    return LopsidedResult(lopsided=margin >= margin_limit or ratio <= ratio_limit,
                          margin=margin, ratio=round(ratio, 3))
