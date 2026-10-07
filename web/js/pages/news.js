// 时政晨读：资料文件夹里“时政合集 + 每日晨读”整理成的文字内容。
// 五块：月度时政（年 → 月）、时政专题（按主题）、时政题库、人民日报精读（按月 → 每天一篇）、成语积累（按天：例句 + 释义，可挖空自测）。
// 讲义、精读、题库在内置阅读器里读（#/news/doc/<id>）；成语积累在本页直接看。
import { apiGet, apiPost, esc, jobDoneText, jobProgressHTML, shuffle, store, toast } from "../lib.js";

const TABS = [
  ["month", "月度时政"],
  ["topic", "时政专题"],
  ["bank", "时政题库"],
  ["read", "人民日报精读"],
  ["cy", "成语积累"],
];
const SEC_OF = { month: "月度时政", topic: "时政专题", bank: "时政题库", read: "人民日报精读" };
const SRC_ORDER = ["超格", "小黑", "粉笔", "必胜哥", "人民日报", "其他"];
const SRC_NOTE = { "超格": "超格时政讲练班 / 热点汇总 / 月度刷题", "小黑": "小黑月半时政（含金卷）", "粉笔": "粉笔每月时政串讲 / 刷题" };
const WEEK = "日一二三四五六";

const docHref = (id, seq, q) => `#/news/doc/${encodeURIComponent(id)}${seq != null ? `?s=${seq}${q ? `&q=${encodeURIComponent(q)}` : ""}` : ""}`;
const fmtChars = (n) => (n >= 10000 ? `${(n / 10000).toFixed(1)} 万字` : `${n} 字`);
const ym = (y, m) => `${y}-${String(m).padStart(2, "0")}`;
const ymLabel = (k) => (k === "0000-00" ? "未标月份" : `${+k.slice(0, 4)} 年 ${+k.slice(5)} 月`);
const weekday = (d) => WEEK[new Date(d + "T00:00:00").getDay()];
const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

let pollTimer = null;

export async function render(el, ctx) {
  clearInterval(pollTimer);
  if (ctx.parts[1] === "doc" && ctx.parts[2]) {
    const { openReader } = await import("../reader.js");
    try {
      return await openReader(el, ctx.parts[2], ctx.query.s != null ? +ctx.query.s : undefined, ctx.query.q);
    } catch (e) {
      el.innerHTML = `<div class="card empty"><h3>打不开这份资料</h3><p>${esc(e.message)}</p><a href="#/news">返回时政晨读</a></div>`;
      return;
    }
  }

  const data = await apiGet("/api/news");
  const items = data.items;
  const prog = data.progress || {};
  const markCount = data.marks || {};
  const byId = Object.fromEntries(items.map((d) => [d.id, d]));
  const saved = store.get("news", {});
  const st = {
    tab: TABS.some(([k]) => k === saved.tab) ? saved.tab : "month",
    sel: saved.sel || {},          // 每个标签页左栏选中的项
    src: saved.src || "全部",       // 月度时政：按机构筛
    query: "", results: null,
    cyMode: saved.cyMode || "read", // 成语：read 阅读 / test 挖空自测 / list 成语总表
    cyOpen: null,                   // 展开的那一天
    cyData: {},                     // 已取回的月份 { "2026-09": [day...] }
    cyAll: null, cyFilter: "",
  };
  const cyDone = () => store.get("cy_done", {});
  const remember = () => store.set("news", { tab: st.tab, sel: st.sel, src: st.src, cyMode: st.cyMode });

  const secItems = (sec) => items.filter((d) => d.sec === sec);

  // ---------------------------------------------------------------- 资料卡片
  function card(d, { showMonth = false, label = null } = {}) {
    const p = prog[d.id];
    const meta = [fmtChars(d.chars), d.nq ? `<span class="doc-q">题 ${d.nq} 道</span>` : "", d.toc_n > 1 ? `目录 ${d.toc_n} 条` : ""].filter(Boolean).join(" · ");
    const sub = showMonth && d.y ? `${d.y}${d.m ? ` 年 ${d.m} 月` : " 年"} · ` : "";
    return `<a class="doc-card" href="${docHref(d.id)}">
      <div class="name">${p?.fav ? '<span class="star">★</span>' : ""}${esc(label ?? d.title)}</div>
      <div class="sub">${sub}${meta}</div>
      <div class="foot">${d.src && d.src !== "其他" ? `<span class="chip">${esc(d.src)}</span>` : ""}${markCount[d.id] ? `<span class="small muted">✎ ${markCount[d.id]}</span>` : ""}<span class="spacer"></span>
        ${p?.done ? `<span class="small done">已读完</span>` : p?.pct > 0 ? `<span class="doc-pct" title="已读 ${Math.round(p.pct)}%"><i style="width:${Math.round(p.pct)}%"></i></span>` : ""}</div>
    </a>`;
  }
  const section = (title, list, opts = {}, note = "") => `<div class="doc-sec"><div class="doc-sec-h"><h3>${esc(title)}</h3>
      <span class="small muted">${list.length} 份${note ? " · " + esc(note) : ""}</span></div><div class="doc-grid">${list.map((d) => card(d, opts)).join("")}</div></div>`;

  function navBtn(key, value, label, n, cls = "") {
    return `<button data-nav="${esc(key)}" data-val="${esc(value)}" class="${cls}${(st.sel[key] ?? "") === value ? " active" : ""}">${label}<small>${n}</small></button>`;
  }

  // ---------------------------------------------------------------- 月度时政：年 → 月
  function monthTab() {
    const all = secItems("月度时政");
    const srcs = SRC_ORDER.filter((s) => all.some((d) => d.src === s));
    const pool = st.src === "全部" ? all : all.filter((d) => d.src === st.src);
    const years = [...new Set(pool.map((d) => d.y || 0))].sort((a, b) => b - a);
    if (!years.length) return emptyTab();
    let year = +(st.sel.month ?? years[0]);
    if (!years.includes(year)) year = years[0];
    st.sel.month = String(year);
    const side = years.map((y) => navBtn("month", String(y), y ? `${y} 年` : "未标年份", pool.filter((d) => (d.y || 0) === y).length)).join("");
    const inYear = pool.filter((d) => (d.y || 0) === year);
    const months = [...new Set(inYear.map((d) => d.m))].sort((a, b) => b - a);
    const order = (d) => [d.half === "上" ? 0 : d.half === "下" ? 2 : 1, SRC_ORDER.indexOf(d.src), d.kind === "刷题" ? 1 : 0, d.title];
    const cmp = (a, b) => { const x = order(a), y = order(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1; return 0; };
    const body = months.map((m) => {
      const list = inYear.filter((d) => d.m === m).sort(cmp);
      return section(m ? `${year} 年 ${m} 月` : `${year} 年（未标月份）`, list);
    }).join("");
    return `<div class="lib-layout"><div class="card lib-side" style="padding:12px 8px">
        <h4>按机构</h4><div class="news-srcs">${["全部", ...srcs].map((s) => `<button data-src="${esc(s)}" class="${st.src === s ? "active" : ""}" title="${esc(SRC_NOTE[s] || "")}">${esc(s)}<small>${s === "全部" ? all.length : all.filter((d) => d.src === s).length}</small></button>`).join("")}</div>
        <h4>按年份</h4>${side}</div>
      <div class="card">${body}</div></div>`;
  }

  // ---------------------------------------------------------------- 时政专题：按主题
  function topicTab() {
    const all = secItems("时政专题");
    if (!all.length) return emptyTab();
    const topics = [...new Set(all.map((d) => d.topic || "其他专题"))].sort((a, b) => all.filter((d) => d.topic === b).length - all.filter((d) => d.topic === a).length);
    const cur = st.sel.topic && (st.sel.topic === "全部" || topics.includes(st.sel.topic)) ? st.sel.topic : "全部";
    st.sel.topic = cur;
    const side = navBtn("topic", "全部", "全部专题", all.length) + topics.map((t) => navBtn("topic", t, esc(t), all.filter((d) => (d.topic || "其他专题") === t).length)).join("");
    const show = cur === "全部" ? topics : [cur];
    const byYear = (a, b) => (b.y || 0) - (a.y || 0) || a.title.localeCompare(b.title, "zh-CN", { numeric: true });
    const body = show.map((t) => section(t, all.filter((d) => (d.topic || "其他专题") === t).sort(byYear), { showMonth: true })).join("");
    return `<div class="lib-layout"><div class="card lib-side" style="padding:12px 8px">${side}</div><div class="card">${body}</div></div>`;
  }

  // ---------------------------------------------------------------- 时政题库
  function bankTab() {
    const all = secItems("时政题库");
    const withQ = items.filter((d) => d.sec === "月度时政" && d.nq);
    const nMonthQ = withQ.reduce((a, d) => a + d.nq, 0);
    const groups = [["时政题", "时政题集"], ["专题题", "专题题集"], ["公基综合", "公基综合"]];
    const body = groups.map(([k, label]) => {
      const list = all.filter((d) => d.topic === k).sort((a, b) => (b.y || 0) - (a.y || 0) || b.m - a.m);
      return list.length ? section(label, list, { showMonth: true }) : "";
    }).join("");
    const total = all.reduce((a, d) => a + d.nq, 0);
    const scope = st.drillScope || "6";
    return `<div class="card news-drill">
        <div class="doc-sec-h"><h3>随机刷时政题</h3><span class="small muted">从全部讲义、题集里抽有答案的题，做完看对错和解析</span></div>
        <div class="row" style="gap:12px;flex-wrap:wrap">
          <span class="small ink2">范围</span><div class="seg" id="dr-scope">${[["3", "最近 3 个月"], ["6", "最近半年"], ["12", "最近一年"], ["0", "全部"]].map(([k, l]) =>
            `<button data-k="${k}" class="${scope === k ? "active" : ""}">${l}</button>`).join("")}</div>
          <span class="small ink2">题量</span><div class="seg" id="dr-n">${[10, 20, 50].map((k) => `<button data-k="${k}" class="${(st.drillN || 20) === k ? "active" : ""}">${k}</button>`).join("")}</div>
          <button class="btn primary" id="dr-go">开始</button></div></div>
      <div class="card mt">
        <p class="small ink2" style="margin:0 0 14px">题都能直接点选项作答，选好按 <kbd>Enter</kbd> 看答案和解析（答案来自资料本身）。题集共 <b>${total}</b> 道；
          另外月度讲义里还有随堂题 <b>${nMonthQ}</b> 道，在“月度时政”各月讲义里做，或者用上面的随机刷题。</p>
        ${body || `<div class="empty">还没有整理出题库</div>`}
        ${withQ.length ? section("带随堂题的月度讲义（最近）", withQ.sort((a, b) => b.y - a.y || b.m - a.m).slice(0, 12), { showMonth: true }) : ""}
      </div>`;
  }

  // ---------------------------------------------------------------- 人民日报精读：按月 → 每天
  function readTab() {
    const all = secItems("人民日报精读");
    if (!all.length) return emptyTab();
    const months = [...new Set(all.map((d) => (d.date || "").slice(0, 7)))].sort().reverse();
    const cur = months.includes(st.sel.read) ? st.sel.read : months[0];
    st.sel.read = cur;
    const side = months.map((k) => navBtn("read", k, ymLabel(k), all.filter((d) => d.date.startsWith(k)).length)).join("");
    const list = all.filter((d) => d.date.startsWith(cur)).sort((a, b) => (a.date < b.date ? 1 : -1));
    const done = list.filter((d) => prog[d.id]?.done).length;
    const rows = list.map((d) => {
      const p = prog[d.id];
      return `<a class="news-row${p?.done ? " is-done" : ""}" href="${docHref(d.id)}">
        <span class="news-date"><b>${+d.date.slice(8)}</b><small>${+d.date.slice(5, 7)} 月 · 周${weekday(d.date)}</small></span>
        <span class="news-title">${p?.fav ? '<span class="star">★</span>' : ""}${esc(d.title)}${d.kind ? ` <span class="chip">${esc(d.kind)}</span>` : ""}</span>
        <span class="small muted">${fmtChars(d.chars)}</span>
        ${p?.done ? `<span class="small done">已读</span>` : p?.pct > 0 ? `<span class="doc-pct"><i style="width:${Math.round(p.pct)}%"></i></span>` : `<span class="small muted">未读</span>`}
      </a>`;
    }).join("");
    return `<div class="lib-layout"><div class="card lib-side" style="padding:12px 8px">${side}</div>
      <div class="card"><div class="doc-sec-h"><h3>${ymLabel(cur)}</h3><span class="small muted">${list.length} 篇 · 已读 ${done} 篇 · 每篇：原文、结构笔记、思维导图（部分有拆解报告和仿写范文）</span></div>
        <div class="news-rows">${rows}</div></div></div>`;
  }

  // ---------------------------------------------------------------- 成语积累
  function cyTab() {
    const days = data.days || [];
    if (!days.length) return emptyTab("成语积累");
    const months = [...new Set(days.map((d) => d.date.slice(0, 7)))].sort().reverse();
    const cur = months.includes(st.sel.cy) ? st.sel.cy : months[0];
    st.sel.cy = cur;
    const done = cyDone();
    const total = days.reduce((a, d) => a + d.n, 0);
    const side = navBtn("cy", "__all", "成语总表", st.cyAll ? st.cyAll.length : "…", "grp") +
      `<h4>按月</h4>` + months.map((k) => navBtn("cy", k, ymLabel(k), days.filter((d) => d.date.startsWith(k)).length)).join("");
    if (st.sel.cy === "__all") return `<div class="lib-layout"><div class="card lib-side" style="padding:12px 8px">${side}</div><div class="card" id="cy-main">${cyAllBlock()}</div></div>`;
    const drills = items.filter((d) => d.sec === "成语演练" && (ym(d.y, d.m) === cur || !d.m));
    const mdays = days.filter((d) => d.date.startsWith(cur)).sort((a, b) => (a.date < b.date ? 1 : -1));
    const nDone = mdays.filter((d) => done[d.date]).length;
    return `<div class="lib-layout"><div class="card lib-side" style="padding:12px 8px">${side}</div>
      <div class="stack" style="gap:16px">
        <div class="card"><div class="doc-sec-h"><h3>${ymLabel(cur)}</h3>
          <span class="small muted">${mdays.length} 天 · ${mdays.reduce((a, d) => a + d.n, 0)} 个词 · 已学 ${nDone} 天（全部共 ${days.length} 天、${total} 个词）</span>
          <span class="spacer"></span>
          <div class="seg" id="cy-mode"><button data-m="read" class="${st.cyMode === "read" ? "active" : ""}">阅读</button><button data-m="test" class="${st.cyMode === "test" ? "active" : ""}" title="例句里的成语挖成空，自己回想后点开对答案">挖空自测</button></div></div>
          <p class="small ink2" style="margin:0 0 12px">每天的句子摘自人民日报，标出的词就是当天积累的成语和实词，下面是释义。逻辑填空常考这些词在语境里的意思和搭配。</p>
          <div class="cy-days" id="cy-days">${mdays.map((d) => cyDayRow(d)).join("")}</div></div>
        ${drills.length ? `<div class="card">${section("随堂演练（逻辑填空题，可直接作答）", drills.filter((d) => d.kind !== "成语手册"))}
          ${drills.some((d) => d.kind === "成语手册") ? section("成语手册", drills.filter((d) => d.kind === "成语手册")) : ""}</div>` : ""}
      </div></div>`;
  }

  function cyDayRow(d) {
    const open = st.cyOpen === d.date;
    const done = cyDone()[d.date];
    const det = st.cyData[d.date.slice(0, 7)]?.find((x) => x.date === d.date);
    const preview = det ? det.words.slice(0, 8).map((w) => w.w).join("、") + (det.words.length > 8 ? "…" : "") : "";
    return `<div class="cy-day${open ? " open" : ""}${done ? " is-done" : ""}" data-day="${d.date}">
      <button class="cy-day-h" data-open="${d.date}">
        <span class="news-date"><b>${+d.date.slice(8)}</b><small>周${weekday(d.date)}</small></span>
        <span class="cy-prev">${esc(preview || `${d.n} 个词`)}</span>
        <span class="small muted">${d.s} 句 · ${d.n} 词</span>
        ${done ? `<span class="small done">已学</span>` : ""}
        <span class="caret">${open ? "▾" : "▸"}</span></button>
      ${open ? `<div class="cy-body">${det ? cyDayBody(det) : `<div class="empty">加载中…</div>`}</div>` : ""}</div>`;
  }

  function marked(text, words, test, date, si) {
    // 句子里的成语：阅读模式加粗高亮；自测模式挖空（点一下显示）
    const ws = [...new Set(words)].sort((a, b) => b.length - a.length);
    if (!ws.length) return esc(text);
    const re = new RegExp(ws.map((w) => reEsc(esc(w))).join("|"), "g");
    let k = 0;
    return esc(text).replace(re, (m) => test
      ? `<button class="cy-blank" data-w="${m}" title="点一下看答案">${"＿".repeat(Math.min(m.length, 6))}</button>`
      : `<mark class="cy-w" data-k="${date}-${si}-${k++}">${m}</mark>`);
  }

  function cyDayBody(det) {
    const test = st.cyMode === "test";
    const done = cyDone()[det.date];
    const sents = det.sents.map((s, i) => `<li><span class="cy-n">${s.n}</span><span>${marked(s.t, s.w, test, det.date, i)}</span></li>`).join("");
    const words = det.words.map((w) => `<div class="cy-def${test ? " hide" : ""}"><b>${esc(w.w)}</b><span>${esc(w.m)}</span>
        <button class="btn sm ghost" data-keep="${esc(w.w)}" title="收进“我的积累”，会出现在闪卡复习里">＋积累</button></div>`).join("");
    return `<ol class="cy-sents">${sents || `<li class="muted">这一天没有识别出例句</li>`}</ol>
      <div class="cy-defs-h"><b>释义</b>${test ? `<button class="btn sm ghost" data-reveal="1">显示全部释义</button>` : ""}<span class="spacer"></span>
        <button class="btn sm ${done ? "" : "primary"}" data-done="${det.date}">${done ? "✓ 已学（点一下取消）" : "标记已学"}</button></div>
      <div class="cy-defs">${words || `<div class="muted">这一天没有识别出释义</div>`}</div>`;
  }

  function cyAllBlock() {
    if (!st.cyAll) return `<div class="empty">正在汇总全部成语…</div>`;
    const f = st.cyFilter;
    const list = f ? st.cyAll.filter((w) => w.w.includes(f) || w.m.includes(f)) : st.cyAll;
    return `<div class="doc-sec-h"><h3>成语总表</h3><span class="small muted">${st.cyAll.length} 个（去重），出现次数多的排前面</span><span class="spacer"></span>
        <button class="btn sm" id="cy-rand">随机抽 10 个自测</button></div>
      <input type="search" id="cy-flt" class="mb" placeholder="查成语或释义里的字" value="${esc(f)}" autocomplete="off" style="width:100%;max-width:360px">
      <div id="cy-rand-box"></div>
      <div class="cy-defs">${list.slice(0, 600).map((w) => `<div class="cy-def"><b>${esc(w.w)}</b><span>${esc(w.m)}${w.ex ? `<em class="cy-ex">例：${marked(w.ex, [w.w], false, "", 0)}</em>` : ""}</span>
        <span class="small muted" title="${esc(w.dates.join("、"))}">${w.dates.length > 1 ? `出现 ${w.dates.length} 次` : w.dates[0].slice(5)}</span>
        <button class="btn sm ghost" data-keep="${esc(w.w)}">＋积累</button></div>`).join("")}
        ${list.length > 600 ? `<div class="small muted mt">还有 ${list.length - 600} 个，用上面的框查找</div>` : ""}</div>`;
  }

  function emptyTab(what = "资料") {
    const job = data.job || {};
    return `<div class="card empty"><h3>${esc(what)}还没整理好</h3>
      <p>${job.running ? "正在后台整理，扫描件要识别文字，比较慢；整理好的会陆续出现。" : "点上面的“整理时政晨读”。"}</p></div>`;
  }

  // ---------------------------------------------------------------- 搜索
  function hitsBlock() {
    const r = st.results;
    if (!r) return "";
    const groups = new Map();
    const cy = [];
    for (const h of r) {
      if (h.cy) { cy.push(h); continue; }
      if (!byId[h.doc]) continue;
      if (!groups.has(h.doc)) groups.set(h.doc, []);
      groups.get(h.doc).push(h);
    }
    const terms = st.query.split(/\s+/).filter(Boolean).map((t) => reEsc(esc(t)));
    const re = new RegExp(terms.join("|"), "g");
    const hi = (s) => esc(s).replace(re, (m) => `<mark>${m}</mark>`);
    const n = [...groups.values()].reduce((a, b) => a + b.length, 0);
    return `<div class="card"><div class="card-head"><h3>“${esc(st.query)}”</h3>
        <span class="small muted">${groups.size || cy.length ? `${groups.size} 份资料 ${n} 处${cy.length ? `，成语积累 ${cy.length} 条` : ""}` : "没有找到"}</span>
        <span class="spacer"></span><button class="btn sm ghost" id="clear-hits">收起</button></div>
      ${cy.length ? `<div class="hit"><b>成语积累</b>${cy.slice(0, 8).map((h) => `<a class="snip" href="#/news" data-goto-cy="${h.cy}">${h.cy} · ${hi(h.snippet)}</a>`).join("")}</div>` : ""}
      ${[...groups].slice(0, 60).map(([id, hs]) => { const d = byId[id]; return `<div class="hit"><div class="row"><a href="${docHref(id, hs[0].seq, st.query)}"><b>${esc(d.title)}</b></a>
          <span class="small muted">${esc(d.sec)}${d.y ? ` · ${d.date || ym(d.y, d.m)}` : ""} · ${hs.length} 处</span></div>
        ${hs.slice(0, 3).map((h) => `<a class="snip" href="${docHref(id, h.seq, st.query)}">${hi(h.snippet)}</a>`).join("")}</div>`; }).join("")}
    </div>`;
  }

  // ---------------------------------------------------------------- 整页
  function jobBox(job) {
    if (job?.running && /时政/.test(job.name || "")) return jobProgressHTML(job, "整理好的会陆续出现，可以先看");
    return `<div id="job"></div>`;
  }

  function tabBody() {
    return { month: monthTab, topic: topicTab, bank: bankTab, read: readTab, cy: cyTab }[st.tab]();
  }

  function counts() {
    const c = (sec) => secItems(sec).length;
    return { month: c("月度时政"), topic: c("时政专题"), bank: c("时政题库"), read: c("人民日报精读"), cy: (data.days || []).length };
  }

  function draw() {
    const c = counts();
    const latest = secItems("月度时政").filter((d) => d.y && d.m).sort((a, b) => b.y - a.y || b.m - a.m)[0];
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">时政晨读</div><h1>时政热点与每日晨读</h1>
        <p>超格、小黑、粉笔的月度时政讲义，两会、一号文件、全会等专题，时政题库，人民日报每日精读和成语积累——都整理成了文字，带目录，题目可以直接作答。${latest ? `最新到 ${latest.y} 年 ${latest.m} 月。` : ""}</p></div>
        <button class="btn" data-job="shizheng" title="资料文件夹里新增了时政、晨读资料后点这里，只处理新增或改动的文件">整理时政晨读</button></div>
      ${jobBox(data.job)}
      <form class="card lib-search mt" id="sf">
        <input type="search" id="q" placeholder="搜时政内容，如：新质生产力、十五五、神舟、低空经济、乡村振兴" value="${esc(st.query)}" autocomplete="off">
        <button class="btn primary">搜索</button>
      </form>
      <div id="hits" class="mt">${hitsBlock()}</div>
      <div class="tabs mt">${TABS.map(([k, label]) => `<button data-tab="${k}" class="${st.tab === k ? "active" : ""}">${label} <small class="muted">${c[k]}</small></button>`).join("")}</div>
      <div id="body">${tabBody()}</div>`;
    bind();
  }

  function redrawBody() {
    el.querySelector("#body").innerHTML = tabBody();
    bindBody();
  }

  async function loadMonth(m) {
    if (st.cyData[m]) return;
    try { st.cyData[m] = (await apiGet(`/api/news/chengyu?month=${m}`)).days; } catch (e) { toast(e.message); st.cyData[m] = []; }
  }

  async function loadAll() {
    if (st.cyAll) return;
    try { st.cyAll = (await apiGet("/api/news/chengyu_all")).words; } catch (e) { toast(e.message); st.cyAll = []; }
  }

  async function keepWord(w) {
    let def = null;
    for (const days of Object.values(st.cyData)) for (const d of days) { const x = d.words.find((y) => y.w === w); if (x) { def = { m: x.m, ex: d.sents.find((s) => s.w.includes(w))?.t, date: d.date }; break; } }
    if (!def && st.cyAll) { const x = st.cyAll.find((y) => y.w === w); if (x) def = { m: x.m, ex: x.ex, date: x.dates[0] }; }
    try {
      await apiPost("/api/notebook", { kind: "好词好句", title: w, content: (def?.m || "") + (def?.ex ? `\n例：${def.ex}` : ""),
        source: `人民日报成语积累 ${def?.date || ""}`.trim(), tags: "成语" });
      toast(`“${w}”已收进我的积累`);
    } catch (e) { toast(e.message); }
  }

  // ---------------------------------------------------------------- 随机刷时政题
  async function startDrill() {
    const latest = items.filter((d) => d.y && d.m).reduce((a, d) => Math.max(a, d.y * 12 + d.m - 1), 0);
    const back = +(st.drillScope || "6");
    const since = back && latest ? (() => { const v = latest - back + 1; return `${Math.floor(v / 12)}-${String((v % 12) + 1).padStart(2, "0")}`; })() : "";
    let r;
    try { r = await apiGet(`/api/news/quiz?n=${st.drillN || 20}&since=${since}`); } catch (e) { toast(e.message); return; }
    if (!r.items.length) { toast("这个范围里还没有带答案的题"); return; }
    const run = { qs: r.items, i: 0, picks: r.items.map(() => null), started: Date.now(), since, total: r.total };
    drawDrill(run);
  }

  const isMulti = (q) => q.ans.length > 1 || /多选|不定项/.test(q.stem);
  const qkeyOf = (q) => (q.stem || "").replace(/⦅([^⁄⦆]*)⁄([^⦆]*)⦆/g, "$1/$2").replace(/\s+/g, "").slice(0, 40);

  function drawDrill(run) {
    const body = el.querySelector("#body");
    if (run.i >= run.qs.length) {
      const right = run.qs.filter((q, k) => run.picks[k] === q.ans).length;
      const mins = Math.max(1, Math.round((Date.now() - run.started) / 60000));
      apiPost("/api/study_log", { module: "常识判断", minutes: mins, source: "时政刷题" }).catch(() => {});
      body.innerHTML = `<div class="card"><div class="doc-sec-h"><h3>做完了：${run.qs.length} 题对 ${right} 题</h3>
          <span class="small muted">正确率 ${Math.round((right / run.qs.length) * 100)}% · 用时约 ${mins} 分钟</span><span class="spacer"></span>
          <button class="btn primary" id="dr-again">再来一组</button><button class="btn ghost" id="dr-back">返回题库</button></div>
        ${run.qs.map((q, k) => run.picks[k] === q.ans ? "" : `<div class="hit"><div class="small muted">${esc(q.ym)} · ${esc(q.title)}</div>
          <div>${esc(q.stem.slice(0, 120))}${q.stem.length > 120 ? "…" : ""}</div>
          <div class="small">你选 <b style="color:var(--bad)">${esc(run.picks[k] || "—")}</b>，答案 <b style="color:var(--good)">${esc(q.ans)}</b>
            · <a href="${docHref(q.doc, q.seq)}">回到讲义看这道题</a></div></div>`).join("") || `<p class="done">全对！</p>`}</div>`;
      body.querySelector("#dr-again").onclick = startDrill;
      body.querySelector("#dr-back").onclick = redrawBody;
      return;
    }
    const q = run.qs[run.i];
    const multi = isMulti(q);
    const chosen = new Set();
    body.innerHTML = `<div class="card news-q"><div class="doc-sec-h"><h3>第 ${run.i + 1} / ${run.qs.length} 题</h3>
        <span class="small muted">${esc(q.ym)} · ${esc(q.title)}</span><span class="spacer"></span><button class="btn sm ghost" id="dr-quit">结束</button></div>
      <div class="rd-q" style="margin:0"><div class="q-stem">${multi ? `<span class="chip warn">多选</span> ` : ""}${esc(q.stem).replace(/\n/g, "<br>")}</div>
        <div class="q-opts">${q.opts.map(([a, o]) => `<button class="q-opt" data-o="${a}"><b>${a}</b><span>${esc(o)}</span></button>`).join("")}</div>
        <div class="q-foot"><span class="q-res small muted">${multi ? "可以选多个，选好点“确定”" : "点选项作答"}</span><span class="spacer"></span>
          <button class="btn sm primary" id="dr-ok"${multi ? "" : " hidden"}>确定</button><button class="btn sm primary" id="dr-next" hidden>下一题 →</button></div>
        <div class="q-exp" hidden></div></div></div>`;
    const opts = [...body.querySelectorAll(".q-opt")];
    const finish = () => {
      const pick = [...chosen].sort().join("");
      run.picks[run.i] = pick;
      const ok = pick === q.ans;
      opts.forEach((b) => {
        b.disabled = true;
        if (q.ans.includes(b.dataset.o)) b.classList.add("ok");
        else if (chosen.has(b.dataset.o)) b.classList.add("bad");
      });
      body.querySelector(".q-res").innerHTML = ok ? `<b class="done">答对了</b>` : `<b style="color:var(--bad)">答错了</b>，正确答案 <b>${esc(q.ans)}</b>`;
      const exp = body.querySelector(".q-exp");
      exp.hidden = false;
      exp.innerHTML = q.exp.length ? q.exp.map((t) => `<p>${esc(t)}</p>`).join("") : `<p class="muted">资料没有给解析。<a href="${docHref(q.doc, q.seq)}">回到讲义看相关内容</a></p>`;
      body.querySelector("#dr-ok").hidden = true;
      body.querySelector("#dr-next").hidden = false;
      body.querySelector("#dr-next").focus();
      apiPost("/api/docquiz", { doc: q.doc, qkey: qkeyOf(q), choice: pick, correct: ok }).catch(() => {});
    };
    opts.forEach((b) => (b.onclick = () => {
      if (multi) { chosen.has(b.dataset.o) ? chosen.delete(b.dataset.o) : chosen.add(b.dataset.o); b.classList.toggle("sel", chosen.has(b.dataset.o)); return; }
      chosen.add(b.dataset.o);
      finish();
    }));
    body.querySelector("#dr-ok").onclick = () => { if (chosen.size) finish(); else toast("先选选项"); };
    body.querySelector("#dr-next").onclick = () => { run.i++; drawDrill(run); };
    body.querySelector("#dr-quit").onclick = () => { run.qs = run.qs.slice(0, run.i + (run.picks[run.i] != null ? 1 : 0)); run.i = run.qs.length; drawDrill(run); };
    body.scrollIntoView({ block: "nearest" });
  }

  function bindBody() {
    const body = el.querySelector("#body");
    body.querySelectorAll("#dr-scope button").forEach((x) => (x.onclick = () => { st.drillScope = x.dataset.k; body.querySelectorAll("#dr-scope button").forEach((b) => b.classList.toggle("active", b === x)); }));
    body.querySelectorAll("#dr-n button").forEach((x) => (x.onclick = () => { st.drillN = +x.dataset.k; body.querySelectorAll("#dr-n button").forEach((b) => b.classList.toggle("active", b === x)); }));
    const go = body.querySelector("#dr-go");
    if (go) go.onclick = startDrill;
    body.querySelectorAll("[data-nav]").forEach((x) => (x.onclick = async () => {
      st.sel[x.dataset.nav] = x.dataset.val;
      st.cyOpen = null;
      remember();
      if (x.dataset.nav === "cy" && x.dataset.val === "__all") { redrawBody(); await loadAll(); }
      else if (x.dataset.nav === "cy") await loadMonth(x.dataset.val);
      redrawBody();
      el.querySelector("#body").scrollIntoView({ block: "nearest" });
    }));
    body.querySelectorAll("[data-src]").forEach((x) => (x.onclick = () => { st.src = x.dataset.src; remember(); redrawBody(); }));
    const mode = body.querySelector("#cy-mode");
    if (mode) mode.querySelectorAll("button").forEach((x) => (x.onclick = () => { st.cyMode = x.dataset.m; remember(); redrawBody(); }));
    body.querySelectorAll("[data-open]").forEach((x) => (x.onclick = async () => {
      const d = x.dataset.open;
      st.cyOpen = st.cyOpen === d ? null : d;
      await loadMonth(d.slice(0, 7));
      redrawBody();
      body.isConnected && el.querySelector(`[data-day="${d}"]`)?.scrollIntoView({ block: "nearest" });
    }));
    body.querySelectorAll(".cy-blank").forEach((x) => (x.onclick = () => { x.textContent = x.dataset.w; x.classList.add("shown"); }));
    body.querySelectorAll("[data-reveal]").forEach((x) => (x.onclick = () => {
      x.closest(".cy-body").querySelectorAll(".cy-def.hide").forEach((d) => d.classList.remove("hide"));
      x.closest(".cy-body").querySelectorAll(".cy-blank").forEach((b) => { b.textContent = b.dataset.w; b.classList.add("shown"); });
    }));
    body.querySelectorAll("[data-done]").forEach((x) => (x.onclick = () => {
      const all = { ...cyDone() };
      if (all[x.dataset.done]) delete all[x.dataset.done]; else all[x.dataset.done] = 1;
      store.set("cy_done", all);
      if (all[x.dataset.done]) apiPost("/api/study_log", { module: "言语理解与表达", minutes: 5, source: "成语积累" }).catch(() => {});
      redrawBody();
    }));
    body.querySelectorAll("[data-keep]").forEach((x) => (x.onclick = (e) => { e.preventDefault(); keepWord(x.dataset.keep); }));
    const flt = body.querySelector("#cy-flt");
    if (flt) {
      let t = null;
      flt.oninput = () => { clearTimeout(t); t = setTimeout(() => { st.cyFilter = flt.value.trim(); const pos = flt.selectionStart; redrawBody(); const n = el.querySelector("#cy-flt"); n.focus(); n.setSelectionRange(pos, pos); }, 250); };
    }
    const rnd = body.querySelector("#cy-rand");
    if (rnd) rnd.onclick = () => {
      const pick = shuffle(st.cyAll.slice()).slice(0, 10);
      body.querySelector("#cy-rand-box").innerHTML = `<div class="cy-quiz">${pick.map((w) => `<div class="cy-def"><button class="cy-blank big" data-w="${esc(w.w)}">看释义想成语 · 点开</button>
          <span>${esc(w.m)}</span></div>`).join("")}</div>`;
      body.querySelectorAll("#cy-rand-box .cy-blank").forEach((x) => (x.onclick = () => { x.textContent = x.dataset.w; x.classList.add("shown"); }));
    };
  }

  function bind() {
    el.querySelectorAll("[data-tab]").forEach((x) => (x.onclick = async () => {
      st.tab = x.dataset.tab;
      remember();
      el.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("active", b === x));
      if (st.tab === "cy") {
        if (st.sel.cy === "__all") await loadAll();
        else await loadMonth(st.sel.cy || (data.days || []).map((d) => d.date.slice(0, 7)).sort().pop());
      }
      redrawBody();
    }));
    el.querySelector("#sf").onsubmit = async (e) => {
      e.preventDefault();
      const text = el.querySelector("#q").value.trim();
      if (!text) { toast("先输入要搜的内容"); return; }
      el.querySelector("#hits").innerHTML = `<div class="card empty">正在搜索…</div>`;
      try { st.results = (await apiGet(`/api/news/search?q=${encodeURIComponent(text)}`)).hits; st.query = text; } catch (err) { toast(err.message); st.results = null; }
      el.querySelector("#hits").innerHTML = hitsBlock();
      bindHits();
    };
    el.querySelectorAll("[data-job]").forEach((x) => (x.onclick = async () => {
      try {
        const r = await apiPost("/api/jobs/start", { job: x.dataset.job });
        toast(r.queued ? `已排队：等前面的整理完成后开始“${r.name}”` : "开始整理；扫描件要识别文字，可能需要较长时间", 3500);
        poll();
      } catch (err) { toast(err.message, 4000); }
    }));
    bindHits();
    bindBody();
  }

  function bindHits() {
    const ch = el.querySelector("#clear-hits");
    if (ch) ch.onclick = () => { st.results = null; st.query = ""; el.querySelector("#hits").innerHTML = ""; };
    el.querySelectorAll("[data-goto-cy]").forEach((x) => (x.onclick = async (e) => {
      e.preventDefault();
      const d = x.dataset.gotoCy;
      st.tab = "cy"; st.sel.cy = d.slice(0, 7); st.cyOpen = d; remember();
      await loadMonth(st.sel.cy);
      el.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === "cy"));
      redrawBody();
      el.querySelector(`[data-day="${d}"]`)?.scrollIntoView({ block: "center" });
    }));
  }

  async function poll() {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (!el.isConnected) { clearInterval(pollTimer); return; }
      const job = await apiGet("/api/jobs").catch(() => null);
      if (!job) return;
      const box = el.querySelector("#job");
      if (job.running) { if (box) box.outerHTML = jobBox(job); }
      else { clearInterval(pollTimer); toast(jobDoneText(job, "时政晨读整理完成"), 4000); render(el, ctx); }
    }, 2000);
  }

  if (st.tab === "cy") {
    const months = (data.days || []).map((d) => d.date.slice(0, 7)).sort();
    if (st.sel.cy === "__all") await loadAll();
    else await loadMonth(st.sel.cy && months.includes(st.sel.cy) ? st.sel.cy : months.pop());
  }
  draw();
  if (data.job?.running && /时政/.test(data.job.name || "")) poll();
  return () => clearInterval(pollTimer);
}
