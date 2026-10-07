import { apiGet, apiPost, content, esc, fmtClock, mountAIBox, shuffle, store, streamAI, toast } from "../lib.js";

// ---------------------------------------------------------------- 录音与停顿分析
// 录音用 MediaRecorder；同时用 AudioContext 每 100 毫秒测一次音量，统计说话时长和停顿（超过 2 秒没声音算一次停顿）
const PAUSE_SEC = 2;

function startRecorder(stream) {
  const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg"].find((t) => window.MediaRecorder?.isTypeSupported?.(t)) || "";
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  const chunks = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = ctx.createMediaStreamSource(stream);
  const an = ctx.createAnalyser();
  an.fftSize = 1024;
  src.connect(an);
  const buf = new Float32Array(an.fftSize);
  const m = { t0: Date.now(), speaking: 0, pauses: 0, longest: 0, silent: 0, floor: 0.01, samples: 0 };
  const timer = setInterval(() => {
    an.getFloatTimeDomainData(buf);
    let s = 0;
    for (const v of buf) s += v * v;
    const rms = Math.sqrt(s / buf.length);
    m.samples++;
    if (m.samples < 10) m.floor = Math.max(m.floor, rms * 1.5); // 开头一秒估一下环境噪声
    const loud = rms > Math.max(0.015, m.floor * 2);
    if (loud) {
      if (m.silent >= PAUSE_SEC && m.speaking > 0) { m.pauses++; m.longest = Math.max(m.longest, m.silent); }
      m.silent = 0;
      m.speaking += 0.1;
    } else m.silent += 0.1;
  }, 100);
  rec.start(1000);
  return {
    stop: () => new Promise((resolve) => {
      clearInterval(timer);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        ctx.close().catch(() => {});
        const total = (Date.now() - m.t0) / 1000;
        resolve({
          blob: new Blob(chunks, { type: rec.mimeType || "audio/webm" }),
          pauses: { speech_seconds: Math.round(total), speaking_seconds: Math.round(m.speaking), pauses: m.pauses, longest: Math.round(m.longest) },
        });
      };
      rec.stop();
    }),
  };
}

function metricsText(m) {
  if (!m || !Object.keys(m).length) return "";
  const parts = [];
  if (m.speech_seconds) parts.push(`时长 ${fmtClock(m.speech_seconds)}`);
  if (m.speaking_seconds != null && m.speech_seconds) parts.push(`有声 ${Math.round((m.speaking_seconds / m.speech_seconds) * 100)}%`);
  if (m.pauses != null) parts.push(`停顿 ${m.pauses} 次${m.pauses ? `（最长 ${m.longest} 秒）` : ""}`);
  if (m.cpm) parts.push(`语速 ${m.cpm} 字/分${m.cpm < 150 ? "（偏慢）" : m.cpm > 260 ? "（偏快）" : ""}`);
  if (m.fillers && Object.keys(m.fillers).length) parts.push("口头禅 " + Object.entries(m.fillers).map(([k, v]) => `“${k}”×${v}`).join(" "));
  return parts.join(" · ");
}

export async function render(el) {
  const data = await content("interview.json");
  const mine = (await apiGet("/api/interviews")).items;
  const asr = await apiGet("/api/asr/status").catch(() => ({ ready: false }));
  const types = Object.keys(data.types);
  let type = "全部";
  let q = null;
  let phase = "idle"; // idle → think → answer → done
  let t0 = 0, tick = null, savedId = null;
  let recorder = null, recording = null, audioURL = "", uploaded = false, metrics = null, transcript = "";
  let followTurns = [];
  const THINK = 60, ANSWER = 180;
  const useMic = () => store.get("iv-record", true) && !!navigator.mediaDevices?.getUserMedia && !!window.MediaRecorder;

  function resetTake() {
    if (recorder) recorder.stop().catch?.(() => {});
    recorder = null; recording = null; uploaded = false; metrics = null; transcript = ""; followTurns = [];
    if (audioURL) URL.revokeObjectURL(audioURL);
    audioURL = "";
  }

  function nextQuestion() {
    const pool = data.questions.filter((x) => type === "全部" || x.type === type);
    const done = new Set(mine.map((m) => m.qid));
    const fresh = pool.filter((x) => !done.has(x.id));
    q = shuffle(fresh.length ? fresh : pool)[0];
    phase = "idle"; savedId = null;
    clearInterval(tick);
    resetTake();
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

  async function beginRecording() {
    if (!useMic() || recorder) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder = startRecorder(stream);
      draw();
    } catch (e) {
      toast("打不开麦克风：" + (e.message || e.name) + "。可以在设置里关掉“作答时录音”", 5000);
    }
  }

  async function endRecording() {
    if (!recorder) return;
    const r = recorder;
    recorder = null;
    recording = await r.stop();
    metrics = { ...recording.pauses };
    audioURL = URL.createObjectURL(recording.blob);
  }

  function start(p) {
    phase = p; t0 = Date.now();
    clearInterval(tick);
    tick = setInterval(() => {
      const c = document.getElementById("iclock");
      if (!c) return;
      c.textContent = clockText();
      if (phase === "think" && Date.now() - t0 >= THINK * 1000) { start("answer"); }
      c.classList.toggle("low", phase === "answer" && (Date.now() - t0) / 1000 > ANSWER - 30);
    }, 500);
    if (p === "answer") beginRecording();
    draw();
  }

  // 先保存这次练习（拿到 id），再上传录音和语音指标
  async function ensureSaved(aiFeedback = "") {
    if (!savedId) {
      const r = await apiPost("/api/interviews", { qid: q.id, answer: sessionText, seconds: answeredSec, ai_feedback: aiFeedback });
      savedId = r.id;
      mine.unshift({ id: r.id, qid: q.id, answer: sessionText, seconds: answeredSec, created_at: new Date().toISOString().replace("T", " "), ai_feedback: aiFeedback });
    }
    if (recording && !uploaded) {
      const r = await fetch(`/api/interviews/audio?id=${savedId}`, { method: "POST", headers: { "Content-Type": recording.blob.type.split(";")[0] || "audio/webm" }, body: recording.blob });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.error) throw new Error(j.error || "上传录音失败");
      uploaded = true;
      const m = mine.find((x) => x.id === savedId);
      if (m) m.audio = j.audio;
    }
    if (metrics) {
      const r = await apiPost("/api/interviews/metrics", { id: savedId, pauses: recording?.pauses || {}, transcript, speech_seconds: metrics.speech_seconds });
      metrics = { ...metrics, ...r.metrics };
      const m = mine.find((x) => x.id === savedId);
      if (m) Object.assign(m, { metrics: JSON.stringify(metrics), transcript });
    }
    return savedId;
  }

  function takeBlock() {
    if (phase !== "done" || !recording) return "";
    return `<div class="ai-box mt"><div class="row"><b class="small">我的录音</b><span class="spacer"></span>
        ${asr.ready ? `<button class="btn sm" id="asr">转成文字</button>` : ""}</div>
      <audio controls src="${audioURL}" style="width:100%;margin-top:6px"></audio>
      <div class="small ink2 mt">${esc(metricsText(metrics))}</div>
      ${transcript ? `<details class="mt" open><summary class="small" style="cursor:pointer">语音转写</summary><div class="small" style="white-space:pre-wrap">${esc(transcript)}</div></details>` : ""}
      ${!asr.ready && asr.hint ? `<p class="small muted" style="margin:6px 0 0">${esc(asr.hint)}</p>` : ""}</div>`;
  }

  function followBlock() {
    if (phase !== "done") return "";
    const last = followTurns[followTurns.length - 1];
    const finished = followTurns.length >= 2 && last?.a && last.summary;
    return `<div class="card mt" id="follow"><div class="card-head"><h3>考官追问</h3><span class="small muted">真实面试常会追问 1–2 个问题，考应变</span></div>
      ${followTurns.map((t, i) => `<div class="mb"><div class="small"><b>追问 ${i + 1}：</b>${esc(t.q)}</div>
        ${t.a ? `<div class="small ink2">我的回答：${esc(t.a)}</div>` : `<textarea id="fa" rows="3" class="mt" placeholder="像现场一样，先想 10 秒再回答（可以写要点）"></textarea>
          <button class="btn sm primary mt" id="fa-go">回答完毕</button>`}</div>`).join("")}
      ${finished ? `<div class="ai-box"><b class="small">考官总评</b><div class="ai-out">${esc(last.summary)}</div></div>` : ""}
      <div class="ai-out small" id="f-stream"></div>
      ${!followTurns.length ? `<button class="btn" id="f-start">请考官追问</button>` : ""}</div>`;
  }

  function draw() {
    const history = q ? mine.filter((m) => m.qid === q.id) : [];
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">面试练习</div><h1>结构化面试：计时开口说</h1>
        <p>真实面试每题约 3 分钟。先思考 1 分钟列提纲，再计时作答；开着录音大声说出来，结束后回听、看停顿和语速。<span class="small muted">第一次录音时窗口会问是否允许使用麦克风，选“允许”。</span></p></div>
        <a class="btn" href="#/learn/interview">面试教程</a></div>
      <div class="row mb"><div class="seg" id="types">${["全部", ...types].map((t) => `<button data-t="${esc(t)}" class="${t === type ? "active" : ""}">${esc(t)}</button>`).join("")}</div>
        <span class="spacer"></span><label class="small row" style="gap:6px"><input type="checkbox" id="mic" ${useMic() ? "checked" : ""}
          ${navigator.mediaDevices?.getUserMedia && window.MediaRecorder ? "" : "disabled"}> 作答时录音</label></div>
      <div class="grid cols-main">
        <div class="card">
          ${q ? `
            <div class="row mb"><span class="chip brand">${esc(q.type)}</span><span class="small muted">已练 ${new Set(mine.map((m) => m.qid)).size} / ${data.questions.length} 题</span>
              <span class="spacer"></span>${recorder ? `<span class="chip bad">● 录音中</span>` : ""}<span class="clock" id="iclock">${clockText()}</span></div>
            <div class="q-stem" style="font-size:18px;font-family:var(--font-display)">${esc(q.question)}</div>
            <div class="row mb">
              ${phase === "idle" ? `<button class="btn primary" id="think">开始思考（1 分钟）</button><button class="btn" id="answer">直接开始作答</button>` : ""}
              ${phase === "think" ? `<button class="btn primary" id="answer">思考好了，开始作答</button>` : ""}
              ${phase === "answer" ? `<button class="btn primary" id="stop">作答完毕</button>` : ""}
              <span class="spacer"></span><button class="btn ghost" id="next">换一题</button>
            </div>
            <textarea id="ians" rows="9" placeholder="写下你的答题提纲或要点（作答时可以边说边记关键词）"></textarea>
            ${takeBlock()}
            ${phase === "done" ? `
              <div class="explain">
                <h3 class="mb">参考思路</h3>
                <div class="ref">${esc(q.guide)}</div>
                <div class="row mt"><button class="btn primary" id="save">${savedId ? "已保存" : "保存这次练习"}</button></div>
                <div class="mt" id="ai-iv"></div>
              </div>` : ""}
          ` : `<div class="empty"><h3>点“抽一道题”开始</h3><button class="btn primary mt" id="next">抽一道题</button></div>`}
          ${followBlock()}
        </div>
        <div class="stack" style="gap:16px">
          <div class="card"><h3 class="mb">${q ? esc(q.type) + "的答题思路" : "各题型答题思路"}</h3>
            ${q ? `<p class="ink2" style="margin:0">${esc(data.types[q.type])}</p>` :
              types.map((t) => `<div style="margin-bottom:8px"><b>${esc(t)}</b><div class="small ink2">${esc(data.types[t])}</div></div>`).join("")}
          </div>
          ${history.length ? `<div class="card"><h3 class="mb">这道题的历史练习</h3>${history.map((h) => {
            let hm = null;
            try { hm = h.metrics ? JSON.parse(h.metrics) : null; } catch { hm = null; }
            return `<details class="note-item"><summary class="small" style="cursor:pointer">${esc((h.created_at || "").slice(0, 16))} · 用时 ${fmtClock(h.seconds)}${h.audio ? " · 有录音" : ""}</summary>
              ${h.audio ? `<audio controls preload="none" src="/api/recording/${esc(h.audio)}" style="width:100%"></audio>` : ""}
              ${hm ? `<div class="small muted">${esc(metricsText(hm))}</div>` : ""}
              <div class="c small">${esc(h.answer)}</div>${h.ai_feedback ? `<div class="ai-box"><div class="ai-out">${esc(h.ai_feedback)}</div></div>` : ""}</details>`;
          }).join("")}</div>` : ""}
        </div>
      </div>`;
    bind();
  }

  async function askFollow() {
    const box = el.querySelector("#f-stream");
    const btn = el.querySelector("#f-start");
    if (btn) btn.disabled = true;
    try {
      const body = { question: q.question, type: q.type, answer: sessionText, transcript, turns: followTurns };
      const text = (await streamAI("followup", body, (t) => { if (box) box.textContent = t; })).trim();
      const last = followTurns[followTurns.length - 1];
      if (followTurns.length >= 2 && last?.a) last.summary = text;
      else followTurns.push({ q: text, a: "" });
      draw();
    } catch (e) {
      toast(e.message, 4000);
      if (btn) btn.disabled = false;
    }
  }

  function bind() {
    el.querySelectorAll("#types button").forEach((x) => (x.onclick = () => { type = x.dataset.t; nextQuestion(); }));
    const mic = el.querySelector("#mic");
    if (mic) mic.onchange = () => store.set("iv-record", mic.checked);
    const on = (id, fn) => { const b = el.querySelector(id); if (b) b.onclick = fn; };
    const ta = el.querySelector("#ians");
    if (ta) {
      ta.value = sessionText;
      ta.oninput = () => (sessionText = ta.value);
    }
    on("#next", () => { sessionText = ""; nextQuestion(); });
    on("#think", () => start("think"));
    on("#answer", () => start("answer"));
    on("#stop", async () => {
      answeredSec = phase === "answer" ? Math.round((Date.now() - t0) / 1000) : 0;
      phase = "done"; clearInterval(tick);
      await endRecording();
      draw();
    });
    on("#save", async () => {
      if (savedId && (uploaded || !recording)) return;
      try { await ensureSaved(); toast("已保存" + (recording ? "（含录音）" : "")); } catch (e) { toast(e.message, 4000); }
      draw();
    });
    on("#asr", async (e) => {
      const b = e.currentTarget;
      b.disabled = true; b.textContent = "正在转写…（第一次要加载模型，较慢）";
      try {
        await ensureSaved();
        transcript = (await apiPost("/api/interviews/transcribe", { id: savedId })).transcript;
        await ensureSaved();
        toast("转写完成");
      } catch (err) { toast(err.message, 5000); }
      draw();
    });
    on("#f-start", askFollow);
    on("#fa-go", async () => {
      const a = el.querySelector("#fa").value.trim();
      if (!a) { toast("先回答再继续"); return; }
      followTurns[followTurns.length - 1].a = a;
      await askFollow();
    });
    const ai = el.querySelector("#ai-iv");
    if (ai) mountAIBox(ai, {
      label: "请 AI 点评我的作答",
      kind: "interview",
      getBody: () => {
        if (!sessionText.trim() && !transcript) throw new Error("先在上面的输入框写下你的作答要点（或把录音转成文字）");
        return { question: q.question, type: q.type, guide: q.guide, answer: sessionText, transcript, metrics };
      },
      onDone: async (text) => {
        const had = savedId;
        await ensureSaved(text);
        if (had) await apiPost("/api/interviews/feedback", { id: savedId, ai_feedback: text });
        const m = mine.find((x) => x.id === savedId);
        if (m) m.ai_feedback = text;
      },
    });
  }

  let sessionText = "", answeredSec = 0;
  draw();
  return () => { clearInterval(tick); if (recorder) recorder.stop(); };
}
