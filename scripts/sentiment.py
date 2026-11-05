# -*- coding: utf-8 -*-
"""P2 情绪择时：全市场赚钱效应温度计 → 进攻 / 中性 / 收缩。

数据源（东财涨停板专题，共 3~4 次请求，均支持历史日期）：
    getTopicZTPool  涨停池 → 涨停家数、连板高度(lbc)、封板资金
    getTopicZBPool  炸板池 → 炸板家数 → 封板率 = 涨停 /（涨停 + 炸板）
    getTopicDTPool  跌停池 → 跌停家数
另用「上一个交易日的涨停池代码 + 今日快照涨跌幅」算昨日涨停今日溢价
（接力资金的赚钱效应，比涨停家数更贴近次日）。

打分（约 -6 ~ +7）：
    涨停家数      ≥80 +2 / ≥50 +1 / <25 -2 / <40 -1
    跌停家数      ≤3 +1 / ≥8 -1 / ≥20 -2
    封板率        ≥75% +1 / <60% -1
    昨日涨停溢价   ≥2% +2 / ≥0 +1 / <0 -1 / ≤-3% -2
    沪深300 20日线 上方 +1 / 下方 -1
    连板高度      ≥5 +1 / ≤2 -1
    ≥4 → 进攻；≤-3 → 收缩；其余中性。

结果落 `data/sentiment/<date>.json`，并内联进 `data/latest.json` 的 `sentiment` 字段，
页面直接读取，不额外发请求。
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Dict, List, Optional

import requests

EM_POOL = "https://push2ex.eastmoney.com/getTopic{kind}Pool"
UT = "7eea3edcaed734bea9cbfc24409ed989"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

LEVEL_CN = {"attack": "进攻", "neutral": "中性", "shrink": "收缩"}


# --------------------------------------------------------------------------- #
# 涨停 / 炸板 / 跌停池
# --------------------------------------------------------------------------- #
def _fetch_pool(kind: str, date: str, tries: int = 3) -> Dict:
    """kind: ZT（涨停）/ ZB（炸板）/ DT（跌停）。date: YYYYMMDD。"""
    import time as _t

    params = {
        "ut": UT, "dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 500,
        "sort": "fbt:asc", "date": date,
    }
    for i in range(tries):
        try:
            r = requests.get(EM_POOL.format(kind=kind), params=params, headers=UA, timeout=15)
            data = (r.json() or {}).get("data")
            if isinstance(data, dict):
                return data
        except Exception:  # noqa: BLE001
            pass
        if i + 1 < tries:
            _t.sleep(1.2 * (i + 1))
    return {}


def _count(node: Dict) -> int:
    if not node:
        return 0
    try:
        return int(node.get("tc") or 0)
    except (TypeError, ValueError):
        return len(node.get("pool") or [])


def prev_trading_day(date: str, max_back: int = 10) -> Optional[str]:
    """往前找一个「有涨停」的交易日（周末/节假日涨停池为 0）。"""
    d = dt.datetime.strptime(date, "%Y-%m-%d").date()
    for i in range(1, max_back + 1):
        p = d - dt.timedelta(days=i)
        if p.weekday() >= 5:      # 周六日直接跳过，省两次请求
            continue
        node = _fetch_pool("ZT", p.strftime("%Y%m%d"))
        if _count(node) > 0:
            return p.strftime("%Y-%m-%d")
    return None


# --------------------------------------------------------------------------- #
# 情绪打分
# --------------------------------------------------------------------------- #
def _score(zt: int, dt_n: int, seal: Optional[float], prem: Optional[float],
           above: Optional[bool], lbc: Optional[int]) -> int:
    s = 0
    s += 2 if zt >= 80 else 1 if zt >= 50 else -2 if zt < 25 else -1 if zt < 40 else 0
    s += 1 if dt_n <= 3 else -1 if dt_n >= 8 else 0
    s += -2 if dt_n >= 20 else 0
    if seal is not None:
        s += 1 if seal >= 0.75 else -1 if seal < 0.60 else 0
    if prem is not None:
        s += 2 if prem >= 2 else 1 if prem >= 0 else -2 if prem <= -3 else -1
    if above is not None:
        s += 1 if above else -1
    if lbc is not None:
        s += 1 if lbc >= 5 else -1 if lbc <= 2 else 0
    return s


def _level(score: int) -> str:
    if score >= 4:
        return "attack"
    if score <= -3:
        return "shrink"
    return "neutral"


ADVICE = {
    "attack": "赚钱效应回暖：可按评分正常排序参与，优先双级别共振 + 资金流入的标的。",
    "neutral": "情绪一般：只做高评分（≥75）且双级别共振的标的，控制单笔仓位，不追高。",
    "shrink": "亏钱效应明显：建议轻仓或空仓观望，等涨停家数回升、昨日涨停转正再考虑进场。",
}


def compute(trade_date: str, index_daily: Optional[Dict[str, float]] = None,
            chg_by_code: Optional[Dict[str, Optional[float]]] = None) -> Dict:
    """返回 {date, level, level_cn, score, metrics, advice, missing}。"""
    d = trade_date.replace("-", "")
    zt_node = _fetch_pool("ZT", d)
    zb_node = _fetch_pool("ZB", d)
    dt_node = _fetch_pool("DT", d)

    zt = _count(zt_node)
    broken = _count(zb_node)
    dt_n = _count(dt_node)

    pool = zt_node.get("pool") or []
    lbc = max((int(x.get("lbc") or 1) for x in pool), default=None)

    seal = None
    if zt + broken > 0:
        seal = round(zt / float(zt + broken), 3)

    missing: List[str] = []
    if zt == 0:
        missing.append("涨停池")

    # 昨日涨停今日溢价
    prem = None
    pdate = prev_trading_day(trade_date) if chg_by_code else None
    if pdate:
        pcodes = [str(x.get("c") or "") for x in (_fetch_pool("ZT", pdate.replace("-", "")).get("pool") or [])]
        vals = []
        for c in pcodes:
            v = (chg_by_code or {}).get(c)
            if v is not None:
                vals.append(float(v))
        if vals:
            prem = round(sum(vals) / len(vals), 2)
    if prem is None and chg_by_code:
        missing.append("昨日涨停溢价")

    # 沪深300 20 日线
    above, idx_dev = None, None
    if index_daily:
        keys = sorted(k for k in index_daily if k <= trade_date)
        if len(keys) >= 20:
            closes = [index_daily[k] for k in keys[-20:]]
            ma20 = sum(closes) / len(closes)
            last = closes[-1]
            if ma20:
                above = last > ma20
                idx_dev = round((last / ma20 - 1) * 100, 2)
    if above is None:
        missing.append("指数20日线")

    score = _score(zt, dt_n, seal, prem, above, lbc)
    level = _level(score)

    return {
        "date": trade_date,
        "level": level,
        "level_cn": LEVEL_CN[level],
        "score": score,
        "advice": ADVICE[level],
        "metrics": {
            "zt": zt,
            "dt": dt_n,
            "broken": broken,
            "seal": seal,
            "max_lbc": lbc,
            "prev_premium": prem,
            "prev_date": pdate,
            "index_above_ma20": above,
            "index_dev": idx_dev,
        },
        "missing": missing,
    }


def save(data_dir: str, sent: Dict) -> None:
    """写 data/sentiment/<date>.json（保留历史，供后续回看情绪与收益的关系）。"""
    if not sent or not sent.get("date"):
        return
    root = os.path.join(data_dir, "sentiment")
    os.makedirs(root, exist_ok=True)
    p = os.path.join(root, "%s.json" % sent["date"])
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(sent, f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)
