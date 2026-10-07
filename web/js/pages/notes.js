import { apiGet, apiPost, esc, store, todayISO, toast } from "../lib.js";

const KINDS = ["好词好句", "规范表述", "名言警句", "典型事例", "词语辨析", "常识", "时政", "其他"];
const SOURCES = [
  { name: "人民日报评论", url: "http://opinion.people.com.cn/", hint: "人民时评、人民论坛，申论大作文的最佳范本" },
  { name: "新华网评论", url: "http://www.news.cn/comments/", hint: "新华时评，短小精悍，适合积累观点" },
  { name: "求是网", url: "http://www.qstheory.cn/", hint: "理论文章，政治理论和大作文立意" },
  { name: "半月谈", url: "http://www.banyuetan.org/", hint: "基层治理、社会热点，贴近申论材料" },
  { name: "光明网评论", url: "https://guancha.gmw.cn/", hint: "文化、教育类评论较多" },
  { name: "中国政府网", url: "https://www.gov.cn/", hint: "政策文件和权威解读" },
  { name: "国家公务员局", url: "http://www.scs.gov.cn/", hint: "国考公告、考试大纲" },
];

export async function render(el, ctx) {
  const sc = await apiGet("/api/sucai");
  let tab = ctx.query.tab || store.get("notes-tab", "lib");
  let notes = (await apiGet("/api/notebook")).items;
  let readings = (await apiGet("/api/reading")).items;
  let filter = { kind: "全部", q: "" };
  let editing = null;

  async function reload() {
    notes = (await apiGet("/api/notebook")).items;
    readings = (await apiGet("/api/reading")).items;
  }

  async function saveNote(n) {
    await apiPost("/api/notebook", n);
    await reload();
  }

  // ---------------------------------------------------------------- 素材库
  // 类型、主题、来源三个筛选互相联动：每个选项后面的数字 = 在其他两个条件下选它能看到几条，点开不会是空的
  const TYPE_KIND = { "规范表述": "规范表述", "金句": "好词好句", "名言古句": "名言警句", "人物事例": "典型事例", "典故": "名言警句",
    "论据": "典型事例", "开头结尾": "好词好句", "热点素材": "时政", "范文": "其他" };
  const PAGE = 60;
  const sf = Object.assign({ type: "全部", theme: "全部", src: "全部", q: "", show: PAGE, rand: null }, store.get("sucai-filter", {}), { q: "", show: PAGE, rand: null });
  const collected = new Set(notes.map((n) => n.content));

  function match(it, skip) {
    if (skip !== "type" && sf.type !== "全部" && it.type !== sf.type) return false;
    if (skip !== "theme" && sf.theme !== "全部" && it.theme !== sf.theme) return false;
    if (skip !== "src" && sf.src !== "全部" && (sf.src === "内置精选") !== (it.src === "内置精选")) return false;
    if (sf.q) {
      const hay = it.text + it.title + it.note + it.theme;
      if (!sf.q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  }

  function filterList(name, values, key) {
    const counts = {};
    let all = 0;
    for (const it of sc.items) {
      if (!match(it, key)) continue;
      all++;
      counts[it[key === "src" ? "src" : key]] = (counts[it[key === "src" ? "src" : key]] || 0) + 1;
    }
    if (key === "src") {
      const mine = sc.items.filter((it) => match(it, "src") && it.src !== "内置精选").length;
      counts["内置精选"] = all - mine;
      counts["我的资料"] = mine;
    }
    const cur = sf[key];
    return `<h4>${name}</h4>` + ["全部", ...values].map((v) => {
      const n = v === "全部" ? all : counts[v] || 0;
      if (v !== "全部" && !n && cur !== v) return "";
      return `<button data-f="${key}" data-v="${esc(v)}" class="${cur === v ? "active" : ""}">${esc(v)}<small>${n}</small></button>`;
    }).join("");
  }

  function itemHTML(it) {
    const has = collected.has(it.text);
    const jump = it.doc ? `<a class="small" href="#/library/doc/${encodeURIComponent(it.doc)}?s=${it.seq}">${esc(it.src)} ›</a>` : `<span class="small muted">${esc(it.src)}</span>`;
    const long = it.type === "人物事例" || it.type === "范文" || it.text.length > 160;
    return `<div class="sc-item${long ? " long" : ""}" data-id="${it.id}">
      <div class="sc-meta"><span class="chip brand">${esc(it.type)}</span><span class="chip">${esc(it.theme)}</span>${it.title ? `<b>${esc(it.title)}</b>` : ""}</div>
      <div class="sc-text${it.type === "名言古句" ? " sc-quote" : ""}">${esc(it.text).replace(/\n/g, "<br>")}</div>
      ${it.note ? `<div class="sc-note">${esc(it.note).replace(/\n/g, "<br>")}</div>` : ""}
      <div class="sc-foot">${jump}<span class="spacer"></span>
        <button class="btn sm ghost" data-copy="${it.id}">复制</button>
        <button class="btn sm ${has ? "ghost" : ""}" data-pick="${it.id}" ${has ? "disabled" : ""}>${has ? "已收藏" : "收进积累"}</button></div>
    </div>`;
  }

  function libTab() {
    if (!sc.items.length) {
      return `<div class="card empty"><h3>素材库还没生成</h3><p>到“资料库”整理资料后会自动生成；也可以点下面按钮马上生成。</p>
        <button class="btn primary" id="sc-build">生成素材库</button></div>`;
    }
    const list = sf.rand || sc.items.filter((it) => match(it));
    return `<div class="lib-layout">
      <div class="card lib-side sc-side" style="padding:12px 8px">
        ${filterList("类型", sc.types, "type")}
        ${filterList("主题", sc.themes, "theme")}
        ${filterList("来源", ["内置精选", "我的资料"], "src")}
      </div>
      <div class="stack" style="gap:14px">
        <div class="card sc-bar">
          <input type="search" id="sc-q" placeholder="搜素材，如：乡村振兴 人才、枫桥经验、工匠精神" value="${esc(sf.q)}" autocomplete="off">
          <button class="btn" id="sc-rand" title="从当前筛选里随机抽 10 条，适合每天背一组">随机抽 10 条</button>
          ${sf.rand ? `<button class="btn ghost" id="sc-all">看全部</button>` : ""}
        </div>
        <div class="small muted">${sf.rand ? "随机抽取的 10 条" : `共 ${list.length} 条`}${sf.type !== "全部" || sf.theme !== "全部" || sf.src !== "全部" ? ` · ${[sf.type, sf.theme, sf.src].filter((x) => x !== "全部").join(" · ")}` : ""}
          · 素材库收录 ${sc.items.length} 条（${sc.items.filter((x) => x.src === "内置精选").length} 条内置精选，其余从你的资料里整理）</div>
        <div class="sc-list">${list.slice(0, sf.show).map(itemHTML).join("") || `<div class="card empty">没有符合条件的素材</div>`}</div>
        ${!sf.rand && list.length > sf.show ? `<div class="row"><button class="btn" id="sc-more">再显示 ${Math.min(PAGE, list.length - sf.show)} 条</button><span class="small muted">已显示 ${sf.show} / ${list.length}</span></div>` : ""}
      </div>
    </div>`;
  }

  function bindLib() {
    const body = el.querySelector("#tab-body");
    const redraw = (keepScroll) => {
      store.set("sucai-filter", { type: sf.type, theme: sf.theme, src: sf.src });
      const y = el.closest("#view")?.scrollTop;
      body.innerHTML = libTab();
      bindLib();
      if (keepScroll && y != null) el.closest("#view").scrollTop = y;
    };
    body.querySelectorAll("[data-f]").forEach((x) => (x.onclick = () => { sf[x.dataset.f] = x.dataset.v; sf.show = PAGE; sf.rand = null; redraw(); }));
    const q = body.querySelector("#sc-q");
    if (q) {
      let t = null;
      q.oninput = () => {
        clearTimeout(t);
        t = setTimeout(() => {
          sf.q = q.value.trim(); sf.show = PAGE; sf.rand = null;
          const pos = q.selectionStart;
          redraw();
          const nq = body.querySelector("#sc-q");
          nq.focus();
          nq.setSelectionRange(pos, pos);
        }, 250);
      };
    }
    const more = body.querySelector("#sc-more");
    if (more) more.onclick = () => { sf.show += PAGE; redraw(true); };
    const rand = body.querySelector("#sc-rand");
    if (rand) rand.onclick = () => {
      const pool = sc.items.filter((it) => match(it));
      const out = [];
      const used = new Set();
      while (out.length < Math.min(10, pool.length)) {
        const i = Math.floor(Math.random() * pool.length);
        if (!used.has(i)) { used.add(i); out.push(pool[i]); }
      }
      sf.rand = out;
      redraw();
    };
    const all = body.querySelector("#sc-all");
    if (all) all.onclick = () => { sf.rand = null; redraw(); };
    const byId = (id) => sc.items.find((x) => x.id === +id);
    body.querySelectorAll("[data-copy]").forEach((x) => (x.onclick = async () => {
      const it = byId(x.dataset.copy);
      try { await navigator.clipboard.writeText(it.text); toast("已复制"); } catch { toast("复制失败"); }
    }));
    body.querySelectorAll("[data-pick]").forEach((x) => (x.onclick = async () => {
      const it = byId(x.dataset.pick);
      await saveNote({ kind: TYPE_KIND[it.type] || "其他", title: it.title || it.theme, content: it.text,
        source: [it.note.startsWith("——") ? it.note.slice(2).split("　")[0] : "", it.src].filter(Boolean).join(" · "), tags: `${it.theme} ${it.type}` });
      collected.add(it.text);
      x.textContent = "已收藏";
      x.disabled = true;
      x.classList.add("ghost");
      toast("已收进我的积累，也会出现在闪卡里");
    }));
    const build = body.querySelector("#sc-build");
    if (build) build.onclick = async () => {
      try { await apiPost("/api/jobs/start", { job: "sucai" }); toast("正在生成素材库，稍等片刻后重新打开本页"); } catch (e) { toast(e.message, 4000); }
    };
  }

  function noteForm(n = {}) {
    return `<form class="card stack" id="note-form">
      <div class="card-head"><h3>${n.id ? "编辑" : "添加"}一条积累</h3>${n.id ? `<button type="button" class="btn sm ghost" id="cancel">取消</button>` : ""}</div>
      <div class="grid cols-2">
        <label class="field">类型<select id="nk">${KINDS.map((k) => `<option ${k === (n.kind || "好词好句") ? "selected" : ""}>${k}</option>`).join("")}</select></label>
        <label class="field">标题 / 关键词（可选）<input type="text" id="nt" value="${esc(n.title || "")}" placeholder="例如：基层治理、首当其冲"></label>
      </div>
      <label class="field">内容<textarea id="nc" rows="4" placeholder="摘抄的句子、自己的理解、词语辨析……">${esc(n.content || "")}</textarea></label>
      <div class="grid cols-2">
        <label class="field">出处（可选）<input type="text" id="ns" value="${esc(n.source || "")}" placeholder="例如：人民日报 2026-10-03"></label>
        <label class="field">标签（可选，用空格分隔）<input type="text" id="ng" value="${esc(n.tags || "")}" placeholder="例如：民生 大作文开头"></label>
      </div>
      <div class="row"><button class="btn primary" type="submit">${n.id ? "保存修改" : "添加"}</button>
        <span class="small muted">积累的内容会自动加入“闪卡记忆”里的“我的积累”卡组</span></div>
    </form>`;
  }

  function mineTab() {
    let xs = notes;
    if (filter.kind !== "全部") xs = xs.filter((n) => n.kind === filter.kind);
    if (filter.q) xs = xs.filter((n) => (n.title + n.content + n.tags + n.source).includes(filter.q));
    return `${noteForm(editing || {})}
      <div class="card">
        <div class="row mb">
          <div class="seg" id="kinds">${["全部", ...KINDS].map((k) => `<button data-k="${k}" class="${filter.kind === k ? "active" : ""}">${k}</button>`).join("")}</div>
          <span class="spacer"></span>
          <input type="search" id="nq" placeholder="搜索" value="${esc(filter.q)}" style="width:180px">
        </div>
        ${xs.length ? xs.map((n) => `<div class="note-item">
          <div class="row"><span class="chip brand">${esc(n.kind)}</span>${n.title ? `<b>${esc(n.title)}</b>` : ""}
            ${(n.tags || "").split(/\s+/).filter(Boolean).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}
            <span class="spacer"></span><span class="small muted">${esc(n.created_at.slice(0, 10))}</span>
            <button class="btn sm ghost" data-edit="${n.id}">编辑</button><button class="btn sm ghost danger" data-del="${n.id}">删除</button></div>
          <div class="c">${esc(n.content)}</div>
          ${n.source ? `<div class="small muted">出处：${esc(n.source)}</div>` : ""}
        </div>`).join("") : `<div class="empty"><h3>还没有积累</h3><p>从素材库收藏、读文章时摘抄，或者把做题时遇到的生词记下来。</p></div>`}
      </div>`;
  }

  function readTab() {
    const today = todayISO();
    const todayDone = readings.some((r) => r.day === today);
    return `<div class="grid cols-main">
      <form class="card stack" id="read-form">
        <div class="card-head"><h3>记录今天读的文章</h3>${todayDone ? `<span class="chip good">今天已阅读</span>` : ""}</div>
        <p class="small ink2" style="margin:0">建议每天精读 1 篇评论文章：①看标题和开头找中心论点；②划出分论点；③摘抄 2–3 句好句；④用一句话写下你的收获。</p>
        <div class="grid cols-2">
          <label class="field">文章标题<input type="text" id="rt" placeholder="例如：让基层减负成为常态"></label>
          <label class="field">来源<input type="text" id="rs" placeholder="例如：人民日报 · 人民时评"></label>
        </div>
        <label class="field">中心论点和分论点<textarea id="ra" rows="3" placeholder="总论点：……&#10;分论点一：……"></textarea></label>
        <label class="field">摘抄的好句（每行一句，会自动加入我的积累）<textarea id="rq" rows="3"></textarea></label>
        <label class="field">阅读用时（分钟）<input type="number" id="rm" min="0" max="180" value="20" style="width:120px"></label>
        <div class="row"><button class="btn primary" type="submit">保存阅读记录</button></div>
      </form>
      <div class="stack" style="gap:16px">
        <div class="card"><h3 class="mb">推荐阅读来源</h3>
          ${SOURCES.map((s) => `<div style="padding:5px 0"><a href="${s.url}" target="_blank" rel="noopener">${esc(s.name)}</a><div class="small muted">${esc(s.hint)}</div></div>`).join("")}
        </div>
        <div class="card"><h3 class="mb">阅读记录（${readings.length}）</h3>
          ${readings.length ? readings.slice(0, 30).map((r) => `<details class="note-item"><summary class="row" style="cursor:pointer">
            <span class="small muted num">${esc(r.day.slice(5))}</span><span class="small" style="flex:1">${esc(r.title || "（无标题）")}</span></summary>
            <div class="small muted">${esc(r.source)}</div><div class="c small">${esc(r.summary)}</div>
            <button class="btn sm ghost danger" data-rdel="${r.id}">删除</button></details>`).join("") : `<div class="empty small">还没有记录</div>`}
        </div>
      </div>
    </div>`;
  }

  function draw() {
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">素材积累</div><h1>积累是申论和言语的底气</h1>
        <p>素材库按类型和主题整理了规范表述、金句、名言古句、人物事例、典故、论据、开头结尾、热点素材和范文；可以搜索、随机抽背，点来源能回到资料原文。</p></div></div>
      <div class="tabs">${[["lib", "素材库"], ["mine", `我的积累 ${notes.length}`], ["read", "每日阅读"]].map(([k, n]) => `<button data-tab="${k}" class="${tab === k ? "active" : ""}">${n}</button>`).join("")}</div>
      <div id="tab-body">${tab === "lib" ? libTab() : tab === "mine" ? mineTab() : readTab()}</div>`;
    bind();
  }

  function bind() {
    el.querySelectorAll("[data-tab]").forEach((x) => (x.onclick = () => { tab = x.dataset.tab; store.set("notes-tab", tab); editing = null; draw(); }));
    if (tab === "lib") bindLib();
    const nf = el.querySelector("#note-form");
    if (nf) {
      nf.onsubmit = async (e) => {
        e.preventDefault();
        const n = {
          id: editing?.id, kind: el.querySelector("#nk").value, title: el.querySelector("#nt").value.trim(),
          content: el.querySelector("#nc").value.trim(), source: el.querySelector("#ns").value.trim(), tags: el.querySelector("#ng").value.trim(),
        };
        if (!n.content) { toast("内容不能为空"); return; }
        await saveNote(n);
        editing = null;
        toast("已保存");
        draw();
      };
      const c = el.querySelector("#cancel");
      if (c) c.onclick = () => { editing = null; draw(); };
    }
    el.querySelectorAll("#kinds button").forEach((x) => (x.onclick = () => { filter.kind = x.dataset.k; draw(); }));
    const nq = el.querySelector("#nq");
    if (nq) nq.onchange = () => { filter.q = nq.value.trim(); draw(); };
    el.querySelectorAll("[data-edit]").forEach((x) => (x.onclick = () => {
      editing = notes.find((n) => n.id === +x.dataset.edit); draw(); el.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    el.querySelectorAll("[data-del]").forEach((x) => (x.onclick = async () => {
      if (x.dataset.armed) { await apiPost("/api/notebook/delete", { id: +x.dataset.del }); await reload(); draw(); return; }
      x.dataset.armed = "1"; x.textContent = "确认删除";
    }));
    el.querySelectorAll("[data-rdel]").forEach((x) => (x.onclick = async () => {
      if (x.dataset.armed) { await apiPost("/api/reading/delete", { id: +x.dataset.rdel }); await reload(); draw(); return; }
      x.dataset.armed = "1"; x.textContent = "确认删除";
    }));
    const rf = el.querySelector("#read-form");
    if (rf) rf.onsubmit = async (e) => {
      e.preventDefault();
      const title = el.querySelector("#rt").value.trim(), source = el.querySelector("#rs").value.trim();
      const summary = el.querySelector("#ra").value.trim();
      const quotes = el.querySelector("#rq").value.split("\n").map((s) => s.trim()).filter(Boolean);
      if (!title && !summary) { toast("至少填写标题或论点"); return; }
      await apiPost("/api/reading", {
        title, source, minutes: +el.querySelector("#rm").value || 0,
        summary: summary + (quotes.length ? "\n\n摘抄：\n" + quotes.join("\n") : ""),
      });
      for (const q of quotes) await apiPost("/api/notebook", { kind: "好词好句", title, content: q, source: [source, title].filter(Boolean).join(" · "), tags: "阅读摘抄" });
      await reload();
      toast(quotes.length ? `已保存，${quotes.length} 句摘抄加入了我的积累` : "已保存");
      draw();
    };
  }

  draw();
}
