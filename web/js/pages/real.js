// 真题卷：从资料文件夹解析出的国考、四川省考行测真题（整卷限时模考、按模块练）和题册（千题册、5000题：按题型顺序 / 随机练）
import { apiGet, bankMeta, esc, MODULES, MODULE_SHORT, pickQuestions, store } from "../lib.js";
import { runQuiz } from "../quiz.js";

const TABS = [
  { id: "国考", name: "国考" },
  { id: "四川", name: "四川省考" },
  { id: "千题册", name: "题册" },
];
// 整卷时间：国考、四川行测都是 120 分钟
const PAPER_MINUTES = 120;
const BOOK_ORDERS = { seq: "顺序练", new: "随机新题", wrong: "错题重做" };

function levelGroup(p) {
  const l = p.level || "";
  if (/副省/.test(l)) return "副省级";
  if (/地市/.test(l)) return "地市级";
  if (/行政执法/.test(l)) return "行政执法";
  return "其他";
}

export async function render(el, ctx) {
  const [meta, prog] = await Promise.all([bankMeta(), apiGet("/api/real/progress")]);
  const pid = ctx.parts[1];
  let cleanup = null;

  if (!meta.papers.length && !meta.books.length) {
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">真题卷</div><h1>还没有导入真题</h1>
        <p>真题来自你的资料文件夹。到“资料库”页点“整理资料”，软件会自动找出国考、四川省考的行测和申论真题、千题册和5000题，连同答案解析一起整理成可以做的题。</p></div></div>
      <div class="card"><div class="row"><a class="btn primary" href="#/library">去资料库整理</a><a class="btn" href="#/settings">设置资料文件夹</a></div></div>`;
    return;
  }

  if (pid) {
    const src = meta.sourceById[pid];
    if (!src) { el.innerHTML = `<div class="card empty"><h3>没有找到这套题</h3><a href="#/real">返回真题卷</a></div>`; return; }
    let ids, title, mode, minutes = 0;
    if (src.kind === "book") {
      const order = BOOK_ORDERS[ctx.query.order] ? ctx.query.order : "seq";
      const count = +(ctx.query.count || 20);
      ids = await pickQuestions({ source: pid, order, count });
      mode = ctx.query.mode === "exam" ? "exam" : "practice";
      minutes = mode === "exam" ? Math.max(5, Math.round(ids.length * 0.8)) : 0;
      title = `${src.title} · ${BOOK_ORDERS[order]} ${ids.length} 题`;
    } else {
      mode = ctx.query.mode === "exam" ? "exam" : "practice";
      const module = ctx.query.module || "";
      ids = await pickQuestions({ source: pid, module: module || "全部", order: "all", count: 0 });
      title = `${src.title}${module ? " · " + module : ""}`;
      minutes = mode === "exam" ? (module ? Math.max(10, Math.round(ids.length * PAPER_MINUTES / src.count)) : PAPER_MINUTES) : 0;
    }
    cleanup = await runQuiz(el, {
      title, ids, mode, timeLimit: minutes * 60,
      onAgain: src.kind === "book" ? () => { cleanup?.(); render(el, ctx).then((c) => (cleanup = c)); } : () => { location.hash = "#/real"; },
    });
    return () => cleanup?.();
  }

  const saved = store.get("real", {});
  const st = { exam: saved.exam || (meta.papers.length ? "国考" : "千题册"), level: saved.level || "全部", count: saved.count || 20 };
  const save = () => store.set("real", st);

  function papersHTML() {
    const all = meta.papers.filter((p) => p.exam === st.exam);
    const levels = ["全部", ...new Set(all.map(levelGroup))];
    const papers = all.filter((p) => st.level === "全部" || levelGroup(p) === st.level);
    return `
      <div class="row" style="justify-content:flex-end;margin-top:-6px">
        ${levels.length > 2 ? `<div class="seg" id="levels">${levels.map((l) => `<button data-l="${l}" class="${st.level === l ? "active" : ""}">${l}</button>`).join("")}</div>` : ""}
      </div>
      <hr class="sep">
      ${papers.length ? papers.map((p) => {
        const pr = prog[p.id] || { done: 0, correct: 0 };
        const answered = p.answered || 0;
        const mods = MODULES.filter((m) => p.modules[m]);
        const pct = answered ? Math.min(100, Math.round((pr.done / answered) * 100)) : 0;
        return `<div class="paper-row">
          <div class="info"><div class="t"><span class="year-tag">${p.year}</span>${esc(p.title.replace(/^\d{4}\s*年?/, ""))}</div>
            <div class="meta">${p.count} 题${answered < p.count ? `（${p.count - answered} 题缺答案）` : ""} · ${mods.map((m) => `${MODULE_SHORT[m]} ${p.modules[m]}`).join(" / ")}</div></div>
          <div class="stat"><div class="progress"><i style="width:${pct}%"></i></div>
            <div class="meta mt">${pr.done ? `做过 ${pr.done} 题 · 正确率 ${Math.round((pr.correct / pr.done) * 100)}%` : "还没做过"}</div></div>
          <div class="actions">
            ${answered ? `<a class="btn sm primary" href="#/real/${p.id}?mode=exam">整卷模考</a>
            <a class="btn sm" href="#/real/${p.id}">练习</a>
            <select data-mod="${p.id}" style="width:auto;padding:3px 6px;font-size:13px"><option value="">按模块…</option>${mods.map((m) => `<option value="${esc(m)}">${esc(m)}（${p.modules[m]}）</option>`).join("")}</select>` : `<span class="small muted">暂无答案</span>`}
            <a class="btn sm ghost" href="#/library/view/${p.fid}" title="在资料库里看原卷 PDF">原卷</a>
            ${p.answer_fid ? `<a class="btn sm ghost" href="#/library/view/${p.answer_fid}" title="答案解析原文件">解析</a>` : ""}
          </div></div>`;
      }).join("") : `<div class="empty">这一类没有卷子</div>`}`;
  }

  function bookRow(b) {
    const pr = prog[b.id] || { done: 0, correct: 0 };
    const pct = b.answered ? Math.min(100, Math.round((pr.done / b.answered) * 100)) : 0;
    return `<div class="paper-row">
      <div class="info"><div class="t"><span class="year-tag">${esc(MODULE_SHORT[b.module] || "")}</span>${esc(b.title)}</div>
        <div class="meta">${b.answered} 题${b.year ? ` · 最新到 ${b.year} 年` : ""} · ${esc(b.note || "")}</div></div>
      <div class="stat"><div class="progress"><i style="width:${pct}%"></i></div>
        <div class="meta mt">${pr.done ? `做过 ${pr.done} 题 · 正确率 ${Math.round((pr.correct / pr.done) * 100)}%` : "还没做过"}</div></div>
      <div class="actions">
        <a class="btn sm primary" href="#/real/${b.id}?order=seq&count=${st.count}">顺序练</a>
        <a class="btn sm" href="#/real/${b.id}?order=new&count=${st.count}">随机新题</a>
        <a class="btn sm" href="#/real/${b.id}?order=new&count=${st.count}&mode=exam" title="每题 48 秒">限时</a>
        <a class="btn sm ghost" href="#/real/${b.id}?order=wrong&count=${st.count}">错题</a>
      </div></div>`;
  }

  function booksHTML() {
    // 千题册（按题型）和《决战行测5000题》（按模块、章）两套书，各自按模块顺序排
    const series = [
      { name: "千题册", note: "按题型收录近几年各省市真题，各版本已合并", list: meta.books.filter((b) => b.exam !== "5000题") },
      { name: "决战行测5000题", note: "五个模块按章节编排的真题练习，解析来自下册", list: meta.books.filter((b) => b.exam === "5000题") },
    ].filter((s) => s.list.length);
    const modIdx = (b) => { const i = MODULES.indexOf(b.module); return i < 0 ? 99 : i; };
    return `
      <div class="row" style="justify-content:space-between;margin-top:-6px">
        <p class="small ink2" style="margin:0">和真题卷、其他题册重复的题已去掉。“顺序练”从你第一道没做过的题接着做。</p>
        <div class="row"><span class="small muted">每组</span>
          <div class="seg" id="bcount">${[10, 20, 30, 50].map((n) => `<button data-c="${n}" class="${st.count === n ? "active" : ""}">${n}</button>`).join("")}</div></div>
      </div>
      ${series.length ? series.map((s) => `
        <h3 class="mt" style="margin-bottom:2px">${esc(s.name)} <small class="muted">${s.list.reduce((a, b) => a + (b.answered || 0), 0)} 题 · ${esc(s.note)}</small></h3>
        <hr class="sep">
        ${[...s.list].sort((a, b) => modIdx(a) - modIdx(b)).map(bookRow).join("")}`).join("")
        : `<div class="empty">还没有识别题册。到“资料库 → 整理资料”运行“识别题册”。</div>`}`;
  }

  function draw() {
    const totals = Object.fromEntries(TABS.map((t) => {
      const ps = t.id === "千题册" ? meta.books : meta.papers.filter((p) => p.exam === t.id);
      return [t.id, { n: ps.length, q: ps.reduce((a, p) => a + (p.answered || 0), 0) }];
    }));
    const done = Object.values(prog).reduce((a, x) => a + x.done, 0);
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">真题卷</div><h1>行测真题</h1>
        <p>真题卷 ${meta.papers.length} 套（国考 ${totals["国考"].n} 套 · 四川 ${totals["四川"].n} 套）${meta.books.length ? `，题册 ${totals["千题册"].q} 题` : ""}，已做 ${done} 道。
          整卷模考严格计时 ${PAPER_MINUTES} 分钟；也可以只练某个模块。图形推理、图表题会显示原卷截图。</p></div>
        <a class="btn" href="#/practice?src=real">按模块混合刷真题</a></div>
      <div class="card">
        <div class="tabs" style="margin:0 0 10px;border:0" id="exams">${TABS.filter((t) => totals[t.id].n).map((t) => `<button data-e="${t.id}" class="${st.exam === t.id ? "active" : ""}">${t.name} <small class="muted">${t.id === "千题册" ? totals[t.id].q + " 题" : totals[t.id].n + " 套"}</small></button>`).join("")}</div>
        ${st.exam === "千题册" ? booksHTML() : papersHTML()}
      </div>
      <p class="small muted">题目和答案由软件从 PDF 自动识别，个别题的文字可能有错漏，以“原卷”为准；缺答案的题来自扫描版答案文件，可以点“解析”查看原文件。</p>`;
    el.querySelectorAll("#exams button").forEach((x) => (x.onclick = () => { st.exam = x.dataset.e; st.level = "全部"; save(); draw(); }));
    el.querySelectorAll("#levels button").forEach((x) => (x.onclick = () => { st.level = x.dataset.l; save(); draw(); }));
    el.querySelectorAll("#bcount button").forEach((x) => (x.onclick = () => { st.count = +x.dataset.c; save(); draw(); }));
    el.querySelectorAll("[data-mod]").forEach((x) => (x.onchange = () => {
      if (x.value) location.hash = `#/real/${x.dataset.mod}?module=${encodeURIComponent(x.value)}`;
    }));
  }

  draw();
  return () => cleanup?.();
}
