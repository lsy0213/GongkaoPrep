// 资料库：讲义、笔记、常识、申论素材整理成的文字资料，按“行测各模块 / 申论 / 省情 / 面试”分类，点开在内置阅读器里读。
// 真题卷、千题册、答案解析不在这里，它们在“真题卷”“刷题”里；#/library/view/<fid> 只给真题“原卷”按钮用。
import { apiGet, apiPost, esc, jobDoneText, jobProgressHTML, store, toast } from "../lib.js";
import { bindHeadSearch, headSearchBox, hlRegex } from "../headsearch.js";

const SUBJ_MODULE = { "言语": "言语理解与表达", "数量": "数量关系", "判断": "判断推理", "资料": "资料分析", "常识": "常识判断", "申论": "申论", "面试": "面试" };
const COLOR_NAME = { y: "黄", g: "绿", p: "粉", b: "蓝" };
const GROUP_LABEL = { "行测": "行测", "申论": "申论", "省情": "省情（省考）", "面试": "面试", "其他": "其他" };
const MINE = ["在读", "收藏", "已读完", "标注"];

function fmtChars(n) {
  return n >= 10000 ? `${(n / 10000).toFixed(1)} 万字` : `${n} 字`;
}

const docHref = (id, seq, q) => `#/library/doc/${encodeURIComponent(id)}${seq != null ? `?s=${seq}${q ? `&q=${encodeURIComponent(q)}` : ""}` : ""}`;
const sortKey = (t) => t.replace(/^\s*【[^】]{1,6}】\s*/, "");
const byTitle = (a, b) => sortKey(a.title).localeCompare(sortKey(b.title), "zh-CN", { numeric: true });

let pollTimer = null;
let searchOff = null;
// 搜索框空着时给的常搜词
const HOT = ["基期量", "主旨概括", "削弱论证", "工程问题", "乡村振兴", "归纳概括", "枫桥经验"];

export async function render(el, ctx) {
  clearInterval(pollTimer);
  searchOff?.();
  searchOff = null;
  if (ctx.parts[1] === "doc" && ctx.parts[2]) {
    const { openReader } = await import("../reader.js");
    try {
      return await openReader(el, ctx.parts[2], ctx.query.s != null ? +ctx.query.s : undefined, ctx.query.q);
    } catch (e) {
      el.innerHTML = `<div class="card empty"><h3>打不开这份资料</h3><p>${esc(e.message)}</p><a href="#/library">返回资料库</a></div>`;
      return;
    }
  }
  if (ctx.parts[1] === "view" && ctx.parts[2]) return viewer(el, ctx.parts[2], +(ctx.query.p || 0));

  const data = await apiGet("/api/docs");
  const docs = data.docs;
  const prog = data.progress;
  const markCount = data.marks;
  const byId = Object.fromEntries(docs.map((d) => [d.id, d]));
  const saved = store.get("library3", {});
  // sel：all | g:行测 | s:行测/言语理解 | m:在读
  const st = { sel: saved.sel || "all", allMarks: null };

  const inSel = (d, sel) => {
    if (sel === "all") return true;
    const [k, v] = [sel.slice(0, 1), sel.slice(2)];
    if (k === "g") return d.grp === v;
    if (k === "s") return `${d.grp}/${d.sub}` === v;
    const p = prog[d.id];
    if (v === "在读") return p && !p.done && p.pct > 0;
    if (v === "收藏") return p?.fav;
    if (v === "已读完") return p?.done;
    return false;
  };
  const count = (sel) => (sel === "m:标注" ? Object.values(markCount).reduce((a, b) => a + b, 0) : docs.filter((d) => inSel(d, sel)).length);

  const pool = () => docs.filter((d) => inSel(d, st.sel));

  function jobBox(job) {
    const pending = Math.max(0, data.total_files - docs.length);
    if (job.running) return jobProgressHTML(job);
    if (!pending && !job.error) return `<div id="job"></div>`;
    return `<div class="job-box" id="job"><div class="row">
        <span class="small ink2">${pending ? `还有 <b>${pending}</b> 份资料没整理（扫描件要识别文字，比较慢）` : ""}</span><span class="spacer"></span>
        <button class="btn sm primary" data-job="docs">继续整理</button></div>
        ${job.error ? `<div class="small mt" style="color:var(--bad)">上次整理出错：${esc(job.error)}</div>` : ""}</div>`;
  }

  function continueBlock() {
    const list = docs.filter((d) => prog[d.id] && !prog[d.id].done && prog[d.id].pct > 0 && prog[d.id].pct < 100)
      .sort((a, b) => (prog[b.id].updated_at > prog[a.id].updated_at ? 1 : -1)).slice(0, 4);
    if (!list.length) return "";
    return `<div class="lib-cont">${list.map((d) => `<a class="lib-cont-i" href="${docHref(d.id)}">
        <span class="small muted">${esc(d.sub || d.grp)}</span>
        <b>${esc(d.title)}</b>
        <div class="progress"><i style="width:${Math.round(prog[d.id].pct)}%"></i></div>
        <span class="small muted">已读 ${Math.round(prog[d.id].pct)}% · 继续阅读 →</span></a>`).join("")}</div>`;
  }

  function card(d) {
    const p = prog[d.id];
    const empty = d.error || !d.chars;
    const meta = empty ? `<span style="color:var(--warn)">${d.error ? "整理出错" : "没有识别出文字"}</span>`
      : [fmtChars(d.chars), d.nq ? `<span class="doc-q">例题 ${d.nq} 道</span>` : "", d.toc_n ? `目录 ${d.toc_n} 条` : ""].filter(Boolean).join(" · ");
    return `<a class="doc-card${empty ? " is-empty" : ""}" href="${docHref(d.id)}" title="${esc(d.rel)}">
      <div class="name">${p?.fav ? '<span class="star">★</span>' : ""}${esc(d.title)}</div>
      <div class="sub">${meta}</div>
      <div class="foot">${markCount[d.id] ? `<span class="small muted">✎ ${markCount[d.id]}</span>` : ""}<span class="spacer"></span>
        ${p?.done ? `<span class="small done">已读完</span>` : p?.pct > 0 ? `<span class="doc-pct" title="已读 ${Math.round(p.pct)}%"><i style="width:${Math.round(p.pct)}%"></i></span>` : ""}</div>
    </a>`;
  }

  function section(title, list, n) {
    return `<div class="doc-sec"><div class="doc-sec-h"><h3>${esc(title)}</h3><span class="small muted">${n ?? list.length} 份</span></div>
      <div class="doc-grid">${list.map(card).join("")}</div></div>`;
  }

  function listBlock() {
    const ds = pool();
    if (!ds.length) {
      return `<div class="card empty">${docs.length ? "这里还没有资料" : `<h3>资料还没整理</h3><p>点上面的“继续整理”。</p>`}</div>`;
    }
    const k = st.sel.slice(0, 1);
    if (k === "m" || k === "s" && !st.sel.startsWith("s:省情")) {
      const title = st.sel.slice(2).split("/").pop();
      return `<div class="card">${section(title, ds.slice().sort(byTitle))}</div>`;
    }
    // 全部 / 大类：按小类分段，每段直接列出资料
    const order = [];
    for (const [g, subs] of data.groups) {
      if (subs.length) subs.forEach((s) => order.push([g, s]));
      else order.push([g, null]);
    }
    const parts = [];
    for (const [g, s] of order) {
      let list = ds.filter((d) => d.grp === g && (s == null || d.sub === s));
      if (!list.length) continue;
      if (g === "省情") {
        // 省情按省份排，同一省的放一起
        list = list.sort((a, b) => a.sub.localeCompare(b.sub, "zh-CN") || byTitle(a, b));
        parts.push(section(GROUP_LABEL[g], list));
      } else {
        parts.push(section(s ? `${g} · ${s}` : GROUP_LABEL[g], list.sort(byTitle)));
      }
    }
    return `<div class="card">${parts.join("")}</div>`;
  }

  // 页头搜索：先列标题里有关键词的资料，再列正文里搜到的（每份资料一条，点开跳到第一处）
  async function runSearch(q) {
    const re = hlRegex(q);
    const hl = (t) => esc(t).replace(re, (m) => `<mark>${m}</mark>`);
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const titled = docs.filter((d) => words.every((w) => d.title.toLowerCase().includes(w))).sort(byTitle);
    const groups = new Map();
    const hits = (await apiGet(`/api/docs/search?q=${encodeURIComponent(q)}`)).hits;
    for (const h of hits) {
      if (!byId[h.doc]) continue;
      if (!groups.has(h.doc)) groups.set(h.doc, []);
      groups.get(h.doc).push(h);
    }
    if (!titled.length && !groups.size) {
      return `<div class="hs-empty">没有找到“${esc(q)}”<br><span class="small muted">换个说法，或者少打几个字试试</span></div>`;
    }
    const total = [...groups.values()].reduce((a, b) => a + b.length, 0);
    const snip = (t) => t.replace(/⦅([^⁄⦆]*)⁄([^⦆]*)⦆/g, "$1/$2");
    return `<div class="hs-list">
      ${titled.length ? `<div class="hs-label">标题含“${esc(q)}” · ${titled.length} 份</div>
        ${titled.slice(0, 5).map((d) => `<a class="hs-hit" data-go href="${docHref(d.id)}"><span class="hs-meta">${esc(d.sub || d.grp)}</span><b>${hl(d.title)}</b></a>`).join("")}` : ""}
      ${groups.size ? `<div class="hs-label"${titled.length ? ' style="padding-top:12px"' : ""}>${groups.size} 份资料的正文里提到 · 共 ${total}${hits.length >= 200 ? "+" : ""} 处${groups.size > 15 ? " · 先列前 15 份" : ""}</div>
        ${[...groups].slice(0, 15).map(([id, hs]) => `<a class="hs-hit" data-go href="${docHref(id, hs[0].seq, q)}">
          <span class="hs-meta">${esc(byId[id].sub || byId[id].grp)} · ${hs.length} 处</span>
          <b>${esc(byId[id].title)}</b><span class="snip">${hl(snip(hs[0].snippet))}</span></a>`).join("")}` : ""}
    </div>`;
  }

  function marksBlock() {
    const items = st.allMarks;
    if (!items) return `<div class="card empty">加载中…</div>`;
    if (!items.length) return `<div class="card empty"><h3>还没有标注</h3><p>在阅读器里选中文字，点颜色就能高亮，高亮还可以写笔记。</p></div>`;
    const groups = new Map();
    for (const m of items) {
      if (!groups.has(m.doc)) groups.set(m.doc, []);
      groups.get(m.doc).push(m);
    }
    return [...groups].map(([id, ms]) => `<div class="card"><div class="card-head"><h3><a href="${docHref(id)}">${esc(byId[id]?.title || ms[0].title)}</a></h3><span class="small muted">${ms.length} 处</span></div>
      ${ms.sort((a, b) => a.seq - b.seq || a.start - b.start).map((m) => `<a class="pm" href="${docHref(id, m.seq)}"><span class="dot hl-${esc(m.color)}" title="${COLOR_NAME[m.color] || ""}"></span>
        <div><div class="pm-t">${esc(m.text.slice(0, 200))}${m.text.length > 200 ? "…" : ""}</div>${m.note ? `<div class="small ink2">✎ ${esc(m.note)}</div>` : ""}
        <div class="small muted">${esc(m.created_at.slice(0, 10))}</div></div></a>`).join("")}</div>`).join("");
  }

  function navBtn(sel, label, cls = "") {
    const n = count(sel);
    return `<button data-sel="${esc(sel)}" class="${cls}${st.sel === sel ? " active" : ""}">${label}<small>${n}</small></button>`;
  }

  function nav() {
    let h = navBtn("all", "全部资料");
    for (const [g, subs] of data.groups) {
      if (!count(`g:${g}`)) continue;
      h += navBtn(`g:${g}`, GROUP_LABEL[g], "grp");
      for (const s of subs) if (count(`s:${g}/${s}`)) h += navBtn(`s:${g}/${s}`, esc(s), "subitem");
    }
    h += `<h4>我的</h4>` + MINE.map((m) => navBtn(`m:${m}`, m === "标注" ? "我的标注" : m)).join("");
    return h;
  }

  function draw(job) {
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">资料库</div><h1>我的备考资料</h1>
        <p>讲义、笔记、素材都整理成了带目录的文字：例题可以直接点选项作答、看答案和解析，填空可以直接输入；选中文字能高亮、写笔记、问 AI。<a href="#/real">去做真题卷 →</a></p></div>
        ${headSearchBox("搜资料标题或内容", "在资料库里搜索")}</div>
      ${jobBox(job)}
      ${continueBlock()}
      <div class="lib-layout mt">
        <div class="card lib-side" style="padding:12px 8px">${nav()}</div>
        <div class="stack" style="gap:18px">
          <div id="list">${st.sel === "m:标注" ? marksBlock() : listBlock()}</div>
        </div>
      </div>`;
    bind();
  }

  const remember = () => store.set("library3", { sel: st.sel });

  async function loadMarks() {
    if (st.allMarks) return;
    try { st.allMarks = (await apiGet("/api/docmarks")).items; } catch (e) { toast(e.message); st.allMarks = []; }
    if (st.sel === "m:标注" && el.isConnected) el.querySelector("#list").innerHTML = marksBlock();
  }

  function bind() {
    el.querySelectorAll("[data-sel]").forEach((x) => (x.onclick = () => {
      st.sel = x.dataset.sel;
      remember();
      draw(lastJob);
      if (st.sel === "m:标注") loadMarks();
      el.querySelector("#list")?.scrollIntoView({ block: "nearest" });
    }));
    searchOff?.();
    searchOff = bindHeadSearch(el, { hot: HOT, run: runSearch });
    el.querySelectorAll("[data-job]").forEach((x) => (x.onclick = async () => {
      try {
        const r = await apiPost("/api/jobs/start", { job: x.dataset.job });
        toast(r.queued ? `已排队：等前面的整理完成后开始“${r.name}”` : "开始整理；扫描件要识别文字，可能需要较长时间", 3500);
        poll();
      } catch (err) { toast(err.message, 4000); }
    }));
  }

  let lastJob = await apiGet("/api/jobs");
  async function poll() {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (!el.isConnected) { clearInterval(pollTimer); return; }
      const job = await apiGet("/api/jobs").catch(() => null);
      if (!job) return;
      if (job.running) {
        lastJob = job;
        const box = el.querySelector("#job");
        if (box) box.outerHTML = jobBox(job);
      } else {
        clearInterval(pollTimer);
        toast(jobDoneText(job, "资料整理完成"), 4000);
        render(el, ctx);
      }
    }, 1500);
  }
  draw(lastJob);
  if (st.sel === "m:标注") loadMarks();
  if (lastJob.running) poll();
  return () => { clearInterval(pollTimer); searchOff?.(); searchOff = null; };
}

// ---------------------------------------------------------------- 原卷查看（真题卷、申论卷的原始 PDF）

async function viewer(el, fid, page) {
  const data = await apiGet("/api/library");
  const f = data.files.find((x) => x.id === fid);
  if (!f) { el.innerHTML = `<div class="card empty"><h3>找不到这个文件</h3><p>可能已被移动或删除，请在资料库重新整理。</p><a href="#/library">返回资料库</a></div>`; return; }
  const p = data.progress[fid] || { page: 0, done: 0, fav: 0 };
  const startPage = Math.min(page || p.page || 0, Math.max(0, (f.pages || 1) - 1));
  const opened = Date.now();
  const save = (patch) => apiPost("/api/library/progress", { fid, rel: f.rel, ...patch }).catch(() => {});
  let maxPage = Math.max(startPage, p.page || 0);
  save({ page: maxPage });

  const isPdf = f.ext === "pdf";
  const isImg = ["jpg", "jpeg", "png"].includes(f.ext);
  const scanned = isPdf && !f.text;
  // PDF 用内置的 PDF 阅读器打开（可以选中文字、Ctrl+F 查找）；页码框跳页时记下读到的位置
  function body() {
    if (isPdf) return `<iframe id="frame" src="/api/library/file/${fid}#page=${startPage + 1}" title="${esc(f.name)}"></iframe>`;
    if (isImg) return `<div class="pages"><img src="/api/library/file/${fid}" alt="${esc(f.name)}"></div>`;
    return `<div class="card empty"><h3>这个文件不能在软件里直接显示</h3><p>${esc(f.ext.toUpperCase())} 文件请用 Word / WPS 打开。</p><button class="btn primary" id="sys2">用系统程序打开</button></div>`;
  }

  function draw() {
    el.innerHTML = `
      <div class="row mb"><a class="btn sm ghost" href="#/library">← 资料库</a>
        <b style="font:500 17px var(--display);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:40vw" title="${esc(f.rel)}">${esc(f.name)}</b>
        <span class="small muted">${isPdf ? `${f.pages} 页` : esc(f.ext.toUpperCase())}${scanned ? " · 扫描版" : ""}</span>
        <span class="spacer"></span>
        ${isPdf ? `<label class="row small">第 <input type="number" id="pg" min="1" max="${f.pages}" value="${startPage + 1}" style="width:72px"> 页</label>` : ""}
        <button class="btn sm" id="fav">${p.fav ? "★ 已收藏" : "☆ 收藏"}</button>
        <button class="btn sm" id="done">${p.done ? "✓ 已读完" : "标记读完"}</button>
        <button class="btn sm ghost" id="sys" title="用电脑上默认的程序打开">系统程序打开</button>
        <button class="btn sm ghost" id="reveal">在文件夹中显示</button>
      </div>
      <div class="viewer">${body()}</div>`;
    bind();
  }

  function goPage(n) {
    const fr = el.querySelector("#frame");
    if (fr) fr.src = `/api/library/file/${fid}#page=${n + 1}`;
  }

  function bind() {
    const pg = el.querySelector("#pg");
    if (pg) pg.onchange = () => {
      const n = Math.max(1, Math.min(f.pages, +pg.value || 1));
      goPage(n - 1);
      if (n - 1 > maxPage) { maxPage = n - 1; save({ page: maxPage }); }
    };
    el.querySelector("#fav").onclick = async (e) => { p.fav = !p.fav; await save({ fav: p.fav }); e.target.textContent = p.fav ? "★ 已收藏" : "☆ 收藏"; };
    el.querySelector("#done").onclick = async (e) => { p.done = !p.done; await save({ done: p.done }); e.target.textContent = p.done ? "✓ 已读完" : "标记读完"; };
    const sys = async () => { try { await apiPost("/api/library/open", { fid }); } catch (err) { toast(err.message, 4000); } };
    el.querySelector("#sys").onclick = sys;
    const sys2 = el.querySelector("#sys2");
    if (sys2) sys2.onclick = sys;
    el.querySelector("#reveal").onclick = async () => { try { await apiPost("/api/library/open", { fid, reveal: true }); } catch (err) { toast(err.message, 4000); } };
  }

  draw();
  // 离开阅读器时把阅读时长记进学习统计
  return () => {
    const minutes = Math.round((Date.now() - opened) / 60000);
    if (minutes >= 1) {
      // 真题卷是综合练习；讲义、题册才按科目记
      const subj = f.cat === "真题" ? null : f.subj.find((s) => SUBJ_MODULE[s]);
      apiPost("/api/library/progress", { fid, rel: f.rel, minutes, module: subj ? SUBJ_MODULE[subj] : "综合" }).catch(() => {});
    }
  };
}
