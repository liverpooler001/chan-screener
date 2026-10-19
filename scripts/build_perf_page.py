# -*- coding: utf-8 -*-
"""由 data/perf/*.json 生成 perf.html（数据内联，无需 fetch，file:// 也能看）。

页面 = 一张跟踪曲线图 + 一张「名称 × 1~14 天后」明细表，不做汇总统计。
用法：
    python scripts/build_perf_page.py
"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERF = os.path.join(ROOT, "data", "perf")
OUT = os.path.join(ROOT, "perf.html")

MAX_DAYS = 10

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>选股跟踪 · 推荐后 1~10 个交易日</title>
<style>
:root{
  --bg:#f6f7f9;--surface:#fff;--border:#e6e8ec;--text:#1f2329;--text-2:#5a6270;--text-3:#8b94a3;
  --up:#d93a2b;--up-bg:rgba(217,58,43,.12);--down:#0f9d58;--down-bg:rgba(15,157,88,.12);
  --blue:#2b6ff0;--blue-soft:#eaf1fe;
  --radius:12px;--shadow:0 1px 3px rgba(16,24,40,.06),0 1px 2px rgba(16,24,40,.04);
  --mono:"SF Mono",ui-monospace,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1200px;margin:0 auto;padding:22px 18px 56px}
.top{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:14px}
h1{font-size:20px;margin:0 0 3px;letter-spacing:-.2px}
.sub{color:var(--text-3);font-size:12.5px;margin:0}
.back{font-size:12.5px;color:var(--text-2);text-decoration:none;border:1px solid var(--border);
  background:#fff;border-radius:8px;padding:6px 11px;white-space:nowrap;transition:.15s}
.back:hover{border-color:#c9ced6;color:var(--text)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:14px 16px 16px;margin-bottom:14px}
.card-head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:10px}
.card-head h2{font-size:14px;margin:0;font-weight:650;letter-spacing:.1px}
.hint{font-size:11.5px;color:var(--text-3)}
.tools{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
.glabel{font-size:11.5px;color:var(--text-3);margin-right:2px}
.seg{display:inline-flex;background:#eef0f3;border-radius:8px;padding:2px;gap:2px;flex-wrap:wrap}
.seg button{border:0;background:transparent;color:var(--text-2);font-size:12px;
  padding:4px 9px;border-radius:6px;cursor:pointer;font-family:inherit;transition:.15s;white-space:nowrap}
.seg button[aria-pressed="true"]{background:#fff;color:var(--text);font-weight:600;
  box-shadow:0 1px 2px rgba(16,24,40,.1)}
.chart-wrap{position:relative}
svg{display:block;width:100%;height:auto;overflow:visible}
.axis-t{fill:var(--text-3);font-size:10.5px;font-variant-numeric:tabular-nums}
.grid{stroke:#eef0f3;stroke-width:1}
.zero{stroke:#b9bfc9;stroke-width:1;stroke-dasharray:4 3}
.series{fill:none;stroke-width:1.9;stroke-linejoin:round;stroke-linecap:round;
  transition:opacity .15s,stroke-width .15s}
.series.dim{opacity:.10}
.dot{stroke:#fff;stroke-width:1.2}
.tip{position:absolute;pointer-events:none;background:rgba(31,35,41,.94);color:#fff;border-radius:8px;
  padding:8px 10px;font-size:11.5px;line-height:1.55;min-width:132px;opacity:0;transition:opacity .1s;
  z-index:5;box-shadow:0 6px 18px rgba(16,24,40,.22)}
.tip.on{opacity:1}
.tip .hd{font-size:11px;color:#c3c9d4;margin-bottom:4px}
.tip .r{display:flex;justify-content:space-between;gap:10px;font-variant-numeric:tabular-nums}
.tip .r i{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:5px}
.legend{display:flex;flex-wrap:wrap;gap:5px 8px;margin-top:10px}
.lg{display:inline-flex;align-items:center;gap:6px;font-size:12px;border:1px solid var(--border);
  border-radius:20px;padding:3px 10px 3px 7px;cursor:pointer;background:#fff;transition:.15s;user-select:none}
.lg:hover{border-color:#c9ced6}
.lg.off{opacity:.35}
.lg i{width:8px;height:8px;border-radius:2px;flex:0 0 auto}
.lg b{font-weight:600;font-variant-numeric:tabular-nums}
.tbl-scroll{overflow-x:auto;margin:0 -4px;padding:0 4px 2px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:12px;font-variant-numeric:tabular-nums}
th,td{padding:0;border-bottom:1px solid #f1f2f4;white-space:nowrap}
thead{position:sticky;top:0;z-index:3;background:#fff}
thead th{background:#fff;font-size:11px;color:var(--text-3);
  font-weight:600;padding:6px 0;text-align:center;border-bottom:1px solid var(--border)}
thead th.grp-h{color:var(--text-2);border-bottom:1px dashed #eceef2}
thead th.corner{text-align:left;padding-left:10px;position:sticky;left:0;z-index:4;
  border-right:1px solid #f4f5f7;font-size:12px;color:var(--text)}
td.nm{position:sticky;left:0;background:#fff;z-index:2;text-align:left;padding:7px 12px 7px 10px;
  border-right:1px solid #f4f5f7;min-width:170px;max-width:230px}
tbody tr:hover td{background:#fafbfd}
tbody tr:hover td.nm{background:#fafbfd}
.nm-l1{display:flex;align-items:center;gap:4px;line-height:1.35}
.nm-l2{font-size:10.5px;color:var(--text-3);line-height:1.3;font-family:var(--mono)}
.nm-n{font-size:13px;font-weight:600;color:var(--text)}
.chip{display:inline-block;font-size:9px;line-height:1;padding:2px 4px;border-radius:4px;
  background:#eef1f6;color:#5b6472;font-weight:600;letter-spacing:.3px}
.chip.etf{background:#eef3ff;color:#3d63c4}
.chip.stk{background:#f4f0fb;color:#7b4fc4}
td.v{text-align:right;padding:7px 9px;min-width:62px;font-size:11.5px;color:var(--text-3)}
td.v span{display:inline-block;padding:1.5px 5px;border-radius:4px;min-width:52px;text-align:right}
td.v .u{color:var(--up)}
td.v .d{color:var(--down)}
td.v .z{color:var(--text-3)}
tr.grp td{background:#f7f8fa;border-bottom:1px solid #e9ebef;padding:0}
tr.grp .gi{position:sticky;left:0;display:inline-flex;align-items:center;gap:8px;
  padding:6px 10px;font-size:11.5px;color:var(--text-2)}
tr.grp .gi b{font-size:12.5px;color:var(--text)}
tr.grp .gi .k{color:var(--text-3)}
.u{color:var(--up)}.d{color:var(--down)}.z{color:var(--text-3)}
.empty{padding:26px 10px;text-align:center;color:var(--text-3);font-size:12.5px}
.note{color:var(--text-3);font-size:11.5px;line-height:1.85;margin-top:4px}
.note b{color:var(--text-2);font-weight:600}
@media(max-width:640px){
  .wrap{padding:16px 12px 40px}
  h1{font-size:18px}
  .card{padding:12px 10px 12px}
  td.nm{min-width:120px;max-width:150px;padding:5px 7px}
  td.v{min-width:54px;padding:5px 5px}
  td.v span{min-width:46px;font-size:10.5px;padding:1px 3px}
}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div>
      <h1>选股跟踪表</h1>
      <p class="sub" id="sub"></p>
    </div>
    <a class="back" href="index.html">← 选股主页</a>
  </div>

  <section class="card">
    <div class="card-head">
      <h2>累计涨跌走势</h2>
      <div class="tools">
        <span class="glabel">推荐日</span>
        <div class="seg" id="dateSeg"></div>
        <div class="seg" id="typeSeg">
          <button data-type="all" aria-pressed="true">全部</button>
          <button data-type="stock" aria-pressed="false">股票</button>
          <button data-type="etf" aria-pressed="false">ETF</button>
        </div>
      </div>
    </div>
    <div class="chart-wrap" id="chartWrap">
      <svg id="chart" viewBox="0 0 1000 360" preserveAspectRatio="xMinYMin meet"></svg>
      <div class="tip" id="tip"></div>
    </div>
    <div class="legend" id="legend"></div>
  </section>

  <section class="card">
    <div class="card-head">
      <h2>跟踪明细</h2>
      <span class="hint">单位 %，红涨绿跌 · 「·」= 还没走到那天 · 推荐日列在名称下方</span>
    </div>
    <div class="tbl-scroll">
      <table id="tbl">
        <thead id="thead"></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
    <div class="note">
      <b>口径</b>：基准价为推荐日收盘价（前复权）；「n 天后」= 推荐日之后第 n 个交易日收盘相对基准价的涨跌；
      一组走满 10 个交易日（约两周）后自动从表里下线。每天取当日评分前 5 的股票和前 5 的 ETF 入表。
    </div>
  </section>
</div>

<script>
const DATA = __DATA__;
const DAYS = 10;
const COLORS = ['#2b6ff0','#e0742b','#7c3aed','#0f9d58','#d1477a','#b8860b','#0e8ea8','#8e5b3b','#4b6e9e','#a03fd0'];
const state = { date: DATA.dates[0], type: 'all', off: new Set() };

const pct = v => (v > 0 ? '+' : '') + v.toFixed(2) + '%';
const group = d => DATA.groups[d];
const rowsOf = d => (group(d) ? group(d).rows : []);
const shown = rows => rows.filter(r => state.type === 'all' || r.type === state.type);

/* ---------------- 顶部 ---------------- */
function buildSub() {
  const d = state.date, g = group(d) || { rows: [] };
  const done = Math.max(0, ...g.rows.map(r => r.done_days || 0));
  document.getElementById('sub').textContent =
    `数据截至 ${DATA.cutoff} · 共跟踪 ${DATA.dates.length} 个推荐日 · 曲线图为 ${d}（已走 ${done} 个交易日），明细表含全部标的`;
}

document.getElementById('dateSeg').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  state.date = b.dataset.date; state.off.clear(); renderChart(); buildSub();
});
document.getElementById('typeSeg').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  state.type = b.dataset.type;
  [...e.currentTarget.children].forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  state.off.clear(); renderChart();
});

/* ---------------- 折线图 ---------------- */
function renderChart() {
  const svg = document.getElementById('chart');
  const rows = shown(rowsOf(state.date));
  const W = 1000, H = 360, L = 46, R = 26, T = 16, B = 34;
  const iw = W - L - R, ih = H - T - B;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

  const series = rows.map((r, i) => {
    const pts = [{ d: 0, v: 0 }];
    for (let n = 1; n <= DAYS; n++) {
      const v = r.rets && r.rets[String(n)];
      if (v == null) break;
      pts.push({ d: n, v: v });
    }
    return { r, pts, color: COLORS[i % COLORS.length] };
  });

  const vals = series.flatMap(s => s.pts.map(p => p.v));
  vals.push(0);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.18, 1.2);
  lo -= pad; hi += pad;

  const x = d => L + d / DAYS * iw;
  const y = v => T + (hi - v) / (hi - lo) * ih;

  let out = '';
  // 横向网格
  const step = niceStep((hi - lo) / 4);
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    out += `<line class="grid" x1="${L}" y1="${y(v)}" x2="${L + iw}" y2="${y(v)}"/>`;
    out += `<text class="axis-t" x="${L - 8}" y="${y(v) + 3.5}" text-anchor="end">${v.toFixed(1)}%</text>`;
  }
  // 纵向刻度
  for (let d = 0; d <= DAYS; d++) {
    out += `<line class="grid" x1="${x(d)}" y1="${T}" x2="${x(d)}" y2="${T + ih}" opacity="${d % 2 ? 0 : 1}"/>`;
    out += `<text class="axis-t" x="${x(d)}" y="${T + ih + 16}" text-anchor="middle">${d}</text>`;
  }
  out += `<text class="axis-t" x="${L + iw / 2}" y="${T + ih + 30}" text-anchor="middle">推荐后第 n 个交易日（0 = 推荐日）</text>`;
  out += `<line class="zero" x1="${L}" y1="${y(0)}" x2="${L + iw}" y2="${y(0)}"/>`;
  out += `<line x1="${L + iw}" y1="${T}" x2="${L + iw}" y2="${T + ih}" stroke="#eef0f3"/>`;

  // 曲线
  const empty = series.every(s => s.pts.length < 2);
  if (empty) {
    out += `<text class="axis-t" x="${L + iw / 2}" y="${T + ih / 2}" text-anchor="middle"
      style="font-size:12px">这一天还没有走完一个交易日，收盘后再看</text>`;
  } else {
    series.forEach((s, i) => {
      if (s.pts.length < 2) return;
      const dim = state.off.has(s.r.code + s.r.name);
      const p = s.pts.map((pt, k) => `${k ? 'L' : 'M'}${x(pt.d).toFixed(1)},${y(pt.v).toFixed(1)}`).join(' ');
      out += `<path class="series${dim ? ' dim' : ''}" data-i="${i}" d="${p}" stroke="${s.color}"/>`;
      const last = s.pts[s.pts.length - 1];
      out += `<circle class="dot" data-i="${i}" cx="${x(last.d)}" cy="${y(last.v)}" r="3.2" fill="${s.color}"/>`;
    });
  }
  svg.innerHTML = out;

  // 图例
  document.getElementById('legend').innerHTML = series.map((s, i) => {
    const last = s.pts[s.pts.length - 1];
    const key = s.r.code + s.r.name;
    return `<span class="lg${state.off.has(key) ? ' off' : ''}" data-key="${key}" data-i="${i}">
      <i style="background:${s.color}"></i>${s.r.name}
      <b class="${last && last.v > 0 ? 'u' : last && last.v < 0 ? 'd' : 'z'}"
         style="${last ? '' : 'color:#8b94a3'}">${last && last.d > 0 ? pct(last.v) : '待更新'}</b></span>`;
  }).join('') || '<span class="hint">该日没有可展示的标的</span>';

  [...document.querySelectorAll('.lg')].forEach(el => {
    el.addEventListener('click', () => {
      const k = el.dataset.key;
      state.off.has(k) ? state.off.delete(k) : state.off.add(k);
      renderChart();
    });
  });
  bindHover(series, x, y, L, iw);
}

function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 0.1))));
  const n = raw / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

function bindHover(series, x, y, L, iw) {
  const svg = document.getElementById('chart');
  const tip = document.getElementById('tip');
  const wrap = document.getElementById('chartWrap');

  svg.onmousemove = ev => {
    const box = svg.getBoundingClientRect();
    const W = 1000;
    const px = (ev.clientX - box.left) / box.width * W;
    let d = Math.round((px - L) / iw * DAYS);
    d = Math.max(0, Math.min(DAYS, d));

    const items = series
      .map(s => {
        const pt = s.pts.find(p => p.d === d);
        return pt ? { name: s.r.name, v: pt.v, c: s.color } : null;
      })
      .filter(Boolean)
      .sort((a, b) => b.v - a.v);

    // 竖直参考线
    const old = svg.querySelector('.guide');
    if (old) old.remove();
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    g.setAttribute('class', 'guide');
    g.setAttribute('x1', x(d)); g.setAttribute('x2', x(d));
    g.setAttribute('y1', 16); g.setAttribute('y2', 326);
    g.setAttribute('stroke', '#c9ced6'); g.setAttribute('stroke-dasharray', '3 3');
    svg.appendChild(g);

    if (!items.length) { tip.classList.remove('on'); return; }
    tip.innerHTML = `<div class="hd">第 ${d} 个交易日${d === 0 ? '（推荐日）' : ''}</div>` +
      items.map(i => `<div class="r"><span><i style="background:${i.c}"></i>${i.name}</span>
        <span style="color:${i.v > 0 ? '#ff8f83' : i.v < 0 ? '#63d29b' : '#c3c9d4'}">${pct(i.v)}</span></div>`).join('');
    tip.classList.add('on');

    const left = ev.clientX - box.left;
    const tw = tip.offsetWidth;
    tip.style.left = (left + 14 + tw > box.width ? left - tw - 14 : left + 14) + 'px';
    tip.style.top = Math.min(ev.clientY - box.top + 12, box.height - tip.offsetHeight - 6) + 'px';
  };
  svg.onmouseleave = () => {
    document.getElementById('tip').classList.remove('on');
    const old = svg.querySelector('.guide'); if (old) old.remove();
  };
}

/* ---------------- 明细表 ---------------- */
function head() {
  const days = Array.from({ length: DAYS }, (_, i) => `<th>${i + 1}个交易日</th>`).join('');
  document.getElementById('thead').innerHTML =
    `<tr><th class="nm corner" rowspan="2">个股名称</th>
       <th class="grp-h" colspan="${DAYS}">推荐后涨跌（单位 %）</th></tr>
     <tr>${days}</tr>`;
}

function cell(v) {
  if (v == null) return '<td class="v"><span class="z">·</span></td>';
  const a = Math.min(Math.abs(v) / 8, 1);
  const cls = v > 0 ? 'u' : v < 0 ? 'd' : 'z';
  const bg = v === 0 ? '' : `background:rgba(${v > 0 ? '217,58,43' : '15,157,88'},${(0.05 + a * 0.13).toFixed(3)})`;
  return `<td class="v"><span class="${cls}" style="${bg}">${v > 0 ? '+' : ''}${v.toFixed(2)}</span></td>`;
}

function renderTable() {
  const rows = [];
  DATA.dates.forEach(d => rowsOf(d).forEach(r => {
    if (state.type !== 'all' && r.type !== state.type) return;
    rows.push({ ...r, base_date: d });
  }));

  document.getElementById('tbody').innerHTML = rows.length ? rows.map(r => {
    let tds = '';
    for (let n = 1; n <= DAYS; n++) tds += cell(r.rets ? r.rets[String(n)] : null);
    const chip = r.type === 'etf' ? '<span class="chip etf">ETF</span>' : '';
    const meta = [r.code, r.base_date ? r.base_date.slice(5) + ' 推荐' : '', r.score ? r.score + '分' : '']
      .filter(Boolean).join(' · ');
    return `<tr><td class="nm">
      <div class="nm-l1"><span class="nm-n">${r.name}</span>${chip}</div>
      <div class="nm-l2">${meta}</div></td>${tds}</tr>`;
  }).join('') : `<tr><td class="empty" colspan="${DAYS + 1}">还没有可展示的数据</td></tr>`;
}

/* ---------------- 渲染 ---------------- */
function buildDateSeg() {
  document.getElementById('dateSeg').innerHTML = DATA.dates
    .map(d => `<button data-date="${d}" aria-pressed="${d === state.date}">${d.slice(5)}</button>`).join('');
  const b = document.querySelector('#dateSeg button[aria-pressed="true"]');
  if (b) b.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

function render() { head(); buildSub(); renderChart(); renderTable(); }

// 默认看最新一组里「已走完至少 1 天」的那天，这样一进页面就有曲线
(function initDate() {
  for (const d of DATA.dates) {
    if (rowsOf(d).some(r => r.done_days > 0)) { state.date = d; break; }
  }
})();
buildDateSeg();
render();
</script>
</body>
</html>
"""


def main():
    idx_path = os.path.join(PERF, "index.json")
    with io.open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)
    dates = [d for d in idx.get("dates", []) if os.path.exists(os.path.join(PERF, d + ".json"))]
    if not dates:
        raise SystemExit("data/perf 下没有跟踪数据，先跑 scripts/backtest.py")

    groups = {}
    for d in dates:
        with io.open(os.path.join(PERF, d + ".json"), encoding="utf-8") as f:
            p = json.load(f)
        groups[d] = {"base_date": d, "rows": p.get("rows", [])}

    payload = {
        "dates": dates,
        "groups": groups,
        "cutoff": idx.get("cutoff", dates[0]),
        "updated_at": idx.get("updated_at", ""),
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print("生成 %s（%d 个推荐日，%.1f KB）" % (OUT, len(dates), len(html.encode()) / 1024))


if __name__ == "__main__":
    main()
