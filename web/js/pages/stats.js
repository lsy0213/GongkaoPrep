import { accuracyBars, apiGet, esc, fmtClock, fmtMinutes, lineChart, MODULES, todayISO } from "../lib.js";

const COURSE_OF = { "政治理论": "politics", "常识判断": "common", "言语理解与表达": "verbal", "数量关系": "math", "判断推理": "reason", "资料分析": "data" };

const TARGET = { "政治理论": 30, "常识判断": 40, "言语理解与表达": 45, "数量关系": 60, "判断推理": 55, "资料分析": 75 };

function heatmap(heat, checkins) {
  const map = Object.fromEntries(heat.map((h) => [h.day, h.minutes]));
  const ck = new Set(checkins);
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - 7 * 26 + 1);
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7)); // 对齐到周一
  let cells = "";
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const iso = todayISO(d);
    const m = map[iso] || 0;
    const l = m === 0 ? "" : m < 30 ? "l1" : m < 90 ? "l2" : m < 180 ? "l3" : "l4";
    cells += `<i class="${l} ${ck.has(iso) ? "ck" : ""}" title="${iso}：${m} 分钟${ck.has(iso) ? "，已打卡" : ""}"></i>`;
  }
  return `<div class="heat">${cells}</div>`;
}

export async function render(el) {
  const s = await apiGet("/api/stats");
  const totalQ = s.modules.reduce((a, m) => a + m.total, 0);
  const totalOk = s.modules.reduce((a, m) => a + m.correct, 0);
  const totalMin = s.minutes_by_module.reduce((a, m) => a + m.minutes, 0);
  const rows = MODULES.map((m) => {
    const r = s.modules.find((x) => x.module === m);
    return { name: m, total: r?.total || 0, ok: r?.correct || 0, acc: r?.accuracy || 0, avg: r?.avg_seconds || 0 };
  });
  const weakest = rows.filter((r) => r.total >= 5).sort((a, b) => a.acc - b.acc)[0];
  const maxMin = Math.max(1, ...s.minutes_by_module.map((m) => m.minutes));
  const days = s.days.map((d) => ({ l: d.day.slice(5), v: d.questions, m: d.minutes }));

  el.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">学习统计</div><h1>看看自己走了多远</h1></div></div>
    <div class="stats mb">
      <div class="stat"><div class="v num">${Math.round(totalMin / 60)}<small>小时</small></div><div class="k">累计学习</div></div>
      <div class="stat"><div class="v num">${s.checkins.length}<small>天</small></div><div class="k">累计打卡</div></div>
      <div class="stat"><div class="v num">${totalQ}<small>题</small></div><div class="k">累计做题</div></div>
      <div class="stat"><div class="v num">${totalQ ? Math.round((totalOk / totalQ) * 100) : 0}<small>%</small></div><div class="k">总正确率</div></div>
      <div class="stat"><div class="v num">${s.essays}<small>篇</small></div><div class="k">申论作答</div></div>
      <div class="stat"><div class="v num">${s.interviews}<small>题</small></div><div class="k">面试练习</div></div>
      <div class="stat"><div class="v num">${s.readings}<small>篇</small></div><div class="k">阅读文章</div></div>
      <div class="stat"><div class="v num">${s.wrong_mastered}<small>/ ${s.wrong_open + s.wrong_mastered}</small></div><div class="k">错题已掌握</div></div>
    </div>

    <div class="card">
      <div class="card-head"><h2>近 30 天</h2><span class="small muted"><span style="color:var(--brand)">—</span> 做题数　<span style="color:var(--warn)">- -</span> 学习分钟</span></div>
      ${lineChart(days.map((d) => ({ l: d.l, v: d.v, m: d.m })), { key: "v", key2: "m", labelEvery: 5 })}
    </div>

    <div class="grid cols-2 mt">
      <div class="card">
        <div class="card-head"><h2>各模块表现</h2></div>
        ${accuracyBars(rows.map((r) => ({ name: r.name, total: r.total, acc: r.acc })))}
        <div class="table-wrap mt"><table class="tbl"><thead><tr><th>模块</th><th class="n">做题</th><th class="n">正确率</th><th class="n">平均用时</th><th class="n">参考用时</th></tr></thead><tbody>
          ${rows.map((r) => `<tr><td>${esc(r.name)}</td><td class="n">${r.total}</td><td class="n">${r.total ? r.acc + "%" : "—"}</td>
            <td class="n" style="${r.total && r.avg > TARGET[r.name] * 1.3 ? "color:var(--bad)" : ""}">${r.total ? r.avg + " 秒" : "—"}</td><td class="n muted">${TARGET[r.name]} 秒</td></tr>`).join("")}
        </tbody></table></div>
        <p class="small ink2">${weakest ? `目前最需要加强的是 <b>${esc(weakest.name)}</b>（正确率 ${weakest.acc}%），建议回看 <a href="#/learn/${COURSE_OF[weakest.name] || ""}">教程</a> 并多做专项练习。` : "每个模块做满 5 题后，这里会给出薄弱项建议。"}
          平均用时偏高（标红）的模块，说明方法还不够熟练。</p>
      </div>
      <div class="card">
        <div class="card-head"><h2>学习时间分布</h2><span class="small muted">共 ${fmtMinutes(totalMin)}</span></div>
        ${s.minutes_by_module.length ? s.minutes_by_module.map((m) => `<div class="hbar"><span>${esc(m.module)}</span><span class="track"><i style="width:${(m.minutes / maxMin) * 100}%"></i></span><span class="v">${m.minutes} 分</span></div>`).join("")
          : `<div class="empty small">做题、读教程、用专注计时器学习都会被记录</div>`}
        <hr class="sep">
        <h3 class="mb">近半年学习热力图</h3>
        ${heatmap(s.heat, s.checkins)}
        <div class="small muted">颜色越深学习时间越长，黄框表示当天打了卡。</div>
      </div>
    </div>

    <div class="card mt">
      <div class="card-head"><h2>最近的练习</h2></div>
      ${s.sessions.length ? `<div class="table-wrap"><table class="tbl"><thead><tr><th>时间</th><th>内容</th><th class="n">正确</th><th class="n">正确率</th><th class="n">用时</th></tr></thead><tbody>
        ${s.sessions.map((x) => `<tr><td class="small">${esc(x.created_at.slice(5, 16))}</td><td>${esc(x.title)}</td><td class="n">${x.correct}/${x.total}</td>
          <td class="n">${x.total ? Math.round((x.correct / x.total) * 100) : 0}%</td><td class="n">${fmtClock(x.duration)}</td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty">还没有练习记录</div>`}
    </div>`;
}
