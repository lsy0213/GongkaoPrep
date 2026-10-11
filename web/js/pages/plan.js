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

// 公考的每周节奏和计划表单；其他考试由 /api/plan 带回 rhythm、form
const GK_RHYTHM = [["一", "言语"], ["二", "数量"], ["三", "判断"], ["四", "资料"], ["五", "政治 · 常识"], ["六", "申论"], ["日", "复盘"]];
const GK_FORM = [
  { key: "guokao_date", label: "国考笔试日期", type: "date" },
  { key: "shengkao_date", label: "省考笔试日期", type: "date" },
  { key: "start_date", label: "开始备考日期", type: "date" },
  { key: "daily_hours", label: "每天学习时长（小时）", type: "number" },
];

export async function render(el) {
  const [p, st, settings] = await Promise.all([apiGet("/api/plan"), apiGet("/api/stats"), apiGet("/api/settings")]);
  const cur = p.current;
  if (!cur) {
    el.innerHTML = `<div class="page-head"><div><div class="eyebrow">复习计划</div><h1>这门考试还没有复习计划</h1></div></div>`;
    return;
  }
  const rhythm = p.rhythm ? p.rhythm.map((x) => [x.day, x.label]) : GK_RHYTHM;
  const form = p.form || GK_FORM;
  const total = p.phases.reduce((a, x) => a + x.days, 0);
  const now = new Date();
  const monthCount = st.checkins.filter((d) => d.startsWith(todayISO().slice(0, 7))).length;

  el.innerHTML = `
  <div class="page-head">
    <div><div class="eyebrow">复习计划</div><h1>${esc(cur.exam)} · ${esc(cur.name)}</h1>
      <p>${esc(cur.goal)}</p></div>
  </div>

  <div class="card">
    <div class="card-head"><h2>备考路线</h2><span class="small muted">按考试日期自动划分 · 共 ${total} 天</span></div>
    <ol class="phase-list">
      ${p.phases.map((x) => {
        const isNow = x.status === "now";
        return `<li class="ph ${x.status}">
          <span class="ph-dot" aria-hidden="true"></span>
          <div class="ph-body">
            <div class="ph-row"><b>${esc(x.name)}</b>${isNow ? `<span class="ph-tag">进行中</span>` : ""}<span class="spacer"></span>
              <span class="ph-date num">${esc(x.start.slice(5).replace("-", "."))} – ${esc(x.end.slice(5).replace("-", "."))}</span></div>
            ${isNow ? `<div class="ph-prog"><i style="width:${Math.round((cur.day_index / cur.days) * 100)}%"></i></div>
              <div class="ph-meta">第 <b class="num">${cur.day_index}</b> / ${cur.days} 天 · 还剩 ${cur.days_left} 天</div>
              <ul class="ph-focus">${cur.focus.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`
              : `<div class="ph-meta">${x.days} 天${x.status === "done" ? " · 已完成" : ""}</div>`}
          </div></li>`;
      }).join("")}
    </ol>
  </div>

  <div class="card">
    <div class="card-head"><h2>每周节奏</h2><span class="small muted">任务量按每天学习时长自动调整</span></div>
    <div class="rhythm">${rhythm
      .map(([d, t]) => `<div class="${"日一二三四五六"[now.getDay()] === d ? "on" : ""}"><span>周${esc(d)}</span><b>${esc(t)}</b></div>`).join("")}</div>
    <p class="small muted" style="margin:12px 0 0">${p.rhythm ? "每天另有闪卡复习；到期错题在首页“今日复习”里。" : "每天另有速算、闪卡、阅读和错题复习。"}</p>
  </div>

  <div class="card">
    <div class="card-head"><h2>未来 7 天</h2></div>
    <div class="week-scroll">
      ${p.week.map((w, i) => `<div class="wk-day ${i === 0 ? "today" : ""}">
        <div class="wk-h"><b>${i === 0 ? "今天" : "周" + w.weekday}</b><span class="num">${w.date.slice(5).replace("-", ".")}</span></div>
        <div class="wk-focus">${esc(w.focus)}</div>
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
        ${form.map((x) => `<label class="field">${esc(x.label)}<input type="${x.type === "number" ? "number" : "date"}" data-k="${esc(x.key)}"
          ${x.type === "number" ? `min="1" max="12" step="0.5"` : ""} value="${esc(settings[x.key] || "")}"></label>`).join("")}
        <div class="row"><button class="btn primary" type="submit">保存并重新安排</button></div>
      </form>
    </div>
  </div>`;

  el.querySelector("#plan-form").onsubmit = async (e) => {
    e.preventDefault();
    const body = Object.fromEntries([...el.querySelectorAll("#plan-form [data-k]")].map((x) => [x.dataset.k, x.value]));
    if (body.guokao_date && body.shengkao_date && body.shengkao_date <= body.guokao_date) { toast("省考日期应在国考之后"); return; }
    await apiPost("/api/settings", body);
    toast("计划已更新，今日未完成的任务已重新生成");
    render(el);
  };
}
