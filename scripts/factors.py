# -*- coding: utf-8 -*-
"""P0 因子：量比 / 成交额分位 / 相对强度 RS / 行业强弱分位。

设计原则：**不新增逐标的的网络请求**。
量比、成交额分位、涨跌幅都可以从「已经下载好的 30 分钟 K 线」按日聚合得到；
只有沪深300 指数日线需要一次额外请求（全流程 1 次）。

口径：
    量比      = 今日成交量 / 前 5 个交易日均量
    成交额分位 = 今日成交额在近 60 个交易日中的分位（1 = 最大）
    RS(n)     = 个股 n 日涨幅 − 沪深300 n 日涨幅
    行业分位   = 所属行业当日平均涨幅，在所有行业中的分位（1 = 最强）
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import requests

INDEX_CODE = "000300"
INDEX_NAME = "沪深300"
EM_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


# --------------------------------------------------------------------------- #
# 日线聚合
# --------------------------------------------------------------------------- #
def daily_series(bars) -> List[Dict]:
    """把分钟 K 线按自然日聚合成日线：[{date, close, vol, amount}]。

    amount 用 volume(手) × 100 × close 估算，只用于「分位」这种相对比较，
    不追求和真实成交额对齐。
    """
    agg: Dict[str, Dict] = {}
    for b in bars:
        d = b.dt[:10]
        a = agg.get(d)
        if a is None:
            a = agg[d] = {"date": d, "close": b.close, "vol": 0.0, "amount": 0.0}
        a["close"] = b.close
        a["vol"] += b.volume or 0.0
        a["amount"] += (b.volume or 0.0) * 100.0 * b.close
    return [agg[k] for k in sorted(agg)]


def _ratio(a: float, b: float) -> Optional[float]:
    if not b:
        return None
    return a / b


# --------------------------------------------------------------------------- #
# 单标的因子
# --------------------------------------------------------------------------- #
def compute(bars, ctx: Optional[Dict] = None, industry_pct: Optional[float] = None) -> Dict:
    """返回该标的的原始因子值（不是分数）。数据不足时给 None。"""
    ctx = ctx or {}
    days = daily_series(bars)
    out = {
        "vol_ratio": None,     # 量比
        "amount_pct": None,    # 成交额分位 0~1
        "ret5": None,
        "ret20": None,
        "rs5": None,
        "rs20": None,
        "industry_pct": industry_pct,
    }
    if len(days) < 7:
        return out

    today = days[-1]
    prev5 = days[-6:-1]
    avg_vol = sum(d["vol"] for d in prev5) / len(prev5) if prev5 else 0.0
    out["vol_ratio"] = round(_ratio(today["vol"], avg_vol) or 0.0, 2) if avg_vol else None

    window = days[-60:]
    if len(window) >= 20 and today["amount"]:
        vals = sorted(d["amount"] for d in window)
        n = len(vals)
        below = sum(1 for v in vals if v <= today["amount"])
        out["amount_pct"] = round(below / n, 3)

    for n in (5, 20):
        if len(days) > n and days[-1 - n]["close"]:
            out[f"ret{n}"] = round((today["close"] / days[-1 - n]["close"] - 1) * 100, 2)

    idx: Dict[str, float] = ctx.get("index") or {}
    if idx:
        d0 = today["date"]
        for n in (5, 20):
            if len(days) <= n:
                continue
            d1 = days[-1 - n]["date"]
            i0, i1 = idx.get(d0), idx.get(d1)
            if i0 and i1 and out[f"ret{n}"] is not None:
                idx_ret = (i0 / i1 - 1) * 100
                out[f"rs{n}"] = round(out[f"ret{n}"] - idx_ret, 2)
    return out


# --------------------------------------------------------------------------- #
# 行业强弱分位（全市场一次算出）
# --------------------------------------------------------------------------- #
def industry_percentiles(stocks: List[Dict]) -> Dict[str, float]:
    """行业当日平均涨幅 → 全行业排名分位（1 = 最强）。"""
    grp: Dict[str, List[float]] = {}
    for s in stocks:
        ind = s.get("industry")
        chg = s.get("change_pct")
        if ind and chg is not None:
            grp.setdefault(ind, []).append(float(chg))
    if not grp:
        return {}
    means = sorted(((k, sum(v) / len(v)) for k, v in grp.items()), key=lambda kv: kv[1])
    n = len(means)
    return {k: round((i + 1) / n, 3) for i, (k, _) in enumerate(means)}


# --------------------------------------------------------------------------- #
# 指数日线（全流程只请求一次）
# --------------------------------------------------------------------------- #
def fetch_index_daily(days: int = 120, tries: int = 3) -> Dict[str, float]:
    """沪深300 日线收盘价 {date: close}。失败返回空字典，调用方降级处理。"""
    end = dt.date.today()
    beg = end - dt.timedelta(days=days * 2)
    params = {
        "secid": "1." + INDEX_CODE,
        "fields1": "f1,f2,f3,f4,f5",
        "fields2": "f51,f53",
        "klt": "101",
        "fqt": "1",
        "beg": beg.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "lmt": "300",
    }
    for i in range(tries):
        try:
            r = requests.get(EM_KLINE, params=params, headers=UA, timeout=15)
            node = (r.json() or {}).get("data") or {}
            out: Dict[str, float] = {}
            for row in node.get("klines") or []:
                d, c = row.split(",")[:2]
                out[d] = float(c)
            if out:
                return out
        except Exception:  # noqa: BLE001
            pass
        if i + 1 < tries:
            import time
            time.sleep(1.5 * (i + 1))
    return {}
