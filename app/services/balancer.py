"""전수 탐색 팀 밸런싱 (명세서 7장). 순수 함수, DB 의존 없음."""
from __future__ import annotations

import heapq
import itertools
import math
import statistics
from dataclasses import dataclass, field

from app.config import (EXHAUSTIVE_MAX_PLAYERS, HEIGHT_SCALE, MIN_SWAPS_ON_RESHUFFLE,
                        RANK_WEIGHTS, SPLIT_TALLEST_N, TOP_K_CANDIDATES, WEIGHTS)

DEFAULT_HEIGHT = 178


@dataclass(frozen=True)
class Player:
    id: int
    mu: float
    position: str | None = None
    height: int | None = None


@dataclass
class Candidate:
    team_a: list[int]
    team_b: list[int]
    cost: float
    breakdown: dict[str, float] = field(default_factory=dict)


class BalanceError(ValueError):
    pass


def pair_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def height_matchup_gap(heights_a, heights_b, weights=RANK_WEIGHTS, scale=HEIGHT_SCALE):
    """키 순서대로 1:1 매치업 차이. 홀수 인원이면 많은 팀의 가장 작은 선수는 비교에서 빠진다."""
    a = sorted(heights_a, reverse=True)
    b = sorted(heights_b, reverse=True)
    n = min(len(a), len(b))
    w = list(weights) + [weights[-1]] * max(0, n - len(weights))
    return sum(wi * abs(x - y) for wi, x, y in zip(w, a[:n], b[:n])) / scale


def position_gap(pos_a, pos_b) -> int:
    return sum(abs(sum(1 for p in pos_a if p == k) - sum(1 for p in pos_b if p == k))
               for k in ("G", "F", "C"))


def _filled_heights(players: list[Player]) -> dict[int, float]:
    """키 미입력자는 참가자 키 중앙값으로 취급."""
    known = [p.height for p in players if p.height]
    fill = statistics.median(known) if known else DEFAULT_HEIGHT
    return {p.id: (p.height or fill) for p in players}


def _same_team_pairs(ids: list[int]):
    return itertools.combinations(sorted(ids), 2)


def evaluate(team_a: list[Player], team_b: list[Player], *, weights: dict | None = None,
             heights: dict[int, float] | None = None,
             weekly_pairs: dict[tuple[int, int], float] | None = None,
             game1_sides: dict[int, str] | None = None,
             early_ids: set[int] | None = None) -> Candidate:
    """두 팀 구성의 비용과 항목별 내역 계산. early_ids: 조퇴 예정자 (같은 팀에 몰리지 않게)."""
    w = {**WEIGHTS, **(weights or {})}
    heights = heights or _filled_heights(team_a + team_b)
    if not team_a or not team_b:
        raise BalanceError("두 팀 모두 1명 이상이어야 합니다.")

    strength_gap = abs(sum(p.mu for p in team_a) / len(team_a) - sum(p.mu for p in team_b) / len(team_b))
    pos_gap = position_gap([p.position for p in team_a], [p.position for p in team_b])
    h_gap = height_matchup_gap([heights[p.id] for p in team_a], [heights[p.id] for p in team_b])

    ids_a = [p.id for p in team_a]
    ids_b = [p.id for p in team_b]
    pairs = list(_same_team_pairs(ids_a)) + list(_same_team_pairs(ids_b))
    n_pairs = max(1, len(pairs))

    # 반복 조합 페널티는 같은 팀 쌍 개수로 정규화한다 (0~1 범위, 인원수에 무관하게 가중치 의미 유지)
    weekly = 0.0
    if weekly_pairs:
        weekly = sum(weekly_pairs.get(pk, 0.0) for pk in pairs) / n_pairs
    g1 = 0.0
    if game1_sides:
        g1 = sum(1 for x, y in pairs
                 if x in game1_sides and y in game1_sides and game1_sides[x] == game1_sides[y]) / n_pairs

    breakdown = {
        "strength": w["strength"] * strength_gap,
        "position": w["position"] * pos_gap,
        "height": w["height"] * h_gap,
        "repeat_weekly": w["repeat_weekly"] * weekly,
        "repeat_game1": w["repeat_game1"] * g1 if game1_sides else 0.0,
        "early_together": w.get("early_split", 0.0) * _early_pairs(ids_a, ids_b, early_ids),
    }
    raw = {"strength_gap": strength_gap, "position_gap": pos_gap, "height_matchup_gap": h_gap}
    return Candidate(team_a=ids_a, team_b=ids_b, cost=sum(breakdown.values()),
                     breakdown={**breakdown, **raw})


def _early_pairs(ids_a: list[int], ids_b: list[int], early_ids: set[int] | None) -> int:
    """조퇴 예정자끼리 같은 팀인 쌍의 수 (양 팀에 고르게 나뉠수록 작다)."""
    if not early_ids:
        return 0
    ea = sum(1 for i in ids_a if i in early_ids)
    eb = sum(1 for i in ids_b if i in early_ids)
    return ea * (ea - 1) // 2 + eb * (eb - 1) // 2


def swaps_vs(team_a: list[int], team_b: list[int], game1_sides: dict[int, str]) -> int:
    """게임1 대비 맞교환 인원: 라벨 방향을 맞춘 뒤 게임1 A팀에서 B로 넘어간 인원과 그 반대 중 작은 값."""
    def moved(a_label: str) -> int:
        a_to_b = sum(1 for m in team_b if game1_sides.get(m) == a_label)
        b_to_a = sum(1 for m in team_a if game1_sides.get(m) not in (None, a_label))
        return min(a_to_b, b_to_a)
    # 새 A팀이 게임1 A팀과 더 많이 겹치는 방향을 기준으로 삼는다
    overlap_a = sum(1 for m in team_a if game1_sides.get(m) == "A")
    overlap_b = sum(1 for m in team_a if game1_sides.get(m) == "B")
    return moved("A") if overlap_a >= overlap_b else moved("B")


def balance(players: list[Player], *, weights: dict | None = None,
            weekly_pairs: dict[tuple[int, int], float] | None = None,
            game1_sides: dict[int, str] | None = None,
            top_k: int = TOP_K_CANDIDATES,
            split_tallest_n: int = SPLIT_TALLEST_N,
            min_swaps: int = MIN_SWAPS_ON_RESHUFFLE,
            early_ids: set[int] | None = None) -> list[Candidate]:
    """모든 2팀 분할을 계산해 cost 하위 top_k 후보를 반환.

    - 대칭 제거: 첫 번째 선수를 항상 A팀에 고정
    - 홀수 인원이면 한 팀이 1명 많다 (7:6과 6:7 모두 탐색)
    - 키 상위 N명은 서로 다른 팀 (하드 제약, 정보가 있을 때만)
    - game1_sides가 있으면 재편성 모드: 최소 맞교환 인원 제약 + 게임1 같은 팀 페널티
    """
    n = len(players)
    if n < 2:
        raise BalanceError("최소 2명이 필요합니다.")
    if n > EXHAUSTIVE_MAX_PLAYERS:
        raise BalanceError(f"{n}명은 전수 탐색 한도({EXHAUSTIVE_MAX_PLAYERS}명)를 넘습니다.")

    players = sorted(players, key=lambda p: p.id)
    heights = _filled_heights(players)

    tallest: list[int] = []
    known_h = [p for p in players if p.height]
    if split_tallest_n >= 2 and len(known_h) >= 2:
        tallest = [p.id for p in sorted(known_h, key=lambda p: (-p.height, p.id))[:split_tallest_n]]

    reshuffle_ids = {p.id for p in players if game1_sides and p.id in game1_sides}
    # 재편성 제약은 맞교환이 물리적으로 가능할 때만 적용
    enforce_swaps = bool(game1_sides) and min_swaps > 0 and len(reshuffle_ids) >= 2 * min_swaps

    first, rest = players[0], players[1:]
    sizes = {n // 2, math.ceil(n / 2)}
    heap: list[tuple[float, int, Candidate]] = []
    counter = 0

    for size_a in sorted(sizes):
        for combo in itertools.combinations(rest, size_a - 1):
            team_a = [first, *combo]
            a_ids = {p.id for p in team_a}
            team_b = [p for p in rest if p.id not in a_ids]
            if not team_b:
                continue
            if len(tallest) >= 2 and len({("A" if t in a_ids else "B") for t in tallest}) == 1:
                continue
            if enforce_swaps and swaps_vs([p.id for p in team_a], [p.id for p in team_b],
                                          game1_sides) < min_swaps:
                continue
            cand = evaluate(team_a, team_b, weights=weights, heights=heights,
                            weekly_pairs=weekly_pairs, game1_sides=game1_sides, early_ids=early_ids)
            counter += 1
            item = (-cand.cost, counter, cand)
            if len(heap) < top_k:
                heapq.heappush(heap, item)
            elif cand.cost < -heap[0][0]:
                heapq.heapreplace(heap, item)

    if not heap:
        raise BalanceError("제약 조건을 만족하는 팀 조합이 없습니다.")
    result = [c for _, _, c in sorted(heap, key=lambda x: (-x[0], x[1]))]

    # 표시용 라벨 정렬: 재편성이면 게임1 A팀과 더 많이 겹치는 쪽을 A로
    if game1_sides:
        for c in result:
            ov_a = sum(1 for m in c.team_a if game1_sides.get(m) == "A")
            ov_b = sum(1 for m in c.team_b if game1_sides.get(m) == "A")
            if ov_b > ov_a:
                c.team_a, c.team_b = c.team_b, c.team_a
    for c in result:
        c.team_a.sort(key=lambda i: -heights[i])
        c.team_b.sort(key=lambda i: -heights[i])
    return result


def balance_label(breakdown: dict) -> str:
    """팀 전력 숫자 대신 공개하는 밸런스 표시 (명세서 4장)."""
    s = breakdown.get("strength_gap", 0)
    h = breakdown.get("height_matchup_gap", 0)
    p = breakdown.get("position_gap", 0)
    if s <= 1.5 and h <= 2.5 and p <= 2:
        return "양호"
    if s <= 4 and h <= 5:
        return "보통"
    return "주의"


def weekly_pair_weights(past_rosters: list[list[dict[int, str]]], decay=None) -> dict[tuple[int, int], float]:
    """최근 N주 게임별 명단 → 같은 팀 쌍 가중치.

    past_rosters[0] = 1주 전 모임의 게임별 {member_id: side} 목록, [1] = 2주 전 ...
    한 주에 같은 쌍이 두 게임 모두 같은 팀이어도 그 주 가중치는 한 번만 더한다.
    """
    from app.config import REPEAT_DECAY
    decay = decay or REPEAT_DECAY
    weights: dict[tuple[int, int], float] = {}
    for week_idx, games in enumerate(past_rosters[:len(decay)]):
        pairs: set[tuple[int, int]] = set()
        for sides in games:
            for side in ("A", "B"):
                ids = [m for m, s in sides.items() if s == side]
                pairs.update(pair_key(x, y) for x, y in itertools.combinations(ids, 2))
        for pk in pairs:
            weights[pk] = weights.get(pk, 0.0) + decay[week_idx]
    return weights
