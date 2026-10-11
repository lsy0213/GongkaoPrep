// 软考 · 资料库：资料文件夹整理情况（真题、模拟题、案例、论文、视频、文档）+ 整理按钮 + 按类别列出的文字资料（点开用阅读器读）
import { apiGet, apiPost, esc, store, toast } from "../../lib.js";

const CATS = [
  ["教材", "教材与官方教程"], ["讲义", "讲义与课件"], ["知识点", "知识点 · 背诵 · 笔记"], ["案例", "案例分析资料"],
  ["论文指导", "论文写作指导"], ["论文范文", "论文范文"], ["思维导图", "思维导图"], ["参考书", "架构参考书"], ["报名机考", "报名与机考"],
];
const JOBS = [
  ["all", "整理全部资料", "扫描资料文件夹、下载开源题库（第一次）、生成题库和案例论文、整理视频和文档"],
  ["github", "更新开源题库", "从 GitHub 重新下载 2020 年以来的真题回忆版和模拟卷，再生成题库"],
  ["bank", "只生成题库", "真题、模拟题、案例、论文"],
  ["docs", "只整理文档", "教材、讲义、笔记、范文（扫描件要 OCR，比较慢）"],
];

let poll = null;

export async function render(el, ctx) {
  clearInterval(poll);
  if (ctx.parts[1] === "doc" || ctx.parts[1] === "view") {
    const lib = await import("../library.js");
    return lib.render(el, ctx);
  }
  const [info, data, settings] = await Promise.all([apiGet("/api/rk/library"), apiGet("/api/docs"), apiGet("/api/settings")]);
  const docs = data.docs.filter((d) => !d.error || d.nblocks);
  const prog = data.progress;
  const saved = store.get("library3", {});
  let cat = CATS.some(([c]) => c === saved.rkCat) ? saved.rkCat : "all";

  // 纯文字（放进页面时再转义）
  const jobLine = (j) => j.running ? `正在${j.name}：${j.step} ${j.done}/${j.total} ${(j.msg || "").slice(0, 40)}`
    : j.finished_at ? `上次整理：${j.name}，完成于 ${j.finished_at}${j.error ? `（出错：${j.error}）` : ""}` : "";

  function docCard(d) {
    const p = prog[d.id] || {};
    const pct = Math.round((p.pct || 0) * 100);
    return `<a class="card rk-doc" href="#/library/doc/${encodeURIComponent(d.id)}">
      <b>${esc(d.title)}</b>
      <span class="small muted">${d.pages ? `${d.pages} 页 · ` : ""}${d.toc_n ? `目录 ${d.toc_n} 项 · ` : ""}${Math.round(d.chars / 1000)} 千字${d.nq ? ` · 例题 ${d.nq}` : ""}${d.scanned ? " · 扫描件" : ""}</span>
      ${pct ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ""}</a>`;
  }

  function draw(job) {
    const counts = Object.fromEntries(CATS.map(([c]) => [c, docs.filter((d) => d.cat === c).length]));
    const list = cat === "all" ? docs : docs.filter((d) => d.cat === cat);
    const reading = docs.filter((d) => prog[d.id] && !prog[d.id].done && (prog[d.id].pct || 0) > 0)
      .sort((a, b) => (prog[b.id].updated_at || "").localeCompare(prog[a.id].updated_at || "")).slice(0, 4);
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">学习</div><h1>软考资料库</h1>
        <p>教材、讲义、知识点、范文整理成带目录的文字，可以高亮、批注、全文搜索、选中一段问 AI。真题和模拟题在“真题卷”里做，案例和论文在各自的页面。</p></div></div>
      <div class="card mb job-box">
        <div class="card-head"><h3>资料文件夹</h3><span class="small muted">${info.scanned_at ? `扫描于 ${esc(info.scanned_at)} · ${info.files} 个文件` : "还没扫描"}</span></div>
        <div class="row"><input type="text" id="root" value="${esc(settings.library_root || "")}" style="flex:1;min-width:260px" aria-label="资料文件夹">
          <button class="btn" id="save-root">保存</button></div>
        <div class="lib-stats mt">
          <span>真题 <b class="num">${info.bank["真题"]}</b> 题（${info.bank.papers} 套）</span>
          <span>模拟题 <b class="num">${info.bank["模拟"]}</b> 题（${info.bank.mocks} 套）</span>
          <span>案例 <b class="num">${info.cases}</b> 道</span><span>论文题 <b class="num">${info.essays}</b> 道</span>
          <span>文档 <b class="num">${docs.length}</b> 份</span><span>视频 <b class="num">${info.videos}</b> 讲</span>
        </div>
        <div class="row mt">${JOBS.map(([id, name, hint]) => `<button class="btn ${id === "all" ? "primary" : "ghost"}" data-job="${id}" title="${esc(hint)}">${name}</button>`).join("")}</div>
        <p class="small muted" id="job-line">${esc(jobLine(job))}</p>
        <p class="small muted">开源题库：github.com/wujiaming88/awesome-ruankao（CC BY-SA 4.0）${info.github?.downloaded_at ? `，下载于 ${esc(info.github.downloaded_at)}` : info.github?.downloaded ? "" : "，还没下载"}。原始资料只读不改。</p>
      </div>
      ${reading.length ? `<h3>继续阅读</h3><div class="rk-doc-grid mb">${reading.map(docCard).join("")}</div>` : ""}
      <div class="pills scroll mb" id="cats"><button data-c="all" class="${cat === "all" ? "active" : ""}">全部<small class="num">${docs.length}</small></button>
        ${CATS.filter(([c]) => counts[c]).map(([c, name]) => `<button data-c="${c}" class="${cat === c ? "active" : ""}">${esc(name)}<small class="num">${counts[c]}</small></button>`).join("")}</div>
      ${list.length ? `<div class="rk-doc-grid">${list.map(docCard).join("")}</div>`
        : `<div class="card empty"><h3>${docs.length ? "这一类没有资料" : "还没有整理好的文档"}</h3><p class="small muted">点上面的“整理全部资料”。扫描件需要文字识别，第一次会比较久，可以先去做题。</p></div>`}`;
    el.querySelectorAll("#cats button").forEach((b) => (b.onclick = () => { cat = b.dataset.c; store.set("library3", { ...saved, rkCat: cat }); draw(job); }));
    el.querySelector("#save-root").onclick = async () => {
      await apiPost("/api/settings", { library_root: el.querySelector("#root").value.trim() });
      toast("已保存资料文件夹");
    };
    el.querySelectorAll("[data-job]").forEach((b) => (b.onclick = async () => {
      try {
        await apiPost("/api/settings", { library_root: el.querySelector("#root").value.trim() });
        const r = await apiPost("/api/rk/jobs/start", { job: b.dataset.job });
        toast(r.queued ? `已排队：${r.name}` : `已开始：${r.name}`);
        watch();
      } catch (e) { toast(e.message, 4000); }
    }));
  }

  function watch() {
    clearInterval(poll);
    poll = setInterval(async () => {
      if (!el.isConnected) { clearInterval(poll); return; }
      const j = await apiGet("/api/jobs").catch(() => null);
      if (!j) return;
      const line = el.querySelector("#job-line");
      if (line) line.textContent = jobLine(j);
      if (!j.running && !j.queue.length) { clearInterval(poll); render(el, ctx); }
    }, 1500);
  }

  draw(info.job);
  if (info.job.running) watch();
  return () => clearInterval(poll);
}
