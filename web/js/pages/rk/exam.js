// 软考 · 机考模拟：照真实机考的流程——综合知识（75 题）和案例分析连考，共用 240 分钟；交综合知识后进入案例，
// 试题一必答、其余 4 题选 2。界面仿机考系统：顶栏计时、左侧答题卡、标记、上一题 / 下一题。交卷后出综合知识得分和案例参考答案。
import { apiGet, apiPost, bankMeta, cropHTML, esc, fmtClock, getQuestions, LETTERS, md, MODULES, pickQuestions, store, toast } from "../../lib.js";

const TOTAL_MIN = 240;
const CN = "一二三四五六七八九";

async function composeZh(paperId) {
  if (paperId) return pickQuestions({ source: paperId, module: "全部", order: "all", count: 0 });
  // 按真题里各模块比例组 75 题
  const sum = await apiPost("/api/bank/summary", { src: "真题" });
  const en = MODULES.find((m) => /英语/.test(m));
  const rest = MODULES.filter((m) => m !== en);
  const base = rest.reduce((a, m) => a + (sum.modules[m]?.total || 0), 0) || 1;
  const plan = rest.map((m) => [m, Math.round(((sum.modules[m]?.total || 0) / base) * 70)]);
  let diff = 70 - plan.reduce((a, [, n]) => a + n, 0);
  plan.sort((a, b) => b[1] - a[1]);
  plan[0][1] += diff;
  if (en) plan.push([en, 5]);
  const ids = [];
  for (const [m, n] of plan) if (n > 0) ids.push(...await pickQuestions({ module: m, count: n, order: "new", src: "all" }));
  return ids;
}

function pickCases(all, year) {
  const same = all.filter((c) => c.kind === "paper" && c.year === year);
  if (year && same.length >= 5) return same.sort((a, b) => a.no - b.no).slice(0, 5);
  const shuffle = (a) => a.map((x) => [Math.random(), x]).sort((p, q) => p[0] - q[0]).map((p) => p[1]);
  const first = shuffle(all.filter((c) => c.tags.includes("质量属性与评估") && c.answered))[0] || shuffle(all)[0];
  const others = [];
  const seen = new Set([first.id]);
  for (const tag of ["数据库与缓存", "系统建模", "嵌入式", "Web 与云原生", "架构设计"]) {
    const c = shuffle(all.filter((x) => x.tags.includes(tag) && !seen.has(x.id) && x.answered))[0];
    if (c && others.length < 4) { others.push(c); seen.add(c.id); }
  }
  return [first, ...others];
}

export async function render(el) {
  const [meta, caseList] = await Promise.all([bankMeta(), apiGet("/api/rk/cases")]);
  const papers = meta.sources.filter((s) => s.kind === "paper" && s.count >= 60).sort((a, b) => b.year - a.year);
  const saved = store.get("rk-exam", {});
  let tick = null;
  const st = { stage: "setup", paper: saved.paper ?? (papers[0]?.id || ""), start: 0, zh: null, idx: 0, ans: {}, flags: {}, zhScore: null,
    cases: [], chosen: new Set(), caseAns: {}, caseTab: 0, zhUsed: 0 };

  const left = () => TOTAL_MIN * 60 - Math.round((Date.now() - st.start) / 1000);
  function header(title, extra = "") {
    return `<div class="mx-top"><b>全国计算机技术与软件专业技术资格考试 · 系统架构设计师（模拟）</b><span>${esc(title)}</span>${extra}
      <span class="mx-clock" id="mx-clock">${fmtClock(Math.max(0, left()))}</span></div>`;
  }

  function setup() {
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">综合知识 + 案例分析</div><h1>机考模拟</h1>
        <p>和真实机考一样：综合知识 75 题和案例分析连考，共 ${TOTAL_MIN} 分钟。综合知识交卷后进入案例，第 1 题必答，其余 4 题选 2。论文是下午另一场 120 分钟，在“论文写作”里限时练。</p></div></div>
      <div class="card">
        <h3>综合知识用哪套题</h3>
        <select id="paper"><option value="">按真题比例随机组卷（优先没做过的题）</option>
          ${papers.map((p) => `<option value="${esc(p.id)}" ${p.id === st.paper ? "selected" : ""}>${esc(p.title)}</option>`).join("")}</select>
        <p class="small muted">选了某一年的整卷时，案例也用同一年的 5 道题（有的话）；随机组卷时案例按题型各抽一道。</p>
        <ul class="small ink2"><li>考试中可以标记、来回改答案；交了综合知识就不能再回去改。</li>
          <li>案例作答写在答题框里，考场上要点式作答更容易拿分。</li><li>中途关掉页面不会保存这次模拟。</li></ul>
        <div class="row mt"><button class="btn primary lg" id="go">开始考试</button></div>
      </div>`;
    el.querySelector("#paper").onchange = (e) => { st.paper = e.target.value; store.set("rk-exam", { paper: st.paper }); };
    el.querySelector("#go").onclick = async () => {
      const ids = await composeZh(st.paper);
      if (!ids.length) { toast("题库里还没有题，先去资料库整理资料"); return; }
      st.zh = await getQuestions(ids);
      const year = st.paper ? meta.sourceById[st.paper]?.year : 0;
      st.cases = pickCases(caseList.sets, year);
      st.start = Date.now();
      st.stage = "zh";
      draw();
      tick = setInterval(onTick, 1000);
    };
  }

  function onTick() {
    const c = el.querySelector("#mx-clock");
    if (!c) { clearInterval(tick); return; }
    const l = left();
    c.textContent = fmtClock(Math.max(0, l));
    c.classList.toggle("warn", l < 900);
    if (l <= 0) {
      clearInterval(tick);
      toast("时间到，自动交卷");
      if (st.stage === "zh") submitZh().then(() => finish());
      else if (st.stage === "pick" || st.stage === "case") finish();
    }
  }

  function zhView() {
    const qs = st.zh.questions;
    const q = qs[st.idx];
    const mat = q.material ? st.zh.mat(q.material) : null;
    const answered = Object.keys(st.ans).length;
    el.innerHTML = `<div class="mx">${header("科目一：综合知识", `<span>已答 ${answered} / ${qs.length}</span>`)}
      <div class="mx-body">
        <div class="mx-card"><div class="small">答题卡　<span class="mx-k d"></span>已答　<span class="mx-k f"></span>标记</div>
          <div class="mx-grid">${qs.map((x, i) => `<button data-go="${i}" class="${st.ans[x.id] != null ? "d" : ""} ${st.flags[x.id] ? "f" : ""} ${i === st.idx ? "c" : ""}">${i + 1}</button>`).join("")}</div></div>
        <div class="mx-main">
          <div class="mx-q">
            ${mat ? `<div class="mx-mat">${md(mat.text)}</div>` : ""}
            <div class="small muted">第 ${st.idx + 1} 题 · 单选 · 1 分${q.fig && q.crop?.length ? " · 本题有图，见下方原卷" : ""}</div>
            <div class="mx-stem">${esc(q.stem)}</div>
            ${q.fig && q.crop?.length && q.fid ? cropHTML(q.crop, q.fid) : ""}
            ${(q.options || ["", "", "", ""]).map((o, k) => `<button class="mx-opt ${st.ans[q.id] === k ? "on" : ""}" data-k="${k}"><span>${LETTERS[k]}</span>${esc(o)}</button>`).join("")}
          </div>
          <div class="row mt"><button class="mx-btn" id="prev" ${st.idx ? "" : "disabled"}>上一题</button>
            <button class="mx-btn" id="flag">${st.flags[q.id] ? "取消标记" : "标记"}</button>
            <button class="mx-btn p" id="next" ${st.idx < qs.length - 1 ? "" : "disabled"}>下一题</button>
            <span class="spacer"></span><button class="mx-btn" id="hand">交综合知识，进入案例分析</button></div>
        </div></div></div>`;
    el.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => { st.idx = +b.dataset.go; draw(); }));
    el.querySelectorAll("[data-k]").forEach((b) => (b.onclick = () => { st.ans[q.id] = +b.dataset.k; draw(); }));
    el.querySelector("#prev").onclick = () => { st.idx--; draw(); };
    el.querySelector("#next").onclick = () => { st.idx++; draw(); };
    el.querySelector("#flag").onclick = () => { st.flags[q.id] = !st.flags[q.id]; draw(); };
    el.querySelector("#hand").onclick = async (e) => {
      const miss = qs.length - Object.keys(st.ans).length;
      if (!e.currentTarget.dataset.armed) { e.currentTarget.dataset.armed = "1"; e.currentTarget.textContent = miss ? `还有 ${miss} 题没答，确认交卷` : "确认交综合知识"; return; }
      await submitZh();
      st.stage = "pick";
      draw();
    };
  }

  async function submitZh() {
    const qs = st.zh.questions;
    st.zhUsed = Math.round((Date.now() - st.start) / 1000);
    const items = qs.filter((q) => q.answer != null).map((q) => ({ qid: q.id, module: q.module, chosen: st.ans[q.id] ?? null,
      correct: st.ans[q.id] === q.answer, seconds: Math.round(st.zhUsed / qs.length) }));
    const r = await apiPost("/api/attempts", { mode: "exam", title: "机考模拟 · 综合知识", items, duration: st.zhUsed });
    st.zhScore = { right: r.correct, total: r.total, score: r.score };
  }

  function pickView() {
    el.innerHTML = `<div class="mx">${header("科目二：案例分析 · 选题")}
      <div class="mx-body one"><div class="mx-main">
        <p>试题一必答；试题二至试题${CN[st.cases.length - 1]}中选 2 道。选好后开始作答（剩余时间都可以用在案例上）。</p>
        ${st.cases.map((c, i) => `<label class="mx-pick ${i === 0 || st.chosen.has(c.id) ? "on" : ""}">
          <input type="checkbox" data-c="${esc(c.id)}" ${i === 0 ? "checked disabled" : st.chosen.has(c.id) ? "checked" : ""}>
          <b>试题${CN[i]}${i === 0 ? "（必答）" : ""}</b><span>${esc(c.title || c.tags.join("、"))}</span><small>${esc(c.source)}</small></label>`).join("")}
        <div class="row mt"><button class="mx-btn p" id="start-case" ${st.chosen.size === 2 ? "" : "disabled"}>开始作答（已选 ${st.chosen.size + 1} / 3）</button></div>
      </div></div></div>`;
    el.querySelectorAll("[data-c]").forEach((b) => (b.onchange = () => {
      if (b.checked) { if (st.chosen.size >= 2) { b.checked = false; toast("只能选 2 道"); return; } st.chosen.add(b.dataset.c); }
      else st.chosen.delete(b.dataset.c);
      draw();
    }));
    el.querySelector("#start-case").onclick = async () => {
      const ids = [st.cases[0].id, ...st.cases.filter((c) => st.chosen.has(c.id)).map((c) => c.id)];
      st.full = await Promise.all(ids.map((id) => apiGet("/api/rk/case?id=" + encodeURIComponent(id))));
      st.stage = "case";
      draw();
    };
  }

  function caseView() {
    const c = st.full[st.caseTab];
    el.innerHTML = `<div class="mx">${header("科目二：案例分析")}
      <div class="mx-tabs">${st.full.map((x, i) => `<button data-t="${i}" class="${i === st.caseTab ? "on" : ""}">试题${CN[st.cases.findIndex((y) => y.id === x.id)]}</button>`).join("")}
        <span class="spacer"></span><button class="mx-btn" id="hand">交卷</button></div>
      <div class="mx-body two">
        <div class="mx-main mx-scroll">${md(c.material || "")}</div>
        <div class="mx-main mx-scroll">${c.questions.map((q) => `<div class="mb"><b>【问题 ${q.n}】</b>${q.score ? `（${q.score} 分）` : ""}<div class="small">${md(q.text)}</div>
          <textarea data-q="${q.n}" rows="7">${esc(st.caseAns[c.id]?.[q.n] || "")}</textarea></div>`).join("")}</div>
      </div></div>`;
    el.querySelectorAll("[data-t]").forEach((b) => (b.onclick = () => { st.caseTab = +b.dataset.t; draw(); }));
    el.querySelectorAll("textarea[data-q]").forEach((t) => (t.oninput = () => { (st.caseAns[c.id] ||= {})[t.dataset.q] = t.value; }));
    el.querySelector("#hand").onclick = (e) => {
      if (!e.currentTarget.dataset.armed) { e.currentTarget.dataset.armed = "1"; e.currentTarget.textContent = "确认交卷"; return; }
      finish();
    };
  }

  async function finish() {
    clearInterval(tick);
    const used = Math.round((Date.now() - st.start) / 1000);
    if (st.full) {
      for (const c of st.full) for (const q of c.questions) {
        const a = st.caseAns[c.id]?.[q.n] || "";
        if (a.trim()) await apiPost("/api/essays", { set_id: "case:" + c.id, q_index: q.n, answer: a, words: a.length, seconds: 0, module: "案例分析", source: "机考模拟" });
      }
      const caseSecs = used - st.zhUsed;
      if (caseSecs > 60) apiPost("/api/study_log", { module: "案例分析", minutes: Math.round(caseSecs / 60), source: "机考模拟" }).catch(() => {});
    }
    st.stage = "done";
    const z = st.zhScore || { right: 0, total: 0, score: 0 };
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">机考模拟</div><h1>交卷了</h1><p>用时 ${fmtClock(used)}（综合知识 ${fmtClock(st.zhUsed)}）。</p></div>
        <a class="btn" href="#/exam">再来一场</a></div>
      <div class="rk-subjects mb">
        <div class="card rk-subj"><div class="card-head"><h3>综合知识</h3><span class="chip ${z.score >= 45 ? "good" : "bad"}">${z.score >= 45 ? "过线" : `差 ${Math.ceil(45 - z.score)} 分`}</span></div>
          <div class="rk-score"><b class="num">${z.score}</b><small>/ 75 · 对 ${z.right} / ${z.total} 题</small></div>
          <div class="pass-bar ${z.score >= 45 ? "good" : "bad"}"><i style="width:${Math.round((z.score / 75) * 100)}%"></i><u style="left:60%"></u></div>
          <p class="small"><a href="#/wrong">错题已进错题本</a> · <a href="#/mock">看估分走势</a></p></div>
        <div class="card rk-subj" style="grid-column: span 2"><div class="card-head"><h3>案例分析</h3><span class="small muted">对照参考答案自评，或到案例页请 AI 批改</span></div>
          ${(st.full || []).map((c) => `<div class="mt"><b>${esc(c.source)} · 试题${CN[(c.no || 1) - 1]}</b> <a class="btn sm" href="#/case/${encodeURIComponent(c.id)}">看参考答案、AI 批改</a></div>`).join("") || `<p class="small muted">没有进入案例作答。</p>`}
        </div>
      </div>`;
  }

  function draw() {
    if (st.stage === "setup") return setup();
    if (st.stage === "zh") return zhView();
    if (st.stage === "pick") return pickView();
    if (st.stage === "case") return caseView();
  }
  draw();
  return () => clearInterval(tick);
}
