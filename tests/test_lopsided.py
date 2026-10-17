from app.services.lopsided import judge


def test_margin_boundary():
    assert judge(44, 30).lopsided is False   # 14점 차, ratio 0.68
    assert judge(45, 30).lopsided is True    # 15점 차


def test_ratio_boundary():
    assert judge(20, 12).lopsided is True    # ratio 0.6 (경계 포함)
    assert judge(20, 13).lopsided is False   # ratio 0.65, 7점 차


def test_order_independent():
    assert judge(30, 45).lopsided is True
    assert judge(30, 45).margin == 15


def test_zero_scores():
    r = judge(0, 0)
    assert r.lopsided is False and r.ratio == 1.0
