import random
import time

import pytest

from app.services.balancer import (BalanceError, Player, balance, evaluate, height_matchup_gap,
                                   swaps_vs, weekly_pair_weights)


def make_players(n, seed=0):
    rnd = random.Random(seed)
    return [Player(id=i + 1, mu=rnd.uniform(17, 33), position=rnd.choice("GFC"),
                   height=rnd.randint(165, 195)) for i in range(n)]


def sides_of(c):
    return {**{m: "A" for m in c.team_a}, **{m: "B" for m in c.team_b}}


def test_12_players_split_6_6():
    c = balance(make_players(12))[0]
    assert sorted([len(c.team_a), len(c.team_b)]) == [6, 6]
    assert set(c.team_a) | set(c.team_b) == set(range(1, 13))


def test_13_players_split_7_6():
    c = balance(make_players(13))[0]
    assert sorted([len(c.team_a), len(c.team_b)]) == [6, 7]


def test_10_and_14_players():
    assert sorted(map(len, (lambda c: (c.team_a, c.team_b))(balance(make_players(10))[0]))) == [5, 5]
    assert sorted(map(len, (lambda c: (c.team_a, c.team_b))(balance(make_players(14))[0]))) == [7, 7]


def test_positions_not_concentrated():
    # G4 F4 C4 → 각 팀 2/2/2 가 가능한 입력
    players = [Player(i + 1, 25 + (i % 3), "GFC"[i % 3], 175 + i) for i in range(12)]
    c = balance(players)[0]
    assert c.breakdown["position_gap"] <= 1


def test_tallest_two_always_split():
    for seed in range(20):
        players = make_players(12, seed)
        tallest = sorted(players, key=lambda p: (-p.height, p.id))[:2]
        for c in balance(players):
            sa = sides_of(c)
            assert sa[tallest[0].id] != sa[tallest[1].id]


def test_reshuffle_min_two_swaps():
    for seed in range(10):
        players = make_players(12, seed)
        g1 = sides_of(balance(players)[0])
        for c in balance(players, game1_sides=g1):
            assert swaps_vs(c.team_a, c.team_b, g1) >= 2


def test_height_matchup_detects_mismatch_with_same_average():
    # 평균 키는 같지만 (190+165) vs (178+177) — 매치업 차이가 커야 한다
    lopsided = height_matchup_gap([190, 165], [178, 177])
    even = height_matchup_gap([178, 177], [178, 177])
    assert sum([190, 165]) / 2 == pytest.approx(sum([178, 177]) / 2)
    assert lopsided > 3
    assert even == 0


def test_height_matchup_odd_team_drops_shortest():
    assert height_matchup_gap([190, 180, 150], [190, 180]) == 0


def test_16_players_under_half_second():
    t = time.perf_counter()
    balance(make_players(16))
    assert time.perf_counter() - t < 0.5


def test_too_many_players_rejected():
    with pytest.raises(BalanceError):
        balance(make_players(18))


def test_candidates_sorted_and_distinct():
    cands = balance(make_players(12), top_k=5)
    assert len(cands) == 5
    assert [c.cost for c in cands] == sorted(c.cost for c in cands)
    assert len({frozenset(c.team_a) for c in cands} | set()) == 5


def test_weekly_repeat_penalty_discourages_same_pairs():
    players = [Player(i + 1, 25.0, None, None) for i in range(8)]  # 실력/키/포지션 모두 동일
    last_week = [{1: "A", 2: "A", 3: "A", 4: "A", 5: "B", 6: "B", 7: "B", 8: "B"}]
    pairs = weekly_pair_weights([last_week])
    best = balance(players, weekly_pairs=pairs, split_tallest_n=0)[0]
    same = evaluate([p for p in players if p.id <= 4], [p for p in players if p.id > 4], weekly_pairs=pairs)
    assert best.breakdown["repeat_weekly"] < same.breakdown["repeat_weekly"]


def test_missing_heights_do_not_crash():
    players = [Player(i + 1, 20 + i, "G", None if i % 2 else 180) for i in range(10)]
    assert balance(players)
