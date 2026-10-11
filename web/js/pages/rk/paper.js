// 软考 · 论文写作：选论题 → 限时 120 分钟打字（机考就是打字）→ 摘要、正文字数和结构实时检查 → 交卷后看写作要点、请 AI 按评分维度批改。
// “我的项目素材”写一次，各论题的项目背景段都从这里插入（考场上就是把同一个项目套到不同论题）
import { apiGet, apiPost, esc, fmtClock, md, mountAIBox, store, toast } from "../../lib.js";

const MINUTES = 120;
const PROJ_KEY = "rk-projects";
const DRAFT_KEY = "rk-paper-draft";

// 结构检查：按常见的高分结构（摘要 / 项目背景 / 理论 / 实践论点 / 效果与不足）粗略判断
function structure(abstract, body) {
  const paras = body.split(/\n+/).map((x) => x.trim()).filter(Boolean);
  const points = paras.filter((p) => /^(?:[一二三四五六七八九十]+[、.．]|[（(][一二三四五六七八九十\d]+[)）]|\d+[.、．]|首先|其次|再次|最后|第[一二三四五]，?)/.test(p)).length;
  return [
    ["摘要", abstract.trim().length >= 150, abstract.trim().length ? `${abstract.trim().length} 字` : "还没写"],
    ["项目背景（时间、规模、我的角色）", /20\d\d\s*年/.test(body) && /项目/.test(body) && /(担任|负责|作为|我是|本人)/.test(body), ""],
    ["理论阐述（论题的概念、原理）", paras.length >= 3, ""],
    ["实践论点（分条论述 2–3 个做法）", points >= 2, `识别到 ${points} 个分条`],
    ["效果与不足、改进", /(效果|成效|上线|不足|改进|问题|总结)/.test(paras.slice(-2).join("")), ""],
    ["正文字数 2000–3000", body.trim().length >= 2000 && body.trim().length <= 3200, `${body.trim().length} 字`],
  ];
}

function projectParagraph(p) {
  return `${p.time || "20XX 年 X 月"}，我参与了${p.org ? p.org + "的" : ""}“${p.name || "某某系统"}”项目的建设，${p.scale ? p.scale + "，" : ""}我在项目中担任${p.role || "系统架构设计师"}，${p.duty ? "主要负责" + p.duty + "。" : "负责系统的整体架构设计。"}${p.tech ? `系统采用了${p.tech}等技术。` : ""}${p.bg || ""}`;
}

async function listView(el) {
  const [data, docs] = await Promise.all([apiGet("/api/rk/essays"), apiGet("/api/docs").catch(() => ({ docs: [] }))]);
  const samples = (docs.docs || []).filter((d) => d.cat === "论文范文");
  const guides = (docs.docs || []).filter((d) => d.cat === "论文指导");
  let q = "", src = store.get("rk-paper", {}).src || "paper";
  function draw() {
    const list = data.topics.filter((t) => (src === "all" || t.kind === src) && (!q || t.title.includes(q)));
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">论文</div><h1>论文写作</h1>
        <p>考试从 4 道论题中选 1 道，120 分钟机考打字：摘要 300 字左右，正文 2000–3000 字，75 分满分、45 分及格。先在下面写好“我的项目素材”，每篇论文的项目背景都用同一个项目。</p></div>
        <a class="btn" href="#/learn/rk-paper">看论文写作方法</a></div>
      <div class="grid cols-main">
        <div class="stack">
          <div class="row"><div class="seg" id="srcs">${[["paper", "历年真题论题"], ["mock", "模拟题论题"], ["all", "全部"]].map(([k, n]) => `<button data-s="${k}" class="${src === k ? "active" : ""}">${n}</button>`).join("")}</div>
            <input type="search" id="q" placeholder="搜论题，如 微服务、可靠性" value="${esc(q)}" style="max-width:240px"></div>
          <div class="card">${list.map((t) => `<a class="paper-row" href="#/paper/${encodeURIComponent(t.id)}">
            <div class="info"><div class="t">${t.year ? `<span class="year-tag">${t.year}${t.half ? " " + esc(t.half.replace("半年", "")) : ""}</span>` : ""}${esc(t.title)}</div>
              <div class="meta">${esc(t.source)}${t.has_guide ? " · 有写作要点" : ""}</div></div>
            <div class="stat"><span class="meta">${t.rec ? `写过 ${t.rec.n} 次${t.rec.ai != null ? ` · AI ${t.rec.ai} 分` : ""}` : "还没写过"}</span></div></a>`).join("") || `<div class="empty">没有符合的论题</div>`}</div>
        </div>
        <div class="stack">
          <div class="card" id="proj"></div>
          ${samples.length || guides.length ? `<div class="card"><h3>范文与写作指导</h3>
            ${guides.map((d) => `<a class="block-link" href="#/library/doc/${encodeURIComponent(d.id)}">📘 ${esc(d.title)}</a>`).join("")}
            ${samples.map((d) => `<a class="block-link" href="#/library/doc/${encodeURIComponent(d.id)}">${esc(d.title)}</a>`).join("")}</div>` : ""}
        </div>
      </div>`;
    el.querySelectorAll("#srcs button").forEach((b) => (b.onclick = () => { src = b.dataset.s; store.set("rk-paper", { src }); draw(); }));
    const qi = el.querySelector("#q");
    qi.oninput = () => { q = qi.value.trim(); const pos = qi.selectionStart; draw(); const n = el.querySelector("#q"); n.focus(); n.setSelectionRange(pos, pos); };
    projectCard(el.querySelector("#proj"));
  }
  draw();
}

// 我的项目素材：可以存几个项目，写论文时一键插入背景段
function projectCard(box, onInsert) {
  const list = store.get(PROJ_KEY, []);
  let cur = list[0] ? 0 : -1;
  const F = [["name", "项目名称", "例：某市医保结算平台"], ["org", "建设单位", "例：某市医疗保障局"], ["time", "时间", "例：2024 年 3 月至 2025 年 6 月"],
    ["scale", "规模", "例：投资 1200 万元，日均交易 60 万笔"], ["role", "我的角色", "例：系统架构设计师"], ["duty", "我负责", "例：总体架构设计和关键技术选型"],
    ["tech", "技术栈", "例：Spring Cloud、Kubernetes、Redis、Kafka"], ["bg", "补充背景", "业务痛点、为什么要做这个项目（两三句）"]];
  function draw() {
    const p = list[cur] || {};
    box.innerHTML = `<div class="card-head"><h3>我的项目素材</h3><span class="small muted">写一次，各篇论文复用</span></div>
      ${list.length > 1 ? `<div class="pills wrap sm mb">${list.map((x, i) => `<button data-i="${i}" class="${i === cur ? "active" : ""}">${esc(x.name || "未命名")}</button>`).join("")}</div>` : ""}
      ${cur < 0 ? `<p class="small muted">考官最看重“真实项目 + 本人角色”。准备 1–2 个自己做过（或熟悉）的项目，背景、规模、角色、技术写清楚。</p>`
        : F.map(([k, label, ph]) => `<label class="field small">${esc(label)}${k === "bg" ? `<textarea data-k="${k}" rows="3" placeholder="${esc(ph)}">${esc(p[k] || "")}</textarea>` : `<input type="text" data-k="${k}" value="${esc(p[k] || "")}" placeholder="${esc(ph)}">`}</label>`).join("")}
      <div class="row mt"><button class="btn sm" id="pj-new">新建项目</button>
        ${cur >= 0 ? `<button class="btn sm ghost" id="pj-del">删除</button>${onInsert ? `<button class="btn sm primary" id="pj-ins">插入背景段</button>` : ""}` : ""}</div>
      ${cur >= 0 ? `<details class="mt"><summary class="small">背景段预览</summary><p class="small ink2">${esc(projectParagraph(p))}</p></details>` : ""}`;
    box.querySelectorAll("[data-i]").forEach((b) => (b.onclick = () => { cur = +b.dataset.i; draw(); }));
    box.querySelectorAll("[data-k]").forEach((inp) => (inp.onchange = () => { list[cur][inp.dataset.k] = inp.value; store.set(PROJ_KEY, list); draw(); }));
    box.querySelector("#pj-new").onclick = () => { list.push({ role: "系统架构设计师" }); cur = list.length - 1; store.set(PROJ_KEY, list); draw(); };
    const del = box.querySelector("#pj-del");
    if (del) del.onclick = () => { list.splice(cur, 1); cur = list.length ? 0 : -1; store.set(PROJ_KEY, list); draw(); };
    const ins = box.querySelector("#pj-ins");
    if (ins) ins.onclick = () => onInsert(projectParagraph(list[cur]));
  }
  draw();
}

async function writeView(el, id) {
  const e = await apiGet("/api/rk/essay?id=" + encodeURIComponent(id));
  const drafts = store.get(DRAFT_KEY, {});
  const d = drafts[id] || { abstract: "", body: "" };
  let startAt = d.startAt || 0, submitted = false, savedId = null, tick = null;
  const saveDraft = () => { drafts[id] = { ...d, startAt }; store.set(DRAFT_KEY, drafts); };

  function checks() {
    const box = el.querySelector("#checks");
    if (!box) return;
    box.innerHTML = structure(d.abstract, d.body).map(([k, ok, note]) => `<div class="ck-row ${ok ? "ok" : ""}"><span>${ok ? "✓" : "○"}</span><span>${esc(k)}</span><small>${esc(note)}</small></div>`).join("");
    el.querySelector("#n-abs").textContent = `${d.abstract.trim().length} 字（建议 300 字左右，不超过 400）`;
    el.querySelector("#n-body").textContent = `${d.body.trim().length} 字（2000–3000）`;
  }
  function clock() {
    const k = el.querySelector("#clock");
    if (!k) { clearInterval(tick); return; }
    if (!startAt) { k.textContent = `限时 ${MINUTES} 分钟`; return; }
    const left = MINUTES * 60 - Math.round((Date.now() - startAt) / 1000);
    k.textContent = left > 0 ? `剩余 ${fmtClock(left)}` : `已超时 ${fmtClock(-left)}`;
    k.classList.toggle("bad", left < 600);
  }

  function draw() {
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow"><a href="#/paper">论文写作</a> · ${esc(e.source)}</div><h1>${esc(e.title)}</h1></div>
        <span class="chip" id="clock"></span>${!startAt && !submitted ? `<button class="btn primary" id="go">开始计时</button>` : ""}</div>
      <div class="paper-layout">
        <div class="stack">
          <div class="card"><div class="prose small">${md(e.background || "")}</div>
            ${e.requirements?.length ? `<p class="small"><b>请围绕论题，依次从以下方面论述：</b></p><ol class="small">${e.requirements.map((r) => `<li>${esc(r)}</li>`).join("")}</ol>` : ""}</div>
          <div class="card">
            <label class="field"><b>摘要</b> <small class="muted" id="n-abs"></small>
              <textarea id="abs" rows="5" placeholder="交代项目（时间、规模、你的角色）、论文论述的几个方面、结果。不要写成正文的开头" ${submitted ? "readonly" : ""}>${esc(d.abstract)}</textarea></label>
            <label class="field"><b>正文</b> <small class="muted" id="n-body"></small>
              <textarea id="body" rows="24" placeholder="建议结构：项目背景（约 400 字）→ 理论阐述（约 400 字）→ 分条论述 2–3 个做法，每条结合项目（约 1200 字）→ 效果、不足和改进（约 300 字）" ${submitted ? "readonly" : ""}>${esc(d.body)}</textarea></label>
            ${submitted ? `<div class="mt" id="ai"></div>` : `<div class="row mt"><button class="btn primary lg" id="submit">交卷</button><span class="small muted">草稿自动保存</span></div>`}
          </div>
        </div>
        <div class="stack paper-side">
          <div class="card"><h3>结构检查</h3><div id="checks"></div></div>
          <div class="card" id="proj"></div>
          ${e.guide ? `<details class="card" ${submitted ? "open" : ""}><summary><b>写作要点</b> <small class="muted">${submitted ? "" : "（建议写完再看）"}</small></summary><div class="prose small">${md(e.guide)}</div></details>` : ""}
          ${e.history?.length ? `<details class="card"><summary>以前写过（${e.history.length}）</summary>${e.history.map((h) => `<div class="small mt">${esc(h.created_at.slice(0, 16))} · ${+h.words || 0} 字${h.ai_score != null ? ` · AI ${h.ai_score}/${h.ai_full}` : ""}</div>`).join("")}</details>` : ""}
        </div>
      </div>`;
    const abs = el.querySelector("#abs"), body = el.querySelector("#body");
    abs.oninput = () => { d.abstract = abs.value; saveDraft(); checks(); };
    body.oninput = () => { d.body = body.value; saveDraft(); checks(); };
    projectCard(el.querySelector("#proj"), submitted ? null : (text) => {
      const pos = body.selectionStart ?? body.value.length;
      body.value = body.value.slice(0, pos) + text + "\n" + body.value.slice(pos);
      d.body = body.value; saveDraft(); checks(); toast("已插入项目背景段，记得按论题改写");
    });
    const go = el.querySelector("#go");
    if (go) go.onclick = () => { startAt = Date.now(); saveDraft(); draw(); body.focus(); };
    const sub = el.querySelector("#submit");
    if (sub) sub.onclick = async () => {
      if (d.body.trim().length < 200) { toast("正文还太短"); return; }
      const secs = startAt ? Math.round((Date.now() - startAt) / 1000) : 0;
      const r = await apiPost("/api/essays", { set_id: "paper:" + id, q_index: 0, answer: JSON.stringify({ abstract: d.abstract, body: d.body }),
        words: d.body.trim().length, seconds: secs, module: "论文", source: "论文写作" });
      savedId = r.id; submitted = true;
      delete drafts[id]; store.set(DRAFT_KEY, drafts);
      draw();
    };
    const ai = el.querySelector("#ai");
    if (ai) mountAIBox(ai, { label: "请 AI 按论文评分标准批改（75 分制）", kind: "rkpaper",
      getBody: () => ({ title: e.title, background: e.background, requirements: e.requirements, abstract: d.abstract, body: d.body }),
      onDone: async (text) => { if (savedId) await apiPost("/api/essays/feedback", { id: savedId, ai_feedback: text }); } });
    checks();
    clock();
  }
  draw();
  tick = setInterval(clock, 1000);
  return () => clearInterval(tick);
}

export async function render(el, ctx) {
  if (ctx.parts[1]) return writeView(el, ctx.parts[1]);
  return listView(el);
}
