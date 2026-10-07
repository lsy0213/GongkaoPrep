import { apiGet, apiPost, bankMeta, esc, MODULES, pickQuestions } from "../lib.js";
import { runQuiz } from "../quiz.js";

const REAL = {
  "地市级": { "政治理论": 20, "常识判断": 15, "言语理解与表达": 30, "数量关系": 10, "判断推理": 35, "资料分析": 20 },
  "副省级": { "政治理论": 20, "常识判断": 15, "言语理解与表达": 30, "数量关系": 15, "判断推理": 35, "资料分析": 20 },
};
const PAPERS = [
  { id: "mini", name: "迷你模考", ratio: 0.3, hint: "约 40 题，适合每天或隔天做一次" },
  { id: "half", name: "半套模考", ratio: 0.5, hint: "约 65 题，周末做" },
  { id: "full", name: "全真结构", ratio: 1, hint: "按真实题量和 120 分钟，题库不够时用现有题" },
];

// 各模块要出的题数（资料分析按 5 题一篇材料取整）
function planOf(level, ratio, mods) {
  const real = REAL[level] || REAL["地市级"];
  const realTotal = Object.values(real).reduce((a, x) => a + x, 0);
  const plan = MODULES.map((m) => {
    let want = Math.max(m === "资料分析" ? 5 : 2, Math.round(real[m] * ratio));
    if (m === "资料分析") want = Math.max(5, Math.round(want / 5) * 5);
    return { m, want, got: Math.min(want, mods[m]?.total || 0) };
  });
  const n = plan.reduce((a, r) => a + r.got, 0);
  return { plan, n, minutes: Math.max(10, Math.round((120 * n) / realTotal)) };
}

async function compose(plan) {
  const ids = [];
  for (const r of plan) {
    if (!r.got) continue;
    ids.push(...await pickQuestions({ module: r.m, count: r.want, order: "new" }));
  }
  return ids;
}

export async function render(el) {
  const [meta, settings, st, sum] = await Promise.all([bankMeta(), apiGet("/api/settings"), apiGet("/api/stats"),
    apiPost("/api/bank/summary", {})]);
  let paper = PAPERS[0];
  let level = settings.paper_level || "地市级";
  let cleanup = null;
  const history = st.sessions.filter((s) => s.mode === "exam" && s.title.startsWith("模考"));

  function setup() {
    const preview = planOf(level, paper.ratio, sum.modules);
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">模拟考试</div><h1>行测限时模考</h1>
        <p>按真实考试的模块顺序和题量比例出题，严格计时，交卷后出成绩和各模块用时。</p></div>
        ${meta.papers.length ? `<a class="btn" href="#/real">做历年真题整卷</a>` : ""}</div>
      <div class="grid cols-main">
        <div class="card">
          <h3 style="margin-bottom:10px">试卷</h3>
          <div class="pick" id="papers">${PAPERS.map((p) => `<button data-p="${p.id}" class="${p.id === paper.id ? "active" : ""}">${p.name}<small>${p.hint}</small></button>`).join("")}</div>
          <h3 class="mt" style="margin-bottom:10px">卷别</h3>
          <div class="seg" id="levels">${Object.keys(REAL).map((l) => `<button data-l="${l}" class="${l === level ? "active" : ""}">${l}</button>`).join("")}</div>
          <div class="table-wrap mt"><table class="tbl"><thead><tr><th>模块</th><th class="n">本卷题数</th><th class="n">真实考试</th></tr></thead><tbody>
            ${preview.plan.map((r) => `<tr><td>${esc(r.m)}</td><td class="n">${r.got}${r.got < r.want ? ` <span class="small muted">（题库只有这些）</span>` : ""}</td><td class="n">${REAL[level][r.m]}</td></tr>`).join("")}
            <tr><td><b>合计</b></td><td class="n"><b>${preview.n}</b></td><td class="n">${Object.values(REAL[level]).reduce((a, x) => a + x, 0)}</td></tr>
          </tbody></table></div>
          <div class="row mt"><button class="btn primary lg" id="start">开始模考（${preview.minutes} 分钟）</button>
            <span class="small muted">时间按真实考试的“每题平均用时”折算</span></div>
        </div>
        <div class="card">
          <h3 class="mb">模考记录</h3>
          ${history.length ? `<div class="table-wrap"><table class="tbl"><thead><tr><th>时间</th><th class="n">得分</th><th class="n">正确率</th></tr></thead><tbody>
            ${history.slice(0, 12).map((s) => `<tr><td class="small">${esc(s.created_at.slice(5, 16))}</td><td class="n">${s.correct}/${s.total}</td><td class="n">${Math.round((s.correct / s.total) * 100)}%</td></tr>`).join("")}
          </tbody></table></div>` : `<div class="empty">还没有模考记录</div>`}
          <hr class="sep">
          <p class="small ink2" style="margin:0">模考要点：中途不暂停、不查资料；交卷后先看各模块用时，再逐题复盘错因。详见教程
            <a href="#/learn/strategy-01">做题顺序与时间分配</a>。</p>
        </div>
      </div>`;
    el.querySelectorAll("#papers button").forEach((x) => (x.onclick = () => { paper = PAPERS.find((p) => p.id === x.dataset.p); setup(); }));
    el.querySelectorAll("#levels button").forEach((x) => (x.onclick = () => { level = x.dataset.l; setup(); }));
    el.querySelector("#start").onclick = async () => {
      const ids = await compose(preview.plan);
      cleanup = await runQuiz(el, {
        title: `模考 · ${paper.name}（${level}）`, ids, mode: "exam", timeLimit: preview.minutes * 60,
        onAgain: () => { cleanup?.(); setup(); },
      });
    };
  }

  setup();
  return () => cleanup?.();
}
