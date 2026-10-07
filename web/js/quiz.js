// 做题引擎：练习模式（选完立即看解析）、考试模式（交卷后看结果）、复习模式（错题重做）
import { apiGet, apiPost, cropHTML, getQuestions, esc, fmtClock, LETTERS, md, MODULES, MODULE_SHORT, mountAIBox, needsCrop, srcLabel, store, toast } from "./lib.js";
import { refreshBadge } from "./app.js";

const MODE_NAME = { practice: "练习", exam: "模考", review: "错题复习" };

// 做到一半的题（窗口关了、软件崩了、误点了别的页面）：每次作答、翻页和每 15 秒存一次，下次可以接着做
const DRAFT_KEY = "quiz-draft";

export function quizDraft() {
  const d = store.get(DRAFT_KEY, null);
  return d && Array.isArray(d.ids) && d.ids.length ? d : null;
}

export function dropQuizDraft() {
  store.set(DRAFT_KEY, null);
}

// 页面顶部的“继续上次没做完的题”提示条（app.js 在每个页面渲染后调用）
export function draftBannerHTML() {
  const d = quizDraft();
  if (!d) return "";
  const done = Object.keys(d.answers || {}).length;
  const left = d.timeLimit ? Math.max(0, d.timeLimit - d.elapsed) : 0;
  return `<div class="card draft-bar" id="draft-bar"><div class="row">
    <span>📝 <b>${esc(d.title)}</b> 还没做完：已答 ${done}/${d.ids.length} 题${d.timeLimit ? `，剩余 ${fmtClock(left)}（关闭期间不计时）` : ""}，存于 ${esc((d.savedAt || "").slice(5, 16))}</span>
    <span class="spacer"></span><a class="btn sm primary" href="#/resume">继续做</a>
    <button class="btn sm ghost" data-draft-drop>放弃</button></div></div>`;
}

export async function runQuiz(el, { title, ids, mode = "practice", timeLimit = 0, onAgain = null, resume = null }) {
  const data = await getQuestions(ids);
  const progress = await apiGet("/api/progress");
  // 没有答案的真题（答案文件是扫描件等）不能判分，不出
  const qs = data.questions.filter((q) => q.answer != null);
  if (!qs.length) {
    el.innerHTML = `<div class="card empty"><h3>没有可做的题</h3><p>换个条件试试。</p></div>`;
    if (resume) dropQuizDraft();
    return () => {};
  }
  const st = {
    idx: 0, answers: {}, revealed: {}, flags: {}, spent: {}, start: Date.now(), lastSwitch: Date.now(),
    finished: false, favorites: new Set(progress.favorites), notes: progress.notes,
    crop: {}, // 每题手动切换“原卷 / 文字”
  };
  if (resume) {
    Object.assign(st, {
      idx: Math.min(resume.idx || 0, qs.length - 1), answers: resume.answers || {}, revealed: resume.revealed || {},
      flags: resume.flags || {}, spent: resume.spent || {}, start: Date.now() - (resume.elapsed || 0) * 1000,
    });
  }
  const instant = mode !== "exam";
  let clock = null;
  let keyHandler = null;
  let lastSave = 0;

  function saveDraft(force = false) {
    if (st.finished) return;
    if (!force && Date.now() - lastSave < 1000) return;
    if (!Object.keys(st.answers).length && !resume) return; // 还一题没答，不算“做了一半”
    lastSave = Date.now();
    const spent = { ...st.spent };
    const cur = qs[st.idx];
    spent[cur.id] = (spent[cur.id] || 0) + (Date.now() - st.lastSwitch) / 1000;
    store.set(DRAFT_KEY, {
      title, ids, mode, timeLimit, idx: st.idx, answers: st.answers, revealed: st.revealed, flags: st.flags, spent,
      elapsed: Math.round(elapsed()), savedAt: new Date().toLocaleString("sv").replace("T", " "),
    });
  }

  function account() {
    const q = qs[st.idx];
    const now = Date.now();
    st.spent[q.id] = (st.spent[q.id] || 0) + (now - st.lastSwitch) / 1000;
    st.lastSwitch = now;
  }

  function go(i) {
    if (i < 0 || i >= qs.length) return;
    account();
    st.idx = i;
    draw();
    saveDraft(true);
  }

  function choose(k) {
    const q = qs[st.idx];
    if (st.finished) return;
    if (instant && st.revealed[q.id]) return;
    st.answers[q.id] = k;
    if (instant) st.revealed[q.id] = true;
    draw();
    saveDraft(true);
    if (!instant && st.idx < qs.length - 1) setTimeout(() => go(st.idx + 1), 180);
  }

  function elapsed() { return (Date.now() - st.start) / 1000; }

  function sheet() {
    return `<div class="card sheet">
      <div class="card-head"><h3>答题卡</h3><span class="small muted num">${Object.keys(st.answers).length}/${qs.length}</span></div>
      <div class="sheet-grid">${qs.map((q, i) => {
        const a = st.answers[q.id];
        let cls = a == null ? "" : "filled";
        if ((instant && st.revealed[q.id]) || st.finished) {
          if (a != null) cls = a === q.answer ? "ok" : "no";
          else if (st.finished) cls = "no";
        }
        if (i === st.idx) cls += " cur";
        if (st.flags[q.id]) cls += " flag";
        return `<button data-go="${i}" class="${cls}" title="第 ${i + 1} 题 · ${esc(q.module)}">
          <span class="dot">${a != null ? LETTERS[a] : ""}</span>${i + 1}</button>`;
      }).join("")}</div>
      <div class="sheet-legend"><span>● 已答</span>${instant || st.finished ? "<span style='color:var(--good)'>● 对</span><span style='color:var(--bad)'>● 错</span>" : ""}<span style="color:var(--warn)">◯ 标记</span></div>
      ${st.finished ? "" : `<button class="btn ${mode === "exam" ? "primary" : ""}" style="width:100%;margin-top:12px" data-finish>${mode === "exam" ? "交卷" : "结束并保存"}</button>`}
      <p class="small muted" style="margin:8px 0 0">键盘：1–4 或 A–D 选择，← → 切换题目</p>
    </div>`;
  }

  function showCrop(q) {
    return q.id in st.crop ? st.crop[q.id] : needsCrop(q);
  }

  function materialBlock(mat) {
    if (!mat) return "";
    const img = mat.crop && mat.fid ? cropHTML(mat.crop, mat.fid) : "";
    const useImg = img && (mat.fig || !mat.text);
    const text = mat.text ? `<div class="prose" style="font-size:14.5px">${md(mat.text)}</div>` : "";
    return `<div class="material" style="${img ? "max-height:560px" : ""}"><h4>${esc(mat.title || "材料")}</h4>
      ${useImg ? `${img}${text ? `<details class="mt"><summary class="small ink2" style="cursor:pointer">材料文字</summary>${text}</details>` : ""}`
        : `${text}${img ? `<details class="mt"><summary class="small ink2" style="cursor:pointer">看原卷</summary>${img}</details>` : ""}`}
    </div>`;
  }

  function questionCard() {
    const q = qs[st.idx];
    const mat = q.material ? data.mat(q.material) : null;
    const a = st.answers[q.id];
    const show = (instant && st.revealed[q.id]) || st.finished;
    const hist = progress.done[q.id];
    const wrong = progress.wrong[q.id];
    const crop = showCrop(q);
    const paper = q.real ? data.source(q.source) : null;
    const opts = q.options || ["", "", "", ""];
    const compact = !q.options || (crop && opts.every((o) => o.length <= 12));
    return `<div class="card">
      ${materialBlock(mat)}
      <div class="q-meta">
        <span class="chip brand">${esc(q.module)}</span>${q.sub ? `<span class="chip">${esc(q.sub)}</span>` : ""}
        ${q.real ? `<span class="chip" title="${esc(paper ? paper.title : "")}">${esc(srcLabel(q))}${paper && paper.level ? " · " + esc(paper.level) : ""} · 第 ${q.num} 题</span>` : ""}
        ${q.custom ? `<span class="chip">导入</span>` : ""}
        ${hist ? `<span class="small muted">做过 ${hist.n} 次，对 ${hist.ok || 0} 次</span>` : `<span class="small muted">新题</span>`}
        ${wrong && !wrong.mastered ? `<span class="chip bad">错题本</span>` : ""}
        <span class="spacer"></span>
        ${q.real && q.crop ? `<button class="btn sm ghost view-toggle" data-crop>${crop ? "看文字" : "看原卷"}</button>` : ""}
        ${!st.finished && mode === "exam" ? `<button class="btn sm ghost" data-flag>${st.flags[q.id] ? "取消标记" : "标记"}</button>` : ""}
      </div>
      ${crop ? cropHTML(q.crop, q.fid) : `<div class="q-stem"><span class="num muted">${st.idx + 1}. </span>${esc(q.stem)}</div>`}
      <div class="${compact ? "opt-grid" : "options"}">${opts.map((o, k) => {
        let cls = "";
        if (show) {
          if (k === q.answer) cls = "right";
          else if (k === a) cls = "wrong";
        } else if (k === a) cls = "chosen";
        const label = compact ? "" : `<span>${esc(o)}</span>`;
        return `<button class="opt ${cls}" data-opt="${k}" ${show ? "disabled" : ""} title="${esc(o)}"><span class="L">${LETTERS[k]}</span>${label}</button>`;
      }).join("")}</div>
      ${show ? `<div class="explain">
        <div class="row"><span class="verdict ${a === q.answer ? "ok" : "no"}">${a == null ? "未作答" : a === q.answer ? "回答正确" : "回答错误"}</span>
          <span class="ink2">正确答案 <b>${LETTERS[q.answer]}</b>${a != null && a !== q.answer ? `，你选了 ${LETTERS[a]}` : ""}</span>
          <span class="spacer"></span>
          <button class="btn sm" data-fav>${st.favorites.has(q.id) ? "已收藏" : "收藏"}</button></div>
        <div class="explain-text">${q.explain ? esc(q.explain) : "这道题没有解析。"}</div>
        <details class="mt" ${st.notes[q.id] ? "open" : ""}><summary class="small ink2" style="cursor:pointer">我的笔记</summary>
          <textarea id="qnote" rows="2" class="mt" placeholder="写下这道题的要点或错因">${esc(st.notes[q.id] || "")}</textarea>
          <button class="btn sm mt" data-note>保存笔记</button></details>
        <div class="mt" id="ai-explain"></div>
      </div>` : ""}
      <div class="row mt">
        <button class="btn" data-prev ${st.idx === 0 ? "disabled" : ""}>上一题</button>
        <button class="btn ${show || mode === "exam" ? "primary" : ""}" data-next ${st.idx === qs.length - 1 ? "disabled" : ""}>下一题</button>
      </div>
    </div>`;
  }

  function draw() {
    const limit = timeLimit ? timeLimit - elapsed() : 0;
    el.innerHTML = `
      <div class="quiz-bar">
        <div><div class="eyebrow">${MODE_NAME[mode]}${st.finished ? " · 已结束" : ""}</div><h2>${esc(title)}</h2></div>
        <span class="spacer"></span>
        <span class="clock ${timeLimit && limit < 300 ? "low" : ""}" id="clock">${timeLimit ? fmtClock(limit) : fmtClock(elapsed())}</span>
        ${st.finished ? `<button class="btn" data-result>查看成绩</button>` : ""}
      </div>
      <div class="quiz">${questionCard()}${sheet()}</div>`;
    bind();
  }

  function bind() {
    el.querySelectorAll("[data-opt]").forEach((x) => (x.onclick = () => choose(+x.dataset.opt)));
    el.querySelectorAll("[data-go]").forEach((x) => (x.onclick = () => go(+x.dataset.go)));
    el.querySelector("[data-prev]").onclick = () => go(st.idx - 1);
    el.querySelector("[data-next]").onclick = () => go(st.idx + 1);
    const cropBtn = el.querySelector("[data-crop]");
    if (cropBtn) cropBtn.onclick = () => { const q = qs[st.idx]; st.crop[q.id] = !showCrop(q); draw(); };
    const flag = el.querySelector("[data-flag]");
    if (flag) flag.onclick = () => { const id = qs[st.idx].id; st.flags[id] = !st.flags[id]; draw(); saveDraft(true); };
    const fin = el.querySelector("[data-finish]");
    if (fin) fin.onclick = () => confirmFinish(fin);
    const res = el.querySelector("[data-result]");
    if (res) res.onclick = () => showResult();
    const fav = el.querySelector("[data-fav]");
    if (fav) fav.onclick = async () => {
      const id = qs[st.idx].id, on = !st.favorites.has(id);
      await apiPost("/api/favorite", { qid: id, on });
      on ? st.favorites.add(id) : st.favorites.delete(id);
      toast(on ? "已收藏，可在错题本的“收藏”里找到" : "已取消收藏");
      draw();
    };
    const note = el.querySelector("[data-note]");
    if (note) note.onclick = async () => {
      const id = qs[st.idx].id, text = el.querySelector("#qnote").value;
      await apiPost("/api/qnote", { qid: id, text });
      st.notes[id] = text;
      toast("笔记已保存");
    };
    const aiEl = el.querySelector("#ai-explain");
    if (aiEl) {
      const q = qs[st.idx];
      mountAIBox(aiEl, {
        label: "请 AI 讲讲这道题",
        kind: "explain",
        getBody: () => ({
          module: q.module, stem: q.stem, options: q.options, answer: q.answer, explain: q.explain,
          chosen: st.answers[q.id], material: q.material ? data.mat(q.material)?.text : "",
        }),
      });
    }
  }

  function confirmFinish(btn) {
    const left = qs.length - Object.keys(st.answers).length;
    if (btn.dataset.armed) return finish();
    btn.dataset.armed = "1";
    btn.textContent = left && mode === "exam" ? `还有 ${left} 题未答，确定交卷？` : "再点一次确认";
    btn.classList.add("primary");
    setTimeout(() => { if (btn.isConnected) { delete btn.dataset.armed; btn.textContent = mode === "exam" ? "交卷" : "结束并保存"; } }, 4000);
  }

  async function finish() {
    if (st.finished) return;
    account();
    st.finished = true;
    clearInterval(clock);
    dropQuizDraft();
    const duration = Math.round(elapsed());
    const items = qs
      .filter((q) => mode === "exam" || st.answers[q.id] != null)
      .map((q) => ({
        qid: q.id, module: q.module, chosen: st.answers[q.id] ?? -1,
        correct: st.answers[q.id] === q.answer, seconds: Math.round(st.spent[q.id] || 0),
      }));
    if (items.length) {
      try {
        await apiPost("/api/attempts", { mode, title, duration, items });
        refreshBadge();
      } catch (e) { toast("保存失败：" + e.message); }
    }
    showResult();
  }

  function showResult() {
    const answered = qs.filter((q) => st.answers[q.id] != null);
    const right = qs.filter((q) => st.answers[q.id] === q.answer);
    const total = mode === "exam" ? qs.length : answered.length;
    const rows = MODULES.map((m) => {
      const mq = qs.filter((q) => q.module === m && (mode === "exam" || st.answers[q.id] != null));
      if (!mq.length) return null;
      const ok = mq.filter((q) => st.answers[q.id] === q.answer).length;
      const sec = mq.reduce((a, q) => a + (st.spent[q.id] || 0), 0);
      return { m, n: mq.length, ok, sec };
    }).filter(Boolean);
    const wrongList = qs.filter((q) => st.answers[q.id] != null && st.answers[q.id] !== q.answer || (mode === "exam" && st.answers[q.id] == null));
    const pct = total ? Math.round((right.length / total) * 100) : 0;
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">${MODE_NAME[mode]}结果</div><h1>${esc(title)}</h1></div></div>
      <div class="grid cols-main">
        <div class="card">
          <div class="row" style="align-items:flex-end;gap:24px">
            <div><div class="score-big">${right.length}<small> / ${total} 题</small></div><div class="muted">正确率 ${pct}% · 用时 ${fmtClock(elapsed())}</div></div>
            <span class="spacer"></span>
            <span class="chip ${pct >= 80 ? "good" : pct >= 60 ? "warn" : "bad"}">${pct >= 80 ? "很好，保持住" : pct >= 60 ? "还不错，看看错题" : "别灰心，先吃透错题"}</span>
          </div>
          <div class="table-wrap mt"><table class="tbl"><thead><tr><th>模块</th><th class="n">题数</th><th class="n">答对</th><th class="n">正确率</th><th class="n">用时</th><th class="n">平均每题</th></tr></thead>
          <tbody>${rows.map((r) => `<tr><td>${esc(r.m)}</td><td class="n">${r.n}</td><td class="n">${r.ok}</td><td class="n">${Math.round((r.ok / r.n) * 100)}%</td><td class="n">${fmtClock(r.sec)}</td><td class="n">${Math.round(r.sec / r.n)} 秒</td></tr>`).join("")}</tbody></table></div>
          <p class="small muted">${wrongList.length ? `做错和未答的 ${wrongList.length} 道题已加入错题本，会在第 1、2、4、7、15、30 天提醒你复习。` : "全部答对！"}</p>
          <div class="row mt">
            <button class="btn primary" data-review>逐题查看解析</button>
            ${onAgain ? `<button class="btn" data-again>再来一组</button>` : ""}
            <a class="btn" href="#/wrong">去错题本</a>
          </div>
        </div>
        <div class="card">
          <h3 class="mb">错题一览</h3>
          ${wrongList.length ? wrongList.map((q) => `<div class="row" style="padding:6px 0;border-bottom:1px dashed var(--line)">
            <span class="chip">${MODULE_SHORT[q.module] || esc(q.module)}</span>
            <span class="small" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${q.real ? `<span class="muted">${esc(srcLabel(q))} 第 ${q.num} 题</span> ` : ""}${esc((q.stem || "").split("\n")[0])}</span>
            <button class="btn sm ghost" data-goq="${qs.indexOf(q)}">看解析</button></div>`).join("") : `<div class="empty">没有错题</div>`}
        </div>
      </div>`;
    el.querySelector("[data-review]").onclick = () => { st.idx = 0; draw(); };
    el.querySelectorAll("[data-goq]").forEach((x) => (x.onclick = () => { st.idx = +x.dataset.goq; draw(); }));
    const again = el.querySelector("[data-again]");
    if (again) again.onclick = onAgain;
  }

  clock = setInterval(() => {
    if (!st.finished && Date.now() - lastSave > 15000) saveDraft(true);
    const c = document.getElementById("clock");
    if (!c || st.finished) return;
    if (timeLimit) {
      const left = timeLimit - elapsed();
      c.textContent = fmtClock(left);
      c.classList.toggle("low", left < 300);
      if (left <= 0) { toast("时间到，已自动交卷"); finish(); }
    } else c.textContent = fmtClock(elapsed());
  }, 1000);

  keyHandler = (e) => {
    if (!el.isConnected || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) return;
    const k = e.key.toUpperCase();
    if (["1", "2", "3", "4"].includes(k)) choose(+k - 1);
    else if ("ABCD".includes(k) && k.length === 1) choose("ABCD".indexOf(k));
    else if (e.key === "ArrowRight") go(st.idx + 1);
    else if (e.key === "ArrowLeft") go(st.idx - 1);
  };
  document.addEventListener("keydown", keyHandler);

  // 继续上次的题：限时的如果时间已经用完，直接交卷
  if (resume && timeLimit && timeLimit - elapsed() <= 0) {
    toast("时间已用完，已自动交卷");
    finish();
  } else {
    draw();
  }
  const onUnload = () => { saveDraft(true); store.flushNow(true); };
  window.addEventListener("beforeunload", onUnload);
  return () => {
    saveDraft(true);
    clearInterval(clock);
    document.removeEventListener("keydown", keyHandler);
    window.removeEventListener("beforeunload", onUnload);
  };
}

// 资料分析等带材料的题，抽题时保持同一材料的题挨在一起
export function groupByMaterial(questions) {
  const seen = new Set(), out = [];
  for (const q of questions) {
    if (seen.has(q.id)) continue;
    if (q.material) {
      for (const x of questions) if (x.material === q.material && !seen.has(x.id)) { seen.add(x.id); out.push(x); }
    } else { seen.add(q.id); out.push(q); }
  }
  return out;
}
