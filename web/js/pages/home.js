import { accuracyBars, apiGet, apiPost, barChart, content, esc, fmtMinutes, MODULES, toast } from "../lib.js";

function ring(done, total) {
  const r = 50, c = 2 * Math.PI * r, p = total ? done / total : 0;
  return `<div class="ring"><svg viewBox="0 0 118 118" width="118" height="118">
    <circle class="track" cx="59" cy="59" r="${r}" stroke-width="6"/>
    <circle class="val" cx="59" cy="59" r="${r}" stroke-width="6" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - p)}"/></svg>
    <div class="ring-label"><div><b>${done}</b><span>/ ${total} 项任务</span></div></div></div>`;
}

const MODULE_ICON_ORDER = MODULES;

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
  </div>

  <div class="countdowns mb">
    ${exams.map((m) => `
      <div class="card countdown exam ${m.days_left < 0 ? "passed" : ""}">
        ${m.days_left >= 0 && m.days_left <= 30 ? `<span class="stamp">冲刺</span>` : ""}
        <div class="label">${m.days_left >= 0 ? "距" : ""}${esc(m.title)}${m.days_left < 0 ? "已过去" : ""}</div>
        <div class="days num">${Math.abs(m.days_left)}<small>天</small></div>
        <div class="date">${esc(m.date)} · 预估，可在设置中修改</div>
      </div>`).join("")}
    <div class="card countdown">
      <div class="label">当前阶段剩余</div>
      <div class="days num">${phase.days_left}<small>天</small></div>
      <div class="date">${esc(phase.name)}：${esc(phase.start)} 至 ${esc(phase.end)}</div>
    </div>
  </div>

  <div class="stats mb">
    <div class="stat"><div class="v num">${d.streak}<small>天</small></div><div class="k">连续打卡</div></div>
    <div class="stat"><div class="v num">${d.minutes_today}<small>分钟</small></div><div class="k">今日学习</div></div>
    <div class="stat"><div class="v num">${d.questions_today}<small>题</small></div><div class="k">今日做题${d.questions_today ? ` · 正确率 ${Math.round((d.correct_today / d.questions_today) * 100)}%` : ""}</div></div>
    <div class="stat ${d.due_wrong ? "alert" : ""}"><div class="v num">${d.due_wrong}<small>题</small></div><div class="k"><a href="#/wrong">待复习错题</a></div></div>
    <div class="stat"><div class="v num">${d.due_cards}<small>张</small></div><div class="k"><a href="#/cards">待复习闪卡</a></div></div>
  </div>

  <div class="grid cols-main">
    <div class="card">
      <div class="card-head">
        <h2>今日任务</h2>
        <span class="small muted num">${doneCount} / ${d.tasks.length}</span>
      </div>
      <div class="progress mb"><i style="width:${pct}%"></i></div>
      <ul class="tasks" id="tasks">
        ${d.tasks.map((t) => `
          <li class="task ${t.done ? "done" : ""}">
            <input type="checkbox" data-id="${t.id}" ${t.done ? "checked" : ""} aria-label="完成：${esc(t.title)}">
            <div class="t"><div class="t-title">${esc(t.title)}</div>
              <div class="t-meta">${esc(t.module)}${t.minutes ? ` · 约 ${t.minutes} 分钟` : ""}${t.source === "user" ? " · 自己添加" : ""}</div></div>
            ${t.link ? `<a class="btn sm" href="${esc(t.link)}">去完成</a>` : `<button class="btn sm ghost" data-del="${t.id}" title="删除">删除</button>`}
          </li>`).join("")}
      </ul>
      <form class="row mt" id="add-task">
        <input type="text" id="new-task" placeholder="添加一项自己的任务，例如：背 20 个成语" style="flex:1;min-width:180px">
        <button class="btn" type="submit">添加</button>
      </form>
      <hr class="sep">
      <div id="checkin">
        ${d.checked_in
          ? `<div class="row"><span class="chip good">今日已打卡</span><span class="small muted">累计打卡 ${d.checkin_total} 天，连续 ${d.streak} 天</span></div>`
          : `<div class="stack">
              <textarea id="checkin-note" rows="2" placeholder="今天学了什么、有什么收获或问题？（可不填）"></textarea>
              <div class="row"><button class="btn primary" id="checkin-btn">打卡</button>
                <span class="small muted">${pct < 100 ? `还有 ${d.tasks.length - doneCount} 项任务未完成，也可以先打卡` : "今日任务全部完成，打个卡吧"}</span></div>
            </div>`}
      </div>
    </div>

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

  el.querySelectorAll("#tasks input[type=checkbox]").forEach((cb) => {
    cb.onchange = async () => {
      try {
        await apiPost("/api/tasks/toggle", { id: +cb.dataset.id });
        render(el);
      } catch (e) { toast(e.message); }
    };
  });
  el.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = async () => {
      await apiPost("/api/tasks/delete", { id: +b.dataset.del });
      render(el);
    };
  });
  el.querySelector("#add-task").onsubmit = async (e) => {
    e.preventDefault();
    const title = el.querySelector("#new-task").value.trim();
    if (!title) return;
    await apiPost("/api/tasks/add", { title });
    render(el);
  };
  const btn = el.querySelector("#checkin-btn");
  if (btn) btn.onclick = async () => {
    const r = await apiPost("/api/checkin", { note: el.querySelector("#checkin-note").value });
    toast(`打卡成功，已连续 ${r.streak} 天`);
    render(el);
  };
}
