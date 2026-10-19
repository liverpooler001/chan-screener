# -*- coding: utf-8 -*-
"""选股跟踪表：每个推荐日记录「评分前 N 的股票」与「评分前 N 的 ETF」，
跟踪其后第 1~14 个交易日的累计涨跌。

口径：
  - 基准价 = 推荐日收盘价（前复权）
  - 「n 天后」= 推荐日之后第 n 个交易日的收盘价，相对基准价的涨跌幅
  - 一行的 14 个格子都走完（已跟踪 > 14 个交易日）后，自动从跟踪表下线

数据源：腾讯前复权日线 web.ifzq.gtimg.cn
输出：data/perf/<推荐日>.json、data/perf/index.json

用法：
    python scripts/backtest.py              # 重建全部
    python scripts/backtest.py --days 2026-10-16 --per-type 5
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datasource import to_tx_symbol  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
HIST = os.path.join(DATA, "history")
PERF = os.path.join(DATA, "perf")
TX_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

MAX_DAYS = 14          # 跟踪 1~14 个交易日，超过即下线
PER_TYPE = 5           # 每天股票 / ETF 各取评分前 N


def log(msg):
    print(msg, flush=True)


def last_complete_day():
    """今天 15:05 之前，当日 K 线不算完成。"""
    now = dt.datetime.now()
    if now.hour * 60 + now.minute < 15 * 60 + 5:
        return (now - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


def fetch_day_bars(symbol, start, end, tries=3):
    """返回 [(date, close)]，前复权。"""
    for i in range(tries):
        try:
            r = requests.get(
                TX_URL,
                params={"param": f"{symbol},day,{start},{end},400,qfq"},
                timeout=15,
            )
            j = r.json()
            node = (j.get("data") or {}).get(symbol) or {}
            rows = node.get("qfqday") or node.get("day") or []
            out = []
            for b in rows:
                try:
                    out.append((b[0], float(b[2])))
                except (IndexError, ValueError):
                    continue
            if out:
                return out
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.6 * (i + 1))
    return []


def pct(a, b):
    return round((b / a - 1) * 100, 2) if a else None


def pick_rows(hist, per_type):
    """评分前 N 的股票 + 评分前 N 的 ETF。"""
    sigs = hist.get("signals") or []
    out = []
    for t in ("stock", "etf"):
        group = [s for s in sigs if s.get("type") == t]
        group.sort(key=lambda s: (-(s.get("score") or 0), s.get("code") or ""))
        out.extend(group[:per_type])
    return out


def build_one(day, cutoff, start_all, cache, per_type):
    path = os.path.join(HIST, f"{day}.json")
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8") as f:
        hist = json.load(f)

    picks = pick_rows(hist, per_type)
    if not picks:
        return None

    rows = []
    for s in picks:
        code = s["code"]
        symbol = to_tx_symbol(code)
        if symbol not in cache:
            cache[symbol] = [b for b in fetch_day_bars(symbol, start_all, cutoff) if b[0] <= cutoff]
        bars = cache[symbol]
        row = {
            "code": code,
            "name": s.get("name"),
            "type": s.get("type"),
            "score": s.get("score"),
            "tags": s.get("tags") or [],
            "base_price": None,
            "rets": {},
            "done_days": 0,
        }
        if not bars:
            row["error"] = "无日线"
            rows.append(row)
            continue

        i0 = next((i for i, b in enumerate(bars) if b[0] == day), None)
        if i0 is None:      # 推荐日停牌：退化为之前最近一根
            prior = [i for i, b in enumerate(bars) if b[0] < day]
            i0 = prior[-1] if prior else None
        if i0 is None:
            row["error"] = "推荐日无数据"
            rows.append(row)
            continue

        base = bars[i0][1]
        row["base_price"] = round(base, 3)
        for n in range(1, MAX_DAYS + 1):
            k = i0 + n
            if k < len(bars):
                row["rets"][str(n)] = pct(base, bars[k][1])
        row["done_days"] = min(len(bars) - 1 - i0, MAX_DAYS)
        rows.append(row)

    return {
        "base_date": day,
        "cutoff": cutoff,
        "per_type": per_type,
        "max_days": MAX_DAYS,
        "rows": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="", help="逗号分隔的推荐日，留空=全部历史")
    ap.add_argument("--per-type", type=int, default=PER_TYPE, help="每天股票/ETF 各取前 N")
    args = ap.parse_args()

    cutoff = last_complete_day()
    log("已完成交易日截止: %s" % cutoff)

    days = [d.strip() for d in args.days.split(",") if d.strip()]
    if not days:
        days = sorted(f[:-5] for f in os.listdir(HIST) if f.endswith(".json"))
    days = [d for d in days if d <= cutoff]
    if not days:
        raise SystemExit("没有可回测的推荐日")

    start_all = (dt.date.fromisoformat(days[0]) - dt.timedelta(days=10)).isoformat()
    cache = {}
    os.makedirs(PERF, exist_ok=True)

    active, dropped = [], []
    for d in days:
        p = build_one(d, cutoff, start_all, cache, args.per_type)
        if not p:
            continue
        done = max((r["done_days"] for r in p["rows"]), default=0)
        if done > MAX_DAYS:                      # 两周已走完，自动下线
            dropped.append(d)
            stale = os.path.join(PERF, f"{d}.json")
            if os.path.exists(stale):
                os.remove(stale)
            log("下线 %s（已跟踪 %d 个交易日）" % (d, done))
            continue
        out = os.path.join(PERF, f"{d}.json")
        with io.open(out, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, separators=(",", ":"))
        active.append(d)
        log("%s  股票 %d / ETF %d  已跟踪 %d 天" % (
            d,
            sum(1 for r in p["rows"] if r["type"] == "stock"),
            sum(1 for r in p["rows"] if r["type"] == "etf"),
            done))

    # 清掉已不在历史里的旧文件
    keep = set(active)
    for fn in os.listdir(PERF):
        if fn.endswith(".json") and fn != "index.json" and fn[:-5] not in keep:
            os.remove(os.path.join(PERF, fn))

    idx_path = os.path.join(PERF, "index.json")
    with io.open(idx_path, "w", encoding="utf-8") as f:
        json.dump({
            "dates": sorted(active, reverse=True),
            "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cutoff": cutoff,
            "per_type": args.per_type,
            "max_days": MAX_DAYS,
        }, f, ensure_ascii=False, indent=1)

    log("\n在跟踪 %d 个推荐日，下线 %d 个 -> %s" % (len(active), len(dropped), PERF))


if __name__ == "__main__":
    main()
