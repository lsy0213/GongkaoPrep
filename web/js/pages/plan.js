import { apiGet, apiPost, esc, todayISO, toast } from "../lib.js";

function calendar(checkins, year, month) {
  const first = new Date(year, month, 1);
  const days = new Date(year, month + 1, 0).getDate();
  const offset = (first.getDay() + 6) % 7; // 周一开头
  const set = new Set(checkins);
  const today = todayISO();
  let cells = "一二三四五六日".split("").map((w) => `<div class="h">${w}</div>`).join("");
  for (let i = 0; i < offset; i++) cells += "<div></div>";
  for (let dnum = 1; dnum <= days; dnum++) {
    const iso = todayISO(new Date(year, month, dnum));
    cells += `<div class="c ${set.has(iso) ? "on" : ""} ${iso === today ? "today" : ""}">${dnum}</div>`;
  }
  return `<div class="calendar">${cells}</div>`;
}

export async function render(el) {
  const [p, st, settings] = await Promise.all([apiGet("/api/plan"), apiGet("/api/stats"), apiGet("/api/settings")]);
  const cur = p.current;
  const total = p.phases.reduce((a, x) => a + x.days, 0);
  const now = new Date();
  const monthCount = st.checkins.filter((d) => d.startsWith(todayISO().slice(0, 7))).length;

  el.innerHTML = `
  <div class="page-head">
    <div><div class="eyebrow">复习计划</div><h1>${esc(cur.exam)} · ${esc(cur.name)}</h1>
      <p>${esc(cur.goal)}</p></div>
  </div>

  <div class="card">
    <div class="card-head"><h2>备考路线</h2><span class="small muted">按考试日期自动划分，共 ${total} 天</span></div>
    <div class="table-wrap"><div class="timeline" style="min-width:640px">
      ${p.phases.map((x) => `<div class="seg-p ${x.status}" style="flex:${Math.max(x.days, 6)}" title="${esc(x.goal)}">
        <b>${esc(x.name)}</b><span>${esc(x.start.slice(5))}—${esc(x.end.slice(5))}</span></div>`).join("")}
    </div></div>
    <div class="grid cols-2 mt">
      <div>
        <h3 class="mb" style="margin-bottom:6px">当前阶段要点</h3>
        <ul class="ink2" style="margin:0;padding-left:1.2em">${cur.focus.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
        <p class="small muted">第 ${cur.day_index} 天 / 共 ${cur.days} 天，还剩 ${cur.days_left} 天</p>
      </div>
      <div>
        <h3 style="margin-bottom:6px">每周节奏</h3>
        <p class="small ink2" style="margin:0">周一言语 · 周二数量 · 周三判断 · 周四资料 · 周五政治和常识 · 周六申论 · 周日复盘。<br>
        每天另有速算、闪卡、阅读和错题复习。任务量按“每天学习时长”自动调整。</p>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-head"><h2>未来 7 天</h2></div>
    <div class="week">
      ${p.week.map((w, i) => `<div class="day ${i === 0 ? "today" : ""}">
        <h4>${i === 0 ? "今天" : "周" + w.weekday} <span class="muted num" style="font-weight:400">${w.date.slice(5)}</span></h4>
        <span class="chip brand">${esc(w.focus)}</span>
        <ul>${w.tasks.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>`).join("")}
    </div>
  </div>

  <div class="grid cols-2 mt">
    <div class="card">
      <div class="card-head"><h2>关键时间点</h2><span class="small muted">预估，以官方公告为准</span></div>
      <ul class="milestones">
        ${p.milestones.map((m) => `<li class="${m.days_left < 0 ? "past" : ""} ${m.exam_day ? "exam" : ""}">
          <span class="d">${esc(m.date)}</span>
          <span><span class="t">${esc(m.title)}</span><br><span class="small muted">${esc(m.note)}</span></span>
          <span class="left">${m.days_left < 0 ? "已过" : m.days_left === 0 ? "今天" : m.days_left + " 天"}</span></li>`).join("")}
      </ul>
    </div>
    <div class="card">
      <div class="card-head"><h2>${now.getMonth() + 1} 月打卡</h2><span class="small muted">本月 ${monthCount} 天</span></div>
      ${calendar(st.checkins, now.getFullYear(), now.getMonth())}
      <hr class="sep">
      <h3 style="margin-bottom:10px">调整计划</h3>
      <form id="plan-form" class="grid cols-2">
        <label class="field">国考笔试日期<input type="date" id="gk" value="${esc(settings.guokao_date)}"></label>
        <label class="field">省考笔试日期<input type="date" id="sk" value="${esc(settings.shengkao_date)}"></label>
        <label class="field">开始备考日期<input type="date" id="sd" value="${esc(settings.start_date)}"></label>
        <label class="field">每天学习时长（小时）<input type="number" id="hrs" min="1" max="12" step="0.5" value="${esc(settings.daily_hours)}"></label>
        <div class="row"><button class="btn primary" type="submit">保存并重新安排</button></div>
      </form>
    </div>
  </div>`;

  el.querySelector("#plan-form").onsubmit = async (e) => {
    e.preventDefault();
    const gk = el.querySelector("#gk").value, sk = el.querySelector("#sk").value;
    if (gk && sk && sk <= gk) { toast("省考日期应在国考之后"); return; }
    await apiPost("/api/settings", {
      guokao_date: gk, shengkao_date: sk, start_date: el.querySelector("#sd").value,
      daily_hours: el.querySelector("#hrs").value,
    });
    toast("计划已更新，今日未完成的任务已重新生成");
    render(el);
  };
}
