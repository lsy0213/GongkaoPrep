// 软考 · 计算题专练：12 类常考计算题，程序出题、程序算答案，做完看分步解析，不限量
import { apiGet, apiPost, esc, LETTERS, store } from "../../lib.js";
import { CALC_TYPES } from "../../rk-calc.js";

export async function render(el) {
  const stats = await apiGet("/api/rk/calc/stats").catch(() => ({}));
  const saved = store.get("rk-calc", {});
  let sel = new Set((saved.types || []).filter((id) => CALC_TYPES.some((t) => t.id === id)));
  let cur = null, chosen = null, startAt = 0;
  const session = {}; // 本次各类做了几题、对几题、用时

  const flush = () => {
    for (const [id, s] of Object.entries(session)) {
      if (!s.n) continue;
      apiPost("/api/speed", { kind: "rk-" + id, total: s.n, correct: s.ok, seconds: s.sec, module: "综合知识", source: "计算题" }).catch(() => {});
      const all = stats[id] || (stats[id] = { n: 0, ok: 0, sec: 0 });
      all.n += s.n; all.ok += s.ok; all.sec += s.sec;
      s.n = s.ok = s.sec = 0;
    }
  };

  function next() {
    const pool = CALC_TYPES.filter((t) => !sel.size || sel.has(t.id));
    const t = pool[Math.floor(Math.random() * pool.length)];
    cur = { t, q: t.gen() };
    chosen = null;
    startAt = Date.now();
    draw();
  }

  function tableHTML(rows) {
    if (!rows) return "";
    return `<table class="tbl small calc-tbl"><thead><tr>${rows[0].map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
      <tbody>${rows.slice(1).map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  function draw() {
    const { t, q } = cur;
    const st = stats[t.id];
    const done = chosen != null;
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">综合知识</div><h1>计算题专练</h1>
        <p>每年综合知识有 5–10 分计算题。这里的题由程序随机出、答案由程序算，可以无限练；选完马上看分步解析。</p></div></div>
      <div class="pills wrap mb" id="types">
        <button data-t="" class="${sel.size ? "" : "active"}">全部混合</button>
        ${CALC_TYPES.map((x) => {
          const s = stats[x.id];
          return `<button data-t="${x.id}" class="${sel.has(x.id) ? "active" : ""}" title="${s ? `做过 ${s.n} 题，正确率 ${Math.round((s.ok / s.n) * 100)}%` : "还没练过"}">${esc(x.name)}${s ? `<small class="num">${Math.round((s.ok / s.n) * 100)}%</small>` : ""}</button>`;
        }).join("")}
      </div>
      <div class="card calc-card">
        <div class="q-meta"><span class="chip brand">${esc(t.name)}</span>
          ${st ? `<span class="small muted">本类做过 ${st.n} 题 · 正确率 ${Math.round((st.ok / st.n) * 100)}% · 平均 ${Math.round(st.sec / st.n)} 秒</span>` : `<span class="small muted">新题型</span>`}</div>
        <div class="q-stem">${esc(q.stem)}</div>
        ${tableHTML(q.table)}
        <div class="options">${q.options.map((o, k) => {
          let cls = "";
          if (done) cls = k === q.answer ? "right" : k === chosen ? "wrong" : "";
          return `<button class="opt ${cls}" data-k="${k}" ${done ? "disabled" : ""}><span class="L">${LETTERS[k]}</span><span>${esc(o)}</span></button>`;
        }).join("")}</div>
        ${done ? `<div class="explain"><div class="row"><span class="verdict ${chosen === q.answer ? "ok" : "no"}">${chosen === q.answer ? "回答正确" : "回答错误"}</span>
            <span class="ink2">正确答案 <b>${LETTERS[q.answer]}</b></span></div>
          <ol class="calc-steps">${q.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>` : ""}
        <div class="row mt"><span class="spacer"></span>
          <a class="btn ghost" href="#/learn/${esc(t.course)}">看讲解课</a>
          <button class="btn ${done ? "primary" : ""}" id="next">${done ? "下一题" : "换一题"}</button></div>
      </div>`;
    el.querySelectorAll("#types button").forEach((b) => (b.onclick = () => {
      const id = b.dataset.t;
      if (!id) sel = new Set();
      else if (sel.has(id)) sel.delete(id);
      else sel.add(id);
      store.set("rk-calc", { types: [...sel] });
      next();
    }));
    el.querySelectorAll("[data-k]").forEach((b) => (b.onclick = () => {
      if (chosen != null) return;
      chosen = +b.dataset.k;
      const s = session[t.id] || (session[t.id] = { n: 0, ok: 0, sec: 0 });
      s.n += 1; s.ok += chosen === q.answer ? 1 : 0; s.sec += Math.round((Date.now() - startAt) / 1000);
      if (Object.values(session).reduce((a, x) => a + x.n, 0) >= 10) flush();
      draw();
    }));
    el.querySelector("#next").onclick = next;
  }
  next();
  return () => flush();
}
