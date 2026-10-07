import { apiGet, apiPost, esc, getAIStatus, streamAI, toast } from "../lib.js";

const PROMPTS = [
  "我是零基础，帮我解释一下行测资料分析里“增长量”和“增长率”的区别，并各举一个例子。",
  "逻辑判断里“只有……才……”和“如果……那么……”怎么翻译？给我出 3 道练习题。",
  "申论归纳概括题怎么从材料里找要点？请给我一个具体的操作步骤。",
  "我每天只有 3 小时，离国考还有不到两个月，帮我排一个每周的学习安排。",
  "结构化面试的综合分析题，怎样在 1 分钟内列好提纲？",
  "给我 5 个近两年申论常考的主题，每个主题给出一个可用的大作文标题和三个分论点。",
];

export async function render(el) {
  const status = await getAIStatus(true);
  let history = (await apiGet("/api/chats")).items;
  let abort = null;
  const ready = status.installed && status.configured;

  function draw(streaming = "") {
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">AI 助教</div><h1>随时问，讲到懂为止</h1>
        <p>可以问题目、方法、计划安排。做题页、申论页和面试页里也能直接请 AI 讲解、批改和点评。</p></div>
        ${history.length ? `<button class="btn ghost" id="clear">清空对话</button>` : ""}</div>
      ${ready ? "" : `<div class="card mb" style="border-color:var(--warn)">
        <h3 class="mb">AI 助教还没有启用</h3>
        <ol class="ink2" style="margin:0;padding-left:1.3em;line-height:2">
          ${status.installed ? "" : `<li>在命令行运行 <code>pip install anthropic</code>，然后重新启动本软件</li>`}
          ${status.configured ? "" : `<li>到 <a href="#/settings">设置 → AI 助教</a> 选择服务商（DeepSeek、通义千问、Claude 等）并填写 API Key</li>`}
        </ol>
        <p class="small muted" style="margin-bottom:0">AI 功能按调用量计费，费用由你的 API 账户承担。不启用 AI，其他所有功能都能正常使用。</p></div>`}
      <div class="card">
        <div class="chat" id="chat">
          ${history.length || streaming ? history.map((m) => `<div class="msg ${m.role}">${esc(m.content)}</div>`).join("") : `<div class="empty"><h3>可以这样问</h3></div>
            <div class="pick">${PROMPTS.map((p, i) => `<button data-p="${i}" style="max-width:100%;min-width:0">${esc(p)}</button>`).join("")}</div>`}
          ${streaming ? `<div class="msg assistant" id="live">${esc(streaming)}</div>` : ""}
        </div>
        <form class="row mt" id="ask" style="align-items:flex-end">
          <textarea id="msg" rows="3" style="flex:1;min-width:200px" placeholder="输入你的问题，Ctrl + Enter 发送" ${ready ? "" : "disabled"}></textarea>
          <div class="stack" style="gap:6px"><button class="btn primary" type="submit" id="send" ${ready ? "" : "disabled"}>发送</button>
            <button class="btn" type="button" id="stop" hidden>停止</button></div>
        </form>
        <p class="small muted" style="margin-bottom:0">当前：${esc(status.provider_name || "")} · ${esc(status.model || "")}。AI 的回答可能有错，涉及考试安排和最新政策时请以官方发布为准。</p>
      </div>`;
    bind();
  }

  async function send(text) {
    if (!text.trim()) return;
    history.push({ role: "user", content: text });
    draw("AI 正在思考……");
    const live = () => el.querySelector("#live");
    el.querySelector("#send").disabled = true;
    el.querySelector("#stop").hidden = false;
    abort = new AbortController();
    el.querySelector("#stop").onclick = () => abort.abort();
    live()?.scrollIntoView({ block: "end" });
    try {
      const out = await streamAI("chat", { message: text }, (t) => { const l = live(); if (l) l.textContent = t; }, abort.signal);
      history.push({ role: "assistant", content: out });
    } catch (e) {
      history.push({ role: "assistant", content: e.name === "AbortError" ? "（已停止）" : "出错了：" + e.message });
    }
    draw();
    el.querySelector("#chat").lastElementChild?.scrollIntoView({ block: "end" });
  }

  function bind() {
    const form = el.querySelector("#ask"), box = el.querySelector("#msg");
    form.onsubmit = (e) => { e.preventDefault(); const t = box.value; box.value = ""; send(t); };
    box.onkeydown = (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) form.requestSubmit(); };
    el.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => {
      if (!ready) { toast("请先在设置里启用 AI 助教"); return; }
      send(PROMPTS[+b.dataset.p]);
    }));
    const c = el.querySelector("#clear");
    if (c) c.onclick = async () => {
      if (!c.dataset.armed) { c.dataset.armed = "1"; c.textContent = "确认清空"; return; }
      await apiPost("/api/chats/clear");
      history = [];
      draw();
    };
  }

  draw();
  return () => abort?.abort();
}
