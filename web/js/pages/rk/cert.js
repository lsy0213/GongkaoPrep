// 软考 · 考试与证书：从报名到拿证的流程和时间点、证书的用途，以及自己每次考试的成绩记录（存在 prefs）
import { apiGet, esc, store, toast } from "../../lib.js";

const STEPS = [
  ["报名", "各省人事考试机构分别组织，时间不统一（上半年考试一般 3～4 月）。在本省人事考试网或中国计算机技术职业资格网的报名入口报名、审核、缴费。"],
  ["打印准考证", "考前一周左右开放打印，确认机考批次、场次和考点。考前用官方模拟作答系统熟悉界面和输入法。"],
  ["考试", "机考。上午综合知识与案例分析连考 240 分钟，下午论文 120 分钟。带身份证和准考证。"],
  ["查成绩", "一般在考后 1～2 个月，在中国计算机技术职业资格网查询。三科在同一次考试中都达到合格线才算通过，成绩不保留。"],
  ["领证书", "合格名单公示后，按考区通知领取纸质证书，或在网上下载电子证书。"],
];

const USES = [
  ["职称", "取得高级资格，用人单位可以据此聘任高级工程师（以考代评）。"],
  ["落户与人才政策", "一些城市把软考高级资格作为积分落户、人才认定的依据，政策各地不同、经常调整，以当地人社部门为准。"],
  ["个税扣除", "取得证书的当年，可以享受继续教育专项附加扣除 3600 元。"],
  ["招投标与资质", "不少企业资质评定、项目投标要求有高级资格的人员。"],
];

const KEY = "rk-results";

function results() {
  return store.get(KEY, []) || [];
}

function resultsCard() {
  const list = results();
  return `<div class="card">
    <div class="card-head"><h2>我的考试记录</h2><span class="small muted">考完记下估分，成绩出来再补上实际分数</span></div>
    ${list.length ? `<div class="table-wrap"><table class="tbl"><thead><tr><th>考试</th><th>综合知识</th><th>案例分析</th><th>论文</th><th>结果</th><th></th></tr></thead><tbody>
      ${list.map((r, i) => {
        const ok = [r.zh, r.al, r.lw].every((x) => x !== "" && +x >= 45);
        const done = [r.zh, r.al, r.lw].every((x) => x !== "");
        return `<tr><td>${esc(r.date)}${r.note ? `<div class="small muted">${esc(r.note)}</div>` : ""}</td>
          <td class="num">${esc(r.zh || "—")}</td><td class="num">${esc(r.al || "—")}</td><td class="num">${esc(r.lw || "—")}</td>
          <td>${done ? (ok ? `<span class="chip good">通过</span>` : `<span class="chip bad">未通过</span>`) : `<span class="chip">待补全</span>`}</td>
          <td><button class="btn sm ghost" data-del="${i}">删除</button></td></tr>`;
      }).join("")}</tbody></table></div>` : `<p class="small muted">还没有记录。</p>`}
    <form id="res-form" class="grid cols-2 mt">
      <label class="field">考试日期<input type="date" name="date" required></label>
      <label class="field">备注<input type="text" name="note" placeholder="例如：估分 / 实际成绩、论文题目"></label>
      <label class="field">综合知识<input type="number" name="zh" min="0" max="75" step="1"></label>
      <label class="field">案例分析<input type="number" name="al" min="0" max="75" step="1"></label>
      <label class="field">论文<input type="number" name="lw" min="0" max="75" step="1"></label>
      <div class="row"><button class="btn primary" type="submit">添加记录</button></div>
    </form>
  </div>`;
}

export async function render(el) {
  const p = await apiGet("/api/plan");
  el.innerHTML = `
  <div class="page-head"><div><div class="eyebrow">软考 · 系统架构设计师</div><h1>考试与证书</h1>
    <p>从报名到拿证的每一步。时间是按设置里的考试日期推算的预估，以中国计算机技术职业资格网和本省考试机构的通知为准。</p></div></div>

  <div class="grid cols-2">
    <div class="card">
      <div class="card-head"><h2>流程</h2><a class="small" href="#/learn/rk-start-03">教程：报名、机考与考场流程 →</a></div>
      <ol class="cert-steps">${STEPS.map(([t, d], i) => `<li><span class="n num">${i + 1}</span><div><b>${esc(t)}</b><p class="small ink2">${esc(d)}</p></div></li>`).join("")}</ol>
    </div>
    <div class="card">
      <div class="card-head"><h2>关键时间点</h2><a class="small" href="#/settings">改考试日期</a></div>
      <ul class="milestones">
        ${p.milestones.map((m) => `<li class="${m.days_left < 0 ? "past" : ""} ${m.exam_day ? "exam" : ""}">
          <span class="d">${esc(m.date)}</span>
          <span><span class="t">${esc(m.title)}</span><br><span class="small muted">${esc(m.note)}</span></span>
          <span class="left">${m.days_left < 0 ? "已过" : m.days_left === 0 ? "今天" : m.days_left + " 天"}</span></li>`).join("")}
      </ul>
    </div>
  </div>

  <div class="card">
    <div class="card-head"><h2>证书能做什么</h2><a class="small" href="#/learn/rk-start-01">教程：软考全景 →</a></div>
    <div class="cert-uses">${USES.map(([t, d]) => `<div><b>${esc(t)}</b><span class="small ink2">${esc(d)}</span></div>`).join("")}</div>
  </div>

  ${resultsCard()}`;

  el.querySelector("#res-form").onsubmit = (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target).entries());
    if (!f.date) return;
    const list = results().concat([{ date: f.date, note: f.note.trim(), zh: f.zh, al: f.al, lw: f.lw }]);
    list.sort((a, b) => b.date.localeCompare(a.date));
    store.set(KEY, list);
    toast("已记下");
    render(el);
  };
  el.querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => {
    const list = results();
    list.splice(+b.dataset.del, 1);
    store.set(KEY, list);
    render(el);
  }));
}
