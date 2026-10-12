/* 用真实 latest.json 验证前端筛选逻辑（vm 里加载 app.js，注入 stub DOM） */
const fs = require('fs');
const vm = require('vm');

const ROOT = 'C:/Users/cz/WorkBuddy/2026-10-08-10-16-42/chan-screener';
const appJs = fs.readFileSync(ROOT + '/assets/app.js', 'utf8');
const payload = JSON.parse(fs.readFileSync(ROOT + '/data/latest.json', 'utf8'));

function stubEl() {
  return {
    children: [], hidden: false, textContent: '', innerHTML: '', dataset: {},
    addEventListener() {}, setAttribute() {}, classList: { add() {}, remove() {} },
    querySelectorAll: () => [],
  };
}

const tests = `
(function runTests(){
  const P = __payload;
  const all = P.signals || [];
  const out = [];
  const check = (name, got, want) => out.push({ name, got, want, ok: got === want });
  const setOf = (arr) => new Set(arr);
  const apply = () => filtered().length;

  state.payload = P;

  // 期望值（用原始数据直接算，不依赖 app.js 的内部实现）
  const cnt = (fn) => all.filter(fn).length;

  // 1) 只看 30 分三买：30 分行只勾三买，5 分行全空 —— 两种模式都应等价
  state.k30 = setOf(['3']); state.k5 = setOf([]);
  state.mode = 'and';
  check('只看30分三买 共振模式', apply(), cnt((s) => s.m30 && s.m30.kind === '3'));
  state.mode = 'or';
  check('只看30分三买 任一模式', apply(), cnt((s) => s.m30 && s.m30.kind === '3'));

  // 2) 30 分三买 且 5 分一买 共振
  state.k30 = setOf(['3']); state.k5 = setOf(['1']); state.mode = 'and';
  check('30分三买 且 5分一买(共振)', apply(),
        cnt((s) => s.m30 && s.m30.kind === '3' && s.m5 && s.m5.kind === '1'));

  // 3) 只看 5 分一买：30 分行全空
  state.k30 = setOf([]); state.k5 = setOf(['1']); state.mode = 'and';
  check('只看5分一买(共振模式)', apply(), cnt((s) => s.m5 && s.m5.kind === '1'));
  state.mode = 'or';
  check('只看5分一买(任一模式)', apply(), cnt((s) => s.m5 && s.m5.kind === '1'));

  // 4) 任一模式：30分三买 或 5分一买
  state.k30 = setOf(['3']); state.k5 = setOf(['1']); state.mode = 'or';
  check('30分三买 或 5分一买(任一)', apply(),
        cnt((s) => (s.m30 && s.m30.kind === '3') || (s.m5 && s.m5.kind === '1')));

  // 5) 两行都不勾 = 不设条件，显示全部
  state.k30 = setOf([]); state.k5 = setOf([]);
  check('两行全空=显示全部(共振)', apply(), all.length);
  state.mode = 'or';
  check('两行全空=显示全部(任一)', apply(), all.length);

  // 6) 与旧版行为对齐：kinds(2/3) 共享 + 共振 = m30 且 m5 且 kind∈{2,3}
  state.k30 = setOf(['2','3']); state.k5 = setOf(['2','3']); state.mode = 'and';
  check('回归:旧版共振(2/3买)', apply(),
        cnt((s) => s.m30 && s.m5 && ['2','3'].includes(s.m30.kind) && ['2','3'].includes(s.m5.kind)));

  // 7) 品种过滤（注意：此时买点条件也在生效，期望值必须带上同样的买点条件）
  const condNow = (s) => s.m30 && s.m5 &&
      ['2','3'].includes(s.m30.kind) && ['1','2','3'].includes(s.m5.kind);
  state.k30 = setOf(['2','3']); state.k5 = setOf(['1','2','3']); state.mode = 'and'; state.type = 'etf';
  check('仅ETF', apply(), all.filter((s) => condNow(s) && s.type === 'etf').length);
  state.type = 'stock';
  check('仅股票', apply(), all.filter((s) => condNow(s) && s.type === 'stock').length);
  state.type = 'all';

  // 8) 关键词
  state.keyword = all.length ? all[0].code : 'X';
  check('关键词搜索', apply(),
        all.filter((s) => condNow(s) && s.code.includes(state.keyword.toUpperCase())).length);
  state.keyword = '';

  // 9) 条件文案
  state.k30 = setOf(['3']); state.k5 = setOf([]); state.mode = 'and';
  out.push({ name: '副标题文案', got: conditionText(), want: '30分 三买 共振 5分 不限', ok: /30分 三买 共振 5分 不限/.test(conditionText()) });

  // 10) 徽标映射
  const b = bpBadge({ kind: '1', label: '1买', price: 12.345 }, '5分');
  out.push({ name: '一买徽标', got: b, want: 'b1 + 一买', ok: b.includes('bp b1') && b.includes('一买') });

  __out = out;
})();
`;

const sandbox = {
  __payload: payload, __out: null, console,
  document: { querySelector: () => stubEl(), addEventListener() {} },
  location: { protocol: 'http:' },
  fetch: () => Promise.reject(new Error('no network in test')),
  setTimeout, clearTimeout, Promise, Array, Set, Map, Number, String, Math, JSON, Object, RegExp,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(appJs + tests, sandbox, { filename: 'app.js' });

const rows = sandbox.__out || [];
let pass = 0;
console.log('数据: 命中 ' + payload.signals.length + ' 条  (交易日 ' + payload.trade_date + ')');
console.log('-'.repeat(74));
for (const r of rows) {
  if (r.ok) pass++;
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name.padEnd(30)} got=${String(r.got).slice(0, 60)}`);
}
console.log('-'.repeat(74));
console.log(`结果: ${pass}/${rows.length} 通过`);
process.exit(pass === rows.length ? 0 : 1);
