import { accuracyBars, apiGet, apiPost, barChart, content, esc, fmtMinutes, MODULES, toast } from "../lib.js";

function ring(done, total) {
  const r = 50, c = 2 * Math.PI * r, p = total ? done / total : 0;
  return `<div class="ring"><svg viewBox="0 0 118 118" width="118" height="118">
    <circle class="track" cx="59" cy="59" r="${r}" stroke-width="6"/>
    <circle class="val" cx="59" cy="59" r="${r}" stroke-width="6" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - p)}"/></svg>
    <div class="ring-label"><div><b>${done}</b><span>/ ${total} 项任务</span></div></div></div>`;
}

const MODULE_ICON_ORDER = MODULES;

// 白瓷星轨主题的首页顶部（珍藏手稿里 .hero-3d 是隐藏的）：悬浮的黏土字星轨、一行连续打卡天数和今日任务进度、透明的天使
function hero3d(d, done, total) {
  const pct = total ? done / total : 0;
  const ph = d.phase;
  return `<div class="hero-3d">
    <div class="h3d-art" aria-hidden="true"></div>
    <div class="h3d-day">
      <span class="h3d-streak" title="${d.streak ? `已经连续打卡 ${d.streak} 天` : "今天打卡，开始新的连续天数"}">${d.streak ? `Day <b>${d.streak}</b>` : "New <b>Day</b>"}<span class="h3d-heart">♥</span></span>
      <span class="h3d-goal" title="今日任务完成 ${done} / ${total}"><svg class="h3d-ring" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8"/><circle class="fg" cx="10" cy="10" r="8" pathLength="100" stroke-dasharray="${Math.round(pct * 100)} 100"/></svg><b>${done}</b> / ${total} 项任务</span>
      <a class="h3d-phase" href="#/plan">${esc(ph.exam)} · ${esc(ph.name)} · 第 ${ph.day_index} / ${ph.days} 天</a>
    </div>
    <img class="h3d-figure" src="/img/skin/private/porcelain-angel.webp" alt="" aria-hidden="true" decoding="async" onerror="this.remove()">
  </div>`;
}

// 今日复习：错题、闪卡（FSRS 到期的）、还能学的新卡，一张卡片列全
function reviewCard(r) {
  if (!r) return "";
  const nothing = !r.wrong && !r.cards;
  return `<div class="card">
    <div class="card-head"><h3>今日复习</h3><span class="small muted">${nothing ? "到期的都复习完了" : `约 ${Math.max(1, r.minutes)} 分钟`}</span></div>
    <div class="review-rows">
      <a class="review-row ${r.wrong ? "due" : ""}" href="#/wrong"><span>错题重做</span><b class="num">${r.wrong}</b><small>题到期</small></a>
      <a class="review-row ${r.cards ? "due" : ""}" href="#/cards"><span>闪卡复习</span><b class="num">${r.cards}</b><small>张到期${r.cards_reviewed ? ` · 已复习 ${r.cards_reviewed}` : ""}</small></a>
      <a class="review-row" href="#/cards"><span>新卡</span><b class="num">${r.new_left}</b><small>张可学${r.new_today ? ` · 今天已学 ${r.new_today}` : ""}</small></a>
    </div>
    <p class="small muted" style="margin:8px 0 0">先复习到期的，再学新的；间隔由 FSRS 记忆模型按你的打分安排。</p>
  </div>`;
}

// 概览：最近的一场考试倒计时放大，另外两个小的；下面一行今天的三个数字（待复习的错题、闪卡在「今日复习」里）
function overview(d, exams, phase) {
  const next = exams.find((m) => m.days_left >= 0) || exams[exams.length - 1];
  const rest = exams.filter((m) => m !== next);
  const md = (iso) => { const [, m, dd] = iso.split("-"); return `${+m} 月 ${+dd} 日`; };
  const side = [
    ...rest.map((m) => [m.days_left >= 0 ? `距${m.title}` : `${m.title}已过去`, Math.abs(m.days_left), `${m.date} · 预估，可在设置中修改`]),
    [`${phase.name} 剩余`, phase.days_left, `${phase.start} 至 ${phase.end}`],
  ];
  const acc = d.questions_today ? ` · 正确率 ${Math.round((d.correct_today / d.questions_today) * 100)}%` : "";
  return `<div class="card overview mb">
    <div class="ov-top">
      ${next ? `<div class="ov-main ${next.days_left < 0 ? "passed" : ""}" title="${esc(next.date)} · 预估，可在设置中修改">
        <span class="ov-label">${next.days_left >= 0 ? "距" : ""}${esc(next.title)}${next.days_left < 0 ? "已过去" : ""}${next.days_left >= 0 && next.days_left <= 30 ? `<span class="stamp">冲刺</span>` : ""}</span>
        <span class="ov-days"><b class="num">${Math.abs(next.days_left)}</b><small>天</small></span>
        <span class="ov-date">${md(next.date)} · 预估</span></div>` : ""}
      <div class="ov-side">${side.map(([k, v, t]) => `<div title="${esc(t)}"><span>${esc(k)}</span><b class="num">${v}</b><small>天</small></div>`).join("")}</div>
    </div>
    <div class="ov-stats">
      <div><b class="num">${d.streak}</b><small>天</small><span>连续打卡</span></div>
      <div><b class="num">${d.minutes_today}</b><small>分钟</small><span>今日学习</span></div>
      <div><b class="num">${d.questions_today}</b><small>题</small><span>今日做题${acc}</span></div>
    </div>
  </div>`;
}

// 今日任务：圆形勾选 + 标题，右边一个小箭头去完成；加任务和打卡都收成一行
export function tasksCard(d, doneCount, pct, hint = "背 20 个成语") {
  const total = d.tasks.length;
  return `<div class="card tasks-card">
      <div class="card-head">
        <h2>今日任务</h2>
        <span class="tk-count"><svg class="h3d-ring" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8"/><circle class="fg" cx="10" cy="10" r="8" pathLength="100" stroke-dasharray="${pct} 100"/></svg><b class="num">${doneCount}</b> / ${total}</span>
      </div>
      <ul class="tasks" id="tasks">
        ${d.tasks.map((t) => `
          <li class="task ${t.done ? "done" : ""}">
            <label class="tk-check"><input type="checkbox" data-id="${t.id}" ${t.done ? "checked" : ""} aria-label="完成：${esc(t.title)}"><span aria-hidden="true"></span></label>
            <div class="t"><div class="t-title">${esc(t.title)}</div>
              <div class="t-meta">${esc(t.module)}${t.minutes ? ` · 约 ${t.minutes} 分钟` : ""}${t.source === "user" ? " · 自己添加" : ""}</div></div>
            ${t.link ? `<a class="tk-go" href="${esc(t.link)}" title="去完成" aria-label="去完成：${esc(t.title)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></a>` : `<button class="tk-del" data-del="${t.id}" title="删除" aria-label="删除：${esc(t.title)}">×</button>`}
          </li>`).join("")}
      </ul>
      <form class="tk-add" id="add-task">
        <span class="tk-plus" aria-hidden="true">+</span>
        <input type="text" id="new-task" placeholder="添加自己的任务，例如：${esc(hint)}" aria-label="添加任务">
        <button class="btn sm" type="submit">添加</button>
      </form>
      <div id="checkin" class="tk-checkin">
        ${d.checked_in
          ? `<span class="chip good">今日已打卡</span><span class="small muted">累计 ${d.checkin_total} 天 · 连续 ${d.streak} 天</span>`
          : `<input type="text" id="checkin-note" placeholder="今天学了什么？（可不填）" aria-label="打卡备注">
             <button class="btn primary" id="checkin-btn" title="${pct < 100 ? `还有 ${total - doneCount} 项任务未完成，也可以先打卡` : "今日任务全部完成"}">打卡</button>`}
      </div>
    </div>`;
}

export async function render(el) {
  const [d, lib] = await Promise.all([apiGet("/api/dashboard"), content("materials.json")]);
  const quotes = lib.themes.flatMap((t) => t.quotes);
  const dayNo = Math.floor(new Date(d.today + "T00:00:00").getTime() / 86400000);
  const quote = quotes[dayNo % quotes.length];
  const s = d.settings;
  const hour = new Date().getHours();
  const greet = hour < 6 ? "夜深了" : hour < 11 ? "早上好" : hour < 14 ? "中午好" : hour < 18 ? "下午好" : "晚上好";
  const name = s.nickname ? `，${esc(s.nickname)}` : "";
  const phase = d.phase;
  const doneCount = d.tasks.filter((t) => t.done).length;
  const pct = d.tasks.length ? Math.round((doneCount / d.tasks.length) * 100) : 0;
  const exams = d.milestones.filter((m) => m.exam_day);
  const modRows = MODULE_ICON_ORDER.map((m) => {
    const r = d.modules.find((x) => x.module === m);
    return { name: m, total: r ? r.total : 0, acc: r ? r.accuracy : 0 };
  });
  const weekDays = d.week.map((w, i) => ({ l: i === 6 ? "今天" : "日一二三四五六"[new Date(w.day + "T00:00:00").getDay()], v: w.minutes }));

  el.innerHTML = `
  <div class="hero">
    ${ring(doneCount, d.tasks.length)}
    <div class="hero-copy">
      <span class="hero-kicker">上岸备考 · 今日手札 · ${esc(d.today)}</span>
      <h1>${greet}${name}</h1>
      <p>${d.streak ? `已经连续打卡 <b>${d.streak}</b> 天，` : ""}今天还有 <b>${d.tasks.length - doneCount}</b> 项任务。${esc(phase.goal)}</p>
      <span class="phase">${esc(phase.exam)} · ${esc(phase.name)} · 第 ${phase.day_index} / ${phase.days} 天</span>
    </div>
    <div class="hero-art" aria-hidden="true"></div>
    ${hero3d(d, doneCount, d.tasks.length)}
  </div>

  ${overview(d, exams, phase)}

  <div class="grid cols-main">
    ${tasksCard(d, doneCount, pct)}

    <div class="stack" style="gap:16px">
      ${reviewCard(d.review)}
      <div class="card">
        <div class="card-head"><h3>今日一句</h3><a class="small" href="#/notes">素材库</a></div>
        <p class="daily-quote">${esc(quote.text)}</p>
        <div class="small muted mt">—— ${esc(quote.source)}　${esc(quote.use)}</div>
      </div>
      <div class="card">
        <div class="card-head"><h3>近 7 天学习时长</h3><span class="small muted">分钟</span></div>
        ${barChart(weekDays, { today: 6 })}
        <div class="small muted mt">累计学习 ${fmtMinutes(d.minutes_total)} · 累计做题 ${d.questions_total} 道${d.questions_total ? `，正确率 ${d.accuracy_total}%` : ""}</div>
      </div>
      <div class="card">
        <div class="card-head"><h3>各模块正确率</h3><a class="small" href="#/stats">详细统计</a></div>
        ${accuracyBars(modRows)}
      </div>
      <div class="card">
        <div class="card-head"><h3>本阶段重点</h3><a class="small" href="#/plan">完整计划</a></div>
        <ul style="margin:0;padding-left:1.2em" class="ink2">${phase.focus.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
      </div>
    </div>
  </div>`;

  bindTasks(el, () => render(el));
}

// 今日任务卡片的勾选、删除、添加和打卡（软考首页也用）
export function bindTasks(el, again) {
  el.querySelectorAll("#tasks input[type=checkbox]").forEach((cb) => {
    cb.onchange = async () => {
      try {
        await apiPost("/api/tasks/toggle", { id: +cb.dataset.id });
        again();
      } catch (e) { toast(e.message); }
    };
  });
  el.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = async () => {
      await apiPost("/api/tasks/delete", { id: +b.dataset.del });
      again();
    };
  });
  el.querySelector("#add-task").onsubmit = async (e) => {
    e.preventDefault();
    const title = el.querySelector("#new-task").value.trim();
    if (!title) return;
    await apiPost("/api/tasks/add", { title });
    again();
  };
  const btn = el.querySelector("#checkin-btn");
  if (btn) btn.onclick = async () => {
    const r = await apiPost("/api/checkin", { note: el.querySelector("#checkin-note").value });
    toast(`打卡成功，已连续 ${r.streak} 天`);
    again();
  };
}
