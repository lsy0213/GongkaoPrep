// 软考 · 综合知识模考：按历年真题里各模块的题量比例组卷，严格计时，交卷出 75 分制的估分和走势（金线 45 分及格）
import { apiGet, apiPost, esc, MODULES, MODULE_SHORT, pickQuestions, scoreTrend, store } from "../../lib.js";
import { runQuiz } from "../../quiz.js";

const PAPERS = [
  { id: "mini", name: "迷你模考", n: 20, minutes: 40, hint: "20 题 · 40 分钟，每天一次找手感" },
  { id: "half", name: "半套模考", n: 38, minutes: 75, hint: "38 题 · 75 分钟，周末做" },
  { id: "full", name: "全真模考", n: 75, minutes: 150, hint: "75 题 · 150 分钟，和机考一样" },
];
const SRCS = [
  { id: "真题", name: "只出真题" },
  { id: "all", name: "真题 + 模拟卷" },
];

// 各模块出几题：按真题里的题量比例分配 n 题（英语固定 5 题 / 75）
function planOf(n, mods, realMods) {
  const en = MODULES.find((m) => /英语/.test(m));
  const enN = en ? Math.round((5 * n) / 75) : 0;
  const rest = MODULES.filter((m) => m !== en);
  const base = rest.reduce((a, m) => a + (realMods[m]?.total || 0), 0) || 1;
  let plan = rest.map((m) => ({ m, want: Math.round(((realMods[m]?.total || 0) / base) * (n - enN)) }));
  let diff = n - enN - plan.reduce((a, r) => a + r.want, 0);
  plan.sort((a, b) => (realMods[b.m]?.total || 0) - (realMods[a.m]?.total || 0));
  for (let i = 0; diff !== 0 && i < 50; i++) { const r = plan[i % plan.length]; r.want += diff > 0 ? 1 : (r.want > 0 ? -1 : 0); diff += diff > 0 ? -1 : 1; }
  if (en && enN) plan.push({ m: en, want: enN });
  plan = MODULES.map((m) => plan.find((r) => r.m === m)).filter(Boolean);
  return plan.map((r) => ({ ...r, got: Math.min(r.want, mods[r.m]?.total || 0) }));
}

export async function render(el) {
  const saved = store.get("rk-mock", {});
  let paper = PAPERS.find((p) => p.id === saved.paper) || PAPERS[0];
  let src = SRCS.find((s) => s.id === saved.src) || SRCS[0];
  const [mh, realSum] = await Promise.all([apiGet("/api/mock/history"), apiPost("/api/bank/summary", { src: "真题" })]);
  let cleanup = null;

  async function setup() {
    const sum = src.id === "真题" ? realSum : await apiPost("/api/bank/summary", { src: "all" });
    const plan = planOf(paper.n, sum.modules, realSum.modules);
    const n = plan.reduce((a, r) => a + r.got, 0);
    const items = mh.items;
    const last = items[items.length - 1];
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">综合知识</div><h1>限时模考</h1>
        <p>按历年真题里各模块的题量比例出题，优先出没做过的题，严格计时，交卷后出 75 分制估分。案例分析 + 综合知识的整场机考模拟在“机考模拟”里。</p></div>
        <a class="btn" href="#/real">做历年真题整卷</a></div>
      <div class="grid cols-main">
        <div class="card">
          <h3 style="margin-bottom:10px">试卷</h3>
          <div class="pick" id="papers">${PAPERS.map((p) => `<button data-p="${p.id}" class="${p.id === paper.id ? "active" : ""}">${p.name}<small>${p.hint}</small></button>`).join("")}</div>
          <h3 class="mt" style="margin-bottom:10px">题目来源</h3>
          <div class="seg" id="srcs">${SRCS.map((s) => `<button data-s="${s.id}" class="${s.id === src.id ? "active" : ""}">${s.name}</button>`).join("")}</div>
          <h3 class="mt" style="margin-bottom:6px">各模块题数</h3>
          <table class="tbl small"><tbody>${plan.map((r) => `<tr><td>${esc(r.m)}</td><td class="num">${r.got}${r.got < r.want ? ` <span class="muted">（题库只有 ${r.got}）</span>` : ""}</td></tr>`).join("")}</tbody></table>
          <div class="row mt"><button class="btn primary lg" id="go" ${n ? "" : "disabled"}>开始：${n} 题 · ${paper.minutes} 分钟</button></div>
        </div>
        <div class="card">
          <div class="card-head"><h3>估分走势</h3><span class="small muted">${items.length ? `共 ${items.length} 次 · 最近 ${last.score} / 75` : "还没有模考记录"}</span></div>
          ${items.length ? scoreTrend(items.map((x) => ({ v: x.score, tip: `${x.created_at.slice(5, 16)} ${x.title}：${x.score} / 75` })), { target: mh.target || 45, label: "及格", max: 75 })
            : `<p class="small muted">做完一次限时模考或真题整卷，这里画出每次的估分，金线是 45 分及格线。</p>`}
          ${items.length ? `<div class="small muted mt">${items.slice(-5).reverse().map((x) => `<div>${esc(x.created_at.slice(5, 16))} · ${esc(x.title)} · <b>${x.score}</b> / 75 · ${Object.entries(x.modules).map(([m, v]) => `${esc(MODULE_SHORT[m] || m)} ${v.ok}/${v.n}`).join(" ")}</div>`).join("")}</div>` : ""}
        </div>
      </div>`;
    el.querySelectorAll("#papers button").forEach((b) => (b.onclick = () => { paper = PAPERS.find((p) => p.id === b.dataset.p); store.set("rk-mock", { paper: paper.id, src: src.id }); setup(); }));
    el.querySelectorAll("#srcs button").forEach((b) => (b.onclick = () => { src = SRCS.find((s) => s.id === b.dataset.s); store.set("rk-mock", { paper: paper.id, src: src.id }); setup(); }));
    el.querySelector("#go").onclick = async () => {
      const ids = [];
      for (const r of plan) if (r.got) ids.push(...await pickQuestions({ module: r.m, count: r.want, order: "new", src: src.id }));
      cleanup = await runQuiz(el, { title: `${paper.name} · ${ids.length} 题`, ids, mode: "exam", timeLimit: paper.minutes * 60,
        onAgain: () => { location.hash = "#/mock"; location.reload(); } });
    };
  }
  await setup();
  return () => cleanup?.();
}
