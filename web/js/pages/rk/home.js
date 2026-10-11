// 软考首页：考试倒计时、三科离 45 分及格线还差多少、今日学习和复习
import { EXAM, apiGet, esc } from "../../lib.js";
import { bindTasks, tasksCard } from "../home.js";

function ring(minutes, goal) {
  const r = 50, c = 2 * Math.PI * r, p = goal ? Math.min(1, minutes / goal) : 0;
  return `<div class="ring"><svg viewBox="0 0 118 118" width="118" height="118">
    <circle class="track" cx="59" cy="59" r="${r}" stroke-width="6"/>
    <circle class="val" cx="59" cy="59" r="${r}" stroke-width="6" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - p)}"/></svg>
    <div class="ring-label"><div><b>${minutes}</b><span>/ ${goal} 分钟</span></div></div></div>`;
}

// 白瓷星轨的首页顶部：黏土字星轨 + 连续打卡 + 今日学习进度 + 考试倒计时
function hero3d(d, goal) {
  const pct = goal ? Math.min(1, d.minutes_today / goal) : 0;
  return `<div class="hero-3d">
    <div class="h3d-art" aria-hidden="true"></div>
    <div class="h3d-day">
      <span class="h3d-streak">${d.streak ? `Day <b>${d.streak}</b>` : "New <b>Day</b>"}<span class="h3d-heart">♥</span></span>
      <span class="h3d-goal" title="今日学习 ${d.minutes_today} / ${goal} 分钟"><svg class="h3d-ring" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8"/><circle class="fg" cx="10" cy="10" r="8" pathLength="100" stroke-dasharray="${Math.round(pct * 100)} 100"/></svg><b>${d.minutes_today}</b> / ${goal} 分钟</span>
      <a class="h3d-phase" href="#/settings">${esc(d.exam.family)} · ${esc(d.exam.name)}${d.days_left != null ? ` · 距考试 ${d.days_left} 天` : ""}</a>
    </div>
    <img class="h3d-figure" src="/img/skin/private/porcelain-angel.webp" alt="" aria-hidden="true" decoding="async" onerror="this.remove()">
  </div>`;
}

function overview(d) {
  const md = (iso) => { const [y, m, dd] = iso.split("-"); return `${y} 年 ${+m} 月 ${+dd} 日`; };
  const acc = d.questions_today ? ` · 正确率 ${Math.round((d.correct_today / d.questions_today) * 100)}%` : "";
  const sessions = d.exam.sessions.map((x) => `${x.name} ${x.minutes} 分钟`).join(" · ");
  return `<div class="card overview mb">
    <div class="ov-top">
      ${d.exam_date ? `<div class="ov-main ${d.days_left < 0 ? "passed" : ""}" title="可在设置里改成你报的那一次">
        <span class="ov-label">${d.days_left >= 0 ? "距" : ""}${esc(d.exam.family)}${esc(d.exam.name)}考试${d.days_left < 0 ? "已过去" : ""}${d.days_left >= 0 && d.days_left <= 30 ? `<span class="stamp">冲刺</span>` : ""}</span>
        <span class="ov-days"><b class="num">${Math.abs(d.days_left)}</b><small>天</small></span>
        <span class="ov-date">${md(d.exam_date)} · 预估，可在设置中修改</span></div>`
        : `<div class="ov-main"><span class="ov-label">还没有设置考试日期</span><a class="btn sm" href="#/settings">去设置</a></div>`}
      <div class="ov-side">
        <div title="从开始备考那天算起"><span>已备考</span><b class="num">${d.days_studied}</b><small>天</small></div>
        <div title="${esc(sessions)}"><span>三科及格线</span><b class="num">45</b><small>/ 75</small></div>
      </div>
    </div>
    <div class="ov-stats">
      <div><b class="num">${d.streak}</b><small>天</small><span>连续打卡</span></div>
      <div><b class="num">${d.minutes_today}</b><small>分钟</small><span>今日学习</span></div>
      <div><b class="num">${d.questions_today}</b><small>题</small><span>今日做题${acc}</span></div>
    </div>
  </div>`;
}

// 三科：各自的估分和 45 分及格线（金线）。还没练过的科目显示怎么开始
function subjects(d) {
  return `<div class="rk-subjects mb">${d.exam.subjects.map((s) => {
    const est = s.estimate;
    const pct = est != null ? Math.round((est / s.full) * 100) : 0;
    const passPct = Math.round((s.pass / s.full) * 100);
    const tone = est == null ? "" : est >= s.pass ? "good" : est >= s.pass - 6 ? "warn" : "bad";
    const chip = est == null ? `<span class="chip">还没有估分</span>`
      : est >= s.pass ? `<span class="chip good">已过线</span>` : `<span class="chip ${tone}">差 ${Math.ceil(s.pass - est)} 分</span>`;
    return `<div class="card rk-subj">
      <div class="card-head"><h3>${esc(s.name)}</h3>${chip}</div>
      <div class="rk-score"><b class="num">${est != null ? est : "—"}</b><small>/ ${s.full} 估分</small></div>
      <div class="pass-bar ${tone}" title="金线是 ${s.pass} 分及格线"><i style="width:${pct}%"></i><u style="left:${passPct}%"></u></div>
      <p class="small muted">${esc(s.desc || "")}</p>
    </div>`;
  }).join("")}</div>`;
}

function reviewCard(r) {
  const nothing = !r.wrong && !r.cards;
  return `<div class="card">
    <div class="card-head"><h3>今日复习</h3><span class="small muted">${nothing ? "到期的都复习完了" : `约 ${Math.max(1, r.minutes)} 分钟`}</span></div>
    <div class="review-rows">
      <a class="review-row ${r.wrong ? "due" : ""}" href="#/wrong"><span>错题重做</span><b class="num">${r.wrong}</b><small>题到期</small></a>
      <a class="review-row ${r.cards ? "due" : ""}" href="#/cards"><span>闪卡复习</span><b class="num">${r.cards}</b><small>张到期${r.cards_reviewed ? ` · 已复习 ${r.cards_reviewed}` : ""}</small></a>
      <a class="review-row" href="#/cards"><span>新卡</span><b class="num">${r.new_left}</b><small>张可学</small></a>
    </div>
  </div>`;
}

// 近期的报名、准考证等时间点：30 天内的提醒一下
function reminder(d) {
  const m = (d.milestones || []).find((x) => x.days_left >= 0 && x.days_left <= 30 && !x.exam_day);
  if (!m) return "";
  return `<div class="card rk-notice mb"><b>${m.days_left === 0 ? "今天" : `${m.days_left} 天后`}：${esc(m.title)}</b>
    <span class="small ink2">${esc(m.date)} 前后 · ${esc(m.note)}</span> <a class="small" href="#/cert">考试与证书 →</a></div>`;
}

export async function render(el) {
  const d = await apiGet("/api/rk/dashboard");
  const s = d.settings;
  const goal = Math.round((parseFloat(s.daily_hours) || 3) * 60);
  const hour = new Date().getHours();
  const greet = hour < 6 ? "夜深了" : hour < 11 ? "早上好" : hour < 14 ? "中午好" : hour < 18 ? "下午好" : "晚上好";

  const subjNames = d.exam.subjects.map((x) => x.name).join("、");
  const doneCount = d.tasks.filter((t) => t.done).length;
  const pct = d.tasks.length ? Math.round((doneCount / d.tasks.length) * 100) : 0;
  el.innerHTML = `
  <div class="hero">
    ${ring(d.minutes_today, goal)}
    <div class="hero-copy">
      <span class="hero-kicker">${esc(EXAM.cur.family || "")} · ${esc(EXAM.cur.level || "")} · ${esc(d.today)}</span>
      <h1>${greet}${s.nickname ? `，${esc(s.nickname)}` : ""}</h1>
      <p>${d.streak ? `已经连续打卡 <b>${d.streak}</b> 天，` : ""}${esc(subjNames)}三科都要过 45 分，同一次考完才算通过。</p>
      <span class="phase">${esc(d.exam.family)} · ${esc(d.exam.name)}</span>
    </div>
    <div class="hero-art" aria-hidden="true"></div>
    ${hero3d(d, goal)}
  </div>
  ${reminder(d)}
  ${overview(d)}
  ${subjects(d)}
  <div class="grid cols-main">
    ${tasksCard(d, doneCount, pct, "背 10 个英语专业词汇")}
    <div class="stack">
      ${reviewCard(d.review)}
      ${d.phase ? `<div class="card"><div class="card-head"><h3>${esc(d.phase.name)}</h3><a class="small" href="#/plan">复习计划 →</a></div>
        <p class="small ink2">${esc(d.phase.goal)}</p>
        <div class="small muted">第 ${d.phase.day_index} / ${d.phase.days} 天 · 还剩 ${d.phase.days_left} 天</div></div>` : ""}
    </div>
  </div>`;
  bindTasks(el, () => render(el));
}
