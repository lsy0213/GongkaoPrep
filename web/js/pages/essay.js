import { apiGet, apiPost, countChars, esc, fmtClock, mountAIBox, scoreTrend, store, toast } from "../lib.js";

const SRC = [["builtin", "原创练习"], ["国考", "国考真题"], ["四川", "四川真题"]];
// 真题卷别：把资料库里五花八门的卷名归成几类，按这个顺序排
const LEVELS = ["地市级", "副省级", "省市卷", "县乡卷", "行政执法", "上半年", "下半年", "B/C 卷", "不分卷"];
function levelOf(s) {
  const l = s.level;
  if (/县乡|乡镇/.test(l)) return "县乡卷";
  if (/^[A-Z]卷$/.test(l)) return "B/C 卷";
  if (l === s.exam) return "不分卷"; // 早年没有分级的卷子，level 只记了考试名
  return l;
}

// AI 批改得分走势（换算成得分率，不同满分的题放在一起比）
function essayTrend(mine) {
  const scored = mine.filter((m) => m.ai_score != null && m.ai_full).slice().reverse();
  if (scored.length < 2) return "";
  const pts = scored.map((m) => ({ v: Math.round((m.ai_score / m.ai_full) * 100),
    tip: `${(m.created_at || "").slice(5, 16)}：${m.ai_score} / ${m.ai_full}` }));
  const recent = pts.slice(-5).reduce((a, p) => a + p.v, 0) / Math.min(5, pts.length);
  return `<div class="card mb"><div class="card-head"><h3>AI 批改得分率走势</h3><span class="small muted">最近 5 次平均 ${Math.round(recent)}% · 共 ${pts.length} 次</span></div>
    ${scoreTrend(pts, { target: 70, label: "七成" })}
    <p class="small muted" style="margin:0">每次按同一套评分细则（要点 70%、结构 15%、语言 15%）批改；得分率 = AI 估分 ÷ 满分。</p></div>`;
}

export async function render(el, ctx) {
  const data = await apiGet("/api/essay_sets");
  const mine = (await apiGet("/api/essays")).items;
  const setId = ctx.parts[1];

  if (!setId) {
    const src = store.get("essay-src", data.real_count ? "国考" : "builtin");
    const pool = data.sets.filter((s) => (src === "builtin" ? !s.real : s.exam === src));
    // 原创题按主题大类筛选（主题写作“大类 · 小类”），真题按卷别筛选
    const domainOf = src === "builtin" ? (s) => s.theme.split(" · ")[0] : levelOf;
    const domKey = src === "builtin" ? "essay-domain" : `essay-level:${src}`;
    const domains = [...new Set(pool.map(domainOf))];
    const rank = (d) => (LEVELS.includes(d) ? LEVELS.indexOf(d) : LEVELS.length);
    domains.sort(src === "builtin"
      ? (a, b) => pool.filter((s) => domainOf(s) === b).length - pool.filter((s) => domainOf(s) === a).length
      : (a, b) => rank(a) - rank(b));
    let dom = store.get(domKey, "");
    if (!domains.includes(dom)) dom = "";
    const sets = dom ? pool.filter((s) => domainOf(s) === dom) : pool;
    const card = (s) => {
      const n = mine.filter((m) => m.set_id === s.id).length;
      const done = new Set(mine.filter((m) => m.set_id === s.id).map((m) => m.q_index)).size;
      return `<a class="card" href="#/essay/${s.id}" style="color:inherit;text-decoration:none">
        <div class="row mb"><span class="chip brand">${esc(s.theme)}</span><span class="chip">${esc(s.level)}</span></div>
        <h3 style="margin-bottom:8px">${esc(s.title)}</h3>
        <div class="small ink2">${s.materials.length} 则材料 · ${s.questions.length} 道题：${[...new Set(s.questions.map((q) => q.type))].join("、")}</div>
        <div class="progress mt"><i style="width:${(done / s.questions.length) * 100}%"></i></div>
        <div class="small muted mt">${done ? `已完成 ${done}/${s.questions.length} 题，共作答 ${n} 次` : "还没做过"}</div>
      </a>`;
    };
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">申论练习</div><h1>读材料，找要点，动笔写</h1>
        <p>每套题包含一组材料和 3–5 道题。写完后对照参考答案自评，配置了 AI 助教还可以请 AI 估分和点评。${data.real_count ? `历年真题 ${data.real_count} 套来自你的资料库。` : ""}</p></div>
        <a class="btn" href="#/learn/essay">先学申论教程</a></div>
      ${essayTrend(mine)}
      <div class="row mb"><div class="seg" id="src">${SRC.map(([k, n]) => `<button data-src="${k}" class="${src === k ? "active" : ""}">${n}（${data.sets.filter((s) => (k === "builtin" ? !s.real : s.exam === k)).length}）</button>`).join("")}</div></div>
      ${domains.length > 1 ? `<div class="row mb" id="dom" style="flex-wrap:wrap;gap:6px">${[["", "全部", pool.length], ...domains.map((d) => [d, d, pool.filter((s) => domainOf(s) === d).length])]
        .map(([k, n, c]) => `<button class="chip${dom === k ? " brand" : ""}" data-dom="${esc(k)}" style="cursor:pointer">${esc(n)} ${c}</button>`).join("")}</div>` : ""}
      ${sets.length ? `<div class="grid cols-3">${sets.map(card).join("")}</div>` : `<div class="card empty"><h3>还没有这一类题</h3><p>真题来自资料库：到“资料库”页点“整理资料”。</p><a class="btn" href="#/library">去资料库</a></div>`}
      <p class="small muted mt">${src === "builtin" ? esc(data.note) : "真题由软件从 PDF 自动整理，个别题目的材料分段或参考答案可能不完整，可在题目页点“原卷”核对。"}</p>`;
    el.querySelectorAll("#dom [data-dom]").forEach((x) => (x.onclick = () => { store.set(domKey, x.dataset.dom); render(el, ctx); }));
    el.querySelectorAll("#src button").forEach((x) => (x.onclick = () => { store.set("essay-src", x.dataset.src); render(el, ctx); }));
    return;
  }

  const set = data.sets.find((s) => s.id === setId);
  if (!set) { el.innerHTML = `<div class="card empty"><h3>没有找到这套题</h3><a href="#/essay">返回</a></div>`; return; }
  let qi = Math.min(+(ctx.query.q || 0), set.questions.length - 1);
  let timerStart = 0, tick = null, phase = "write";
  let lastSaved = null;

  function draftKey() { return `essay:${set.id}:${qi}`; }

  function draw() {
    const q = set.questions[qi];
    const draft = store.get(draftKey(), "");
    const history = mine.filter((m) => m.set_id === set.id && m.q_index === qi);
    el.innerHTML = `
      <div class="row mb"><a class="btn sm ghost" href="#/essay">← 申论练习</a><span class="spacer"></span>
        ${set.fid ? `<a class="btn sm ghost" href="#/library/view/${set.fid}">原卷</a>` : ""}
        <span class="chip brand">${esc(set.theme)}</span><span class="chip">${esc(set.level)}</span></div>
      <h1 class="mb">${esc(set.title)}</h1>
      <div class="essay-layout">
        <div class="card materials">
          ${set.materials.map((m) => `<h4>${esc(m.title)}</h4>${m.text.split("\n").filter(Boolean).map((p) => `<p>${esc(p)}</p>`).join("")}`).join("")}
        </div>
        <div class="stack" style="gap:16px">
          <div class="card">
            <div class="tabs" style="margin-bottom:14px">${set.questions.map((x, i) => `<button data-q="${i}" class="${i === qi ? "active" : ""}">第 ${i + 1} 题 · ${esc(x.type)}</button>`).join("")}</div>
            <div class="q-stem" style="margin-bottom:8px">${esc(q.question)}</div>
            ${q.requirement ? `<div class="small ink2" style="white-space:pre-wrap">要求：${esc(q.requirement)}</div>` : ""}
            <div class="row small muted mt">${q.words ? `<span>${esc(q.words)}</span>` : ""}${q.score ? `<span>· ${q.score} 分</span>` : ""}${q.minutes ? `<span>· 建议用时 ${q.minutes} 分钟</span>` : ""}</div>
          </div>
          <div class="card">
            <div class="row mb">
              <h3>我的作答</h3><span class="spacer"></span>
              <span class="clock" id="eclock">${timerStart ? fmtClock((Date.now() - timerStart) / 1000) : "00:00"}</span>
              ${timerStart ? "" : `<button class="btn sm" id="tstart">开始计时</button>`}
            </div>
            <textarea class="paper" id="ans" rows="14" placeholder="先读材料、列要点，再在这里作答。草稿会自动保存在本机。" ${phase === "check" ? "readonly" : ""}>${esc(draft)}</textarea>
            <div class="row mt"><span class="small muted num" id="wc">${countChars(draft)} 字</span><span class="small muted">（${esc(q.words)}）</span>
              <span class="spacer"></span>
              ${phase === "write" ? `<button class="btn primary" id="submit">写完了，对照要点</button>` : `<button class="btn" id="rewrite">继续修改</button>`}</div>
          </div>
          ${phase === "check" ? checkCard(q) : ""}
          ${history.length ? `<div class="card"><h3 class="mb">历史作答（${history.length}）</h3>
            ${history.map((h) => `<details class="note-item"><summary class="row" style="cursor:pointer">
              <span class="small">${esc(h.created_at.slice(0, 16))}</span><span class="small muted">${h.words} 字 · 用时 ${fmtClock(h.seconds)}</span>
              ${h.self_score != null ? `<span class="chip">自评 ${h.self_score} 分</span>` : ""}${h.ai_score != null ? `<span class="chip brand">AI 估分 ${h.ai_score} / ${h.ai_full}</span>` : h.ai_feedback ? `<span class="chip brand">有 AI 点评</span>` : ""}</summary>
              <div class="c">${esc(h.answer)}</div>
              ${h.ai_feedback ? `<div class="ai-box mt"><b class="small">AI 点评</b><div class="ai-out">${esc(h.ai_feedback)}</div></div>` : ""}</details>`).join("")}
          </div>` : ""}
        </div>
      </div>`;
    bind(q);
  }

  function checkCard(q) {
    const pts = q.points || [];
    const max = q.score || 100;
    return `<div class="card" id="check">
      <div class="card-head"><h3>${pts.length ? "对照参考要点自评" : "对照参考答案自评"}</h3><span class="small muted">${pts.length ? "答到了就勾上" : "逐条比对要点，再给自己打分"}</span></div>
      ${pts.length ? `<ul class="checklist">${pts.map((p, i) => `<li><label><input type="checkbox" data-pt="${i}"> <span>${esc(p)}</span></label></li>`).join("")}</ul>` : ""}
      <div class="row mt">${pts.length ? `<span>要点覆盖 <b class="num" id="cov">0</b> / ${pts.length}</span>` : ""}<span class="spacer"></span>
        <label class="row small">自评得分 <input type="number" id="score" min="0" max="${max}" step="0.5" style="width:80px"> / ${q.score || "—"}</label></div>
      ${q.reference ? (pts.length ? `<details class="mt"><summary class="small ink2" style="cursor:pointer">查看参考答案</summary><div class="ref mt">${esc(q.reference)}</div></details>`
        : `<div class="ref mt" style="white-space:pre-wrap">${esc(q.reference)}</div>`) : `<p class="small muted">这道题没有整理出参考答案，可以点上方“原卷”查看答案原文。</p>`}
      <div class="row mt"><button class="btn primary" id="save">保存这次作答</button><span class="small muted" id="saved-hint"></span></div>
      <div class="mt" id="ai-essay"></div>
    </div>`;
  }

  function bind(q) {
    el.querySelectorAll("[data-q]").forEach((x) => (x.onclick = () => {
      qi = +x.dataset.q; phase = "write"; lastSaved = null; history.replaceState(null, "", `#/essay/${set.id}?q=${qi}`); draw();
    }));
    const ans = el.querySelector("#ans");
    ans.oninput = () => {
      store.set(draftKey(), ans.value);
      el.querySelector("#wc").textContent = countChars(ans.value) + " 字";
      if (!timerStart) startTimer();
    };
    const ts = el.querySelector("#tstart");
    if (ts) ts.onclick = startTimer;
    const sub = el.querySelector("#submit");
    if (sub) sub.onclick = () => {
      if (countChars(ans.value) < 10) { toast("先写一些内容再对照要点"); return; }
      phase = "check"; draw();
      el.querySelector("#check").scrollIntoView({ behavior: "smooth", block: "start" });
    };
    const rw = el.querySelector("#rewrite");
    if (rw) rw.onclick = () => { phase = "write"; draw(); };
    if (phase !== "check") return;
    const boxes = el.querySelectorAll("[data-pt]");
    const scoreEl = el.querySelector("#score");
    boxes.forEach((b) => (b.onchange = () => {
      const n = [...boxes].filter((x) => x.checked).length;
      el.querySelector("#cov").textContent = n;
      scoreEl.value = Math.round((n / q.points.length) * (q.score || 0) * 0.85 * 2) / 2; // 要点之外还看结构和语言，按 85% 折算
    }));
    el.querySelector("#save").onclick = async () => {
      const text = ans.value;
      const body = {
        set_id: set.id, q_index: qi, answer: text, words: countChars(text),
        seconds: timerStart ? Math.round((Date.now() - timerStart) / 1000) : 0,
        self_score: scoreEl.value === "" ? null : +scoreEl.value,
        checked: [...boxes].filter((x) => x.checked).map((x) => +x.dataset.pt),
      };
      const r = await apiPost("/api/essays", body);
      lastSaved = r.id;
      mine.unshift({ ...body, id: r.id, created_at: new Date().toISOString().replace("T", " "), ai_feedback: "" });
      store.set(draftKey(), "");
      stopTimer();
      el.querySelector("#saved-hint").textContent = "已保存。可以继续请 AI 点评，点评也会存进这次作答。";
      toast("作答已保存");
    };
    mountAIBox(el.querySelector("#ai-essay"), {
      label: "请 AI 批改并估分",
      kind: "essay",
      getBody: () => ({
        materials: set.materials.map((m) => m.title + "\n" + m.text).join("\n\n"),
        question: q.question, requirement: q.requirement, words: q.words, score: q.score,
        points: q.points, reference: q.reference, answer: ans.value,
      }),
      onDone: async (text) => {
        if (!lastSaved) {
          // 还没保存就先请 AI 批改：连作答一起存下来，分数才能进走势
          const r = await apiPost("/api/essays", {
            set_id: set.id, q_index: qi, answer: ans.value, words: countChars(ans.value),
            seconds: timerStart ? Math.round((Date.now() - timerStart) / 1000) : 0, self_score: null, checked: [],
          });
          lastSaved = r.id;
          mine.unshift({ id: r.id, set_id: set.id, q_index: qi, answer: ans.value, words: countChars(ans.value),
            seconds: 0, created_at: new Date().toISOString().replace("T", " "), ai_feedback: "" });
        }
        const r = await apiPost("/api/essays/feedback", { id: lastSaved, ai_feedback: text });
        const m = mine.find((x) => x.id === lastSaved);
        if (m) Object.assign(m, { ai_feedback: text, ai_score: r.ai_score, ai_full: r.ai_full });
        if (r.ai_score != null) toast(`AI 估分 ${r.ai_score} / ${r.ai_full}，已记入走势`);
      },
    });
  }

  function startTimer() {
    if (timerStart) return;
    timerStart = Date.now();
    const ts = el.querySelector("#tstart");
    if (ts) ts.remove();
    tick = setInterval(() => {
      const c = document.getElementById("eclock");
      if (c) c.textContent = fmtClock((Date.now() - timerStart) / 1000);
    }, 1000);
  }
  function stopTimer() { clearInterval(tick); timerStart = 0; }

  draw();
  return () => clearInterval(tick);
}
