// 选岗：导入职位表（国考、省考的 Excel），填好自己的条件，只看能报的岗位；导入报名人数后可以按报录比排序
import { apiPost, esc, store, toast } from "../lib.js";

const EDU = ["大专", "本科", "硕士研究生", "博士研究生"];
const POLITICS = ["群众", "共青团员", "中共党员"];
const SORTS = [["", "表格顺序"], ["count", "招考人数多的在前"], ["ratio", "报录比低的在前"], ["ratio_desc", "报录比高的在前"]];

async function upload(path, file) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.error) throw new Error(j.error || `上传失败（${r.status}）`);
  return j;
}

export async function render(el) {
  const prof = store.get("job_profile", { edu: "本科", politics: "群众", years: 0, project: false, majors: [] });
  let favs = new Set((store.get("job_favs", []) || []).map(String));
  const st = { q: "", region: "", mine: !!(prof.majors || []).length, only_fav: false, sort: "", page: 1, batch: null };
  const open = new Set();
  let res = null;

  async function load() {
    res = await apiPost("/api/positions/search", { ...st, batch: st.batch });
    st.batch = res.batch;
    draw();
  }

  function profileCard() {
    return `<form class="card" id="prof">
      <div class="card-head"><h2>我的报考条件</h2><span class="small muted">按这些条件判断每个岗位能不能报</span></div>
      <div class="grid cols-3">
        <label class="field">最高学历<select id="p-edu">${EDU.map((x) => `<option ${x === prof.edu ? "selected" : ""}>${x}</option>`).join("")}</select></label>
        <label class="field">政治面貌<select id="p-pol">${POLITICS.map((x) => `<option ${x === prof.politics ? "selected" : ""}>${x}</option>`).join("")}</select></label>
        <label class="field">基层工作年限<input type="number" id="p-years" min="0" max="40" value="${+prof.years || 0}"></label>
        <label class="field" style="grid-column:span 2">专业（名称、专业类或代码，多个用逗号或空格隔开）
          <input type="text" id="p-major" value="${esc((prof.majors || []).join("，"))}" placeholder="例如：计算机科学与技术，计算机类，0809"></label>
        <label class="field row" style="align-items:center;gap:8px;margin-top:22px"><input type="checkbox" id="p-proj" ${prof.project ? "checked" : ""}> 有服务基层项目经历（村官、三支一扶、西部计划等）</label>
      </div>
      <p class="small muted">专业按“职位表里出现了你填的任意一个词”判断，建议同时填专业全称和所属专业类（如“会计学，工商管理类”），以官方专业目录和招录机关解释为准。</p>
      <div class="row"><button class="btn primary" type="submit">保存条件</button></div></form>`;
  }

  function row(p) {
    const ok = !p.blocked.length;
    const isFav = favs.has(String(p.id));
    return `<tr class="${ok ? "" : "muted"}">
      <td><button class="btn sm ghost" data-fav="${p.id}" title="${isFav ? "取消收藏" : "收藏"}">${isFav ? "★" : "☆"}</button></td>
      <td><b>${esc(p.dept)}</b>${p.unit ? `<div class="small muted">${esc(p.unit)}</div>` : ""}</td>
      <td>${esc(p.title)}<div class="small muted num">${esc(p.code)}</div></td>
      <td class="small">${esc(p.region)}</td>
      <td class="n">${p.count}</td>
      <td class="n">${p.ratio != null ? `${p.ratio}:1` : "—"}</td>
      <td class="small">${ok ? `<span class="chip good">能报</span>` : `<span class="chip bad" title="不符合：${esc(p.blocked.join("、"))}">不符合 ${esc(p.blocked.join("、"))}</span>`}</td>
      <td><button class="btn sm ghost" data-open="${p.id}">${open.has(p.id) ? "收起" : "详情"}</button></td></tr>
      ${open.has(p.id) ? `<tr><td></td><td colspan="7"><div class="small" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:4px 16px">
        ${Object.entries(p.raw).map(([k, v]) => `<div><span class="muted">${esc(k)}：</span>${esc(v)}</div>`).join("")}</div></td></tr>` : ""}`;
  }

  function draw() {
    const focusId = ["q", "region"].includes(document.activeElement?.id) ? document.activeElement.id : "";
    drawPage();
    if (focusId) {
      const inp = el.querySelector("#" + focusId);
      inp?.focus();
      inp?.setSelectionRange?.(inp.value.length, inp.value.length);
    }
  }

  function drawPage() {
    const has = res.batches.length;
    const pages = Math.max(1, Math.ceil(res.total / (res.size || 50)));
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">选岗</div><h1>找出自己能报、好考的岗位</h1>
        <p>把国考或省考公告里的《职位表》Excel 导进来，填好自己的条件，软件逐个岗位核对学历、政治面貌、基层年限、服务基层项目和专业。
          报名期间各机构会公布报名人数，导入后可以按报录比排序。</p></div></div>
      <div class="card">
        <div class="row"><b>导入职位表</b>
          <input type="file" id="pf" accept=".xls,.xlsx" style="max-width:260px">
          <input type="text" id="pname" placeholder="起个名字，如 2027 国考" style="width:180px">
          <button class="btn primary" id="pup">导入</button>
          ${has ? `<span class="spacer"></span><select id="batch">${res.batches.map((b) => `<option value="${b.id}" ${b.id === res.batch ? "selected" : ""}>${esc(b.name)}（${b.count} 个岗位）</option>`).join("")}</select>
            <button class="btn ghost danger sm" id="bdel">删除这份</button>` : ""}</div>
        ${has ? `<div class="row mt"><b>导入报名人数</b><input type="file" id="af" accept=".xls,.xlsx" style="max-width:260px"><button class="btn" id="aup">导入</button>
          <span class="small muted">表里要有“职位代码”和“报名人数 / 过审人数”两列</span></div>` : ""}
      </div>
      ${profileCard()}
      ${has ? `<div class="card">
        <div class="row mb">
          <input type="search" id="q" value="${esc(st.q)}" placeholder="搜部门、职位、专业、代码（空格分隔多个词）" style="flex:1;min-width:200px">
          <input type="text" id="region" value="${esc(st.region)}" placeholder="工作地点，如 成都" style="width:150px">
          <select id="sort">${SORTS.map(([k, n]) => `<option value="${k}" ${st.sort === k ? "selected" : ""}>${n}</option>`).join("")}</select>
          <label class="small row" style="gap:4px"><input type="checkbox" id="mine" ${st.mine ? "checked" : ""}> 只看我能报的</label>
          <label class="small row" style="gap:4px"><input type="checkbox" id="ofav" ${st.only_fav ? "checked" : ""}> 只看收藏</label>
        </div>
        <p class="small muted">共 ${res.all} 个岗位，符合筛选的 ${res.total} 个${res.total ? `，第 ${res.page} / ${pages} 页` : ""}。</p>
        ${res.items.length ? `<div class="table-wrap"><table class="tbl"><thead><tr><th></th><th>部门</th><th>职位</th><th>地点</th><th class="n">招考</th><th class="n">报录比</th><th>条件</th><th></th></tr></thead>
          <tbody>${res.items.map(row).join("")}</tbody></table></div>
          <div class="row mt"><button class="btn sm" id="prev" ${res.page <= 1 ? "disabled" : ""}>上一页</button>
            <button class="btn sm" id="next" ${res.page >= pages ? "disabled" : ""}>下一页</button></div>`
          : `<div class="empty">没有符合条件的岗位，放宽一下条件试试</div>`}
      </div>` : `<div class="card empty"><h3>还没有导入职位表</h3><p>在国家公务员局或省人事考试网的招考公告里下载《职位表》（Excel），在上面导入。</p></div>`}`;
    bind();
  }

  function bind() {
    el.querySelector("#prof").onsubmit = (e) => {
      e.preventDefault();
      Object.assign(prof, {
        edu: el.querySelector("#p-edu").value, politics: el.querySelector("#p-pol").value,
        years: +el.querySelector("#p-years").value || 0, project: el.querySelector("#p-proj").checked,
        majors: el.querySelector("#p-major").value.split(/[,，、\s]+/).filter(Boolean),
      });
      store.set("job_profile", prof);
      store.flushNow();
      toast("已保存条件");
      setTimeout(() => { st.page = 1; load(); }, 300);
    };
    el.querySelector("#pup").onclick = async () => {
      const f = el.querySelector("#pf").files[0];
      if (!f) return toast("先选择职位表文件");
      try {
        toast("正在导入，表大的话要十几秒…", 4000);
        const name = el.querySelector("#pname").value.trim();
        const r = await upload(`/api/positions/upload?file=${encodeURIComponent(f.name)}&name=${encodeURIComponent(name)}`, f);
        toast(`导入了 ${r.count} 个岗位`);
        st.batch = r.batch; st.page = 1;
        load();
      } catch (e) { toast(e.message, 5000); }
    };
    const aup = el.querySelector("#aup");
    if (aup) aup.onclick = async () => {
      const f = el.querySelector("#af").files[0];
      if (!f) return toast("先选择报名人数文件");
      try {
        const r = await upload(`/api/positions/applicants?batch=${st.batch}&file=${encodeURIComponent(f.name)}`, f);
        toast(`对上了 ${r.matched} 个岗位的报名人数`);
        load();
      } catch (e) { toast(e.message, 5000); }
    };
    const bsel = el.querySelector("#batch");
    if (bsel) bsel.onchange = () => { st.batch = +bsel.value; st.page = 1; load(); };
    const bdel = el.querySelector("#bdel");
    if (bdel) bdel.onclick = async () => {
      if (!bdel.dataset.armed) { bdel.dataset.armed = "1"; bdel.textContent = "确认删除"; return; }
      await apiPost("/api/positions/delete", { batch: st.batch });
      st.batch = null; load();
    };
    let t = null;
    const re = () => { clearTimeout(t); t = setTimeout(() => { st.page = 1; load(); }, 300); };
    const q = el.querySelector("#q");
    if (q) q.oninput = () => { st.q = q.value; re(); };
    const rg = el.querySelector("#region");
    if (rg) rg.oninput = () => { st.region = rg.value; re(); };
    const so = el.querySelector("#sort");
    if (so) so.onchange = () => { st.sort = so.value; st.page = 1; load(); };
    const mi = el.querySelector("#mine");
    if (mi) mi.onchange = () => { st.mine = mi.checked; st.page = 1; load(); };
    const of = el.querySelector("#ofav");
    if (of) of.onchange = () => { st.only_fav = of.checked; st.page = 1; load(); };
    const pv = el.querySelector("#prev"), nx = el.querySelector("#next");
    if (pv) pv.onclick = () => { st.page--; load(); };
    if (nx) nx.onclick = () => { st.page++; load(); };
    el.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => {
      const id = +b.dataset.open;
      open.has(id) ? open.delete(id) : open.add(id);
      draw();
    }));
    el.querySelectorAll("[data-fav]").forEach((b) => (b.onclick = () => {
      const id = b.dataset.fav;
      favs.has(id) ? favs.delete(id) : favs.add(id);
      store.set("job_favs", [...favs]);
      store.flushNow();
      draw();
    }));
  }

  await load();
  return () => {};
}
