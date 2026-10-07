import { apiGet, apiPost, content, esc, fmtClock, mountAIBox, shuffle, toast } from "../lib.js";

export async function render(el) {
  const data = await content("interview.json");
  const mine = (await apiGet("/api/interviews")).items;
  const types = Object.keys(data.types);
  let type = "全部";
  let q = null;
  let phase = "idle"; // idle → think → answer → done
  let t0 = 0, tick = null, savedId = null;
  const THINK = 60, ANSWER = 180;

  function nextQuestion() {
    const pool = data.questions.filter((x) => type === "全部" || x.type === type);
    const done = new Set(mine.map((m) => m.qid));
    const fresh = pool.filter((x) => !done.has(x.id));
    q = shuffle(fresh.length ? fresh : pool)[0];
    phase = "idle"; savedId = null;
    clearInterval(tick);
    draw();
  }

  function clockText() {
    if (phase === "think") return "思考 " + fmtClock(THINK - (Date.now() - t0) / 1000);
    if (phase === "answer") {
      const left = ANSWER - (Date.now() - t0) / 1000;
      return (left >= 0 ? "作答 " : "超时 ") + fmtClock(Math.abs(left));
    }
    return "03:00";
  }

  function start(p) {
    phase = p; t0 = Date.now();
    clearInterval(tick);
    tick = setInterval(() => {
      const c = document.getElementById("iclock");
      if (!c) return;
      c.textContent = clockText();
      if (phase === "think" && Date.now() - t0 >= THINK * 1000) { start("answer"); draw(); }
      c.classList.toggle("low", phase === "answer" && (Date.now() - t0) / 1000 > ANSWER - 30);
    }, 500);
    draw();
  }

  function draw() {
    const history = q ? mine.filter((m) => m.qid === q.id) : [];
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">面试练习</div><h1>结构化面试：计时开口说</h1>
        <p>真实面试每题约 3 分钟。先思考 1 分钟列提纲，再计时作答，最好大声说出来或录音回听。</p></div>
        <a class="btn" href="#/learn/interview">面试教程</a></div>
      <div class="seg mb" id="types">${["全部", ...types].map((t) => `<button data-t="${esc(t)}" class="${t === type ? "active" : ""}">${esc(t)}</button>`).join("")}</div>
      <div class="grid cols-main">
        <div class="card">
          ${q ? `
            <div class="row mb"><span class="chip brand">${esc(q.type)}</span><span class="small muted">已练 ${new Set(mine.map((m) => m.qid)).size} / ${data.questions.length} 题</span>
              <span class="spacer"></span><span class="clock ${phase === "idle" ? "" : ""}" id="iclock">${clockText()}</span></div>
            <div class="q-stem" style="font-size:18px;font-family:var(--font-display)">${esc(q.question)}</div>
            <div class="row mb">
              ${phase === "idle" ? `<button class="btn primary" id="think">开始思考（1 分钟）</button><button class="btn" id="answer">直接开始作答</button>` : ""}
              ${phase === "think" ? `<button class="btn primary" id="answer">思考好了，开始作答</button>` : ""}
              ${phase === "answer" ? `<button class="btn primary" id="stop">作答完毕</button>` : ""}
              <span class="spacer"></span><button class="btn ghost" id="next">换一题</button>
            </div>
            <textarea id="ians" rows="9" placeholder="写下你的答题提纲或要点（作答时可以边说边记关键词）"></textarea>
            ${phase === "done" ? `
              <div class="explain">
                <h3 class="mb">参考思路</h3>
                <div class="ref">${esc(q.guide)}</div>
                <div class="row mt"><button class="btn primary" id="save">${savedId ? "已保存" : "保存这次练习"}</button></div>
                <div class="mt" id="ai-iv"></div>
              </div>` : ""}
          ` : `<div class="empty"><h3>点“抽一道题”开始</h3><button class="btn primary mt" id="next">抽一道题</button></div>`}
        </div>
        <div class="stack" style="gap:16px">
          <div class="card"><h3 class="mb">${q ? esc(q.type) + "的答题思路" : "各题型答题思路"}</h3>
            ${q ? `<p class="ink2" style="margin:0">${esc(data.types[q.type])}</p>` :
              types.map((t) => `<div style="margin-bottom:8px"><b>${esc(t)}</b><div class="small ink2">${esc(data.types[t])}</div></div>`).join("")}
          </div>
          ${history.length ? `<div class="card"><h3 class="mb">这道题的历史练习</h3>${history.map((h) => `<details class="note-item"><summary class="small" style="cursor:pointer">${esc(h.created_at.slice(0, 16))} · 用时 ${fmtClock(h.seconds)}</summary>
            <div class="c small">${esc(h.answer)}</div>${h.ai_feedback ? `<div class="ai-box"><div class="ai-out">${esc(h.ai_feedback)}</div></div>` : ""}</details>`).join("")}</div>` : ""}
        </div>
      </div>`;
    bind();
  }

  function bind() {
    el.querySelectorAll("#types button").forEach((x) => (x.onclick = () => { type = x.dataset.t; nextQuestion(); }));
    const on = (id, fn) => { const b = el.querySelector(id); if (b) b.onclick = fn; };
    const ta = el.querySelector("#ians");
    if (ta) {
      ta.value = sessionText;
      ta.oninput = () => (sessionText = ta.value);
    }
    on("#next", () => { sessionText = ""; nextQuestion(); });
    on("#think", () => start("think"));
    on("#answer", () => start("answer"));
    on("#stop", () => {
      answeredSec = phase === "answer" ? Math.round((Date.now() - t0) / 1000) : 0;
      phase = "done"; clearInterval(tick); draw();
    });
    on("#save", async () => {
      if (savedId) return;
      const r = await apiPost("/api/interviews", { qid: q.id, answer: sessionText, seconds: answeredSec });
      savedId = r.id;
      mine.unshift({ id: r.id, qid: q.id, answer: sessionText, seconds: answeredSec, created_at: new Date().toISOString().replace("T", " "), ai_feedback: "" });
      toast("已保存");
      draw();
    });
    const ai = el.querySelector("#ai-iv");
    if (ai) mountAIBox(ai, {
      label: "请 AI 点评我的作答",
      kind: "interview",
      getBody: () => {
        if (!sessionText.trim()) throw new Error("先在上面的输入框写下你的作答要点");
        return { question: q.question, type: q.type, guide: q.guide, answer: sessionText };
      },
      onDone: async (text) => {
        if (!savedId) {
          const r = await apiPost("/api/interviews", { qid: q.id, answer: sessionText, seconds: answeredSec, ai_feedback: text });
          savedId = r.id;
          mine.unshift({ id: r.id, qid: q.id, answer: sessionText, seconds: answeredSec, created_at: new Date().toISOString().replace("T", " "), ai_feedback: text });
        } else {
          await apiPost("/api/interviews/feedback", { id: savedId, ai_feedback: text });
        }
      },
    });
  }

  let sessionText = "", answeredSec = 0;
  draw();
  return () => clearInterval(tick);
}
