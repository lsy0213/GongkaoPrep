// 全部考试总览：同时备几门考试时，每门的倒计时、做题量、学习时长放一屏，点一下切过去
import { apiGet, esc, switchExam } from "../lib.js";

function emblem(e) {
  return `<span class="exs-em" style="--exs:${esc(e.color || "#8C6D35")}">${esc(e.emblem || e.name.slice(0, 1))}</span>`;
}

function card(e, current) {
  const on = e.id === current;
  const dates = e.dates.length ? e.dates.map((d) => `<div class="ex-date ${d.days_left < 0 ? "passed" : ""}" title="${esc(d.date)}">
      <span>${d.days_left >= 0 ? "距" : ""}${esc(d.title)}${d.days_left < 0 ? "已过去" : ""}</span><b class="num">${Math.abs(d.days_left)}</b><small>天</small></div>`).join("")
    : `<div class="ex-date"><span>还没有设置考试日期</span></div>`;
  return `<div class="card ex-card ${on ? "on" : ""}">
    <div class="ex-top">${emblem(e)}<div><h3>${esc(e.family)}${e.family ? " · " : ""}${esc(e.name)}</h3>
      <span class="small muted">${esc(e.level ? e.level + " · " : "")}${esc(e.desc)}</span></div></div>
    <div class="ex-dates">${dates}</div>
    <div class="ex-stats">
      <div><b class="num">${e.questions}</b><span>做题</span></div>
      <div><b class="num">${e.questions ? e.accuracy + "%" : "—"}</b><span>正确率</span></div>
      <div><b class="num">${e.minutes >= 60 ? (e.minutes / 60).toFixed(e.minutes >= 600 ? 0 : 1) : e.minutes}</b><span>累计学习（${e.minutes >= 60 ? "小时" : "分钟"}）</span></div>
      <div><b class="num">${e.due_wrong}</b><span>到期错题</span></div>
    </div>
    <div class="ex-actions">
      ${on ? `<span class="chip good">当前考试</span><a class="btn sm" href="#/">回首页</a>` : `<button class="btn primary sm" data-go="${esc(e.id)}">切换到这门</button>`}
      <span class="small muted" style="margin-left:auto">${e.minutes_today ? `今天学了 ${e.minutes_today} 分钟` : e.last_day ? `上次学习 ${esc(e.last_day)}` : "还没开始"}</span>
    </div>
  </div>`;
}

export async function render(el) {
  const d = await apiGet("/api/exams/overview");
  el.innerHTML = `
    <div class="page-head"><div><h1>全部考试</h1>
      <p>每门考试的学习记录分开统计；打卡、笔记本、AI 设置和外观是共用的。切换后整个软件（菜单、首页、错题、闪卡）都换成那门考试。</p></div></div>
    ${(d.conflicts || []).map((c) => `<div class="card rk-notice mb"><b>考试时间挨得很近：${esc(c.note)}</b>
      <span class="small ink2">${esc(c.a)}（${esc(c.a_date)}）与 ${esc(c.b)}（${esc(c.b_date)}）。建议提前把后一门的计划往前排，或者在设置里改成下一次考试。</span></div>`).join("")}
    <div class="ex-grid">
      ${d.exams.map((e) => card(e, d.current)).join("")}
      <div class="card ex-card ex-add">
        <h3 style="margin:0">以后加别的考试</h3>
        <p class="small" style="margin:0">每门考试是一个「考试包」：<code>content/exams/&lt;名字&gt;/exam.json</code> 写科目、分值、菜单和设置项，需要的话再加教程、复习计划、专属页面和资料整理（做法见 <code>docs/添加考试.md</code>）。比如：</p>
        <ul class="small"><li>软考 · 软件设计师（中级）、系统分析师</li><li>信息系统项目管理师</li><li>教师资格、考研……</li></ul>
      </div>
    </div>`;
  el.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => switchExam(b.dataset.go)));
}
