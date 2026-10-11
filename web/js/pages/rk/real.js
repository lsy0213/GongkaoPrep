// 软考 · 真题卷与模拟卷：2009 年至今的综合知识真题（2009–2018 来自资料文件夹，有原卷截图；2020 年起多为考生回忆版）
// 和模拟卷；整卷练习、限时 150 分钟模考、按模块练
import { apiGet, bankMeta, esc, MODULES, MODULE_SHORT, pickQuestions, store } from "../../lib.js";
import { runQuiz } from "../../quiz.js";

const PAPER_MINUTES = 150; // 综合知识最长 150 分钟（和案例连考，节省的时间留给案例）

function row(p, prog) {
  const pr = prog[p.id] || { done: 0, correct: 0 };
  const mods = MODULES.filter((m) => p.modules?.[m]);
  const pct = p.count ? Math.round((pr.done / p.count) * 100) : 0;
  return `<div class="paper-row pr-card">
    <div class="info"><div class="t">${p.year ? `<span class="year-tag">${p.year}${p.level ? " " + esc(p.level.replace("半年", "")) : ""}</span>` : ""}${esc(p.title.replace(/^\d{4}年(上|下)?半?年?\s*/, ""))}</div>
      <div class="meta">${p.count} 题${p.answered < p.count ? `（${p.count - p.answered} 题缺答案）` : ""} · ${esc(p.note || "")}</div></div>
    <div class="stat"><div class="progress"><i style="width:${pct}%"></i></div>
      <span class="meta">${pr.done ? `做过 ${pr.done} 题 · 正确率 ${Math.round((pr.correct / pr.done) * 100)}%` : "还没做过"}</span></div>
    <div class="actions">
      <a class="btn sm primary" href="#/real/${encodeURIComponent(p.id)}?mode=exam" title="和真实机考一样限时 ${PAPER_MINUTES} 分钟，交卷再看答案">限时模考</a>
      <a class="btn sm" href="#/real/${encodeURIComponent(p.id)}">练习</a>
      ${mods.length > 1 ? `<select class="pr-mod" data-src="${esc(p.id)}" aria-label="按模块练"><option value="">按模块练</option>${mods.map((m) => `<option value="${esc(m)}">${esc(MODULE_SHORT[m] || m)} · ${p.modules[m]} 题</option>`).join("")}</select>` : ""}
      ${p.fid ? `<span class="pr-links"><a href="#/library/view/${esc(p.fid)}" title="看原卷 PDF">原卷</a>${p.answer_fid ? `<a href="#/library/view/${esc(p.answer_fid)}" title="答案详解原文件">解析</a>` : ""}</span>` : ""}
    </div></div>`;
}

export async function render(el, ctx) {
  const [meta, prog] = await Promise.all([bankMeta(true), apiGet("/api/real/progress")]);
  const pid = ctx.parts[1];
  let cleanup = null;
  const papers = meta.sources.filter((s) => s.kind === "paper").sort((a, b) => b.year - a.year || (b.level || "").localeCompare(a.level || ""));
  const mocks = meta.sources.filter((s) => s.kind === "mock");

  if (!papers.length && !mocks.length) {
    el.innerHTML = `<div class="page-head"><div><div class="eyebrow">真题卷</div><h1>还没有整理真题</h1>
      <p>真题来自你的资料文件夹（2009–2018 年文字版试卷和答案详解）和开源题库（2020 年至今的回忆版、模拟卷）。到设置里点“整理软考资料”。</p></div></div>
      <div class="card"><a class="btn primary" href="#/settings">去整理资料</a></div>`;
    return;
  }

  if (pid) {
    const src = meta.sourceById[pid];
    if (!src) { el.innerHTML = `<div class="card empty"><h3>没有找到这套题</h3><a href="#/real">返回真题卷</a></div>`; return; }
    const mode = ctx.query.mode === "exam" ? "exam" : "practice";
    const module = ctx.query.module || "";
    const ids = await pickQuestions({ source: pid, module: module || "全部", order: "all", count: 0 });
    const minutes = mode === "exam" ? (module ? Math.max(10, Math.round((ids.length * PAPER_MINUTES) / 75)) : PAPER_MINUTES) : 0;
    cleanup = await runQuiz(el, { title: `${src.title}${module ? " · " + module : ""}`, ids, mode, timeLimit: minutes * 60,
      onAgain: () => { location.hash = "#/real"; } });
    return () => cleanup?.();
  }

  const saved = store.get("real", {});
  let tab = ["paper", "mock"].includes(saved.rkTab) ? saved.rkTab : "paper";
  function draw() {
    const list = tab === "paper" ? papers : mocks;
    const done = list.reduce((a, p) => a + (prog[p.id]?.done || 0), 0), total = list.reduce((a, p) => a + p.count, 0);
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">综合知识</div><h1>真题卷</h1>
        <p>每套 75 题（含 5 道英语），每题 1 分，45 分及格。整卷限时 ${PAPER_MINUTES} 分钟；练习模式选完马上看解析，题目有原卷截图的可以点“看原卷”。</p></div>
        <a class="btn" href="#/practice">按模块 / 考点刷题</a></div>
      <div class="seg mb" id="tabs">
        <button data-t="paper" class="${tab === "paper" ? "active" : ""}">历年真题 · ${papers.length} 套</button>
        <button data-t="mock" class="${tab === "mock" ? "active" : ""}">模拟卷 · ${mocks.length} 套</button></div>
      <p class="small muted">已做 ${done} / ${total} 题。${tab === "paper" ? "2020 年起机考不公开试题，题目来自考生回忆和开源题库（github.com/wujiaming88/awesome-ruankao，CC BY-SA 4.0），个别题可能不全。" : "模拟卷来自你的资料文件夹（希赛模拟卷）和开源题库的 2026 年模拟卷。"}</p>
      <div class="card">${list.map((p) => row(p, prog)).join("")}</div>`;
    el.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => { tab = b.dataset.t; store.set("real", { ...saved, rkTab: tab }); draw(); }));
    el.querySelectorAll(".pr-mod").forEach((s) => (s.onchange = () => {
      if (s.value) location.hash = `#/real/${encodeURIComponent(s.dataset.src)}?module=${encodeURIComponent(s.value)}`;
    }));
  }
  draw();
}
