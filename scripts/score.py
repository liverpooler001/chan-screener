# -*- coding: utf-8 -*-
"""评分：结构 40 + 资金 40 + 比价 15 + 质量 5 = 100（P1 起含主力资金流）。

    结构 structure  买点类型 / 级别权重 / 双级别共振 / 信号新鲜度（原评分归一化到 40）
    资金 fund       量比 8 + 成交额分位 8 + 当日主力净占比 12 + 5日主力净占比 7
                    + 所属行业板块主力资金排名 5
    比价 relative   RS5 6 + RS20 4 + 行业涨幅强弱分位 5
    质量 quality    动态市盈率合理性 5

分数只用于「同一交易日内的排序」，不等于上涨概率。
阈值集中在本文件顶部，权重从 config.yaml 的 scoring.weights 读取；
把 fund 里各项调成 0、structure 调成 80 即可退回 P0 之前的纯结构排序。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# ---------------- 结构 ----------------
KIND_SCORE = {"3": 40, "2": 34, "1": 30}   # 三买 > 二买 > 一买
STRUCT_RAW_MAX = 99.0                      # 40 + 34 + 15(共振) + 10(新鲜度)

# ---------------- 阈值 ----------------
VOL_RATIO = ((1.5, 8), (1.2, 5), (1.0, 3))            # 量比 → 分
AMOUNT_PCT = ((0.70, 8), (0.50, 5), (0.30, 2))        # 成交额分位 → 分
MAIN_PCT = ((10.0, 12), (5.0, 9), (2.0, 6), (0.0, 3))  # 当日主力净占比(%) → 分
MAIN_5D = ((8.0, 7), (3.0, 5), (0.0, 2))              # 5日主力净占比(%) → 分
IND_FUND_PCT = ((0.80, 5), (0.60, 3), (0.40, 1))      # 行业资金排名分位 → 分
RS5 = ((3.0, 6), (1.0, 4), (0.0, 2))                  # 5 日相对强度(%) → 分
RS20 = ((5.0, 4), (0.0, 2))                           # 20 日相对强度(%) → 分
INDUSTRY_PCT = ((0.80, 5), (0.60, 3), (0.40, 1))      # 行业涨幅分位 → 分
INDUSTRY_NEUTRAL = 3                                   # ETF / 缺行业数据时给中性分
IND_FUND_NEUTRAL = 2                                   # 同上，行业资金中性分

DEFAULT_WEIGHTS = {"structure": 40, "fund": 40, "relative": 15, "quality": 5}


def _step(value: Optional[float], table) -> int:
    if value is None:
        return 0
    for edge, pts in table:
        if value >= edge:
            return pts
    return 0


def structure_raw(m30: Optional[Dict], m5: Optional[Dict]) -> Tuple[float, Optional[int]]:
    """原结构分（0~99），第二个返回值是最新鲜的那根 K 线的 bars_ago。"""
    raw, fresh = 0.0, None
    for lv, base in ((m30, 1.0), (m5, 0.85)):
        if not lv:
            continue
        raw += KIND_SCORE.get(lv.get("kind"), 25) * base
        b = lv.get("bars_ago")
        fresh = b if fresh is None else min(fresh, b)
    if m30 and m5:
        raw += 15
    if fresh is not None:
        raw += 10 if fresh <= 2 else 6 if fresh <= 6 else 3 if fresh <= 12 else 0
    return raw, fresh


def score_signal(
    m30: Optional[Dict],
    m5: Optional[Dict],
    metrics: Optional[Dict],
    pe: Optional[float],
    is_etf: bool,
    weights: Optional[Dict] = None,
) -> Tuple[int, Dict, list]:
    """返回 (总分, 各维度得分, 文字理由)。"""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update({k: v for k, v in weights.items() if isinstance(v, (int, float))})
    metrics = metrics or {}

    # ---- 结构 ----
    raw, fresh = structure_raw(m30, m5)
    structure = raw / STRUCT_RAW_MAX * w["structure"]

    # ---- 资金 ----
    vr = metrics.get("vol_ratio")
    ap = metrics.get("amount_pct")
    mp = metrics.get("main_pct")
    m5p = metrics.get("main_5d_pct")
    ifp = metrics.get("industry_fund_pct")
    fund = _step(vr, VOL_RATIO) + _step(ap, AMOUNT_PCT)
    fund += _step(mp, MAIN_PCT) + _step(m5p, MAIN_5D)
    fund += _step(ifp, IND_FUND_PCT) if ifp is not None else IND_FUND_NEUTRAL

    # ---- 比价 ----
    rs5, rs20 = metrics.get("rs5"), metrics.get("rs20")
    ip = metrics.get("industry_pct")
    relative = _step(rs5, RS5) + _step(rs20, RS20)
    relative += _step(ip, INDUSTRY_PCT) if ip is not None else INDUSTRY_NEUTRAL

    # ---- 质量 ----
    if is_etf:
        quality = w["quality"]
    elif pe and pe < 50:
        quality = w["quality"]
    elif pe and pe < 100:
        quality = round(w["quality"] * 0.6, 1)
    else:
        quality = 0

    parts = {
        "structure": round(structure, 1),
        "fund": round(fund, 1),
        "relative": round(relative, 1),
        "quality": round(quality, 1),
    }
    total = int(round(max(0, min(100, sum(parts.values())))))

    # ---- 理由（给前端展示，最多 4 条）----
    why = []
    if m30 and m5:
        why.append("双级别共振")
    if mp is not None and mp >= 2:
        why.append(f"主力净流入 {mp:+.1f}%")
    elif m5p is not None and m5p >= 3:
        why.append(f"5日主力净流入 {m5p:+.1f}%")
    if vr is not None and vr >= 1.2:
        why.append(f"量比 {vr:.2f} 放量")
    if ap is not None and ap >= 0.5:
        why.append(f"成交额居近 60 日 {ap * 100:.0f}% 分位")
    if rs5 is not None and rs5 >= 1:
        why.append(f"5日跑赢沪深300 {rs5:+.1f}%")
    if ifp is not None and ifp >= 0.6:
        why.append(f"行业资金流入前 {round((1 - ifp) * 100)}%")
    elif ip is not None and ip >= 0.6:
        why.append(f"所属行业强度前 {round((1 - ip) * 100)}%")
    if fresh is not None and fresh <= 6:
        why.append(f"信号新鲜（{fresh} 根K线内）")
    return total, parts, why[:4]
