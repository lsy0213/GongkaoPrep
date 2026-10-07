import { apiGet, apiPost, bankMeta, clearBankCache, esc, getAIStatus, saveFile, store, streamAI, toast, todayISO } from "../lib.js";

const SAMPLE = `{
  "materials": [
    {"id": "my-m1", "title": "资料标题", "text": "材料正文，支持 | 表格 | 写法"}
  ],
  "questions": [
    {
      "id": "my-001",
      "module": "言语理解与表达",
      "sub": "逻辑填空",
      "stem": "题干……",
      "options": ["选项A", "选项B", "选项C", "选项D"],
      "answer": 0,
      "explain": "解析（可选）"
    },
    {
      "id": "my-002", "module": "资料分析", "material": "my-m1",
      "stem": "……", "options": ["…", "…", "…", "…"], "answer": 2
    }
  ]
}`;

function readFile(input) {
  return new Promise((resolve, reject) => {
    const f = input.files[0];
    if (!f) return reject(new Error("请先选择文件"));
    const r = new FileReader();
    r.onload = () => { try { resolve(JSON.parse(r.result)); } catch { reject(new Error("文件不是有效的 JSON")); } };
    r.onerror = () => reject(new Error("读取文件失败"));
    r.readAsText(f, "utf-8");
  });
}

export async function render(el) {
  const [s, ai, presets, b, job] = await Promise.all([apiGet("/api/settings"), getAIStatus(true), apiGet("/api/ai/presets"), bankMeta(true), apiGet("/api/jobs")]);
  const aiPreset = presets[ai.provider] || presets.none;
  const c = b.counts, realCount = (c["国考"] || 0) + (c["四川"] || 0);
  const theme = store.get("theme", "system");

  el.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">设置</div><h1>设置</h1></div></div>
    <form class="card" id="basic">
      <div class="card-head"><h2>考试与计划</h2></div>
      <div class="grid cols-3">
        <label class="field">怎么称呼你<input type="text" id="nickname" value="${esc(s.nickname)}" placeholder="可不填"></label>
        <label class="field">国考笔试日期<input type="date" id="guokao_date" value="${esc(s.guokao_date)}"></label>
        <label class="field">省考笔试日期<input type="date" id="shengkao_date" value="${esc(s.shengkao_date)}"></label>
        <label class="field">开始备考日期<input type="date" id="start_date" value="${esc(s.start_date)}"></label>
        <label class="field">每天学习时长（小时）<input type="number" id="daily_hours" min="1" max="12" step="0.5" value="${esc(s.daily_hours)}"></label>
        <label class="field">国考卷别<select id="paper_level">${["地市级", "副省级"].map((x) => `<option ${x === s.paper_level ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      </div>
      <p class="small muted">默认日期是根据往年规律的预估：国考一般在 11 月底或 12 月初的周日；多省联考省考一般在 3 月中旬，江苏、浙江、上海、北京、广东、山东、四川、天津等单独命题的省份时间不同。公告发布后请改成准确日期。</p>
      <div class="row"><button class="btn primary" type="submit">保存</button></div>
    </form>

    <div class="card">
      <div class="card-head"><h2>外观</h2></div>
      <div class="seg" id="theme">${[["system", "跟随系统"], ["light", "浅色"], ["dark", "深色"]].map(([k, n]) => `<button data-t="${k}" class="${theme === k ? "active" : ""}">${n}</button>`).join("")}</div>
    </div>

    <form class="card" id="ai">
      <div class="card-head"><h2>AI 助教（可选）</h2>
        <span class="chip ${ai.configured ? "good" : "warn"}">${ai.configured ? "已启用" : ai.provider === "none" ? "未启用" : !ai.installed ? "未安装 anthropic" : "未配置完成"}</span></div>
      <p class="small ink2" style="margin-top:0">启用后可以让 AI 讲题、批改申论、点评面试、解答资料里的疑问。支持 DeepSeek、通义千问、Kimi、智谱、OpenAI、Claude，以及其他兼容 OpenAI 接口的服务，费用由你自己的 API 账户按用量支付。</p>
      <div class="grid cols-2">
        <label class="field">AI 服务商<select id="ai_provider">${Object.entries(presets).map(([k, v]) => `<option value="${k}" ${k === ai.provider ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select></label>
        <label class="field" data-ai-more>模型名称<input type="text" id="ai_model" value="${esc(ai.model)}" placeholder="如 deepseek-chat"></label>
        <label class="field" data-ai-more style="grid-column:1/-1">接口地址（Base URL）<input type="text" id="ai_base_url" value="${esc(s.ai_base_url || aiPreset.base_url)}" placeholder="https://…">
          <span class="small muted" id="ai-base-help"></span></label>
        <label class="field" data-ai-more style="grid-column:1/-1">API Key<input type="password" id="ai_api_key" autocomplete="off"
          placeholder="${s.ai_key_saved ? `已保存（${esc(s.ai_key_hint)}），留空表示不修改` : "粘贴你的 API Key"}"></label>
      </div>
      ${ai.installed ? "" : `<p class="small" style="color:var(--warn)">使用 Claude 需要先在命令行运行 <code>pip install anthropic</code>，然后重启软件。</p>`}
      <div class="row mt"><button class="btn primary" type="submit">保存 AI 设置</button>
        <button class="btn" type="button" id="ai-test" data-ai-more>测试连接</button>
        ${s.ai_key_saved ? `<button class="btn ghost danger" type="button" id="clear-key">清除已保存的 Key</button>` : ""}</div>
      <div id="ai-test-res"></div>
      <p class="small muted">Key 只保存在本机的 <code>%APPDATA%\\GongkaoPrep\\app.db</code> 里，界面上只显示掩码，导出备份时也不会包含。</p>
      <details class="small muted"><summary style="cursor:pointer">怎么获取 API Key？</summary>
        <ul style="line-height:1.9">
          <li><b>DeepSeek</b>：platform.deepseek.com → API Keys（便宜、中文好，推荐）</li>
          <li><b>通义千问</b>：阿里云百炼控制台 bailian.console.aliyun.com → API-KEY</li>
          <li><b>Kimi</b>：platform.moonshot.cn → API Key 管理</li>
          <li><b>智谱 GLM</b>：open.bigmodel.cn → API Keys（glm-4-flash 有免费额度）</li>
          <li><b>Claude</b>：console.anthropic.com → API Keys（需海外网络；接口地址留空即可，用中转服务时填中转地址）</li>
          <li>其他兼容 OpenAI 接口的服务选「自定义」，填接口地址和模型名。</li>
        </ul>
        <p>模型名称可以改成服务商提供的其他模型；各家模型名会更新，以服务商文档为准。申论批改要把整份材料发给 AI，建议选上下文较长的模型。</p></details>
    </form>

    <form class="card" id="lib">
      <div class="card-head"><h2>资料文件夹</h2>
        <span class="chip ${realCount ? "good" : "warn"}">${realCount ? `已整理真题 ${b.papers.length} 套${b.books.length ? `、题册 ${c["千题册"]} 题` : ""}` : "尚未整理"}</span></div>
      <p class="small ink2" style="margin-top:0">把真题、讲义、题册放在一个文件夹里（可以有子文件夹）。软件只读取、不会修改或移动这些文件；整理出的题库、全文索引和截图缓存保存在 <code>%APPDATA%\\GongkaoPrep\\library</code>。</p>
      <label class="field">文件夹路径<input type="text" id="library_root" value="${esc(s.library_root)}" placeholder="例如 E:\\资料\\公考"></label>
      <div class="row mt"><button class="btn primary" type="submit">保存</button>
        <button class="btn" type="button" data-job="all" ${job.running ? "disabled" : ""}>整理全部资料</button>
        <button class="btn ghost" type="button" data-job="real" ${job.running ? "disabled" : ""} title="重新识别真题和答案">只重建真题题库</button>
        <button class="btn ghost" type="button" data-job="books" ${job.running ? "disabled" : ""} title="识别千题册、5000题（扫描版需要 OCR）">只识别题册</button>
        <button class="btn ghost" type="button" data-job="index" ${job.running ? "disabled" : ""} title="重新提取 PDF 文字供搜索">只重建全文索引</button>
        <span class="small muted">${job.running ? `正在${esc(job.name)}：${esc(job.step)} ${job.done}/${job.total}` : job.finished_at ? `上次整理完成于 ${esc(job.finished_at)}` : ""}</span></div>
      <p class="small muted">新增资料后点“整理全部资料”，只会处理新增或改动过的文件。整理进度可以在“资料库”页查看。</p>
    </form>

    <div class="card">
      <div class="card-head"><h2>题库</h2><span class="small muted">内置 ${c["内置"] || 0} 题 · 真题卷 ${realCount} 题 · 题册 ${c["千题册"] || 0} 题 · 导入 ${b.custom_count} 题</span></div>
      <p class="small ink2" style="margin-top:0">可以把自己整理的真题或练习题按下面的格式存成 JSON 文件导入。module 必须是：政治理论、常识判断、言语理解与表达、数量关系、判断推理、资料分析；answer 用 0–3 表示 A–D。</p>
      <details><summary class="small" style="cursor:pointer">查看题目文件格式</summary><pre class="ref small" style="overflow-x:auto">${esc(SAMPLE)}</pre></details>
      <div class="row mt"><input type="file" id="bank-file" accept=".json,application/json" style="max-width:280px">
        <button class="btn" id="bank-import">导入题目</button>
        ${b.custom_count ? `<button class="btn ghost danger" id="bank-clear">删除全部导入的题目</button>` : ""}</div>
    </div>

    <div class="card">
      <div class="card-head"><h2>数据备份</h2></div>
      <p class="small ink2" style="margin-top:0">所有学习记录保存在 <code>%APPDATA%\\GongkaoPrep\\app.db</code>，升级或重新打包软件都不会丢失。建议每周导出一次备份，换电脑时导入即可恢复。</p>
      <div class="row"><button class="btn" id="export">导出备份</button>
        <input type="file" id="restore-file" accept=".json,application/json" style="max-width:280px">
        <button class="btn" id="restore">从备份恢复</button></div>
      <p class="small muted">恢复会覆盖当前的学习记录（AI Key 除外）。</p>
    </div>`;

  el.querySelector("#basic").onsubmit = async (e) => {
    e.preventDefault();
    const body = {};
    for (const k of ["nickname", "guokao_date", "shengkao_date", "start_date", "daily_hours", "paper_level"]) body[k] = el.querySelector("#" + k).value;
    await apiPost("/api/settings", body);
    toast("已保存，复习计划已按新设置调整");
  };
  el.querySelector("#lib").onsubmit = async (e) => {
    e.preventDefault();
    await apiPost("/api/settings", { library_root: el.querySelector("#library_root").value.trim() });
    toast("已保存资料文件夹，点“整理全部资料”开始整理");
  };
  el.querySelectorAll("[data-job]").forEach((x) => (x.onclick = async () => {
    try {
      await apiPost("/api/settings", { library_root: el.querySelector("#library_root").value.trim() });
      await apiPost("/api/jobs/start", { job: x.dataset.job });
      toast("已开始，在资料库页可以看到进度");
      location.hash = "#/library";
    } catch (err) { toast(err.message, 4000); }
  }));
  el.querySelectorAll("#theme button").forEach((x) => (x.onclick = () => {
    store.set("theme", x.dataset.t);
    applyTheme();
    el.querySelectorAll("#theme button").forEach((y) => y.classList.toggle("active", y === x));
  }));
  const aiForm = el.querySelector("#ai");
  const prov = aiForm.querySelector("#ai_provider"), model = aiForm.querySelector("#ai_model"), base = aiForm.querySelector("#ai_base_url");
  const syncAI = () => {
    const pr = presets[prov.value];
    aiForm.querySelectorAll("[data-ai-more]").forEach((f) => (f.hidden = pr.type === "none"));
    aiForm.querySelector("#ai-base-help").textContent = pr.type === "anthropic"
      ? "官方接口留空即可；使用中转服务时填写中转地址。Key 也可以不填，改为设置环境变量 ANTHROPIC_API_KEY。" : "";
  };
  prov.onchange = () => {
    const pr = presets[prov.value];
    base.value = pr.base_url;
    model.value = pr.model;
    aiForm.querySelector("#ai-test-res").innerHTML = "";
    syncAI();
  };
  syncAI();
  const saveAI = () => apiPost("/api/settings", {
    ai_provider: prov.value, ai_model: model.value.trim(), ai_base_url: base.value.trim(),
    ai_api_key: aiForm.querySelector("#ai_api_key").value.trim(),
  });
  aiForm.onsubmit = async (e) => {
    e.preventDefault();
    await saveAI();
    const st = await getAIStatus(true);
    toast(st.configured ? "已保存，AI 助教已启用" : prov.value === "none" ? "已保存，AI 助教已关闭" : "已保存，但还没配置完成：" + st.problem, 4000);
    render(el);
  };
  aiForm.querySelector("#ai-test").onclick = async (e) => {
    const btn = e.currentTarget, res = aiForm.querySelector("#ai-test-res");
    btn.disabled = true;
    res.innerHTML = `<div class="ai-box">正在连接…</div>`;
    try {
      await saveAI();
      aiForm.querySelector("#ai_api_key").value = "";
      await getAIStatus(true);
      const text = await streamAI("test", {}, () => {});
      if (text.includes("[AI 出错]")) throw new Error(text.split("[AI 出错]").pop().trim());
      res.innerHTML = `<div class="ai-box" style="border-color:var(--good);background:var(--good-soft)">✅ 连接成功，设置已保存。AI 回复：${esc(text.trim().slice(0, 100))}</div>`;
    } catch (err) {
      res.innerHTML = `<div class="ai-box" style="border-color:var(--bad);background:var(--bad-soft);white-space:pre-wrap">连接失败：${esc(err.message)}</div>`;
    } finally {
      btn.disabled = false;
    }
  };
  const ck = el.querySelector("#clear-key");
  if (ck) ck.onclick = async () => { await apiPost("/api/settings", { ai_clear_key: true }); await getAIStatus(true); toast("已清除"); render(el); };

  el.querySelector("#bank-import").onclick = async () => {
    try {
      const data = await readFile(el.querySelector("#bank-file"));
      const r = await apiPost("/api/bank/import", data);
      clearBankCache();
      toast(`导入成功：${r.imported} 题`);
      render(el);
    } catch (e) { toast(e.message, 5000); }
  };
  const bc = el.querySelector("#bank-clear");
  if (bc) bc.onclick = async () => {
    if (!bc.dataset.armed) { bc.dataset.armed = "1"; bc.textContent = "确认删除导入的题目"; return; }
    await apiPost("/api/bank/clear");
    clearBankCache();
    toast("已删除导入的题目");
    render(el);
  };
  el.querySelector("#export").onclick = async () => {
    const data = await apiGet("/api/export");
    const where = await saveFile(`上岸备考-备份-${todayISO()}.json`, JSON.stringify(data, null, 1));
    if (where) toast("备份已保存：" + where, 4000);
  };
  el.querySelector("#restore").onclick = async (e) => {
    const btn = e.currentTarget;
    try {
      const data = await readFile(el.querySelector("#restore-file"));
      if (data.app !== "gongkao-prep") throw new Error("这不是本软件导出的备份文件");
      if (!btn.dataset.armed) { btn.dataset.armed = "1"; btn.textContent = "确认覆盖当前记录"; return; }
      await apiPost("/api/import", data);
      toast("已从备份恢复");
      render(el);
    } catch (err) { toast(err.message, 4000); }
  };
}

export function applyTheme() {
  const t = store.get("theme", "system");
  if (t === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
}
