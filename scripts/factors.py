# -*- coding: utf-8 -*-
"""多因子原始值：P0（量比 / 成交额分位 / RS / 行业强弱）+ P1（主力资金流）。

设计原则：**不新增逐标的的网络请求**。
量比、成交额分位、涨跌幅都可以从「已经下载好的 30 分钟 K 线」按日聚合得到；
沪深300 指数日线 1 次请求；主力资金流随快照字段一起来，板块资金流 1 次请求。

口径：
    量比      = 今日成交量 / 前 5 个交易日均量
    成交额分位 = 今日成交额在近 60 个交易日中的分位（1 = 最大）
    RS(n)     = 个股 n 日涨幅 − 沪深300 n 日涨幅
    行业分位   = 所属行业当日平均涨幅，在所有行业中的分位（1 = 最强）
    主力净占比 = 东财「主力（超大单+大单）」净流入 / 成交额（快照 f184）
    5日主力   = 近 5 日主力净流入占比（快照 f165）
    行业资金分位 = 所属行业板块主力净占比排名（1 = 最强）
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
        "dev_ma20": None,      # 收盘价偏离 20 日均线（%），仅记录，不参与评分/过滤
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

    if len(days) >= 20:
        ma20 = sum(d["close"] for d in days[-20:]) / 20.0
        if ma20:
            out["dev_ma20"] = round((today["close"] / ma20 - 1) * 100, 2)

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
# 行业板块资金流（P1，全流程只请求一次，板块级不是个股级）
# --------------------------------------------------------------------------- #
EM_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"
_SECTOR_FS = "m:90 t:2"          # 东财行业板块（含一/二/三级，约 500 个）
_SECTOR_FIELDS = "f12,f14,f3,f62,f184"


def fetch_industry_fund(tries: int = 3, max_pages: int = 8) -> Dict[str, Dict]:
    """行业板块当日主力资金流 → {行业名: {net: 净额(元), pct: 净占比(%), chg: 涨幅}}。

    用板块接口一次拿全（不是逐行业请求），失败返回空字典由调用方按中性处理。
    """
    import time as _t

    for i in range(tries):
        out: Dict[str, Dict] = {}
        try:
            for pn in range(1, max_pages + 1):
                params = {
                    "pn": pn, "pz": 100, "po": 1, "np": 1,
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": 2, "invt": 2, "fid": "f62",
                    "fs": _SECTOR_FS, "fields": _SECTOR_FIELDS,
                }
                r = requests.get(EM_CLIST, params=params, headers=UA, timeout=15)
                diff = ((r.json() or {}).get("data") or {}).get("diff") or []
                if not diff:
                    break
                for x in diff:
                    name = x.get("f14")
                    if not name:
                        continue
                    out[name] = {
                        "net": x.get("f62"),
                        "pct": x.get("f184"),
                        "chg": x.get("f3"),
                    }
                if len(diff) < 100:
                    break
            if out:
                return out
        except Exception:  # noqa: BLE001
            pass
        if i + 1 < tries:
            _t.sleep(1.5 * (i + 1))
    return {}


def industry_fund_percentiles(stocks: List[Dict], board_fund: Dict[str, Dict]) -> Dict[str, float]:
    """在「本池出现过的行业」范围内按主力净占比排名，1 = 最强。

    只在本池行业内比较（而不是在全市场 500 个板块里比），避免分级行业
    （如「半导体设备」与「半导体」）互相稀释。
    """
    vals = []
    for ind in {s.get("industry") for s in stocks if s.get("industry")}:
        node = board_fund.get(ind) or {}
        v = node.get("pct")
        if v is None:
            v = node.get("net")
        if v is not None:
            vals.append((ind, float(v)))
    if not vals:
        return {}
    vals.sort(key=lambda kv: kv[1])
    n = len(vals)
    return {k: round((i + 1) / n, 3) for i, (k, _) in enumerate(vals)}


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
