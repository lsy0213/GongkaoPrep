import { apiPost, bankMeta, esc, MODULES, pickQuestions, store } from "../lib.js";
import { runQuiz } from "../quiz.js";

const SOURCES = [
  { id: "all", name: "全部题目" },
  { id: "builtin", name: "内置练习题" },
  { id: "国考", name: "国考真题" },
  { id: "四川", name: "四川真题" },
  { id: "千题册", name: "题册" },
];
const YEARS = [
  { id: "all", name: "不限年份" },
  { id: "3", name: "近 3 年" },
  { id: "5", name: "近 5 年" },
  { id: "10", name: "近 10 年" },
];

const ORDERS = [
  { id: "new", name: "优先新题", hint: "没做过的先出" },
  { id: "random", name: "随机", hint: "完全随机抽题" },
  { id: "wrong", name: "只做错过的", hint: "错题本里还没掌握的" },
  { id: "fav", name: "只做收藏", hint: "你收藏过的题" },
];

export async function render(el, ctx) {
  const meta = await bankMeta();
  const c = meta.counts;
  const realCount = (c["国考"] || 0) + (c["四川"] || 0);
  const saved = store.get("practice", {});
  const st = {
    module: ctx.query.module || saved.module || "全部",
    sub: ctx.query.sub || "全部",
    count: +(ctx.query.count || saved.count || 15),
    order: ctx.query.auto ? "new" : (saved.order || "new"),
    timed: ctx.query.auto ? false : !!saved.timed,
    src: ctx.query.src === "real" ? "国考" : (ctx.query.src || (ctx.query.auto ? "all" : saved.src) || "all"),
    years: saved.years || "all",
  };
  const sources = SOURCES.filter((x) => x.id === "all" || x.id === "builtin" || c[x.id]);
  if (!sources.some((x) => x.id === st.src)) st.src = "all";
  let cleanup = null;

  const filter = () => ({ src: st.src, years: st.years, module: st.module, sub: st.sub, order: st.order });

  async function setup() {
    const sum = await apiPost("/api/bank/summary", filter());
    if (!el.isConnected) return;
    const mods = sum.modules;
    const subs = st.module === "全部" ? [] : Object.entries(mods[st.module]?.subs || {}).sort((a, b) => b[1] - a[1]);
    const avail = sum.matching;
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">专项刷题</div><h1>选一个模块开始练</h1>
        <p>题库共 ${c.total} 道题${realCount ? `，其中历年真题卷 ${realCount} 道` : ""}${c["千题册"] ? `、题册（千题册、5000题） ${c["千题册"]} 道` : ""}${meta.custom_count ? `，导入 ${meta.custom_count} 道` : ""}。</p></div>
        ${realCount ? `<a class="btn" href="#/real">整卷做真题</a>` : `<a class="btn" href="#/library">导入资料里的真题</a>`}</div>
      <div class="card">
        ${sources.length > 2 ? `<div class="row" style="margin-bottom:14px"><h3 style="margin:0">题目来源</h3>
          <div class="seg" id="srcs">${sources.map((x) => `<button data-src="${x.id}" class="${st.src === x.id ? "active" : ""}">${x.name}</button>`).join("")}</div>
          ${st.src !== "builtin" ? `<select id="years" style="width:auto">${YEARS.map((y) => `<option value="${y.id}" ${st.years === y.id ? "selected" : ""}>${y.name}</option>`).join("")}</select>` : ""}</div>` : ""}
        <h3 style="margin-bottom:10px">模块</h3>
        <div class="pick" id="mods">
          <button data-m="全部" class="${st.module === "全部" ? "active" : ""}">全部模块<small>${sum.total} 题</small></button>
          ${MODULES.map((m) => {
            const x = mods[m] || { total: 0, done: 0 };
            return `<button data-m="${esc(m)}" class="${st.module === m ? "active" : ""}" ${x.total ? "" : "disabled"}>${esc(m)}<small>做过 ${x.done} / ${x.total}</small></button>`;
          }).join("")}
        </div>
        ${subs.length > 1 ? `<h3 class="mt" style="margin-bottom:10px">题型</h3>
          <div class="seg wrap" id="subs">${[["全部", mods[st.module].total], ...subs].map(([s, n]) => `<button data-s="${esc(s)}" class="${st.sub === s ? "active" : ""}">${esc(s)} <small class="muted">${n}</small></button>`).join("")}</div>` : ""}
        <div class="grid cols-3 mt">
          <div><h3 style="margin-bottom:10px">题量</h3>
            <div class="seg" id="counts">${[5, 10, 15, 20, 30, 50].map((n) => `<button data-c="${n}" class="${st.count === n ? "active" : ""}">${n}</button>`).join("")}</div></div>
          <div><h3 style="margin-bottom:10px">出题方式</h3>
            <select id="order">${ORDERS.map((o) => `<option value="${o.id}" ${st.order === o.id ? "selected" : ""}>${o.name}（${o.hint}）</option>`).join("")}</select></div>
          <div><h3 style="margin-bottom:10px">模式</h3>
            <div class="seg" id="timed"><button data-t="0" class="${!st.timed ? "active" : ""}">练习：选完看解析</button><button data-t="1" class="${st.timed ? "active" : ""}">限时：每题 1 分钟</button></div></div>
        </div>
        <div class="row mt">
          <button class="btn primary lg" id="start" ${avail ? "" : "disabled"}>开始练习</button>
          <span class="small muted">${avail ? `符合条件的有 ${avail} 题（做过 ${sum.matching_done} 题），本次出 ${Math.min(st.count, avail)} 题左右` : "没有符合条件的题目，换个条件试试"}</span>
        </div>
      </div>
      <div class="card">
        <h3 style="margin-bottom:6px">练习建议</h3>
        <ul class="ink2 small" style="margin:0;padding-left:1.2em;line-height:1.9">
          <li>刚开始先用“练习”模式，每题看完解析弄懂再做下一题；有基础后换成“限时”模式找考场节奏。</li>
          <li>做错的题自动进入错题本，会按遗忘规律提醒你复习，比刷新题更重要。</li>
          <li>每个题型先学 <a href="#/learn">教程</a> 里对应的课再练，效果更好。</li>
        </ul>
      </div>`;
    el.querySelectorAll("#mods button").forEach((x) => (x.onclick = () => { st.module = x.dataset.m; st.sub = "全部"; setup(); }));
    el.querySelectorAll("#subs button").forEach((x) => (x.onclick = () => { st.sub = x.dataset.s; setup(); }));
    el.querySelectorAll("#counts button").forEach((x) => (x.onclick = () => { st.count = +x.dataset.c; setup(); }));
    el.querySelectorAll("#timed button").forEach((x) => (x.onclick = () => { st.timed = x.dataset.t === "1"; setup(); }));
    el.querySelector("#order").onchange = (e) => { st.order = e.target.value; setup(); };
    el.querySelectorAll("#srcs button").forEach((x) => (x.onclick = () => { st.src = x.dataset.src; st.sub = "全部"; setup(); }));
    const ys = el.querySelector("#years");
    if (ys) ys.onchange = () => { st.years = ys.value; setup(); };
    el.querySelector("#start").onclick = start;
  }

  async function start() {
    if (!ctx.query.auto) store.set("practice", { module: st.module, count: st.count, order: st.order, timed: st.timed, src: st.src, years: st.years });
    const ids = await pickQuestions({ ...filter(), count: st.count });
    const srcName = st.src === "国考" || st.src === "四川" ? st.src + "真题 · " : st.src === "千题册" ? "题册 · " : "";
    const title = `${srcName}${st.module === "全部" ? "综合" : st.module}${st.sub !== "全部" ? " · " + st.sub : ""} · ${ids.length} 题`;
    cleanup = await runQuiz(el, {
      title, ids, mode: st.timed ? "exam" : "practice", timeLimit: st.timed ? ids.length * 60 : 0,
      onAgain: () => { cleanup?.(); start(); },
    });
  }

  await setup();
  // 从教程“真题演练”进来：直接开始
  if (ctx.query.auto && el.querySelector("#start") && !el.querySelector("#start").disabled) await start();
  return () => cleanup?.();
}
