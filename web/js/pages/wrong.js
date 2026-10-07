import { apiGet, apiPost, cropHTML, getQuestions, esc, LETTERS, md, MODULES, MODULE_SHORT, needsCrop, srcLabel, toast } from "../lib.js";
import { runQuiz } from "../quiz.js";
import { refreshBadge } from "../app.js";

const REASONS = ["", "概念不清", "方法不会", "审题错误", "计算失误", "时间不够", "粗心"];

export async function render(el) {
  const [wb, progress] = await Promise.all([apiGet("/api/wrongbook"), apiGet("/api/progress")]);
  const data = await getQuestions([...new Set([...wb.items.map((x) => x.qid), ...progress.favorites])]);
  const b = { byId: Object.fromEntries(data.questions.map((q) => [q.id, q])) };
  let tab = "due", mod = "全部";
  let cleanup = null;
  const open = new Set();
  const items = wb.items.filter((x) => b.byId[x.qid]);
  const due = items.filter((x) => !x.mastered && x.next_review <= wb.today);
  const favs = progress.favorites.filter((id) => b.byId[id]);

  function list() {
    if (tab === "fav") return favs.map((id) => ({ qid: id, module: b.byId[id].module, fav: true }));
    let xs = tab === "due" ? due : tab === "all" ? items.filter((x) => !x.mastered) : items.filter((x) => x.mastered);
    if (mod !== "全部") xs = xs.filter((x) => x.module === mod);
    return xs;
  }

  function reasonStats() {
    const c = {};
    items.filter((x) => x.reason).forEach((x) => (c[x.reason] = (c[x.reason] || 0) + 1));
    const total = Object.values(c).reduce((a, x) => a + x, 0);
    if (!total) return `<p class="small muted" style="margin:0">给错题选择错因后，这里会统计你最常见的失分原因。</p>`;
    return Object.entries(c).sort((a, z) => z[1] - a[1]).map(([k, v]) =>
      `<div class="hbar"><span>${esc(k)}</span><span class="track"><i style="width:${(v / total) * 100}%"></i></span><span class="v">${v} 题</span></div>`).join("");
  }

  function itemHTML(x) {
    const q = b.byId[x.qid];
    const isOpen = open.has(x.qid);
    const mat = q.material ? data.mat(q.material) : null;
    return `<div class="note-item">
      <div class="row">
        <span class="chip brand">${MODULE_SHORT[q.module] || esc(q.module)}</span>
        ${q.real ? `<span class="chip">${esc(srcLabel(q))} · 第 ${q.num} 题</span>` : ""}
        ${x.fav ? "" : `<span class="small muted">错 ${x.wrong_count} 次 · ${x.mastered ? "已掌握" : x.next_review <= wb.today ? `<b style="color:var(--bad)">今天该复习</b>` : `下次复习 ${esc(x.next_review)}`}
          · ${x.stability ? `记忆稳定性约 ${x.stability < 1 ? "不到 1" : Math.round(x.stability)} 天` : `已复习 ${x.stage} 次`}</span>`}
        <span class="spacer"></span>
        ${x.fav ? "" : `<select data-reason="${esc(x.qid)}" aria-label="错因" style="width:auto;padding:3px 8px;font-size:13px">
          ${REASONS.map((r) => `<option value="${r}" ${r === (x.reason || "") ? "selected" : ""}>${r || "选择错因"}</option>`).join("")}</select>`}
        <button class="btn sm ghost" data-toggle="${esc(x.qid)}">${isOpen ? "收起" : "看题"}</button>
        ${x.fav ? `<button class="btn sm ghost" data-unfav="${esc(x.qid)}">取消收藏</button>` :
          `<button class="btn sm ghost" data-master="${esc(x.qid)}" data-v="${x.mastered ? 0 : 1}">${x.mastered ? "移回错题" : "已掌握"}</button>`}
      </div>
      <div class="c ${isOpen ? "" : "small ink2"}" style="${isOpen ? "" : "white-space:nowrap;overflow:hidden;text-overflow:ellipsis"}">${isOpen && needsCrop(q) ? cropHTML(q.crop, q.fid) : esc(isOpen ? q.stem : (q.stem || "（图形题，展开看原卷）").split("\n")[0])}</div>
      ${isOpen ? `
        ${mat ? `<details class="mt"><summary class="small ink2" style="cursor:pointer">查看材料：${esc(mat.title || "材料")}</summary><div class="material mt prose">${mat.crop && mat.fig ? cropHTML(mat.crop, mat.fid) : md(mat.text)}</div></details>` : ""}
        ${q.options ? `<div class="options mt">${q.options.map((o, k) => `<div class="opt ${k === q.answer ? "right" : ""}" style="cursor:default"><span class="L">${LETTERS[k]}</span><span>${esc(o)}</span></div>`).join("")}</div>`
          : `<div class="mt">正确答案：<b>${LETTERS[q.answer]}</b></div>`}
        <div class="explain-text mt">${esc(q.explain || "")}</div>
        ${progress.notes[x.qid] ? `<div class="ai-box"><b class="small">我的笔记</b><div class="small" style="white-space:pre-wrap">${esc(progress.notes[x.qid])}</div></div>` : ""}` : ""}
    </div>`;
  }

  function draw() {
    const xs = list();
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">错题本</div><h1>错题比新题更值得做</h1>
        <p>做错的题第二天复习；之后按 FSRS 记忆模型安排：每次到期做对，间隔就按你对这道题的记忆稳定性拉长，间隔超过设置里的天数（默认 30 天）即视为掌握，再做错会重新开始。</p></div>
        <div class="row">
          <button class="btn primary lg" id="review" ${due.length ? "" : "disabled"}>${due.length ? `复习今天到期的 ${due.length} 题` : "今天没有到期的错题"}</button>
        </div></div>
      <div class="grid cols-main">
        <div class="card">
          <div class="tabs" id="tabs">
            ${[["due", `今日待复习 ${due.length}`], ["all", `未掌握 ${items.filter((x) => !x.mastered).length}`], ["done", `已掌握 ${items.filter((x) => x.mastered).length}`], ["fav", `收藏 ${favs.length}`]]
              .map(([k, n]) => `<button data-tab="${k}" class="${tab === k ? "active" : ""}">${n}</button>`).join("")}
          </div>
          ${tab !== "fav" ? `<div class="seg mb" id="mods">${["全部", ...MODULES].map((m) => `<button data-m="${esc(m)}" class="${mod === m ? "active" : ""}">${esc(MODULE_SHORT[m] || m)}</button>`).join("")}</div>` : ""}
          ${xs.length ? xs.map(itemHTML).join("") : `<div class="empty"><h3>${tab === "due" ? "今天没有需要复习的错题" : "这里还是空的"}</h3>
            <p>${tab === "fav" ? "做题时点“收藏”可以把好题收进来。" : "去 <a href='#/practice'>刷题</a> 吧，做错的题会自动收进来。"}</p></div>`}
          ${xs.length ? `<div class="row mt">
            ${tab !== "due" ? `<button class="btn" id="redo">${tab === "fav" ? "练习收藏的题" : `把这 ${xs.length} 题再做一遍`}</button>` : ""}
            <span class="spacer"></span>
            <label class="small row" style="gap:4px"><input type="checkbox" id="ans-last" checked> 答案放最后（先自测）</label>
            <button class="btn ghost" id="print">导出打印（${xs.length} 题）</button></div>` : ""}
        </div>
        <div class="stack" style="gap:16px">
          <div class="card"><h3 class="mb">错因统计</h3>${reasonStats()}</div>
          <div class="card"><h3 class="mb">各模块错题</h3>
            ${MODULES.map((m) => {
              const n = items.filter((x) => x.module === m && !x.mastered).length;
              return `<div class="row" style="justify-content:space-between;padding:3px 0"><span>${esc(m)}</span><span class="num ${n ? "" : "muted"}">${n}</span></div>`;
            }).join("")}
          </div>
        </div>
      </div>`;
    el.querySelectorAll("[data-tab]").forEach((x) => (x.onclick = () => { tab = x.dataset.tab; draw(); }));
    el.querySelectorAll("#mods button").forEach((x) => (x.onclick = () => { mod = x.dataset.m; draw(); }));
    el.querySelectorAll("[data-toggle]").forEach((x) => (x.onclick = () => {
      const id = x.dataset.toggle;
      open.has(id) ? open.delete(id) : open.add(id);
      draw();
    }));
    el.querySelectorAll("[data-reason]").forEach((x) => (x.onchange = async () => {
      await apiPost("/api/wrongbook/reason", { qid: x.dataset.reason, reason: x.value });
      const it = items.find((i) => i.qid === x.dataset.reason);
      if (it) it.reason = x.value;
      draw();
    }));
    el.querySelectorAll("[data-master]").forEach((x) => (x.onclick = async () => {
      const v = x.dataset.v === "1";
      await apiPost("/api/wrongbook/master", { qid: x.dataset.master, mastered: v });
      toast(v ? "已标记为掌握" : "已移回错题");
      render(el);
      refreshBadge();
    }));
    el.querySelectorAll("[data-unfav]").forEach((x) => (x.onclick = async () => {
      await apiPost("/api/favorite", { qid: x.dataset.unfav, on: false });
      render(el);
    }));
    const startQuiz = async (ids, title, mode) => {
      cleanup = await runQuiz(el, { title, ids: groupIds(ids), mode, onAgain: () => { cleanup?.(); render(el); } });
    };
    const rv = el.querySelector("#review");
    if (rv) rv.onclick = () => startQuiz(due.map((x) => x.qid), `今日错题复习 · ${due.length} 题`, "review");
    const redo = el.querySelector("#redo");
    if (redo) redo.onclick = () => startQuiz(xs.map((x) => x.qid), tab === "fav" ? "收藏题练习" : "错题重做", "practice");
    const pr = el.querySelector("#print");
    if (pr) pr.onclick = () => printList(xs, el.querySelector("#ans-last").checked);
  }

  // 打印版：题干、选项、原卷截图、我的错因和笔记；答案解析跟在每题后面或集中放在最后。用打印对话框“另存为 PDF”
  function printList(xs, ansLast) {
    const tabName = { due: "今日待复习", all: "未掌握", done: "已掌握", fav: "收藏" }[tab];
    const qs = groupIds(xs.map((x) => x.qid)).map((id) => b.byId[id]).filter(Boolean);
    const info = Object.fromEntries(items.map((x) => [x.qid, x]));
    const seenMat = new Set();
    const ans = (q, i) => `<div class="pr-ans"><b>${i + 1}. 答案 ${LETTERS[q.answer] ?? "—"}</b>
      ${q.explain ? `<div>${esc(q.explain)}</div>` : ""}
      ${progress.notes[q.id] ? `<div class="pr-note">我的笔记：${esc(progress.notes[q.id])}</div>` : ""}</div>`;
    const body = qs.map((q, i) => {
      const x = info[q.id] || {};
      let mat = "";
      if (q.material && !seenMat.has(q.material)) {
        seenMat.add(q.material);
        const m = data.mat(q.material);
        if (m) mat = `<div class="pr-mat"><b>${esc(m.title || "材料")}</b>${m.crop && m.fig ? cropHTML(m.crop, m.fid) : `<div>${md(m.text || "")}</div>`}</div>`;
      }
      return `${mat}<div class="pr-q">
        <div class="pr-head">${i + 1}. <span class="muted">${esc(MODULE_SHORT[q.module] || q.module)}${q.real ? " · " + esc(srcLabel(q)) + " 第 " + q.num + " 题" : ""}
          ${x.wrong_count ? ` · 错 ${x.wrong_count} 次` : ""}${x.reason ? ` · 错因：${esc(x.reason)}` : ""}</span></div>
        ${needsCrop(q) ? cropHTML(q.crop, q.fid) : `<div class="pr-stem">${esc(q.stem)}</div>`}
        ${q.options ? `<div class="pr-opts">${q.options.map((o, k) => `<div>${LETTERS[k]}. ${esc(o)}</div>`).join("")}</div>` : ""}
        ${ansLast ? "" : ans(q, i)}</div>`;
    }).join("");
    const html = `<div class="print-sheet">
      <div class="no-print row mb"><button class="btn primary" id="do-print">打印 / 另存为 PDF</button><button class="btn" id="back">返回错题本</button>
        <span class="small muted">打印对话框里把“目标打印机”选成“另存为 PDF”就能得到 PDF 文件</span></div>
      <h1>错题本 · ${esc(tabName)}${mod !== "全部" ? " · " + esc(mod) : ""}</h1>
      <p class="small muted">共 ${qs.length} 题 · ${new Date().toLocaleDateString("zh-CN")} 导出</p>
      ${body}
      ${ansLast ? `<h2 class="pr-break">答案与解析</h2>${qs.map(ans).join("")}` : ""}</div>`;
    el.innerHTML = html;
    el.querySelector("#do-print").onclick = () => window.print();
    el.querySelector("#back").onclick = () => draw();
  }

  // 同一材料的题挨在一起
  function groupIds(ids) {
    const out = [], seen = new Set();
    for (const id of ids) {
      if (seen.has(id)) continue;
      const m = b.byId[id]?.material;
      for (const x of m ? ids.filter((y) => b.byId[y]?.material === m) : [id]) if (!seen.has(x)) { seen.add(x); out.push(x); }
    }
    return out;
  }

  draw();
  return () => cleanup?.();
}
