// 软考 · 案例练习：按题型（质量属性、数据库与缓存、嵌入式……）挑题，读说明、逐问作答，交卷后对照参考答案自评或请 AI 按评分点批改
import { apiGet, apiPost, esc, fmtClock, md, mountAIBox, store, toast } from "../../lib.js";

function caseTitle(c) {
  return `${c.source || ""} · 试题${"一二三四五六七八九"[(c.no || 1) - 1] || c.no}${c.title ? "：" + c.title : ""}`;
}

async function listView(el) {
  const data = await apiGet("/api/rk/cases");
  const saved = store.get("rk-case", {});
  let tag = saved.tag || "全部", src = saved.src || "all";
  function draw() {
    const list = data.sets.filter((c) => (tag === "全部" || c.tags.includes(tag)) && (src === "all" || c.kind === src));
    const tagN = Object.fromEntries(data.tags.map((t) => [t, data.sets.filter((c) => c.tags.includes(t)).length]));
    const done = data.sets.filter((c) => c.rec).length;
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">案例分析</div><h1>案例练习</h1>
        <p>考试时 5 道题：第 1 题必答（多是质量属性与架构评估），其余 4 题选 2 题，每题 25 分，三题共 75 分、45 分及格。按题型练，先把每类的答题套路练熟。共 ${data.sets.length} 道，做过 ${done} 道。</p></div>
        <a class="btn" href="#/learn/rk-case">看案例答题方法</a></div>
      <div class="seg mb" id="srcs">${[["all", "全部"], ["paper", "历年真题"], ["mock", "模拟题"]].map(([k, n]) => `<button data-s="${k}" class="${src === k ? "active" : ""}">${n}</button>`).join("")}</div>
      <div class="pills wrap mb" id="tags"><button data-t="全部" class="${tag === "全部" ? "active" : ""}">全部题型</button>
        ${data.tags.filter((t) => tagN[t]).map((t) => `<button data-t="${esc(t)}" class="${tag === t ? "active" : ""}">${esc(t)}<small class="num">${tagN[t]}</small></button>`).join("")}</div>
      <div class="card">${list.map((c) => `<a class="paper-row case-row" href="#/case/${encodeURIComponent(c.id)}">
        <div class="info"><div class="t">${c.year ? `<span class="year-tag">${c.year}</span>` : ""}${esc(caseTitle(c).replace(/^\d{4}年/, ""))}${c.required ? ` <span class="chip warn">必答题</span>` : ""}</div>
          <div class="meta">${c.tags.map(esc).join(" · ")} · ${c.nq} 问${c.answered < c.nq ? `（${c.nq - c.answered} 问缺参考答案）` : ""}</div>
          <div class="meta">${esc(c.intro)}…</div></div>
        <div class="stat"><span class="meta">${c.rec ? `做过 ${c.rec.n} 次${c.rec.ai != null ? ` · AI ${c.rec.ai} 分` : c.rec.self != null ? ` · 自评 ${c.rec.self} 分` : ""}` : "还没做过"}</span></div></a>`).join("") || `<div class="empty">这一类还没有题。到资料库点“整理全部资料”。</div>`}</div>`;
    el.querySelectorAll("#tags button").forEach((b) => (b.onclick = () => { tag = b.dataset.t; store.set("rk-case", { tag, src }); draw(); }));
    el.querySelectorAll("#srcs button").forEach((b) => (b.onclick = () => { src = b.dataset.s; store.set("rk-case", { tag, src }); draw(); }));
  }
  draw();
}

async function caseView(el, id) {
  const c = await apiGet("/api/rk/case?id=" + encodeURIComponent(id));
  const draftKey = "rk-case-draft";
  const drafts = store.get(draftKey, {});
  const answers = drafts[id] || {};
  const start = Date.now();
  let submitted = false, tick = null;
  const totalScore = c.score || 25;

  function draw() {
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow"><a href="#/case">案例练习</a></div><h1>${esc(caseTitle(c))}</h1>
        <p>${c.tags.map(esc).join(" · ")} · ${totalScore} 分${c.required ? " · 必答题" : ""}。考场上每道案例大约 40–45 分钟，先看问题再读说明。</p></div>
        <span class="chip" id="clock">${fmtClock(0)}</span></div>
      <div class="case-layout">
        <div class="card case-mat"><h3>说明</h3><div class="prose">${md(c.material || "（这道题没有单独的说明）")}</div>
          ${c.fid ? `<p class="small mt"><a href="#/library/view/${esc(c.fid)}">看原卷（图、表在原卷里）</a></p>` : `<p class="small muted mt">题里提到的图、表在开源题库原文中可能缺失。</p>`}</div>
        <div class="stack">
          ${c.questions.map((q) => `<div class="card case-q">
            <div class="card-head"><h3>问题 ${q.n}${q.score ? ` <small class="muted">（${q.score} 分）</small>` : ""}</h3></div>
            <div class="prose small">${md(q.text)}</div>
            <textarea data-n="${q.n}" rows="7" placeholder="在这里作答。考场上要点式作答：先写结论，再分条说理由" ${submitted ? "readonly" : ""}>${esc(answers[q.n] || "")}</textarea>
            <div class="small muted">${(answers[q.n] || "").length} 字</div>
            ${submitted ? `<details class="ref" open><summary>参考答案</summary><div class="prose small">${q.answer ? md(q.answer) : "这一问没有参考答案，可以请 AI 批改。"}</div></details>
              <label class="field small">自评得分（满分 ${q.score || "?"}）<input type="number" min="0" max="${q.score || 25}" step="0.5" data-self="${q.n}"></label>` : ""}
          </div>`).join("")}
          ${c.analysis && submitted ? `<div class="card"><h3>解析</h3><div class="prose small">${md(c.analysis)}</div></div>` : ""}
          <div class="card">
            ${submitted ? `<div class="row"><button class="btn primary" id="save-self">保存自评</button><span class="small muted" id="self-sum"></span></div>
              <div class="mt" id="ai"></div>` : `<div class="row"><button class="btn primary lg" id="submit">交卷，看参考答案</button>
              <span class="small muted">作答会自动保存草稿</span></div>`}
          </div>
          ${c.history.length ? `<details class="card"><summary>以前的作答（${c.history.length}）</summary>${c.history.slice(0, 15).map((h) => `<div class="small mt">
            <b>${esc(h.created_at.slice(0, 16))} · 问题 ${h.q_index}</b>${h.ai_score != null ? ` · AI ${h.ai_score}/${h.ai_full}` : h.self_score != null ? ` · 自评 ${h.self_score}` : ""}
            <div class="ink2">${esc((h.answer || "").slice(0, 300))}</div></div>`).join("")}</details>` : ""}
        </div>
      </div>`;
    el.querySelectorAll("textarea[data-n]").forEach((t) => (t.oninput = () => {
      answers[t.dataset.n] = t.value;
      t.nextElementSibling.textContent = `${t.value.length} 字`;
      drafts[id] = answers; store.set(draftKey, drafts);
    }));
    const sub = el.querySelector("#submit");
    if (sub) sub.onclick = async () => {
      if (!Object.values(answers).some((x) => (x || "").trim())) { toast("先写一点再交卷"); return; }
      submitted = true;
      clearInterval(tick);
      const secs = Math.round((Date.now() - start) / 1000);
      const ids = [];
      for (const q of c.questions) {
        const r = await apiPost("/api/essays", { set_id: "case:" + id, q_index: q.n, answer: answers[q.n] || "", words: (answers[q.n] || "").length,
          seconds: Math.round(secs / c.questions.length), module: "案例分析", source: "案例练习" });
        ids.push(r.id);
      }
      c._ids = ids;
      delete drafts[id]; store.set(draftKey, drafts);
      draw();
    };
    const ss = el.querySelector("#save-self");
    if (ss) {
      ss.onclick = async () => {
        let sum = 0;
        for (const [i, q] of c.questions.entries()) {
          const v = el.querySelector(`[data-self="${q.n}"]`).value;
          if (v === "") continue;
          sum += +v;
          await apiPost("/api/rk/case/self", { id: c._ids?.[i], score: +v });
        }
        el.querySelector("#self-sum").textContent = `自评合计 ${sum} / ${totalScore}`;
        toast("已保存自评");
      };
      mountAIBox(el.querySelector("#ai"), {
        label: "请 AI 按评分点批改", kind: "rkcase",
        getBody: () => ({ material: c.material, score: totalScore,
          questions: c.questions.map((q) => ({ n: q.n, score: q.score, text: q.text, reference: q.answer, answer: answers[q.n] || "" })) }),
        onDone: async (text) => { if (c._ids?.[0]) await apiPost("/api/essays/feedback", { id: c._ids[0], ai_feedback: text }); },
      });
    }
  }
  draw();
  tick = setInterval(() => { const k = el.querySelector("#clock"); if (k) k.textContent = fmtClock(Math.round((Date.now() - start) / 1000)); else clearInterval(tick); }, 1000);
  return () => clearInterval(tick);
}

export async function render(el, ctx) {
  if (ctx.parts[1]) return caseView(el, ctx.parts[1]);
  return listView(el);
}
