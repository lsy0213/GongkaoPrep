import { EXAM, apiPost, bankMeta, esc, MODULES, pickQuestions, store } from "../lib.js";
import { runQuiz } from "../quiz.js";

// 软考：真题（2009 年至今）、模拟卷、内置原创练习；“题型”叫“考点”
const RK_SOURCES = [
  { id: "all", name: "全部题目" },
  { id: "真题", name: "历年真题" },
  { id: "模拟", name: "模拟卷" },
  { id: "builtin", name: "原创练习" },
];
const GK_SOURCES = [
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
  const gk = EXAM.id === "gongkao";
  const SOURCES = gk ? GK_SOURCES : RK_SOURCES;
  const SUB_LABEL = gk ? "题型" : "考点";
  const realCount = gk ? (c["国考"] || 0) + (c["四川"] || 0) : (c["真题"] || 0);
  const saved = store.get("practice", {});
  const st = {
    module: ctx.query.module || saved.module || "全部",
    sub: ctx.query.sub || "全部",
    count: +(ctx.query.count || saved.count || 15),
    order: ctx.query.auto ? "new" : (saved.order || "new"),
    timed: ctx.query.auto ? false : !!saved.timed,
    src: ctx.query.src === "real" ? (gk ? "国考" : "真题") : (ctx.query.src || (ctx.query.auto ? "all" : saved.src) || "all"),
    years: saved.years || "all",
    topic: ctx.query.topic || "", topicName: ctx.query.tname || "",  // 从“弱项诊断”进来：只出这个考点的题
  };
  const sources = SOURCES.filter((x) => x.id === "all" || x.id === "builtin" || c[x.id]);
  if (!sources.some((x) => x.id === st.src)) st.src = "all";
  let cleanup = null;

  const filter = () => ({ src: st.src, years: st.years, module: st.module, sub: st.sub, order: st.order, topic: st.topic });

  // 题型：一个模块下常有十几二十个，默认只露出前 8 个（按题量），其余点「更多」展开
  function subsBlock(subs, total) {
    const all = [["全部", total], ...subs];
    const SHOW = 8;
    const open = st.subsOpen || all.findIndex(([x]) => x === st.sub) >= SHOW;
    const list = open ? all : all.slice(0, SHOW);
    return `<div class="pr-label mt">${SUB_LABEL}</div>
      <div class="pills wrap sm" id="subs">${list.map(([x, n]) => `<button data-s="${esc(x)}" class="${st.sub === x ? "active" : ""}">${esc(x)}<small class="num">${n}</small></button>`).join("")}
        ${all.length > SHOW ? `<button class="pill-more" id="subs-more">${open ? "收起" : `更多 ${all.length - SHOW} 个`}</button>` : ""}</div>`;
  }

  async function setup() {
    const sum = await apiPost("/api/bank/summary", filter());
    if (!el.isConnected) return;
    const mods = sum.modules;
    const subs = st.module === "全部" ? [] : Object.entries(mods[st.module]?.subs || {}).sort((a, b) => b[1] - a[1]);
    const avail = sum.matching;
    const pctOf = (x) => (x.total ? Math.round((x.done / x.total) * 100) : 0);
    const allMods = { total: sum.total, done: MODULES.reduce((a, m) => a + (mods[m]?.done || 0), 0) };
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">${gk ? "专项刷题" : "综合知识"}</div><h1>${gk ? "专项刷题" : "章节刷题"}</h1>
        <div class="pr-meta"><span><b class="num">${c.total}</b> 道题</span>${realCount ? `<span>真题 <b class="num">${realCount}</b></span>` : ""}${c["模拟"] ? `<span>模拟卷 <b class="num">${c["模拟"]}</b></span>` : ""}${c["千题册"] ? `<span>题册 <b class="num">${c["千题册"]}</b></span>` : ""}${meta.custom_count ? `<span>导入 <b class="num">${meta.custom_count}</b></span>` : ""}</div></div>
        ${realCount ? `<a class="btn" href="#/real">整卷做真题</a>` : `<a class="btn" href="${gk ? "#/library" : "#/settings"}">导入资料里的真题</a>`}</div>

      ${sources.length > 2 ? `<section class="pr-sec">
        <div class="pr-label">题目来源</div>
        <div class="pr-row">
          <div class="pills scroll" id="srcs">${sources.map((x) => `<button data-src="${x.id}" class="${st.src === x.id ? "active" : ""}">${x.name}</button>`).join("")}</div>
          ${st.src !== "builtin" ? `<select id="years" class="pr-years" aria-label="年份">${YEARS.map((y) => `<option value="${y.id}" ${st.years === y.id ? "selected" : ""}>${y.name}</option>`).join("")}</select>` : ""}
        </div></section>` : ""}
      ${st.topic ? `<div class="row mb"><span class="chip warn">只练考点：${esc(st.topicName || st.topic)}</span>
        <button class="btn sm ghost" id="clear-topic">不限考点</button></div>` : ""}

      <section class="pr-sec">
        <div class="pr-label">模块</div>
        <div class="mod-grid" id="mods">
          <button data-m="全部" class="mod-tile ${st.module === "全部" ? "active" : ""}"><b>全部模块</b><span class="num">${sum.total} 题</span><i style="--p:${pctOf(allMods)}%"></i></button>
          ${MODULES.map((m) => {
            const x = mods[m] || { total: 0, done: 0 };
            return `<button data-m="${esc(m)}" class="mod-tile ${st.module === m ? "active" : ""}" ${x.total ? "" : "disabled"}><b>${esc(m)}</b><span class="num">${x.done} / ${x.total}</span><i style="--p:${pctOf(x)}%"></i></button>`;
          }).join("")}
        </div>
        ${subs.length > 1 ? subsBlock(subs, mods[st.module].total) : ""}
      </section>

      <section class="pr-sec card pr-opts">
        <div class="pr-opt"><div class="pr-label">题量</div>
          <div class="pills" id="counts">${[5, 10, 15, 20, 30, 50].map((n) => `<button data-c="${n}" class="num ${st.count === n ? "active" : ""}">${n}</button>`).join("")}</div></div>
        <div class="pr-opt"><div class="pr-label">出题方式</div>
          <div class="pills wrap" id="order">${ORDERS.map((o) => `<button data-o="${o.id}" title="${esc(o.hint)}" class="${st.order === o.id ? "active" : ""}">${esc(o.name)}</button>`).join("")}</div></div>
        <div class="pr-opt"><div class="pr-label">模式</div>
          <div class="mode-pick" id="timed">
            <button data-t="0" class="${!st.timed ? "active" : ""}"><b>练习</b><span>选完马上看解析</span></button>
            <button data-t="1" class="${st.timed ? "active" : ""}"><b>限时</b><span>每题 1 分钟，交卷再看</span></button>
          </div></div>
      </section>

      <div class="start-bar">
        <div class="sb-info">${avail ? `<b class="num">${Math.min(st.count, avail)}</b> 题<span>符合条件 ${avail} 题 · 做过 ${sum.matching_done}</span>` : `<span>没有符合条件的题目，换个条件试试</span>`}</div>
        <button class="btn primary lg" id="start" ${avail ? "" : "disabled"}>开始练习</button>
      </div>

      <details class="pr-tips">
        <summary>练习建议</summary>
        <ul class="ink2 small">
          <li>刚开始先用“练习”模式，每题看完解析弄懂再做下一题；有基础后换成“限时”模式找考场节奏。</li>
          <li>做错的题自动进入错题本，会按遗忘规律提醒你复习，比刷新题更重要。</li>
          <li>每个题型先学 <a href="#/learn">教程</a> 里对应的课再练，效果更好。</li>
        </ul>
      </details>`;
    el.querySelectorAll("#mods button").forEach((x) => (x.onclick = () => { st.module = x.dataset.m; st.sub = "全部"; setup(); }));
    el.querySelectorAll("#subs button[data-s]").forEach((x) => (x.onclick = () => { st.sub = x.dataset.s; setup(); }));
    const more = el.querySelector("#subs-more");
    if (more) more.onclick = () => { st.subsOpen = !st.subsOpen; setup(); };
    el.querySelectorAll("#counts button").forEach((x) => (x.onclick = () => { st.count = +x.dataset.c; setup(); }));
    el.querySelectorAll("#timed button").forEach((x) => (x.onclick = () => { st.timed = x.dataset.t === "1"; setup(); }));
    el.querySelectorAll("#order button").forEach((x) => (x.onclick = () => { st.order = x.dataset.o; setup(); }));
    el.querySelectorAll("#srcs button").forEach((x) => (x.onclick = () => { st.src = x.dataset.src; st.sub = "全部"; setup(); }));
    const ys = el.querySelector("#years");
    if (ys) ys.onchange = () => { st.years = ys.value; setup(); };
    el.querySelector("#start").onclick = start;
    const ct = el.querySelector("#clear-topic");
    if (ct) ct.onclick = () => { st.topic = ""; st.topicName = ""; setup(); };
  }

  async function start() {
    if (!ctx.query.auto) store.set("practice", { module: st.module, count: st.count, order: st.order, timed: st.timed, src: st.src, years: st.years });
    const ids = await pickQuestions({ ...filter(), count: st.count });
    const srcName = st.src === "国考" || st.src === "四川" ? st.src + "真题 · " : st.src === "千题册" ? "题册 · " : st.src === "真题" ? "真题 · " : st.src === "模拟" ? "模拟卷 · " : "";
    const title = `${srcName}${st.module === "全部" ? "综合" : st.module}${st.sub !== "全部" ? " · " + st.sub : ""}${st.topic ? " · " + (st.topicName || st.topic) : ""} · ${ids.length} 题`;
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
