"""竞价超预期五步法（auction_five_step_score）单元测试。

钉住 2026-10-15 分位校准后的关键行为：
- _EXPECT_TABLE 新中枢（S1 不再要求高开 1~3%）
- fail 线接入判定（gap < fail → 不及预期，不再进机会组）
- 放量出清 CL ≥ 30 门槛（S9 天量出货不得判出清）
- 出清分支已降级为观察项（2026-10-16 验证：中位 -2.38%/胜率40%，删买入语义）
- rule 文案与 R 实际档位一致
"""
from src.api.trading_tools_routes import _EXPECT_TABLE, auction_five_step_score


def _score(**kw):
    base = dict(cl_pct=50.0, turnover_pct=5.0, vol_ratio=None, gap_pct=0.0, r_pct=None)
    base.update(kw)
    return auction_five_step_score(**base)


class TestExpectTable:
    def test_new_s1_hub_is_flat_not_positive(self):
        hub_lo, hub_hi, sup, fail = _EXPECT_TABLE["S1"]
        assert hub_lo < 0 < hub_hi < 1.0  # 旧表 (1,3,5,0) 已废弃
        assert fail < hub_lo

    def test_all_keys_present(self):
        for k in ("S1_lb", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"):
            hub_lo, hub_hi, sup, fail = _EXPECT_TABLE[k]
            assert fail < hub_lo < hub_hi < sup, k


class TestS1Zone:
    def test_flat_open_is_normal(self):
        s = _score(cl_pct=80, turnover_pct=3, gap_pct=0.0)
        assert s["zone"] == "S1"
        assert s["verdict"] == "正常"

    def test_mild_gap_is_bias_not_super(self):
        s = _score(cl_pct=80, turnover_pct=3, gap_pct=0.5)
        assert s["verdict"] == "偏强"

    def test_gap_over_sup_without_volume_is_weak_super(self):
        s = _score(cl_pct=80, turnover_pct=3, gap_pct=1.0, r_pct=1.0)
        assert s["verdict"] == "弱超预期"

    def test_sup_with_r5_is_super(self):
        s = _score(cl_pct=80, turnover_pct=3, gap_pct=1.0, r_pct=6.0)
        assert s["verdict"] == "超预期"

    def test_sup_with_r9_is_strong_super(self):
        s = _score(cl_pct=80, turnover_pct=3, gap_pct=1.0, r_pct=9.0)
        assert s["verdict"] == "强超预期"


class TestFailGate:
    def test_gap_below_fail_is_miss_not_decay(self):
        # S6: fail=-4.40，gap 更低且 T>15 → 旧代码会判抛压衰竭，新代码判不及预期
        s = _score(cl_pct=40, turnover_pct=20, gap_pct=-4.5, r_pct=1.0)
        assert s["zone"] == "S6"
        assert s["verdict"] == "不及预期"
        assert "不及线" in s["rule"]

    def test_gap_below_fail_with_r5_is_dump_still(self):
        # R≥5 优先于 fail（放量低开出货语义不变）
        s = _score(cl_pct=40, turnover_pct=20, gap_pct=-4.5, r_pct=6.0)
        assert s["verdict"] == "出货加速"

    def test_gap_between_fail_and_hub_lo_can_decay(self):
        # gap 在 fail 与中枢下沿之间且 CL≥30、T>15、收阴 → 放量出清待确认（观察，不买）
        s = _score(cl_pct=40, turnover_pct=20, gap_pct=-3.0, r_pct=1.0, yday_yin=True)
        assert s["verdict"] == "放量出清待确认"
        assert s["action"] == "观察，不买（出清未确认）"


class TestDecayClGate:
    def test_s9_high_turnover_is_not_decay(self):
        # CL<30 & T>15 = S9 天量出货：不得判出清，R<3 → 抛压未释放
        s = _score(cl_pct=20, turnover_pct=20, gap_pct=-3.0, r_pct=1.0, yday_yin=True)
        assert s["zone"] == "S9"
        assert s["verdict"] == "抛压未释放"

    def test_s9_r_none_is_miss(self):
        s = _score(cl_pct=20, turnover_pct=20, gap_pct=-3.0, r_pct=None, yday_yin=True)
        assert s["zone"] == "S9"
        assert s["verdict"] == "不及预期"

    def test_s6_outflow_watch_only(self):
        s = _score(cl_pct=40, turnover_pct=20, gap_pct=-3.0, r_pct=1.0, yday_yin=True)
        assert s["zone"] == "S6"
        assert s["verdict"] == "放量出清待确认"
        assert s["action"] == "观察，不买（出清未确认）"


class TestYinGate:
    """昨日收阴门槛（2026-10-15，绿盟科技案例）：放量滞涨阳线不标出清形态。"""

    def test_green_union_case_is_not_decay(self):
        # 绿盟 sz300369: 10-14 平收阳线（开10.82 收11.05）T=16.37% CL=41，
        # 10-15 竞价 -3.44% R=1.79% —— 旧判出清，现应抛压未释放/回避
        s = _score(cl_pct=41, turnover_pct=16.37, gap_pct=-3.44, r_pct=1.79, yday_yin=False)
        assert s["zone"] == "S6"
        assert s["verdict"] == "抛压未释放"
        assert s["action"] == "回避"

    def test_same_inputs_with_yin_is_outflow_watch(self):
        s = _score(cl_pct=41, turnover_pct=16.37, gap_pct=-3.44, r_pct=1.79, yday_yin=True)
        assert s["verdict"] == "放量出清待确认"

    def test_yday_yin_none_is_conservative_not_decay(self):
        s = _score(cl_pct=41, turnover_pct=16.37, gap_pct=-3.44, r_pct=1.79)
        assert s["verdict"] == "抛压未释放"
        assert s["yday_yin"] is None

    def test_r_mid_with_non_yin_high_turnover_is_miss(self):
        # R∈[3,5) + 放量阳线 → 不及预期（放量未出清）
        s = _score(cl_pct=41, turnover_pct=16.37, gap_pct=-3.44, r_pct=4.0, yday_yin=False)
        assert s["verdict"] == "不及预期"
        assert "未收阴" in s["rule"]


class TestRuleText:
    def test_decay_rule_uses_actual_r_level(self):
        # R=4 属「正常」档，旧文案写死"缩量"是错的
        s = _score(cl_pct=40, turnover_pct=20, gap_pct=-3.0, r_pct=4.0, yday_yin=True)
        assert s["verdict"] == "放量出清待确认"
        assert "缩量" not in s["rule"]
        assert "正常" in s["rule"]

    def test_dump_rule_says_below_hub_not_gap_down(self):
        # hub_lo 可为正（S1_lb），gap 可为正；文案不得写死"放量低开"
        s = _score(cl_pct=80, turnover_pct=3, gap_pct=-1.2, r_pct=6.0, is_lianban=True)
        assert s["verdict"] == "出货加速"
        assert "低开" not in s["rule"]


class TestWeakZoneSupGe:
    def test_s7_sup_is_inclusive(self):
        # 弱势档 sup_ge：gap == sup 即算超预期系
        hub_lo, hub_hi, sup, fail = _EXPECT_TABLE["S7"]
        s = _score(cl_pct=20, turnover_pct=3, gap_pct=sup, r_pct=6.0)
        assert s["zone"] == "S7"
        assert s["sup_ge"] is True
        assert s["verdict"] == "超预期"

    def test_s7_just_below_sup_is_bias(self):
        hub_lo, hub_hi, sup, fail = _EXPECT_TABLE["S7"]
        s = _score(cl_pct=20, turnover_pct=3, gap_pct=sup - 0.01)
        assert s["verdict"] == "偏强"


class TestLianbanAndPassthrough:
    def test_s1_lb_uses_own_table(self):
        s = _score(cl_pct=80, turnover_pct=3, gap_pct=4.0, is_lianban=True)
        assert s["zone"] == "S1"
        assert s["lianban"] is True
        assert s["hub"] == [3.0, 5.0]
        assert s["verdict"] == "正常"

    def test_vr_is_passthrough_only(self):
        a = _score(cl_pct=80, turnover_pct=3, gap_pct=0.0, vol_ratio=None)
        b = _score(cl_pct=80, turnover_pct=3, gap_pct=0.0, vol_ratio=2.5)
        assert b["vr"] == 2.5
        assert a["verdict"] == b["verdict"] == "正常"

    def test_missing_turnover_assumed_and_miss_below_hub(self):
        s = _score(cl_pct=50, turnover_pct=None, gap_pct=-1.5)
        assert s["turnover_assumed"] is True
        assert s["verdict"] == "不及预期"
        assert "换手率缺失" in s["rule"]
